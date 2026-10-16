# ruff: noqa: E501
"""Offline native NDJSON import, interruption/resume and bounded-memory checks.

The supplied local sample and generated synthetic bytes are processed by the
real Hop Java reader and PostgreSQL loader. All containers use one INTERNAL
network, local images and fixture connections. No source URL or model is called.
"""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from linking_native import LinkingFixture, q
from native import REMOTE, ROOT

SAMPLE_SHA = "f42cff119b4db77ff2c1bdb5d57eefd2398bae677f6fbf8d14cc390b67ae20e3"
LEGACY_SHA = "934b51137ad3e4d38fb369719ae1ff654af932ea4b9f4c4d5e83ed21626bde95"


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def synthetic_row(number, **extra):
    return {
        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(number),
        "job_title": "SYNTHETIC database developer",
        **extra,
    }


def line(row, ending=b"\n"):
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + ending


class NDJSONFixture(LinkingFixture):
    def stage(self):
        super().stage()
        (self.work / "inputs/sample.json").rename(self.work / "inputs/sample.ndjson")

    def run(self, filename, label, success=True, input_name="sample.ndjson", extra=None,
            isolated=True, interrupt_after=None, heap="1024m"):
        # Blank MAX_FILE_BYTES deliberately exercises the format-specific native
        # default; the old array Fixture's fixed 16 MiB limit remains unchanged.
        params = {
            "INPUT_FILE": REMOTE + "/inputs/" + input_name,
            "RAW_ROOT": REMOTE + "/raw",
            "MODE": "DRY_RUN",
            "INPUT_FORMAT": "NDJSON",
            "MAX_FILE_BYTES": "",
        }
        params.update(extra or {})
        command = ["docker", "exec", "-e", "HOP_CONFIG_FOLDER=" + REMOTE + "/config",
                   "-e", "HOP_OPTIONS=-Xmx" + heap,
                   "-e", "JOBKOREA_ISOLATED_CONTEXT=" + str(isolated).lower(),
                   "-e", "JOBKOREA_ISOLATED_TOKEN=" + self.token]
        if interrupt_after is not None:
            command += ["-e", "JOBKOREA_NDJSON_INTERRUPT_AFTER_BATCHES=" + str(interrupt_after)]
        command += ["-w", "/opt/hop", self.hop, "bash", "hop-run.sh", "-j", "jobkorea-test",
                    "-r", "jobkorea-local", "-f",
                    REMOTE + "/project/ingestions/jobkorea/" + filename,
                    "-p", ",".join(k + "=" + str(v) for k, v in params.items()), "-l", "Basic"]
        result = self.command(command, label, success=success, timeout=1800)
        self.expect(True, label)
        return result

    def run_for(self, path):
        return self.sql("SELECT run_id FROM ingestion.jobkorea_import WHERE file_sha256="
                        + q(sha_file(path)), "run-for-" + path.stem)

    def record_digest(self, jobs):
        # Small sample only. The larger streaming test never aggregates source
        # payloads in Python or PostgreSQL to calculate its receipt.
        return self.sql("SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY locator)::text,'')) "
                        "FROM ingestion.record r WHERE run_id=" + q(jobs), "record-digest")

    def no_publication(self, path, label):
        digest = q(sha_file(path))
        self.expect(self.sql("SELECT count(*) FROM ingestion.run r JOIN ingestion.jobkorea_import i USING(run_id) "
                             "WHERE i.file_sha256=" + digest + " AND r.state='READY'", label + "-ready") == "0",
                    label + "-no-ready")
        self.expect(self.sql("SELECT count(*) FROM ingestion.graph_export g JOIN ingestion.jobkorea_import i USING(run_id) "
                             "WHERE i.file_sha256=" + digest, label + "-graph") == "0",
                    label + "-no-graph-checkpoint")
        self.expect(self.sql("SELECT count(*) FROM ingestion.ready_record r JOIN ingestion.jobkorea_import i USING(run_id) "
                             "WHERE i.file_sha256=" + digest, label + "-visible") == "0",
                    label + "-staged-prefix-invisible")


