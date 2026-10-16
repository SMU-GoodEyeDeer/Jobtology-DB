#!/usr/bin/env python3
"""Independently validate O*NET responses against pinned local Python code.

Only one consistent read-only PostgreSQL snapshot is taken. No model request,
review decision, publication or database write runs here. Raw responses and
review exports remain private; a technical validation does not confer review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import run_onet_matches as runner

TUNABLE_PARAMETERS = frozenset({
    "temperature", "top_p", "top_k", "min_p", "frequency_penalty", "presence_penalty",
    "repetition_penalty", "max_tokens", "seed", "response_format", "tools", "tool_choice",
    "stop", "logit_bias", "logprobs", "top_logprobs", "verbosity", "reasoning",
    "reasoning_effort", "include_reasoning",
})


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def invalid_constant(_value: str) -> None:
    raise ValueError("Non-finite JSON number")


def strict_json(value: str) -> Any:
    return json.loads(value, object_pairs_hook=unique_object, parse_float=Decimal,
                      parse_constant=invalid_constant)


def amount(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    return result if result.is_finite() and result >= 0 else None


def decode_response(row: dict[str, Any]) -> tuple[Any, list[str]]:
    issues = []
    body = row.get("response_body")
    if not isinstance(body, str):
        return None, ["MISSING_RAW_RESPONSE"]
    try:
        envelope = strict_json(body)
    except (ValueError, TypeError):
        return None, ["INVALID_RAW_RESPONSE_JSON"]
    if not isinstance(envelope, dict):
        return None, ["RAW_RESPONSE_NOT_OBJECT"]
    if row.get("http_status") != 200 or "error" in envelope:
        issues.append("PROVIDER_HTTP_OR_ERROR")
    if envelope.get("model") != runner.MODEL or row.get("actual_model") != runner.MODEL:
        issues.append("MODEL_MISMATCH")
    if str(envelope.get("provider", "")).lower() != "openai" or (
        str(row.get("provider", "")).lower() != "openai"
    ):
        issues.append("PROVIDER_MISMATCH")
    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        issues.append("MISSING_USAGE")
        usage = {}
    details = usage.get("cost_details") or {}
    if not isinstance(details, dict):
        details = {}
    router_cost = amount(usage.get("cost"))
    upstream_cost = amount(details.get("upstream_inference_cost"))
    if usage.get("is_byok") is not True or row.get("is_byok") is not True:
        issues.append("BYOK_ROUTE_MISMATCH")
    is_byok = usage.get("is_byok")
    if router_cost is None or not isinstance(is_byok, bool) or (is_byok and upstream_cost is None):
        issues.append("UNKNOWN_COMBINED_COST")
    else:
        combined = router_cost + (upstream_cost if is_byok else Decimal("0"))
        if (router_cost, upstream_cost, combined) != (
            amount(row.get("router_cost_usd")), amount(row.get("upstream_cost_usd")),
            amount(row.get("cost_usd"))
        ):
            issues.append("RECORDED_COST_MISMATCH")
        reserve = amount(row.get("reserve_usd"))
        if reserve is None or combined > reserve:
            issues.append("RESERVATION_BREACH")
    if envelope.get("id") != row.get("response_id"):
        issues.append("RESPONSE_ID_MISMATCH")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return None, [*issues, "CHOICES_SHAPE"]
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
        return None, [*issues, "INCOMPLETE_OUTPUT"]
    if message.get("refusal") not in (None, ""):
        issues.append("REFUSAL")
    content = message.get("content")
    if not isinstance(content, str):
        return None, [*issues, "CONTENT_NOT_STRING"]
    try:
        output = strict_json(content)
    except (ValueError, TypeError):
        return None, [*issues, "INVALID_RAW_OUTPUT_JSON"]
    if output != row.get("parsed_output"):
        issues.append("RECORDED_OUTPUT_MISMATCH")
    return output, issues


def snapshot_query(task_id: str, batch_id: str | None) -> str:
    task = "'" + runner.identity(task_id) + "'"
    batch_filter = "" if batch_id is None else " AND a.batch_id='" + runner.identity(batch_id) + "'"
    return f"""BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='120s';
