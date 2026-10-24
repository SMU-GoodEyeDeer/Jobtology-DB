"""Bounded catalogue reads preserve publication/review and latest-capture semantics."""

# SQL fixture rows retain their complete audit fields.
# ruff: noqa: E501
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, LiteralString, cast

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database() -> Iterator[Connection[Any]]:
    dsn = os.environ.get("JOBTOLOGY_CROSSWALK_TEST_ADMIN_DSN")
    if not dsn:
        pytest.skip("Set JOBTOLOGY_CROSSWALK_TEST_ADMIN_DSN to a disposable loopback server")
    if conninfo_to_dict(dsn).get("host") not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail("This fixture requires an explicitly supplied loopback disposable server")
    name = "bounded_occupation_" + uuid.uuid4().hex + "_test"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(make_conninfo(dsn, dbname=name), autocommit=True) as connection:
                connection.execute("""
CREATE SCHEMA ingestion; CREATE SCHEMA enrichment; CREATE SCHEMA catalog;
CREATE TABLE ingestion.run(run_id text PRIMARY KEY,source_id text,state text);
INSERT INTO ingestion.run VALUES('job','jobkorea','READY'),('ncs','ncs_competency','READY');
CREATE VIEW ingestion.latest_ready_run AS SELECT * FROM ingestion.run;
CREATE TABLE enrichment.metadata_occupation_graph_guard(job_run_id text,ncs_run_id text,state text,
 completed_at timestamptz,writer_token text,include_unreviewed boolean);
INSERT INTO enrichment.metadata_occupation_graph_guard VALUES('job','ncs','READY','2026-01-01','writer-1',true);
CREATE TABLE enrichment.metadata_occupation_binding(item_id text,bundle_id text,job_run_id text,ncs_run_id text,source_hash text);
CREATE TABLE enrichment.item(item_id text,posting_id text,batch_id text);
CREATE TABLE enrichment.batch(batch_id text,settings jsonb,created_at timestamptz);
CREATE TABLE enrichment.metadata_occupation_result(item_id text,result_id text,output jsonb);
CREATE TABLE enrichment.input_bundle(bundle_id text,manifest jsonb);
CREATE TABLE enrichment.metadata_occupation_candidate(result_id text,candidate_id text,ncs_run_id text,occupation_code text);
CREATE TABLE enrichment.metadata_occupation_catalog(ncs_run_id text,occupation_code text,occupation_name text,catalog_hash text);
CREATE TABLE enrichment.metadata_occupation_decision(result_id text,decision text,reviewer_kind text,decision_id bigint);
CREATE TABLE enrichment.metadata_occupation_candidate_decision(candidate_id text,decision text,reviewer_kind text,decision_id bigint);
CREATE FUNCTION enrichment.hash(v text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to(v,'UTF8')),'hex') $$;
CREATE FUNCTION enrichment.metadata_occupation_graph_rows(text,text,boolean) RETURNS TABLE(unused text)
 LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'UNBOUNDED_GRAPH_PUBLISHER_CALLED'; END $$;
INSERT INTO enrichment.metadata_occupation_catalog VALUES
 ('ncs','20010201','A','catalog-a'),('ncs','20010202','B','catalog-b');
INSERT INTO enrichment.batch VALUES
 ('legacy','{"prompt_version":"ko-metadata-occupation-v2"}','2026-01-01'),
 ('old','{"prompt_version":"ko-metadata-occupation-v3"}','2026-01-01'),
 ('new','{"prompt_version":"ko-metadata-occupation-v3"}','2026-01-02'),
 ('failed','{"prompt_version":"ko-metadata-occupation-v3"}','2026-01-03');
INSERT INTO enrichment.item VALUES
 ('p1-old','p1','legacy'),('p1-failed','p1','failed'),
 ('p2-old','p2','old'),('p2-new','p2','new'),
 ('p3','p3','new'),('p4','p4','new'),('p5-old','p5','old'),('p5-new','p5','new');
INSERT INTO enrichment.metadata_occupation_binding SELECT item_id,item_id,'job','ncs','source-'||posting_id FROM enrichment.item;
INSERT INTO enrichment.input_bundle SELECT item_id,jsonb_build_object('document',jsonb_build_object(
 'source_record_id',posting_id,'normalized_hash','normalized-'||posting_id)) FROM enrichment.item;
INSERT INTO enrichment.metadata_occupation_result SELECT item_id,item_id,
 CASE WHEN item_id='p2-new' THEN '{"outcome":"abstained","matches":[]}'::jsonb
  WHEN item_id='p3' THEN '{"outcome":"matched","matches":[{"occupation_code":"20010201"},{"occupation_code":"20010202"}]}'::jsonb
  WHEN item_id='p5-old' THEN '{"outcome":"matched","matches":[{"occupation_code":"20010202"}]}'::jsonb
  ELSE '{"outcome":"matched","matches":[{"occupation_code":"20010201"}]}'::jsonb END
 FROM enrichment.item WHERE item_id<>'p1-failed';
INSERT INTO enrichment.metadata_occupation_candidate
 SELECT r.result_id,r.result_id||':'||(match->>'occupation_code'),'ncs',match->>'occupation_code'
 FROM enrichment.metadata_occupation_result r CROSS JOIN LATERAL jsonb_array_elements(r.output->'matches') match;
INSERT INTO enrichment.metadata_occupation_decision VALUES('p1-old','ACCEPT','assistant',1);
INSERT INTO enrichment.metadata_occupation_candidate_decision VALUES
 ('p3:20010201','REJECT','human',1),('p3:20010202','ACCEPT','human',2);
""")
                migration = (
                    ROOT / "hop/ontology/sql/033_posting_occupation_classifications.sql"
                ).read_text()
                # Only install the bounded adapter block; this isolated fixture
                # deliberately omits posting/source function dependencies.
                adapter = migration[
                    migration.index("-- Default hook") : migration.index(
                        "-- An inferred occupation"
                    )
                ]
                connection.execute(sql.SQL(cast(LiteralString, adapter)))
                yield connection
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def rows(
    connection: Connection[Any], codes: list[str] | None = None, postings: list[str] | None = None
) -> list[dict[str, Any]]:
    result = connection.execute(
        "SELECT to_jsonb(r) FROM catalog._inferred_occupation_rows(%s,%s) r ORDER BY posting_key,occupation_code",
        (codes, postings),
    ).fetchall()
    return [cast(dict[str, Any], row[0]) for row in result]


