"""Offline deployment race/recovery and archived profiler contract checks."""
# Pytest monkeypatch stubs and dynamic script imports have deliberately loose types.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


def load(name: str) -> Any:
    directory = Path(__file__).resolve().parents[2] / 'hop/operations'
    spec = importlib.util.spec_from_file_location(name, directory / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rollout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'hop/operations'))
    module = load('deploy_performance_runtime')
    root, state = tmp_path / 'source', tmp_path / 'state'
    root.mkdir()
    state.mkdir()
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(module, 'STATE', state)
    selected = module.ALLOWLIST[:2]
    runtime = {'hop': 'hop-test', 'pg': 'pg-test'}
    remote: dict[str, bytes] = {
        relative: b'<pipeline><name>old</name></pipeline>' for relative in selected}
    for relative in selected:
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b'<pipeline><name>new</name></pipeline>')
    monkeypatch.setattr(module, 'read_remote', lambda _, relative: remote[relative])
    monkeypatch.setattr(module, 'idle', lambda _: None)
    monkeypatch.setattr(module.common, 'db_state', lambda _: {'catalog_context': {'id': 'fixed'}})
    replacements: list[str] = []

    def replace(_: str, relative: str, data: bytes, expected: str, *args: Any) -> None:
        assert module.common.digest(remote[relative]) == expected
        replacements.append(relative)
        remote[relative] = data

    monkeypatch.setattr(module, 'replace', replace)
    manifest = module.plan(runtime, selected)
    return module, runtime, manifest, remote, replacements


def test_exact_subset_install_and_rollback(rollout: tuple[Any, ...]) -> None:
    module, runtime, manifest, remote, replacements = rollout
    receipt = module.apply(manifest, runtime)
    report = json.loads(receipt.read_text())
    assert report['status'] == 'VERIFIED'
    assert report['executed_sql'] is False and report['executed_jobs'] is False
    assert report['scheduler_fence_removed'] is True
    assert replacements == list(module.ALLOWLIST[:2])
    assert not (module.STATE / module.FENCE_NAME).exists()
    module.rollback(receipt, runtime)
    assert json.loads(receipt.read_text())['status'] == 'ROLLED_BACK'
    assert all(b'old' in value for value in remote.values())
    assert not (module.STATE / module.FENCE_NAME).exists()


def test_stale_plan_refuses_mutation(rollout: tuple[Any, ...]) -> None:
    module, runtime, manifest, remote, replacements = rollout
    remote[module.ALLOWLIST[0]] = b'<pipeline><name>other</name></pipeline>'
    with pytest.raises(RuntimeError, match='Artifacts changed'):
        module.apply(manifest, runtime)
    assert replacements == []
    assert not list(module.STATE.glob('performance-runtime-applied-*'))


