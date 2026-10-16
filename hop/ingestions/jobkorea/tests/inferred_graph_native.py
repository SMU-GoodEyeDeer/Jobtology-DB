# ruff: noqa: E501
# pyright: reportUnknownMemberType=false
"""Run the native inferred graph workflow on one wholly synthetic local record.

Unique disposable Hop/PostgreSQL/Neo4j containers use an internal network. A
guarded test-only response pipeline injects synthetic JSON; no API or key is used.
"""

import json
import os
import tempfile
from pathlib import Path

from linking_native import LinkingFixture


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def js(value: dict[str, object]) -> str:
    return q(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def graph(fixture: LinkingFixture, query: str, label: str) -> str:
    return fixture.command(
        ["docker", "exec", "-i", fixture.neo, "cypher-shell", "--format", "plain"],
        label,
        query + ";\n",
    ).lower()


def check(fixture: LinkingFixture) -> None:
    fixture.install()
    fixture.run("full.hwf", "native-synthetic-job-source-graph")
    jobs = fixture.sql(
        "SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "jobs-pin"
    )
    ncs = fixture.seed_ncs()
    fixture.run(
        "../../graph/load_snapshot.hwf",
        "native-synthetic-ncs-source-graph",
        extra={"RUN_ID": ncs, "NEO4J_CONNECTION": "jobtology-neo4j"},
    )
    fixture.run(
        "../../operations/record_graph_export.hpl",
        "native-synthetic-ncs-graph-checkpoint",
        extra={"RUN_ID": ncs},
    )
    fixture.run("install_inferred_occupations.hwf", "native-inferred-installer")
    fixture.sql(
        f"SELECT enrichment.prepare_jobkorea_input_bundle({q(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={q(jobs)}",
        "freeze-source",
    )
    posting = fixture.sql(
        f"SELECT posting_id FROM enrichment.input_bundle WHERE job_run_id={q(jobs)}", "posting-id"
    )
    settings: dict[str, object] = dict(
        categorize_model="fixture/metadata",
        extra_params={},
        limit=1,
        candidate_limit=12,
        max_matches=1,
        max_input_chars=16000,
        max_output_tokens=768,
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
    )
    fixture.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('native-graph',{q(jobs)},{q(ncs)},{js(settings)})",
        "plan-offline-inference",
    )
    attempt = fixture.sql(
        "SELECT attempt_id FROM enrichment.attempt WHERE batch_id='native-graph' AND state='PLANNED'",
        "attempt-id",
    )
    fixture.response(
        attempt,
        dict(
            outcome="matched",
            matches=[
                dict(
                    occupation_code="20010204",
                    reason="SYNTHETIC title database role",
                    evidence=[dict(field="title", quote="데이터베이스")],
                )
            ],
            abstain_reason="",
        ),
        "inject-offline-envelope",
    )
    fixture.sql(
        "SELECT enrichment.finish_metadata_occupation_batch('native-graph')",
        "capture-offline-result",
    )
    fixture.expect(
        fixture.sql(
            "SELECT count(*) FROM enrichment.metadata_occupation_candidate", "candidate-count"
        )
        == "1",
        "one-validated-synthetic-candidate",
    )
    params = {"JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs, "INCLUDE_UNREVIEWED": "Y"}
    fixture.run("publish_inferred_occupations.hwf", "native-inferred-graph-publish", extra=params)
    fixture.expect(
        "true"
        in graph(
            fixture,
            "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=1 AND all(x IN collect(r) WHERE x.current=true AND x.stage='STAGING' AND x.review_status='UNREVIEWED' AND x.confidence IS NULL AND x.confidence_state='UNASSESSED') AS valid",
            "graph-unreviewed-readback",
        ).splitlines(),
        "native-staging-unreviewed-null-confidence",
    )
    fixture.expect(
        fixture.sql(
            "SELECT count(*) FROM enrichment.metadata_occupation_graph_guard WHERE state='READY'",
            "ready-guard",
        )
        == "1",
        "native-readback-finishes-sql-guard",
    )
    fixture.expect(
        fixture.sql(
            "SELECT count(*) FROM retention.writer WHERE writer_id='metadata-occupation-graph'",
            "writer-released",
        )
        == "0",
        "native-success-releases-exact-lease",
    )
    fixture.run("publish_inferred_occupations.hwf", "native-inferred-graph-replay", extra=params)
    fixture.expect(
        "true"
        in graph(
            fixture,
            "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=1 AS valid",
            "graph-idempotent-count",
        ).splitlines(),
        "native-replay-one-edge",
    )
    result = fixture.sql("SELECT result_id FROM enrichment.metadata_occupation_result", "result-id")
    fixture.sql(
        f"SELECT enrichment.decide_metadata_occupation({q(result)},'ACCEPT','synthetic-independent-reviewer','assistant','SYNTHETIC fixture review')",
        "review-synthetic-result",
    )
    fixture.run("publish_inferred_occupations.hwf", "native-reviewed-graph-publish", extra=params)
    fixture.expect(
        "true"
        in graph(
            fixture,
            "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=1 AND all(x IN collect(r) WHERE x.review_status='ASSISTANT_REVIEWED' AND x.accepted=true AND x.current=true) AS valid",
            "graph-review-readback",
        ).splitlines(),
        "native-actual-review-status-projected",
    )
    fixture.sql(
        f"SELECT enrichment.decide_metadata_occupation({q(result)},'REJECT','synthetic-independent-reviewer','assistant','SYNTHETIC fixture revocation')",
        "reject-synthetic-result",
    )
    fixture.run("publish_inferred_occupations.hwf", "native-empty-graph-publish", extra=params)
    fixture.expect(
        "true"
        in graph(
            fixture,
            "MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=1 AND all(x IN collect(r) WHERE x.current=false) AS valid",
            "graph-rejection-readback",
        ).splitlines(),
        "native-empty-projection-retires-rejected-edge",
    )
    fixture.sql(
        f"SELECT enrichment.decide_metadata_occupation({q(result)},'ACCEPT','synthetic-independent-reviewer','assistant','SYNTHETIC fixture restore before rollover')",
        "restore-reviewed-synthetic-result",
    )
    fixture.run("publish_inferred_occupations.hwf", "restored-accepted-graph-publish", extra=params)
    # Publish newer accepted observations, then replay the original frozen pins.
    # Source proofs remain historical while the stable business nodes are current.
    before = fixture.sql(
        f"SELECT enrichment.metadata_occupation_graph_hash({q(jobs)},{q(ncs)},true)",
        "old-projection-hash",
    )
    newer_ncs = ncs + "-newer"
    fixture.sql(
        f"""INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,completed_at)
VALUES({q(newer_ncs)},'ncs_competency','FULL','SYNTHETIC_FIXTURE','READY',clock_timestamp());
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
VALUES({q(newer_ncs)},'synthetic','FILE',2,2);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,
 http_status,retrieved_at,declared_total,effective_page,effective_page_size,item_count,selected,verified_at)
VALUES({q(newer_ncs)},'synthetic','synthetic',1,'synthetic-newer-ncs.json',repeat('b',64),1,'UTF-8',200,
clock_timestamp(),2,1,2,2,true,clock_timestamp());
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
SELECT {q(newer_ncs)},document_id,locator,source_record_id,
 jsonb_set(source_payload,'{{occupation_name}}','"새로운 DB 이름"'),
 jsonb_set(normalized,'{{occupation_name}}','"새로운 DB 이름"')
FROM ingestion.record WHERE run_id={q(ncs)};""",
        "newer-synthetic-ncs",
    )
    fixture.run(
        "../../graph/load_snapshot.hwf",
        "newer-synthetic-ncs-graph",
        extra={"RUN_ID": newer_ncs, "NEO4J_CONNECTION": "jobtology-neo4j"},
    )
    updated = fixture.work / "inputs/updated.json"
    updated.write_text(
        json.dumps(
            [
                dict(
                    product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000001",
                    job_title="업데이트된 데이터베이스 개발자",
                )
            ],
            ensure_ascii=False,
        )
    )
    fixture.run("full.hwf", "newer-synthetic-job-source-graph", input_name="updated.json")
    fixture.run(
        "publish_inferred_occupations.hwf", "historical-frozen-pin-publication", extra=params
    )
    fixture.expect(
        fixture.sql(
            f"SELECT enrichment.metadata_occupation_graph_hash({q(jobs)},{q(ncs)},true)",
            "historical-hash-readback",
        )
        == before,
        "historical-frozen-payload-hash-preserved",
    )
    fixture.expect(
        "true"
        in graph(
            fixture,
            "MATCH (o:entity:occupation {id:'ncs:occupation:20010204'}) RETURN o.source_run_id="
            + json.dumps(newer_ncs)
            + " AS valid",
            "updated-occupation-still-supports-old-pin",
        ).splitlines(),
        "native-historical-pin-with-updated-business-node",
    )
    graph(
        fixture,
        "MATCH (o:entity:occupation) SET o.code='99999999' RETURN count(o)",
        "break-fixture-only-business-endpoint",
    )
    fixture.run(
        "publish_inferred_occupations.hwf",
        "native-source-marker-failure",
        extra=params,
        success=False,
    )
    fixture.expect(
        fixture.sql(
            "SELECT count(*) FROM enrichment.metadata_occupation_graph_guard WHERE state='FAILED'",
            "failed-guard",
        )
        == "1",
        "native-source-guard-failure-recorded",
    )
    fixture.expect(
        fixture.sql(
            "SELECT count(*) FROM retention.writer WHERE writer_id='metadata-occupation-graph'",
            "failure-writer-released",
        )
        == "0",
        "native-failure-releases-only-own-lease",
    )
    graph(
        fixture,
        "MATCH (o:entity:occupation) SET o.code='20010204' RETURN count(o)",
        "restore-fixture-only-business-endpoint",
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "source-request-count")
        == "0",
        "zero-source-http-ledger",
    )
    fixture.expect(
        "true"
        in graph(
            fixture,
            "MATCH (n) WHERE n:ingestionBatch OR n:ingestionRecord OR n:archivedRecord RETURN count(n)=0 AS valid",
            "no-source-history-node-recreation",
        ).splitlines(),
        "native-no-source-history-node-recreation",
    )
    ready_guards = fixture.sql(
        "SELECT count(*) FROM enrichment.metadata_occupation_graph_guard", "before-missing-proof"
    )
    fixture.sql(
        f"UPDATE ingestion.source_graph_projection SET state='FAILED',verified_at=NULL WHERE run_id={q(ncs)}",
        "missing-ready-source-proof",
    )
    fixture.run(
        "publish_inferred_occupations.hwf",
        "missing-pg-source-proof-blocked",
        extra=params,
        success=False,
    )
    fixture.expect(
        fixture.sql(
            "SELECT count(*) FROM enrichment.metadata_occupation_graph_guard", "after-missing-proof"
        )
        == ready_guards,
        "missing-source-proof-rejected-before-graph-guard-write",
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM retention.writer", "missing-proof-no-lease") == "0",
        "missing-source-proof-leaves-no-writer",
    )
    fixture.receipt["status"] = "PASSED_NATIVE_INFERRED_GRAPH"
    fixture.receipt["native_hop_plugin_execution"] = True
    fixture.receipt["synthetic_response_injection"] = True


def main() -> None:
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="jobtology-inferred-graph-native-") as temp:
        source = Path(temp) / "synthetic.json"
        source.write_text(
            json.dumps(
                [
                    dict(
                        product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000001",
                        job_title="데이터베이스 개발자",
                    )
                ],
                ensure_ascii=False,
            )
        )
        fixture = LinkingFixture(source)
        try:
            fixture.boot()
            check(fixture)
        except BaseException:
            fixture.receipt["status"] = "FAILED_NATIVE_INFERRED_GRAPH"
            raise
        finally:
            fixture.close()
            print("Protected receipt:", fixture.work / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
