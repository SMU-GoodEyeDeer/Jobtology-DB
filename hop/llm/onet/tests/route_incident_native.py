"""Isolated native recovery of a known router charge with bounded unknown BYOK exposure."""

# Explicit SQL fixtures model immutable production state without production access.
# ruff: noqa: E501
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import re
import sys
import tempfile
import types
from pathlib import Path

import native as base
from reconciliation_native import error

ROOT, q, js = base.ROOT, base.q, base.js


def prompt_module(path):
    package = types.ModuleType("route_fixture_pinned_prompt")
    package.__path__ = [str(path)]
    sys.modules[package.__name__] = package
    sys.dont_write_bytecode = True
    return importlib.import_module(package.__name__ + ".prompt")


def setup(f, prompt):
    f.sql(
        "CREATE SCHEMA retention; CREATE TABLE retention.plan(plan_id text PRIMARY KEY,state text NOT NULL,owner_id text); CREATE TABLE retention.writer(writer_id text PRIMARY KEY,kind text NOT NULL,target_id text NOT NULL,started_at timestamptz NOT NULL DEFAULT clock_timestamp())",
        "retention-stubs",
    )
    canonical = (ROOT / "hop/retention/sql/001_retention.sql").read_text()
    for name in ["gate", "freeze_writes", "enter_writer", "leave_writer"]:
        body = re.search(
            rf"CREATE OR REPLACE FUNCTION retention\.{name}\(.*?\$\$;", canonical, re.DOTALL
        )
        assert body
        f.sql(body.group(), "retention-" + name)
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
        "reference-proof",
    )
    f.sql(
        "CREATE SCHEMA ingestion; CREATE TABLE ingestion.source_graph_projection(run_id text PRIMARY KEY,source_id text,state text,loader_version text,content_sha256 text,verified_at timestamptz); CREATE TABLE ingestion.source_graph_membership(run_id text,record_id text,identity_id text,kind text); CREATE TABLE ingestion.source_graph_record_evidence(run_id text,record_id text,source_record_id text); INSERT INTO ingestion.source_graph_projection VALUES('fixture-source','jobkorea','READY','hop-graph-batchfree-v1',repeat('a',64),clock_timestamp())",
        "source-stubs",
    )
    f.native("llm/onet/install.hwf", "native-base-install")
    f.native("llm/onet/install_reconciliation.hwf", "native-005-install")
    f.sql(
        "INSERT INTO onet_matching.prompt_contract VALUES("
        + q(prompt.PROMPT_VERSION)
        + ","
        + q(prompt.PROMPT_TEXT)
        + ","
        + q(prompt.PROMPT_HASH)
        + ","
        + js(prompt.SCHEMA)
        + ")",
        "pinned-prompt-registry",
    )
    term = next(term for term in payload["terms"] if term["term_kind"] == "OCCUPATION")
    candidate = {
        "occupation_code": term["code"],
        "term_id": term["term_id"],
        "label": term["preferred_label"],
        "description": term["description"],
    }
    source = {"title": "최고경영자"}
    source_sha = f.sql(
        "SELECT encode(sha256(convert_to(" + js(source) + "::text,'UTF8')),'hex')", "source-sha"
    )
    rows = []
    for n in range(90):
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
        rows.append(
            {
                "posting_identity": identity,
                "source_id": "jobkorea",
                "source_run_id": "fixture-source",
                "source_record_id": str(n),
                "source_facts": source,
                "source_fields": prompt.admitted_fields(source),
                "source_facts_sha256": source_sha,
                "candidates": [candidate],
                "request_body": prompt.build_request(source, [candidate]),
            }
        )
    settings = {
        "max_cost_usd": 40,
        "request_reserve_usd": 0.02,
        "max_output_tokens": 1024,
        "max_matches": 3,
        "endpoint": "http://" + f.mock + ":18080/chat/completions",
        "model": "openai/gpt-5.6-luna",
        "prompt_hash": prompt.PROMPT_HASH,
        "retrieval_hash": "b" * 64,
        "read_timeout_ms": 5000,
        "request_delay_ms": 0,
        "execute_requests": "Y",
        "frozen_input_count": 90,
    }

    def task(name, opts=settings):
        f.sql(
            "SELECT onet_matching.create_task("
            + q(name)
            + ","
            + q(release)
            + ",'fixture-db',"
            + js(opts)
            + "); SELECT onet_matching.freeze_inputs("
            + q(name)
            + ","
            + js(rows)
            + "); SELECT onet_matching.finalize_freeze("
            + q(name)
            + ",90)",
            "task-" + name,
        )

    task("route-task")
    (f.work / "inputs/key.csv").write_text("api_key\nfixture_never_a_real_secret\n")
    (f.work / "inputs/key.csv").chmod(0o600)
    (f.work / "mock/output.json").write_text(
        json.dumps(
            {
                "outcome": "matched",
                "matches": [
                    {
                        "occupation_code": term["code"],
                        "match_rank": 1,
                        "reason": "Explicit role",
                        "evidence": [{"field": "title", "quote": "최고경영자"}],
                    }
                ],
                "abstain_reason": "",
            },
            ensure_ascii=False,
        )
    )
    return rows, settings, task