def check_sample(fixture):
    sample = fixture.work / "inputs/sample.ndjson"
    expected_rows = sum(1 for _ in sample.open("rb"))
    fixture.run("full.hwf", "native-ndjson-sample-full", extra={"INPUT_FORMAT": "AUTO", "BATCH_ROWS": "53"})
    jobs = fixture.run_for(sample)
    fixture.expect(bool(jobs) and "\n" not in jobs, "ndjson-exact-run")
    report = json.loads(fixture.sql("SELECT to_jsonb(i) FROM ingestion.jobkorea_import i WHERE run_id="
                                  + q(jobs), "ndjson-source-receipt"))
    fixture.receipt["ndjson_run_id"] = jobs
    fixture.receipt["ndjson_import"] = report
    fixture.expect(report["file_format"] == "NDJSON" and report["loaded"]
                   and report["parser_version"] == "hop-jobkorea-ndjson-v1", "ndjson-format-and-parser")
    fixture.expect(report["next_byte_offset"] == sample.stat().st_size
                   and report["next_line_number"] == expected_rows + 1
                   and report["batch_count"] == (expected_rows + 52) // 53, "ndjson-complete-checkpoints")
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.ready_record WHERE run_id=" + q(jobs),
                               "ndjson-ready-count") == str(expected_rows), "ndjson-all-rows-ready")
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.jobkorea_validation_issue WHERE run_id="
                               + q(jobs), "ndjson-valid") == "0", "ndjson-source-validation")
    provenance = json.loads(fixture.sql("SELECT jsonb_build_object('lines',count(*),'bytes',sum(byte_length),"
                                       "'first_line',min(line_number),'last_line',max(line_number),"
                                       "'first_byte',min(byte_offset),'last_byte',max(byte_offset+byte_length)) "
                                       "FROM ingestion.jobkorea_ndjson_line WHERE run_id=" + q(jobs), "ndjson-provenance"))
    fixture.expect(provenance == {"lines": expected_rows, "bytes": sample.stat().st_size,
                                 "first_line": 1, "last_line": expected_rows,
                                 "first_byte": 0, "last_byte": sample.stat().st_size}, "ndjson-exact-line-byte-provenance")
    # Independently calculate the exact physical line byte hashes/offsets from
    # the archived local sample, then compare all rows without source output.
    rows = json.loads(fixture.sql("SELECT jsonb_agg(jsonb_build_array(line_number,byte_offset,byte_length,raw_sha256) "
                                 "ORDER BY line_number) FROM ingestion.jobkorea_ndjson_line WHERE run_id=" + q(jobs),
                                 "ndjson-line-hashes"))
    offset = 0
    expected = []
    with sample.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            expected.append([number, offset, len(raw), hashlib.sha256(raw).hexdigest()])
            offset += len(raw)
    fixture.expect(rows == expected, "ndjson-all-physical-line-hashes")
    outcomes = json.loads(fixture.sql("SELECT jsonb_build_object('total',count(*),'missing_starts',"
                                     "count(*) FILTER(WHERE NOT source_payload ? 'application_start_date'),"
                                     "'policy_rolling',count(*) FILTER(WHERE normalized->>'deadline_basis'='USER_POLICY' "
                                     "AND normalized->>'deadline_kind'='ROLLING'),'missing_descriptions',"
                                     "count(*) FILTER(WHERE normalized->>'content_status'='MISSING')) "
                                     "FROM ingestion.ready_record WHERE run_id=" + q(jobs), "ndjson-outcomes"))
    fixture.receipt["ndjson_source_outcomes"] = outcomes
    if sha_file(sample) == SAMPLE_SHA:
        fixture.expect(outcomes == {"total": 416, "missing_starts": 170,
                                    "policy_rolling": 26, "missing_descriptions": 416}, "actual-416-sample-outcomes")
    fixture.expect(report["scraped_at"] is None, "ndjson-scrape-time-unknown")
    graph = fixture.command(["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain",
                             "MATCH (b:ingestionBatch {id:" + q(jobs) + "})-[:HAS_RECORD]->(r) "
                             "WITH b,count(r) AS records MATCH (b)-[:HAS_RECORD]->()-[ref:REFERS_TO]->(e) "
                             "WITH b,records,count(ref) AS references,count(DISTINCT e) AS identities "
                             "RETURN toString(records)+'|'+toString(references)+'|'+b.state+'|'+b.serving_scope "
                             "+'|'+toString(identities) AS scope"], "ndjson-independent-neo")
    scope = f"{expected_rows}|{expected_rows}|READY|STAGING|{expected_rows}"
    fixture.expect(any(x.strip('"') == scope for x in graph.splitlines()), "ndjson-source-neo-counts")
    before = fixture.record_digest(jobs)
    fixture.run("full.hwf", "native-ndjson-full-replay", extra={"INPUT_FORMAT": "AUTO", "BATCH_ROWS": "53"})
    fixture.expect(before == fixture.record_digest(jobs), "ndjson-replay-preserves-record-identities")
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.graph_export WHERE run_id=" + q(jobs),
                               "ndjson-graph-checkpoint") == "1", "ndjson-one-graph-checkpoint")
    fixture.expect(report == json.loads(fixture.sql("SELECT to_jsonb(i) FROM ingestion.jobkorea_import i WHERE run_id="
                                                  + q(jobs), "ndjson-replayed-receipt")), "ndjson-replay-preserves-import-checkpoints")

    ncs = fixture.seed_ncs()
    fixture.run("install_linking.hwf", "native-ndjson-linking-install")
    params = {"JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs, "API_KEY_FILE": "/does-not-exist"}
    fixture.run("preview_linking.hwf", "native-ndjson-linking-preview", extra=params)
    fixture.run("prepare_linking.hwf", "native-ndjson-linking-prepare", extra=params)
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.input_bundle WHERE job_run_id=" + q(jobs),
                               "ndjson-bundles") == "5", "ndjson-five-frozen-input-bundles")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.input_bundle WHERE job_run_id=" + q(jobs)
                               + " AND manifest#>>'{document,locator_kind}'='NDJSON_PHYSICAL_LINE' "
                               "AND (manifest#>>'{document,physical_line}')::bigint>0", "ndjson-bundle-provenance") == "5",
                    "ndjson-bundle-physical-line-manifest")
    fixture.sql("SELECT enrichment.verify_input_bundle(bundle_id) FROM enrichment.input_bundle WHERE job_run_id="
                + q(jobs), "ndjson-verify-input-bundles")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL",
                               "ndjson-model-reservations") == "0", "ndjson-linking-zero-model-requests")
    return jobs


