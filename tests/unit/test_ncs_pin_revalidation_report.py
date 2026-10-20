from __future__ import annotations

import copy
import importlib.util
import json
import stat
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ncs_pin_report", ROOT / "hop/operations/report_ncs_pin_revalidation.py"
)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)
CODE = "20010201"


def snapshot():
    return {
        "observed_at": "2026-10-20T15:30:00+00:00",
        "read_only": "on", "isolation": "repeatable read", "latest_ready_ncs": "current",
        "runs": [{"ncs_run_id": pin, "state": "READY", "mode": "FULL",
                  "source_id": "ncs_competency", "run_unit_count": 2,
                  "unique_unit_codes": True, "hierarchical": True} for pin in ("old", "current")],
        "hashes": [{"run_id": pin, "occupation_code": CODE, "catalog_hash": "frozen",
                    "unit_count": 2, "valid_hierarchy": True} for pin in ("old", "current")],
        "cohorts": [{"ncs_run_id": "old", "occupation_code": CODE, "association_count": 7,
                     "published_hash": "frozen", "published_hash_consistent": True,
                     "frozen_catalog_hash": "frozen"}],
    }


def classify(value):
    return report.build_report(value, "current", [CODE])["rows"][0]


def test_equal_pin_rollover_is_report_only_and_counts_associations():
    value = snapshot()
    original = copy.deepcopy(value)
    result = report.build_report(value, "current", [CODE])
    assert result["rows"][0]["status"] == "PIN_CHANGED_CONTENT_EQUAL"
    assert result["counts"]["backend_associations"]["PIN_CHANGED_CONTENT_EQUAL"] == 7
    assert result["counts"]["cohort_occupation_rows"]["PIN_CHANGED_CONTENT_EQUAL"] == 1
    assert "v2 context" in result["limitations"][0]
    assert "STALE" in result["limitations"][1]
    assert datetime.fromisoformat(result["observed_at"]).utcoffset() is not None
    assert result["observation_basis"] == (
        "Database transaction timestamp; not source collection time"
    )
    assert value == original


def test_changed_and_missing_targets_have_distinct_statuses():
    value = snapshot()
    value["hashes"][1]["catalog_hash"] = "changed-definition"
    assert classify(value)["status"] == "TARGET_CHANGED"
    value["hashes"].pop()
    assert classify(value)["status"] == "TARGET_MISSING"
    assert classify(value)["current_recomputed_sql036_catalog_hash"] is None


@pytest.mark.parametrize("change,issue", [
    ("old_hash", "ORIGINAL_HASH_NOT_PROVEN"),
    ("old_archive", "ORIGINAL_ARCHIVE_UNAVAILABLE"),
    ("current_archive", "CURRENT_ARCHIVE_UNAVAILABLE"),
    ("duplicate_units", "CURRENT_UNIT_CODES_NOT_UNIQUE_OR_VALID"),
    ("hierarchy", "CURRENT_HIERARCHY_INVALID_OR_INCONSISTENT"),
    ("published_context_hash", "PUBLISHED_HASH_DIFFERS"),
    ("wrong_current", "EXPLICIT_CURRENT_PIN_IS_NOT_LATEST_READY"),
    ("failed_run", "CURRENT_RUN_NOT_READY_NCS"),
])
def test_incomplete_or_inconsistent_proof_is_unverifiable(change, issue):
    value = snapshot()
    if change == "old_hash":
        value["hashes"][0]["catalog_hash"] = "different-historical-formula"
    elif change == "old_archive":
        value["hashes"].pop(0)
        value["runs"][0]["run_unit_count"] = None
    elif change == "current_archive":
        value["hashes"].pop()
        value["runs"][1]["run_unit_count"] = None
    elif change == "duplicate_units":
        value["runs"][1]["unique_unit_codes"] = False
    elif change == "hierarchy":
        value["hashes"][1]["valid_hierarchy"] = False
    elif change == "published_context_hash":
        value["cohorts"][0]["published_hash"] = "v2-context-is-not-sql036-catalog"
    elif change == "wrong_current":
        value["latest_ready_ncs"] = "newer-ready-run"
    elif change == "failed_run":
        value["runs"][1]["state"] = "FAILED"
    row = classify(value)
    assert row["status"] == "UNVERIFIABLE"
    assert any(i.startswith(issue) for i in row["issues"])


