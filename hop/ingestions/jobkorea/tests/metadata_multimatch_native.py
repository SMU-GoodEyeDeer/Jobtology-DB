"""Real Hop/PostgreSQL/Neo4j multi-match publication with synthetic local evidence."""

# Synthetic SQL and Cypher intentionally retain their precise literals.
# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from inferred_graph_native import graph, js, q
from linking_native import LinkingFixture

TITLE = "데이터베이스 관리자 및 웹 개발자"
ROOT = Path(__file__).resolve().parents[4]
ARTIFACTS = (
    "llm/sql/037_metadata_occupation_multimatch.sql",
    "llm/prompts/categorize-ko-metadata-occupation-v3.txt",
    "llm/prompts/categorize-ko-metadata-occupation-v3.schema.json",
    "llm/install.hwf",
    "ingestions/jobkorea/install_inferred_occupations.hwf",
    "ingestions/jobkorea/execute_inferred_occupations.hwf",
    "ingestions/jobkorea/execute_inferred_occupation_workers.hwf",
    "ingestions/jobkorea/load_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/verify_inferred_occupation_graph.hpl",
)


class MultiFixture(LinkingFixture):
    def seed_ncs(self):
        ncs = "synthetic-multi-ncs-" + self.token
        rows = [
            dict(
                kind="Competency",
                code="2001020403_24v1",
                name="데이터베이스 설계",
                definition="데이터베이스 설계",
                occupation_code="20010204",
                occupation_name="DB엔지니어링",
                level=4,
                classification_names=["정보통신", "정보기술", "정보기술개발"],
            ),
            dict(
                kind="Competency",
                code="2001020201_24v1",
                name="웹 개발",
                definition="웹 응용 소프트웨어 개발",
                occupation_code="20010202",
                occupation_name="응용SW엔지니어링",
                level=4,
                classification_names=["정보통신", "정보기술", "정보기술개발"],
            ),
        ]
        self.sql(
            f"""INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,completed_at)
VALUES({q(ncs)},'ncs_competency','FULL','SYNTHETIC_MULTIMATCH','READY',clock_timestamp());
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
VALUES({q(ncs)},'synthetic','FILE',2,2);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,
http_status,retrieved_at,declared_total,effective_page,effective_page_size,item_count,selected,verified_at)
VALUES({q(ncs)},'synthetic','synthetic',1,'synthetic-multi-ncs.json',repeat('a',64),1,'UTF-8',200,
clock_timestamp(),2,1,2,2,true,clock_timestamp());""",
            "multi-ncs-ledger",
        )
        for index, row in enumerate(rows):
            self.sql(
                f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(ncs)},'synthetic',{q('/' + str(index))},{q(row['code'])},{js(row)},{js(row)})",
                "multi-ncs-row-" + str(index),
            )
        self.expect(
            self.sql(
                f"SELECT count(*) FROM ingestion.validation_issue WHERE run_id={q(ncs)}",
                "multi-ncs-validation",
            )
            == "0",
            "validated-synthetic-two-occupations",
        )
        return ncs


