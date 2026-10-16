"""Network-none PostgreSQL proof of terminal metadata status and history preservation."""

# Synthetic SQL fixtures retain exact JSON contracts.
# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import metadata_occupation_context as context
from metadata_occupation_pm_revision import history

f: Any = context.f
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = "hop/llm/sql/035_metadata_occupation_terminal_status.sql"


def checks(receipt: Path) -> None:
    count = 0

    def expect(value: bool, name: str) -> None:
        nonlocal count
        assert value, name
        count += 1

    for number in range(31, 35):
        f.sql(next((ROOT / "hop/llm/sql").glob(f"{number:03d}_*.sql")).read_text())
    source_requests_before = f.sql("SELECT count(*) FROM ingestion.request_attempt")
    f.sql("UPDATE ingestion.record SET normalized=normalized||"
          + f.js(dict(code="2001020101_24v1", name="데이터베이스 개발", definition="데이터베이스 설계 및 개발",
                      occupation_code="20010201", occupation_name="데이터베이스엔지니어링",
                      classification_names=["정보통신", "정보기술", "정보기술개발"]))
          + " WHERE run_id='ncs_competency'")
    names = [
        "accepted", "review", "rejected", "abstained", "accepted-abstention",
        "rejected-abstention", "latest-reject", "latest-accept", "citation-failure",
        "request-failure", "planning-failure", "unfinished-reject", "unfinished-error",
        "blocked-unsent", "planned", "reserved", "validated-without-result",
        "skipped-without-result", "missing-pointer", "retry-planned", "retry-reserved",
        "newer-failure", "batch-order", "same-time-order",
    ]
    rows = [dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(94000000 + index),
                 job_title="데이터베이스 개발자 " + name) for index, name in enumerate(names)]
    body = json.dumps(rows, ensure_ascii=False)
    digest = hashlib.sha256(body.encode()).hexdigest()
    jobs = f.sql(f"SELECT run_id FROM ingestion.begin_jobkorea_import({f.quote(digest)},{len(body.encode())},'jobkorea/'||{f.quote(digest)}||'/source.json',clock_timestamp())")
    f.sql(f"SELECT * FROM ingestion.load_jobkorea_document({f.quote(jobs)},{f.quote(body)}); SELECT ingestion.verify_jobkorea_file({f.quote(jobs)},{f.quote(digest)},{len(body.encode())}); SELECT * FROM ingestion.finalize_jobkorea_import({f.quote(jobs)})")
    f.sql(f"SELECT enrichment.prepare_jobkorea_input_bundle({f.quote(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={f.quote(jobs)}; SELECT enrichment.prepare_metadata_occupation_catalog('ncs_competency')")
    ids = {name: "ext-jobkorea-" + hashlib.sha256(str(94000000 + index).encode()).hexdigest()
           for index, name in enumerate(names)}
    opts = dict(categorize_model="openai/gpt-5.6-luna", extra_params={}, limit=len(rows), candidate_limit=12,
                max_matches=1, max_input_chars=16000, max_output_tokens=768, max_requests=len(rows),
                request_reserve_usd=0.005, max_cost_usd=0.15, daily_budget_usd=4.75,
                request_delay_ms=0, read_timeout_ms=5000, execute_requests="Y", reuse_cache="N",
                endpoint="https://openrouter.ai/api/v1/chat/completions", provider_only="openai",
                reasoning_effort="none", posting_ids="|".join(ids.values()))
    f.sql(f"SELECT enrichment.plan_metadata_occupation_batch('status-base',{f.quote(jobs)},'ncs_competency',{f.js(opts)})")
    items = json.loads(f.sql("SELECT jsonb_object_agg(posting_id,to_jsonb(i)) FROM enrichment.item i WHERE batch_id='status-base'"))
    by_name = {name: items[posting] for name, posting in ids.items()}
    expect(f.sql("SELECT bool_and(state='PLANNED' AND candidates<>'[]') FROM enrichment.attempt WHERE batch_id='status-base'") == "t", "all-base-items-have-unsent-candidates")

    def output(name: str, abstained: bool = False) -> dict[str, Any]:
        code = f.sql("SELECT candidates->0->>'occupation_code' FROM enrichment.attempt WHERE attempt_id=" + f.quote(by_name[name]["categorization_id"]))
        return dict(outcome="abstained" if abstained else "matched",
                    matches=[] if abstained else [dict(occupation_code=code, reason="Synthetic exact title supports database occupation",
                                                       evidence=[dict(field="title", quote=by_name[name]["source_data"]["title"])])],
                    abstain_reason="Synthetic ambiguity" if abstained else "")

    results = {}
    for name in [*names[:8], "newer-failure"]:
        item = by_name[name]
        f.sql(f"UPDATE enrichment.attempt SET state='VALIDATED',parsed_output={f.js(output(name, 'abstention' in name or name == 'abstained'))},completed_at=clock_timestamp() WHERE attempt_id={f.quote(item['categorization_id'])}")
        results[name] = f.sql(f"SELECT enrichment.capture_metadata_occupation_result({f.quote(item['item_id'])},'synthetic-status-author')")
    for name, decisions in {
        "accepted": ["ACCEPT"], "rejected": ["REJECT"], "accepted-abstention": ["ACCEPT"],
        "rejected-abstention": ["REJECT"], "latest-reject": ["ACCEPT", "REJECT"],
        "latest-accept": ["REJECT", "ACCEPT"], "newer-failure": ["ACCEPT"],
    }.items():
        for decision in decisions:
            f.sql(f"SELECT enrichment.decide_metadata_occupation({f.quote(results[name])},{f.quote(decision)},'independent-status-reviewer','assistant','Synthetic exact evidence reviewed')")

    # Exercise actual response validation and unknown-charge error handling using
    # locally generated envelopes; no HTTP client or provider credential exists.
    invalid = output("citation-failure")
    invalid["matches"][0]["evidence"][0]["quote"] = "Invented unsupported citation"
    response = dict(id="synthetic-charged-invalid", model="openai/gpt-5.6-luna",
                    choices=[dict(finish_reason="stop", message=dict(content=json.dumps(invalid, ensure_ascii=False)))],
                    usage=dict(is_byok=True, cost=0, cost_details=dict(upstream_inference_cost=0.001)))
    invalid_attempt = by_name["citation-failure"]["categorization_id"]
    f.sql(f"SELECT enrichment.reserve_request({f.quote(invalid_attempt)}); SELECT enrichment.save_response({f.quote(invalid_attempt)},200,{f.quote(json.dumps(response, ensure_ascii=False))},1)")
    expect(f.sql(f"SELECT state='REJECTED' AND completed_at IS NOT NULL AND cost_usd=0.001 AND issues='[\"METADATA_OCCUPATION_UNSUPPORTED_CITATION\"]' FROM enrichment.attempt WHERE attempt_id={f.quote(invalid_attempt)}") == "t", "charged-citation-failure-is-completed-rejected-attempt")
    request_attempt = by_name["request-failure"]["categorization_id"]
    f.sql(f"SELECT enrichment.reserve_request({f.quote(request_attempt)}); SELECT enrichment.save_response({f.quote(request_attempt)},0,'',1)")
    expect(f.sql(f"SELECT state='ERROR' AND completed_at IS NOT NULL AND cost_usd IS NULL AND reserved_usd=0.005 FROM enrichment.attempt WHERE attempt_id={f.quote(request_attempt)}") == "t", "request-error-retains-unknown-charge-hold")
    for name in ["planning-failure", "retry-planned", "retry-reserved", "batch-order", "same-time-order"]:
        f.sql(f"UPDATE enrichment.attempt SET state='REJECTED',completed_at=clock_timestamp(),issues='[\"INPUT_OR_COST_BOUND_EXCEEDED\"]' WHERE attempt_id={f.quote(by_name[name]['categorization_id'])}")
    f.sql("SELECT enrichment.finish_metadata_occupation_batch('status-base')")
    for name, state, complete in [
        ("unfinished-reject", "REJECTED", False), ("unfinished-error", "ERROR", False),
        ("blocked-unsent", "BUDGET_BLOCKED", True), ("reserved", "RESERVED", False),
        ("validated-without-result", "VALIDATED", True), ("skipped-without-result", "SKIPPED", True),
    ]:
        f.sql(f"UPDATE enrichment.attempt SET state={f.quote(state)},completed_at={'clock_timestamp()' if complete else 'NULL'} WHERE attempt_id={f.quote(by_name[name]['categorization_id'])}")
    f.sql(f"UPDATE enrichment.item SET categorization_id=NULL WHERE item_id={f.quote(by_name['missing-pointer']['item_id'])}")
    f.sql(f"UPDATE enrichment.item SET state='REJECTED' WHERE item_id={f.quote(by_name['blocked-unsent']['item_id'])}")

    # A retry is a later item/batch, never an aggregation over old failed attempts.
    for name, state in [("retry-planned", "PLANNED"), ("retry-reserved", "RESERVED"),
                        ("newer-failure", "REJECTED"), ("batch-order", "PLANNED"),
                        ("same-time-order", "PLANNED")]:
        f.sql(f"SELECT enrichment.plan_metadata_occupation_batch({f.quote('status-' + name)},{f.quote(jobs)},'ncs_competency',{f.js(opts | dict(posting_ids=ids[name], limit=1))})")
        f.sql(f"UPDATE enrichment.attempt SET state={f.quote(state)},completed_at={'clock_timestamp()' if state == 'REJECTED' else 'NULL'} WHERE batch_id={f.quote('status-' + name)}")
    # Deliberately reverse attempt chronology: batch/item ordering must win.
    f.sql("UPDATE enrichment.attempt SET created_at=clock_timestamp()+interval '1 day' WHERE batch_id='status-base'")
    f.sql("UPDATE enrichment.batch SET created_at='2000-01-01' WHERE batch_id='status-batch-order'")
    f.sql("UPDATE enrichment.batch SET created_at=(SELECT created_at FROM enrichment.batch WHERE batch_id='status-base') WHERE batch_id='status-same-time-order'")
    tied_expected = f.sql(f"SELECT CASE WHEN batch_id='status-base' THEN 'VALIDATION_FAILED' ELSE 'PENDING' END FROM enrichment.item WHERE posting_id={f.quote(ids['same-time-order'])} ORDER BY item_id DESC LIMIT 1")

    # The real cache planner references an attempt owned by a different item.
    f.sql(f"SELECT enrichment.plan_metadata_occupation_batch('status-cache',{f.quote(jobs)},'ncs_competency',{f.js(opts | dict(posting_ids=ids['accepted'], limit=1, reuse_cache='Y'))})")
    expect(f.sql("SELECT a.item_id<>i.item_id AND a.state='VALIDATED' FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.categorization_id WHERE i.batch_id='status-cache'") == "t", "current-pointer-can-reference-reused-validated-attempt")

    def statuses() -> dict[str, str]:
        return json.loads(f.sql(f"SELECT jsonb_object_agg(posting_id,outcome) FROM enrichment.metadata_occupation_status({f.quote(jobs)},'ncs_competency')"))

    old_status = statuses()
    expect(old_status[ids["citation-failure"]] == "PENDING", "034-reproduces-terminal-citation-pending-bug")
    before = history()
    graph_before = f.sql(f"SELECT enrichment.metadata_occupation_graph_hash({f.quote(jobs)},'ncs_competency',true)")
    functions_before = f.sql("SELECT enrichment.hash(jsonb_agg(jsonb_build_array(p.proname,p.prosrc) ORDER BY p.proname,p.oid::regprocedure::text)::text) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='enrichment' AND p.proname<>'metadata_occupation_status'")
    f.install(MIGRATION)
    expected = {name: "PENDING" for name in names}
    expected.update(review="REVIEW_PENDING", rejected="REJECTED", abstained="ABSTAINED",
                    **{"accepted-abstention": "ABSTAINED", "rejected-abstention": "REJECTED",
                       "latest-reject": "REJECTED", "latest-accept": "ACCEPTED_INFERRED_OCCUPATION",
                       "citation-failure": "VALIDATION_FAILED", "request-failure": "REQUEST_FAILED",
                       "planning-failure": "VALIDATION_FAILED", "newer-failure": "VALIDATION_FAILED",
                       "batch-order": "VALIDATION_FAILED", "same-time-order": tied_expected})
    actual = statuses()
    for name, outcome in expected.items():
        expect(actual[ids[name]] == outcome, name + "-status-" + outcome)
    expect(f.sql(f"SELECT bool_and(result_id IS NULL AND decision IS NULL AND matches='[]') FROM enrichment.metadata_occupation_status({f.quote(jobs)},'ncs_competency') WHERE outcome IN ('VALIDATION_FAILED','REQUEST_FAILED')") == "t", "terminal-failures-create-no-inferred-result-review-or-matches")
    expect(history() == before, "035-leaves-all-recorded-history-unchanged")
    expect(f.sql(f"SELECT enrichment.metadata_occupation_graph_hash({f.quote(jobs)},'ncs_competency',true)") == graph_before, "035-does-not-change-inferred-graph-payloads")
    expect(f.sql("SELECT enrichment.hash(jsonb_agg(jsonb_build_array(p.proname,p.prosrc) ORDER BY p.proname,p.oid::regprocedure::text)::text) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='enrichment' AND p.proname<>'metadata_occupation_status'") == functions_before, "035-changes-no-other-enrichment-function")
    expect(all(actual[posting] == outcome for posting, outcome in old_status.items()
               if posting not in {ids[name] for name in ["citation-failure", "request-failure", "planning-failure", "newer-failure", "batch-order", "same-time-order"]}), "existing-results-and-pending-precedence-preserved")
    for replay in range(2):
        for number in range(29, 36):
            f.sql(next((ROOT / "hop/llm/sql").glob(f"{number:03d}_*.sql")).read_text())
        expect(history() == before, f"canonical-replay-{replay}-preserves-history")
        expect(statuses() == actual, f"canonical-replay-{replay}-retains-terminal-status")
        expect(f.sql(f"SELECT enrichment.metadata_occupation_graph_hash({f.quote(jobs)},'ncs_competency',true)") == graph_before, f"canonical-replay-{replay}-preserves-graph")
    f.sql("SELECT enrichment.finish_metadata_occupation_batch('status-cache')")
    expect(statuses()[ids["accepted"]] == "REVIEW_PENDING", "cached-output-is-revalidated-for-new-item-without-transferring-old-review")
    expect(f.sql("SELECT count(*) FROM ingestion.request_attempt") == source_requests_before, "no-new-source-http-requests")
    report = dict(status="PASSED_OFFLINE_METADATA_TERMINAL_STATUS_035", checks=count,
                  source_http_requests=0, model_http_requests=0, production_writes=0,
                  sql_sha256=hashlib.sha256((ROOT / MIGRATION).read_bytes()).hexdigest(),
                  terminal_validation_status="VALIDATION_FAILED", terminal_request_status="REQUEST_FAILED",
                  validation_failure_includes="Completed planning-bound rejections and rejected responses; no charge assertion.",
                  request_failure_cost="May remain unknown; reservations and accounting are preserved.",
                  history_preserved=True, other_functions_preserved=True, graph_payloads_preserved=True,
                  canonical_replays=2, reused_attempt_pointer=True, newer_unsent_and_reserved_precedence=True)
    receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    context.checks = lambda: checks(args.receipt)
    context.main()


if __name__ == "__main__":
    main()
