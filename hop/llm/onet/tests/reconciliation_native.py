"""Qualify additive SQL005 against retained pre-dispatch evidence and native mock calls."""

# Exact SQL and evidence fixtures are deliberately explicit.
# ruff: noqa: E501
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import tempfile
from pathlib import Path

import native as base

from hop.llm.onet.prompt import PROMPT_HASH, admitted_fields, build_request, validate_output

ROOT, q, js = base.ROOT, base.q, base.js


def error(f, statement, expected):
    try:
        f.sql(statement, "reject-" + expected)
    except RuntimeError:
        f.expect(expected in (f.logs / ("reject-" + expected + ".log")).read_text(), expected)
    else:
        raise AssertionError(expected)


def check(f, body: str, export_hash: str, base_proof: Path):
    f.receipt.update(
        kind="ISOLATED_ONET_RECONCILIATION_NATIVE",
        predecessor_proof=str(base_proof),
        predecessor_proof_sha256=hashlib.sha256(base_proof.read_bytes()).hexdigest(),
        routing_response_export_sha256=export_hash,
    )
    f.sql(
        "CREATE SCHEMA retention; CREATE TABLE retention.plan(plan_id text PRIMARY KEY,state text NOT NULL,owner_id text); CREATE TABLE retention.writer(writer_id text PRIMARY KEY,kind text NOT NULL,target_id text NOT NULL,started_at timestamptz NOT NULL DEFAULT clock_timestamp())",
        "retention-minimal",
    )
    canonical = (ROOT / "hop/retention/sql/001_retention.sql").read_text()
    for name in ("gate", "freeze_writes", "enter_writer", "leave_writer"):
        match = re.search(
            rf"CREATE OR REPLACE FUNCTION retention\.{name}\(.*?\$\$;", canonical, re.DOTALL
        )
        assert match
        f.sql(match.group(), "retention-" + name)
    for path in sorted((ROOT / "hop/ingestions/onet/sql").glob("*.sql")):
        f.sql(path.read_text(), "classification-" + path.stem)
    payload = base.catalog.small_payload()
    release = payload["release_id"]
    f.sql(
        "SELECT classification.import_onet_catalog("
        + js(payload)
        + "); SELECT classification.begin_graph_load("
        + q(release)
        + ",'fixture-db','reference-proof'); SELECT classification.finish_graph_load('reference-proof',(SELECT expected_nodes FROM classification.graph_load WHERE load_id='reference-proof'),(SELECT expected_edges FROM classification.graph_load WHERE load_id='reference-proof'),true); SELECT classification.activate_catalog("
        + q(release)
        + ",'fixture-db','reference-proof')",
        "reference-pg-proof",
    )
    f.sql(
        "CREATE SCHEMA ingestion; CREATE TABLE ingestion.source_graph_projection(run_id text PRIMARY KEY,source_id text,state text,loader_version text,content_sha256 text,verified_at timestamptz); CREATE TABLE ingestion.source_graph_membership(run_id text,record_id text,identity_id text,kind text); CREATE TABLE ingestion.source_graph_record_evidence(run_id text,record_id text,source_record_id text); INSERT INTO ingestion.source_graph_projection VALUES('fixture-source','jobkorea','READY','hop-graph-batchfree-v1',repeat('a',64),clock_timestamp())",
        "source-proof-stubs",
    )
    f.native("llm/onet/install.hwf", "native-frozen-base-installer")
    term = next(value for value in payload["terms"] if value["term_kind"] == "OCCUPATION")
    candidate = {
        "occupation_code": term["code"],
        "term_id": term["term_id"],
        "label": term["preferred_label"],
        "description": term["description"],
    }
    source_fields = {"title": "최고경영자\n\n"}
    manifest = []
    digest = f.sql(
        "SELECT encode(sha256(convert_to(" + js(source_fields) + "::text,'UTF8')),'hex')",
        "source-hash",
    )
    for n in range(3):
        identity = "jobkorea:posting:" + str(n)
        f.sql(
            "INSERT INTO ingestion.source_graph_membership VALUES('fixture-source',"
            + q(str(n))
            + ","
            + q(identity)
            + ",'JobPosting'); INSERT INTO ingestion.source_graph_record_evidence VALUES('fixture-source',"
            + q(str(n))
            + ","
            + q(str(n))
            + ")",
            "source-member-" + str(n),
        )
        manifest.append(
            {
                "posting_identity": identity,
                "source_id": "jobkorea",
                "source_run_id": "fixture-source",
                "source_record_id": str(n),
                "source_facts": source_fields,
                "source_facts_sha256": digest,
                "source_fields": admitted_fields(source_fields),
                "candidates": [candidate],
                "request_body": build_request(source_fields, [candidate]),
            }
        )
    settings = {
        "max_cost_usd": 40,
        "request_reserve_usd": 0.02,
        "max_output_tokens": 1024,
        "max_matches": 3,
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "model": "openai/gpt-5.6-luna",
        "prompt_hash": PROMPT_HASH,
        "retrieval_hash": "b" * 64,
        "read_timeout_ms": 5000,
        "request_delay_ms": 0,
        "execute_requests": "Y",
        "frozen_input_count": 3,
    }
    old_manifest = copy.deepcopy(manifest)
    for row in old_manifest:
        row["request_body"]["temperature"] = 0
    f.sql(
        "SELECT onet_matching.create_task('old-task',"
        + q(release)
        + ",'fixture-db',"
        + js(settings)
        + "); SELECT onet_matching.freeze_inputs('old-task',"
        + js(old_manifest)
        + "); SELECT onet_matching.finalize_freeze('old-task',3); SELECT onet_matching.plan_batch('old-task','old-pilot','[\"jobkorea:posting:0\",\"jobkorea:posting:1\",\"jobkorea:posting:2\"]','PILOT',3,0.25)",
        "old-frozen-request-history",
    )
    token = json.loads(f.sql("SELECT onet_matching.start_execution('old-pilot',2)", "old-token"))[
        "execution_token"
    ]
    attempts = json.loads(
        f.sql(
            "SELECT jsonb_agg(attempt_id ORDER BY ordinal) FROM onet_matching.attempt WHERE batch_id='old-pilot'",
            "old-attempts",
        )
    )
    for aid in attempts[:2]:
        f.sql(
            "SELECT onet_matching.admit_request(" + q(aid) + "," + q(token) + "::uuid)",
            "old-reservation-" + aid,
        )
    for aid in attempts[:2]:
        f.sql(
            "SELECT onet_matching.save_response(" + q(aid) + ",404," + q(body) + ",10)",
            "old-routing-response-" + aid,
        )
    original_rows = f.sql(
        "SELECT jsonb_agg(a ORDER BY attempt_id) FROM onet_matching.attempt a WHERE task_id='old-task'",
        "immutable-old-attempts-before",
    )
    f.expect(
        json.loads(f.sql("SELECT onet_matching.task_status('old-task')", "old-held-accounting"))[
            "unknown_holds"
        ]
        == 2,
        "original-routing-errors-remain-unknown-held",
    )
    f.native("llm/onet/install_reconciliation.hwf", "native-additive-reconciliation-install")
    f.native("llm/onet/install_reconciliation.hwf", "native-additive-reconciliation-install-replay")
    f.expect(
        f.sql(
            "SELECT onet_matching.no_dispatch_response_issue(404," + q(body) + ") IS NULL",
            "exact-original-router-evidence",
        )
        == "t",
        "exact-retained-parameter-filter-evidence-eligible",
    )
    envelope = json.loads(body)
    for name, status, change in (
        ("other404", 404, {"error": {"code": 404, "message": "Not found"}}),
        ("usage404", 404, dict(envelope, usage={"cost": 0})),
        (
            "selected_provider",
            404,
            {
                "error": dict(
                    envelope["error"],
                    metadata=dict(envelope["error"]["metadata"], provider_name="OpenAI"),
                )
            },
        ),
        (
            "wrong_stage",
            404,
            {
                "error": dict(
                    envelope["error"],
                    metadata=dict(
                        envelope["error"]["metadata"], failed_routing_step="Provider Dispatch"
                    ),
                )
            },
        ),
        ("transport", 0, envelope),
        ("upstream503", 503, envelope),
    ):
        f.expect(
            f.sql(
                "SELECT onet_matching.no_dispatch_response_issue("
                + str(status)
                + ","
                + q(json.dumps(change))
                + ") IS NOT NULL",
                "reject-shape-" + name,
            )
            == "t",
            "not-all-routing-or-transport-errors-free-" + name,
        )
    evidence = json.loads(
        f.sql(
            "SELECT jsonb_build_object('basis','OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER','response_export_sha256',"
            + q(export_hash)
            + ",'accounting_before_sha256',repeat('a',64),'accounting_after_sha256',repeat('b',64),'accounting_before_basis','RETAINED_TOOL_RESPONSE_TRANSCRIPT','checked_before_at',clock_timestamp()-interval '1 hour','checked_after_at',clock_timestamp()+interval '1 minute','router_usage_before_usd',1.25,'router_usage_after_usd',1.25,'byok_usage_before_usd',2.5,'byok_usage_after_usd',2.5)",
            "synthetic-reviewed-observations",
        )
    )
    response_hash = hashlib.sha256(body.encode()).hexdigest()

    def call(aid, e=evidence, h=response_hash):
        return (
            "SELECT onet_matching.reconcile_no_dispatch("
            + q(aid)
            + ","
            + q(h)
            + ",'fixture-coordinator','Exact router pre-dispatch error; unchanged synthetic observations corroborate zero dispatch.',"
            + js(e)
            + ")"
        )

    error(
        f,
        "INSERT INTO onet_matching.no_dispatch_reconciliation VALUES('forged',"
        + q(attempts[0])
        + ","
        + q(response_hash)
        + ",0,'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER','forged','unreviewed','{}',clock_timestamp())",
        "ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE",
    )
    error(
        f,
        "INSERT INTO onet_matching.no_dispatch_reconciliation VALUES('forged',"
        + q(attempts[2])
        + ","
        + q(response_hash)
        + ",0,'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER','forged','release unrelated hold',"
        + js(evidence)
        + ",clock_timestamp())",
        "ONET_MATCHING_RECONCILIATION_REQUIRES_EXACT_UNCHARGED_ROUTER_ATTEMPT",
    )
    error(
        f,
        call(attempts[0], h="0" * 64),
        "ONET_MATCHING_RECONCILIATION_REQUIRES_EXACT_UNCHARGED_ROUTER_ATTEMPT",
    )
    error(
        f,
        call(attempts[0], e=evidence | {"router_usage_after_usd": 1.26}),
        "ONET_MATCHING_RECONCILIATION_COUNTERS_OR_OBSERVATION_TIMES_INCONSISTENT",
    )
    for aid in attempts[:2]:
        f.sql(call(aid), "reviewed-no-dispatch-" + aid)
    f.sql(call(attempts[0]), "exact-reconciliation-replay")
    f.expect(
        f.sql(
            "SELECT count(*) FROM onet_matching.no_dispatch_reconciliation", "reconciliation-count"
        )
        == "2",
        "reconciliation-is-append-only-idempotent",
    )
    f.expect(
        original_rows
        == f.sql(
            "SELECT jsonb_agg(a ORDER BY attempt_id) FROM onet_matching.attempt a WHERE task_id='old-task'",
            "immutable-old-attempts-after",
        ),
        "original-terminal-response-cost-and-attempt-history-exact",
    )
    status = json.loads(f.sql("SELECT onet_matching.task_status('old-task')", "reconciled-status"))
    f.expect(
        status["unknown_holds"] == 0 and status["accounting_usd"] == 0,
        "effective-zero-charge-with-original-cost-null",
    )
    error(
        f,
        "UPDATE onet_matching.no_dispatch_reconciliation SET notes='rewrite'",
        "ONET_MATCHING_IMMUTABLE_HISTORY",
    )
    f.sql(
        "SELECT onet_matching.stop_task('old-task','fixture-coordinator','Abandon original unsupported-temperature request contract')",
        "stop-old-task",
    )
    error(
        f, "SELECT onet_matching.start_execution('old-pilot',1,true)", "ONET_MATCHING_TASK_STOPPED"
    )
    f.expect(
        f.sql("SELECT onet_matching.eligible_inputs('old-task')", "stopped-eligible-inputs")
        == "[]",
        "old-never-sent-plans-retained-but-never-admitted",
    )
    output = {
        "outcome": "matched",
        "matches": [
            {
                "occupation_code": term["code"],
                "match_rank": 1,
                "reason": "Synthetic chief executive role.",
                "evidence": [{"field": "title", "quote": "최고경영자"}],
            }
        ],
        "abstain_reason": "",
    }
    for name, modified in (
        ("newline_quote", {"field": "title", "quote": "\n\n"}),
        ("unicode_quote", {"field": "title", "quote": "\u00a0\u3000"}),
        ("leading_newline_one_character", {"field": "title", "quote": "\na"}),
    ):
        test = copy.deepcopy(output)
        test["matches"][0]["evidence"] = [modified]
        fields = {"title": "최고경영자\n\na\u00a0\u3000"}
        sql_issues = json.loads(
            f.sql(
                "SELECT onet_matching.output_issues("
                + js(test)
                + ","
                + js(fields)
                + ","
                + js([candidate])
                + ",3)",
                "unicode-parity-" + name,
            )
        )
        f.expect(
            bool(sql_issues) == bool(validate_output(test, fields, [candidate])),
            "unicode-quote-parity-" + name,
        )
    for name in ("reason", "abstain_reason"):
        test = copy.deepcopy(output)
        if name == "reason":
            test["matches"][0]["reason"] = "\n\t"
        else:
            test = {"outcome": "abstained", "matches": [], "abstain_reason": "\n\t"}
        f.expect(
            bool(
                json.loads(
                    f.sql(
                        "SELECT onet_matching.output_issues("
                        + js(test)
                        + ","
                        + js(source_fields)
                        + ","
                        + js([candidate])
                        + ",3)",
                        "unicode-parity-" + name,
                    )
                )
            ),
            "unicode-nonblank-" + name,
        )
    settings = settings | {
        "endpoint": "http://" + f.mock + ":18080/chat/completions",
        "request_version": "onet-luna-strict-v2",
    }
    f.sql(
        "SELECT onet_matching.create_task('corrected-task',"
        + q(release)
        + ",'fixture-db',"
        + js(settings)
        + "); SELECT onet_matching.freeze_inputs('corrected-task',"
        + js(manifest)
        + "); SELECT onet_matching.finalize_freeze('corrected-task',3); SELECT onet_matching.plan_batch('corrected-task','corrected-pilot','[\"jobkorea:posting:0\"]','PILOT',1,0.25)",
        "corrected-request-successor",
    )
    (f.work / "mock/output.json").write_text(json.dumps(output, ensure_ascii=False))
    (f.work / "inputs/key.csv").write_text("api_key\nfixture_never_a_real_secret\n")
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-no-temperature-successor-request",
        {
            "ONET_BATCH_ID": "corrected-pilot",
            "REQUEST_WORKERS": "1",
            "API_KEY_FILE": base.REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(
        f.count() == 1
        and f.sql(
            "SELECT count(*) FROM onet_matching.attempt WHERE batch_id='corrected-pilot' AND state='VALIDATED' AND cost_usd=0.00021",
            "corrected-native-ledger",
        )
        == "1",
        "corrected-native-dispatch-after-reviewed-zero-holds",
    )
    f.sql(
        "SELECT onet_matching.approve_scale('corrected-task','fixture-coordinator','Individually checked mock and combined charge'); SELECT onet_matching.plan_batch('corrected-task','known-invalid','[\"jobkorea:posting:1\"]','FULL',1,0.25)",
        "known-invalid-plan",
    )
    bad = copy.deepcopy(output)
    bad["matches"][0]["evidence"][0]["quote"] = "\n\n"
    (f.work / "mock/output.json").write_text(json.dumps(bad, ensure_ascii=False))
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-whitespace-rejection-known-charge",
        {
            "ONET_BATCH_ID": "known-invalid",
            "REQUEST_WORKERS": "1",
            "API_KEY_FILE": base.REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(
        f.sql(
            "SELECT count(*) FROM onet_matching.attempt WHERE batch_id='known-invalid' AND state='REJECTED' AND cost_usd=0.00021 AND issues ? 'INVALID_EXACT_SOURCE_CITATION'",
            "known-rejected-ledger",
        )
        == "1",
        "invalid-output-still-settles-known-combined-cost",
    )
    status = json.loads(
        f.sql("SELECT onet_matching.task_status('corrected-task')", "all-effective-cost")
    )
    f.expect(
        status["accounting_usd"] == 0.00042 and status["unknown_holds"] == 0,
        "cumulative-scope-includes-successor-and-invalid-known-cost",
    )
    f.sql(
        "SELECT onet_matching.plan_batch('corrected-task','budget-block','[\"jobkorea:posting:2\"]','FULL',1,0.001)",
        "budget-plan",
    )
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-successor-budget-bound",
        {
            "ONET_BATCH_ID": "budget-block",
            "REQUEST_WORKERS": "1",
            "API_KEY_FILE": base.REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(f.count() == 2, "combined-accounting-budget-still-blocks-before-post")
    f.expect(
        f.sql("SELECT count(*) FROM retention.writer", "owned-writers-absent") == "0",
        "owned-writers-absent",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--base-proof", type=Path, required=True)
    args = parser.parse_args()
    data = args.responses.read_bytes()
    response = json.loads(data)["responses"][0]["response_body"]
    with tempfile.TemporaryDirectory(prefix="onet-reconcile-synthetic-") as directory:
        source = Path(directory) / "source.json"
        source.write_text("[]\n")
        f = base.Fixture(source)
        try:
            f.boot()
            check(f, response, hashlib.sha256(data).hexdigest(), args.base_proof)
            f.receipt["status"] = "PASSED_ONET_MATCHING_NATIVE"
        except Exception as failure:
            f.receipt.update(status="FAILED", error=type(failure).__name__ + ": " + str(failure))
            raise
        finally:
            f.close()
            print(str(f.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