def check(fixture: MultiFixture) -> None:
    fixture.install()
    fixture.run("full.hwf", "native-multi-job-source-graph")
    jobs = fixture.sql(
        "SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "multi-jobs-pin"
    )
    ncs = fixture.seed_ncs()
    fixture.run(
        "../../graph/load_snapshot.hwf",
        "multi-ncs-source-graph",
        extra={"RUN_ID": ncs, "NEO4J_CONNECTION": "jobtology-neo4j"},
    )
    fixture.run(
        "../../operations/record_graph_export.hpl", "multi-ncs-proof", extra={"RUN_ID": ncs}
    )
    fixture.run("install_inferred_occupations.hwf", "multi-native-installer")
    fixture.sql(
        f"SELECT enrichment.prepare_jobkorea_input_bundle({q(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={q(jobs)}",
        "multi-freeze-source",
    )
    posting = fixture.sql(
        f"SELECT posting_id FROM enrichment.input_bundle WHERE job_run_id={q(jobs)}",
        "multi-posting",
    )
    settings = dict(
        categorize_model="fixture/metadata",
        extra_params={},
        limit=1,
        candidate_limit=12,
        max_matches=3,
        max_input_chars=16000,
        max_output_tokens=1536,
        max_requests=1,
        request_reserve_usd=0.005,
        max_cost_usd=0.05,
        daily_budget_usd=4.75,
        request_delay_ms=0,
        read_timeout_ms=5000,
        execute_requests="Y",
        reuse_cache="N",
        endpoint="http://" + fixture.prefix + "-mock:18080/chat/completions",
        posting_ids=posting,
        provider_only="openai",
        reasoning_effort="none",
        prompt_version="ko-metadata-occupation-v3",
    )
    fixture.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('native-multi',{q(jobs)},{q(ncs)},{js(settings)})",
        "multi-plan",
    )
    attempt = fixture.sql(
        "SELECT attempt_id FROM enrichment.attempt WHERE batch_id='native-multi' AND state='PLANNED'",
        "multi-attempt",
    )
    matches = [
        dict(
            occupation_code=code,
            match_rank=rank,
            role_anchor=dict(field="title", quote=quote),
            reason="SYNTHETIC independent explicit advertised role",
            evidence=[dict(field="title", quote=quote)],
        )
        for rank, (code, quote) in enumerate(
            [("20010204", "데이터베이스 관리자"), ("20010202", "웹 개발자")], 1
        )
    ]
    fixture.response(
        attempt,
        dict(outcome="matched", matches=matches, abstain_reason=""),
        "multi-synthetic-response",
    )
    fixture.sql(
        "SELECT enrichment.finish_metadata_occupation_batch('native-multi')", "multi-capture"
    )
    before = fixture.sql(
        "SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_no)::text) FROM enrichment.metadata_occupation_result r",
        "multi-frozen-results-before",
    )
    fixture.run("../../llm/install.hwf", "multi-canonical-installer-replay")
    fixture.expect(
        before
        == fixture.sql(
            "SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_no)::text) FROM enrichment.metadata_occupation_result r",
            "multi-frozen-results-after",
        ),
        "canonical-replay-preserves-frozen-v3-result",
    )
    params = {"JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs, "INCLUDE_UNREVIEWED": "Y"}

    def publish(label: str, include: str = "Y") -> None:
        fixture.run(
            "publish_inferred_occupations.hwf",
            label,
            extra=params | {"INCLUDE_UNREVIEWED": include},
        )

    def expect(query: str, label: str) -> None:
        fixture.expect("true" in graph(fixture, query, label).splitlines(), label)

    publish("native-two-occupation-publish")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=2 AND all(x IN collect(r) WHERE x.current=true AND x.occupation_scheme='NCS' AND x.rank_basis='SOURCE_ANCHOR_DISPLAY_ORDER_V1' AND x.review_status='UNREVIEWED' AND x.confidence IS NULL) AS valid",
        "two-direct-scheme-rank-staging-edges",
    )
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN sum(CASE WHEN r.current_primary THEN 1 ELSE 0 END)=1 AND sum(CASE WHEN r.original_primary THEN 1 ELSE 0 END)=1 AND sum(r.match_rank)=3 AS valid",
        "one-display-primary-two-stable-ranks",
    )
    publish("native-two-occupation-replay")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=2 AS valid",
        "two-edges-idempotent-replay",
    )
    result = fixture.sql(
        "SELECT result_id FROM enrichment.metadata_occupation_result", "multi-result"
    )
    first = fixture.sql(
        f"SELECT candidate_id FROM enrichment.metadata_occupation_candidate WHERE result_id={q(result)} AND occupation_code='20010204'",
        "multi-first",
    )
    second = fixture.sql(
        f"SELECT candidate_id FROM enrichment.metadata_occupation_candidate WHERE result_id={q(result)} AND occupation_code='20010202'",
        "multi-second",
    )
    fixture.sql(
        f"SELECT enrichment.decide_metadata_occupation_candidate({q(first)},'ACCEPT','independent-first-reviewer','assistant','SYNTHETIC individual first-role review')",
        "multi-first-review",
    )
    publish("multi-one-reviewed-publish")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() WHERE r.current RETURN count(r)=2 AND sum(CASE WHEN r.accepted THEN 1 ELSE 0 END)=1 AND sum(CASE WHEN r.review_status='UNREVIEWED' THEN 1 ELSE 0 END)=1 AS valid",
        "review-is-per-candidate",
    )
    fixture.sql(
        f"SELECT enrichment.decide_metadata_occupation_candidate({q(first)},'REJECT','independent-first-reviewer','assistant','SYNTHETIC revoke first-role only')",
        "multi-first-reject",
    )
    publish("multi-first-rejected-publish")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() WHERE r.current RETURN count(r)=1 AND all(x IN collect(r) WHERE x.match_rank=2 AND x.current_primary=true AND x.original_primary=false AND x.review_status='UNREVIEWED') AS valid",
        "reject-first-retains-second-original-rank",
    )
    publish("multi-reviewed-only-empty", "N")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=2 AND all(x IN collect(r) WHERE x.current=false) AS valid",
        "review-filter-keeps-historical-edges",
    )
    fixture.sql(
        f"SELECT enrichment.decide_metadata_occupation_candidate({q(second)},'ACCEPT','independent-second-reviewer','human','SYNTHETIC individual second-role review')",
        "multi-second-review",
    )
    publish("multi-second-reviewed-publish", "N")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() WHERE r.current RETURN count(r)=1 AND all(x IN collect(r) WHERE x.review_status='HUMAN_REVIEWED' AND x.match_rank=2 AND x.current_primary=true) AS valid",
        "second-review-status-direct-readback",
    )
    fixture.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('native-multi-pending',{q(jobs)},{q(ncs)},{js(settings)})",
        "multi-new-pending",
    )
    publish("multi-pending-preserves-completed-projection", "N")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() WHERE r.current RETURN count(r)=1 AND all(x IN collect(r) WHERE x.candidate_id='"
        + second
        + "') AS valid",
        "pending-successor-preserves-reviewed-link",
    )
    legacy_settings = settings | dict(
        prompt_version="ko-metadata-occupation-v2", max_matches=1, max_output_tokens=768
    )
    fixture.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('native-multi-legacy',{q(jobs)},{q(ncs)},{js(legacy_settings)})",
        "multi-plan-legacy-successor",
    )
    legacy_attempt = fixture.sql(
        "SELECT attempt_id FROM enrichment.attempt WHERE batch_id='native-multi-legacy' AND state='PLANNED'",
        "multi-legacy-attempt",
    )
    legacy_match = {
        key: value for key, value in matches[0].items() if key not in ("match_rank", "role_anchor")
    }
    fixture.response(
        legacy_attempt,
        dict(outcome="matched", matches=[legacy_match], abstain_reason=""),
        "multi-legacy-synthetic-response",
    )
    fixture.sql(
        "SELECT enrichment.finish_metadata_occupation_batch('native-multi-legacy')",
        "multi-legacy-capture",
    )
    publish("multi-legacy-payload-publish")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() WHERE r.current RETURN count(r)=1 AND all(x IN collect(r) WHERE x.occupation_scheme IS NULL AND x.match_rank IS NULL AND x.rank_basis IS NULL AND x.original_primary IS NULL AND x.current_primary IS NULL) AS valid",
        "legacy-payload-clears-all-v3-only-fields",
    )
    token = fixture.sql(
        f"SELECT enrichment.begin_metadata_occupation_graph({q(jobs)},{q(ncs)},true)",
        "multi-tamper-writer",
    )
    phase_params = params | {"GRAPH_TOKEN": token, "NEO4J_CONNECTION": "jobtology-neo4j"}
    fixture.run("begin_inferred_occupation_graph.hpl", "multi-tamper-begin", extra=phase_params)
    fixture.run("load_inferred_occupation_graph.hpl", "multi-tamper-load", extra=phase_params)
    graph(
        fixture,
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() WHERE r.projection_token='"
        + token
        + "' SET r.current_primary=true RETURN count(r)",
        "multi-tamper-legacy-primary",
    )
    fixture.run(
        "verify_inferred_occupation_graph.hpl",
        "multi-legacy-primary-tamper-rejected",
        extra=phase_params,
        success=False,
    )
    fixture.expect(
        "Inferred occupation projection differs from its exact frozen pins/evidence."
        in (fixture.logs / "multi-legacy-primary-tamper-rejected.log").read_text(),
        "legacy-primary-tamper-rejected-by-exact-readback",
    )
    fixture.run(
        "fail_inferred_occupation_graph.hpl", "multi-tamper-owned-cleanup", extra=phase_params
    )
    publish("multi-legacy-tamper-repair")
    expect(
        "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() WHERE r.current RETURN count(r)=1 AND all(x IN collect(r) WHERE x.current_primary IS NULL) AS valid",
        "legacy-replay-clears-tampered-field",
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM retention.writer", "multi-final-writers") == "0",
        "multi-all-writer-leases-released",
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "multi-source-request-count")
        == "0",
        "multi-zero-source-http-ledger",
    )
    expect(
        "MATCH (n) WHERE n:ingestionBatch OR n:ingestionRecord OR n:archivedRecord RETURN count(n)=0 AS valid",
        "multi-no-audit-scaffold-recreation",
    )
    fixture.receipt["status"] = "PASSED"
    fixture.receipt["proof_kind"] = "native_multimatch_graph"
    fixture.receipt["native_hop_plugin_execution"] = True
    fixture.receipt["synthetic_response_injection"] = True


