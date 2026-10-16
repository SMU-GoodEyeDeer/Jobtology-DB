"""Network-none additive hierarchy correction, legacy history and cache tests."""

# SQL fixtures preserve exact source JSON.
# ruff: noqa: E501
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("JOBTOLOGY_CONTEXT_TEST_REPO", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / "hop/llm/tests"))
f: Any = importlib.import_module("jobkorea_linking")
MIGRATION = Path(__file__).resolve().parents[1] / "sql/032_metadata_occupation_context.sql"
CLASSES = ["정보통신", "정보기술", "정보기술개발"]
WORKERS_SQL = Path(
    os.environ.get(
        "JOBTOLOGY_CONTEXT_WORKERS_SQL", ROOT / "hop/llm/sql/031_metadata_occupation_workers.sql"
    )
)


def source_transaction(rows: list[dict[str, Any]]) -> str:
    return (
        "BEGIN; INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) "
        "VALUES('context-source-test','ncs_competency','REPLAY','LOCAL_CONTEXT_TEST','READY');"
        " INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) "
        "VALUES('context-source-test','context','FILE',1);"
        " INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) "
        "VALUES('context-source-test','context','context',1,'local-context-fixture',repeat('0',64),0,'UTF-8',200,clock_timestamp(),true);"
        " INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) "
        "SELECT 'context-source-test','context',ordinal::text,value->>'code','{}',value "
        f"FROM jsonb_array_elements({f.js(rows)}) WITH ORDINALITY x(value,ordinal);"
        " SELECT enrichment.prepare_metadata_occupation_catalog('context-source-test'); ROLLBACK;"
    )