WITH scoped AS MATERIALIZED (
 SELECT a.*,i.source_id,i.source_run_id,i.source_record_id,i.source_facts_sha256
 FROM onet_matching.attempt a JOIN onet_matching.input i USING(task_id,posting_identity)
 WHERE a.task_id={task}{batch_filter}
), bounds AS (SELECT count(*) AS rows,
 coalesce(sum(octet_length(coalesce(response_body,''))),0) AS response_bytes FROM scoped)
SELECT jsonb_build_object('captured_at',transaction_timestamp(),
 'task',onet_matching.task_status({task}),
 'shared_accounting_usd',onet_matching.task_status({task})->>'accounting_usd',
 'shared_known_cost_usd',onet_matching.task_status({task})->>'known_cost_usd',
 'task_settings',(SELECT settings FROM onet_matching.task WHERE task_id={task}),
 'bounds',(SELECT to_jsonb(b) FROM bounds b),
 'rows',CASE WHEN (SELECT response_bytes FROM bounds)>268435456 THEN NULL ELSE
 (SELECT coalesce(jsonb_agg(jsonb_build_object(
  'attempt_id',a.attempt_id,'task_id',a.task_id,'batch_id',a.batch_id,
  'posting_identity',a.posting_identity,'source_id',a.source_id,
  'source_run_id',a.source_run_id,'source_record_id',a.source_record_id,
  'source_facts_sha256',a.source_facts_sha256,'state',a.state,'issues',a.issues,
  'reserved_at',a.reserved_at,'http_status',a.http_status,'response_body',a.response_body,
  'response_id',a.response_id,'actual_model',a.actual_model,'provider',a.provider,
  'is_byok',a.is_byok,'reserve_usd',a.reserve_usd::text,'cost_usd',a.cost_usd::text,
  'router_cost_usd',a.router_cost_usd::text,'upstream_cost_usd',a.upstream_cost_usd::text,
  'prompt_tokens',a.prompt_tokens,'completion_tokens',a.completion_tokens,
  'latency_ms',a.latency_ms,'parsed_output',a.parsed_output) ORDER BY a.posting_identity),
  '[]'::jsonb) FROM scoped a) END);