def main() -> None:
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="jobtology-multimatch-native-") as temp:
        source = Path(temp) / "synthetic.json"
        source.write_text(
            json.dumps(
                [
                    dict(
                        product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000001",
                        job_title=TITLE,
                    )
                ],
                ensure_ascii=False,
            )
        )
        fixture = MultiFixture(source)
        fixture.receipt["started_at"] = datetime.now(UTC).isoformat()
        fixture.receipt["artifact_hashes"] = {
            relative: hashlib.sha256((ROOT / "hop" / relative).read_bytes()).hexdigest()
            for relative in ARTIFACTS
        }
        fixture.receipt["sql_sha256"] = {
            relative: value
            for relative, value in fixture.receipt["artifact_hashes"].items()
            if relative.endswith(".sql")
        }
        try:
            fixture.boot()
            check(fixture)
            assert fixture.receipt["artifact_hashes"] == {
                relative: hashlib.sha256((ROOT / "hop" / relative).read_bytes()).hexdigest()
                for relative in ARTIFACTS
            }
        except BaseException:
            fixture.receipt["status"] = "FAILED_NATIVE_MULTIMATCH_GRAPH"
            raise
        finally:
            fixture.close()
            fixture.receipt["cleanup_confirmed"] = (
                fixture.receipt["private_scratch_removed"]
                and fixture.receipt["disposable_resources_removed"]
            )
            fixture.receipt["finished_at"] = datetime.now(UTC).isoformat()
            if not fixture.receipt["cleanup_confirmed"]:
                fixture.receipt["status"] = "FAILED_CLEANUP"
            (fixture.work / "receipt.json").write_text(
                json.dumps(fixture.receipt, ensure_ascii=False, indent=2) + "\n"
            )
            print("Protected receipt:", fixture.work / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