def check_resume(fixture):
    path = fixture.work / "inputs/interrupted.ndjson"
    with path.open("wb") as stream:
        for number in range(91000001, 91000014):
            stream.write(line(synthetic_row(number)))
    fixture.run("import_local.hpl", "native-ndjson-jvm-interruption", success=False,
                input_name=path.name, extra={"BATCH_ROWS": "3"}, interrupt_after=2)
    jobs = fixture.run_for(path)
    checkpoint = json.loads(fixture.sql("SELECT jsonb_build_object('state',u.state,'loaded',i.loaded,"
                                        "'batches',i.batch_count,'line',i.next_line_number,'byte',i.next_byte_offset,"
                                        "'records',(SELECT count(*) FROM ingestion.record WHERE run_id=i.run_id)) "
                                        "FROM ingestion.jobkorea_import i JOIN ingestion.run u USING(run_id) WHERE i.run_id="
                                        + q(jobs), "interruption-checkpoint"))
    fixture.expect(checkpoint["state"] == "LOADING" and not checkpoint["loaded"]
                   and checkpoint["batches"] == 2 and checkpoint["line"] == 7
                   and checkpoint["records"] == 6 and checkpoint["byte"] > 0,
                   "jvm-halt-keeps-two-committed-batches")
    fixture.receipt["interruption_checkpoint"] = checkpoint
    # Recovery must use the exact immutable archive. The original supplied input
    # is removed, and INPUT_FILE intentionally refers to a missing path.
    path.unlink()
    fixture.run("import_local.hpl", "native-ndjson-archive-only-resume", input_name="absent.ndjson",
                extra={"RESUME_RUN_ID": jobs, "INPUT_FORMAT": "AUTO", "BATCH_ROWS": "3"})
    fixture.expect(fixture.sql("SELECT state FROM ingestion.run WHERE run_id=" + q(jobs), "resumed-state") == "READY",
                    "archive-only-resume-ready")
    fixture.expect(fixture.sql("SELECT count(*)||'|'||count(DISTINCT source_record_id)||'|'||count(DISTINCT locator) "
                               "FROM ingestion.ready_record WHERE run_id=" + q(jobs), "resumed-counts") == "13|13|13",
                    "resume-no-row-or-identity-duplicates")
    fixture.expect(fixture.sql("SELECT next_line_number||'|'||batch_count FROM ingestion.jobkorea_import WHERE run_id="
                               + q(jobs), "resumed-checkpoint") == "14|5", "resume-completes-only-remaining-batches")
    before = fixture.record_digest(jobs)
    fixture.run("import_local.hpl", "native-ndjson-ready-archive-replay", input_name="absent.ndjson",
                extra={"RESUME_RUN_ID": jobs, "BATCH_ROWS": "3"})
    fixture.expect(before == fixture.record_digest(jobs), "archive-replay-preserves-resumed-identities")


