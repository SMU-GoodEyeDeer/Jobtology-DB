"""Network-none PostgreSQL NDJSON batch, checkpoint and evidence contracts."""
# Exact SQL fixtures make the source/evidence invariants easier to audit.
# ruff: noqa: E501

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
NAME = "jobtology-jobkorea-ndjson-sql-" + uuid.uuid4().hex[:10]


def command(args, value=None):
    result = subprocess.run(args, input=value, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:] + result.stdout[-2000:])
    return result.stdout.strip()


def sql(value):
    return command(["docker", "exec", "-i", NAME, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres"], value)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def row(identity, **extra):
    return dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(identity), job_title="데이터 분석 개발자", company_name="Fixture", job_position="데이터 분석가") | extra


def line(value, ending="\n"):
    return json.dumps(value, ensure_ascii=False) + ending


def begin(body):
    sha = digest(body)
    result = json.loads(sql(f"SELECT to_jsonb(x) FROM ingestion.begin_jobkorea_ndjson_import({quote(sha)},{len(body.encode())},'jobkorea/'||{quote(sha)}||'/source.ndjson',clock_timestamp()) x"))
    return result["run_id"], sha


def append(run, body, byte=0, physical=1):
    return json.loads(sql(f"SELECT to_jsonb(x) FROM ingestion.append_jobkorea_ndjson_batch({quote(run)},{byte},{physical},{quote(body)},{quote(digest(body))}) x"))


def reject(statement, expected):
    try:
        sql(statement)
    except RuntimeError as exc:
        assert expected in str(exc), str(exc)
        return str(exc)
    raise AssertionError("Expected " + expected)


def reject_batch(run, body, expected, byte=0, physical=1):
    return reject(f"SELECT * FROM ingestion.append_jobkorea_ndjson_batch({quote(run)},{byte},{physical},{quote(body)},{quote(digest(body))})", expected)


def seal(run, sha, body):
    return json.loads(sql(f"SELECT to_jsonb(x) FROM ingestion.seal_jobkorea_ndjson_import({quote(run)},{quote(sha)},{len(body.encode())}) x"))


def receipt(run):
    return json.loads(sql(f"SELECT to_jsonb(i) FROM ingestion.jobkorea_import i WHERE run_id={quote(run)}"))


def checks():
    rows = [row(700001 + n) for n in range(4)]
    chunks = [line(rows[0], "\r\n"), line(rows[1]) + line(rows[2], "\r\n"), line(rows[3])]
    body = "".join(chunks)
    run, sha = begin(body)
    assert receipt(run)["next_byte_offset"] == 0
    first = append(run, chunks[0])
    assert first == dict(next_byte_offset=len(chunks[0].encode()), next_line_number=2, accepted_count=1, rejected_count=0, replayed=False, state="LOADING"), first
    reject(f"SELECT * FROM ingestion.seal_jobkorea_ndjson_import({quote(run)},{quote(sha)},{len(body.encode())})", "JOBKOREA_NDJSON_CHECKPOINT_INCOMPLETE")
    reject(f"UPDATE ingestion.run SET state='READY' WHERE run_id={quote(run)}", "JOBKOREA_READY_VALIDATION_FAILED")
    reject(f"UPDATE ingestion.record SET source_payload=source_payload||'{{\"tamper\":true}}'::jsonb WHERE run_id={quote(run)}", "JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE")
    reject(f"UPDATE ingestion.record SET run_id='another-run' WHERE run_id={quote(run)}", "JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE")
    reject(f"UPDATE ingestion.jobkorea_ndjson_line SET run_id='another-run' WHERE run_id={quote(run)}", "JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE")
    reject(f"UPDATE ingestion.jobkorea_ndjson_chunk SET raw_text=raw_text WHERE run_id={quote(run)}", "JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE")
    reject("TRUNCATE ingestion.jobkorea_ndjson_line", "JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE")
    reject(f"UPDATE ingestion.jobkorea_import SET scraped_at=clock_timestamp() WHERE run_id={quote(run)}", "JOBKOREA_NDJSON_RECEIPT_IMMUTABLE")
    reject_batch(run, chunks[1], "JOBKOREA_NDJSON_CHECKPOINT_CONFLICT", first["next_byte_offset"] + 1, 2)
    second = append(run, chunks[1], first["next_byte_offset"], 2)
    assert second["next_line_number"] == 4 and second["accepted_count"] == 2
    resumed, _ = begin(body)
    assert resumed == run and receipt(run)["next_byte_offset"] == second["next_byte_offset"]
    replay = append(run, chunks[0])
    assert replay == first | dict(replayed=True)
    reject_batch(run, chunks[0].replace("Fixture", "Changed"), "JOBKOREA_NDJSON_BATCH_REPLAY_CONFLICT")
    assert receipt(run)["batch_count"] == 2
    append(run, chunks[2], second["next_byte_offset"], 4)
    result = seal(run, sha, body)
    assert result == dict(state="READY", record_count=4, issue_count=0), result
    assert result == seal(run, sha, body)
    assert append(run, chunks[0])["state"] == "READY"
    lines = json.loads(sql(f"SELECT jsonb_agg(to_jsonb(l) ORDER BY line_number) FROM ingestion.jobkorea_ndjson_line l WHERE run_id={quote(run)}"))
    expected_byte = 0
    for physical, raw in enumerate(body.splitlines(keepends=True), 1):
        provenance = lines[physical - 1]
        assert (provenance["line_number"], provenance["byte_offset"], provenance["byte_length"], provenance["raw_sha256"]) == (physical, expected_byte, len(raw.encode()), digest(raw))
        expected_byte += len(raw.encode())
    assert receipt(run)["row_manifest_sha256"] == sql(f"SELECT ingestion.jobkorea_row_manifest({quote(run)})")
    assert sql(f"SELECT count(*) FROM ingestion.jobkorea_validation_issue WHERE run_id={quote(run)}") == "0"

    # Equivalent array and physical-line observations share model content, while
    # audit manifests preserve their distinct file serialization and locators.
    array = json.dumps(rows, ensure_ascii=False)
    array_sha = digest(array)
    array_run = sql(f"SELECT run_id FROM ingestion.begin_jobkorea_import({quote(array_sha)},{len(array.encode())},'jobkorea/'||{quote(array_sha)}||'/source.json',clock_timestamp())")
    sql(f"SELECT * FROM ingestion.load_jobkorea_document({quote(array_run)},{quote(array)}); SELECT ingestion.verify_jobkorea_file({quote(array_run)},{quote(array_sha)},{len(array.encode())}); SELECT * FROM ingestion.finalize_jobkorea_import({quote(array_run)})")
    array_manifest = receipt(array_run)["row_manifest_sha256"]
    posting = "ext-jobkorea-" + digest("700001")
    prepared = [json.loads(sql(f"SELECT enrichment.build_jobkorea_input({quote(r)},{quote(posting)})")) for r in [array_run, run]]
    assert prepared[0]["source_data"] == prepared[1]["source_data"]
    assert prepared[0]["manifest"] != prepared[1]["manifest"]
    assert prepared[1]["manifest"]["document"]["locator_kind"] == "NDJSON_PHYSICAL_LINE"
    # With sequential scans disabled, both the exact builder lookup and the
    # public qualified-ID view must expose an indexed identity condition.
    for lookup in [
        f"SELECT * FROM ingestion.ready_record WHERE run_id={quote(run)} AND source_id='jobkorea' AND document_id='local-json' AND 'ext-jobkorea-'||enrichment.hash(source_record_id)={quote(posting)}",
        f"SELECT * FROM ingestion.llm_posting WHERE run_id={quote(run)} AND source_id='jobkorea' AND posting_id={quote(posting)}",
    ]:
        plan = sql("SET enable_seqscan=off; EXPLAIN (FORMAT JSON) " + lookup)
        assert '"Index Name": "jobkorea_llm_posting_lookup"' in plan and '"Index Cond"' in plan, plan
    for path in sorted((ROOT / "hop/ingestions/jobkorea/sql").glob("*.sql")):
        sql(path.read_text())
    assert array_manifest == receipt(array_run)["row_manifest_sha256"] == sql(f"SELECT ingestion.jobkorea_row_manifest({quote(array_run)})")
    assert sql(f"SELECT count(*) FROM ingestion.jobkorea_validation_issue WHERE run_id IN({quote(array_run)},{quote(run)})") == "0"
    assert prepared[1] == json.loads(sql(f"SELECT enrichment.build_jobkorea_input({quote(run)},{quote(posting)})"))

    # A late bad line rolls back its whole batch without losing earlier commits.
    valid = line(row(710001))
    invalid = line(row(710002)) + '{"job_title":"bad","job_title":"duplicate"}\n'
    late_body = valid + invalid
    late, _ = begin(late_body)
    checkpoint = append(late, valid)
    error = reject_batch(late, invalid, "LOCAL_NDJSON_DUPLICATE_KEYS", len(valid.encode()), 2)
    assert f"line:3@byte:{len((valid + line(row(710002))).encode())}" in error
    assert receipt(late)["next_byte_offset"] == checkpoint["next_byte_offset"] and receipt(late)["batch_count"] == 1
    assert sql(f"SELECT count(*) FROM ingestion.record WHERE run_id={quote(late)}") == "1"
    sql(f"SELECT ingestion.mark_failed_jobkorea_ndjson_import({quote(late)},3,{len((valid + line(row(710002))).encode())},'LOCAL_NDJSON_DUPLICATE_KEYS')")
    assert sql(f"SELECT state FROM ingestion.run WHERE run_id={quote(late)}") == "FAILED"
    reject(f"UPDATE ingestion.run SET state='READY' WHERE run_id={quote(late)}", "JOBKOREA_READY_VALIDATION_FAILED")

    duplicate_body = line(row(720001)) * 2
    duplicate, _ = begin(duplicate_body)
    append(duplicate, line(row(720001)))
    reject_batch(duplicate, line(row(720001)), "LOCAL_NDJSON_DUPLICATE_IDENTITY", len(line(row(720001)).encode()), 2)
    assert receipt(duplicate)["batch_count"] == 1
    assert sql(f"SELECT count(*) FROM ingestion.record WHERE run_id={quote(duplicate)}") == "1"
    for malformed, code in [
        (line(row(730001))[:-1], "NDJSON_FINAL_NEWLINE_REQUIRED"),
        ('{"broken":\n', "LOCAL_NDJSON_JSON_INVALID"),
        ('[{}]\n', "LOCAL_NDJSON_JSON_INVALID"),
        (' \t\r\n', "LOCAL_NDJSON_BLANK_LINE"),
        ('\ufeff' + line(row(730002)), "LOCAL_NDJSON_BOM_FORBIDDEN"),
        ('{"job_title":"title"}\n', "LOCAL_NDJSON_IDENTITY_INVALID"),
        (line(row(730003)).replace('"job_position":', '"nested":{"a":1,"a":2},"job_position":'), "LOCAL_NDJSON_DUPLICATE_KEYS"),
    ]:
        rejected, _ = begin(malformed)
        reject_batch(rejected, malformed, code)
        assert receipt(rejected)["next_byte_offset"] == 0 and receipt(rejected)["batch_count"] == 0

    semantic_body = line(row(740001)) + line(row(740002, application_end_date="2026-02-31"))
    semantic, semantic_sha = begin(semantic_body)
    assert append(semantic, semantic_body)["rejected_count"] == 1
    assert sql(f"SELECT locator FROM ingestion.jobkorea_issue WHERE run_id={quote(semantic)} AND code='INVALID_DATE'") == "line:2"
    semantic_result = seal(semantic, semantic_sha, semantic_body)
    assert semantic_result["state"] == "REVIEW_REQUIRED" and semantic_result["record_count"] == 1
    assert sql(f"SELECT count(*) FROM ingestion.ready_record WHERE run_id={quote(semantic)}") == "0"
    assert sql("SELECT count(*) FROM ingestion.request_attempt WHERE source_id='jobkorea'") == "0"
    assert sql("SELECT count(*) FROM retention.writer") == "0"
    print("NDJSON bounded batches, exact byte/line checkpoints, replay/resume, multibyte CRLF provenance, late invalid rollback, identity/key failures, rejected-row gates, immutable chunks, content-hash compatibility and installer replay passed", flush=True)


def main():
    try:
        command(["docker", "run", "-d", "--pull", "never", "--network", "none", "--name", NAME, "-e", "POSTGRES_HOST_AUTH_METHOD=trust", os.environ.get("JOBTOLOGY_TEST_POSTGRES_IMAGE", "postgres:18-alpine")])
        for _ in range(100):
            try:
                if "PostgreSQL init process complete" in command(["docker", "logs", NAME]) and sql("SELECT 1") == "1":
                    break
            except RuntimeError:
                pass
            time.sleep(.1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        for relative in ["docs/hop-migration/schema.sql", "docs/hop-migration/checks.sql", "docs/hop-migration/operations.sql"]:
            sql((ROOT / relative).read_text())
        for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
            sql(path.read_text())
        sql((ROOT / "hop/retention/sql/001_retention.sql").read_text())
        for path in sorted((ROOT / "hop/ingestions/jobkorea/sql").glob("*.sql")):
            sql(path.read_text())
        sql((ROOT / "hop/llm/sql/027_jobkorea_inputs.sql").read_text())
        checks()
    finally:
        subprocess.run(["docker", "rm", "-fv", NAME], capture_output=True, check=False)


if __name__ == "__main__":
    main()
