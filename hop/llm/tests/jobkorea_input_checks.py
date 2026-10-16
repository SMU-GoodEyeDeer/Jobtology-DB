"""Frozen local JobKorea model inputs; isolated PostgreSQL, zero HTTP/paid calls.

Run: python hop/llm/tests/jobkorea_input_checks.py
Requires a locally available postgres:18-alpine image. Synthetic source rows
exercise absent descriptions and future supplied narratives without URL recovery.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NAME = "jobtology-jobkorea-input-test-" + uuid.uuid4().hex[:12]


def command(args: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(args, input=stdin, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    return result.stdout.strip()


def sql(statement: str) -> str:
    return command(
        [
            "docker",
            "exec",
            "-i",
            NAME,
            "psql",
            "-X",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
        ],
        statement,
    )


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def js(value: object) -> str:
    return quote(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def expect_failure(statement: str, message: str) -> None:
    try:
        sql(statement)
    except RuntimeError as exc:
        assert message in str(exc), (message, str(exc))
    else:
        raise AssertionError("Expected " + message)


def install(path: str) -> None:
    sql((ROOT / path).read_text())


def checks() -> None:
    # Bootstrap the actual source adapter, including accepted-evidence seals.
    install("docs/hop-migration/schema.sql")
    install("docs/hop-migration/checks.sql")
    install("docs/hop-migration/operations.sql")
    install("hop/llm/sql/001_schema.sql")
    install("hop/retention/sql/001_retention.sql")
    llm_files = [
        path for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")) if int(path.name[:3]) <= 27
    ]
    for path in llm_files:
        sql(path.read_text())
    expect_failure(
        "SELECT enrichment.build_jobkorea_input('absent','ext-jobkorea-'||repeat('0',64))",
        "JOBKOREA_SOURCE_ADAPTER_REQUIRED",
    )
    for path in sorted((ROOT / "hop/ingestions/jobkorea/sql").glob("*.sql")):
        sql(path.read_text())
    for path in llm_files:
        sql(path.read_text())

    base = {
        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109422",
        "job_title": "  데이터 개발자 채용\n\nSQL 담당자  ",
        "company_name": "중소기업",
        "job_position": "데이터 개발자",
        "experience_level": "경력 무관",
        "education_level": "학력 무관",
        "job_functions": "개발·데이터베이스",
        "work_location": "서울",
        "job_description_url": "https://example.invalid/?X-Amz-Signature=synthetic-private-secret",
    }
    narrative = base | {
        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109423",
        "company_name": "  Example employer  ",
        "job_description_text": "  데이터 개발자\n\n데이터베이스를 설계하고 SQL 쿼리를 개발한다  ",
    }
    application = base | {
        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109424",
        "job_position": "홈페이지 지원",
        "company_name": "회사명 비공개",
    }
    body = json.dumps([base, narrative, application], ensure_ascii=False)
    file_hash = hashlib.sha256(body.encode()).hexdigest()
    begun = json.loads(
        sql(
            "SELECT to_jsonb(v) FROM ingestion.begin_jobkorea_import("
            + quote(file_hash)
            + ","
            + str(len(body.encode()))
            + ","
            + quote("jobkorea/" + file_hash + "/source.json")
            + ",'2026-10-07T00:00:00Z',NULL) v"
        )
    )
    jobs = begun["run_id"]
    loaded = json.loads(
        sql(
            "SELECT to_jsonb(v) FROM ingestion.load_jobkorea_document("
            + quote(jobs)
            + ","
            + quote(body)
            + ") v"
        )
    )
    assert loaded["accepted_count"] == 3 and loaded["error_code"] is None, loaded
    sql(
        "SELECT ingestion.verify_jobkorea_file("
        + quote(jobs)
        + ","
        + quote(file_hash)
        + ","
        + str(len(body.encode()))
        + ")"
    )
    accepted = json.loads(
        sql("SELECT to_jsonb(v) FROM ingestion.finalize_jobkorea_import(" + quote(jobs) + ") v")
    )
    assert accepted["state"] == "READY", accepted
    source_before = sql("SELECT ingestion.jobkorea_row_manifest(" + quote(jobs) + ")")
    posting = "ext-jobkorea-" + hashlib.sha256(b"50109422").hexdigest()
    with_text = "ext-jobkorea-" + hashlib.sha256(b"50109423").hexdigest()
    application_id = "ext-jobkorea-" + hashlib.sha256(b"50109424").hexdigest()
    prepared = json.loads(
        sql(
            "SELECT enrichment.prepare_jobkorea_inputs("
            + quote(jobs)
            + ","
            + quote(posting + "|" + with_text + "|" + application_id)
            + ",3)"
        )
    )
    assert prepared["postings"] == 3 and prepared["job_run_id"] == jobs
    before = sql("SELECT jsonb_agg(to_jsonb(b) ORDER BY posting_id) FROM enrichment.input_bundle b")
    assert sql("SELECT count(*) FROM ingestion.llm_posting WHERE source_id='jobkorea'") == "3"
    bundle = json.loads(
        sql("SELECT to_jsonb(b) FROM enrichment.input_bundle b WHERE posting_id=" + quote(posting))
    )
    source = bundle["source_data"]
    assert source["title"] == base["job_title"]
    assert source["company_name_raw"] == "중소기업" and "organization_name" not in source
    assert (
        source["role"] == base["job_position"]
        and source["experience_raw"] == base["experience_level"]
    )
    assert source["job_functions"] == base["job_functions"]
    assert "description_text" not in source and "duties_text" not in source
    assert source["_input"]["content_status"] == "MISSING"
    assert source["_input"]["metadata_extraction_eligible"] is True
    assert source["_input"]["full_description_eligible"] is False
    assert source["_input"]["metadata"]["deadline_basis"] == "USER_POLICY"
    assert source["_input"]["metadata"]["deadline_kind"] == "ROLLING"
    assert bundle["manifest"]["scraped_at"] is None
    assert bundle["manifest"]["document"]["source_locator"] == "/0"
    assert bundle["manifest"]["fields"]["title"]["source_locator"] == "/0/job_title"
    assert "source_locator" not in json.dumps(source)
    assert source["_input"]["fields"]["title"]["offset_unit"] == "unicode-codepoint-one-inclusive"
    assert "synthetic-private-secret" not in json.dumps(bundle)
    assert "product_page_url" not in json.dumps(source)
    passages = json.loads(sql("SELECT enrichment.source_passages_v2(" + js(source) + ")"))
    assert [p["id"] for p in passages if p["field"] == "title"] == ["title:1", "title:3"]
    assert {p["field"] for p in passages} >= {"role", "experience_raw", "job_functions"}
    for passage in passages:
        assert source[passage["field"]][passage["start"] - 1 : passage["end"]] == passage["text"]

    title_only = dict(
        positions=[dict(id="p1", name="데이터 개발자", evidence_ids=["role:1"])],
        duties=[],
        requirements=[],
        duties_status="not_stated",
    )
    assert (
        sql("SELECT enrichment.output_issues_link_v1(" + js(title_only) + "," + js(source) + ")")
        == "[]"
    )
    hydrated = json.loads(
        sql("SELECT enrichment.hydrate_link_v1(" + js(title_only) + "," + js(source) + ")")
    )
    assert hydrated["source_metadata"] == source["_input"]["metadata"]
    assert hydrated["source_metadata"]["role"] == "데이터 개발자"
    assert hydrated["source_metadata"]["employer_identity_kind"] == "CATEGORY_ONLY"
    invented = copy.deepcopy(title_only)
    invented["duties"] = [
        dict(
            position_ids=["p1"], text_parts=["개발·데이터베이스"], evidence_ids=["job_functions:1"]
        )
    ]
    invented["duties_status"] = "explicit"
    assert "duties:NON_DUTY_FIELD" in sql(
        "SELECT enrichment.output_issues_link_v1(" + js(invented) + "," + js(source) + ")"
    )
    base_schema = json.loads(
        sql(
            "SELECT output_schema FROM enrichment.prompt "
            "WHERE version='ko-link-v1' AND stage='extract'"
        )
    )
    bound = json.loads(
        sql(
            "SELECT enrichment.link_bound_extract_schema_v1("
            + js(base_schema)
            + ","
            + js(source)
            + ")"
        )
    )
    assert bound["properties"]["duties"]["maxItems"] == 0
    assert (
        sql("SELECT enrichment.schema_issues_request_v1(" + js(invented) + "," + js(bound) + ")")
        != "[]"
    )

    supplied = json.loads(
        sql("SELECT source_data FROM enrichment.input_bundle WHERE posting_id=" + quote(with_text))
    )
    assert supplied["description_text"] == narrative["job_description_text"]
    assert supplied["organization_name"] == narrative["company_name"]
    assert supplied["_input"]["full_description_eligible"] is True
    explicit = copy.deepcopy(title_only)
    explicit["duties"] = [
        dict(
            position_ids=["p1"],
            text_parts=["데이터베이스를 설계하고 SQL 쿼리를 개발한다"],
            evidence_ids=["description_text:3"],
        )
    ]
    explicit["duties_status"] = "explicit"
    assert (
        sql("SELECT enrichment.output_issues_link_v1(" + js(explicit) + "," + js(supplied) + ")")
        == "[]"
    )
    app_source = json.loads(
        sql(
            "SELECT source_data FROM enrichment.input_bundle WHERE posting_id="
            + quote(application_id)
        )
    )
    assert "role" not in app_source and "organization_name" not in app_source

    # Timezone, replay and migration replay cannot change a frozen bundle.
    sql(
        "SET TIME ZONE 'Asia/Seoul'; SELECT enrichment.verify_input_bundle("
        + quote(bundle["bundle_id"])
        + ")"
    )
    assert (
        sql(
            "SELECT enrichment.prepare_jobkorea_input_bundle("
            + quote(jobs)
            + ","
            + quote(posting)
            + ")"
        )
        == bundle["bundle_id"]
    )
    install("hop/llm/sql/017_input_bundles.sql")
    install("hop/llm/sql/027_jobkorea_inputs.sql")
    sql("SELECT enrichment.verify_input_bundle(" + quote(bundle["bundle_id"]) + ")")
    assert (
        sql("SELECT jsonb_agg(to_jsonb(b) ORDER BY posting_id) FROM enrichment.input_bundle b")
        == before
    )
    expect_failure(
        "UPDATE enrichment.input_bundle SET manifest='{}' WHERE bundle_id="
        + quote(bundle["bundle_id"]),
        "APPEND_ONLY_REVIEW_HISTORY",
    )
    expect_failure("TRUNCATE enrichment.input_bundle CASCADE", "APPEND_ONLY_REVIEW_HISTORY")
    expect_failure(
        "SELECT enrichment.prepare_jobkorea_inputs(" + quote(jobs) + ",'',3)",
        "JOBKOREA_INPUT_EXPLICIT_SELECTION_REQUIRED",
    )
    expect_failure(
        "SELECT enrichment.prepare_jobkorea_input_bundle('LATEST'," + quote(posting) + ")",
        "JOBKOREA_INPUT_REQUIRES_EXACT_SNAPSHOT_AND_POSTING",
    )
    expect_failure(
        "SELECT enrichment.prepare_jobkorea_inputs("
        + quote(jobs)
        + ","
        + quote(posting + "|" + posting)
        + ",3)",
        "INVALID_OR_EXCESSIVE_INPUT_POSTING_SELECTION",
    )
    expect_failure(
        "SELECT enrichment.prepare_jobkorea_inputs("
        + quote(jobs)
        + ","
        + quote(posting + "|" + with_text)
        + ",1)",
        "INVALID_OR_EXCESSIVE_INPUT_POSTING_SELECTION",
    )
    expect_failure(
        "SELECT enrichment.prepare_jobkorea_input_bundle("
        + quote(jobs)
        + ",'ext-jobkorea-'||repeat('0',64))",
        "query returned no rows",
    )
    # A new file/run and changed raw row pointer affect audit bundle identity,
    # while identical observed evidence retains the same model content hash.
    reordered_body = json.dumps([narrative, application, base], ensure_ascii=False)
    reordered_hash = hashlib.sha256(reordered_body.encode()).hexdigest()
    reordered_size = len(reordered_body.encode())
    reordered_receipt = json.loads(
        sql(
            "SELECT to_jsonb(v) FROM ingestion.begin_jobkorea_import("
            + quote(reordered_hash)
            + ","
            + str(reordered_size)
            + ","
            + quote("jobkorea/" + reordered_hash + "/source.json")
            + ",'2026-10-07T00:00:00Z',NULL) v"
        )
    )
    reordered_jobs = reordered_receipt["run_id"]
    sql(
        "SELECT ingestion.load_jobkorea_document("
        + quote(reordered_jobs)
        + ","
        + quote(reordered_body)
        + ")"
    )
    sql(
        "SELECT ingestion.verify_jobkorea_file("
        + quote(reordered_jobs)
        + ","
        + quote(reordered_hash)
        + ","
        + str(reordered_size)
        + ")"
    )
    reordered_accepted = json.loads(
        sql(
            "SELECT to_jsonb(v) FROM ingestion.finalize_jobkorea_import("
            + quote(reordered_jobs)
            + ") v"
        )
    )
    assert reordered_accepted["state"] == "READY", reordered_accepted
    reordered_id = sql(
        "SELECT enrichment.prepare_jobkorea_input_bundle("
        + quote(reordered_jobs)
        + ","
        + quote(posting)
        + ")"
    )
    reordered_bundle = json.loads(
        sql(
            "SELECT to_jsonb(b) FROM enrichment.input_bundle b WHERE bundle_id="
            + quote(reordered_id)
        )
    )
    assert reordered_jobs != jobs and reordered_id != bundle["bundle_id"]
    assert reordered_bundle["source_data"] == source
    assert reordered_bundle["source_hash"] == bundle["source_hash"]
    assert reordered_bundle["manifest"]["document"]["source_locator"] == "/2"
    assert reordered_bundle["manifest"]["fields"]["title"]["source_locator"] == "/2/job_title"
    sql("SELECT enrichment.verify_input_bundle(" + quote(reordered_id) + ")")
    # Rebuilding proves the actual source binding, independently of the table's
    # source_hash check. A self-consistent forged input cannot enter item review.
    forged = copy.deepcopy(source)
    forged["title"] = "발명한 제목"
    forged_id = "f" * 64
    sql(
        "INSERT INTO enrichment.input_bundle"
        "(bundle_id,job_run_id,posting_id,source_data,source_hash,manifest) VALUES("
        + quote(forged_id)
        + ","
        + quote(jobs)
        + ","
        + quote(posting)
        + ","
        + js(forged)
        + ",enrichment.hash("
        + js(forged)
        + "::text),"
        + js(bundle["manifest"])
        + ")"
    )
    expect_failure(
        "SELECT enrichment.verify_input_bundle(" + quote(forged_id) + ")",
        "IMMUTABLE_INPUT_BUNDLE_CHANGED",
    )
    sql(
        "INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) "
        "VALUES('fixture-ncs','ncs_competency','REPLAY','fixture','LOADING');"
        "INSERT INTO enrichment.batch"
        "(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state) VALUES("
        "'fixture-batch','ENRICH'," + quote(jobs) + ",'fixture-ncs','fixture','{}','PLANNED');"
        "INSERT INTO enrichment.item"
        "(item_id,batch_id,posting_id,source_data,source_hash,ordinal) VALUES("
        "'fixture-item','fixture-batch',"
        + quote(posting)
        + ","
        + js(source)
        + ","
        + quote(bundle["source_hash"])
        + ",1)"
    )
    expect_failure(
        "SELECT enrichment.verify_item_input('fixture-item')", "INPUT_BUNDLE_BINDING_REQUIRED"
    )
    sql(
        "INSERT INTO enrichment.item_input(item_id,bundle_id) VALUES('fixture-item',"
        + quote(bundle["bundle_id"])
        + ");"
        "SELECT enrichment.verify_item_input('fixture-item')"
    )
    sql(
        "INSERT INTO enrichment.item"
        "(item_id,batch_id,posting_id,source_data,source_hash,ordinal) VALUES("
        "'fixture-wrong','fixture-batch',"
        + quote(with_text)
        + ","
        + js(source)
        + ","
        + quote(bundle["source_hash"])
        + ",2);"
        "INSERT INTO enrichment.item_input(item_id,bundle_id) VALUES('fixture-wrong',"
        + quote(bundle["bundle_id"])
        + ")"
    )
    expect_failure(
        "SELECT enrichment.verify_item_input('fixture-wrong')", "ITEM_INPUT_BUNDLE_MISMATCH"
    )
    assert sql("SELECT ingestion.jobkorea_row_manifest(" + quote(jobs) + ")") == source_before
    assert sql("SELECT count(*) FROM ingestion.request_attempt") == "0"
    assert sql("SELECT count(*) FROM enrichment.attempt") == "0"
    legacy = {
        "title": "기존 공고",
        "eligibility_text": "기존 원문",
        "role": "새 필드",
        "experience_raw": "경력",
        "job_functions": "분류",
    }
    expected_legacy = {"title": "기존 공고", "eligibility_text": "기존 원문"}
    assert json.loads(sql("SELECT enrichment.input_fields(" + js(legacy) + ")")) == expected_legacy
    assert sql(
        "SELECT enrichment.hydrate_link_v1(" + js(title_only) + "," + js(legacy) + ")"
    ) == sql(
        "SELECT enrichment.hydrate_v3("
        + js(title_only)
        + ","
        + js(legacy)
        + ')||\'{"schema_version":"ko-link-v1","extraction_scope":"DUTIES_ONLY"}\'::jsonb'
    )
    assert json.loads(sql("SELECT enrichment.source_fields(" + js(source) + ")")) == {
        k: v for k, v in source.items() if k in {"title", "education", "regions"}
    }
    full_preparation_checks([base, narrative, application], source)
    print(
        "JobKorea frozen input/evidence/replay/legacy contracts passed; zero HTTP and paid calls",
        flush=True,
    )


def full_preparation_checks(rows: list[dict[str, str]], original: dict[str, object]) -> None:
    """Real PostgreSQL commit interruption, immutable provenance and all-row coverage."""
    path = ROOT / "hop/ingestions/jobkorea/tools/prepare_inputs.py"
    spec = importlib.util.spec_from_file_location("jobkorea_full_inputs", path)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    def imported(body: str) -> tuple[str, str]:
        digest = hashlib.sha256(body.encode()).hexdigest()
        begun = json.loads(
            sql(
                "SELECT to_jsonb(v) FROM ingestion.begin_jobkorea_ndjson_import("
                + quote(digest)
                + ","
                + str(len(body.encode()))
                + ","
                + quote("jobkorea/" + digest + "/source.ndjson")
                + ",clock_timestamp()) v"
            )
        )
        run = begun["run_id"]
        sql(
            "SELECT * FROM ingestion.append_jobkorea_ndjson_batch("
            + quote(run)
            + ",0,1,"
            + quote(body)
            + ","
            + quote(digest)
            + ")"
        )
        ready = json.loads(
            sql(
                "SELECT to_jsonb(v) FROM ingestion.seal_jobkorea_ndjson_import("
                + quote(run)
                + ","
                + quote(digest)
                + ","
                + str(len(body.encode()))
                + ") v"
            )
        )
        assert ready["state"] == "READY"
        return run, digest

    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    jobs, file_hash = imported(body)
    provenance = dict(
        contract="jobkorea-dataset-provenance-v1",
        row_key="composed_line",
        snapshot_sha256=file_hash,
        snapshot_byte_length=len(body.encode()),
        selected_count=3,
        occurrences_sha256="1" * 64,
        occurrences_byte_length=100,
        descriptor_sha256="2" * 64,
        descriptor_byte_length=200,
        archive_relative_root="jobkorea/datasets/" + "2" * 64,
    )
    register = "SELECT ingestion.register_jobkorea_dataset_provenance(" + quote(jobs) + ","
    for invalid in [provenance | {"selected_count": 2}, provenance | {"snapshot_sha256": "3" * 64}]:
        expect_failure(register + js(invalid) + ")", "JOBKOREA_DATASET_SNAPSHOT_BINDING_INVALID")
        expect_failure(
            "INSERT INTO ingestion.jobkorea_dataset_provenance VALUES("
            + quote(jobs)
            + ","
            + js(invalid)
            + ",clock_timestamp())",
            "JOBKOREA_DATASET_SNAPSHOT_BINDING_INVALID",
        )
    malformed = provenance | {"occurrences_sha256": "forged"}
    expect_failure(register + js(malformed) + ")", "INVALID_JOBKOREA_DATASET_PROVENANCE")
    expect_failure(
        "INSERT INTO ingestion.jobkorea_dataset_provenance VALUES("
        + quote(jobs)
        + ","
        + js(malformed)
        + ",clock_timestamp())",
        "INVALID_JOBKOREA_DATASET_PROVENANCE",
    )
    with tempfile.TemporaryDirectory(prefix="jobkorea-full-inputs-") as private:
        work = Path(private)

        def runner(statement: str) -> dict[str, object]:
            return json.loads(sql(statement))

        try:
            helper.Preparation(runner, jobs, work, 2, require_provenance=True).run()
        except RuntimeError as exc:
            assert "Register the archived dataset provenance" in str(exc)
        else:
            raise AssertionError("Required dataset provenance was ignored")
        archive = work / "archive"
        archive.mkdir(mode=0o700)
        (archive / "originals").mkdir(mode=0o700)
        (archive / "snapshot.ndjson").write_text(body)
        (archive / "originals/source.ndjson").write_text(body)
        mappings: list[dict[str, object]] = []
        offset = 0
        for number, raw in enumerate(body.encode().splitlines(keepends=True), 1):
            line_hash = hashlib.sha256(raw).hexdigest()
            mappings.append(
                dict(
                    composed_line=number,
                    composed_byte_offset=offset,
                    composed_byte_length=len(raw),
                    composed_line_sha256=line_hash,
                    source_record_id=str(50109421 + number),
                    selected_original=dict(
                        file="source.ndjson",
                        file_sha256=file_hash,
                        line=number,
                        byte_offset=offset,
                        byte_length=len(raw),
                        line_sha256=line_hash,
                    ),
                    alternative_occurrences=[],
                )
            )
            offset += len(raw)
        occurrence_bytes = ("".join(json.dumps(m) + "\n" for m in mappings)).encode()
        (archive / "occurrences.ndjson").write_bytes(occurrence_bytes)
        descriptor = dict(
            contract="jobkorea-composed-dataset-v1",
            row_key="composed_line",
            selected_count=3,
            snapshot=dict(sha256=file_hash, byte_length=len(body.encode())),
            occurrences=dict(
                sha256=hashlib.sha256(occurrence_bytes).hexdigest(),
                byte_length=len(occurrence_bytes),
            ),
            source_inventory=[
                dict(file="source.ndjson", sha256=file_hash, bytes=len(body.encode()))
            ],
        )
        descriptor_bytes = (json.dumps(descriptor) + "\n").encode()
        (archive / "composition.json").write_bytes(descriptor_bytes)
        descriptor_hash = hashlib.sha256(descriptor_bytes).hexdigest()
        provenance.update(
            occurrences_sha256=hashlib.sha256(occurrence_bytes).hexdigest(),
            occurrences_byte_length=len(occurrence_bytes),
            descriptor_sha256=descriptor_hash,
            descriptor_byte_length=len(descriptor_bytes),
            archive_relative_root="jobkorea/datasets/" + descriptor_hash,
        )
        (archive / "provenance.json").write_text(json.dumps(provenance))
        assert helper.verify_provenance(archive) == provenance
        database_calls = 0

        def forbidden_registration(statement: str) -> dict[str, object]:
            nonlocal database_calls
            database_calls += 1
            raise AssertionError("Invalid local metadata reached the database")

        for corrupted in [
            provenance | {"descriptor_sha256": "3" * 64},
            provenance | {"selected_count": 4},
        ]:
            (archive / "provenance.json").write_text(json.dumps(corrupted))
            try:
                helper.register_provenance(forbidden_registration, jobs, archive)
            except RuntimeError as exc:
                assert "mismatch" in str(exc) or "count/contract differs" in str(exc)
            else:
                raise AssertionError("Invalid local metadata was registered")
        assert database_calls == 0
        (archive / "provenance.json").write_text(json.dumps(provenance))
        assert helper.register_provenance(runner, jobs, archive) == provenance
        sql(register + js(provenance) + ")")
        initial = helper.Preparation(runner, jobs, work, 2, require_provenance=True).run(
            max_batches=1
        )
        assert initial["prepared"] == 2 and initial["batches"] == 1
        committed_receipt = (work / "batch-000001.json").read_bytes()

        def lost_acknowledgement(statement: str) -> dict[str, object]:
            result = runner(statement)
            if "/* full-input:prepare */" in statement:
                raise RuntimeError("Simulated halt after committed database batch")
            return result

        try:
            helper.Preparation(lost_acknowledgement, jobs, work, 2, require_provenance=True).run()
        except RuntimeError as exc:
            assert "Simulated halt" in str(exc)
        else:
            raise AssertionError("Expected interrupted committed batch")
        assert (
            sql("SELECT count(*) FROM enrichment.input_bundle WHERE job_run_id=" + quote(jobs))
            == "3"
        )
        completed = helper.Preparation(runner, jobs, work, 2, require_provenance=True).run()
        assert completed["status"] == "VERIFIED" and completed["prepared"] == 3
        assert completed["batches"] == 2 and completed["before"] == completed["after"]
        assert (work / "batch-000001.json").read_bytes() == committed_receipt
        prepared = sql(
            "SELECT jsonb_agg(to_jsonb(b) ORDER BY posting_id) FROM enrichment.input_bundle b"
            " WHERE job_run_id=" + quote(jobs)
        )
        replay = helper.Preparation(runner, jobs, work, 2, require_provenance=True).run()
        assert replay["batch_manifest_sha256"] == completed["batch_manifest_sha256"]
        assert (
            sql(
                "SELECT jsonb_agg(to_jsonb(b) ORDER BY posting_id) FROM enrichment.input_bundle b"
                " WHERE job_run_id=" + quote(jobs)
            )
            == prepared
        )
        for bundle in json.loads(prepared):
            assert bundle["manifest"]["dataset_provenance"] == provenance
            assert bundle["manifest"]["document"]["physical_line"] in (1, 2, 3)
            if bundle["manifest"]["document"]["source_record_id"] == "50109422":
                assert bundle["source_data"] == original
            sql("SELECT enrichment.verify_input_bundle(" + quote(bundle["bundle_id"]) + ")")
        install("hop/ingestions/jobkorea/sql/007_dataset_provenance.sql")
        install("hop/llm/sql/027_jobkorea_inputs.sql")
        assert (
            sql(
                "SELECT jsonb_agg(to_jsonb(b) ORDER BY posting_id) FROM enrichment.input_bundle b"
                " WHERE job_run_id=" + quote(jobs)
            )
            == prepared
        )
    expect_failure(
        register + js(provenance | {"selected_count": 4}) + ")",
        "IMMUTABLE_JOBKOREA_DATASET_PROVENANCE",
    )
    for statement in [
        "UPDATE ingestion.jobkorea_dataset_provenance SET provenance=provenance",
        "DELETE FROM ingestion.jobkorea_dataset_provenance",
        "TRUNCATE ingestion.jobkorea_dataset_provenance",
    ]:
        expect_failure(statement, "IMMUTABLE_JOBKOREA_DATASET_PROVENANCE")
    late_jobs, late_hash = imported(body.replace("\n", "\r\n"))
    late = provenance | {
        "snapshot_sha256": late_hash,
        "snapshot_byte_length": len(body.replace("\n", "\r\n").encode()),
    }
    posting = "ext-jobkorea-" + hashlib.sha256(b"50109422").hexdigest()
    sql(
        "SELECT enrichment.prepare_jobkorea_input_bundle("
        + quote(late_jobs)
        + ","
        + quote(posting)
        + ")"
    )
    expect_failure(
        "SELECT ingestion.register_jobkorea_dataset_provenance("
        + quote(late_jobs)
        + ","
        + js(late)
        + ")",
        "JOBKOREA_DATASET_PROVENANCE_MUST_PRECEDE_INPUTS",
    )
    expect_failure(
        "INSERT INTO ingestion.jobkorea_dataset_provenance VALUES("
        + quote(late_jobs)
        + ","
        + js(late)
        + ",clock_timestamp())",
        "JOBKOREA_DATASET_PROVENANCE_MUST_PRECEDE_INPUTS",
    )
    print("Full local inputs/provenance/direct-write/resume contracts passed", flush=True)


def main() -> None:
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                "none",
                "--name",
                NAME,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                os.environ.get("JOBTOLOGY_TEST_POSTGRES_IMAGE", "postgres:18-alpine"),
            ]
        )
        for _ in range(100):
            try:
                if (
                    "PostgreSQL init process complete" in command(["docker", "logs", NAME])
                    and sql("SELECT 1") == "1"
                ):
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        checks()
    finally:
        subprocess.run(["docker", "rm", "-f", NAME], text=True, capture_output=True, check=False)


if __name__ == "__main__":
    main()
