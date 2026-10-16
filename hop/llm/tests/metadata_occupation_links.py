"""Native isolated PostgreSQL tests for inferred metadata occupation links.

Uses locally installed images, synthetic local rows and SQL-generated responses.
No HTTP client, provider key or production connection is invoked.
"""
# SQL fixtures preserve explicit literals for source/citation assertions.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import time
from typing import Any

import jobkorea_linking as fixture

f: Any = fixture


def calibrate_local(container: str, jobs: str, ncs: str, sample_limit: int) -> None:
    """Read selected fields into this disposable database; never query URLs."""

    def production_read(statement: str) -> str:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "jobtology",
            ],
            input="BEGIN READ ONLY; SET LOCAL statement_timeout='55s';\n" + statement + "\nCOMMIT;",
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Read-only local calibration query failed")
        return result.stdout.strip()

    units: list[dict[str, Any]] = json.loads(
        production_read(
            "SELECT jsonb_agg(normalized-ARRAY['source_url','url'] ORDER BY source_record_id) FROM ingestion.ready_record "
            f"WHERE run_id={f.quote(ncs)} AND source_id='ncs_competency';"
        )
    )
    selected: list[dict[str, Any]] = json.loads(
        production_read(
            "WITH inputs AS MATERIALIZED (SELECT posting_id,(SELECT jsonb_object_agg(key,value) FROM jsonb_each(source_data) "
            "WHERE key IN('title','role','job_functions') AND jsonb_typeof(value)='string') AS fields "
            f"FROM enrichment.input_bundle WHERE job_run_id={f.quote(jobs)}), selected AS ("
            f"(SELECT * FROM inputs ORDER BY posting_id LIMIT {sample_limit}) UNION "
            "(SELECT * FROM inputs WHERE lower(fields::text) ~ '(cyber threat|data scientist|machine.?vision|클린.*자동화|프로그래밍.*강사|java|python)' "
            "ORDER BY posting_id LIMIT 30)) SELECT jsonb_agg(to_jsonb(selected) ORDER BY posting_id) FROM selected;"
        )
    )
    # Archived production rows remain read-only. Only their accepted NCS facts
    # and model-field whitelist are loaded into the disposable fixture.
    f.sql(
        "INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES('calibration-ncs','ncs_competency','REPLAY','LOCAL_READ_ONLY_CALIBRATION','READY');"
        " INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES('calibration-ncs','calibration','FILE',1);"
        " INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) "
        "VALUES('calibration-ncs','calibration','calibration',1,'local-db-fixture',repeat('0',64),0,'UTF-8',200,clock_timestamp(),true);"
    )
    f.sql(
        "INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) "
        "SELECT 'calibration-ncs','calibration',ordinal::text,value->>'code','{}',value "
        f"FROM jsonb_array_elements({f.js(units)}) WITH ORDINALITY x(value,ordinal);"
    )
    catalog = json.loads(
        f.sql("SELECT enrichment.prepare_metadata_occupation_catalog('calibration-ncs')")
    )
    records: list[dict[str, Any]] = []
    started = time.monotonic()
    for row in selected:
        candidates = json.loads(
            f.sql(
                f"SELECT enrichment.metadata_occupation_candidates('calibration-ncs',{f.js(row['fields'])},12)"
            )
        )
        records.append(
            dict(posting_id=row["posting_id"], fields=row["fields"], candidates=candidates)
        )
    boundaries: list[dict[str, Any]] = []
    for title in [
        "Cyber Threat Analyst",
        "[유명 SCM전문컨설팅회사] Data Scientist",
        "SKT차세대개발 java 통신사",
        "프로그래밍 강사 채용",
        "클린 자동화 장비 기계 설계",
        "Machine Vision 설비 연동 SW개발자",
    ]:
        candidates = json.loads(
            f.sql(
                f"SELECT enrichment.metadata_occupation_candidates('calibration-ncs',{f.js(dict(title=title))},12)"
            )
        )
        boundaries.append(
            dict(
                title=title,
                occupations=[
                    dict(code=c["occupation_code"], name=c["occupation_name"]) for c in candidates
                ],
            )
        )
    print(
        json.dumps(
            dict(
                calibration="LOCAL_READ_ONLY_OFFLINE",
                official_unit_count=len(units),
                occupation_count=catalog["occupation_count"],
                sampled_listings=len(records),
                zero_candidate_count=sum(not r["candidates"] for r in records),
                mean_candidate_json_characters=sum(
                    len(json.dumps(r["candidates"], ensure_ascii=False)) for r in records
                )
                / len(records),
                elapsed_seconds=round(time.monotonic() - started, 3),
                boundary_shortlists=boundaries,
                model_requests=0,
                source_requests=0,
            ),
            ensure_ascii=False,
        ),
        flush=True,
    )


