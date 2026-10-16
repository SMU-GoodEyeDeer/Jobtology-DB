"""Strict benchmark evidence and matched variant isolation checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "benchmark_archived_routine", ROOT / "hop/operations/benchmark_archived_routine.py"
)
assert SPEC and SPEC.loader
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def log_evidence() -> str:
    lines = []
    for name in bench.STAGES:
        if name in (
            "load_entity_names",
            "verify_entity_names",
            "load_references",
            "verify_references",
            "load_posting_dates",
            "verify_posting_dates",
        ):
            reader = "Read posting dates" if "posting_dates" in name else "Read entity names"
            lines.append(f"{reader}.0 - Finished processing (I=0, O=0, R=1, W=8434, U=0, E=0)")
        else:
            lines.append("Complete.0 - Finished processing (I=0, O=0, R=1, W=1, U=0, E=0)")
        lines.append(f"{name} - Pipeline duration : 1.25 seconds")
    return "\n".join(lines)


def test_complete_workflow_reads_are_independently_accounted():
    result = bench.parse_workflow(log_evidence())
    assert len(result["reader_counters"]) == 6
    assert all(counter["W"] == 8434 for counter in result["reader_counters"].values())
    assert result["stage_seconds"]["verification"] == 5
    assert result["native_pipeline_seconds"] == len(bench.STAGES) * 1.25


@pytest.mark.parametrize("change", ["missing", "duplicate", "error", "counterless"])
def test_incomplete_or_failed_workflow_evidence_rejected(change):
    log = log_evidence()
    if change == "missing":
        log = log.replace("finish_batch - Pipeline duration : 1.25 seconds", "")
    elif change == "duplicate":
        log += "\nfinish_batch - Pipeline duration : 1.25 seconds"
    elif change == "error":
        log = log.replace("E=0", "E=1", 1)
    else:
        log = "\n".join(line for line in log.splitlines() if "Finished processing" not in line)
    with pytest.raises((ValueError, RuntimeError)):
        bench.parse_workflow(log)


def test_archive_is_never_staged_as_source_and_candidates_are_frozen(tmp_path, monkeypatch):
    args = SimpleNamespace(
        backup=tmp_path / "archive.dump",
        backup_sha256="a" * 64,
        run_id="exact",
        candidate_sql=[tmp_path / "candidate.sql"],
    )
    args.backup.write_bytes(b"archive")
    args.candidate_sql[0].write_text("SELECT 1;")
    fixture = object.__new__(bench.RoutineFixture)
    fixture.work = tmp_path / "private"
    fixture.work.mkdir()
    fixture.args = args
    fixture.input = args.backup
    fixture.receipt = {"candidate_artifact_sha256": {}}
    seen = []

    def stage(self):
        seen.append(self.input.read_bytes())
        (self.work / "inputs").mkdir()
        (self.work / "inputs/sample.json").write_bytes(self.input.read_bytes())

    monkeypatch.setattr(bench.Fixture, "stage", stage)
    fixture.stage()
    assert seen == [b"{}"]
    assert fixture.input == args.backup
    assert not (fixture.work / "inputs/sample.json").exists()
