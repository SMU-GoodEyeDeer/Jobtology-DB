"""Bounded profiling failure evidence and rollback transaction guarantees."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hop/operations'))
SPEC = importlib.util.spec_from_file_location('profile_replay_reads',
                                             ROOT / 'hop/operations/profile_replay_reads.py')
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


class Backend:
    def __init__(self, state='57014'):
        self.calls = []
        self.state = state

    def execute(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if query.startswith('EXPLAIN'):
            raise ops.SqlFailure(self.state)
        return ''


def test_direct_replay_timeout_retained_and_transaction_rolled_back():
    backend, sample = Backend(), {}
    ops.direct_replay(backend, 'real-archive-run', sample)
    assert sample['result'] == 'TIMED_OUT'
    assert sample['sqlstate'] == '57014'
    assert sample['client_wall_seconds'] >= 0
    assert backend.calls[0][0] == 'BEGIN'
    assert backend.calls[-1][0] == 'ROLLBACK'
    assert backend.calls[1][1]['allow_timeout'] is True


def test_unexpected_sql_failure_does_not_become_success():
    backend, sample = Backend('XX001'), {}
    with pytest.raises(ops.SqlFailure):
        ops.direct_replay(backend, 'real-archive-run', sample)
    assert sample['result'] == 'FAILED'
    assert backend.calls[-1][0] == 'ROLLBACK'


def test_server_time_is_distinct_from_client_wall():
    class Planned:
        def execute(self, query, **kwargs):
            return '[{"Execution Time":125,"Plan":{"Node Type":"Function Scan",' \
                   '"Actual Rows":1,"Shared Hit Blocks":27,"Shared Read Blocks":4}}]'
    sample = {}
    ops.explain(Planned(), 'SELECT count(*) FROM a_function()', sample)
    assert sample['result'] == 'PASSED'
    assert sample['plan']['execution_ms'] == 125
    assert sample['plan']['buffers']['Shared Read Blocks'] == 4
    assert 'client_wall_seconds' in sample