def checks() -> None:
    f.sql(
        "UPDATE ingestion.record SET normalized=normalized||"
        + f.js(
            dict(
                code="2001020201_24v1",
                name="응용SW 개발",
                definition="웹 응용 소프트웨어 개발",
                occupation_code="20010202",
                occupation_name="응용SW엔지니어링",
                classification_names=CLASSES,
            )
        )
        + " WHERE run_id='ncs_competency'"
    )
    rows = [
        dict(
            job_title="프론트엔드 개발자",
            job_position="프론트엔드 개발자",
            company_name="Fixture",
            product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/50300000",
        )
    ]
    body = json.dumps(rows, ensure_ascii=False)
    sha = hashlib.sha256(body.encode()).hexdigest()
    jobs = f.sql(
        f"SELECT run_id FROM ingestion.begin_jobkorea_import({f.quote(sha)},{len(body.encode())},'jobkorea/'||{f.quote(sha)}||'/source.json',clock_timestamp())"
    )
    f.sql(
        f"SELECT * FROM ingestion.load_jobkorea_document({f.quote(jobs)},{f.quote(body)}); SELECT ingestion.verify_jobkorea_file({f.quote(jobs)},{f.quote(sha)},{len(body.encode())}); SELECT * FROM ingestion.finalize_jobkorea_import({f.quote(jobs)})"
    )
    posting = "ext-jobkorea-" + hashlib.sha256(b"50300000").hexdigest()
    bundle = f.sql(
        f"SELECT enrichment.prepare_jobkorea_input_bundle({f.quote(jobs)},{f.quote(posting)})"
    )
    opts = dict(
        categorize_model="openai/gpt-5.6-luna",
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
        request_delay_ms=250,
        read_timeout_ms=180000,
        execute_requests="N",
        reuse_cache="Y",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        provider_only="openai",
        reasoning_effort="none",
        posting_ids=posting,
    )
    old_catalog = json.loads(
        f.sql("SELECT enrichment.prepare_metadata_occupation_catalog('ncs_competency')")
    )
    f.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('context-old',{f.quote(jobs)},'ncs_competency',{f.js(opts)})"
    )
    item = f.sql("SELECT item_id FROM enrichment.item WHERE batch_id='context-old'")
    attempt = f.sql("SELECT categorization_id FROM enrichment.item WHERE item_id=" + f.quote(item))
    old_candidates = json.loads(
        f.sql(
            "SELECT candidates FROM enrichment.metadata_occupation_binding WHERE item_id="
            + f.quote(item)
        )
    )
    assert old_candidates[0]["classification_names"] == [None, None, None]
    output = dict(
        outcome="matched",
        matches=[
            dict(
                occupation_code="20010202",
                reason="Original exact title identifies software occupation",
                evidence=[dict(field="title", quote="프론트엔드 개발자")],
            )
        ],
        abstain_reason="",
    )
    f.sql(
        f"UPDATE enrichment.attempt SET state='VALIDATED',parsed_output={f.js(output)},actual_model='openai/gpt-5.6-luna' WHERE attempt_id={f.quote(attempt)}"
    )
    result = f.sql(
        f"SELECT enrichment.capture_metadata_occupation_result({f.quote(item)},'synthetic-extractor')"
    )
    f.sql(
        f"UPDATE enrichment.item SET state='VALIDATED' WHERE item_id={f.quote(item)}; SELECT enrichment.decide_metadata_occupation({f.quote(result)},'ACCEPT','independent-fixture','assistant','Reviewed title scope')"
    )
    graph_sql = (
        f"SELECT enrichment.metadata_occupation_graph_hash({f.quote(jobs)},'ncs_competency',true)"
    )
    old_graph = f.sql(graph_sql)
    history_sql = (
        "SELECT jsonb_build_object("
        + ",".join(
            f"'{table}',(SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM enrichment.metadata_occupation_{table} t)"
            for table in ["catalog", "binding", "result", "candidate", "decision"]
        )
        + ")"
    )
    old_history = f.sql(history_sql)
    old_binding = f.sql(
        f"SELECT enrichment.bind_metadata_occupation_item({f.quote(item)},{f.quote(bundle)},{f.js(old_candidates)})"
    )
    old_cache = f.sql(
        f"SELECT cache_key FROM enrichment.attempt WHERE attempt_id={f.quote(attempt)}"
    )
    original_prompts = f.sql(
        "SELECT jsonb_agg(to_jsonb(p) ORDER BY version,stage) FROM enrichment.prompt p"
    )
    f.sql(MIGRATION.read_text())
    context = json.loads(
        f.sql("SELECT enrichment.prepare_metadata_occupation_catalog('ncs_competency')")
    )
    assert context["catalog_hash"] != old_catalog["catalog_hash"]
    assert context["context_version"] == "ncs-occupation-context-v2"
    assert f.sql(history_sql) == old_history
    assert f.sql(graph_sql) == old_graph
    assert old_binding == f.sql(
        f"SELECT enrichment.bind_metadata_occupation_item({f.quote(item)},{f.quote(bundle)},{f.js(old_candidates)})"
    )
    assert result == f.sql(
        f"SELECT enrichment.capture_metadata_occupation_result({f.quote(item)},'synthetic-extractor')"
    )
    assert (
        json.loads(
            f.sql("SELECT classification_names FROM enrichment.metadata_occupation_catalog_context")
        )
        == CLASSES
    )
    for statement in [
        "UPDATE enrichment.metadata_occupation_catalog_context SET classification_names='[]'",
        "DELETE FROM enrichment.metadata_occupation_catalog_context",
        "TRUNCATE enrichment.metadata_occupation_catalog_context",
    ]:
        f.reject(statement, "IMMUTABLE_METADATA_OCCUPATION_HISTORY")
    # Repeating canonical 029 ->030 ->032 never snapshots or renames a wrapper.
    for _ in range(2):
        f.install("hop/llm/sql/029_metadata_occupation_links.sql")
        f.install("hop/llm/sql/030_metadata_occupation_native.sql")
        if WORKERS_SQL.is_file():
            f.sql(WORKERS_SQL.read_text())
        f.sql(MIGRATION.read_text())
        assert (
            json.loads(
                f.sql("SELECT enrichment.prepare_metadata_occupation_catalog('ncs_competency')")
            )
            == context
        )
        assert f.sql(history_sql) == old_history
        assert f.sql(graph_sql) == old_graph
    f.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('context-new',{f.quote(jobs)},'ncs_competency',{f.js(opts)})"
    )
    new_candidates = json.loads(
        f.sql(
            "SELECT candidates FROM enrichment.metadata_occupation_binding b JOIN enrichment.item i USING(item_id) WHERE i.batch_id='context-new'"
        )
    )
    assert [(c["occupation_code"], c["retrieval_score"]) for c in new_candidates] == [
        (c["occupation_code"], c["retrieval_score"]) for c in old_candidates
    ]
    assert new_candidates[0]["classification_names"] == CLASSES
    assert new_candidates[0]["catalog_hash"] != old_candidates[0]["catalog_hash"]
    assert (
        f.sql("SELECT ncs_hash FROM enrichment.batch WHERE batch_id='context-new'")
        == context["catalog_hash"]
    )
    assert (
        f.sql("SELECT cache_key FROM enrichment.attempt WHERE batch_id='context-new'") != old_cache
    )
    assert f.sql("SELECT state FROM enrichment.attempt WHERE batch_id='context-new'") == "PLANNED"
    request = json.loads(
        f.sql("SELECT request_body FROM enrichment.attempt WHERE batch_id='context-new'")
    )
    assert (
        json.loads(request["messages"][1]["content"])["candidates"][0]["classification_names"]
        == CLASSES
    )
    new_item = f.sql("SELECT item_id FROM enrichment.item WHERE batch_id='context-new'")
    f.reject(
        f"SELECT enrichment.bind_metadata_occupation_item({f.quote(new_item)},{f.quote(bundle)},{f.js(old_candidates)})",
        "CANDIDATE_CHANGED",
    )
    assert original_prompts == f.sql(
        "SELECT jsonb_agg(to_jsonb(p) ORDER BY version,stage) FROM enrichment.prompt p"
    )
    # Invalid/mixed hierarchy is rejected before a new context can be committed;
    # the existing source freeze detects any post-freeze unit modification.
    for bad, issue in [
        (dict(classification_names=["정보통신", None, "정보기술개발"]), "HIERARCHY_INVALID"),
        (dict(classification_names="bad"), "HIERARCHY_MISSING"),
        ({}, "HIERARCHY_MISSING"),
    ]:
        f.reject(f"SELECT enrichment.metadata_occupation_source_classes({f.js(bad)},true)", issue)
    assert json.loads(
        f.sql("SELECT enrichment.metadata_occupation_source_classes('{}',false)")
    ) == [None, None, None]
    flat = dict(
        kind="Competency",
        code="2001020201_24v1",
        name="응용SW 개발",
        definition="웹 개발",
        occupation_code="20010202",
        occupation_name="응용SW엔지니어링",
    )
    assert json.loads(f.sql(source_transaction([flat])))["occupation_count"] == 1
    hierarchical = flat | dict(classification_names=CLASSES)
    mixed = flat | dict(code="2001020202_24v1")
    f.reject(source_transaction([hierarchical, mixed]), "HIERARCHY_MISSING")
    conflicting = mixed | dict(classification_names=["정보통신", "정보기술", "다른 분류"])
    f.reject(source_transaction([hierarchical, conflicting]), "HIERARCHY_INCONSISTENT")
    invalid = hierarchical | dict(classification_names=["정보통신", None, "정보기술개발"])
    f.reject(source_transaction([invalid]), "HIERARCHY_INVALID")
    assert f.sql("SELECT count(*) FROM ingestion.run WHERE run_id='context-source-test'") == "0"
    assert f.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL") == "0"
    assert (
        f.sql("SELECT count(*) FROM ingestion.request_attempt WHERE run_id=" + f.quote(jobs)) == "0"
    )
    print(
        "032 hierarchy context, original history/graph preservation, canonical replay, changed cache/full binding and private zero-call contracts passed",
        flush=True,
    )


def main() -> None:
    try:
        f.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                "none",
                "--name",
                f.NAME,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                os.environ.get("JOBTOLOGY_TEST_POSTGRES_IMAGE", "postgres:18-alpine"),
            ]
        )
        for _ in range(100):
            try:
                if (
                    "PostgreSQL init process complete" in f.command(["docker", "logs", f.NAME])
                    and f.sql("SELECT 1") == "1"
                ):
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        f.install("docs/hop-migration/schema.sql")
        f.install("docs/hop-migration/checks.sql")
        f.sql(f.FIXTURE)
        f.install("docs/hop-migration/operations.sql")
        f.install("hop/llm/sql/001_schema.sql")
        f.install("hop/retention/sql/001_retention.sql")
        for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
            if path.name < "027":
                f.sql(path.read_text())
        f.install("hop/cs/sql/001_common_postings.sql")
        for path in sorted((ROOT / "hop/ingestions/jobkorea/sql").glob("*.sql")):
            f.sql(path.read_text())
        for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
            if path.name < "031":
                f.sql(path.read_text())
        checks()
    finally:
        subprocess.run(["docker", "rm", "-fv", f.NAME], capture_output=True, check=False)


if __name__ == "__main__":
    main()
