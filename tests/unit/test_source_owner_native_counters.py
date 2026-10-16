"""Replay the actual empty Hop log without weakening nonempty batch acceptance."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "source_owner_native", ROOT / "hop/graph/tests/source_owner_batches_native.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)
EMPTY = (ROOT / "tests/fixtures/owner_batches_empty_pipeline.log").read_text()


def summary(name: str, *, read: int = 0, written: int = 0, errors: int = 0) -> str:
    return f"{name}.0 - Finished processing (I=0, O=0, R={read}, W={written}, U=0, E={errors})\n"


def test_actual_empty_log_records_absence_without_inventing_operation_counts():
    assert ops.owner_counters(EMPTY, 0) == dict(
        counter_status="EMPTY_INPUT_NO_GRAPH_BATCH",
        expected_batches=0,
        operation=None,
        result_filter=None,
        success_sink=None,
    )


def test_available_empty_downstream_summaries_must_be_zero():
    log = EMPTY + "".join(
        summary(name) for name in ("Set entity names", "Check result", "Complete")
    )
    result = ops.owner_counters(log, 0)
    for name in ("operation", "result_filter", "success_sink"):
        assert result[name]["R"] == result[name]["W"] == result[name]["E"] == 0


@pytest.mark.parametrize(
    "additional",
    (
        summary("Set entity names", read=1),
        summary("Check result", written=1),
        summary("Set entity names").replace("I=0", "I=1"),
        summary("Complete", errors=1),
        summary("Set entity names") * 2,
    ),
)
def test_empty_input_does_not_hide_nonzero_errors_or_ambiguous_summaries(additional):
    with pytest.raises(RuntimeError):
        ops.owner_counters(EMPTY + additional, 0)


def test_zero_input_requires_reader_zero_and_pipeline_completion():
    with pytest.raises(RuntimeError, match="zero-row reader"):
        ops.owner_counters(EMPTY.replace("R=1, W=0", "R=1, W=1"), 0)
    with pytest.raises(RuntimeError, match="completion"):
        ops.owner_counters(EMPTY.replace("Execution finished on a local pipeline engine", ""), 0)


def test_nonempty_input_still_requires_every_native_batch_summary():
    with pytest.raises(RuntimeError, match="absent or ambiguous"):
        ops.owner_counters(EMPTY, 1)