def check_framing_and_failures(fixture):
    prefix = line(synthetic_row(92000001))
    valid = line(synthetic_row(92000002))
    duplicate_key = (b'{"product_page_url":"https://www.jobkorea.co.kr/Recruit/GI_Read/92000003",'
                     b'"job_title":"X","job_title":"Y"}\n')
    staged_prefix = prefix + valid
    cases = {
        "malformed": staged_prefix + b'{"job_title":}\n',
        "truncated-json": staged_prefix + b'{"job_title":"cut\n',
        "invalid-utf8": staged_prefix + valid.replace(b"SYNTHETIC", b"\xff"),
        "duplicate-key": staged_prefix + duplicate_key,
        "duplicate-id": prefix + prefix,
        "blank-line": staged_prefix + b"\n",
        "non-object": staged_prefix + b"[]\n",
        "trailing-garbage": staged_prefix + valid.rstrip(b"\n") + b" true\n",
        "bom": b"\xef\xbb\xbf" + prefix,
        "final-no-lf": staged_prefix + valid.rstrip(b"\n"),
        "oversized-line": staged_prefix + line(synthetic_row(92000004, padding="x" * 1024)),
    }
    for label, raw in cases.items():
        path = fixture.work / "inputs" / (label + ".ndjson")
        path.write_bytes(raw)
        params = {"BATCH_ROWS": "1"}
        if label == "oversized-line":
            params.update(MAX_LINE_BYTES="512", BATCH_BYTES="1024")
        fixture.run("import_local.hpl", "reject-ndjson-" + label, success=False,
                    input_name=path.name, extra=params)
        fixture.no_publication(path, label)
        jobs = fixture.run_for(path)
        offender_line = 1 if label == "bom" else 2 if label == "duplicate-id" else 3
        offender_byte = 0 if label == "bom" else len(prefix) if label == "duplicate-id" else len(staged_prefix)
        locator = f"line:{offender_line}@byte:{offender_byte}"
        fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.jobkorea_issue WHERE run_id=" + q(jobs)
                                   + " AND severity='ERROR' AND locator=" + q(locator), label + "-location") == "1",
                        label + "-redacted-offending-line-and-byte")
        if label in {"malformed", "duplicate-key", "duplicate-id", "blank-line", "non-object", "trailing-garbage"}:
            fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.record WHERE run_id=" + q(jobs),
                                       label + "-prefix-count") == ("1" if label == "duplicate-id" else "2"),
                            label + "-retains-only-committed-prefix")
    invalid_fields = fixture.work / "inputs/invalid-fields.ndjson"
    invalid_fields.write_bytes(staged_prefix + line(synthetic_row(92000005,
                                application_start_date=42, application_end_date="not-a-date")))
    fixture.run("full.hwf", "reject-ndjson-malformed-source-fields", success=False,
                input_name=invalid_fields.name, extra={"BATCH_ROWS": "1"})
    fixture.no_publication(invalid_fields, "malformed-source-fields")
    invalid_jobs = fixture.run_for(invalid_fields)
    fixture.expect(fixture.sql("SELECT state FROM ingestion.run WHERE run_id=" + q(invalid_jobs),
                               "malformed-fields-state") == "REVIEW_REQUIRED", "malformed-source-fields-review-required")
    diagnostics = json.loads(fixture.sql("SELECT jsonb_agg(jsonb_build_array(locator,field,code) ORDER BY field) "
                                        "FROM ingestion.jobkorea_issue WHERE run_id=" + q(invalid_jobs)
                                        + " AND severity='ERROR'", "malformed-fields-diagnostics"))
    fixture.expect(diagnostics == [["line:3", "application_end_date", "INVALID_DATE"],
                                  ["line:3", "application_start_date", "INVALID_DATE_TYPE"]],
                   "malformed-source-fields-exact-line-diagnostics")
    crlf = fixture.work / "inputs/crlf.JSONL"
    raw = line(synthetic_row(93000001, job_title="SYNTHETIC 한국어 데이터 개발자"), b"\r\n")
    raw += line(synthetic_row(93000002), b"\r\n")
    crlf.write_bytes(raw)
    fixture.run("import_local.hpl", "native-ndjson-crlf", input_name=crlf.name,
                extra={"INPUT_FORMAT": "AUTO", "BATCH_ROWS": "1"})
    jobs = fixture.run_for(crlf)
    fixture.expect(fixture.sql("SELECT count(*)||'|'||sum(byte_length)||'|'||max(byte_offset+byte_length) "
                               "FROM ingestion.jobkorea_ndjson_line WHERE run_id=" + q(jobs), "crlf-bytes")
                   == "2|" + str(len(raw)) + "|" + str(len(raw)), "crlf-exact-utf8-byte-accounting")
    fixture.expect(fixture.sql("SELECT state FROM ingestion.run WHERE run_id=" + q(jobs), "crlf-state") == "READY",
                    "crlf-complete-objects-accepted")


