"""Owner readback must reject missing, mismatched and ambiguous native counters."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("owner_qualification",
    Path(__file__).resolve().parents[2] / "hop/operations/qualify_native_owner_counters.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def log(rows=501, batches=2):
    def counter(name, read, written):
        return f" - {name}.0 - Finished processing (I=0,O=0,R={read},W={written},U=0,E=0)\n"
    return (" prior - Pipeline duration : 1 seconds\n"
        + counter("Read entity names", 1, rows)
        + counter("Set entity names", rows, batches)
        + counter("Check result", batches, batches)
        + counter("Complete", batches, batches)
        + " clear_source_edges - Pipeline duration : 2 seconds\n")


def test_partial_batch_owner_counters():
    result = module.owner_counters(log(), "clear_source_edges", 501, 500)
    assert result["expected_batches"] == 2
    assert result["final_batch_rows"] == 1


@pytest.mark.parametrize("text", [log(rows=500), log(batches=1), log() + log(),
    log().replace("Set entity names.0", "Missing.0")])
def test_owner_readback_rejects_incomplete_scope(text):
    with pytest.raises(RuntimeError):
        module.owner_counters(text, "clear_source_edges", 501, 500)
