#!/usr/bin/env python3
"""Bounded multicore experiments on one owned network-disabled archive clone.

All raw SQL/plans/output stay in protected local state. No live connection is
accepted. The optional review pause allows coordinated read-only inspection of
the same clone and always ends with owned-container cleanup.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from profile_archived_postgres import (
    ROOT,
    STATE,
    LogStream,
    Session,
    SqlFailure,
    analyze_ingestion,
    cleanup_profile,
    docker,
    quote,
    require_completed_profile,
    statistics,
    write_json,
)

SCOPES = (
    ('alio_organization', '12d31df1-1783-48bb-be1d-b801502472ca', 355),
    ('job_alio', '18cb0086-5800-4a2b-870f-db8d74c62fbf', 1076),
    ('jobkorea',
     'jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c', 8434),
    ('nara_job', '9419ffbf-0102-4a44-8c3b-ee28685f1a35', 13234),
)
MIGRATIONS = ('hop/graph/sql/003_source_query_sharing.sql',
              'hop/graph/sql/004_verified_proof_replay.sql',
              'hop/ingestions/jobkorea/sql/008_ready_statistics.sql')



VALIDATION_PATH_QUERY = """SELECT jsonb_build_object(
 'wrappers',(SELECT jsonb_object_agg(proname,prosrc) FROM pg_proc WHERE oid IN (
  'ingestion.source_graph_validation_issue(text)'::regprocedure,
  'ingestion.source_graph_local_validation_issue(text)'::regprocedure)),
 'view_hashes',(SELECT jsonb_object_agg(n,md5(pg_get_viewdef(('ingestion.'||n)::regclass,true)))
  FROM unnest(ARRAY['validation_issue','jobkorea_validation_issue'])n),
 'hook_hashes',(SELECT jsonb_object_agg(n,md5(pg_get_functiondef(
  ('ingestion.'||n||'()')::regprocedure)))
  FROM unnest(ARRAY['local_file_validation_issue','jobkorea_ndjson_validation_issue',
  'jobkorea_cs_collision_issue'])n))"""


def validation_path(value: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless all canonical wrapper fast-path hashes match."""
    shared = value['wrappers']['source_graph_validation_issue']
    local = value['wrappers']['source_graph_local_validation_issue']
    checks: dict[str, bool] = {}
    for name, actual in value['view_hashes'].items():
        if name == 'validation_issue':
            pattern = (r"pg_get_viewdef\('ingestion\.validation_issue'::regclass,true\)\)="
                       r"'([0-9a-f]{32})'")
            body = shared
        elif name == 'jobkorea_validation_issue':
            pattern = (r"to_regclass\('ingestion\.jobkorea_validation_issue'\),true\)\)="
                       r"'([0-9a-f]{32})'")
            body = local
        else:
            raise RuntimeError('Unrecognized validation view')
        expected = re.findall(pattern, body)
        checks[name] = len(expected) == 1 and expected[0] == actual
    for name, actual in value['hook_hashes'].items():
        pattern = (r"to_regprocedure\('ingestion\." + re.escape(name)
                   + r"\(\)'\)\)\)='([0-9a-f]{32})'")
        expected = re.findall(pattern, local)
        checks[name] = len(expected) == 1 and expected[0] == actual
    required = {'validation_issue', 'jobkorea_validation_issue', 'local_file_validation_issue',
                'jobkorea_ndjson_validation_issue', 'jobkorea_cs_collision_issue'}
    if set(checks) != required or not all(checks.values()):
        raise RuntimeError('Validation wrapper fallback or unknown contract')
    return {'checks': checks, 'path': 'CANONICAL_FAST_PATH',
            'wrapper_sha256': {name: hashlib.sha256(body.encode()).hexdigest()
                               for name, body in value['wrappers'].items()}}

def fingerprint_query(run_id: str) -> str:
    """Real captured/live manifests; compare full authoritative proof values."""
    key = quote(run_id)
    return ("SELECT jsonb_build_object('captured',to_jsonb(c),'live',to_jsonb(l),"
            "'equal',to_jsonb(c)=to_jsonb(l)) FROM ingestion.source_graph_manifest("
            + key + ',false)c CROSS JOIN ingestion.source_graph_manifest(' + key + ',true)l')