def checks() -> None:
    rows = [
        {"job_title": "  프론트엔드 개발자 채용\n웹 개발  ", "job_position": "프론트엔드 개발자"},
        {"job_title": "  프론트엔드 개발자 채용\n웹 개발  ", "job_position": "프론트엔드 개발자"},
        {"job_title": "채용 공고", "job_position": "전문가"},
    ]
    for index, row in enumerate(rows):
        row.update(
            product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(50200000 + index),
            company_name="Fixture " + str(index),
            job_description_url="https://example.invalid/?signed=private-source-token",
        )
    body = json.dumps(rows, ensure_ascii=False)
    digest = hashlib.sha256(body.encode()).hexdigest()
    jobs = f.sql(
        "SELECT run_id FROM ingestion.begin_jobkorea_import("
        + f.quote(digest)
        + ","
        + str(len(body.encode()))
        + ",'jobkorea/'||"
        + f.quote(digest)
        + "||'/source.json',clock_timestamp())"
    )
    f.sql(
        f"SELECT * FROM ingestion.load_jobkorea_document({f.quote(jobs)},{f.quote(body)});"
        f" SELECT ingestion.verify_jobkorea_file({f.quote(jobs)},{f.quote(digest)},{len(body.encode())});"
        f" SELECT * FROM ingestion.finalize_jobkorea_import({f.quote(jobs)})"
    )
    # Existing fixture has a real accepted NCS run and archived records. Add a
    # second occupation before freezing the derived catalogue.
    f.sql(
        "INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) "
        "SELECT run_id,document_id,'fixture-meta-unit','2001020201_24v1','{}',"
        '\'{"kind":"Competency","code":"2001020201_24v1","name":"응용SW 개발",'
        '"definition":"웹 응용 소프트웨어 개발","occupation_code":"20010202",'
        '"occupation_name":"응용SW엔지니어링","classification_1":"정보통신"}\'::jsonb '
        "FROM ingestion.record WHERE run_id='ncs_competency' LIMIT 1"
    )
    for code, name, definition in [
        ("20010302", "IT기술교육", "프로그래밍 교육과 강의 수행"),
        ("15010201", "기계요소설계", "자동화 장비 기계 요소를 설계하는 능력"),
        ("20010703", "인공지능모델링", "머신 비전 인공지능 모델링"),
        ("20010105", "빅데이터분석", "데이터 분석 통계 모델링"),
        ("20010603", "보안사고분석대응", "사이버 침해 사고 위협 분석"),
    ]:
        data = dict(
            kind="Competency",
            code=code + "01_24v1",
            name=name,
            definition=definition,
            occupation_code=code,
            occupation_name=name,
        )
        f.sql(
            "INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) "
            f"SELECT run_id,document_id,{f.quote('meta-unit-' + code)},{f.quote(data['code'])},'{{}}',{f.js(data)} "
            "FROM ingestion.record WHERE run_id='ncs_competency' LIMIT 1"
        )
    catalog = json.loads(
        f.sql("SELECT enrichment.prepare_metadata_occupation_catalog('ncs_competency')")
    )
    assert catalog["occupation_count"] == 7, catalog
    assert catalog == json.loads(
        f.sql("SELECT enrichment.prepare_metadata_occupation_catalog('ncs_competency')")
    )
    f.reject(
        "SELECT enrichment.prepare_metadata_occupation_catalog('LATEST')", "CURRENT_EXACT_NCS_RUN"
    )
    for title, expected_code in [
        ("프로그래밍 강사 채용", "20010302"),
        ("클린 자동화 장비 기계 설계", "15010201"),
        ("Machine Vision 엔지니어", "20010703"),
        ("Machine Vision 설비 연동 SW개발자", "20010202"),
        ("Cyber Threat Analyst", "20010603"),
        ("[유명 SCM전문컨설팅회사] Data Scientist", "20010105"),
        ("SKT차세대개발 java 통신사", "20010202"),
    ]:
        retrieved = json.loads(
            f.sql(
                f"SELECT enrichment.metadata_occupation_candidates('ncs_competency',{f.js(dict(title=title))},3)"
            )
        )
        assert expected_code in {row["occupation_code"] for row in retrieved}, (title, retrieved)
    original = f.sql(
        "SELECT jsonb_agg(to_jsonb(p) ORDER BY stage) FROM enrichment.prompt p WHERE version='ko-link-v1'"
    )
    bundles: list[tuple[str, str, Any, Any]] = []
    for index in range(3):
        posting = "ext-jobkorea-" + hashlib.sha256(str(50200000 + index).encode()).hexdigest()
        bundle = f.sql(
            f"SELECT enrichment.prepare_jobkorea_input_bundle({f.quote(jobs)},{f.quote(posting)})"
        )
        source = json.loads(
            f.sql(
                f"SELECT source_data FROM enrichment.input_bundle WHERE bundle_id={f.quote(bundle)}"
            )
        )
        candidates = json.loads(
            f.sql(
                f"SELECT enrichment.metadata_occupation_candidates('ncs_competency',{f.js(source)},12)"
            )
        )
        assert "private-source-token" not in json.dumps(candidates)
        if index < 2:
            assert candidates[0]["occupation_code"] == "20010202", candidates
        else:
            assert candidates == [], candidates
        bundles.append((posting, bundle, source, candidates))

    source = bundles[0][2]
    candidates = bundles[0][3]
    output: dict[str, Any] = {
        "outcome": "matched",
        "matches": [
            {
                "occupation_code": "20010202",
                "reason": "제목과 직무명이 프론트엔드 개발자이며 응용SW 직종으로 추정됨. 업무 내용은 미제공.",
                "evidence": [{"field": "role", "quote": "프론트엔드 개발자"}],
            }
        ],
        "abstain_reason": "",
    }
    assert (
        f.sql(
            f"SELECT enrichment.metadata_occupation_output_issues({f.js(output)},{f.js(source)},{f.js(candidates)},2)"
        )
        == "[]"
    )
    invalid = copy.deepcopy(output)
    invalid["matches"][0]["occupation_code"] = "99999999"
    assert "OUTSIDE_SHORTLIST" in f.sql(
        f"SELECT enrichment.metadata_occupation_output_issues({f.js(invalid)},{f.js(source)},{f.js(candidates)},2)"
    )
    for evidence in [
        {"field": "role", "quote": "데이터 분석가"},
        {"field": "company_name_raw", "quote": "Fixture 0"},
        {"field": "role", "quote": ""},
    ]:
        invalid = copy.deepcopy(output)
        invalid["matches"][0]["evidence"] = [evidence]
        assert "UNSUPPORTED_CITATION" in f.sql(
            f"SELECT enrichment.metadata_occupation_output_issues({f.js(invalid)},{f.js(source)},{f.js(candidates)},2)"
        )
    invalid = copy.deepcopy(output)
    invalid["confidence"] = 0.95
    assert "OUTPUT_SHAPE" in f.sql(
        f"SELECT enrichment.metadata_occupation_output_issues({f.js(invalid)},{f.js(source)},{f.js(candidates)},2)"
    )
    f.reject(
        f"SELECT enrichment.metadata_occupation_candidates('ncs_competency',{f.js(source)},31)",
        "CANDIDATE_CAP_1_TO_30",
    )

    settings = dict(
        metadata_scope="NCS_OCCUPATION_INFERENCE_V1",
        prompt_version="ko-metadata-occupation-v1",
        acceptance_policy="REVIEW",
        execute_requests="Y",
        request_reserve_usd=0.001,
        max_cost_usd=0.05,
        daily_budget_usd=0.05,
        max_requests=5,
    )
    f.sql(
        "INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state) VALUES("
        f"'metadata-fixture','ENRICH',{f.quote(jobs)},'ncs_competency',{f.quote(catalog['catalog_hash'])},{f.js(settings)},'RUNNING')"
    )
    results: list[str] = []
    for index, (posting, bundle, _source, candidates) in enumerate(bundles):
        item = "meta-item-" + str(index)
        f.sql(
            "INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal) "
            f"SELECT {f.quote(item)},'metadata-fixture',{f.quote(posting)},source_data,source_hash,{index + 1} "
            f"FROM enrichment.input_bundle WHERE bundle_id={f.quote(bundle)};"
            f" INSERT INTO enrichment.item_input VALUES({f.quote(item)},{f.quote(bundle)})"
        )
        bound = f.sql(
            f"SELECT enrichment.bind_metadata_occupation_item({f.quote(item)},{f.quote(bundle)},{f.js(candidates)})"
        )
        assert bound == f.sql(
            f"SELECT enrichment.bind_metadata_occupation_item({f.quote(item)},{f.quote(bundle)},{f.js(candidates)})"
        )
        forged = copy.deepcopy(candidates)
        if forged:
            forged[0]["occupation_name"] = "invented"
            f.reject(
                f"SELECT enrichment.bind_metadata_occupation_item({f.quote(item)},{f.quote(bundle)},{f.js(forged)})",
                "CANDIDATE_CHANGED",
            )
        if index == 1:
            # Identical 3-field metadata can reuse a prior validated model result,
            # even when employer/source hashes and posting identities differ.
            f.sql(
                f"UPDATE enrichment.item SET categorization_id='meta-attempt-0' WHERE item_id={f.quote(item)}"
            )
        else:
            parsed = (
                output
                if index == 0
                else dict(
                    outcome="abstained",
                    matches=[],
                    abstain_reason="No occupation candidates retrieved from supplied metadata.",
                )
            )
            state = "PLANNED" if index == 0 else "SKIPPED"
            f.sql(
                "INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,candidates,state,parsed_output) "
                f"VALUES('meta-attempt-{index}','metadata-fixture',{f.quote(item)},'categorize','fixture-{index}','{{}}',{f.js(candidates)},{f.quote(state)},{f.js(parsed)});"
                f" UPDATE enrichment.item SET categorization_id='meta-attempt-{index}' WHERE item_id={f.quote(item)}"
            )
            if index == 0:
                f.sql(
                    "SELECT enrichment.reserve_request('meta-attempt-0'); UPDATE enrichment.attempt SET state='VALIDATED',cost_usd=0.0001 WHERE attempt_id='meta-attempt-0'"
                )
        result = f.sql(
            f"SELECT enrichment.capture_metadata_occupation_result({f.quote(item)},'fixture-model-author')"
        )
        assert result == f.sql(
            f"SELECT enrichment.capture_metadata_occupation_result({f.quote(item)},'fixture-model-author')"
        )
        results.append(result)
    assert (
        f.sql(
            "SELECT count(*) FROM enrichment.metadata_occupation_result WHERE confidence IS NULL AND confidence_state='UNASSESSED'"
        )
        == "3"
    )
    assert f.sql("SELECT count(*) FROM enrichment.metadata_occupation_candidate") == "2"
    assert (
        f.sql(
            "SELECT count(*) FROM enrichment.extraction_revision WHERE item_id LIKE 'meta-item-%'"
        )
        == "0"
    )
    assert f.sql("SELECT count(*) FROM enrichment.link_candidate") == "0"
    assert (
        f.sql(
            f"SELECT count(*) FROM enrichment.metadata_occupation_graph_rows({f.quote(jobs)},'ncs_competency')"
        )
        == "0"
    )
    staged = json.loads(
        f.sql(
            f"SELECT jsonb_agg(to_jsonb(g)) FROM enrichment.metadata_occupation_graph_rows({f.quote(jobs)},'ncs_competency',true) g"
        )
    )
    assert len(staged) == 2
    assert all(row["posting_identity"].startswith("source:posting:jobkorea:") for row in staged)
    assert len({row["posting_identity"] for row in staged}) == 2
    assert all(
        row["payload"]["review_status"] == "UNREVIEWED" and not row["payload"]["accepted"]
        for row in staged
    )
    evidence = staged[0]["payload"]["evidence"][0]
    assert evidence["start"] == 1 and evidence["end"] == len("프론트엔드 개발자"), evidence
    f.reject(
        f"SELECT enrichment.decide_metadata_occupation({f.quote(results[0])},'ACCEPT','fixture-model-author','assistant','Self review')",
        "INDEPENDENT_REVIEW_REQUIRED",
    )
    review = f.sql(
        f"SELECT enrichment.decide_metadata_occupation({f.quote(results[0])},'ACCEPT','independent-reviewer','assistant','Exact metadata/occupation context checked; duties remain absent')"
    )
    assert review == f.sql(
        f"SELECT enrichment.decide_metadata_occupation({f.quote(results[0])},'ACCEPT','independent-reviewer','assistant','Exact metadata/occupation context checked; duties remain absent')"
    )
    assert (
        f.sql(
            f"SELECT count(*) FROM enrichment.metadata_occupation_graph_rows({f.quote(jobs)},'ncs_competency')"
        )
        == "1"
    )
    f.sql(
        f"SELECT enrichment.decide_metadata_occupation({f.quote(results[0])},'REJECT','independent-reviewer','assistant','Revoked inferred classification')"
    )
    assert (
        f.sql(
            f"SELECT count(*) FROM enrichment.metadata_occupation_graph_rows({f.quote(jobs)},'ncs_competency',true)"
        )
        == "1"
    )
    packet = json.loads(
        f.sql("SELECT enrichment.metadata_occupation_review_packet('metadata-fixture')")
    )
    assert len(packet["rows"]) == 3 and "private-source-token" not in json.dumps(packet)
    f.reject(
        f"SELECT enrichment.begin_metadata_occupation_graph({f.quote(jobs)},'ncs_competency',true)",
        "REQUIRES_CURRENT_EXACT_SOURCE_GRAPHS",
    )
    f.sql(
        "INSERT INTO ingestion.graph_export(run_id,loader_version) VALUES("
        + f.quote(jobs)
        + ",'synthetic-guard-fixture'),('ncs_competency','synthetic-guard-fixture')"
    )
    token = f.sql(
        f"SELECT enrichment.begin_metadata_occupation_graph({f.quote(jobs)},'ncs_competency',true)"
    )
    f.sql(f"SELECT enrichment.check_metadata_occupation_graph({f.quote(token)})")
    f.reject(
        f"SELECT enrichment.begin_metadata_occupation_graph({f.quote(jobs)},'ncs_competency',true)",
        "GRAPH_ALREADY_ACTIVE",
    )
    f.sql(
        f"SELECT enrichment.decide_metadata_occupation({f.quote(results[1])},'ACCEPT','independent-reviewer','assistant','Second exact metadata suggestion checked')"
    )
    f.reject(
        f"SELECT enrichment.check_metadata_occupation_graph({f.quote(token)})",
        "GRAPH_SOURCE_OR_REVIEW_CHANGED",
    )
    f.sql(f"SELECT enrichment.finish_metadata_occupation_graph({f.quote(token)},true)")
    assert f.sql("SELECT count(*) FROM retention.writer") == "0"
    next_token = f.sql(
        f"SELECT enrichment.begin_metadata_occupation_graph({f.quote(jobs)},'ncs_competency',true)"
    )
    # Retrying an older terminal cleanup cannot release a successor's lease.
    f.sql(f"SELECT enrichment.finish_metadata_occupation_graph({f.quote(token)},true)")
    assert f.sql("SELECT target_id FROM retention.writer") == next_token
    f.sql(f"SELECT enrichment.finish_metadata_occupation_graph({f.quote(next_token)},false)")
    assert f.sql("SELECT count(*) FROM retention.writer") == "0"
    assert (
        f.sql(
            "SELECT string_agg(state,',' ORDER BY created_at) FROM enrichment.metadata_occupation_graph_guard"
        )
        == "FAILED,READY"
    )
    f.reject(
        "UPDATE enrichment.metadata_occupation_graph_guard SET rows_hash=repeat('0',64)",
        "IMMUTABLE_METADATA_OCCUPATION_GRAPH_SCOPE",
    )
    for table in ["catalog", "binding", "result", "candidate", "decision"]:
        f.reject(
            "DELETE FROM enrichment.metadata_occupation_" + table,
            "IMMUTABLE_METADATA_OCCUPATION_HISTORY",
        )
        f.reject(
            "TRUNCATE enrichment.metadata_occupation_" + table + " CASCADE",
            "IMMUTABLE_METADATA_OCCUPATION_HISTORY",
        )
    f.install("hop/llm/sql/029_metadata_occupation_links.sql")
    f.sql(
        "UPDATE ingestion.record SET normalized=normalized||'{\"name\":\"Changed after freeze\"}'::jsonb WHERE run_id='ncs_competency' AND normalized->>'occupation_code'='20010302'"
    )
    f.reject(
        "SELECT enrichment.prepare_metadata_occupation_catalog('ncs_competency')",
        "CATALOG_SOURCE_CHANGED",
    )
    assert original == f.sql(
        "SELECT jsonb_agg(to_jsonb(p) ORDER BY stage) FROM enrichment.prompt p WHERE version='ko-link-v1'"
    )
    assert (
        f.sql("SELECT count(*) FROM ingestion.request_attempt WHERE run_id=" + f.quote(jobs)) == "0"
    )
    assert f.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL") == "1"
    print(
        "Metadata occupation retrieval, frozen bindings, exact citations, cross-posting cache provenance, missing metadata abstention, independent review/revocation, unreviewed staging, immutable history, installer replay and unchanged duty/source contracts passed",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate-local", action="store_true")
    parser.add_argument("--postgres-container", default="b13984985171")
    parser.add_argument(
        "--job-run-id",
        default="jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c",
    )
    parser.add_argument("--ncs-run-id", default="ba32f673-255c-4990-80d4-8dbef6008e2f")
    parser.add_argument("--sample-limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.sample_limit <= 1000:
        parser.error("sample-limit must be 1..1000")
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
        f.sql(
            'UPDATE ingestion.record SET normalized=normalized||\'{"code":"2001020101_24v1","name":"데이터베이스 설계","definition":"데이터 요구사항에 따라 데이터베이스를 설계하는 능력","occupation_code":"20010201","occupation_name":"데이터베이스엔지니어링"}\'::jsonb WHERE run_id=\'ncs_competency\''
        )
        f.install("docs/hop-migration/operations.sql")
        f.install("hop/llm/sql/001_schema.sql")
        f.install("hop/retention/sql/001_retention.sql")
        for path in sorted((f.ROOT / "hop/llm/sql").glob("*.sql")):
            if path.name < "027":
                f.sql(path.read_text())
        for path in sorted((f.ROOT / "hop/ingestions/jobkorea/sql").glob("*.sql")):
            f.sql(path.read_text())
        for path in sorted((f.ROOT / "hop/llm/sql").glob("*.sql")):
            if path.name < "030":
                f.sql(path.read_text())
        checks()
        if args.calibrate_local:
            calibrate_local(
                args.postgres_container, args.job_run_id, args.ncs_run_id, args.sample_limit
            )
    finally:
        subprocess.run(["docker", "rm", "-fv", f.NAME], capture_output=True, check=False)


if __name__ == "__main__":
    main()
