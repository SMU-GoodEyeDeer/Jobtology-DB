"""Independent issue-bag and failure expectations for scoped validation worksets.

Called only inside source_queries_native's disposable schema-only database.
Every adversarial write rolls back; no network or production access is made.
"""
# JSON/SQL fixtures deliberately retain visible source-type distinctions.
# ruff: noqa: E501

from __future__ import annotations

import json


def compare(oracle, label: str, mutation: str, *, target: str = "nara_job",
            conflict_count: int | None = None, row_count: int | None = None) -> None:
    statement = "BEGIN; SET LOCAL session_replication_role=replica; " + mutation + ";"
    statement += f"""WITH scoped AS MATERIALIZED (
 SELECT * FROM ingestion.source_graph_validation_issue('{target}')
), canonical AS MATERIALIZED (
 SELECT * FROM ingestion.validation_issue WHERE run_id='{target}'
)
SELECT jsonb_build_object(
 'bag_equal',(SELECT jsonb_agg(to_jsonb(v) ORDER BY issue,location) FROM scoped v)
  IS NOT DISTINCT FROM (SELECT jsonb_agg(to_jsonb(v) ORDER BY issue,location) FROM canonical v),
 'conflicts',(SELECT count(*) FROM scoped WHERE issue='NARA_POSTING_CONFLICT'),
 'rows',(SELECT count(*) FROM scoped WHERE issue='ROW_COUNT_MISMATCH'),
 'valid',ingestion.source_graph_run_is_valid('{target}'));ROLLBACK;"""
    value = json.loads(oracle.sql(statement))
    oracle.check("adversarial-exact-issue-bag-" + label, value["bag_equal"])
    if conflict_count is not None:
        oracle.check("independent-conflict-multiplicity-" + label,
                     value["conflicts"] == conflict_count)
    if row_count is not None:
        oracle.check("independent-document-count-" + label, value["rows"] == row_count)
    oracle.check("adversarial-fresh-repair-" + label,
                 oracle.sql("SELECT ingestion.source_graph_run_is_valid('" + target + "')") == "t")


def rows(values: list[tuple[str, str | None, str, object]]) -> str:
    # Source IDs and locators are distinct even when normalized posting IDs or
    # representations repeat, so native PKs remain active during replica writes.
    payload = []
    for name, posting, representation, title in values:
        payload.append(dict(name=name, normalized=dict(kind="JobPosting", posting_id=posting,
                         representation=representation, title=title, ongoing=False)))
    serialized = json.dumps(payload, ensure_ascii=False).replace("'", "''")
    return f"""DELETE FROM ingestion.record WHERE run_id='nara_job';
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
SELECT 'nara_job','index',v.name,v.name,'{{}}',v.normalized
FROM jsonb_to_recordset('{serialized}'::jsonb) v(name text,normalized jsonb)"""


def run(oracle) -> None:
    cases = (
        ("duplicate-two-by-two", [("l1", "x", "list", "A"), ("l2", "x", "list", "A"),
                                   ("d1", "x", "detail", "B"), ("d2", "x", "detail", "B")], 4),
        ("null-id-no-match", [("l", None, "list", "A"), ("d", None, "detail", "B")], 0),
        ("empty-id-matches", [("l", "", "list", "A"), ("d", "", "detail", "B")], 1),
        ("null-list-title-conflicts", [("l", "x", "list", None), ("d", "x", "detail", "B")], 1),
        ("null-empty-detail-titles", [("l", "x", "list", "A"), ("d1", "x", "detail", None),
                                       ("d2", "x", "detail", "")], 0),
        ("non-string-title-text-equality", [("l", "x", "list", 7), ("d", "x", "detail", "7")], 0),
        ("title-array-object-text", [("l", "x", "list", ["A", None]),
                                     ("d", "x", "detail", {"a": 1})], 1),
        ("list-only-detail-only-keys", [("l", "one", "list", "A"), ("d", "two", "detail", "B")], 0),
    )
    for label, fixture, expected in cases:
        compare(oracle, label, rows(fixture), conflict_count=expected)
    compare(oracle, "missing-fields",
            "UPDATE ingestion.record SET normalized=normalized-ARRAY['posting_id','title'] WHERE run_id='nara_job'",
            conflict_count=0)
    compare(oracle, "multiple-rejected-and-record-rows",
            "INSERT INTO ingestion.rejected_row VALUES('nara_job','index','bad1','INVALID','{}'),('nara_job','index','bad2','INVALID','{}');UPDATE ingestion.document SET item_count=3 WHERE run_id='nara_job'",
            conflict_count=0, row_count=0)
    compare(oracle, "zero-records-null-item-count",
            "DELETE FROM ingestion.record WHERE run_id='nara_job';UPDATE ingestion.document SET item_count=NULL WHERE run_id='nara_job'",
            conflict_count=0, row_count=1)
    compare(oracle, "zero-records-zero-item-count",
            "DELETE FROM ingestion.record WHERE run_id='nara_job';UPDATE ingestion.document SET item_count=0 WHERE run_id='nara_job'",
            conflict_count=0, row_count=0)
    compare(oracle, "unselected-document-excluded",
            "UPDATE ingestion.document SET selected=false,item_count=999 WHERE run_id='nara_job'",
            conflict_count=0, row_count=0)
    # JOB-ALIO compares jsonb values: numeric and string titles remain different.
    compare(oracle, "jobalio-jsonb-title-type",
            "UPDATE ingestion.record SET normalized=normalized||jsonb_build_object('title',CASE WHEN normalized->>'representation'='list' THEN '7'::jsonb ELSE '\"7\"'::jsonb END) WHERE run_id='job_alio'",
            target="job_alio")
    compare(oracle, "other-source-malformed-boolean-is-not-cast",
            "UPDATE ingestion.record SET normalized=normalized||'{\"ongoing\":\"malformed\"}' WHERE run_id='alio_organization'",
            target="alio_organization")
    compare(oracle, "nara-active-resource-accounting",
            "UPDATE ingestion.record SET normalized=normalized||'{\"ongoing\":true}' WHERE run_id='nara_job'",
            conflict_count=0)
    for relation in ("ingestion.validation_issue WHERE run_id='nara_job'",
                     "ingestion.source_graph_validation_issue('nara_job')"):
        oracle.sql("BEGIN; SET LOCAL session_replication_role=replica; UPDATE ingestion.record SET normalized=normalized||'{\"ongoing\":\"malformed\"}' WHERE run_id='nara_job';SELECT count(*) FROM " + relation + ";ROLLBACK;",
                   failure="invalid input syntax for type boolean")
    oracle.check("malformed-nara-cast-failure-preserved", True)
