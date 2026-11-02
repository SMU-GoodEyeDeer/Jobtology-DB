"""Replacement cohort identity, independent allocations and fresh-response gates."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[2] / "hop/operations"
sys.path.insert(0, str(OPS))
scope = importlib.import_module("replacement_matching_scope")
onet = importlib.import_module("run_onet_matches")
ncs = importlib.import_module("run_inferred_occupations")


def manifest():
    return {
        "contract_version": "jobkorea-replacement-matching-v1",
        "scope_id": scope.SCOPE,
        "source_id": "jobkorea",
        "source_file_sha256": scope.SOURCE_SHA,
        "posting_count": 5482,
        "job_run_id": scope.JOB_RUN,
        "ncs_run_id": "ncs-exact",
        "ncs_batch_prefix": scope.NCS_PREFIX,
        "onet_task_id": scope.ONET_TASK,
        "target_usd": "10",
        "ceiling_usd": "12",
        "ncs_ceiling_usd": "5",
        "onet_ceiling_usd": "7",
        "reuse_paid_responses": False,
        "pilot_count": 24,
        "cohort_sha256": "a" * 64,
        "onet_catalogue_file_sha256": "b" * 64,
        "onet_catalogue_manifest_sha256": "c" * 64,
        "onet_release_id": "onet-exact",
        "onet_database_id": "database-exact",
        "review_actor": "coordinator",
    }


def write(path, value):
    path.write_text(json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_file_sha256", "d" * 64),
        ("posting_count", 5481),
        ("job_run_id", "historical-jobkorea"),
        ("scope_id", "new-reset-scope"),
        ("ncs_batch_prefix", "arbitrary-"),
        ("onet_task_id", "new-reset-task"),
        ("ceiling_usd", "13"),
        ("ncs_ceiling_usd", "6"),
        ("reuse_paid_responses", True),
        ("ncs_run_id", "LATEST"),
        ("cohort_sha256", "missing"),
        ("review_actor", ""),
    ],
)
def test_reviewed_scope_rejects_source_budget_or_identity_drift(tmp_path, key, value):
    data = manifest()
    data[key] = value
    path = tmp_path / "scope.json"
    digest = write(path, data)
    with pytest.raises(RuntimeError):
        scope.load(path, digest)


def test_scope_bytes_are_bound_and_cannot_be_silently_replaced(tmp_path):
    path = tmp_path / "scope.json"
    digest = write(path, manifest())
    assert scope.load(path, digest) == manifest()
    path.write_text(path.read_text() + "\n")
    with pytest.raises(RuntimeError, match="changed"):
        scope.load(path, digest)


def accounting(ncs_spent="0", onet_spent="0"):
    return {
        "ncs": {"accounted_usd": ncs_spent, "unknown": 0, "foreign_batches": 0},
        "onet": {"accounted_usd": onet_spent, "unknown": 0},
    }


def test_independent_native_channel_allocations_cannot_exceed_combined_ceiling():
    assert sum(scope.CAPS.values()) == scope.CAP == Decimal("12")
    state = accounting("4.99", "6.98")
    assert scope.remaining(state, "ncs") == Decimal("0.01")
    assert scope.remaining(state, "onet") == Decimal("0.02")
    assert scope.remaining(accounting("5", "7"), "ncs") == 0
    for state in (
        accounting("5.001", "0"),
        accounting("0", "7.001"),
        accounting("5", "7.001"),
        accounting("NaN", "0"),
    ):
        with pytest.raises(RuntimeError):
            scope.remaining(state, "ncs")


@pytest.mark.parametrize("channel", ["ncs", "onet"])
def test_unknown_charge_stops_both_channels_even_with_apparently_free_balance(channel):
    state = accounting()
    state[channel]["unknown"] = 1
    for target in ("ncs", "onet"):
        with pytest.raises(RuntimeError, match="Unknown"):
            scope.remaining(state, target)


def test_ledger_query_is_bounded_read_only_and_preserves_historical_ledgers():
    queries = []
    result = scope.state("pg", lambda pg, query: queries.append(query) or json.dumps(accounting()))
    assert result == accounting()
    query = queries[0]
    assert "BEGIN READ ONLY" in query and "statement_timeout='30s'" in query
    assert f"left(b.batch_id,{len(scope.NCS_PREFIX)})='{scope.NCS_PREFIX}'" in query
    assert f"a.task_id='{scope.ONET_TASK}'" in query
    assert "effective_cost_usd,a.reserve_usd" in query
    assert "enrichment.accounted_cost" in query
    assert all(
        word not in query for word in ("UPDATE ", "DELETE ", "response_body", "source_facts")
    )
    result["ncs"]["foreign_batches"] = 1
    with pytest.raises(RuntimeError, match="foreign"):
        scope.remaining(result, "ncs")


@pytest.mark.parametrize("drift", ["ncs", "jobkorea", "count", "catalogue"])
def test_live_source_and_catalogue_pins_must_match_reviewed_scope(drift):
    data = manifest()
    state = {
        **accounting(),
        "pins": {"jobkorea": scope.JOB_RUN, "ncs_competency": "ncs-exact"},
        "source_count": 5482,
        "onet_catalogue": {
            "release_id": "onet-exact",
            "database_id": "database-exact",
            "manifest_sha256": "c" * 64,
        },
    }
    assert scope.state("pg", lambda *args: json.dumps(state), data) == state
    if drift == "count":
        state["source_count"] = 8434
    elif drift == "catalogue":
        state["onet_catalogue"]["manifest_sha256"] = "d" * 64
    else:
        state["pins"]["ncs_competency" if drift == "ncs" else "jobkorea"] = "changed"
    with pytest.raises(RuntimeError, match=r"pin|count"):
        scope.state("pg", lambda *args: json.dumps(state), data)


def test_replacement_cohort_cannot_include_old_runs_or_other_sources():
    rows = [{"source_id": "jobkorea", "source_run_id": scope.JOB_RUN} for _ in range(5482)]
    scope.validate_rows(manifest(), rows)
    for key, value in (("source_id", "nara_job"), ("source_run_id", "historical-run")):
        changed = deepcopy(rows)
        changed[0][key] = value
        with pytest.raises(RuntimeError, match="exact new"):
            scope.validate_rows(manifest(), changed)


def test_jobkorea_only_pilot_is_exactly_24_fresh_ids_and_keeps_preregistered_order(tmp_path):
    rows = [
        {"posting_identity": f"source:posting:jobkorea:{number}", "source_id": "jobkorea"}
        for number in range(40)
    ]
    eligible = [r["posting_identity"] for r in rows]
    selected = scope.pilot_ids(rows, eligible)
    assert len(selected) == len(set(selected)) == 24
    assert scope.pilot_ids(list(reversed(rows)), list(reversed(eligible))) == selected
    assert selected[0] not in scope.pilot_ids(rows, [p for p in eligible if p != selected[0]])
    path = tmp_path / "pilot.json"
    write(path, list(reversed(selected)))
    assert onet.explicit_pilot_ids(path, rows, eligible, manifest())[0] == list(reversed(selected))
    eligible.remove(selected[0])
    with pytest.raises(RuntimeError, match="already planned"):
        onet.explicit_pilot_ids(path, rows, eligible, manifest())


def test_ncs_replacement_refuses_cache_reuse_before_any_runtime_access(tmp_path, monkeypatch):
    path = tmp_path / "scope.json"
    digest = write(path, manifest())
    args = SimpleNamespace(
        replacement_manifest=path,
        replacement_sha256=digest,
        jobs=scope.JOB_RUN,
        ncs="ncs-exact",
        reuse_cache="Y",
    )
    monkeypatch.setattr(ncs.common, "containers", lambda: pytest.fail("runtime accessed"))
    with pytest.raises(RuntimeError, match="reuse-cache N"):
        ncs.execute(args)


def test_new_no_cache_cli_passes_native_N_without_changing_legacy_default(monkeypatch):
    captured = []
    monkeypatch.setattr(ncs, "execute", captured.append)
    monkeypatch.setattr(sys, "argv", ["ncs", "plan", "--reuse-cache", "N"])
    ncs.main()
    assert ncs.parameters(captured[0], "batch", Decimal("0.05"))["REUSE_CACHE"] == "N"
    monkeypatch.setattr(sys, "argv", ["ncs", "plan"])
    ncs.main()
    assert ncs.parameters(captured[-1], "batch", Decimal("0.05"))["REUSE_CACHE"] == "Y"


def test_ncs_full_review_binds_actual_reviewed_scope_and_pilot_batch_ids(tmp_path):
    data = {
        "scope_sha256": "f" * 64,
        "decision": "APPROVE_SCALE",
        "reviewed_postings": 24,
        "review_actor": "coordinator",
        "notes": "All outputs/citations and total charges reviewed",
        "pilot_batch_ids": [scope.NCS_PREFIX + "pilot"],
    }
    path = tmp_path / "review.json"
    digest = write(path, data)
    assert scope.ncs_scale_review(path, digest, "f" * 64)["sha256"] == digest
    with pytest.raises(RuntimeError, match="24-posting"):
        scope.ncs_scale_review(path, digest, "e" * 64)
    data["pilot_batch_ids"] = ["legacy-paid-batch"]
    digest = write(path, data)
    with pytest.raises(RuntimeError, match="24-posting"):
        scope.ncs_scale_review(path, digest, "f" * 64)