def eligible_query() -> str:
    """Read and SHA256 every archived record's raw/normalized evidence.

    The planner may inline/recompute expressions for each digest part.
    Associative numeric sums of the full 256-bit row digests allow partial
    aggregation; the result also includes exact row and byte counts. This is an
    evidence-scan checksum workload, not the canonical source proof algorithm.
    """
    return """SELECT count(*) AS records,sum(octet_length(payload)) AS payload_bytes,
    sum(('x'||substr(h,1,16))::bit(64)::bigint::numeric) AS sha_part_1,
    sum(('x'||substr(h,17,16))::bit(64)::bigint::numeric) AS sha_part_2,
    sum(('x'||substr(h,33,16))::bit(64)::bigint::numeric) AS sha_part_3,
    sum(('x'||substr(h,49,16))::bit(64)::bigint::numeric) AS sha_part_4
    FROM (SELECT payload,encode(sha256(convert_to(payload,'UTF8')),'hex') h FROM
    (SELECT jsonb_build_object('run_id',run_id,'record_id',record_id,
    'document_id',document_id,'locator',locator,'source_record_id',source_record_id,
    'source_payload',source_payload,'normalized',normalized,'field_lineage',field_lineage,
    'quality_flags',quality_flags)::text payload FROM ingestion.record)r)s"""


def telemetry(container: str) -> dict[str, Any]:
    """Cgroup counters and surviving-process user/system scheduler ticks.

    Workers that exit between snapshots do not appear in process deltas. The
    cgroup usage_usec counter is authoritative for aggregate container CPU.
    """
    script = ("cat /sys/fs/cgroup/cpu.stat; echo CPU_MAX; cat /sys/fs/cgroup/cpu.max; "
              "echo MEMORY; cat /sys/fs/cgroup/memory.current; echo PROCESSES; "
              "for f in /proc/[0-9]*/stat; do cat \"$f\" 2>/dev/null; done")
    result = subprocess.run(['docker', 'exec', container, 'sh', '-c', script],
                            text=True, capture_output=True, check=True, timeout=10)
    cpu, rest = result.stdout.split('CPU_MAX\n')
    quota, rest = rest.split('MEMORY\n')
    memory, procs = rest.split('PROCESSES\n')
    processes = {}
    for line in procs.splitlines():
        closing = line.rfind(')')
        if closing < 0 or 'postgres' not in line[:closing]:
            continue
        fields = line[closing + 2:].split()
        processes[line.split()[0]] = {'user_ticks': int(fields[11]),
                                     'system_ticks': int(fields[12])}
    return {'cpu_stat': {k: int(v) for k, v in (x.split() for x in cpu.splitlines())},
            'cpu_max': quota.strip(), 'memory_bytes': int(memory.strip()),
            'process_ticks': processes}


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {'cpu_stat': {k: v - before['cpu_stat'].get(k, 0)
                         for k, v in after['cpu_stat'].items()},
            'process_ticks': {pid: {k: value - before['process_ticks'].get(pid, {}).get(k, 0)
                                  for k, value in counters.items()}
                              for pid, counters in after['process_ticks'].items()},
            'memory_bytes_before': before['memory_bytes'],
            'memory_bytes_after': after['memory_bytes']}



