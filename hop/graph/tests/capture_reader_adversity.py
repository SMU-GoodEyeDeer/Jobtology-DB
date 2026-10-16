"""Independent native transition-table and reference-bag equivalence cases.

Use only the coordinator's schema-only oracle. Every synthetic relation, view
replacement and function replacement rolls back in its own connection.
"""
# Exact transactional fixture SQL stays readable alongside the native oracle.
# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def literal(value: Any) -> str:
    return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"


def function(source: str, name: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION ingestion." + name + "(")
    return source[start:source.index("$$;", start) + 3]


def guard_case(oracle: Any, label: str, table: str, inserted: list[dict], live: list[dict],
               accepted: bool, *, poststate: bool = False, live_json_null: bool = False) -> None:
    source = "source_graph_live_record_evidence" if table.endswith("record_evidence") else "source_graph_reference"
    original = function((ROOT / "hop/graph/sql/002_batchfree_source_graph.sql").read_text(),
                        "source_graph_insert_guard")
    candidate = function((ROOT / "hop/graph/sql/007_capture_guard_worksets.sql").read_text(),
                         "source_graph_insert_guard")
    for variant, definition in (("original", original), ("candidate", candidate)):
        # CTAS deliberately removes real NOT NULL/PK restrictions so duplicate
        # and NULL joins exercise the trigger itself rather than table checks.
        setup = (
            "BEGIN; CREATE SCHEMA capture_guard_fixture;"
            "CREATE TABLE capture_guard_fixture.live AS TABLE ingestion." + source + " WITH NO DATA;"
            "ALTER TABLE capture_guard_fixture.live ADD metadata jsonb;"
            "CREATE TABLE capture_guard_fixture." + table + " AS TABLE ingestion." + table + " WITH NO DATA;"
            "ALTER TABLE capture_guard_fixture." + table + " ADD metadata jsonb;"
            "INSERT INTO capture_guard_fixture.live SELECT * FROM jsonb_populate_recordset("
            "NULL::capture_guard_fixture.live," + literal(live) + ");"
        )
        if live_json_null:
            setup += "UPDATE capture_guard_fixture.live SET metadata='null'::jsonb;"
        relation = "capture_guard_fixture." + (table if poststate else "live")
        columns = "*" if table.endswith("record_evidence") else "record_id,run_id,identity_id,kind,code,field,metadata"
        setup += (
            "CREATE OR REPLACE VIEW ingestion." + source + " AS SELECT " + columns + " FROM " + relation + ";"
            "CREATE OR REPLACE FUNCTION ingestion.source_graph_run_is_valid(jobs text) RETURNS boolean "
            "LANGUAGE plpgsql STABLE SET jit=off AS $$ BEGIN RETURN jobs IS NOT NULL AND jobs<>'invalid'; END $$;"
            + definition + ";"
            "CREATE TRIGGER check_insert AFTER INSERT ON capture_guard_fixture." + table
            + " REFERENCING NEW TABLE AS new_evidence FOR EACH STATEMENT "
            "EXECUTE FUNCTION ingestion.source_graph_insert_guard();"
            "INSERT INTO capture_guard_fixture." + table + " SELECT * FROM jsonb_populate_recordset("
            "NULL::capture_guard_fixture." + table + "," + literal(inserted) + ");"
            "SELECT count(*) FROM capture_guard_fixture." + table + ";ROLLBACK;"
        )
        if accepted:
            output = oracle.sql(setup)
            oracle.check("capture-" + variant + "-" + table + "-" + label,
                         output == str(len(inserted)))
        else:
            oracle.sql(setup, failure="INVALID_SOURCE_GRAPH_EVIDENCE")
            oracle.check("capture-" + variant + "-" + table + "-" + label, True)


def guard_cases(oracle: Any) -> None:
    for table in ("source_graph_membership", "source_graph_record_evidence"):
        row = dict(run_id="valid", record_id="hop:valid:1", metadata={"nested": [1, None, True]})
        if table.endswith("membership"):
            row.update(identity_id="identity:1", field="posting_id", kind="JobPosting", code="1")
            changed_field = "kind"
            keys = ("record_id", "identity_id", "field")
        else:
            row.update(source_record_id="source:1", **{name: "a" * 64 for name in
                       ("normalized_sha256", "facts_sha256", "document_sha256", "content_sha256")})
            changed_field = "source_record_id"
            keys = ("record_id",)
        other = dict(row, record_id="hop:valid:2")
        different = dict(row, **{changed_field: "different"})
        cases = [
            ("equal", [row], [row], True),
            ("missing-live", [row], [], False),
            ("equal-live-duplicates", [row], [row, row], True),
            ("different-live-duplicate", [row], [row, different], False),
            ("different-inserted-duplicate", [row, different], [row], False),
            ("equal-inserted-duplicates", [row, row], [row], True),
            ("unrelated-extra-live", [row], [row, other], True),
            ("partial-missing-live", [row, other], [row], False),
            ("empty-both", [], [], True),
            ("empty-insert-extra-live", [], [row, different], True),
            ("invalid-run", [dict(row, run_id="invalid")], [dict(row, run_id="invalid")], False),
            ("null-run", [dict(row, run_id=None)], [dict(row, run_id=None)], False),
            ("multiple-runs", [row, dict(other, run_id="second")],
             [row, dict(other, run_id="second")], True),
            ("one-invalid-run", [row, dict(other, run_id="invalid")],
             [row, dict(other, run_id="invalid")], False),
            ("sql-null-payload", [dict(row, **{changed_field: None})],
             [dict(row, **{changed_field: None})], True),
            ("sql-null-nonnull", [dict(row, **{changed_field: None})], [row], False),
            ("json-null-number", [dict(row, metadata=None)], [dict(row, metadata=1)], False),
            ("json-number-string", [dict(row, metadata=1)], [dict(row, metadata="1")], False),
            ("json-number-boolean", [dict(row, metadata=1)], [dict(row, metadata=True)], False),
            ("json-number-scale", [dict(row, metadata=1)], [dict(row, metadata=1.0)], True),
            ("json-array-order", [dict(row, metadata=[1, 2])], [dict(row, metadata=[2, 1])], False),
        ]
        for key in keys:
            value = dict(row, **{key: None})
            cases.append(("null-key-" + key, [value], [value], False))
        for label, inserted, live, accepted in cases:
            guard_case(oracle, label, table, inserted, live, accepted)
        guard_case(oracle, "post-insert-live-view", table, [row], [], True, poststate=True)
        # Complete-row to_jsonb intentionally maps both SQL NULL and JSON null
        # in this extra JSONB field to the same serialized property value.
        guard_case(oracle, "serialized-sql-null-json-null-equivalence", table,
                   [dict(row, metadata=None)], [dict(row, metadata=None)], True,
                   live_json_null=True)


def reference_bags(oracle: Any) -> None:
    source = (ROOT / "hop/graph/sql/003_source_query_sharing.sql").read_text()
    candidate = (ROOT / "hop/graph/sql/008_reader_worksets.sql").read_text()
    sources = ("ncs_career_path", "ncs_competency", "ncs_qualification", "qnet_schedule",
               "alio_organization", "job_alio", "nara_job", "jobkorea", "unknown")
    rows = []
    for source_id in sources:
        for value in (None, "", "abc", 7, True, ["x"], {"x": 1}):
            normalized = {name: value for name in
                          ("occupation_code", "competency_code", "code", "qualification_code",
                           "organization_code", "posting_id")}
            rows.append(dict(run_id="local:run", record_id=len(rows) + 1, source_id=source_id,
                             source_record_id="source:duplicate", normalized=normalized))
        rows.append(dict(run_id="local:run", record_id=len(rows) + 1, source_id=source_id,
                         source_record_id="source:duplicate", normalized={}))
    # Keep genuine duplicate rows; EXCEPT without ALL would miss their loss.
    rows.extend(rows[8:16])
    records = (
        "records AS MATERIALIZED(SELECT * FROM jsonb_to_recordset(" + literal(rows) + ")"
        " r(run_id text,record_id bigint,source_id text,source_record_id text,normalized jsonb))"
    )
    for name in ("graph_source_edges", "graph_source_entities"):
        bodies = []
        for text in (source, candidate):
            definition = function(text, name)
            bodies.append(definition.split("raw_refs AS (\n", 1)[1].split("\n),\nrefs AS MATERIALIZED", 1)[0])
        statement = (
            "WITH " + records + ",original AS(" + bodies[0] + "),candidate AS(" + bodies[1] + "),"
            "differences AS((TABLE original EXCEPT ALL TABLE candidate) UNION ALL "
            "(TABLE candidate EXCEPT ALL TABLE original)) SELECT NOT EXISTS(TABLE differences);"
        )
        oracle.check("reader-native-reference-bag-null-empty-types-duplicates-" + name,
                     oracle.sql(statement) == "t")


def migration_guards(oracle: Any) -> None:
    for filename, names, failure in (
        ("007_capture_guard_worksets.sql", ("source_graph_insert_guard()",),
         "SOURCE_GRAPH_CAPTURE_WORKSET_BASELINE_DRIFT"),
        ("008_reader_worksets.sql", ("graph_source_edges(text)", "graph_source_entities(text)"),
         "SOURCE_GRAPH_READER_WORKSET_BASELINE_DRIFT"),
    ):
        sql = (ROOT / "hop/graph/sql" / filename).read_text()
        oracle.sql(sql)
        oracle.check("migration-idempotent-" + filename, True)
        for name in names:
            for label, change in (
                ("cost", "COST 99"), ("support", "SUPPORT pg_catalog.text_starts_with_support"),
                ("parallel", "PARALLEL SAFE"), ("strict", "STRICT"),
                ("security", "SECURITY DEFINER"), ("configuration", "SET work_mem='8MB'"),
            ):
                oracle.sql("BEGIN;ALTER FUNCTION ingestion." + name + " " + change + ";" + sql,
                           failure=failure)
                oracle.check("migration-drift-refusal-" + name + "-" + label, True)
            # Preserve metadata and alter only the body to verify unknown bodies
            # cannot enter through standalone or canonical candidate installation.
            original_file = "002_batchfree_source_graph.sql" if name.endswith("()") else "003_source_query_sharing.sql"
            definition = function((ROOT / "hop/graph/sql" / original_file).read_text(), name.split("(")[0])
            drift = definition.replace("AS $$", "AS $$\n-- unapproved body\n", 1)
            oracle.sql("BEGIN;" + drift + sql, failure=failure)
            oracle.check("migration-unknown-body-refusal-" + name, True)


def reader_mutations(oracle: Any) -> None:
    original = (ROOT / "hop/graph/sql/003_source_query_sharing.sql").read_text()
    candidate = (ROOT / "hop/graph/sql/008_reader_worksets.sql").read_text()
    query = (
        "SELECT jsonb_build_object('entities',(SELECT coalesce(jsonb_agg(to_jsonb(v)"
        " ORDER BY to_jsonb(v)::text),'[]') FROM ingestion.graph_source_entities('job_alio') v),"
        "'edges',(SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY to_jsonb(v)::text),'[]')"
        " FROM ingestion.graph_source_edges('job_alio') v),'owners',(SELECT"
        " coalesce(jsonb_agg(to_jsonb(v) ORDER BY to_jsonb(v)::text),'[]')"
        " FROM ingestion.graph_source_edge_owners('job_alio') v));"
    )
    for label, mutation in (
        ("numeric-string-posting-keys", "UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{posting_id}','123'::jsonb) WHERE run_id='new-job' AND normalized->>'representation'='list'"),
        ("unselected-newer-documents", "UPDATE ingestion.document SET selected=false WHERE run_id='new-job'"),
        ("blank-authoritative-name", "UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{name}','\"   \"'::jsonb) WHERE run_id='new-org'"),
        ("same-time-run-tie", "UPDATE ingestion.run SET created_at='2026-10-01T00:00:00Z' WHERE run_id='new-job'"),
    ):
        statement = "BEGIN;SET LOCAL session_replication_role=replica;" + mutation + ";SET LOCAL session_replication_role=origin;"
        for source in (original, candidate):
            for name in ("graph_source_edges", "graph_source_entities"):
                statement += function(source, name) + ";"
            statement += query
        values = [json.loads(line) for line in oracle.sql(statement + "ROLLBACK;").splitlines()]
        oracle.check("reader-full-typed-mutation-" + label, len(values) == 2 and values[0] == values[1])
        posting = next(row for row in values[1]["entities"] if row["identity_id"] == "job-alio:posting:123")
        if label == "numeric-string-posting-keys":
            oracle.check("reader-text-key-coercion-independent", posting["source_run_id"] == "new-job"
                         and json.loads(posting["source_facts_json"])["posting_id"] == "123")
        elif label == "unselected-newer-documents":
            oracle.check("reader-unselected-history-independent", posting["source_run_id"] == "job_alio")


def run(oracle: Any) -> None:
    guard_cases(oracle)
    reference_bags(oracle)
    migration_guards(oracle)
    reader_mutations(oracle)