def check(f, prompt, predecessor):
    f.receipt.update(
        kind="ISOLATED_ONET_ROUTE_INCIDENT_NATIVE",
        predecessor_proof=str(predecessor),
        predecessor_proof_sha256=hashlib.sha256(predecessor.read_bytes()).hexdigest(),
    )
    previous = json.loads(predecessor.read_bytes())
    for path, sha in previous["artifact_sha256"].items():
        f.expect(
            hashlib.sha256((ROOT / "hop" / path).read_bytes()).hexdigest() == sha,
            "original20-exact-" + path,
        )
    _rows, settings, task = setup(f, prompt)
    functions = "SELECT jsonb_object_agg(oid::regprocedure::text,jsonb_build_object('oid',oid,'source',md5(prosrc))) FROM pg_proc WHERE pronamespace='onet_matching'::regnamespace AND proname NOT IN('request_context','task_status','batch_status')"
    functions_before = json.loads(f.sql(functions, "protected-functions-before"))
    f.sql(
        "SELECT onet_matching.plan_batch('route-task','route-pilot','[\"jobkorea:posting:0\",\"jobkorea:posting:1\",\"jobkorea:posting:2\"]','PILOT',3,0.25)",
        "plan-route-pilot",
    )
    (f.work / "mock/mode").write_text("router")
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-nonbyok-stop",
        {
            "ONET_BATCH_ID": "route-pilot",
            "REQUEST_WORKERS": 1,
            "API_KEY_FILE": base.REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(f.count() == 1, "one-router-post-then-stop")
    incident = json.loads(
        f.sql(
            "SELECT to_jsonb(a) FROM onet_matching.attempt a WHERE batch_id='route-pilot' AND state='REJECTED'",
            "incident",
        )
    )
    aid = incident["attempt_id"]
    body = incident["response_body"]
    response_sha = hashlib.sha256(body.encode()).hexdigest()
    f.expect(
        incident["issues"] == ["EXPECTED_OPENAI_BYOK_ROUTE"]
        and incident["is_byok"] is False
        and incident["cost_usd"] == 0.00001,
        "fully-known-router-charge-with-sole-route-rejection",
    )
    before_history = f.sql(
        "SELECT jsonb_agg(a ORDER BY attempt_id) FROM onet_matching.attempt a WHERE batch_id='route-pilot'",
        "history-before",
    )
    f.native("llm/onet/install_route_incident.hwf", "native-006-install")
    f.native("llm/onet/install_route_incident.hwf", "native-006-replay")
    functions_after = json.loads(f.sql(functions, "protected-functions-after"))
    f.expect(
        {key: functions_after[key] for key in functions_before} == functions_before,
        "all-unmodified-function-oids-and-bodies-exact",
    )
    generation = {
        "data": {
            "id": incident["response_id"],
            "is_byok": False,
            "provider_name": "OpenAI",
            "model": "openai/gpt-5.6-luna-20260709",
            "total_cost": 0.00001,
            "upstream_inference_cost": 0,
            "provider_responses": [
                {
                    "is_byok": True,
                    "status": 504,
                    "provider_name": "OpenAI",
                    "model_permaslug": "openai/gpt-5.6-luna-20260709",
                    "endpoint_id": "fixture-endpoint",
                },
                {
                    "is_byok": False,
                    "status": 200,
                    "provider_name": "OpenAI",
                    "model_permaslug": "openai/gpt-5.6-luna-20260709",
                    "endpoint_id": "fixture-endpoint",
                },
            ],
        }
    }
    attestation = {
        "evidence_kind": "USER_REPORTED_ACCOUNT_SETTING_CHANGE",
        "provider": "openai",
        "setting": "Shared capacity fallback",
        "requested_value": "Never use shared capacity for any model on this provider",
        "user_reply": "Saved the BYOK-only setting",
        "credentials_changed_by_agent": False,
        "independent_management_api_readback": False,
        "recorded_at": f.sql("SELECT clock_timestamp()", "confirmation-time"),
    }

    def evidence(gen=generation, att=attestation):
        gen_body = json.dumps(gen, ensure_ascii=False) + "\n"
        att_body = json.dumps(att, ensure_ascii=False) + "\n"
        return {
            "basis": "REVIEWED_KNOWN_ROUTER_BOUNDED_BYOK_EXPOSURE",
            "generation_body": gen_body,
            "generation_sha256": hashlib.sha256(gen_body.encode()).hexdigest(),
            "user_attestation_body": att_body,
            "user_attestation_sha256": hashlib.sha256(att_body.encode()).hexdigest(),
        }

    good = evidence()

    def call(e=good, identity=aid, h=response_sha):
        return (
            "SELECT onet_matching.acknowledge_route_incident("
            + q(identity)
            + ","
            + q(h)
            + ",'fixture-coordinator','User-reported existing key BYOK-only setting; first504 exposure remains bounded, not declared free.',"
            + js(e)
            + ")"
        )

    for _label, change in [
        ("wrong-hash", dict(good, generation_sha256="a" * 64)),
        ("missing-body", dict(good, user_attestation_body=None)),
    ]:
        error(f, call(change), "ONET_MATCHING_ROUTE_ACK_INVALID_IMMUTABLE_EVIDENCE")
    for _label, changed in [
        ("not-saved", dict(attestation, user_reply="not saved")),
        ("missing-setting", dict(attestation, requested_value="Allow shared")),
        ("api-claim", dict(attestation, independent_management_api_readback=True)),
        ("credentials-changed", dict(attestation, credentials_changed_by_agent=True)),
    ]:
        error(
            f,
            call(evidence(att=changed)),
            "ONET_MATCHING_ROUTE_ACK_REQUIRES_USER_REPORTED_BYOK_ONLY_SETTING",
        )
    for _label, change in [
        (
            "extra-route",
            lambda g: g["data"]["provider_responses"].append(
                copy.deepcopy(g["data"]["provider_responses"][0])
            ),
        ),
        ("other-model", lambda g: g["data"].__setitem__("model", "other")),
        (
            "wrong-first-byok",
            lambda g: g["data"]["provider_responses"][0].__setitem__("is_byok", False),
        ),
        (
            "other-first-status",
            lambda g: g["data"]["provider_responses"][0].__setitem__("status", 503),
        ),
    ]:
        gen = copy.deepcopy(generation)
        change(gen)
        error(
            f,
            call(evidence(gen=gen)),
            "ONET_MATCHING_ROUTE_ACK_REQUIRES_EXACT_TWO_ROUTE_GENERATION",
        )
    error(
        f, call(h="a" * 64), "ONET_MATCHING_ROUTE_ACK_REQUIRES_EXACT_FULLY_COSTED_ROUTE_REJECTION"
    )
    ack = json.loads(f.sql(call(), "acknowledge-reviewed-bounded-incident"))
    f.expect(
        ack["known_router_cost_usd"] == 0.00001
        and ack["total_accounting_bound_usd"] == 0.02
        and ack["provisional_exposure_usd"] == 0.01999,
        "known-router-charge-unchanged-plus-full-reserve-accounting-bound",
    )
    f.expect(json.loads(f.sql(call(), "exact-ack-replay")) == ack, "exact-acknowledgement-replay")
    status = json.loads(
        f.sql("SELECT onet_matching.task_status('route-task')", "status-bounded-exposure")
    )
    f.expect(
        status["known_cost_usd"] == 0.00001
        and status["accounting_usd"] == 0.02
        and status["provisional_exposure_usd"] == 0.01999
        and status["provisional_route_incidents"] == 1,
        "status-separates-actual-known-cost-from-provisional-exposure",
    )
    f.expect(
        f.sql(
            "SELECT jsonb_agg(a ORDER BY attempt_id) FROM onet_matching.attempt a WHERE batch_id='route-pilot'",
            "history-after-ack",
        )
        == before_history,
        "exact-original-attempt-history-cost-and-response-preserved",
    )
    error(
        f,
        "UPDATE onet_matching.route_incident_acknowledgement SET notes='change'",
        "ONET_MATCHING_IMMUTABLE",
    )
    error(f, "DELETE FROM onet_matching.route_incident_acknowledgement", "ONET_MATCHING_IMMUTABLE")
    error(f, "TRUNCATE onet_matching.route_incident_acknowledgement", "ONET_MATCHING_IMMUTABLE")
    error(
        f,
        "INSERT INTO onet_matching.route_incident_acknowledgement SELECT acknowledgement_id||'-forged',attempt_id,response_sha256,attempt_hash,input_hash,settings_hash,known_router_cost_usd,total_accounting_bound_usd,provisional_exposure_usd,pinned_byok_cost_bound_usd,basis,actor,notes,evidence,acknowledged_at FROM onet_matching.route_incident_acknowledgement",
        "ONET_MATCHING_ROUTE_ACK_INSERT_NOT_VERIFIED",
    )
    (f.work / "mock/mode").write_text("valid")
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-never-sent-only-resume",
        {
            "ONET_BATCH_ID": "route-pilot",
            "REQUEST_WORKERS": 1,
            "ONET_RESUME": "Y",
            "API_KEY_FILE": base.REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(f.count() == 3, "resume-sends-only-two-never-sent-no-rejected-repost")
    f.expect(
        f.sql(
            "SELECT onet_matching.hash(to_jsonb(a)) FROM onet_matching.attempt a WHERE attempt_id="
            + q(aid),
            "rejected-hash-after-resume",
        )
        == f.sql(
            "SELECT attempt_hash FROM onet_matching.route_incident_acknowledgement",
            "ack-attempt-hash",
        ),
        "rejected-original-history-remains-exact-after-resume",
    )
    f.expect(
        f.sql(
            "SELECT count(*) FROM onet_matching.graph_rows('route-task') WHERE properties->>'attempt_id'="
            + q(aid),
            "rejected-unpublishable",
        )
        == "0",
        "acknowledged-route-result-stays-unpublishable",
    )
    error(
        f,
        "INSERT INTO onet_matching.route_incident_acknowledgement SELECT acknowledgement_id||'-reduced',attempt_id,response_sha256,attempt_hash,input_hash,settings_hash,known_router_cost_usd,known_router_cost_usd,0,pinned_byok_cost_bound_usd,basis,actor,notes,evidence,acknowledged_at FROM onet_matching.route_incident_acknowledgement",
        "ONET_MATCHING_ROUTE_ACK_INSERT_NOT_VERIFIED",
    )
    envelope = json.loads(body)
    for kind in [
        "unknown-charge",
        "wrong-provider",
        "wrong-model",
        "extra-rejection",
        "byok-success",
        "transport",
    ]:
        changed = copy.deepcopy(envelope)
        status_code = 200
        if kind == "unknown-charge":
            changed["usage"].pop("cost")
        elif kind == "wrong-provider":
            changed["provider"] = "Other"
        elif kind == "wrong-model":
            changed["model"] = "other/model"
        elif kind == "extra-rejection":
            changed["choices"][0]["finish_reason"] = "length"
        elif kind == "byok-success":
            changed["usage"]["is_byok"] = True
        elif kind == "transport":
            status_code = 0
        fixture_body = json.dumps(changed)
        fixture_hash = hashlib.sha256(fixture_body.encode()).hexdigest()
        statement = (
            "BEGIN; SELECT onet_matching.plan_batch('route-task','invalid-"
            + kind
            + "','[\"jobkorea:posting:4\",\"jobkorea:posting:5\"]','PILOT',2,0.25); DO $case$ DECLARE token uuid; first_id text; next_id text; BEGIN token:=(onet_matching.start_execution('invalid-"
            + kind
            + "',1)->>'execution_token')::uuid; SELECT attempt_id INTO first_id FROM onet_matching.attempt WHERE batch_id='invalid-"
            + kind
            + "' AND ordinal=1; SELECT attempt_id INTO next_id FROM onet_matching.attempt WHERE batch_id='invalid-"
            + kind
            + "' AND ordinal=2; IF NOT onet_matching.admit_request(first_id,token) THEN RAISE EXCEPTION 'FIXTURE_RESERVATION'; END IF; PERFORM onet_matching.save_response(first_id,"
            + str(status_code)
            + ","
            + q(fixture_body)
            + ",10); IF "
            + ("true" if kind in ["unknown-charge", "transport"] else "false")
            + " AND onet_matching.request_context(next_id,token) IS NOT NULL THEN RAISE EXCEPTION 'FIXTURE_UNKNOWN_NOT_BLOCKED'; END IF; PERFORM onet_matching.assert_route_incident_acknowledgement(first_id,"
            + q(fixture_hash)
            + ",'fixture-coordinator','adversarial route acknowledgement',"
            + js(good)
            + "); END $case$; ROLLBACK;"
        )
        error(f, statement, "ONET_MATCHING_ROUTE_ACK_REQUIRES_EXACT_FULLY_COSTED_ROUTE_REJECTION")
        f.expect(
            f.sql(
                "SELECT count(*) FROM onet_matching.attempt WHERE batch_id='invalid-" + kind + "'",
                "invalid-rolled-back-" + kind,
            )
            == "0",
            "invalid-acknowledgement-fails-and-rolls-back-" + kind,
        )
    task("paid-copy-task")
    error(
        f,
        "BEGIN; SELECT onet_matching.plan_batch('paid-copy-task','paid-copy','[\"jobkorea:posting:0\"]','PILOT',1,0.25); DO $copy$ DECLARE token uuid; id text; BEGIN token:=(onet_matching.start_execution('paid-copy',1)->>'execution_token')::uuid; SELECT attempt_id INTO id FROM onet_matching.attempt WHERE batch_id='paid-copy'; PERFORM onet_matching.admit_request(id,token); END $copy$; ROLLBACK;",
        "ONET_MATCHING_ALREADY_PAID_NO_RETRY",
    )
    budget_settings = dict(settings, max_cost_usd=0.001)
    task("budget-task", budget_settings)
    f.sql(
        "SELECT onet_matching.plan_batch('budget-task','budget-pilot','[\"jobkorea:posting:3\"]','PILOT',1,0.25)",
        "plan-budget",
    )
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-cumulative-budget-block",
        {
            "ONET_BATCH_ID": "budget-pilot",
            "REQUEST_WORKERS": 1,
            "API_KEY_FILE": base.REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(f.count() == 3, "budget-block-before-any-post")
    f.expect(
        json.loads(f.sql("SELECT onet_matching.task_status('route-task')", "final-accounting"))[
            "accounting_usd"
        ]
        == 0.02042,
        "known-router-plus-provisional-hold-plus-two-byok-costs-shared",
    )
    global_settings = dict(settings, request_reserve_usd=0.5)
    task("global-fill-task", global_settings)
    f.sql(
        "SELECT onet_matching.plan_batch('global-fill-task','fill-pilot','[\"jobkorea:posting:3\"]','PILOT',1,0.5)",
        "fill-pilot-plan",
    )
    fill_body = copy.deepcopy(envelope)
    fill_body["usage"].update(is_byok=True, cost=0, cost_details={"upstream_inference_cost": 0.5})
    fill_body = json.dumps(fill_body)
    f.sql(
        "DO $fill$ DECLARE token uuid; aid text; BEGIN token:=(onet_matching.start_execution('fill-pilot',1)->>'execution_token')::uuid; SELECT attempt_id INTO aid FROM onet_matching.attempt WHERE batch_id='fill-pilot'; IF NOT onet_matching.admit_request(aid,token) THEN RAISE EXCEPTION 'FILL_PILOT_ADMISSION'; END IF; PERFORM onet_matching.save_response(aid,200,"
        + q(fill_body)
        + ",10); PERFORM onet_matching.end_execution(token); END $fill$; SELECT onet_matching.approve_scale('global-fill-task','fixture-coordinator','Known mock pilot only for shared cap proof')",
        "fill-pilot-known-charge",
    )
    selection = ["jobkorea:posting:" + str(n) for n in range(4, 82)]
    f.sql(
        "SELECT onet_matching.plan_batch('global-fill-task','fill-full',"
        + js(selection)
        + ",'FULL',78,40)",
        "fill-full-plan",
    )
    f.sql(
        "DO $fill$ DECLARE token uuid; aid text; BEGIN token:=(onet_matching.start_execution('fill-full',1)->>'execution_token')::uuid; FOR aid IN SELECT attempt_id FROM onet_matching.attempt WHERE batch_id='fill-full' ORDER BY ordinal LOOP IF NOT onet_matching.admit_request(aid,token) THEN RAISE EXCEPTION 'FILL_ADMISSION'; END IF; PERFORM onet_matching.save_response(aid,200,"
        + q(fill_body)
        + ",10); END LOOP; PERFORM onet_matching.end_execution(token); END $fill$;",
        "fill-full-known-charges",
    )
    task("global-boundary-task", dict(settings, request_reserve_usd=0.49))
    f.sql(
        "SELECT onet_matching.plan_batch('global-boundary-task','global-boundary','[\"jobkorea:posting:83\"]','PILOT',1,0.5)",
        "global-boundary-plan",
    )
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-global-provisional-budget-boundary",
        {
            "ONET_BATCH_ID": "global-boundary",
            "REQUEST_WORKERS": 1,
            "API_KEY_FILE": base.REMOTE + "/inputs/key.csv",
        },
    )
    accounting = json.loads(
        f.sql(
            "SELECT onet_matching.task_status('global-boundary-task')", "global-boundary-accounting"
        )
    )
    f.expect(
        accounting["known_cost_usd"] + 0.49 < 40
        and accounting["accounting_usd"] + 0.49 > 40
        and f.count() == 3,
        "shared40cap-includes-provisional-exposure-before-post",
    )
    f.sql(
        "SELECT onet_matching.stop_task('route-task','fixture-coordinator','Stopped task remains stopped after recovery')",
        "stop-task",
    )
    error(
        f,
        "SELECT onet_matching.start_execution('route-pilot',1,true)",
        "ONET_MATCHING_TASK_STOPPED",
    )
    f.expect(
        f.sql("SELECT count(*) FROM retention.writer", "writer-cleanup") == "0", "no-owned-writers"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-proof", type=Path, required=True)
    parser.add_argument("--prompt-code", type=Path, required=True)
    args = parser.parse_args()
    prompt = prompt_module(args.prompt_code)
    old = base.MOCK
    needle = 'String body="{\\"id\\"'
    assert needle in old
    base.MOCK = old.replace(
        needle, 'String byok=mode.equals("router")?"false":"true";\n   ' + needle
    ).replace('\\"is_byok\\":true,', '\\"is_byok\\":"+byok+",')
    with tempfile.TemporaryDirectory(prefix="onet-route-synthetic-") as directory:
        source = Path(directory) / "source.json"
        source.write_text("[]\n")
        f = base.Fixture(source)
        try:
            f.boot()
            check(f, prompt, args.base_proof)
            f.receipt["status"] = "PASSED_ONET_MATCHING_NATIVE"
        except Exception as failure:
            f.receipt.update(status="FAILED", error=type(failure).__name__ + ": " + str(failure))
            raise
        finally:
            f.close()
            (f.work / "receipt.json").chmod(0o400)
            print(str(f.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