def test_latest_validated_capture_and_candidate_reviews_are_preserved(
    database: Connection[Any],
) -> None:
    result = rows(database)
    assert [(r["posting_key"], r["occupation_code"], r["review_status"]) for r in result] == [
        ("jobkorea:p1", "20010201", "ASSISTANT_REVIEWED"),
        ("jobkorea:p3", "20010202", "HUMAN_REVIEWED"),
        ("jobkorea:p4", "20010201", "UNREVIEWED"),
        ("jobkorea:p5", "20010201", "UNREVIEWED"),
    ]
    # A failed/unrecorded successor cannot hide p1; a captured abstention hides p2.
    # Filtering B must not resurrect p5's older B result after its newer A result.
    assert [r["posting_key"] for r in rows(database, ["20010202"])] == ["jobkorea:p3"]
    assert rows(database, None, ["jobkorea:p4"]) == [result[2]]
    assert rows(database, [], None) == rows(database, None, []) == []
    assert all(r["source_hash"].startswith("source-") and r["catalog_pin"] == "ncs" for r in result)
    assert all(
        r["catalog_freshness"] == "CURRENT" and r["confidence_state"] == "UNASSESSED"
        for r in result
    )
    database.execute(
        "INSERT INTO enrichment.metadata_occupation_graph_guard VALUES('job','ncs','READY','2026-01-02','writer-2',false)"
    )
    assert [r["posting_key"] for r in rows(database)] == ["jobkorea:p1", "jobkorea:p3"]