def job_summary(jobs: list[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    """Only successful complete job sets support throughput or further scaling."""
    passed = sum(job['status'] == 'PASSED' for job in jobs)
    allowed = bool(jobs) and passed == len(jobs)
    return {'attempted_jobs': len(jobs), 'passed_jobs': passed,
            'jobs_per_second': len(jobs) / wall_seconds if allowed else None,
            'scaling_allowed': allowed}

def gather_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    def walk(node: dict[str, Any]) -> None:
        if node['Node Type'] in ('Gather', 'Gather Merge'):
            found.append({k: node.get(k) for k in ('Node Type', 'Workers Planned',
                                                  'Workers Launched', 'Actual Rows')})
        for child in node.get('Plans', []):
            walk(child)
    walk(plan['Plan'])
    return found


def measured(session: Session, query: str, container: str, *, explain: bool = False,
             sample_cpu: bool = True) -> dict[str, Any]:
    before = telemetry(container) if sample_cpu else None
    started = time.monotonic()
    result: dict[str, Any] = {}
    try:
        if explain:
            plan = json.loads(session.execute('EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) '
                                             + query, allow_timeout=True))[0]
            result.update(plan=plan, execution_ms=plan['Execution Time'],
                          gather=gather_nodes(plan))
        else:
            output = session.execute(query, allow_timeout=True)
            result.update(output=output, output_sha256=hashlib.sha256(output.encode()).hexdigest())
        result['status'] = 'PASSED'
    except SqlFailure as error:
        result.update(status='TIMED_OUT' if error.sqlstate == '57014' else 'FAILED',
                      sqlstate=error.sqlstate)
    result['wall_seconds'] = time.monotonic() - started
    if before:
        after = telemetry(container)
        result.update(cpu_before=before, cpu_after=after, cpu_delta=delta(before, after))
    return result


def run(args: argparse.Namespace) -> Path:
    backup = args.backup.resolve(strict=True)
    with backup.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != args.backup_sha256:
        raise ValueError('Backup SHA256 mismatch')
    token = uuid.uuid4().hex
    directory = STATE / ('postgres-parallelism-' + token)
    directory.mkdir(parents=True, mode=0o700)
    container = 'jobtology-parallel-' + token[:16]
    receipt_path = directory / 'receipt.json'
    receipt: dict[str, Any] = dict(status='RUNNING', started_at=datetime.now(UTC).isoformat(),
        container=container, backup=str(backup), backup_bytes=backup.stat().st_size,
        backup_sha256=args.backup_sha256, source_requests=0, paid_requests=0,
        production_writes=0, scopes=SCOPES, samples=[], limits=[
            'Restored and repeated reads are warm host/cache measurements, not cold-cache.',
            'Fresh backend is not cold data; client startup belongs to session setup.',
            'Source proof manifests are real captured/live readbacks; no capture or graph write.',
            'Associative evidence checksum query is diagnostic, not canonical proof validation.',
            'Forced planner costs/minimum scan size are clone session diagnostics only.',
            'Single sample per order unless separately stated; no general scaling guarantee.'])
    harness = Path(__file__).read_bytes()
    (directory / 'executed-helper.py').write_bytes(harness)
    receipt['executed_helper_sha256'] = hashlib.sha256(harness).hexdigest()
    write_json(receipt_path, receipt)
    session = None
    stream = None
    created = False
    try:
        docker(['run', '--pull', 'never', '-d', '--name', container, '--network', 'none',
                '--label', 'jobtology.parallel-profile', '--memory', '6g', '--cpus', '4',
                '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_DB=jobtology',
                args.image, '-c', 'autovacuum=off', '-c', 'max_worker_processes=8',
                '-c', 'max_parallel_workers=8'], directory, 'boot')
        created = True
        stream = LogStream(container, directory)
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'postgres'],
                                   capture_output=True, check=False)
            if ready.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Owned clone did not become ready')
        started = time.monotonic()
        with backup.open('rb') as data:
            docker(['exec', '-i', container, 'pg_restore', '--no-owner', '--no-privileges',
                    '--exit-on-error', '-U', 'postgres', '-d', 'jobtology'], directory,
                   'restore', source=data, timeout=360)
        receipt['restore_seconds'] = time.monotonic() - started
        session = Session(container, directory, 60)
        receipt['version'] = session.execute('SELECT version()')
        receipt['initial_telemetry'] = telemetry(container)
        receipt['settings'] = json.loads(session.execute("SELECT jsonb_object_agg(name,setting) "
            "FROM pg_settings WHERE name IN ('max_worker_processes','max_parallel_workers',"
            "'max_parallel_workers_per_gather','shared_buffers','work_mem','jit','autovacuum')"))
        receipt['statistics_before'] = statistics(session)
        receipt['statistics_baseline'] = args.statistics_baseline
        if args.statistics_baseline == 'analyzed':
            started = time.monotonic()
            analyze_ingestion(session)
            receipt['analyze_seconds'] = time.monotonic() - started
        receipt['statistics_after'] = statistics(session)
        receipt['migration_sha256'] = {}
        for relative in MIGRATIONS:
            data = (ROOT / relative).read_bytes()
            receipt['migration_sha256'][relative] = hashlib.sha256(data).hexdigest()
            session.execute(data.decode())
        session.execute('SELECT ingestion.source_graph_assert_query_contract()')
        raw_path = json.loads(session.execute(VALIDATION_PATH_QUERY))
        write_json(directory / 'validation-path-preflight.json', raw_path)
        receipt['validation_path'] = validation_path(raw_path)
        receipt['preflight_manifests'] = []
        for source, run_id, count in SCOPES:
            value = json.loads(session.execute(fingerprint_query(run_id)))
            if not value['equal'] or value['captured']['record_count'] != count:
                raise RuntimeError('Canonical full captured/live preflight failed')
            receipt['preflight_manifests'].append(dict(source=source, run_id=run_id, output=value))
        receipt['scope_counts'] = json.loads(session.execute(
            "SELECT jsonb_object_agg(run_id,n) FROM (SELECT run_id,count(*) n "
            "FROM ingestion.record "
            'WHERE run_id IN (' + ','.join(quote(x[1]) for x in SCOPES) + ') GROUP BY run_id)s'))
        if any(receipt['scope_counts'].get(run) != n for _, run, n in SCOPES):
            raise RuntimeError('Exact supplied scope mismatch')
        write_json(receipt_path, receipt)
        write_json(directory / 'ready.json', {'container': container, 'directory': str(directory),
                                             'database': 'jobtology'})
        print('CLONE_READY ' + str(directory), flush=True)
        session.execute("SET statement_timeout='60s'; SET max_parallel_workers_per_gather=0; "
                        "LOAD 'auto_explain'; SET auto_explain.log_min_duration='100ms'; "
                        'SET auto_explain.log_analyze=on; SET auto_explain.log_buffers=on; '
                        'SET auto_explain.log_timing=off; SET auto_explain.log_format=json; '
                        'SET auto_explain.log_nested_statements=on; '
                        'SET auto_explain.sample_rate=1;')
        sample = measured(session, 'SELECT ingestion.assert_source_graph_content('
                          + quote(SCOPES[-1][1]) + ')', container)
        sample.update(phase='nara_nested_diagnosis', bound_seconds=60)
        receipt['samples'].append(sample)
        session.execute("SET auto_explain.log_min_duration=-1; SET statement_timeout='60s'")
        write_json(receipt_path, receipt)
        print('NESTED_DIAGNOSIS ' + sample['status'], flush=True)
        # Independent sessions; identical four jobs. Output equality across widths is required.
        for width in (1, 2, 4):
            part = directory / ('sessions-' + str(width))
            part.mkdir(mode=0o700)
            def job(scope: tuple[str, str, int], part: Path = part) -> dict[str, Any]:
                sub = part / scope[0]
                sub.mkdir(mode=0o700)
                worker = Session(container, sub, 60)
                try:
                    worker.execute('SET default_transaction_read_only=on; '
                                   'SET max_parallel_workers_per_gather=0')
                    value = measured(worker, fingerprint_query(scope[1]), container,
                                     sample_cpu=False)
                    value.update(source=scope[0], run_id=scope[1])
                    if value['status'] == 'PASSED' and not json.loads(value['output'])['equal']:
                        raise RuntimeError('Captured/live proof differs')
                    return value
                finally:
                    worker.close()
            before = telemetry(container)
            started = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
                jobs = list(pool.map(job, SCOPES))
            wall = time.monotonic() - started
            after = telemetry(container)
            summary = job_summary(jobs, wall)
            passed = summary['passed_jobs']
            receipt['samples'].append(dict(phase='independent_sessions', width=width, jobs=jobs,
                wall_seconds=wall, **summary,
                cpu_before=before, cpu_after=after, cpu_delta=delta(before, after)))
            write_json(receipt_path, receipt)
            print(f'SESSIONS {width} {wall:.3f}s passed={passed}/{len(jobs)}', flush=True)
            if not summary['scaling_allowed']:
                raise RuntimeError('Failed independent job set; scaling stopped')
        session.execute('SET default_transaction_read_only=on; SET jit=off')
        query = eligible_query()
        for costs in ('default', 'diagnostic'):
            if costs == 'diagnostic':
                session.execute('SET min_parallel_table_scan_size=0; SET parallel_setup_cost=0; '
                                'SET parallel_tuple_cost=0')
            # Reverse order under different costs is a sensitivity series, not a matched replicate.
            order = (0, 1, 2, 4) if costs == 'default' else (4, 2, 1, 0)
            for workers in order:
                session.execute(f'SET max_parallel_workers_per_gather={workers}')
                output = measured(session, query, container)
                plan = measured(session, query, container, explain=True)
                receipt['samples'].append(dict(phase='single_query', costs=costs,
                    max_workers=workers, output=output, explain=plan))
                write_json(receipt_path, receipt)
                print(f'QUERY {costs} {workers} {output["wall_seconds"]:.3f}s '
                      f'{plan.get("gather", [])}', flush=True)
        session.close()
        session = None
        width_outputs = [{j['run_id']: j.get('output_sha256') for j in s['jobs']}
                         for s in receipt['samples'] if s['phase'] == 'independent_sessions']
        query_outputs = [s['output'].get('output_sha256') for s in receipt['samples']
                         if s['phase'] == 'single_query']
        receipt['output_equality'] = dict(independent_sessions=all(x == width_outputs[0]
            for x in width_outputs) and all(width_outputs[0].values()),
            single_query=len(set(query_outputs)) == 1 and None not in query_outputs)
        receipt['plan_samples_passed'] = all(s['explain']['status'] == 'PASSED'
            for s in receipt['samples'] if s['phase'] == 'single_query')
        receipt['status'] = ('PASSED' if all(receipt['output_equality'].values())
                             and receipt['plan_samples_passed'] else 'FAILED')
        write_json(directory / 'benchmarks-complete.json', receipt)
        print('BENCHMARKS_COMPLETE ' + str(directory), flush=True)
        # Coordinators may inspect/reuse this single owned clone within a bounded review window.
        deadline = time.monotonic() + args.review_pause_seconds
        while time.monotonic() < deadline and not (directory / 'cleanup-now').exists():
            time.sleep(1)
    except BaseException as error:
        receipt.update(status='FAILED', failure_type=type(error).__name__)
        raise
    finally:
        if session is not None:
            try:
                session.close()
            except BaseException as error:
                receipt.update(status='FAILED', failure_type=type(error).__name__)
                receipt.setdefault('cleanup_failures', []).append(
                    {'stage': 'session_close', 'type': type(error).__name__})
        if created:
            cleanup_profile(container, directory, stream, receipt)
        receipt['finished_at'] = datetime.now(UTC).isoformat()
        write_json(receipt_path, receipt)
        print('FINAL_RECEIPT ' + str(receipt_path), flush=True)
    require_completed_profile(receipt, receipt_path)
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--backup-sha256', required=True)
    parser.add_argument('--image', default='postgres:18-alpine')
    parser.add_argument('--statistics-baseline', choices=('analyzed', 'restored'),
                        default='analyzed',
                        help='Owned-clone ANALYZE before timing; restored is diagnostic only')
    parser.add_argument('--review-pause-seconds', type=int, default=0)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{64}', args.backup_sha256):
        parser.error('backup SHA256 must be 64 lowercase hexadecimal characters')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]*', args.image):
        parser.error('image must be a local Docker image reference')
    if not 0 <= args.review_pause_seconds <= 900:
        parser.error('review pause must be bounded to 0..900 seconds')
    run(args)


if __name__ == '__main__':
    main()
