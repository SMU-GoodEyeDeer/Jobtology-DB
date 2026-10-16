#!/usr/bin/env python3
"""Plan/apply/rollback a reviewed, artifact-only performance patch.

No SQL file, migration, graph job or provider call is executed; read-only state
prechecks run. The existing scheduler
lock and checked flat-ontology pending fence protect interrupted multi-file
installation. Rollback restores exact bytes and refuses subsequent runtime drift.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import backfill_posting_dates as dates
import deploy_jobkorea_runtime as deployment
import reconcile_runtime as common

ROOT = common.ROOT
STATE = common.STATE
PROJECT = common.PROJECT
FENCE_NAME = 'flat-ontology-migration.pending'
SQL_ARTIFACT = 'retention/sql/000_operations.sql'
CANONICAL_OPERATIONS = ROOT.parent / 'docs/hop-migration/operations.sql'
ALLOWLIST = (
    'graph/load_entity_names.hpl', 'graph/verify_entity_names.hpl',
    'graph/load_records.hpl', 'graph/verify_records.hpl',
    'ontology/write_node_scalars.hpl', 'ontology/write_node_arrays.hpl',
    'ontology/write_edge_scalars.hpl', 'ontology/write_edge_arrays.hpl',
    'ontology/verify_node_scalars.hpl', 'ontology/verify_node_arrays.hpl',
    'ontology/verify_edge_scalars.hpl', 'ontology/verify_edge_arrays.hpl',
    'ontology/verify_legacy_node_scalars.hpl', 'ontology/verify_legacy_node_arrays.hpl',
    'ontology/verify_legacy_edge_scalars.hpl', 'ontology/verify_legacy_edge_arrays.hpl',
    SQL_ARTIFACT,
)


def artifacts(values: list[str]) -> tuple[str, ...]:
    if not values or len(set(values)) != len(values) or any(v not in ALLOWLIST for v in values):
        raise ValueError('Select unique artifacts from the fixed performance allowlist')
    return tuple(v for v in ALLOWLIST if v in values)


def idle(runtime: dict[str, str]) -> None:
    common.idle_cli(runtime['hop'])
    dates.require_idle(runtime['pg'])
    active = json.loads(deployment.sql(runtime['pg'], """BEGIN READ ONLY;
     SET LOCAL statement_timeout='15s';
     SELECT jsonb_build_object(
      'flat_loads',(SELECT count(*) FROM ontology.flat_graph_load
        WHERE state IN('RUNNING','STAGED')),
      'source_projections',(SELECT count(*) FROM ingestion.source_graph_projection
        WHERE state='LOADING'));
     COMMIT;"""))
    if any(active.values()):
        raise RuntimeError('A flat load or source projection is unfinished')
    if (STATE / 'batchfree-migration.pending').exists():
        raise RuntimeError('An interrupted batch-free operation must be recovered first')
    adapter = common.host_bytes()
    if adapter is None or (
        b'[[ ! -e "$STATE_DIR/flat-ontology-migration.pending" ]] || exit 0' not in adapter
    ):
        raise RuntimeError('Deployed scheduler does not honor the existing durable fence')


def read_remote(hop: str, relative: str) -> bytes:
    if relative not in ALLOWLIST:
        raise ValueError('Artifact outside the fixed performance allowlist')
    # Existing reader checks every ancestor for symlinks.
    data = deployment.remote_bytes(hop, relative)
    if data is None:
        raise RuntimeError('Performance patch requires an existing public artifact')
    return data


def snapshot(runtime: dict[str, str], selected: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for relative in selected:
        path = ROOT / relative
        if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
            raise RuntimeError('Public source artifact is absent or a symlink')
        data = path.read_bytes()
        if relative == SQL_ARTIFACT:
            if data != CANONICAL_OPERATIONS.read_bytes():
                raise RuntimeError('Retention operations artifact differs from canonical SQL')
        else:
            ET.fromstring(data)
        before, after = common.digest(read_remote(runtime['hop'], relative)), common.digest(data)
        result[relative] = {'before': before, 'after': after, 'change': before != after}
    return result


def plan(runtime: dict[str, str], selected: tuple[str, ...]) -> Path:
    idle(runtime)
    if (STATE / FENCE_NAME).exists():
        raise RuntimeError('An existing fenced operation must be recovered first')
    directory = STATE / ('performance-runtime-plan-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    path = directory / 'manifest.json'
    common.write_json(path, {
        'version': 1, 'kind': 'PERFORMANCE_ARTIFACT_ONLY',
        'created_at': datetime.now(UTC).isoformat(), 'containers': runtime,
        'artifacts': snapshot(runtime, selected),
        'catalog_context': common.db_state(runtime['pg'])['catalog_context'],
        'executed_sql': False, 'executed_jobs': False,
        'executed_sql_means': 'SQL file or migration execution; read-only prechecks run',
    })
    return path


def replace(hop: str, relative: str, data: bytes, expected: str, token: str,
            directory: Path) -> None:
    if common.digest(read_remote(hop, relative)) != expected:
        raise RuntimeError('Runtime changed before replacement')
    local = directory / ('stage-' + uuid.uuid4().hex + '.artifact')
    local.write_bytes(data)
    local.chmod(0o600)
    temporary = f'{PROJECT}/{relative}.performance-{token}'
    try:
        common.command(['docker', 'cp', str(local), hop + ':' + temporary])
        common.command(['docker', 'exec', '-u', 'root', hop, 'chown', '501:501', temporary])
        common.command(['docker', 'exec', '-u', 'root', hop, 'chmod', '644', temporary])
        actual = common.command(['docker', 'exec', hop, 'sha256sum', temporary]).decode().split()[0]
        if actual != common.digest(data):
            raise RuntimeError('Staged performance artifact hash mismatch')
        if common.digest(read_remote(hop, relative)) != expected:
            raise RuntimeError('Runtime changed during staging')
        common.command(['docker', 'exec', '-u', 'root', hop, 'mv', '--', temporary,
                        f'{PROJECT}/{relative}'])
    finally:
        local.unlink(missing_ok=True)
        common.command(['docker', 'exec', '-u', 'root', hop, 'rm', '-f', '--', temporary])


def own_fence(receipt: dict[str, Any], receipt_path: Path) -> None:
    fence = STATE / FENCE_NAME
    if fence.exists():
        if fence.is_symlink():
            raise RuntimeError('Durable scheduler fence must not be a symlink')
        value = json.loads(fence.read_bytes())
        if value.get('token') != receipt['token'] or value.get('receipt') != str(receipt_path):
            raise RuntimeError('Durable scheduler fence belongs to another operation')
    else:
        descriptor = os.open(fence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump({'token': receipt['token'], 'receipt': str(receipt_path),
                       'kind': 'PERFORMANCE_ARTIFACT_ONLY'}, output)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())


def release_fence(receipt: dict[str, Any], receipt_path: Path) -> None:
    fence = STATE / FENCE_NAME
    value = json.loads(fence.read_bytes())
    if value.get('token') != receipt['token'] or value.get('receipt') != str(receipt_path):
        raise RuntimeError('Durable scheduler fence ownership changed')
    fence.unlink()


def apply(manifest_path: Path, runtime: dict[str, str]) -> Path:
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get('version') != 1 or manifest.get('kind') != 'PERFORMANCE_ARTIFACT_ONLY':
        raise RuntimeError('Unrecognized performance manifest')
    if manifest['containers'] != runtime:
        raise RuntimeError('Runtime container identity changed')
    selected = artifacts(list(manifest['artifacts']))
    idle(runtime)
    if (STATE / FENCE_NAME).exists():
        raise RuntimeError('An existing fenced operation must be recovered first')
    common.assert_same_plan(manifest['artifacts'], snapshot(runtime, selected))
    if manifest['catalog_context'] != common.db_state(runtime['pg'])['catalog_context']:
        raise RuntimeError('Catalogue context changed since planning')
    directory = STATE / ('performance-runtime-applied-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    path = directory / 'receipt.json'
    receipt: dict[str, Any] = {
               **manifest, 'status': 'BACKING_UP', 'manifest': str(manifest_path.resolve()),
               'token': uuid.uuid4().hex, 'installed': [], 'attempted': [],
               'scheduler_fence_removed': False}
    common.write_json(path, receipt)
    for relative in selected:
        before = read_remote(runtime['hop'], relative)
        if common.digest(before) != manifest['artifacts'][relative]['before']:
            raise RuntimeError('Runtime drifted before backup')
        destination = directory / 'before' / relative
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.write_bytes(before)
        destination.chmod(0o600)
    own_fence(receipt, path)
    try:
        idle(runtime)
        common.assert_same_plan(manifest['artifacts'], snapshot(runtime, selected))
        receipt['status'] = 'INSTALLING'
        common.write_json(path, receipt)
        for relative in selected:
            entry = manifest['artifacts'][relative]
            if not entry['change']:
                continue
            # Write intent before mutation so interrupted rename is recoverable.
            receipt['attempted'].append(relative)
            common.write_json(path, receipt)
            candidate = (ROOT / relative).read_bytes()
            if common.digest(candidate) != entry['after']:
                raise RuntimeError('Candidate changed after planning')
            replace(runtime['hop'], relative, candidate, entry['before'],
                    receipt['token'], directory)
            receipt['installed'].append(relative)
            common.write_json(path, receipt)
        for relative in selected:
            if common.digest(read_remote(runtime['hop'], relative)) != (
                manifest['artifacts'][relative]['after']
            ):
                raise RuntimeError('Final runtime hash verification failed')
        idle(runtime)
        if common.db_state(runtime['pg'])['catalog_context'] != manifest['catalog_context']:
            raise RuntimeError('Catalogue context changed during file deployment')
        receipt['status'] = 'VERIFIED'
        release_fence(receipt, path)
        receipt['scheduler_fence_removed'] = True
    except BaseException as error:
        receipt['status'] = 'FAILED_FENCED_ROLLBACK_REQUIRED'
        receipt['failure_type'] = type(error).__name__
        raise RuntimeError(
            f'Performance rollout stopped; rollback protected receipt {path}') from error
    finally:
        receipt['finished_at'] = datetime.now(UTC).isoformat()
        common.write_json(path, receipt)
    return path


def rollback(receipt_path: Path, runtime: dict[str, str]) -> Path:
    receipt = json.loads(receipt_path.read_bytes())
    if receipt.get('kind') != 'PERFORMANCE_ARTIFACT_ONLY' or receipt.get('version') != 1:
        raise RuntimeError('Unrecognized performance receipt')
    if receipt['containers'] != runtime:
        raise RuntimeError('Rollback runtime identity changed')
    selected = artifacts(list(receipt['artifacts']))
    idle(runtime)
    # Validate every byte before restoring anything. The current artifact may be
    # either pre-rename or post-rename after an interruption.
    current = {}
    for relative in selected:
        entry = receipt['artifacts'][relative]
        backup = receipt_path.parent / 'before' / relative
        if common.digest(backup.read_bytes()) != entry['before']:
            raise RuntimeError('Rollback artifact backup hash mismatch')
        current[relative] = common.digest(read_remote(runtime['hop'], relative))
        if current[relative] not in (entry['before'], entry['after']):
            raise RuntimeError('Later runtime drift prevents exact rollback')
    own_fence(receipt, receipt_path)
    receipt['status'] = 'ROLLING_BACK'
    common.write_json(receipt_path, receipt)
    try:
        for relative in reversed(selected):
            entry = receipt['artifacts'][relative]
            if current[relative] == entry['before']:
                continue
            replace(runtime['hop'], relative,
                    (receipt_path.parent / 'before' / relative).read_bytes(), entry['after'],
                    receipt['token'], receipt_path.parent)
        if any(common.digest(read_remote(runtime['hop'], relative)) !=
               receipt['artifacts'][relative]['before'] for relative in selected):
            raise RuntimeError('Rollback verification failed')
        release_fence(receipt, receipt_path)
        receipt['status'] = 'ROLLED_BACK'
        receipt['scheduler_fence_removed'] = True
    except BaseException as error:
        receipt['status'] = 'ROLLBACK_FAILED_FENCED'
        receipt['failure_type'] = type(error).__name__
        raise RuntimeError(
            'Rollback stopped; retain fence and inspect protected receipt') from error
    finally:
        common.write_json(receipt_path, receipt)
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('plan', 'apply', 'rollback'))
    parser.add_argument('manifest_or_receipt', nargs='?', type=Path)
    parser.add_argument('--artifact', action='append', default=[])
    args = parser.parse_args()
    if args.mode == 'plan' and (args.manifest_or_receipt or not args.artifact):
        parser.error('plan requires explicit --artifact values and no manifest')
    if args.mode != 'plan' and (not args.manifest_or_receipt or args.artifact):
        parser.error('apply/rollback require exactly a manifest/receipt, with no --artifact')
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(STATE / 'refresh.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Scheduler lock is busy') from None
        runtime = common.containers()
        if args.mode == 'plan':
            print(plan(runtime, artifacts(args.artifact)))
        elif args.mode == 'apply':
            print(apply(args.manifest_or_receipt, runtime))
        else:
            print(rollback(args.manifest_or_receipt, runtime))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