COMMIT;"""


def capability_issues(request: dict[str, Any], envelope: dict[str, Any]) -> list[str]:
    data = envelope.get("data") or {}
    endpoints = data.get("endpoints") or []
    # The standard OpenAI tag matches the immutable provider.only route.
    selected = [endpoint for endpoint in endpoints if endpoint.get("tag") == "openai"]
    if not selected:
        return ["NO_ARCHIVED_OPENAI_ENDPOINT"]
    required = TUNABLE_PARAMETERS & request.keys()
    if any(required <= set(endpoint.get("supported_parameters") or []) for endpoint in selected):
        return []
    available = set().union(*(set(endpoint.get("supported_parameters") or [])
                             for endpoint in selected))
    return ["UNSUPPORTED_PARAMETER:" + key for key in sorted(required - available)] or [
        "NO_SINGLE_ENDPOINT_SUPPORTS_REQUIRED_PARAMETERS"
    ]


def audit_rows(manifest: dict[str, Any], snapshot: dict[str, Any], validator: Any
               ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    inputs = {row["posting_identity"]: row for row in manifest["rows"]}
    reviewed = []
    states: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    per_source: dict[str, Counter[str]] = defaultdict(Counter)
    occupations: Counter[str] = Counter()
    seen: set[str] = set()
    failures = []
    known_cost = Decimal("0")
    router_total = Decimal("0")
    upstream_total = Decimal("0")
    reported_upstream_total = Decimal("0")
    matched_edges = 0
    validated = 0
    paid = 0
    local_abstentions = 0
    admission_exclusions = 0
    retrieval_no_hits = 0
    latencies = []
    prompt_tokens = 0
    completion_tokens = 0
    for row in snapshot["rows"]:
        posting = row["posting_identity"]
        source = inputs.get(posting)
        if posting in seen or source is None:
            failures.append("DUPLICATE_OR_UNFROZEN_POSTING:" + posting)
            continue
        seen.add(posting)
        lineage = ("source_id", "source_run_id", "source_record_id", "source_facts_sha256")
        issues = ["SOURCE_PROVENANCE_MISMATCH"] if any(
            row.get(key) != source[key] for key in lineage
        ) else []
        state = row["state"]
        admission = source.get("admission_decision")
        excluded = isinstance(admission, dict) and admission.get("outcome") == "EXCLUDE"
        abstention_basis = None
        states[state] += 1
        per_source[source["source_id"]][state] += 1
        output = row.get("parsed_output")
        if state == "SKIPPED":
            local_abstentions += 1
            if excluded:
                admission_exclusions += 1
                abstention_basis = "EXCLUDED_NON_VACANCY"
            else:
                retrieval_no_hits += 1
                abstention_basis = "NO_RETRIEVAL_CANDIDATES"
            per_source[source["source_id"]][abstention_basis] += 1
            if source["candidates"] or row.get("reserved_at") is not None:
                issues.append("INVALID_LOCAL_ABSTENTION")
        elif row.get("reserved_at") is not None:
            paid += 1
            raw_output, response_issues = decode_response(row)
            issues += response_issues
            output = raw_output
        if excluded and state != "SKIPPED":
            issues.append("EXCLUDED_NON_VACANCY_NOT_LOCAL_ABSTENTION")
        if output is not None or state in ("VALIDATED", "SKIPPED"):
            if state == "VALIDATED" and row.get("issues") != []:
                issues.append("VALIDATED_NATIVE_ISSUES_NOT_EMPTY")
            try:
                issues += validator.validate_output(output, source["source_fields"],
                    source["candidates"], max_matches=manifest["settings"]["max_matches"])
            except Exception:
                issues.append("PYTHON_VALIDATOR_EXCEPTION")
            if not issues and state in ("VALIDATED", "SKIPPED"):
                validated += state == "VALIDATED"
                outcomes[output["outcome"]] += 1
                per_source[source["source_id"]][output["outcome"].upper()] += 1
                for match in output["matches"]:
                    occupations[match["occupation_code"]] += 1
                    matched_edges += 1
        if state in ("VALIDATED", "SKIPPED") and issues:
            failures.append("INVALID_PUBLISHABLE_OUTPUT:" + row["attempt_id"])
        if "SOURCE_PROVENANCE_MISMATCH" in issues:
            failures.append("SOURCE_PROVENANCE_MISMATCH:" + row["attempt_id"])
        if row.get("reserved_at") is not None:
            if isinstance(row.get("latency_ms"), int) and row["latency_ms"] >= 0:
                latencies.append(row["latency_ms"])
            prompt_tokens += row.get("prompt_tokens") or 0
            completion_tokens += row.get("completion_tokens") or 0
        for field, name in (("cost_usd", "total"), ("router_cost_usd", "router"),
                            ("upstream_cost_usd", "upstream")):
            value = amount(row.get(field))
            if value is not None:
                if name == "total":
                    known_cost += value
                elif name == "router":
                    router_total += value
                else:
                    reported_upstream_total += value
                    if row.get("is_byok") is True:
                        upstream_total += value
        reviewed.append({
            "attempt_id": row["attempt_id"], "batch_id": row["batch_id"],
            "posting_identity": posting, "source_id": source["source_id"], "state": state,
            "source_fields": source["source_fields"], "output": output,
            "admission_decision": admission, "local_abstention_basis": abstention_basis,
            "python_issues": issues, "native_issues": row.get("issues", []),
            "raw_response_sha256": hashlib.sha256(row["response_body"].encode()).hexdigest()
                if isinstance(row.get("response_body"), str) else None,
            "cost_usd": row.get("cost_usd"), "router_cost_usd": row.get("router_cost_usd"),
            "upstream_cost_usd": row.get("upstream_cost_usd"),
            "prompt_tokens": row.get("prompt_tokens"),
            "completion_tokens": row.get("completion_tokens"),
            "latency_ms": row.get("latency_ms"), "model": row.get("actual_model"),
            "provider": row.get("provider"), "is_byok": row.get("is_byok"),
            "review_status": "UNREVIEWED", "confidence": None, "confidence_state": "UNASSESSED",
        })
    latencies.sort()
    complete_scope = not failures and all(
        state in ("VALIDATED", "REJECTED", "SKIPPED") for state in states
    )
    complete_cohort = len(seen) == len(inputs) and complete_scope
    completed = sum(states[state] for state in ("VALIDATED", "REJECTED", "SKIPPED"))
    shared_known_cost = amount(snapshot.get("shared_known_cost_usd"))
    shared_settled = (snapshot.get("task") or {}).get("unknown_holds") == 0
    metrics = {
        "scope_attempts": len(snapshot["rows"]), "paid_reservations": paid,
        "sql_states": dict(states), "outcomes": dict(outcomes),
        "python_validated_paid_outputs": validated, "local_abstentions": local_abstentions,
        "excluded_non_vacancy_abstentions": admission_exclusions,
        "no_retrieval_candidate_abstentions": retrieval_no_hits,
        "admission_policy_sha256": manifest["settings"].get("admission_policy_sha256"),
        "proposed_matches": matched_edges, "occupations": dict(occupations),
        "per_source": {source: dict(counts) for source, counts in per_source.items()},
        "known_raw_cost_usd": str(known_cost), "router_cost_usd": str(router_total),
        "upstream_cost_usd": str(upstream_total),
        "reported_upstream_cost_usd": str(reported_upstream_total),
        "task_accounting": snapshot.get("task"),
        "cost_scope": "THIS_FROZEN_TASK_OR_REQUESTED_BATCH_RAW_REPORTED_COST",
        "shared_accounting_usd": snapshot.get("shared_accounting_usd"),
        "shared_known_cost_usd": snapshot.get("shared_known_cost_usd"),
        "unique_frozen_source_postings": len(inputs),
        "unique_audited_source_postings": len(seen),
        "completed_source_postings": completed, "audit_scope_complete": complete_scope,
        "cost_per_1000_audited_postings_usd":
            str(known_cost * 1000 / len(seen)) if complete_scope and seen else None,
        "cost_per_1000_completed_postings_usd":
            str(known_cost * 1000 / completed) if completed else None,
        "cost_per_1000_paid_calls_usd": str(known_cost * 1000 / paid) if paid else None,
        "full_cohort_cost_per_1000_source_postings_usd":
            str(known_cost * 1000 / len(inputs)) if complete_cohort else None,
        "full_cohort_shared_cost_per_1000_source_postings_usd":
            str(shared_known_cost * 1000 / len(inputs))
            if complete_cohort and shared_settled and shared_known_cost is not None else None,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "request_latency_ms": {"samples": len(latencies),
            "minimum": latencies[0] if latencies else None,
            "median": latencies[len(latencies) // 2] if latencies else None,
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * .95))]
                if latencies else None,
            "maximum": latencies[-1] if latencies else None},
    }
    return reviewed, metrics, failures


def serializable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: serializable(child) for key, child in value.items()}
    if isinstance(value, list):
        return [serializable(child) for child in value]
    return value


def csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def audit(args: argparse.Namespace) -> None:
    os.umask(0o077)
    manifest = runner.manifest_inputs(args.manifest)
    validator = runner.frozen_prompt(args.manifest, manifest)
    directory = runner.new_directory("output-audit")
    receipt: dict[str, Any] = {"contract_version": "onet-independent-python-output-audit-v1",
        "started_at": runner.now(), "task_id": manifest["task_id"], "batch_id": args.batch_id,
        "manifest": str(args.manifest.resolve()),
        "manifest_identity": runner.file_identity(args.manifest),
        "code_artifacts": manifest["code_artifacts"], "status": "RUNNING", "database_writes": 0,
        "provider_calls": 0, "review_decisions": 0, "directory": str(directory)}
    path = directory / "receipt.json"
    runner.write_json(path, receipt)
    try:
        if args.capabilities:
            evidence = json.loads(args.capabilities.read_bytes())
            failures = sorted(set(issue for row in manifest["rows"]
                                  for issue in capability_issues(row["request_body"], evidence)))
            receipt["endpoint_evidence"] = {"path": str(args.capabilities.resolve()),
                                             **runner.file_identity(args.capabilities)}
            receipt["endpoint_issues"] = failures
            if failures:
                raise RuntimeError("Archived endpoint capability check failed")
        if args.capabilities_only:
            receipt["status"] = "PASSED_ARCHIVED_ENDPOINT_COMPATIBILITY"
            return
        runtime = runner.common.containers()
        query = snapshot_query(manifest["task_id"], args.batch_id)
        raw = runner.sql(runtime["pg"], query)
        snapshot = json.loads(raw)
        runner.write_json(directory / "snapshot.json", snapshot, immutable=True)
        if snapshot.get("rows") is None:
            raise RuntimeError("Response snapshot exceeds the reviewed 256 MiB bound")
        if not snapshot["rows"]:
            raise RuntimeError("No attempts exist in the exact requested audit scope")
        if snapshot.get("task_settings", {}).get("frozen_manifest_sha256") != (
            receipt["manifest_identity"]["sha256"]
        ):
            raise RuntimeError("Database task does not bind the exact local frozen manifest")
        rows, metrics, failures = audit_rows(manifest, snapshot, validator)
        receipt["metrics"] = metrics
        receipt["failures"] = failures
        receipt["captured_at"] = snapshot["captured_at"]
        with (directory / "validated-results.ndjson").open("x", encoding="utf-8") as output:
            for row in rows:
                output.write(runner.canonical(serializable(row)).decode() + "\n")
        with (directory / "match-review.csv").open("x", encoding="utf-8", newline="") as output:
            fields = ["posting_identity", "source_id", "title", "state", "occupation_code",
                      "label", "match_rank", "reason", "evidence", "review_status", "python_issues"]
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            inputs = {row["posting_identity"]: row for row in manifest["rows"]}
            for row in rows:
                source = inputs[row["posting_identity"]]
                candidates = {candidate["occupation_code"]: candidate
                              for candidate in source["candidates"]}
                result = row.get("output") or {}
                matches = result.get("matches", []) if isinstance(result, dict) else []
                for match in matches if isinstance(matches, list) else []:
                    if not isinstance(match, dict):
                        continue
                    code = match.get("occupation_code")
                    candidate = candidates.get(code, {}) if isinstance(code, str) else {}
                    review = {"posting_identity": row["posting_identity"],
                        "source_id": row["source_id"],
                        "title": source["source_fields"].get("title", ""),
                        "state": row["state"], "occupation_code": match.get("occupation_code"),
                        "label": candidate.get("label", ""),
                        "match_rank": match.get("match_rank"), "reason": match.get("reason"),
                        "evidence": json.dumps(match.get("evidence"), ensure_ascii=False),
                        "review_status": "UNREVIEWED",
                        "python_issues": json.dumps(row["python_issues"])}
                    writer.writerow({key: csv_cell(value) for key, value in review.items()})
        receipt["exports"] = {name: runner.file_identity(directory / name) for name in (
            "snapshot.json", "validated-results.ndjson", "match-review.csv")}
        if failures:
            raise RuntimeError("Independent Python validation found output discrepancies")
        states = metrics["sql_states"]
        if args.require_complete and any(states.get(state, 0) for state in (
            "PLANNED", "RESERVED", "ERROR", "BUDGET_BLOCKED"
        )):
            raise RuntimeError("The audited scope includes unfinished or failed requests")
        receipt["status"] = "PASSED_INDEPENDENT_PYTHON_OUTPUT_AUDIT"
    except BaseException as exc:
        receipt["status"] = "FAILED"
        receipt["error"] = str(exc)
        raise
    finally:
        receipt["finished_at"] = runner.now()
        runner.write_json(path, receipt)
        print(json.dumps({"status": receipt["status"], "receipt": str(path),
                          "metrics": receipt.get("metrics"),
                          "endpoint_issues": receipt.get("endpoint_issues")}),
              flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch-id", type=runner.identity)
    parser.add_argument("--capabilities", type=Path,
                        help="Retained public endpoint JSON; makes no HTTP request")
    parser.add_argument("--capabilities-only", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    if args.capabilities_only and not args.capabilities:
        parser.error("--capabilities-only requires --capabilities")
    audit(args)


if __name__ == "__main__":
    main()
