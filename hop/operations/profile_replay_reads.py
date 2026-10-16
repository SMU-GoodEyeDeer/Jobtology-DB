#!/usr/bin/env python3
"""Bounded first-backend/date and proof replay measurements on a supplied archive.

A network-disabled owned PostgreSQL restores unchanged local evidence. Independent
as-restored and explicitly ANALYZEd databases keep data/migrations matched. New
backends are distinguished from reused backends; host/OS caches are not flushed.
Plans/raw SQL are protected evidence, never repository artifacts.
"""
# Exact fixture SQL is kept readable.
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark_first_capture import (
    absent_proofs,
    capture,
    digest,
    preserved,
    proof_state,
    statistic_identity,
)
from profile_archived_postgres import (
    STATE,
    Session,
    SqlFailure,
    analyze_ingestion,
    docker,
    plan_summary,
    quote,
    safe_runs,
    statistics,
    write_json,
)

BASELINE = (
    'docs/hop-migration/checks.sql', 'docs/hop-migration/operations.sql',
    'hop/graph/sql/001_posting_ingestion_dates.sql',
    'hop/graph/sql/002_batchfree_source_graph.sql',
    'hop/graph/sql/003_source_query_sharing.sql',
)
SOURCES = ('jobkorea', 'nara_job', 'job_alio', 'alio_organization')


def explain(session: Session, query: str, sample: dict[str, Any]) -> None:
    tick = time.monotonic()
    try:
        value = session.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ' + query,
                                allow_timeout=True)
        sample.update(result='PASSED', plan=plan_summary(json.loads(value)[0]))
    except SqlFailure as error:
        sample.update(result='TIMED_OUT' if error.sqlstate == '57014' else 'FAILED',
                      sqlstate=error.sqlstate)
        if error.sqlstate != '57014':
            raise
    finally:
        sample['client_wall_seconds'] = time.monotonic() - tick


def choose_scopes(session: Session) -> list[dict[str, Any]]:
    return json.loads(session.execute(
        "SELECT jsonb_agg(to_jsonb(s) ORDER BY source_id) FROM (SELECT DISTINCT ON(u.source_id) "
        "u.source_id,u.run_id,count(r.*) records FROM ingestion.run u "
        "JOIN ingestion.record r USING(run_id) JOIN ingestion.source_graph_projection p "
        "ON p.run_id=u.run_id WHERE u.state='READY' AND u.mode<>'SMOKE' AND p.state='READY' "
        "AND u.source_id IN (" + ','.join(map(quote, SOURCES)) + ") "
        "GROUP BY u.source_id,u.run_id ORDER BY u.source_id,count(r.*) DESC,u.run_id)s"))