def test_missing_backend_association_and_multiple_original_pins_are_explicit():
    value = snapshot()
    result = report.build_report(value, "current", ["20010202", CODE])
    assert result["rows"][1]["issues"] == ["NO_PUBLISHED_BACKEND_NCS_ASSOCIATION"]
    second = {**value["cohorts"][0], "ncs_run_id": "older", "association_count": 3}
    value["cohorts"].append(second)
    result = report.build_report(value, "current", [CODE])
    assert len(result["rows"]) == 2
    assert result["counts"]["backend_associations"]["UNVERIFIABLE"] == 3
    assert result["counts"]["backend_associations"]["PIN_CHANGED_CONTENT_EQUAL"] == 7


def test_report_is_deterministic_under_snapshot_order_changes():
    value = snapshot()
    first = report.build_report(value, "current", ["20010202", CODE])
    for key in ("runs", "hashes", "cohorts"):
        value[key].reverse()
    assert report.build_report(value, "current", [CODE, "20010202"]) == first


@pytest.mark.parametrize("current,codes", [
    ("LATEST", [CODE]), ("run'; SELECT secret; --", [CODE]),
    ("current", []), ("current", [CODE] * 101), ("current", [CODE, CODE]),
    ("current", ["15-1252.00"]), ("current", ["12345678' OR true"]),
])
def test_scope_is_explicit_bounded_and_ncs_only(current, codes):
    with pytest.raises(ValueError):
        report.validate_scope(current, codes)


def test_capture_is_one_read_only_transaction_with_parameterized_scope(monkeypatch):
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, sql, parameters=None):
            calls.append((sql, parameters))
            return SimpleNamespace(fetchone=lambda: [snapshot()])

    def connect(dsn, **options):
        assert dsn == "private-dsn"
        assert options == {"autocommit": True, "connect_timeout": 10}
        return Connection()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    assert report.capture("private-dsn", "current", [CODE]) == snapshot()
    assert calls[0][0] == "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert calls[1][0] == "SET LOCAL statement_timeout='120s'"
    assert calls[2] == (report.SNAPSHOT_SQL, {"current": "current", "codes": [CODE]})
    assert calls[3][0] == "ROLLBACK"
    formula = "enrichment.hash(jsonb_agg(normalized ORDER BY normalized->>'code')::text)"
    assert formula in calls[2][0]
    assert "prepare_metadata" not in calls[2][0]


def test_receipt_is_private_exclusive_and_symlink_safe(tmp_path):
    path = tmp_path / "private" / "receipt.json"
    report.write_receipt(path, {"status": "UNVERIFIABLE"})
    assert json.loads(path.read_text()) == {"status": "UNVERIFIABLE"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        report.write_receipt(path, {})
    link = tmp_path / "receipt-link.json"
    link.symlink_to(path)
    with pytest.raises(FileExistsError):
        report.write_receipt(link, {})


def test_driver_errors_never_print_dsn_or_exception_context(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(report.DSN_ENV, "postgresql://secret-user:secret-pass@private/db")

    def fail(*_args):
        raise RuntimeError("postgresql://secret-user:secret-pass@private/db")

    monkeypatch.setattr(report, "capture", fail)
    with pytest.raises(SystemExit) as exit_info:
        report.main(["--current-run-id", "current", "--occupation-codes", CODE,
                     "--output", str(tmp_path / "report.json")])
    assert exit_info.value.code == 1
    assert "secret" not in capsys.readouterr().err
    assert not (tmp_path / "report.json").exists()
