"""Matched capture must commit complete runs and reject already populated proofs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "benchmark_first_capture", ROOT / "hop/operations/benchmark_first_capture.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


class Backend:
    def __init__(self):
        self.calls = []

    def execute(self, query):
        self.calls.append(query)
        return "t"


def test_atomic_and_per_run_commit_same_complete_ordered_scopes():
    atomic, per_run = Backend(), Backend()
    ops.capture(atomic, ["real-a", "real-b"], "atomic")
    ops.capture(per_run, ["real-a", "real-b"], "per-run")
    assert [q for q in atomic.calls if q.startswith("SELECT")] == [
        q for q in per_run.calls if q.startswith("SELECT")
    ]
    assert atomic.calls.count("BEGIN") == atomic.calls.count("COMMIT") == 1
    assert per_run.calls.count("BEGIN") == per_run.calls.count("COMMIT") == 2
    assert "finish_source_graph_projection('real-a')" in per_run.calls[2]
    assert per_run.calls[3] == "COMMIT"
    assert per_run.calls[4] == "BEGIN"


def test_failed_capture_keeps_completed_operation_and_never_commits(monkeypatch):
    backend = Backend()
    original = backend.execute

    def failing(query):
        if "finish_source_graph" in query:
            raise RuntimeError("bounded failure")
        return original(query)

    monkeypatch.setattr(backend, "execute", failing)
    sample = {}
    with pytest.raises(RuntimeError, match="bounded"):
        ops.capture(backend, ["real-a", "real-b"], "atomic", sample)
    assert [entry["result"] for entry in sample["operations"]] == ["PASSED", "FAILED"]
    assert "COMMIT" not in backend.calls


def test_first_capture_refuses_existing_evidence_even_without_projection(monkeypatch):
    monkeypatch.setattr(
        ops,
        "proof_state",
        lambda *args: {
            "source_graph_projection": {"n": 0},
            "source_graph_record_evidence": {"n": 1},
        },
    )
    with pytest.raises(RuntimeError, match="no selected proof"):
        ops.absent_proofs(Backend(), ["real-a"])
