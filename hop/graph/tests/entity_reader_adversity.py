"""Independent SQL009 whole-output and posting-join semantics on the owned oracle.

Retain the prior oracle unchanged, then compare SQL008 with the exact new body.
Synthetic posting worksets exercise the changed stage without relying on source
validity to hide NULL, duplicate, scalar or fallback behavior.
"""
# Transactional SQL and independent fixture values stay readable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = "009_reader_fact_worksets.sql"


def definition(source: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION ingestion.graph_source_entities(")
    return source[start:source.index("$$;", start) + 3]


def literal(value: Any) -> str:
    return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"


def posting_query(source: str, rows: list[dict], selected: list[dict]) -> str:
    body = definition(source)
    stage = body.split(" posting_records AS MATERIALIZED(", 1)[1].split("\n SELECT f.identity_id", 1)[0]
    joins = body.split(" FROM current_facts f JOIN names n USING(identity_id)", 1)[1]
    joins = joins.split("\n WHERE n.choice=1", 1)[0].split("\n ORDER BY f.identity_id", 1)[0]
    columns = "run_id text,source_id text,normalized jsonb"
    facts_columns = "record_id text,run_id text,source_id text,kind text,normalized jsonb"
    return (
        "WITH records AS MATERIALIZED(SELECT r.*,normalized->>'posting_id' AS posting_id,"
        "normalized->>'representation' AS representation FROM jsonb_to_recordset(" + literal(rows) + ") r(" + columns + ")),"
        "current_facts AS MATERIALIZED(SELECT f.*,normalized->>'posting_id' AS posting_id "
        "FROM jsonb_to_recordset(" + literal(selected) + ") f(" + facts_columns + ")),"
        "posting_records AS MATERIALIZED(" + stage
        + " SELECT f.record_id,selected.facts_json FROM current_facts f" + joins
        + " ORDER BY f.record_id;"
    )


def posting_cases(oracle: Any, baseline: str, candidate: str) -> None:
    rows, selected = [], []
    cases = (
        ("job", "job_alio", "123", ("list", "detail"), True),
        ("job-incomplete", "job_alio", "123", ("list",), True),
        ("nara-active", "nara_job", "123", ("list", "detail", "positions", "files"), True),
        ("nara-inactive", "nara_job", "123", ("list",), False),
        ("nara-incomplete", "nara_job", "123", ("list", "detail"), True),
        ("nara-inactive-complete", "nara_job", "123", ("list", "detail", "positions", "files"), False),
        ("nara-json-null", "nara_job", "123", ("list", "detail", "positions", "files"), None),
        ("nara-incomplete-bad-boolean", "nara_job", "123", ("list",), "invalid"),
        ("other-source", "jobkorea", "123", ("list", "detail"), True),
        ("null-key", "job_alio", None, ("list", "detail"), True),
        ("empty-key", "job_alio", "", ("list", "detail"), True),
        ("boolean-key", "job_alio", True, ("list", "detail"), True),
        ("array-key", "job_alio", ["x", 1], ("list", "detail"), True),
        ("object-key", "job_alio", {"x": 1}, ("list", "detail"), True),
    )
    for label, source, key, forms, ongoing in cases:
        for index, form in enumerate(forms):
            normalized = dict(posting_id=123 if index == 0 and key == "123" else key,
                              representation=form, marker=form, ongoing=ongoing,
                              custom=[index, None, True])
            rows.append(dict(run_id=label, source_id=source, posting_id=key,
                             representation=form, normalized=normalized))
        selected.append(dict(record_id=label, run_id=label, source_id=source, posting_id=key,
                             kind="JobPosting", normalized=dict(posting_id=key, marker="fallback", title="fallback")))
    # Equal duplicates preserve the aggregate's bag semantics. A nonposting row
    # sharing the same join keys must retain its own complete payload.
    rows.append(dict(rows[0]))
    selected.append(dict(selected[0], record_id="nonposting", kind="Organization",
                         normalized={"posting_id": "123", "organization_code": "own-org",
                                     "organization_name": "Own organization", "marker": "own"}))
    values = [oracle.sql(posting_query(source, rows, selected)) for source in (baseline, candidate)]
    oracle.check("entity-posting-stage-complete-text-bag", values[0] == values[1])
    facts = {line.split("|", 1)[0]: json.loads(line.split("|", 1)[1]) for line in values[1].splitlines()}
    oracle.check("entity-posting-stage-independent-merge-precedence",
                 facts["job"]["marker"] == "detail" and facts["nara-active"]["marker"] == "files")
    oracle.check("entity-posting-stage-independent-fallbacks", all(
        facts[label]["marker"] == "fallback" for label in
        ("job-incomplete", "nara-inactive", "nara-incomplete", "nara-inactive-complete", "nara-json-null", "nara-incomplete-bad-boolean", "null-key"))
        and facts["other-source"]["title"] == "fallback")
    oracle.check("entity-posting-stage-independent-nonposting", facts["nonposting"] ==
                 {"kind": "Organization", "code": "own-org", "name": "Own organization"})
    null_form = [dict(rows[0], normalized=dict(rows[0]["normalized"], representation=None))]
    for variant, source in (("baseline", baseline), ("candidate", candidate)):
        oracle.sql(posting_query(source, null_form, selected[:1]), failure="field name must not be null")
        oracle.check("entity-posting-null-form-refusal-" + variant, True)


def mutations(oracle: Any, baseline: str, candidate: str) -> None:
    query = "SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY to_jsonb(v)::text),'[]') FROM ingestion.graph_source_entities('job_alio') v;"
    for label, mutation in (
        ("numeric-string", "UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{posting_id}','123'::jsonb) WHERE run_id='new-job' AND normalized->>'representation'='list'"),
        ("unselected-history", "UPDATE ingestion.document SET selected=false WHERE run_id='new-job'"),
        ("blank-name", "UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{name}','\"   \"'::jsonb) WHERE run_id='new-org'"),
        ("timestamp-tie", "UPDATE ingestion.run SET created_at='2026-10-01T00:00:00Z' WHERE run_id='new-job'"),
    ):
        sql = "BEGIN;SET LOCAL session_replication_role=replica;" + mutation + ";SET LOCAL session_replication_role=origin;"
        for source in (baseline, candidate):
            sql += definition(source) + ";" + query
        values = [json.loads(line) for line in oracle.sql(sql + "ROLLBACK;").splitlines()]
        oracle.check("entity-reader-complete-typed-" + label, len(values) == 2 and values[0] == values[1])
        posting = next(row for row in values[1] if row["identity_id"] == "job-alio:posting:123")
        if label == "unselected-history":
            oracle.check("entity-reader-independent-unselected-history", posting["source_run_id"] == "job_alio")
        elif label == "timestamp-tie":
            oracle.check("entity-reader-independent-timestamp-tie", posting["source_run_id"] == "new-job")
        elif label == "blank-name":
            organization = next(row for row in values[1] if row["identity_id"] == "alio:organization:o2")
            oracle.check("entity-reader-independent-blank-name-fallback", organization["entity_name"] == "Organization o2")
    for label, value in (("boolean", True), ("array", ["x", 1]), ("object", {"x": 1})):
        mutation = (
            "UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{posting_id}',"
            + literal(value) + ") WHERE run_id='job_alio';"
            "UPDATE ingestion.partition SET partition_id='detail-'||(" + literal(value)
            + "#>>'{}') WHERE run_id='job_alio' AND partition_id='detail-123';"
            "UPDATE ingestion.document SET partition_id='detail-'||(" + literal(value)
            + "#>>'{}') WHERE run_id='job_alio' AND partition_id='detail-123';"
        )
        sql = "BEGIN;SET LOCAL session_replication_role=replica;" + mutation + "SET LOCAL session_replication_role=origin;"
        for source in (baseline, candidate):
            sql += definition(source) + ";" + query
        values = [json.loads(line) for line in oracle.sql(sql + "ROLLBACK;").splitlines()]
        oracle.check("entity-reader-complete-typed-nonstring-" + label, len(values) == 2 and values[0] == values[1])
        postings = [row for row in values[1] if row["kind"] == "JobPosting"]
        oracle.check("entity-reader-independent-nonstring-facts-" + label,
                     len(postings) == 1 and json.loads(postings[0]["source_facts_json"])["posting_id"] == value)
    for label, mutation in (
        ("duplicate-form", "UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{representation}','\"list\"'::jsonb) WHERE run_id='job_alio'"),
        ("null-form", "UPDATE ingestion.record SET normalized=normalized-'representation' WHERE run_id='job_alio'"),
    ):
        for variant, source in (("baseline", baseline), ("candidate", candidate)):
            oracle.sql("BEGIN;SET LOCAL session_replication_role=replica;" + mutation
                       + ";SET LOCAL session_replication_role=origin;" + definition(source) + ";" + query,
                       failure="SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN")
            oracle.check("entity-reader-invalid-" + label + "-" + variant, True)


def run(oracle: Any, runs: list[str]) -> None:
    baseline = (ROOT / "hop/graph/sql/008_reader_worksets.sql").read_text()
    candidate = (ROOT / "hop/graph/sql" / MIGRATION).read_text()
    before = {run: oracle.snapshot(run) for run in [*runs, "ALL_CHECKPOINTED"]}
    oracle.sql(candidate)
    oracle.sql(candidate)
    for run, snapshot in before.items():
        oracle.check("entity-reader-whole-typed-output-" + run[:24], oracle.snapshot(run) == snapshot)
    oracle.check("entity-reader-idempotent", True)
    posting = next(row for row in before["job_alio"]["entities"] if row["identity_id"] == "job-alio:posting:123")
    oracle.check("entity-reader-independent-latest-valid-facts-and-older-name",
                 posting["source_run_id"] == "new-job" and posting["name_source_run_id"] == "job_alio"
                 and posting["entity_name"] == "Legacy"
                 and json.loads(posting["source_facts_json"])["custom"] == ["first", None, "last"])
    posting_cases(oracle, baseline, candidate)
    mutations(oracle, baseline, candidate)
    for label, change in (("cost", "COST 99"), ("rows", "ROWS 999"), ("parallel", "PARALLEL SAFE"),
                          ("strict", "STRICT"), ("config", "SET work_mem='8MB'")):
        oracle.sql("BEGIN;ALTER FUNCTION ingestion.graph_source_entities(text) " + change + ";" + candidate,
                   failure="SOURCE_GRAPH_READER_FACT_WORKSET_BASELINE_DRIFT")
        oracle.check("entity-reader-migration-metadata-refusal-" + label, True)
    drift = definition(baseline).replace("AS $$", "AS $$\n-- unapproved body\n", 1)
    oracle.sql("BEGIN;" + drift + candidate, failure="SOURCE_GRAPH_READER_FACT_WORKSET_BASELINE_DRIFT")
    oracle.check("entity-reader-migration-unknown-body-refused", True)


def module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("entity_reader_fixture", path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def run_oracle(container: str, directory: Path) -> Path:
    """Use the existing schema-only fixture without repeating unchanged 442 cases."""
    os.umask(0o077)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    inspected = json.loads(subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .}}"],
        capture_output=True, text=True, check=True).stdout)
    if inspected["HostConfig"]["NetworkMode"] != "none" or not re.fullmatch(
        r"jobtology-routine-archive-(?:nara-)?[0-9a-f]+", container
    ):
        raise ValueError("Use only the coordinator-owned network-none archived clone")
    support = module(ROOT / "hop/graph/tests/source_queries_native.py")
    oracle = support.Oracle(container, directory)
    inputs = [
        "hop/graph/tests/entity_reader_adversity.py", "hop/graph/tests/source_queries_native.py",
        "hop/ingestions/jobkorea/tests/graph_compatibility.py", "hop/graph/install.hwf",
        "hop/graph/install_posting_dates.hwf", "hop/graph/tools/build_reader_fact_worksets.py",
    ] + ["hop/graph/sql/" + filename for filename in (
        "001_posting_ingestion_dates.sql", "002_batchfree_source_graph.sql",
        "003_source_query_sharing.sql", "004_verified_proof_replay.sql",
        "005_validation_worksets.sql", "006_jobalio_validation_worksets.sql",
        "007_capture_guard_worksets.sql", "008_reader_worksets.sql", MIGRATION,
    )]
    receipt = dict(
        status="RUNNING", container=container, container_id=inspected["Id"], database=oracle.database,
        production_writes=0, source_requests=0, paid_requests=0, checks=oracle.checks,
        created_at=datetime.now(UTC).isoformat(),
        retained_baseline_checks=442,
        retained_baseline_receipt="capture-worksets-c2c27d69f5ed486fa3fa51f0348a9974/reviewer-final-oracle/receipt.json",
        retained_baseline_receipt_sha256="947d6a104184ec36bbfe3a7b9ec35974ce5976aba2de864d671c041aaa1d0bac",
        artifact_sha256={relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() for relative in inputs},
    )
    created = False
    try:
        dump = subprocess.run(["docker", "exec", container, "pg_dump", "-s", "--no-owner",
                               "--no-privileges", "-U", "postgres", "-d", "jobtology"],
                              capture_output=True, check=True).stdout
        (directory / "schema.sql").write_bytes(dump)
        receipt["schema_sha256"] = hashlib.sha256(dump).hexdigest()
        oracle.sql('CREATE DATABASE "' + oracle.database + '"', database="postgres")
        created = True
        oracle.sql(dump.decode())
        oracle.install(False)
        fixture = module(ROOT / "hop/ingestions/jobkorea/tests/graph_compatibility.py")
        oracle.sql(fixture.FIXTURE)
        oracle.sql("UPDATE ingestion.run SET created_at='2026-10-01T00:00:00Z',completed_at='2026-10-01T00:00:00Z';")
        jk = oracle.synthetic_ndjson()
        oracle.sql("SET session_replication_role=replica;" + support.CLONE + "SET session_replication_role=origin;")
        oracle.install(True)
        runs = ["alio_organization", "job_alio", "nara_job", "ncs_competency", "ncs_career_path",
                "ncs_qualification", "qnet_schedule", jk]
        oracle.sql("SET session_replication_role=replica;INSERT INTO ingestion.graph_export(run_id,loader_version) "
                   "SELECT run_id,'oracle-old-pins' FROM ingestion.run WHERE run_id IN("
                   + ",".join(support.quote(item) for item in runs) + ");SET session_replication_role=origin;")
        run(oracle, runs)
        oracle.sql("SELECT * FROM ingestion.graph_source_entities('absent-run')", failure="SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN")
        oracle.check("entity-reader-absent-run-refused", True)
        receipt["status"] = "PASSED"
    except BaseException as exc:
        receipt["status"], receipt["failure_type"] = "FAILED", type(exc).__name__
        raise
    finally:
        if created:
            oracle.sql('DROP DATABASE "' + oracle.database + '" WITH (FORCE)', database="postgres")
            receipt["database_removed"] = True
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        path = directory / "receipt.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        print(path, flush=True)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    run_oracle(args.container, args.directory)