def date_state(session: Session, runs: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for run_id in runs:
        result[run_id] = json.loads(session.execute(
            "SELECT jsonb_build_object('rows',count(*),'sha256',encode(sha256(convert_to("
            "coalesce(string_agg(h,'' ORDER BY h),''),'UTF8')),'hex')) FROM (SELECT "
            "encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') h FROM "
            "ingestion.graph_posting_ingestion_dates(" + quote(run_id) + ")t)s",
            allow_timeout=True))
    return result


def direct_replay(session: Session, run_id: str, sample: dict[str, Any]) -> None:
    # Both variants start from the same immutable proof and projection state.
    # EXPLAIN executes the real guarded write, then rollback removes its effects.
    session.execute('BEGIN')
    try:
        explain(session, 'SELECT ingestion.begin_source_graph_projection(' + quote(run_id) + ')',
                sample)
    finally:
        session.execute('ROLLBACK', allow_timeout=True)


def replay_oracle(session: Session, run_id: str) -> list[str]:
    """Independent mutations in rollback-only transactions; small real scope."""
    key = quote(run_id)
    checks: list[str] = []
    for state in ('READY', 'FAILED', 'LOADING'):
        session.execute('BEGIN')
        try:
            session.execute("UPDATE ingestion.source_graph_projection SET state=" + quote(state)
                            + ",verified_at=" + ("clock_timestamp()" if state == 'READY' else 'NULL')
                            + ',error_code=NULL WHERE run_id=' + key)
            if session.execute('SELECT ingestion.begin_source_graph_projection(' + key + ')') != 't':
                raise RuntimeError('Valid state replay failed')
            if session.execute('SELECT ingestion.finish_source_graph_projection(' + key + ')') != 't':
                raise RuntimeError('Valid state finish failed')
            checks.append('complete-proof-' + state)
        finally:
            session.execute('ROLLBACK', allow_timeout=True)
    for label, mutation in (
        ('absent', 'DELETE FROM ingestion.source_graph_projection WHERE run_id=' + key + '; '
         'DELETE FROM ingestion.source_graph_record_evidence WHERE run_id=' + key + '; '
         'DELETE FROM ingestion.source_graph_membership WHERE run_id=' + key),
        ('partial-record', 'DELETE FROM ingestion.source_graph_record_evidence WHERE (run_id,record_id)'
         ' IN (SELECT run_id,record_id FROM ingestion.source_graph_record_evidence WHERE run_id='
         + key + ' LIMIT 1)'),
        ('partial-member', 'DELETE FROM ingestion.source_graph_membership WHERE '
         '(run_id,record_id,identity_id,field) IN (SELECT run_id,record_id,identity_id,field FROM '
         'ingestion.source_graph_membership WHERE run_id=' + key + ' LIMIT 1)'),
    ):
        before = proof_state(session, [run_id])
        session.execute('BEGIN; SET LOCAL session_replication_role=replica; ' + mutation
                        + '; SET LOCAL session_replication_role=origin')
        try:
            session.execute('SELECT ingestion.begin_source_graph_projection(' + key + ')')
            session.execute('SELECT ingestion.finish_source_graph_projection(' + key + ')')
            if proof_state(session, [run_id]) != before:
                raise RuntimeError('Exact first/partial capture recovery differs')
            checks.append('recovered-' + label)
        finally:
            session.execute('ROLLBACK', allow_timeout=True)
    for label, mutation, expected in (
        ('wrong-record', "UPDATE ingestion.source_graph_record_evidence SET facts_sha256=repeat('b',64)"
         ' WHERE (run_id,record_id) IN (SELECT run_id,record_id FROM '
         'ingestion.source_graph_record_evidence WHERE run_id=' + key + ' LIMIT 1)',
         'SOURCE_GRAPH_EVIDENCE_MISMATCH'),
        ('wrong-member', "UPDATE ingestion.source_graph_membership SET code=code||'-tampered' "
         'WHERE (run_id,record_id,identity_id,field) IN (SELECT run_id,record_id,identity_id,field '
         'FROM ingestion.source_graph_membership WHERE run_id=' + key + ' LIMIT 1)',
         'SOURCE_GRAPH_EVIDENCE_MISMATCH'),
        ('wrong-live-content', "UPDATE ingestion.record SET normalized=normalized||"
         "'{\"unproven_replay_fixture\":true}' WHERE run_id=" + key,
         'SOURCE_GRAPH_LIVE_CONTENT_MISMATCH'),
        ('archived-run', 'DELETE FROM ingestion.run WHERE run_id=' + key,
         'SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN'),
        ('loading-run', "UPDATE ingestion.run SET state='LOADING' WHERE run_id=" + key,
         'SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN'),
    ):
        session.execute('BEGIN; SET LOCAL session_replication_role=replica; ' + mutation
                        + '; SET LOCAL session_replication_role=origin')
        try:
            session.execute('DO $test$ DECLARE refused boolean:=false; BEGIN BEGIN PERFORM '
                            'ingestion.begin_source_graph_projection(' + key + '); EXCEPTION '
                            'WHEN OTHERS THEN IF SQLERRM=' + quote(expected) + ' THEN refused:=true; '
                            'ELSE RAISE; END IF; END; IF NOT refused THEN RAISE EXCEPTION '
                            "'REPLAY_NEGATIVE_ACCEPTED'; END IF; END $test$")
            checks.append('refused-' + label)
        finally:
            session.execute('ROLLBACK', allow_timeout=True)
    # An ACTIVE retention plan must still reject the fast-path UPDATE.
    session.execute("BEGIN; INSERT INTO retention.plan(plan_id,source_id,selection_mode,amount,"
                    "keep_latest,raw_base,state,owner_id) VALUES('fixture-replay-active','alio_organization',"
                    "'fixture',1,1,'/fixture','ACTIVE','unowned-fixture')")
    try:
        session.execute('DO $test$ DECLARE refused boolean:=false; BEGIN BEGIN PERFORM '
                        'ingestion.begin_source_graph_projection(' + key + '); EXCEPTION '
                        "WHEN OTHERS THEN IF SQLERRM LIKE 'RETENTION_ACTIVE:%' THEN refused:=true; "
                        'ELSE RAISE; END IF; END; IF NOT refused THEN RAISE EXCEPTION '
                        "'REPLAY_RETENTION_ACCEPTED'; END IF; END $test$")
        checks.append('retention-fence-retained')
    finally:
        session.execute('ROLLBACK', allow_timeout=True)
    return checks


def first_capture_clone(container: str, directory: Path, scopes: list[dict[str, Any]]) -> Path:
    """Fresh selected proof state in a clone, preserving actual source/history."""
    path = directory / 'first-capture-four-scopes.json'
    database = 'reads_first_capture'
    runs = safe_runs([s['run_id'] for s in scopes])
    keys = ','.join(map(quote, runs))
    evidence: dict[str, Any] = dict(
        status='RUNNING', container=container, database=database, scopes=scopes,
        statement_timeout_seconds=180, source_requests=0, paid_requests=0, production_writes=0,
        limitations=['Selected proof rows are removed only in an owned template clone during '
                     'untimed setup; original supplied source/history/frozen rows are preserved.',
                     'One four-scope atomic first capture; no new transaction-shape speed claim.',
                     'Data already read and explicitly analyzed; this is not a cold-read test.',
                     'Previous matched two-scope atomic/per-run receipt remains separate.'])
    write_json(path, evidence)
    session = None
    try:
        docker(['exec', container, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U',
                'postgres', '-d', 'postgres', '-c',
                'CREATE DATABASE ' + database + ' TEMPLATE reads_analyzed'], directory,
               'clone-first-capture')
        part = directory / 'first-capture-four-scopes'
        part.mkdir(mode=0o700)
        session = Session(container, part, 180, database=database)
        original = proof_state(session, runs)
        before = preserved(session, runs)
        other_runs = json.loads(session.execute(
            "SELECT jsonb_agg(run_id ORDER BY run_id) FROM ingestion.source_graph_projection "
            "WHERE run_id NOT IN (" + keys + ")"))
        others_before = proof_state(session, other_runs)
        evidence.update(original_selected_proofs=original, source_before=before,
                        unselected_proofs_before=others_before,
                        statistic_identity=statistic_identity(session))
        session.execute('BEGIN; SET LOCAL session_replication_role=replica; '
                        'DELETE FROM ingestion.source_graph_membership WHERE run_id IN (' + keys + '); '
                        'DELETE FROM ingestion.source_graph_record_evidence WHERE run_id IN (' + keys
                        + '); DELETE FROM ingestion.source_graph_projection WHERE run_id IN (' + keys
                        + '); COMMIT')
        absent_proofs(session, runs)
        evidence['selected_proofs_before_capture'] = proof_state(session, runs)
        write_json(path, evidence)
        sample: dict[str, Any] = {}
        evidence['sample'] = sample
        capture(session, runs, 'atomic', sample)
        captured = proof_state(session, runs)
        if captured != original:
            raise RuntimeError('First capture differs from immutable original archived proof')
        if preserved(session, runs) != before or proof_state(session, other_runs) != others_before:
            raise RuntimeError('First capture changed preserved source/history/unselected proofs')
        for run_id in runs:
            matched = session.execute('SELECT to_jsonb(a)=to_jsonb(b) FROM '
                'ingestion.source_graph_manifest(' + quote(run_id) + ',false)a CROSS JOIN '
                'ingestion.source_graph_manifest(' + quote(run_id) + ',true)b')
            if matched != 't':
                raise RuntimeError('Fresh captured manifest differs from actual live source')
        evidence.update(status='PASSED_FOUR_SCOPE_FIRST_CAPTURE', selected_proofs_after=captured)
    except BaseException as error:
        evidence.update(status='FAILED', failure_type=type(error).__name__)
        raise
    finally:
        if session is not None:
            session.close()
        docker(['exec', container, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U',
                'postgres', '-d', 'postgres', '-c',
                'DROP DATABASE IF EXISTS ' + database + ' WITH (FORCE)'], directory,
               'drop-first-capture')
        evidence.update(database_removed=True, finished_at=datetime.now(UTC).isoformat())
        write_json(path, evidence)
    return path


def replay_install_and_lock_oracle(session: Session, container: str, directory: Path,
                                  database: str, run_id: str, candidate: str) -> list[str]:
    guard = re.search(r'DO \$guard\$[\s\S]*?END \$guard\$;', candidate)
    if guard is None:
        raise RuntimeError('Candidate installation drift guard is missing')
    session.execute('BEGIN; CREATE OR REPLACE FUNCTION ingestion.begin_source_graph_projection('
                    "jobs text) RETURNS boolean LANGUAGE plpgsql SET jit=off AS $$BEGIN RETURN true; END$$")
    try:
        session.execute('DO $test$ DECLARE refused boolean:=false; BEGIN BEGIN EXECUTE '
                        + quote(guard[0]) + '; EXCEPTION WHEN OTHERS THEN IF SQLERRM='
                        "'SOURCE_GRAPH_REPLAY_CANONICAL_DRIFT' THEN refused:=true; ELSE RAISE; "
                        "END IF; END; IF NOT refused THEN RAISE EXCEPTION 'DRIFT_ACCEPTED'; "
                        'END IF; END $test$')
    finally:
        session.execute('ROLLBACK', allow_timeout=True)
    part = directory / 'concurrent-replay-lock'
    part.mkdir(mode=0o700)
    other = Session(container, part, 10, database=database)
    try:
        other.execute("SET lock_timeout='1s'; BEGIN")
        session.execute('BEGIN; SELECT run_id FROM ingestion.source_graph_projection WHERE run_id='
                        + quote(run_id) + ' FOR UPDATE')
        try:
            other.execute('SELECT ingestion.begin_source_graph_projection(' + quote(run_id) + ')',
                          allow_timeout=True)
        except SqlFailure as error:
            if error.sqlstate != '55P03':
                raise
        else:
            raise RuntimeError('Concurrent complete replay bypassed owned proof row lock')
        finally:
            other.execute('ROLLBACK', allow_timeout=True)
            session.execute('ROLLBACK', allow_timeout=True)
    finally:
        other.close()
    part = directory / 'concurrent-retention-gate'
    part.mkdir(mode=0o700)
    other = Session(container, part, 10, database=database)
    try:
        session.execute('BEGIN; SELECT retention.gate()')
        other.execute("SET lock_timeout='1s'; BEGIN")
        try:
            other.execute('SELECT ingestion.begin_source_graph_projection(' + quote(run_id) + ')',
                          allow_timeout=True)
        except SqlFailure as error:
            if error.sqlstate != '55P03':
                raise
        else:
            raise RuntimeError('Complete replay bypassed retention gate')
        finally:
            other.execute('ROLLBACK', allow_timeout=True)
            session.execute('ROLLBACK', allow_timeout=True)
        session.execute('BEGIN; SELECT retention.gate(); SET LOCAL session_replication_role=replica; '
                        'DELETE FROM ingestion.run WHERE run_id=' + quote(run_id))
        try:
            session.execute('SELECT ingestion.begin_source_graph_projection(' + quote(run_id) + ')',
                            allow_timeout=True)
        except SqlFailure as error:
            if error.sqlstate != 'P0001':
                raise
        else:
            raise RuntimeError('Archived proof accepted as live replay after retention gate')
        finally:
            session.execute('ROLLBACK', allow_timeout=True)
    finally:
        other.close()
    return ['unknown-install-definition-drift-refused', 'concurrent-proof-row-lock-retained',
            'concurrent-retention-gate-retained', 'archived-live-absence-after-gate-refused']


def run(args: argparse.Namespace, *, existing_fixture: Any = None) -> Path:
    os.umask(0o077)
    backup = args.backup.resolve(strict=True)
    if digest(backup) != args.backup_sha256:
        raise ValueError('Supplied archive SHA256 differs')
    directory = STATE / ('replay-reads-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    path = directory / 'receipt.json'
    token = uuid.uuid4().hex[:16]
    container = 'jobtology-replay-reads-' + token
    if existing_fixture is not None:
        container = existing_fixture.pg
    receipt: dict[str, Any] = dict(
        status='RUNNING', created_at=datetime.now(UTC).isoformat(), container=container,
        backup=str(backup), backup_sha256=args.backup_sha256, samples=[], sql_sha256={},
        source_requests=0, paid_requests=0, production_writes=0,
        statement_timeout_seconds=args.timeout_seconds,
        limits=[
            'First backend/physical database reads after local restore, not host-cold reads.',
            'Restore and SQL installation can warm OS buffers; no cache flushing.',
            'EXPLAIN ANALYZE adds instrumentation; server execution and client wall are separate.',
            'Custom/generic comparisons force only session-local plan_cache_mode.',
            'FunctionScan outer plans do not expose nested SPI plans or prove a root cause.',
            'Four representative largest archived source scopes, not all historical 86 runs.',
            'Direct replay runs rollback; native Hop/Neo4j is separately measured.',
        ],
    )
    write_json(path, receipt)
    if existing_fixture is not None:
        existing_fixture.receipt['first_read_receipt'] = str(path)
    session = None
    try:
        if existing_fixture is None:
            docker(['run', '--pull', 'never', '-d', '--name', container, '--network', 'none',
                    '--label', 'jobtology.replay-reads=' + token, '--memory', '4g', '--cpus', '2',
                    '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_DB=jobtology',
                    'postgres:18-alpine', '-c', 'autovacuum=off'], directory, 'boot')
        else:
            receipt['owned_shared_fixture'] = str(existing_fixture.work)
            receipt['limits'].append('Shared owned internal-network PG/Neo4j/Hop fixture; '
                                     'Neo4j/Hop remain idle during SQL timing.')
        info = json.loads(subprocess.check_output(['docker', 'inspect', container], timeout=30))[0]
        receipt.update(image_id=info['Image'], owned_volumes=[
            m['Name'] for m in info['Mounts'] if m['Type'] == 'volume'])
        for _ in range(60):
            if subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'postgres'],
                              capture_output=True, timeout=10).returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Owned PostgreSQL failed to start')
        tick = time.monotonic()
        with backup.open('rb') as source:
            docker(['exec', '-i', container, 'pg_restore', '--no-owner', '--no-privileges',
                    '--exit-on-error', '-U', 'postgres', '-d', 'jobtology'], directory,
                   'restore', source=source, timeout=360)
        receipt['restore_seconds'] = time.monotonic() - tick
        if existing_fixture is not None:
            existing_fixture.receipt['restore_seconds'] = receipt['restore_seconds']
            existing_fixture.receipt['first_read_receipt'] = str(path)
        session = Session(container, directory, args.timeout_seconds)
        frozen = directory / 'sql'
        frozen.mkdir(mode=0o700)
        manifest = json.loads((args.baseline_dir / 'manifest.json').read_text())
        for index, relative in enumerate(BASELINE):
            source = args.baseline_dir / relative
            if digest(source) != manifest[relative]:
                raise ValueError('Sealed deployed baseline changed')
            target = frozen / (str(index) + '-' + source.name)
            shutil.copyfile(source, target)
            receipt['sql_sha256'][relative] = digest(target)
            session.execute(target.read_text())
        candidate = frozen / args.candidate_sql.name
        shutil.copyfile(args.candidate_sql, candidate)
        receipt['candidate_sql_sha256'] = {
            'graph/sql/004_verified_proof_replay.sql': digest(candidate)}
        original = session.execute(
            "SELECT pg_get_functiondef("
            "'ingestion.begin_source_graph_projection(text)'::regprocedure)")
        (frozen / 'original-begin.sql').write_text(original)
        scopes = choose_scopes(session)
        if {s['source_id'] for s in scopes} != set(SOURCES):
            raise RuntimeError('All four realistic archived source scopes are required')
        runs = safe_runs([s['run_id'] for s in scopes])
        receipt['scopes'] = scopes
        # Statistics capture reads catalogues only. Date/source fingerprint reads
        # occur AFTER each physical database's first measured date calls.
        receipt['as_restored_statistics'] = statistics(session)
        session.close()
        session = None
        for database in ('reads_restored', 'reads_analyzed'):
            docker(['exec', container, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
                    '-U', 'postgres', '-d', 'postgres', '-c',
                    'CREATE DATABASE ' + database + ' TEMPLATE jobtology'], directory,
                   'clone-' + database)
        part = directory / 'analyze'
        part.mkdir(mode=0o700)
        session = Session(container, part, args.timeout_seconds, database='reads_analyzed')
        tick = time.monotonic()
        analyze_ingestion(session)
        receipt.update(analyze_seconds=time.monotonic() - tick,
                       analyzed_statistics=statistics(session))
        session.close()
        session = None
        first_input = first_dates = first_proofs = None
        for state, database in (('as-restored', 'reads_restored'), ('analyzed', 'reads_analyzed')):
            for scope in scopes:
                part = directory / (state + '-' + scope['source_id'])
                part.mkdir(mode=0o700)
                session = Session(container, part, args.timeout_seconds, database=database)
                for repeat in range(2):
                    sample = dict(statistics=state, operation='dates', run_id=scope['run_id'],
                                  backend='fresh' if repeat == 0 else 'reused', repeat=repeat,
                                  result='RUNNING')
                    receipt['samples'].append(sample)
                    write_json(path, receipt)
                    explain(session, 'SELECT count(*) FROM ingestion.graph_posting_ingestion_dates('
                            + quote(scope['run_id']) + ')', sample)
                    write_json(path, receipt)
                    if sample['result'] == 'TIMED_OUT':
                        break
                session.close()
                session = None
            for mode in ('force_custom_plan', 'force_generic_plan'):
                if any(s['operation'] == 'dates' and s['statistics'] == state
                       and s['run_id'].startswith('jobkorea-') and s['result'] == 'TIMED_OUT'
                       for s in receipt['samples']):
                    receipt[state + '_prepared_skipped'] = 'Same date scope already timed out'
                    break
                part = directory / (state + '-' + mode)
                part.mkdir(mode=0o700)
                session = Session(container, part, args.timeout_seconds, database=database)
                session.execute('SET plan_cache_mode=' + mode + '; PREPARE replay_date(text) AS '
                                'SELECT count(*) FROM ingestion.graph_posting_ingestion_dates($1)')
                # Fresh plan backend after shared data has been read; explicitly warm data.
                jk = next(s['run_id'] for s in scopes if s['source_id'] == 'jobkorea')
                for repeat in range(2):
                    sample = dict(statistics=state, operation='prepared_dates', run_id=jk,
                                  plan_cache_mode=mode,
                                  backend='fresh' if repeat == 0 else 'reused',
                                  data_state='already-read', repeat=repeat, result='RUNNING')
                    receipt['samples'].append(sample)
                    explain(session, 'EXECUTE replay_date(' + quote(jk) + ')', sample)
                    write_json(path, receipt)
                    if sample['result'] == 'TIMED_OUT':
                        break
                session.close()
                session = None
            part = directory / (state + '-direct-replay')
            part.mkdir(mode=0o700)
            session = Session(container, part, args.timeout_seconds, database=database)
            before = preserved(session, runs)
            try:
                dates = date_state(session, runs)
            except SqlFailure as error:
                if error.sqlstate != '57014':
                    raise
                dates = None
                receipt[state + '_date_hash_timeout'] = True
            proofs = proof_state(session, runs)
            if first_input is None:
                first_input, first_dates, first_proofs = before, dates, proofs
            elif (before, proofs) != (first_input, first_proofs):
                raise RuntimeError('Matched database input/date/proof fingerprints differ')
            if first_dates is not None and dates is not None and dates != first_dates:
                raise RuntimeError('Matched authoritative date outputs differ')
            receipt[state + '_input'] = before
            receipt[state + '_dates'] = dates
            receipt[state + '_proofs'] = proofs
            receipt[state + '_statistic_identity'] = statistic_identity(session)
            variants = (('baseline', 'candidate') if state == 'as-restored'
                        else ('baseline', 'candidate', 'candidate', 'baseline'))
            for variant in variants:
                session.execute(original if variant == 'baseline' else candidate.read_text())
                for scope in scopes:
                    sample = dict(statistics=state, operation='begin_rollback',
                                  variant=variant, run_id=scope['run_id'], result='RUNNING')
                    receipt['samples'].append(sample)
                    write_json(path, receipt)
                    direct_replay(session, scope['run_id'], sample)
                    write_json(path, receipt)
            if preserved(session, runs) != before or proof_state(session, runs) != proofs:
                raise RuntimeError('Rolled-back replay changed immutable input/proofs')
            if dates is not None and date_state(session, runs) != dates:
                raise RuntimeError('Replay variant changed authoritative dates')
            if state == 'analyzed':
                session.execute(candidate.read_text())
                small = next(s['run_id'] for s in scopes if s['source_id'] == 'alio_organization')
                receipt['replay_correctness_checks'] = replay_oracle(session, small)
                receipt['replay_correctness_checks'] += replay_install_and_lock_oracle(
                    session, container, directory, database, small, candidate.read_text())
                if preserved(session, runs) != before or proof_state(session, runs) != proofs:
                    raise RuntimeError('Mutation oracle changed preserved evidence')
            session.close()
            session = None
        receipt['first_capture_receipt'] = str(first_capture_clone(container, directory, scopes))
        receipt['status'] = ('PASSED_BOUNDED_REPLAY_READS' if all(
            s['result'] == 'PASSED' for s in receipt['samples'])
            else 'PASSED_WITH_BOUNDED_TIMEOUTS')
    except BaseException as error:
        receipt.update(status='FAILED', failure_type=type(error).__name__)
        raise
    finally:
        if session is not None:
            session.close()
        if existing_fixture is None:
            subprocess.run(['docker', 'rm', '-fv', container], capture_output=True, timeout=30)
        else:
            for database in ('reads_restored', 'reads_analyzed'):
                docker(['exec', container, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
                        '-U', 'postgres', '-d', 'postgres', '-c',
                        'DROP DATABASE IF EXISTS ' + database + ' WITH (FORCE)'],
                       directory, 'drop-' + database)
            receipt['cleanup_deferred_to_owned_fixture'] = True
        absent = subprocess.run(['docker', 'inspect', container], capture_output=True,
                                timeout=30).returncode != 0
        volumes_absent = all(subprocess.run(['docker', 'volume', 'inspect', name],
                            capture_output=True, timeout=30).returncode != 0
                             for name in receipt.get('owned_volumes', []))
        receipt.update(cleanup_confirmed=absent and volumes_absent,
                       finished_at=datetime.now(UTC).isoformat())
        write_json(path, receipt)
        print(path, flush=True)
    if existing_fixture is None and not receipt['cleanup_confirmed']:
        raise RuntimeError('Owned profiling resources were not removed')
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--backup-sha256', required=True)
    parser.add_argument('--baseline-dir', required=True, type=Path)
    parser.add_argument('--candidate-sql', required=True, type=Path)
    parser.add_argument('--timeout-seconds', type=int, default=90)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 180:
        parser.error('Focused queries require a 1..180 second bound')
    run(args)


if __name__ == '__main__':
    main()