def test_local_candidate_race_leaves_recoverable_fence(
    rollout: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, runtime, manifest, _remote, replacements = rollout
    original = module.own_fence

    def race(receipt: Any, path: Path) -> None:
        original(receipt, path)
        (module.ROOT / module.ALLOWLIST[0]).write_bytes(b'<pipeline><name>raced</name></pipeline>')

    monkeypatch.setattr(module, 'own_fence', race)
    with pytest.raises(RuntimeError, match='rollback protected receipt'):
        module.apply(manifest, runtime)
    receipt = next(module.STATE.glob('performance-runtime-applied-*/receipt.json'))
    assert json.loads(receipt.read_text())['status'] == 'FAILED_FENCED_ROLLBACK_REQUIRED'
    assert replacements == []
    assert (module.STATE / module.FENCE_NAME).exists()
    monkeypatch.setattr(module, 'own_fence', original)
    module.rollback(receipt, runtime)
    assert not (module.STATE / module.FENCE_NAME).exists()


def test_interrupted_rename_recovers_exact_bytes(
    rollout: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, runtime, manifest, remote, _ = rollout
    original = module.replace

    def interrupt(*args: Any) -> None:
        original(*args)
        raise RuntimeError('Interrupted after atomic rename before acknowledgement')

    monkeypatch.setattr(module, 'replace', interrupt)
    with pytest.raises(RuntimeError, match='rollback protected receipt'):
        module.apply(manifest, runtime)
    receipt = next(module.STATE.glob('performance-runtime-applied-*/receipt.json'))
    value = json.loads(receipt.read_text())
    assert value['attempted'] == [module.ALLOWLIST[0]] and value['installed'] == []
    assert b'new' in remote[module.ALLOWLIST[0]]
    monkeypatch.setattr(module, 'replace', original)
    module.rollback(receipt, runtime)
    assert all(b'old' in data for data in remote.values())


def test_later_drift_prevents_rollback(rollout: tuple[Any, ...]) -> None:
    module, runtime, manifest, remote, replacements = rollout
    receipt = module.apply(manifest, runtime)
    replacements.clear()
    remote[module.ALLOWLIST[0]] = b'<pipeline><name>later</name></pipeline>'
    with pytest.raises(RuntimeError, match='Later runtime drift'):
        module.rollback(receipt, runtime)
    assert replacements == []


def test_foreign_fence_refuses_apply(rollout: tuple[Any, ...]) -> None:
    module, runtime, manifest, _, replacements = rollout
    fence = module.STATE / module.FENCE_NAME
    fence.write_text(json.dumps({'token': 'foreign'}))
    with pytest.raises(RuntimeError, match='existing fenced operation'):
        module.apply(manifest, runtime)
    assert replacements == []
    assert json.loads(fence.read_text()) == {'token': 'foreign'}


def test_rollout_fixed_scope_and_xml(rollout: tuple[Any, ...]) -> None:
    module, runtime, _, _, _ = rollout
    with pytest.raises(ValueError):
        module.artifacts(['graph/sql/002_batchfree_source_graph.sql'])
    with pytest.raises(ValueError):
        module.artifacts([module.ALLOWLIST[0]] * 2)
    source = module.ROOT / module.ALLOWLIST[0]
    source.unlink()
    source.symlink_to(module.ROOT / module.ALLOWLIST[1])
    with pytest.raises(RuntimeError, match='symlink'):
        module.snapshot(runtime, module.ALLOWLIST[:2])


def test_canonical_retention_sql_is_only_copied_never_executed(
    rollout: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, runtime, _, remote, replacements = rollout
    canonical = module.ROOT.parent / 'operations.sql'
    canonical.write_bytes(b'CREATE FUNCTION guard() RETURNS void LANGUAGE plpgsql SET jit=off;\n')
    monkeypatch.setattr(module, 'CANONICAL_OPERATIONS', canonical)
    source = module.ROOT / module.SQL_ARTIFACT
    source.parent.mkdir(parents=True)
    source.write_bytes(canonical.read_bytes())
    remote[module.SQL_ARTIFACT] = b'old SQL artifact\n'
    selected = module.artifacts([module.SQL_ARTIFACT])
    manifest = module.plan(runtime, selected)
    receipt = module.apply(manifest, runtime)
    report = json.loads(receipt.read_text())
    assert replacements == [module.SQL_ARTIFACT]
    assert remote[module.SQL_ARTIFACT] == canonical.read_bytes()
    assert report['executed_sql'] is False and report['executed_jobs'] is False
    module.rollback(receipt, runtime)
    assert remote[module.SQL_ARTIFACT] == b'old SQL artifact\n'
    source.write_bytes(canonical.read_bytes() + b'-- drift\n')
    replacements.clear()
    with pytest.raises(RuntimeError, match='canonical SQL'):
        module.plan(runtime, selected)
    assert replacements == []


def test_profile_ids_and_plan_summary() -> None:
    module = load('profile_archived_postgres')
    for values in ([], ['LATEST'], ['ALL_CHECKPOINTED'], ['x', 'x'], ["x';drop"]):
        with pytest.raises(ValueError):
            module.safe_runs(values)
    assert module.safe_runs(['exact:run-1']) == ['exact:run-1']
    value = module.plan_summary({'Execution Time': 10, 'Plan': {
        'Node Type': 'Aggregate', 'Plan Rows': 1, 'Actual Rows': 1, 'Actual Loops': 1,
        'Shared Hit Blocks': 42, 'Plans': [{'Node Type': 'Index Scan', 'Plan Rows': 1,
                                         'Actual Rows': 1000, 'Actual Loops': 2}],
    }})
    assert value['buffers']['Shared Hit Blocks'] == 42
    assert value['largest_row_estimate_errors'][0]['ratio'] == 1000
    assert 'proof_validation' not in module.queries('x', False, False)
    assert 'proof_validation' in module.queries('x', True, False)
    assert 'entities' not in module.queries('x', True, False)


def test_nested_log_stream_captures_before_rotation_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load('profile_archived_postgres')
    calls: list[list[str]] = []

    class Process:
        def wait(self, **_: Any) -> int:
            return 0

    def start(command: list[str], **kwargs: Any) -> Process:
        calls.append(command)
        kwargs['stdout'].write(b'first plan\nlast complete plan\n')
        kwargs['stderr'].write(b'nested plan evidence\n')
        return Process()

    monkeypatch.setattr(module.subprocess, 'Popen', start)
    stream = module.LogStream('owned-isolated-container', tmp_path)
    assert calls == [['docker', 'logs', '--follow', 'owned-isolated-container']]
    assert stream.close() is True
    assert all(file.closed for file in stream.files)
    assert (tmp_path / 'postgres-nested-plans.stdout').read_bytes().endswith(
        b'last complete plan\n')
    assert (tmp_path / 'postgres-nested-plans.stderr').read_bytes() == b'nested plan evidence\n'


@pytest.mark.parametrize('failure', ['drain', 'removal', 'primary'])
def test_profile_cleanup_failure_exits_nonzero_and_preserves_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    module = load('profile_archived_postgres')

    class Process:
        returncode = 1 if failure == 'removal' else 0

        def poll(self) -> None:
            return None

    class Stream:
        process = Process()

        def close(self) -> bool:
            if failure == 'primary':
                raise RuntimeError('Cleanup failure must not mask original SQL failure')
            return failure != 'drain'

    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: Process())
    receipt = {'status': 'PASSED'}
    if failure == 'primary':
        receipt.update(status='FAILED', failure_type='OriginalSqlFailure')
    module.cleanup_profile('owned-isolated-container', tmp_path, Stream(), receipt)
    assert receipt['status'] == 'FAILED'
    if failure == 'primary':
        assert receipt['failure_type'] == 'OriginalSqlFailure'
    with pytest.raises(RuntimeError, match='Archived profile failed'):
        module.require_completed_profile(receipt, tmp_path / 'saved-receipt.json')


def test_idle_refuses_other_migration_and_unfinished_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'hop/operations'))
    module = load('deploy_performance_runtime')
    monkeypatch.setattr(module, 'STATE', tmp_path)
    monkeypatch.setattr(module.common, 'idle_cli', lambda _: None)
    monkeypatch.setattr(module.dates, 'require_idle', lambda _: None)
    monkeypatch.setattr(module.common, 'host_bytes', lambda:
        b'[[ ! -e "$STATE_DIR/flat-ontology-migration.pending" ]] || exit 0')
    active = {'flat_loads': 0, 'source_projections': 0}
    monkeypatch.setattr(module.deployment, 'sql', lambda *_: json.dumps(active))
    runtime = {'hop': 'hop-test', 'pg': 'pg-test'}
    module.idle(runtime)
    pending = tmp_path / 'batchfree-migration.pending'
    pending.write_text('{}')
    with pytest.raises(RuntimeError, match='interrupted batch-free'):
        module.idle(runtime)
    pending.unlink()
    active['source_projections'] = 1
    with pytest.raises(RuntimeError, match='unfinished'):
        module.idle(runtime)
    active['source_projections'] = 0
    active['flat_loads'] = 1
    with pytest.raises(RuntimeError, match='unfinished'):
        module.idle(runtime)


