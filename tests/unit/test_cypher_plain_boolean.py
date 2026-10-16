import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hop/operations'))
from benchmark_archived_routine import cypher_plain_true


@pytest.mark.parametrize('output', ['TRUE', 'true', 'predicate\nTRUE\n'])
def test_cypher_shell_true(output):
    assert cypher_plain_true(output)


@pytest.mark.parametrize('output', ['FALSE', 'false', '', 'predicate\n', 'null'])
def test_cypher_shell_non_true(output):
    assert not cypher_plain_true(output)