def test_only_verified_onet_edges_and_requested_source_rows_are_projected(
    database: Connection[Any],
) -> None:
    database.execute("""
CREATE SCHEMA onet_matching; CREATE SCHEMA classification;
CREATE TABLE onet_matching.graph_guard(publication_id text,database_id text,state text,finished_at timestamptz);
CREATE TABLE onet_matching.graph_edge(publication_id text,edge_id text,posting_identity text,
 occupation_identity text,properties jsonb,payload_json text);
CREATE TABLE onet_matching.input(task_id text,posting_identity text,source_id text,source_run_id text,source_facts jsonb);
CREATE TABLE classification.catalog_current(database_id text,release_id text,load_id text);
CREATE TABLE classification.graph_load_node(load_id text,node_id text,content_hash text);
INSERT INTO onet_matching.graph_guard VALUES('verified','neo','VERIFIED','2026-01-01'),('failed','neo','FAILED','2026-01-02');
INSERT INTO classification.catalog_current VALUES('neo','onet-v1','load');
INSERT INTO classification.graph_load_node VALUES('load','onet:15-1252.00','content-hash');
INSERT INTO onet_matching.input VALUES
 ('task1','posting1','jobkorea','job','{"posting_id":"p1"}'),
 ('task2','posting2','job_alio','alio','{"posting_id":"p2"}');
INSERT INTO onet_matching.graph_edge
 SELECT 'verified','edge-'||task_id,posting_identity,'onet:15-1252.00',jsonb_build_object(
 'occupation_code','15-1252.00','release_id','onet-v1','occupation_content_hash','content-hash',
 'source_facts_sha256','source-hash','catalog_hash','catalog-hash','review_status','UNREVIEWED',
 'stage','STAGING','confidence_state','UNASSESSED'),jsonb_build_object('task_id',task_id,'occupation_name','Software Developers')::text
 FROM onet_matching.input;
INSERT INTO onet_matching.graph_edge SELECT 'failed',edge_id,posting_identity,occupation_identity,
 properties||'{"review_status":"HUMAN_REVIEWED"}'::jsonb,payload_json FROM onet_matching.graph_edge;
""")
    result = rows(database, ["15-1252.00"])
    assert [(r["posting_key"], r["review_status"]) for r in result] == [
        ("jobkorea:p1", "UNREVIEWED"),
        ("p2", "UNREVIEWED"),
    ]
    assert rows(database, ["15-1252.00"], ["p2"]) == [result[1]]
    # An unrelated posting's large/invalid legacy payload is not even decoded
    # for a bounded request; input identities must narrow edges first.
    database.execute(
        "UPDATE onet_matching.graph_edge SET payload_json='not-json' WHERE posting_identity='posting1'"
    )
    assert rows(database, ["15-1252.00"], ["p2"]) == [result[1]]


def test_catalog_rollover_requires_a_revalidation_receipt_and_keeps_original_pins(
    database: Connection[Any],
) -> None:
    original = rows(database)
    database.execute("""
INSERT INTO ingestion.run VALUES('new-ncs','ncs_competency','READY');
CREATE OR REPLACE VIEW ingestion.latest_ready_run AS SELECT * FROM ingestion.run
 WHERE source_id<>'ncs_competency' OR run_id='new-ncs';
""")
    assert all(row["catalog_freshness"] == "STALE" for row in rows(database))
    database.execute("""
CREATE OR REPLACE FUNCTION catalog._ncs_catalog_revalidation(original text,code text,original_hash text)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('receipt','fixture-verified-context','original_pin',original)
 WHERE original='ncs' AND code='20010201' AND original_hash='catalog-a' $$;
""")
    revalidated = rows(database)
    assert [row["catalog_freshness"] for row in revalidated] == [
        "CURRENT",
        "STALE",
        "CURRENT",
        "CURRENT",
    ]
    for before, after in zip(original, revalidated, strict=True):
        assert {key: value for key, value in before.items() if key != "catalog_freshness"} == {
            key: value for key, value in after.items() if key != "catalog_freshness"
        }