def test_private_readback_keeps_cypher_and_restricts_exact_verified_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'hop/operations'))
    module = load('prepare_performance_readback')
    monkeypatch.setattr(module, 'STATE', tmp_path)
    original = (module.ROOT / module.ONTOLOGY[0]).read_bytes()
    path = module.prepare('load-1', 'release-1', 'database-1', 'ALL_CHECKPOINTED')
    manifest = json.loads(path.read_text())
    assert manifest['executed_queries'] is False and manifest['production_writes'] == 0
    assert len(manifest['pipelines']) == 5
    assert manifest['source_compatibility_alias']['artifact'] == 'graph/verify_records.hpl'
    for relative, evidence in manifest['pipelines'].items():
        assert evidence['cypher_sha256']
        copy = Path(evidence['path']).read_text()
        assert '<read_only>Y</read_only>' in copy
        assert '<name>NEO4J_CONNECTION</name>' in copy
        if relative in module.ONTOLOGY:
            assert "l.state='VERIFIED'" in copy
            assert "l.state IN ('RUNNING','STAGED')" not in copy
            assert 'current_pin.load_id=l.load_id' in copy
            assert 'PERFORMANCE_READBACK_LOAD_ID' in copy
            assert '?' not in evidence['count_sql']
    assert (module.ROOT / module.ONTOLOGY[0]).read_bytes() == original
    preflight = Path(manifest['preflight_sql']).read_text()
    assert 'BEGIN READ ONLY' in preflight
    assert 'expected_owner_groups' in preflight and 'expected_property_rows' in preflight


