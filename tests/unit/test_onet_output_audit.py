"""Independent raw-response, accounting and pinned-output audit checks."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "hop/operations"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location("onet_output_audit", OPS / "audit_onet_outputs.py")
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

from hop.llm.onet import prompt  # noqa: E402


def fixture():
    source = {"posting_identity": "source:posting:jobkorea:1", "source_id": "jobkorea",
        "source_run_id": "frozen-run", "source_record_id": "1:detail",
        "source_facts_sha256": "a" * 64, "source_fields": {"title": "소프트웨어 개발자"},
        "candidates": [{"occupation_code": "15-1252.00", "label": "Software Developers"}]}
    output = {"outcome": "matched", "abstain_reason": "", "matches": [{
        "occupation_code": "15-1252.00", "match_rank": 1,
        "reason": "제목에 개발자 역할이 명시되어 있다.",
        "evidence": [{"field": "title", "quote": "소프트웨어 개발자"}]}]}
    envelope = {"id": "response-1", "model": audit.runner.MODEL, "provider": "OpenAI",
        "usage": {"is_byok": True, "cost": 0.00005,
                  "cost_details": {"upstream_inference_cost": 0.001}},
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]}
    row = {**{key: source[key] for key in ("posting_identity", "source_id", "source_run_id",
                                         "source_record_id", "source_facts_sha256")},
        "attempt_id": "attempt-1", "batch_id": "batch-1", "state": "VALIDATED", "issues": [],
        "reserved_at": "2026-10-14T07:00:00Z", "http_status": 200,
        "response_body": json.dumps(envelope), "response_id": "response-1",
        "actual_model": audit.runner.MODEL, "provider": "OpenAI", "is_byok": True,
        "reserve_usd": "0.02", "router_cost_usd": "0.00005", "upstream_cost_usd": "0.001",
        "cost_usd": "0.00105", "prompt_tokens": 100, "completion_tokens": 20,
        "latency_ms": 2000, "parsed_output": output}
    manifest = {"rows": [source], "settings": {"max_matches": 3}}
    return manifest, row, envelope


def test_real_raw_output_and_combined_accounting_are_independently_verified():
    manifest, row, _ = fixture()
    output, issues = audit.decode_response(row)
    assert output == row["parsed_output"] and issues == []
    rows, metrics, failures = audit.audit_rows(manifest, {"rows": [row]}, prompt)
    assert failures == []
    assert metrics["python_validated_paid_outputs"] == metrics["proposed_matches"] == 1
    assert metrics["prompt_tokens"] == 100 and metrics["completion_tokens"] == 20
    assert Decimal(metrics["known_raw_cost_usd"]) == Decimal("0.00105")
    assert rows[0]["review_status"] == "UNREVIEWED" and rows[0]["confidence"] is None
    assert rows[0]["raw_response_sha256"]


@pytest.mark.parametrize("change", ["model", "provider", "byok", "cost", "reserve", "output"])
def test_native_validated_state_cannot_bypass_independent_route_cost_output_checks(change):
    manifest, row, _ = fixture()
    if change == "model":
        row["actual_model"] = "different/model"
    elif change == "provider":
        row["provider"] = "different"
    elif change == "byok":
        row["is_byok"] = False
    elif change == "cost":
        row["cost_usd"] = "0"
    elif change == "reserve":
        row["reserve_usd"] = "0.001"
    else:
        row["parsed_output"] = {"outcome": "abstained"}
    _, _, failures = audit.audit_rows(manifest, {"rows": [row]}, prompt)
    assert failures == ["INVALID_PUBLISHABLE_OUTPUT:attempt-1"]


@pytest.mark.parametrize("body", ['{"model":"a","model":"b"}', '{"usage":NaN}', '[]'])
def test_duplicate_keys_nonfinite_numbers_and_scalar_response_are_rejected(body):
    _, row, _ = fixture()
    row["response_body"] = body
    output, issues = audit.decode_response(row)
    assert output is None and issues


def test_whitespace_only_source_quote_is_rejected_using_python_gate():
    manifest, row, envelope = fixture()
    manifest["rows"][0]["source_fields"]["title"] += "\n\n"
    row["parsed_output"]["matches"][0]["evidence"][0]["quote"] = "\n\n"
    envelope["choices"][0]["message"]["content"] = json.dumps(row["parsed_output"])
    row["response_body"] = json.dumps(envelope)
    rows, _, failures = audit.audit_rows(manifest, {"rows": [row]}, prompt)
    assert failures and any("quote" in issue for issue in rows[0]["python_issues"])


def test_rejected_actual_outputs_are_also_python_validated():
    manifest, row, envelope = fixture()
    row["state"] = "REJECTED"
    row["parsed_output"]["matches"][0]["evidence"][0]["quote"] = "source did not say this"
    envelope["choices"][0]["message"]["content"] = json.dumps(row["parsed_output"])
    row["response_body"] = json.dumps(envelope)
    rows, metrics, failures = audit.audit_rows(manifest, {"rows": [row]}, prompt)
    assert not failures and rows[0]["python_issues"]
    assert metrics["python_validated_paid_outputs"] == 0


def test_local_abstentions_have_no_provider_route_or_charge():
    manifest, row, _ = fixture()
    manifest["rows"][0]["candidates"] = []
    row.update(state="SKIPPED", reserved_at=None, response_body=None,
               cost_usd=None, router_cost_usd=None, upstream_cost_usd=None,
               parsed_output={"outcome": "abstained", "matches": [],
                              "abstain_reason": "No suitable candidate."})
    _, metrics, failures = audit.audit_rows(manifest, {"rows": [row]}, prompt)
    assert not failures and metrics["local_abstentions"] == 1
    assert metrics["paid_reservations"] == 0 and metrics["proposed_matches"] == 0


def test_duplicate_and_unfrozen_outputs_cannot_pass():
    manifest, row, _ = fixture()
    extra = copy.deepcopy(row)
    _, _, failures = audit.audit_rows(manifest, {"rows": [row, extra]}, prompt)
    assert failures == ["DUPLICATE_OR_UNFROZEN_POSTING:" + row["posting_identity"]]
    extra["posting_identity"] = "foreign:posting"
    _, _, failures = audit.audit_rows(manifest, {"rows": [extra]}, prompt)
    assert failures == ["DUPLICATE_OR_UNFROZEN_POSTING:foreign:posting"]


def test_archived_endpoint_rejects_temperature_without_any_http_call():
    capabilities = {"data": {"endpoints": [{"tag": "openai",
        "supported_parameters": ["max_tokens", "response_format", "reasoning"]}]}}
    request = {"model": audit.runner.MODEL, "messages": [], "provider": {"only": ["openai"]},
               "max_tokens": 1024, "response_format": {}, "reasoning": {}}
    assert audit.capability_issues(request, capabilities) == []
    assert audit.capability_issues({**request, "temperature": 0}, capabilities) == [
        "UNSUPPORTED_PARAMETER:temperature"]
    capabilities["data"]["endpoints"][0]["tag"] = "openai/other"
    assert audit.capability_issues(request, capabilities) == ["NO_ARCHIVED_OPENAI_ENDPOINT"]


def test_snapshot_is_one_read_only_transaction_with_exact_task_batch():
    query = audit.snapshot_query("task-1", "batch-1")
    assert "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" in query
    assert "a.task_id='task-1' AND a.batch_id='batch-1'" in query
    assert "statement_timeout='120s'" in query
    assert all(keyword not in query.upper() for keyword in ("INSERT ", "UPDATE ", "DELETE "))
    assert "response_body" in query and "268435456" in query
    with pytest.raises(argparse.ArgumentTypeError):
        audit.snapshot_query("bad'identifier", None)


def test_decimal_costs_remain_exact_and_csv_formulas_are_data():
    parsed = audit.strict_json('{"cost":0.000000000000123456789}')
    assert parsed["cost"] == Decimal("0.000000000000123456789")
    assert audit.csv_cell("  =malicious()") == "'  =malicious()"
    assert audit.csv_cell("ordinary title") == "ordinary title"


def test_final_task_cost_and_shared_pilot_spend_have_the_same_source_denominator():
    manifest, row, _ = fixture()
    snapshot = {"rows": [row], "shared_accounting_usd": "0.00305",
                "shared_known_cost_usd": "0.00305", "task": {"unknown_holds": 0}}
    _, metrics, failures = audit.audit_rows(manifest, snapshot, prompt)
    assert not failures
    assert metrics["unique_frozen_source_postings"] == 1
    assert metrics["full_cohort_cost_per_1000_source_postings_usd"] == "1.05000"
    assert metrics["full_cohort_shared_cost_per_1000_source_postings_usd"] == "3.05000"
    assert metrics["cost_per_1000_paid_calls_usd"] == "1.05000"
    row.update(state="PLANNED", reserved_at=None, parsed_output=None, cost_usd=None,
               router_cost_usd=None, upstream_cost_usd=None)
    _, metrics, _ = audit.audit_rows(manifest, snapshot, prompt)
    assert metrics["full_cohort_cost_per_1000_source_postings_usd"] is None
    assert metrics["full_cohort_shared_cost_per_1000_source_postings_usd"] is None
    assert metrics["cost_per_1000_audited_postings_usd"] is None
    assert metrics["audit_scope_complete"] is False


def test_non_byok_reported_upstream_is_not_a_second_billable_charge():
    manifest, row, envelope = fixture()
    envelope["usage"] = {"is_byok": False, "cost": 0.0010035,
                         "cost_details": {"upstream_inference_cost": 0.0010035}}
    row.update(state="REJECTED", is_byok=False, cost_usd="0.0010035",
               router_cost_usd="0.0010035", upstream_cost_usd="0.0010035",
               response_body=json.dumps(envelope))
    _, issues = audit.decode_response(row)
    assert issues == ["BYOK_ROUTE_MISMATCH"]
    _, metrics, failures = audit.audit_rows(manifest, {"rows": [row]}, prompt)
    assert not failures
    assert metrics["known_raw_cost_usd"] == metrics["router_cost_usd"] == "0.0010035"
    assert metrics["upstream_cost_usd"] == "0"
    assert metrics["reported_upstream_cost_usd"] == "0.0010035"


@pytest.mark.parametrize("excluded", [True, False])
def test_frozen_nonvacancy_reason_is_separate_from_native_local_abstention(excluded):
    manifest, row, _ = fixture()
    source = manifest["rows"][0]
    source["candidates"] = []
    if excluded:
        source["admission_decision"] = {"outcome": "EXCLUDE",
            "reason_code": "EXPLICIT_TRAINING_ENROLLMENT", "reason": "Course enrollment",
            "evidence": [{"field": "title", "quote": source["source_fields"]["title"]}]}
    native = {"outcome": "abstained", "matches": [], "abstain_reason": "No candidates."}
    row.update(state="SKIPPED", reserved_at=None, response_body=None, parsed_output=native,
               cost_usd=None, router_cost_usd=None, upstream_cost_usd=None)
    results, metrics, failures = audit.audit_rows(manifest, {"rows": [row]}, prompt)
    assert not failures and results[0]["output"] == native
    assert results[0]["admission_decision"] == source.get("admission_decision")
    assert results[0]["local_abstention_basis"] == (
        "EXCLUDED_NON_VACANCY" if excluded else "NO_RETRIEVAL_CANDIDATES")
    assert metrics["excluded_non_vacancy_abstentions"] == int(excluded)
    assert metrics["no_retrieval_candidate_abstentions"] == int(not excluded)
