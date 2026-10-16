"""Plan and CPU evidence parsing for the bounded archive benchmark."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

OPERATIONS = Path(__file__).resolve().parents[2] / 'hop' / 'operations'
sys.path.insert(0, str(OPERATIONS))
spec = importlib.util.spec_from_file_location(
    'profile_postgres_parallelism', OPERATIONS / 'profile_postgres_parallelism.py')
assert spec and spec.loader
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def test_nested_gather_records_actual_worker_launches() -> None:
    plan = {'Plan': {'Node Type': 'Aggregate', 'Plans': [
        {'Node Type': 'Gather', 'Workers Planned': 4, 'Workers Launched': 2,
         'Actual Rows': 3, 'Plans': [{'Node Type': 'Aggregate'}]}]}}
    assert profile.gather_nodes(plan) == [
        {'Node Type': 'Gather', 'Workers Planned': 4, 'Workers Launched': 2, 'Actual Rows': 3}]
    assert profile.gather_nodes({'Plan': {'Node Type': 'Aggregate'}}) == []


def test_cgroup_cpu_preserves_exited_worker_cost() -> None:
    before = {'cpu_stat': {'usage_usec': 100, 'nr_throttled': 2},
              'process_ticks': {'1': {'user_ticks': 3, 'system_ticks': 2},
                                '7': {'user_ticks': 20, 'system_ticks': 1}},
              'memory_bytes': 1000}
    after = {'cpu_stat': {'usage_usec': 600, 'nr_throttled': 3},
             'process_ticks': {'1': {'user_ticks': 4, 'system_ticks': 3}},
             'memory_bytes': 1500}
    value = profile.delta(before, after)
    assert value['cpu_stat'] == {'usage_usec': 500, 'nr_throttled': 1}
    assert value['process_ticks'] == {'1': {'user_ticks': 1, 'system_ticks': 1}}
    assert value['memory_bytes_after'] == 1500


def test_validation_fallback_and_unknown_hooks_are_rejected() -> None:
    import pytest

    digest = 'a' * 32
    hooks = ('local_file_validation_issue', 'jobkorea_ndjson_validation_issue',
             'jobkorea_cs_collision_issue')
    value = {
        'wrappers': {
            'source_graph_validation_issue':
                "md5(pg_get_viewdef('ingestion.validation_issue'::regclass,true))='"
                + digest + "'",
            'source_graph_local_validation_issue':
                "md5(pg_get_viewdef(to_regclass('ingestion.jobkorea_validation_issue'),true))='"
                + digest + "' AND " + ' AND '.join(
                    "md5(pg_get_functiondef(to_regprocedure('ingestion." + name + "()')))='"
                    + digest + "'" for name in hooks),
        },
        'view_hashes': {'validation_issue': digest, 'jobkorea_validation_issue': digest},
        'hook_hashes': dict.fromkeys(hooks, digest),
    }
    assert profile.validation_path(value)['path'] == 'CANONICAL_FAST_PATH'
    value['view_hashes']['validation_issue'] = 'b' * 32
    with pytest.raises(RuntimeError, match='fallback'):
        profile.validation_path(value)
    value['view_hashes']['validation_issue'] = digest
    value['hook_hashes']['unexpected_hook'] = digest
    with pytest.raises(RuntimeError, match='fallback'):
        profile.validation_path(value)


def test_failed_job_sets_have_no_throughput_and_stop_scaling() -> None:
    failed = profile.job_summary([{'status': 'FAILED'}, {'status': 'TIMED_OUT'}], 0.5)
    assert failed == {'attempted_jobs': 2, 'passed_jobs': 0,
                      'jobs_per_second': None, 'scaling_allowed': False}
    partial = profile.job_summary([{'status': 'PASSED'}, {'status': 'FAILED'}], 0.5)
    assert partial['passed_jobs'] == 1
    assert partial['jobs_per_second'] is None
    assert partial['scaling_allowed'] is False
    passed = profile.job_summary([{'status': 'PASSED'}, {'status': 'PASSED'}], 2.0)
    assert passed['jobs_per_second'] == 1.0
    assert passed['scaling_allowed'] is True