def test_native_reader_summary_rejects_empty_missing_and_errors() -> None:
    module = load('prepare_performance_readback')
    log = ('Expected properties.0 - Finished processing (I=12, O=0, R=1, W=12, U=0, E=0)\n'
           'Property operation.0 - Finished processing (I=0,O=0,R=12,W=1,U=0,E=0)')
    assert module.log_reader_rows(log, 'Expected properties') == 12
    for malformed in (log.replace('E=0', 'E=1'), '', log + '\n' + log):
        with pytest.raises(RuntimeError):
            module.log_reader_rows(malformed, 'Expected properties')
    assert module.pipeline_duration('verify_node_scalars - Pipeline duration : 79.438 seconds',
                                    'verify_node_scalars') == 79.438
    with pytest.raises(RuntimeError, match='duration'):
        module.pipeline_duration('', 'verify_node_scalars')


@pytest.mark.parametrize('rows', [1, 500, 501, 10001, 60001])
def test_native_verifier_requires_every_batch_and_success(rows: int) -> None:
    module = load('prepare_performance_readback')
    evidence = {'operation_name': 'Property operation', 'filter_name': 'Verify result',
                'success_name': 'Verified', 'batch_size': '500'}
    batches = (rows + 499) // 500
    log = ('Property operation.0 - Finished processing '
           f'(I=0,O={rows},R={rows},W={batches},U=0,E=0)\n'
           'Verify result.0 - Finished processing '
           f'(I=0,O=0,R={batches},W={batches},U=0,E=0)\n'
           'Verified.0 - Finished processing '
           f'(I=0,O=0,R={batches},W={batches},U=0,E=0)')
    assert module.verifier_counters(log, evidence, rows)['expected_batches'] == batches
    for broken in (log.replace(f'R={rows},W={batches}', f'R={rows},W={batches-1}', 1),
                   log.replace(f'R={batches},W={batches}', f'R={batches},W=0'),
                   log.replace('E=0', 'E=1'), log + '\n' + log):
        with pytest.raises(RuntimeError):
            module.verifier_counters(broken, evidence, rows)


