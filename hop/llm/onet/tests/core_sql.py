"""Real isolated PostgreSQL qualification; synthetic local evidence, no HTTP/key."""
# Measured follow-up, 2026-10-14: PostgreSQL btrim() accepts an exact citation
# consisting only of "\n\n" when it occurs in a source string; Python's str.strip()
# rejects it. Qualify a separate successor using a [:space:] non-whitespace guard
# for citation, reason and abstention text. Qualified native files stay frozen;
# the coordinator independently Python-validates actual outputs before scaling
# and publication. Scalar outputs/matches/citations already return issues safely.
# Embedded SQL fixtures preserve exact literal values.
# ruff: noqa: E501

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from hop.llm.onet.prompt import PROMPT_HASH, admitted_fields, build_request  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "onet_catalog_fixture", ROOT / "hop/ingestions/onet/tests/core_sql.py"
)
assert spec and spec.loader
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)
quote = catalog.quote


def quoted(value: object) -> str:
    return quote(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def qualify() -> dict:
    f = catalog.Fixture()
    try:
        f.boot()
        payload = catalog.small_payload()
        release = f.import_payload(payload)
        f.sql(
            "SELECT classification.begin_graph_load("
            + quote(release)
            + ",'fixture-db','fixture-catalog'); SELECT classification.finish_graph_load('fixture-catalog',(SELECT expected_nodes FROM classification.graph_load WHERE load_id='fixture-catalog'),(SELECT expected_edges FROM classification.graph_load WHERE load_id='fixture-catalog'),true); SELECT classification.activate_catalog("
            + quote(release)
            + ",'fixture-db','fixture-catalog')"
        )
        f.sql("""
CREATE SCHEMA ingestion;
CREATE TABLE ingestion.source_graph_projection(run_id text PRIMARY KEY,source_id text,state text,loader_version text,content_sha256 text,verified_at timestamptz);
CREATE TABLE ingestion.source_graph_membership(run_id text,record_id text,identity_id text,kind text);
CREATE TABLE ingestion.source_graph_record_evidence(run_id text,record_id text,source_record_id text);
INSERT INTO ingestion.source_graph_projection VALUES('fixture-source','jobkorea','READY','hop-graph-batchfree-v1',repeat('a',64),clock_timestamp());
""")
        for sql in sorted((ROOT / "hop/llm/onet/sql").glob("*.sql")):
            f.sql(sql.read_text())
        settings = {
            "max_cost_usd": "0.02",
            "request_reserve_usd": "0.01",
            "max_output_tokens": 1024,
            "max_matches": 3,
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "model": "openai/gpt-5.6-luna",
            "prompt_hash": PROMPT_HASH,
            "retrieval_hash": "b" * 64,
            "read_timeout_ms": 1000,
            "request_delay_ms": 0,
            "execute_requests": "Y",
            "frozen_input_count": 5,
        }
        f.sql(
            "SELECT onet_matching.create_task('fixture-task',"
            + quote(release)
            + ",'fixture-db',"
            + quoted(settings)
            + ")"
        )
        occupation = next(term for term in payload["terms"] if term["term_kind"] == "OCCUPATION")
        candidate = {
            "occupation_code": occupation["code"],
            "term_id": occupation["term_id"],
            "label": occupation["preferred_label"],
            "description": occupation["description"],
        }
        manifest = []
        for index in range(5):
            identity = f"jobkorea:posting:{index}"
            facts = {
                "title": "소프트웨어 개발자",
                "positions": [{"title": "개발자"}],
                "ncs_category_names": "정보통신",
            }
            digest = f.sql(
                "SELECT encode(sha256(convert_to(" + quoted(facts) + "::text,'UTF8')),'hex')"
            )
            fields = admitted_fields(facts)
            candidates = [] if index == 4 else [candidate]
            manifest.append(
                {
                    "posting_identity": identity,
                    "source_id": "jobkorea",
                    "source_run_id": "fixture-source",
                    "source_record_id": str(index),
                    "source_facts": facts,
                    "source_facts_sha256": digest,
                    "source_fields": fields,
                    "candidates": candidates,
                    "request_body": build_request(fields, candidates),
                }
            )
            f.sql(
                "INSERT INTO ingestion.source_graph_membership VALUES('fixture-source',"
                + quote(str(index))
                + ","
                + quote(identity)
                + ",'JobPosting'); INSERT INTO ingestion.source_graph_record_evidence VALUES('fixture-source',"
                + quote(str(index))
                + ","
                + quote(str(index))
                + ")"
            )
        first = f.sql(
            "SELECT onet_matching.freeze_inputs('fixture-task'," + quoted(manifest[:2]) + ",1)"
        )
        replay = json.loads(
            f.sql(
                "SELECT onet_matching.freeze_inputs('fixture-task'," + quoted(manifest[:2]) + ",1)"
            )
        )
        f.expect(
            replay.get("replay") is True
            and json.loads(first)["chunk_hash"] == replay["chunk_hash"],
            "immutable-chunk-replay",
        )
        changed = copy.deepcopy(manifest[:2])
        changed[0]["source_fields"]["title"] = "다른 값"
        f.error(
            "SELECT onet_matching.freeze_inputs('fixture-task'," + quoted(changed) + ",1)",
            "ONET_MATCHING_FROZEN_MANIFEST_CHANGED",
        )
        f.error(
            "SELECT onet_matching.plan_batch('fixture-task','too-early','[\"jobkorea:posting:0\"]')",
            "ONET_MATCHING_INPUTS_NOT_FROZEN",
        )
        f.error(
            "SELECT onet_matching.freeze_inputs('fixture-task'," + quoted(manifest[2:]) + ",4)",
            "ONET_MATCHING_NONCONTIGUOUS_FREEZE",
        )
        f.sql("SELECT onet_matching.freeze_inputs('fixture-task'," + quoted(manifest[2:]) + ",3)")
        f.error(
            "SELECT onet_matching.finalize_freeze('fixture-task',4)",
            "ONET_MATCHING_INCOMPLETE_FREEZE",
        )
        f.sql("SELECT onet_matching.finalize_freeze('fixture-task',5)")
        f.error(
            "INSERT INTO onet_matching.input SELECT * FROM onet_matching.input WHERE task_id='fixture-task' LIMIT 1",
            "ONET_MATCHING_INPUT_INSERT_AFTER_FREEZE",
        )
        f.error(
            "SELECT onet_matching.plan_batch('fixture-task','full-too-early','[\"jobkorea:posting:0\"]','FULL',1,1)",
            "ONET_MATCHING_BATCH_OR_SCALE_GATE_INVALID",
        )
        f.sql(
            "SELECT onet_matching.plan_batch('fixture-task','pilot','[\"jobkorea:posting:0\",\"jobkorea:posting:1\",\"jobkorea:posting:2\",\"jobkorea:posting:4\"]','PILOT',3,0.02)"
        )
        token = json.loads(f.sql("SELECT onet_matching.start_execution('pilot',2)"))[
            "execution_token"
        ]
        attempts = json.loads(
            f.sql(
                "SELECT jsonb_agg(attempt_id ORDER BY ordinal) FROM onet_matching.attempt WHERE batch_id='pilot' AND state='PLANNED'"
            )
        )
        f.expect(
            f.sql(
                "SELECT onet_matching.admit_request("
                + quote(attempts[0])
                + ","
                + quote(token)
                + "::uuid)"
            )
            == "t",
            "first-atomic-admission",
        )
        f.expect(
            f.sql(
                "SELECT onet_matching.admit_request("
                + quote(attempts[1])
                + ","
                + quote(token)
                + "::uuid)"
            )
            == "t",
            "second-concurrent-hold",
        )
        f.expect(
            f.sql(
                "SELECT onet_matching.admit_request("
                + quote(attempts[2])
                + ","
                + quote(token)
                + "::uuid)"
            )
            == "f",
            "worker-bound-no-overreservation",
        )
        output = {
            "outcome": "matched",
            "matches": [
                {
                    "occupation_code": occupation["code"],
                    "match_rank": 1,
                    "reason": "Source identifies software development.",
                    "evidence": [{"field": "positions", "quote": "개발자"}],
                }
            ],
            "abstain_reason": "",
        }
        f.expect(
            f.sql(
                "SELECT onet_matching.output_issues("
                + quoted(output)
                + ","
                + quoted(manifest[0]["source_fields"])
                + ","
                + quoted([candidate])
                + ",3)"
            )
            == "[]",
            "recursive-original-string-citation",
        )
        bad = copy.deepcopy(output)
        bad["matches"][0]["evidence"] = [{"field": "ncs_category_names", "quote": "정보통신"}]
        f.expect(
            "INVALID_EXACT_SOURCE_CITATION"
            in f.sql(
                "SELECT onet_matching.output_issues("
                + quoted(bad)
                + ","
                + quoted(manifest[0]["source_fields"])
                + ","
                + quoted([candidate])
                + ",3)"
            ),
            "context-is-not-citation",
        )
        envelope = {
            "id": "fixture-response",
            "model": "openai/gpt-5.6-luna",
            "provider": "OpenAI",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(output, ensure_ascii=False)},
                }
            ],
            "usage": {
                "is_byok": True,
                "cost": 0.0001,
                "cost_details": {"upstream_inference_cost": 0.0009},
                "prompt_tokens": 100,
                "completion_tokens": 50,
            },
        }
        f.sql(
            "SELECT onet_matching.save_response("
            + quote(attempts[0])
            + ",200,"
            + quote(json.dumps(envelope, ensure_ascii=False))
            + ",100)"
        )
        f.expect(
            f.sql(
                "SELECT cost_usd FROM onet_matching.attempt WHERE attempt_id=" + quote(attempts[0])
            )
            == "0.0010",
            "combined-byok-router-accounting",
        )
        f.sql("SELECT onet_matching.save_response(" + quote(attempts[1]) + ",0,NULL,100)")
        f.expect(
            f.sql(
                "SELECT onet_matching.admit_request("
                + quote(attempts[2])
                + ","
                + quote(token)
                + "::uuid)"
            )
            == "f",
            "unknown-charge-stops-next-admission",
        )
        status = json.loads(f.sql("SELECT onet_matching.task_status('fixture-task')"))
        f.expect(
            status["unknown_holds"] == 1 and float(status["accounting_usd"]) == 0.011,
            "unknown-charge-retains-reservation",
        )
        f.error(
            "SELECT onet_matching.start_execution('pilot',2,true)",
            "ONET_MATCHING_EXECUTION_ALREADY_STARTED_NO_RETRY",
        )
        f.error(
            "SELECT onet_matching.approve_scale('fixture-task','assistant','Review complete')",
            "ONET_MATCHING_SCALE_REQUIRES_MEASURED_REVIEWED_BYOK_PILOT",
        )
        f.sql("SELECT onet_matching.end_execution(" + quote(token) + "::uuid)")
        f.expect(
            f.sql("SELECT count(*) FROM onet_matching.attempt WHERE state='SKIPPED'") == "1",
            "no-candidate-local-abstention-no-post",
        )
        f.sql(
            "SELECT classification.begin_graph_load("
            + quote(release)
            + ",'fixture-db','partial-rollover')"
        )
        f.error(
            "SELECT onet_matching.assert_catalog(" + quote(release) + ",'fixture-db')",
            "ONET_MATCHING_CATALOG_NOT_READY_VERIFIED_OR_ROLLOVER",
        )
        f.sql("SELECT classification.fail_graph_load('partial-rollover')")
        f.error(
            "SELECT onet_matching.assert_catalog(" + quote(release) + ",'fixture-db')",
            "ONET_MATCHING_CATALOG_NOT_READY_VERIFIED_OR_ROLLOVER",
        )
        return {
            "status": "PASSED",
            "checks": f.checks,
            "source_http_calls": 0,
            "provider_calls": 0,
            "production_writes": 0,
        }
    finally:
        f.cleanup()


if __name__ == "__main__":
    print(json.dumps(qualify(), ensure_ascii=False, indent=2))