def check_cross_format_and_legacy(fixture, ndjson_jobs, legacy):
    with fixture.input.open("rb") as stream:
        first = json.loads(next(stream))
    path = fixture.work / "inputs/one-observation.json"
    path.write_text(json.dumps([first], ensure_ascii=False), encoding="utf-8")
    fixture.run("import_local.hpl", "native-one-json-observation", input_name=path.name,
                extra={"INPUT_FORMAT": "JSON_ARRAY"})
    array_jobs = fixture.run_for(path)
    same = json.loads(fixture.sql("WITH a AS (SELECT r.source_record_id,"
                                 "enrichment.build_jobkorea_input(r.run_id,cs.external_posting_key('jobkorea',r.source_record_id)) AS v "
                                 "FROM ingestion.ready_record r WHERE r.run_id=" + q(array_jobs) + "), "
                                 "n AS (SELECT r.source_record_id,"
                                 "enrichment.build_jobkorea_input(r.run_id,cs.external_posting_key('jobkorea',r.source_record_id)) AS v "
                                 "FROM ingestion.ready_record r WHERE r.run_id=" + q(ndjson_jobs) + " AND r.source_record_id=(SELECT source_record_id FROM a)) "
                                 "SELECT jsonb_build_object('same_id',a.source_record_id=n.source_record_id,"
                                 "'same_content',a.v->'source_data'=n.v->'source_data',"
                                 "'different_manifest',a.v->'manifest'<>n.v->'manifest',"
                                 "'array_locator',a.v#>>'{manifest,document,source_locator}',"
                                 "'ndjson_locator',n.v#>>'{manifest,document,source_locator}') FROM a CROSS JOIN n",
                                 "cross-format-binding"))
    fixture.expect(same["same_id"] and same["same_content"] and same["different_manifest"]
                   and same["array_locator"] == "/0" and same["ndjson_locator"] == "line:1",
                   "same-observation-cross-format-stable-identity-and-model-hash")
    fixture.receipt["cross_format"] = same
    shutil.copyfile(legacy, fixture.work / "inputs/legacy887.json")
    fixture.run("import_local.hpl", "native-legacy-json-array", input_name="legacy887.json",
                extra={"INPUT_FORMAT": "AUTO", "MAX_FILE_BYTES": "16777216"})
    jobs = fixture.run_for(fixture.work / "inputs/legacy887.json")
    expected = "jobkorea-" + hashlib.sha256(("hop-jobkorea-v1:2026-10-07.1:" + sha_file(legacy)).encode()).hexdigest()
    fixture.expect(jobs == expected, "legacy-json-array-run-identity-preserved")
    expected_rows = len(json.loads(legacy.read_text(encoding="utf-8")))
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.ready_record WHERE run_id=" + q(jobs),
                               "legacy-row-count") == str(expected_rows), "legacy-json-array-all-rows-ready")
    before = fixture.record_digest(jobs)
    content_before = fixture.sql("SELECT md5(string_agg(enrichment.linking_input_hash(run_id,"
                                 "cs.external_posting_key('jobkorea',source_record_id)),'' ORDER BY locator)) "
                                 "FROM ingestion.ready_record WHERE run_id=" + q(jobs), "legacy-content-before")
    fixture.run("import_local.hpl", "native-legacy-json-replay", input_name="legacy887.json",
                extra={"INPUT_FORMAT": "JSON_ARRAY", "MAX_FILE_BYTES": "16777216"})
    fixture.expect(before == fixture.record_digest(jobs), "legacy-json-replay-preserves-record-identities")
    content_after = fixture.sql("SELECT md5(string_agg(enrichment.linking_input_hash(run_id,"
                                "cs.external_posting_key('jobkorea',source_record_id)),'' ORDER BY locator)) "
                                "FROM ingestion.ready_record WHERE run_id=" + q(jobs), "legacy-content-after")
    fixture.expect(content_before == content_after, "legacy-json-replay-preserves-model-content-hashes")
    fixture.receipt["legacy_json_array"] = {"sha256": sha_file(legacy), "rows": expected_rows,
                                             "run_id": jobs, "record_digest": before,
                                             "content_hash_digest": content_before}
    if sha_file(legacy) == LEGACY_SHA:
        fixture.expect(expected_rows == 887, "original-887-json-array-regression")


