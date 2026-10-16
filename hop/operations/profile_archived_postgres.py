#!/usr/bin/env python3
"""Profile local archived source proofs/dates in a disposable network-disabled PG.

Requires a supplied custom-format dump and its SHA256. Never connects to a live
database, retrieves source content, or changes the archive. Plans can contain raw
evidence: all output files belong in protected local state, outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TextIO

ROOT = Path(__file__).resolve().parents[2]
STATE = Path.home() / '.local/state/jobtology-hop'
LABEL = 'jobtology.archived-pg-profile'
SQL_FILES = ('graph/sql/001_posting_ingestion_dates.sql',
             'graph/sql/002_batchfree_source_graph.sql')
IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}')


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def safe_runs(values: list[str]) -> list[str]:
    if not values or len(values) != len(set(values)):
        raise ValueError('At least one unique exact run ID is required')
    if any(not IDENTITY.fullmatch(v) or v in ('LATEST', 'ALL_CHECKPOINTED') for v in values):
        raise ValueError('Use exact safe run IDs')
    return values


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)


def plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    root = plan['Plan']
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        estimated, actual = node.get('Plan Rows'), node.get('Actual Rows')
        if estimated is not None and actual is not None:
            nodes.append({'node': node['Node Type'], 'estimated_rows': estimated,
                          'actual_rows': actual, 'actual_loops': node.get('Actual Loops'),
                          'ratio': max(estimated, actual, 1) / max(min(estimated, actual), 1)})
        for child in node.get('Plans', []):
            walk(child)

    walk(root)
    return {'planning_ms': plan.get('Planning Time'), 'execution_ms': plan['Execution Time'],
            'root_node': root['Node Type'], 'rows': root.get('Actual Rows'),
            'buffers': {k: root.get(k, 0) for k in
                        ('Shared Hit Blocks', 'Shared Read Blocks', 'Temp Read Blocks',
                         'Temp Written Blocks', 'Local Hit Blocks', 'Local Read Blocks')},
            'largest_row_estimate_errors': sorted(nodes, key=lambda n: n['ratio'],
                                                 reverse=True)[:8],
            'jit': plan.get('JIT')}


class Session:
    """One psql backend, so prepared/function plan caches survive repeated calls."""

    def __init__(self, container: str, directory: Path, timeout_seconds: int,
                 *, database: str = 'jobtology'):
        self.directory = directory
        self.index = 0
        self.stderr: TextIO = (directory / 'session.stderr').open('w')
        self.process = subprocess.Popen(
            ['docker', 'exec', '-i', container, 'psql', '-X', '-qAt', '-v',
             'ON_ERROR_STOP=1', '-U', 'postgres', '-d', database],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True,
            bufsize=1,
        )
        self.execute(f"SET statement_timeout='{timeout_seconds}s'; SET lock_timeout='5s';")

    def execute(self, query: str, *, allow_timeout: bool = False) -> str:
        self.index += 1
        marker = 'profile_' + uuid.uuid4().hex
        assert self.process.stdin is not None and self.process.stdout is not None
        (self.directory / f'statement-{self.index:04}.sql').write_text(query + '\n')
        self.process.stdin.write('\\set ON_ERROR_STOP ' + ('off' if allow_timeout else 'on')
                                 + '\n' + query.rstrip(';\n') + ';\n\\echo ' + marker
                                 + '_state :SQLSTATE\n\\echo ' + marker + '\n')
        self.process.stdin.flush()
        lines: list[str] = []
        sqlstate = None
        for line in self.process.stdout:
            if line.startswith(marker + '_state '):
                sqlstate = line.split()[1]
                continue
            if line.strip() == marker:
                output = ''.join(lines).strip()
                (self.directory / f'statement-{self.index:04}.stdout').write_text(output + '\n')
                if sqlstate != '00000':
                    raise SqlFailure(sqlstate or 'UNKNOWN')
                return output
            lines.append(line)
        raise RuntimeError('Isolated SQL failed; inspect protected session.stderr')

    def close(self) -> None:
        if self.process.poll() is None:
            assert self.process.stdin is not None
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.stderr.close()


class SqlFailure(RuntimeError):
    def __init__(self, sqlstate: str):
        self.sqlstate = sqlstate
        super().__init__('Isolated SQL failed with SQLSTATE ' + sqlstate
                         + '; inspect protected session.stderr')


class LogStream:
    """Capture every log while its container runs, before daemon log rotation."""

    def __init__(self, container: str, directory: Path):
        self.files: list[BinaryIO] = [
            (directory / ('postgres-nested-plans.' + suffix)).open('wb')
            for suffix in ('stdout', 'stderr')]
        try:
            self.process = subprocess.Popen(['docker', 'logs', '--follow', container],
                stdout=self.files[0], stderr=self.files[1])
        except BaseException:
            for file in self.files:
                file.close()
            raise

    def close(self) -> bool:
        # Stop/remove the owned container first so the follower can drain and
        # end naturally, preserving its final complete plan.
        try:
            try:
                return self.process.wait(timeout=10) == 0
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                return False
        finally:
            for file in self.files:
                file.close()


def docker(args: list[str], directory: Path, name: str, *, source: Any = None,
           timeout: int = 300) -> None:
    with (directory / (name + '.stdout')).open('wb') as out, \
            (directory / (name + '.stderr')).open('wb') as err:
        result = subprocess.run(['docker', *args], stdin=source, stdout=out, stderr=err,
                                timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f'{name} failed; inspect protected logs')


def cleanup_profile(container: str, directory: Path, stream: LogStream | None,
                    receipt: dict[str, Any]) -> None:
    """Record cleanup failures without masking an exception already in flight."""
    failures: list[dict[str, str]] = receipt.setdefault('cleanup_failures', [])
    try:
        if stream is None:
            docker(['logs', container], directory, 'postgres-nested-plans', timeout=30)
        else:
            receipt['nested_log_stream_running_before_cleanup'] = stream.process.poll() is None
    except BaseException as error:
        failures.append({'stage': 'logs', 'type': type(error).__name__})
    try:
        result = subprocess.run(['docker', 'rm', '-fv', container],
                                capture_output=True, check=False)
        receipt['cleanup_verified'] = result.returncode == 0
    except BaseException as error:
        receipt['cleanup_verified'] = False
        failures.append({'stage': 'container_removal', 'type': type(error).__name__})
    if stream is not None:
        try:
            receipt['nested_log_stream_complete'] = stream.close() and (
                receipt.get('nested_log_stream_running_before_cleanup', False))
        except BaseException as error:
            receipt['nested_log_stream_complete'] = False
            failures.append({'stage': 'log_drain', 'type': type(error).__name__})
    if failures or not receipt['cleanup_verified'] or (
        stream is not None and not receipt['nested_log_stream_complete']
    ):
        receipt['status'] = 'FAILED'
        receipt.setdefault('failure_type', 'CleanupOrLogCaptureFailed')


def require_completed_profile(receipt: dict[str, Any], receipt_path: Path) -> None:
    if receipt['status'] == 'FAILED':
        raise RuntimeError(f'Archived profile failed; inspect protected {receipt_path}')


def statistics(session: Session) -> dict[str, Any]:
    return json.loads(session.execute("""SELECT jsonb_build_object(
     'settings',(SELECT jsonb_object_agg(name,setting) FROM pg_settings WHERE name IN
       ('server_version','jit','work_mem','plan_cache_mode','autovacuum','shared_buffers')),
     'tables',(SELECT jsonb_agg(jsonb_build_object('schema',n.nspname,'table',c.relname,
       'estimated_rows',c.reltuples,'pages',c.relpages,'statistics_columns',
       (SELECT count(*) FROM pg_statistic s WHERE s.starelid=c.oid),
       'last_analyze',t.last_analyze,'last_autoanalyze',t.last_autoanalyze,
       'live_tuples',t.n_live_tup,'dead_tuples',t.n_dead_tup) ORDER BY n.nspname,c.relname)
       FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
       LEFT JOIN pg_stat_all_tables t ON t.relid=c.oid
       WHERE n.nspname='ingestion' AND c.relkind='r'))"""))


def preserved(session: Session, runs: list[str]) -> Any:
    keys = ','.join(quote(r) for r in runs)
    tables = ('run', 'document', 'record', 'graph_export')
    clauses = [f"SELECT '{tab}' AS name,count(*) AS n,"
               "md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS fingerprint FROM "
               f"(SELECT md5(to_jsonb(t)::text) h FROM ingestion.{tab} t "
               f"WHERE run_id IN ({keys})) rows" for tab in tables]
    frozen = json.loads(session.execute("SELECT coalesce(jsonb_agg(c.relname), '[]'::jsonb) "
        'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
        "WHERE n.nspname='enrichment' AND c.relkind='r' AND c.relname IN "
        "('input_bundle','metadata_occupation_candidate','attempt','semantic_link')"))
    for table in frozen:
        clauses.append(f"SELECT 'enrichment.{table}' AS name,count(*) AS n,"
                       "md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS fingerprint FROM "
                       f'(SELECT md5(to_jsonb(t)::text) h FROM enrichment.{table} t) rows')
    return json.loads(session.execute('SELECT jsonb_object_agg(name,to_jsonb(t)-\'name\') FROM ('
                                      + ' UNION ALL '.join(clauses) + ') t'))


def analyze_ingestion(session: Session) -> None:
    relations = json.loads(session.execute(
        "SELECT jsonb_agg(format('%I.%I',n.nspname,c.relname)) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='ingestion' AND c.relkind='r'"))
    for relation in relations:
        session.execute('ANALYZE ' + relation)


def queries(run: str, proof_ready: bool, entities: bool) -> dict[str, str]:
    value = quote(run)
    result = {
        'validation': f'SELECT ingestion.source_graph_run_is_valid({value})',
        'live_manifest': f'SELECT * FROM ingestion.source_graph_manifest({value},true)',
        'dates': f'SELECT count(*) FROM ingestion.graph_posting_ingestion_dates({value})',
    }
    if proof_ready:
        result['proof_validation'] = f'SELECT ingestion.assert_source_graph_projection({value})'
        result['membership'] = ('SELECT count(*) FROM ingestion.source_graph_membership '
                                f'WHERE run_id={value}')
    if entities:
        result['entities'] = f'SELECT count(*) FROM ingestion.graph_source_entities({value})'
    return result


def run_profile(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    backup = args.backup.resolve(strict=True)
    with backup.open('rb') as source:
        actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if actual != args.backup_sha256:
        raise ValueError('Supplied archive SHA256 does not match')
    safe_runs(args.run_id)
    directory = STATE / ('archived-pg-profile-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700, parents=True)
    container = 'jobtology-perf-archive-' + uuid.uuid4().hex[:16]
    receipt: dict[str, Any] = {
        'version': 1, 'status': 'RUNNING', 'created_at': datetime.now(UTC).isoformat(),
        'backup_path': str(backup),
        'backup_sha256': actual, 'backup_bytes': backup.stat().st_size,
        'run_ids': args.run_id, 'capture_mode': args.capture_mode, 'container': container,
        'production_writes': 0, 'source_requests': 0, 'paid_requests': 0,
        'network': 'none', 'statement_timeout_seconds': args.timeout_seconds,
        'clone_autovacuum': args.autovacuum,
        'nested_plan_instrumentation': args.nested_plans,
        'capture_fresh_statistics': args.capture_fresh_statistics,
        'samples': [], 'limits': [
            'First restore read is not a host-cold-cache measurement.',
            'Initial statistics are measured as restored; stale statistics are not assumed.',
            'Initial measured reads follow SQL installation and source fingerprint checks; '
            'capture operations, when selected, also precede them.',
            'Later phases reuse warmed caches; a statistics-only speedup is not established.',
            'EXPLAIN for PL/pgSQL hides nested plans; enable --nested-plans for protected '
            'auto_explain evidence (which adds instrumentation overhead).',
            'Compare capture modes only on separate fresh restores of the same dump, run '
            'order, SQL hashes and statistics phase.'],
    }
    receipt_path = directory / 'receipt.json'
    write_json(receipt_path, receipt)
    session = None
    log_stream = None
    created = False
    try:
        docker(['run', '--pull', 'never', '-d', '--name', container, '--network', 'none',
                '--label', LABEL, '--memory', '4g', '--cpus', '2', '-e',
                'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_DB=jobtology',
                args.image, '-c', 'autovacuum=' + args.autovacuum], directory, 'boot')
        created = True
        if args.nested_plans:
            log_stream = LogStream(container, directory)
        inspected = subprocess.run(
            ['docker', 'inspect', container, '--format', '{{json .}}'],
            capture_output=True, text=True, check=True)
        metadata = json.loads(inspected.stdout)
        receipt['image_id'] = metadata['Image']
        receipt['container_limits'] = {
            'memory_bytes': metadata['HostConfig']['Memory'],
            'nano_cpus': metadata['HostConfig']['NanoCpus'],
            'network': metadata['HostConfig']['NetworkMode'],
        }
        for _attempt in range(60):
            check = subprocess.run(
                ['docker', 'exec', container, 'psql', '-X', '-qAt', '-h', '127.0.0.1',
                 '-U', 'postgres',
                 '-d', 'jobtology', '-c', 'SELECT 1'], capture_output=True, check=False)
            if check.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Isolated PostgreSQL did not become ready')
        started = time.monotonic()
        with backup.open('rb') as source:
            docker(['exec', '-i', container, 'pg_restore', '--no-owner', '--no-privileges',
                    '--exit-on-error', '-U', 'postgres', '-d', 'jobtology'], directory, 'restore',
                   source=source, timeout=args.restore_timeout_seconds)
        receipt['restore_seconds'] = time.monotonic() - started
        session = Session(container, directory, args.timeout_seconds)
        receipt['initial_statistics'] = statistics(session)
        receipt['before'] = preserved(session, args.run_id)
        receipt['sql_sha256'] = {}
        for relative in SQL_FILES:
            data = (ROOT / 'hop' / relative).read_bytes()
            receipt['sql_sha256'][relative] = hashlib.sha256(data).hexdigest()
            session.execute(data.decode())
        if args.nested_plans:
            session.execute("LOAD 'auto_explain'; SET auto_explain.log_min_duration=0; "
                            'SET auto_explain.log_analyze=on; SET auto_explain.log_buffers=on; '
                            'SET auto_explain.log_timing=off; SET auto_explain.log_format=json; '
                            'SET auto_explain.log_nested_statements=on;')
        for run in args.run_id:
            valid = session.execute("SELECT state='READY' AND mode<>'SMOKE' "
                                    'FROM ingestion.run WHERE run_id=' + quote(run))
            if valid != 't':
                raise RuntimeError('Exact READY run is absent in the restored archive')
            valid = session.execute('SELECT ingestion.source_graph_run_is_valid('
                                    + quote(run) + ')')
            if valid != 't':
                raise RuntimeError('Restored exact run failed source validation')
        receipt['source_validation'] = 'PASSED'
        if args.capture_dates:
            for run in args.run_id:
                tick = time.monotonic()
                session.execute('SELECT ingestion.record_posting_ingestion_observations('
                                + quote(run) + ')')
                receipt['samples'].append({'phase': 'capture_dates', 'run_id': run,
                                           'wall_seconds': time.monotonic() - tick})
        if args.capture_mode != 'none':
            present = session.execute('SELECT count(*) FROM ingestion.source_graph_projection '
                                      'WHERE run_id IN (' + ','.join(map(quote, args.run_id)) + ')')
            if present != '0':
                raise RuntimeError('Capture comparison requires an archive with no scoped proofs')
            if args.capture_fresh_statistics:
                analyze_ingestion(session)
            started = time.monotonic()
            if args.capture_mode == 'atomic':
                session.execute('BEGIN;')
            for operation in ('begin', 'finish'):
                for run in args.run_id:
                    tick = time.monotonic()
                    session.execute(f'SELECT ingestion.{operation}_source_graph_projection('
                                    + quote(run) + ')')
                    receipt['samples'].append({'phase': 'capture', 'run_id': run,
                                               'operation': operation,
                                               'wall_seconds': time.monotonic() - tick})
            if args.capture_mode == 'atomic':
                session.execute('COMMIT;')
            receipt['capture_seconds'] = time.monotonic() - started
            for operation in ('begin', 'finish'):
                receipt['capture_' + operation + '_seconds'] = sum(
                    sample['wall_seconds'] for sample in receipt['samples']
                    if sample['phase'] == 'capture' and sample['operation'] == operation)
            receipt['capture_statistics'] = statistics(session)
        available: dict[str, str] = {}
        for index, run in enumerate(args.run_id):
            proof = session.execute('SELECT EXISTS(SELECT 1 FROM ingestion.source_graph_projection '
                                    "WHERE state='READY' AND run_id=" + quote(run) + ')') == 't'
            for name, query in queries(run, proof, args.entities).items():
                available[f'run{index}_{name}'] = query
        phases = ('initial_read', 'fresh_statistics', 'force_custom_plan', 'force_generic_plan')
        for phase in phases:
            if phase == 'fresh_statistics':
                analyze_ingestion(session)
                receipt['fresh_statistics'] = statistics(session)
            prepared = phase.startswith('force_')
            if prepared:
                session.execute('SET plan_cache_mode=' + phase)
            for name, query in available.items():
                if prepared:
                    # Parameterized calls exercise real custom/generic choices.
                    run = args.run_id[int(name.split('_', 1)[0][3:])]
                    parameterized = query.replace(quote(run), '$1')
                    session.execute(f'PREPARE {name}(text) AS ' + parameterized)
                    execution = f'EXECUTE {name}(' + quote(run) + ')'
                else:
                    execution = query
                for sample in range(args.samples):
                    started = time.monotonic()
                    try:
                        plan = json.loads(session.execute('EXPLAIN (ANALYZE, BUFFERS, SETTINGS, '
                                                          'FORMAT JSON) ' + execution,
                                                          allow_timeout=True))[0]
                    except SqlFailure as error:
                        if error.sqlstate != '57014':
                            raise
                        receipt['samples'].append({
                            'phase': phase, 'query': name, 'sample': sample + 1,
                            'result': 'statement_timeout', 'sqlstate': error.sqlstate,
                            'bound_seconds': args.timeout_seconds,
                            'wall_seconds': time.monotonic() - started})
                        write_json(receipt_path, receipt)
                        break
                    write_json(directory / f'{phase}-{name}-{sample + 1}.plan.json', plan)
                    receipt['samples'].append({'phase': phase, 'query': name, 'sample': sample + 1,
                                               'wall_seconds': time.monotonic() - started,
                                               **plan_summary(plan)})
                    write_json(receipt_path, receipt)
                if prepared:
                    session.execute('DEALLOCATE ' + name)
        receipt['after'] = preserved(session, args.run_id)
        if receipt['before'] != receipt['after']:
            raise RuntimeError('Archived source and historical export fingerprints changed')
        receipt['status'] = ('PROFILED_WITH_TIMEOUTS' if any(
            sample.get('result') == 'statement_timeout' for sample in receipt['samples'])
            else 'PASSED')
    except BaseException as error:
        receipt['status'] = 'FAILED'
        receipt['failure_type'] = type(error).__name__
        raise
    finally:
        if session is not None:
            try:
                session.close()
            except BaseException as error:
                receipt['status'] = 'FAILED'
                receipt.setdefault('failure_type', type(error).__name__)
                receipt.setdefault('cleanup_failures', []).append(
                    {'stage': 'session_close', 'type': type(error).__name__})
        if created:
            # The random name belongs to this process, never a supplied container.
            cleanup_profile(container, directory, log_stream, receipt)
        receipt['finished_at'] = datetime.now(UTC).isoformat()
        write_json(receipt_path, receipt)
        print(receipt_path, flush=True)
    require_completed_profile(receipt, receipt_path)
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--backup-sha256', required=True)
    parser.add_argument('--run-id', action='append', required=True)
    parser.add_argument('--image', default='postgres:18-alpine')
    parser.add_argument('--autovacuum', choices=('off', 'on'), default='off',
                        help='Clone-only setting; off isolates explicit statistics phases')
    parser.add_argument('--timeout-seconds', type=int, default=120)
    parser.add_argument('--restore-timeout-seconds', type=int, default=300)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--capture-mode', choices=('none', 'per-run', 'atomic'), default='none')
    parser.add_argument('--capture-fresh-statistics', action='store_true')
    parser.add_argument('--capture-dates', action='store_true',
                        help='Capture missing date observations in the disposable clone only')
    parser.add_argument('--nested-plans', action='store_true')
    parser.add_argument('--entities', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.samples <= 10 or not 1 <= args.timeout_seconds <= 3600:
        parser.error('samples must be 1..10 and statement timeout 1..3600 seconds')
    if not re.fullmatch(r'[0-9a-f]{64}', args.backup_sha256):
        parser.error('backup SHA256 must be 64 lowercase hexadecimal characters')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]*', args.image):
        parser.error('image must be a local Docker image reference, never an option')
    if args.restore_timeout_seconds <= 0:
        parser.error('restore timeout must be positive')
    run_profile(args)


if __name__ == '__main__':
    main()