@pytest.mark.parametrize('wrong_rows', [False, True])
def test_readback_executor_requires_full_native_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong_rows: bool,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'hop/operations'))
    module = load('prepare_performance_readback')
    monkeypatch.setattr(module, 'STATE', tmp_path)
    manifest = module.prepare('load-1', 'release-1', 'database-1', None)
    artifacts = tmp_path / 'artifact-receipt.json'
    artifacts.write_text('{}')
    monkeypatch.setattr(module.rollout, 'idle', lambda _: None)
    monkeypatch.setattr(module, 'verified_inputs', lambda *_: None)
    context = {'load_id': 'load-1', 'state': 'VERIFIED'}
    monkeypatch.setattr(module, 'current_context', lambda *_: context)
    counts = {relative: {'expected_owner_groups': 12, 'expected_property_rows': 50}
              for relative in module.ONTOLOGY}
    monkeypatch.setattr(module.deployment, 'sql', lambda *_: json.dumps(counts))

    def native(_: str, path: Path, directory: Path, label: str) -> Path:
        log = directory / (label + '.log')
        log.write_text('Expected properties.0 - Finished processing '
                       f'(I=12,O=0,R=1,W={0 if wrong_rows else 12},U=0,E=0)\n'
                       'Property operation.0 - Finished processing '
                       '(I=0,O=12,R=12,W=1,U=0,E=0)\n'
                       'Verify result.0 - Finished processing (I=0,O=0,R=1,W=1,U=0,E=0)\n'
                       'Verified.0 - Finished processing (I=0,O=0,R=1,W=1,U=0,E=0)\n'
                       + label + ' - Pipeline duration : 0.25 seconds')
        return log

    monkeypatch.setattr(module.dates, 'temporary_native', native)
    if wrong_rows:
        with pytest.raises(RuntimeError, match='Read-only verification failed'):
            module.execute(manifest, artifacts, {'hop': 'hop-test', 'pg': 'pg-test'})
        report = next(tmp_path.glob('performance-readback-executed-*/receipt.json'))
        assert json.loads(report.read_text())['status'] == 'FAILED'
    else:
        report = module.execute(manifest, artifacts, {'hop': 'hop-test', 'pg': 'pg-test'})
        value = json.loads(report.read_text())
        assert value['status'] == 'VERIFIED' and len(value['pipelines']) == 4
        assert value['production_writes'] == 0
        assert all(p['actual_reader_rows'] == 12 for p in value['pipelines'])
        assert all(p['native_pipeline_seconds'] == .25 for p in value['pipelines'])
        assert all(p['native_counters']['expected_batches'] == 1 for p in value['pipelines'])


def test_readback_binds_deployed_receipt_and_private_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'hop/operations'))
    module = load('prepare_performance_readback')
    monkeypatch.setattr(module, 'STATE', tmp_path)
    path = module.prepare('load-1', 'release-1', 'database-1', 'ALL_CHECKPOINTED')
    manifest = json.loads(path.read_text())
    runtime = {'hop': 'hop-test', 'pg': 'pg-test'}
    selected = (*module.ONTOLOGY, *module.SOURCE, module.SOURCE_ALIAS)
    receipt = {'kind': 'PERFORMANCE_ARTIFACT_ONLY', 'status': 'VERIFIED',
               'containers': runtime, 'artifacts': {relative: {
                   'after': module.common.digest((module.ROOT / relative).read_bytes())}
                   for relative in selected}}
    monkeypatch.setattr(module.rollout, 'read_remote',
                        lambda _, relative: (module.ROOT / relative).read_bytes())
    module.verified_inputs(manifest, receipt, runtime)
    pipeline = Path(manifest['pipelines'][module.ONTOLOGY[0]]['path'])
    pipeline.write_bytes(pipeline.read_bytes() + b'\n')
    with pytest.raises(RuntimeError, match='copy hash changed'):
        module.verified_inputs(manifest, receipt, runtime)