def check_large_stream(fixture):
    path = fixture.work / "inputs/synthetic-over64m.ndjson"
    count, padding_bytes = 512, 196608
    with path.open("wb") as stream:
        for number in range(count):
            stream.write(line(synthetic_row(94000000 + number, padding="x" * padding_bytes)))
    size = path.stat().st_size
    fixture.expect(size > 67108864, "synthetic-stream-exceeds-old-64m-limit")
    fixture.run("import_local.hpl", "native-large-ndjson-256m-heap", input_name=path.name, heap="256m")
    jobs = fixture.run_for(path)
    report = json.loads(fixture.sql("SELECT jsonb_build_object('state',u.state,'bytes',i.byte_length,"
                                   "'next_byte',i.next_byte_offset,'next_line',i.next_line_number,'batches',i.batch_count,"
                                   "'records',(SELECT count(*) FROM ingestion.record WHERE run_id=i.run_id),"
                                   "'max_line',(SELECT max(byte_length) FROM ingestion.jobkorea_ndjson_line WHERE run_id=i.run_id),"
                                   "'max_batch_bytes',(SELECT max(bytes) FROM (SELECT sum(byte_length) AS bytes FROM "
                                   "ingestion.jobkorea_ndjson_line WHERE run_id=i.run_id GROUP BY chunk_no) chunks),"
                                   "'max_batch_rows',(SELECT max(rows) FROM (SELECT count(*) AS rows FROM "
                                   "ingestion.jobkorea_ndjson_line WHERE run_id=i.run_id GROUP BY chunk_no) chunks)) "
                                   "FROM ingestion.jobkorea_import i JOIN ingestion.run u USING(run_id) WHERE i.run_id="
                                   + q(jobs), "large-stream-receipt"))
    fixture.expect(report["state"] == "READY" and report["bytes"] == report["next_byte"] == size
                   and report["records"] == count and report["next_line"] == count + 1
                   and report["batches"] > 1 and report["max_line"] <= 1048576
                   and report["max_batch_bytes"] <= 4194304 and report["max_batch_rows"] <= 500,
                   "bounded-reader-completes-large-stream-with-small-heap")
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.graph_export WHERE run_id=" + q(jobs),
                               "stress-no-graph") == "0", "large-stream-import-only-no-mass-graph")
    fixture.receipt["large_stream"] = {**report, "sha256": sha_file(path), "hop_max_heap": "256m",
                                        "synthetic": True, "graph_loaded": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT.parent / "jobtology/j_muwimlga1lq0obm7dp.ndjson")
    parser.add_argument("--legacy-input", type=Path, default=ROOT.parent / "jobtology/j_muwj57zxdc6o3utkq.json")
    parser.add_argument("--skip-large", action="store_true", help="Development only; no bounded-memory receipt claim.")
    args = parser.parse_args()
    os.umask(0o077)
    fixture = NDJSONFixture(args.input)
    try:
        fixture.boot()
        fixture.install()
        jobs = check_sample(fixture)
        check_resume(fixture)
        check_framing_and_failures(fixture)
        check_cross_format_and_legacy(fixture, jobs, args.legacy_input.resolve(strict=True))
        if not args.skip_large:
            check_large_stream(fixture)
        fixture.run("install.hwf", "native-source-final-installer-replay")
        fixture.sql("SELECT enrichment.verify_input_bundle(bundle_id) FROM enrichment.input_bundle WHERE job_run_id="
                    + q(jobs), "final-ndjson-bundle-verification")
        fixture.expect(True, "ndjson-source-installer-replay-preserves-frozen-inputs")
        fixture.receipt["native_reader_sha256"] = sha_file(ROOT / "hop/ingestions/jobkorea/import_local.hpl")
        fixture.receipt["ndjson_sql_sha256"] = sha_file(ROOT / "hop/ingestions/jobkorea/sql/006_ndjson.sql")
        fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "final-source-requests") == "0",
                        "ndjson-final-zero-source-request-ledger")
        fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL",
                                   "final-model-requests") == "0", "ndjson-final-zero-model-requests")
        fixture.receipt["status"] = "PASSED_NDJSON_PARTIAL" if args.skip_large else "PASSED_NATIVE_NDJSON"
    except Exception as error:
        fixture.receipt["status"] = "FAILED"
        fixture.receipt["error"] = type(error).__name__
        raise
    finally:
        fixture.close()
        print("Protected receipt: " + str(fixture.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
