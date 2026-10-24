"""Actual SQL crosswalk tests in a uniquely owned, disposable loopback database."""
# SQL fixtures preserve complete source literals.
# ruff: noqa: E501

from __future__ import annotations

import json
import os
import runpy
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, LiteralString, cast

import psycopg
import pytest
from psycopg import Connection

ROOT = Path(__file__).resolve().parents[2]
UNIT = "ncs:unit:2001020101_24v2"
BASE = "ncs:unit:2001020101"
OCC = "ncs:occupation:20010201"
ONET = "urn:jobtology:onet:occupation:15-1252.00"
TASK = "urn:jobtology:onet-detail:task:123"


@pytest.fixture
def database() -> Iterator[Connection[Any]]:
    dsn = os.environ.get("JOBTOLOGY_CROSSWALK_TEST_ADMIN_DSN")
    if not dsn:
        pytest.skip("Set JOBTOLOGY_CROSSWALK_TEST_ADMIN_DSN to a disposable loopback PG17+ server")
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    settings = conninfo_to_dict(dsn)
    if settings.get("host") not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail("Crosswalk tests require an explicitly supplied loopback disposable server")
    name = "ncs_onet_crosswalk_" + uuid.uuid4().hex + "_test"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(make_conninfo(dsn, dbname=name), autocommit=True) as connection:
                connection.execute("""
CREATE SCHEMA ingestion; CREATE SCHEMA catalog; CREATE SCHEMA classification; CREATE SCHEMA onet_detail;
CREATE TABLE ingestion.run(run_id text PRIMARY KEY,source_id text,state text,mode text);
INSERT INTO ingestion.run VALUES('ncs-v1','ncs_competency','READY','FULL'),('ncs-v2','ncs_competency','READY','FULL');
CREATE TABLE ingestion.active(pin text); INSERT INTO ingestion.active VALUES('ncs-v1');
CREATE VIEW ingestion.latest_ready_run AS SELECT r.* FROM ingestion.run r JOIN ingestion.active a ON a.pin=r.run_id;
CREATE TABLE ingestion.ready_record(run_id text,source_id text,normalized jsonb);
INSERT INTO ingestion.ready_record VALUES('ncs-v1','ncs_competency','{
 "code":"2001020101_24v2","occupation_code":"20010201","occupation_name":"응용SW엔지니어링",
 "name":"데이터베이스 구현","definition":"데이터베이스와 SQL로 데이터를 저장하고 조회한다."}');
INSERT INTO ingestion.ready_record SELECT 'ncs-v2',source_id,jsonb_set(normalized,'{definition}','"변경된 정의"') FROM ingestion.ready_record;
CREATE TABLE classification.catalog_release(release_id text PRIMARY KEY,state text);
CREATE TABLE classification.catalog_current(scheme_id text PRIMARY KEY,release_id text);
CREATE TABLE classification.term(release_id text,term_id text,code text,term_kind text,preferred_label text,description text);
INSERT INTO classification.catalog_release VALUES('onet-v1','READY');
INSERT INTO classification.catalog_current VALUES('ONET','onet-v1');
INSERT INTO classification.term VALUES('onet-v1','urn:jobtology:onet:occupation:15-1252.00','15-1252.00','OCCUPATION','Software Developers','Develop applications.');
CREATE TABLE onet_detail.catalog_release(release_id text PRIMARY KEY,state text);
CREATE TABLE onet_detail.catalog_current(scheme_id text PRIMARY KEY,release_id text);
CREATE TABLE onet_detail.node(release_id text,id text,type text,properties jsonb);
INSERT INTO onet_detail.catalog_release VALUES('detail-v1','READY');
INSERT INTO onet_detail.catalog_current VALUES('ONET','detail-v1');
INSERT INTO onet_detail.node VALUES
 ('detail-v1','urn:jobtology:onet-detail:task:123','TASK','{"task_id":123,"task":"Design database applications."}'),
 ('detail-v1','urn:jobtology:onet-detail:element:2.B.1','ELEMENT','{"element_id":"2.B.1","element_name":"Critical Thinking","description":"Reason about alternatives."}');
CREATE TABLE catalog.fixture_association(posting_key text,source_id text,occupation_scheme text,occupation_code text,
 source_freshness text,catalog_freshness text,association jsonb);
CREATE FUNCTION catalog._live_occupation_associations(posting_choices text[] DEFAULT NULL,occupation_codes text[] DEFAULT NULL)
RETURNS SETOF catalog.fixture_association LANGUAGE sql STABLE AS $$
 SELECT * FROM catalog.fixture_association WHERE (posting_choices IS NULL OR posting_key=ANY(posting_choices))
 AND (occupation_codes IS NULL OR occupation_code=ANY(occupation_codes)) $$;
INSERT INTO catalog.fixture_association VALUES
 ('jobkorea:42','jobkorea','NCS','20010201','CURRENT','CURRENT',
 '{"occupation_name":"응용SW엔지니어링","association_id":"ncs-a","source_pins":{"run_id":"source-1"},"catalog_pins":{"pin":"ncs-v1","catalog_hash":"ncs-hash"},"review_status":"UNREVIEWED"}'),
 ('jobkorea:42','jobkorea','ONET','15-1252.00','CURRENT','CURRENT',
 '{"occupation_name":"Software Developers","association_id":"onet-a","source_pins":{"run_id":"source-1"},"catalog_pins":{"pin":"onet-v1","catalog_hash":"onet-hash"},"review_status":"ASSISTANT_REVIEWED"}');
""")
                connection.execute("""
CREATE SEQUENCE catalog.qa_observation_calls;
CREATE FUNCTION catalog._live_source_observations()
RETURNS TABLE(posting_id text,source_id text,normalized jsonb) LANGUAGE sql STABLE AS $$
 SELECT 'jobkorea:42'::text,'jobkorea'::text,'{"posting_id":"42"}'::jsonb
 WHERE nextval('catalog.qa_observation_calls')>0 $$;
CREATE FUNCTION catalog._live_source_fact_hash(source text,value jsonb)
RETURNS text LANGUAGE sql STABLE AS $$ SELECT encode(sha256(convert_to(value::text,'UTF8')),'hex') $$;
CREATE FUNCTION catalog._inferred_occupation_rows(occupation_codes text[],posting_choices text[])
RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,
 occupation_scheme text,occupation_code text,occupation_name text,association_id text,
 review_status text,stage text,confidence_state text,source_hash text,
 normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,catalog_freshness text)
LANGUAGE sql STABLE AS $$
 SELECT f.posting_key,'source:posting:42',f.source_id,f.association#>>'{source_pins,run_id}',
  f.occupation_scheme,f.occupation_code,f.association->>'occupation_name',f.association->>'association_id',
  f.association->>'review_status','STAGING','UNASSESSED',NULL::text,
  CASE WHEN f.occupation_scheme='NCS' AND f.source_freshness='CURRENT'
   THEN encode(sha256(convert_to('{"posting_id":"42"}'::jsonb::text,'UTF8')),'hex')
   WHEN f.occupation_scheme='NCS' AND f.source_freshness='STALE' THEN 'old-hash' END,
  CASE WHEN f.occupation_scheme='ONET' AND f.source_freshness='CURRENT'
   THEN encode(sha256(convert_to('{"posting_id":"42"}'::jsonb::text,'UTF8')),'hex')
   WHEN f.occupation_scheme='ONET' AND f.source_freshness='STALE' THEN 'old-hash' END,
  f.association#>>'{catalog_pins,pin}',f.association#>>'{catalog_pins,catalog_hash}',f.catalog_freshness
 FROM catalog.fixture_association f
 WHERE (posting_choices IS NULL OR f.posting_key=ANY(posting_choices))
  AND (occupation_codes IS NULL OR f.occupation_code=ANY(occupation_codes)) $$;
""")
                connection.execute(
                    sql.SQL(
                        cast(
                            LiteralString,
                            (ROOT / "hop/ontology/sql/034_ncs_onet_crosswalk.sql").read_text(),
                        )
                    )
                )
                yield connection
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def read(
    connection: Connection[Any],
    node: str = UNIT,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT catalog.ncs_onet_crosswalk_v1(%s,%s,%s)", (node, limit, offset)
    ).fetchone()
    assert row is not None
    return cast(dict[str, Any], row[0])


def propose(connection: Connection[Any], **changes: str) -> str:
    from psycopg.types.json import Jsonb

    evidence = (
        dict(
            summary="Both catalogue passages refer to a database implementation task.",
            source_quote="데이터베이스",
            target_quote="database",
        )
        | changes
    )
    row = connection.execute(
        "SELECT catalog.propose_ncs_onet_mapping(%s,%s,%s,%s)",
        (UNIT, TASK, "PARTIAL", Jsonb(evidence)),
    ).fetchone()
    assert row is not None and isinstance(row[0], str)
    return row[0]


def test_shared_postings_are_related_proposals_with_original_pins(
    database: Connection[Any],
) -> None:
    database.execute("SELECT setval('catalog.qa_observation_calls',1,false)")
    result = read(database, OCC)
    observed = database.execute(
        "SELECT last_value,is_called FROM catalog.qa_observation_calls"
    ).fetchone()
    assert observed == (1, True)  # Anchor/counterpart source hashes share one source scan.
    assert result["competency_evidence"] is False
    assert result["total"] == 1
    item = result["items"][0]
    assert item["status"] == "PROPOSED" and item["relation"] == "RELATED"
    assert item["basis"] == "SHARED_POSTINGS" and item["review"] is None
    assert item["evidence"]["shared_postings"] == 1
    assert item["evidence"]["associations"][0]["ncs_review_status"] == "UNREVIEWED"
    assert item["source"]["catalog_pin"] == "ncs-v1"
    assert item["target"]["catalog_pin"] == "onet-v1"
    assert item["source_freshness"] == item["catalog_freshness"] == "CURRENT"
    assert read(database, ONET)["items"] == result["items"]
    database.execute(
        "UPDATE catalog.fixture_association SET catalog_freshness='STALE' WHERE occupation_scheme='NCS'"
    )
    assert read(database, OCC)["items"][0]["catalog_freshness"] == "STALE"
    database.execute(
        "UPDATE catalog.fixture_association SET source_freshness='UNKNOWN' WHERE occupation_scheme='NCS'"
    )
    assert read(database, OCC)["items"][0]["source_freshness"] == "UNKNOWN"


def test_bilingual_candidates_have_exact_quotes_and_resolve_a_base_to_its_actual_version(
    database: Connection[Any],
) -> None:
    database.execute("SELECT setval('catalog.qa_observation_calls',1,false)")
    result = read(database, BASE)
    assert result["total"] == 1
    assert database.execute("SELECT is_called FROM catalog.qa_observation_calls").fetchone() == (
        False,
    )
    item = result["items"][0]
    assert item["source"]["id"] == UNIT
    assert item["source"]["code"] == "2001020101_24v2"
    assert item["target"]["id"] == TASK
    assert item["evidence"]["source_quote"] == "데이터베이스"
    assert item["evidence"]["target_quote"] == "database"
    assert item["basis"] == "BILINGUAL_CUE"
    assert item["relation"] == "RELATED" and item["status"] == "PROPOSED"
    assert item["competency_evidence"] is False
    assert read(database)["items"] == result["items"]
    assert read(database, TASK)["items"] == result["items"]
    assert read(database, "urn:jobtology:" + BASE)["items"] == result["items"]
    assert read(database, "urn:jobtology:" + UNIT)["items"] == result["items"]


def test_evidenced_proposals_are_idempotent_and_real_reviews_are_append_only(
    database: Connection[Any],
) -> None:
    identity = propose(database)
    assert propose(database) == identity
    item = next(i for i in read(database)["items"] if i["mapping_id"] == identity)
    assert item["status"] == "PROPOSED" and item["review"] is None
    assert item["source_freshness"] == item["catalog_freshness"] == "CURRENT"
    review_row = database.execute(
        "SELECT catalog.review_ncs_onet_mapping(%s,'APPROVED','ASSISTANT',%s,%s,0)",
        (identity, "fixture assistant", "Compared both specific catalogue definitions."),
    ).fetchone()
    assert review_row is not None and isinstance(review_row[0], int)
    review_id = review_row[0]
    item = next(i for i in read(database, BASE)["items"] if i["mapping_id"] == identity)
    assert item["status"] == "APPROVED" and item["relation"] == "PARTIAL"
    assert item["review"]["reviewer_kind"] == "ASSISTANT"
    assert item["review"]["review_id"] == review_id
    assert item["competency_evidence"] is False
    assert read(database)["total"] == 1  # A reviewed pair suppresses duplicate cue proposals.
    with pytest.raises(Exception, match="CROSSWALK_REVIEW_CONFLICT"):
        database.execute(
            "SELECT catalog.review_ncs_onet_mapping(%s,'REJECTED','HUMAN','fixture','The previous review must not be overwritten.',0)",
            (identity,),
        )
    database.execute(
        "SELECT catalog.review_ncs_onet_mapping(%s,'REJECTED','ASSISTANT','fixture','The relation requires additional evidence.',%s)",
        (identity, review_id),
    )
    assert read(database)["total"] == 0  # Rejected pairs do not immediately reappear as cues.
    count_row = database.execute("SELECT count(*) FROM catalog.ncs_onet_review").fetchone()
    assert count_row is not None and count_row[0] == 2
    with pytest.raises(Exception, match="IMMUTABLE_CROSSWALK_RECORD"):
        database.execute("UPDATE catalog.ncs_onet_mapping SET relation='EXACT'")
    with pytest.raises(Exception, match="IMMUTABLE_CROSSWALK_RECORD"):
        database.execute("DELETE FROM catalog.ncs_onet_review")
    with pytest.raises(Exception, match="IMMUTABLE_CROSSWALK_RECORD"):
        database.execute("TRUNCATE catalog.ncs_onet_review")
    with pytest.raises(Exception, match="IMMUTABLE_CROSSWALK_RECORD"):
        database.execute("TRUNCATE catalog.ncs_onet_mapping CASCADE")


def test_missing_and_fabricated_evidence_is_rejected_and_rollover_keeps_history_stale(
    database: Connection[Any],
) -> None:
    with pytest.raises(Exception, match="CROSSWALK_QUOTE_NOT_IN_CATALOG"):
        propose(database, target_quote="Invented claim")
    with pytest.raises(Exception, match="INVALID_CROSSWALK_PROPOSAL"):
        propose(database, source_quote="")
    identity = propose(database)
    database.execute("UPDATE ingestion.active SET pin='ncs-v2'")
    stored = next(i for i in read(database)["items"] if i["mapping_id"] == identity)
    assert stored["source_freshness"] == "STALE"
    assert stored["catalog_freshness"] == "CURRENT"
    assert stored["source"]["catalog_pin"] == "ncs-v1"
    old = database.execute("SELECT catalog._crosswalk_node(%s,'ncs-v1')", (UNIT,)).fetchone()
    assert old is not None and old[0] == stored["source"]
    with pytest.raises(Exception, match="STALE_CROSSWALK_ENDPOINT"):
        database.execute(
            "SELECT catalog.review_ncs_onet_mapping(%s,'APPROVED','ASSISTANT','fixture','Compared both specific catalogue definitions.',0)",
            (identity,),
        )


def test_pagination_validation_and_reader_cannot_propose_or_write(
    database: Connection[Any],
) -> None:
    assert read(database, BASE, 1, 1)["items"] == []
    with pytest.raises(Exception, match="INVALID_CROSSWALK_FILTER"):
        read(database, "bad")
    with pytest.raises(Exception, match="INVALID_LIVE_PAGE"):
        read(database, limit=0)
    database.execute("CREATE ROLE crosswalk_reader")
    try:
        database.execute("GRANT USAGE ON SCHEMA catalog TO crosswalk_reader")
        database.execute(
            "GRANT EXECUTE ON FUNCTION catalog.ncs_onet_crosswalk_v1(text,integer,integer) TO crosswalk_reader"
        )
        database.execute("SET ROLE crosswalk_reader")
        assert read(database)["total"] == 1
        with pytest.raises(Exception, match="permission denied"):
            database.execute("SELECT * FROM catalog.ncs_onet_mapping")
        with pytest.raises(Exception, match="permission denied"):
            propose(database)
    finally:
        database.execute("RESET ROLE")
        database.execute("DROP OWNED BY crosswalk_reader")
        database.execute("DROP ROLE crosswalk_reader")


def test_shared_posting_pairs_are_restricted_to_the_requested_endpoint(
    database: Connection[Any],
) -> None:
    database.execute("""
INSERT INTO ingestion.ready_record SELECT run_id,source_id,
 jsonb_set(jsonb_set(normalized,'{occupation_code}','"20010202"'),'{code}','"2001020201_24v1"')
 FROM ingestion.ready_record WHERE run_id='ncs-v1';
INSERT INTO classification.term SELECT release_id,'urn:jobtology:onet:occupation:15-1254.00',
 '15-1254.00',term_kind,'Web Developers',description FROM classification.term;
INSERT INTO catalog.fixture_association SELECT posting_key,source_id,occupation_scheme,'20010202',
 source_freshness,catalog_freshness,association||'{"occupation_name":"다른 NCS","association_id":"ncs-b"}'::jsonb
 FROM catalog.fixture_association WHERE occupation_scheme='NCS';
INSERT INTO catalog.fixture_association SELECT posting_key,source_id,occupation_scheme,'15-1254.00',
 source_freshness,catalog_freshness,association||'{"occupation_name":"Web Developers","association_id":"onet-b"}'::jsonb
 FROM catalog.fixture_association WHERE occupation_scheme='ONET';
""")
    ncs_links = read(database, OCC)["items"]
    onet_links = read(database, ONET)["items"]
    assert len(ncs_links) == len(onet_links) == 2
    assert all(item["source"]["id"] == OCC for item in ncs_links)
    assert all(item["target"]["id"] == ONET for item in onet_links)


def test_operator_cli_reads_proposes_and_records_an_explicit_review(
    database: Connection[Any],
    tmp_path: Path,
) -> None:
    cli = runpy.run_path(str(ROOT / "hop/operations/manage_ncs_onet_crosswalk.py"))
    parser = cli["parser"]()
    run = cli["run"]
    result = run(parser.parse_args(["list", "--node-id", BASE]), database.info.dsn)
    assert result["items"][0]["status"] == "PROPOSED"
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(
        json.dumps(
            {
                "summary": "Both catalogue passages refer to database implementation work.",
                "source_quote": "데이터베이스",
                "target_quote": "database",
            }
        )
    )
    identity = run(
        parser.parse_args(
            [
                "propose",
                "--source-id",
                UNIT,
                "--target-id",
                TASK,
                "--relation",
                "PARTIAL",
                "--evidence-file",
                str(evidence_file),
            ]
        ),
        database.info.dsn,
    )
    note = tmp_path / "note.txt"
    note.write_text("Compared both catalogue definitions in this synthetic fixture.")
    review = run(
        parser.parse_args(
            [
                "review",
                "--mapping-id",
                identity,
                "--decision",
                "APPROVED",
                "--reviewer-kind",
                "ASSISTANT",
                "--reviewer",
                "fixture assistant",
                "--note-file",
                str(note),
                "--expected-review-id",
                "0",
            ]
        ),
        database.info.dsn,
    )
    assert isinstance(review, int)
    item = next(i for i in read(database)["items"] if i["mapping_id"] == identity)
    assert item["status"] == "APPROVED" and item["review"]["reviewer_kind"] == "ASSISTANT"


def test_canonical_onet_skill_alias_resolves_only_the_current_exact_element(
    database: Connection[Any],
) -> None:
    database.execute("""
INSERT INTO onet_detail.node VALUES('detail-v1','urn:jobtology:onet-detail:element:2.B.3.e','ELEMENT',
 '{"element_id":"2.B.3.e","element_name":"Programming","description":"Writing computer programs."}');
UPDATE ingestion.ready_record SET normalized=jsonb_set(normalized,'{definition}','"프로그래밍과 SQL을 사용한다."') WHERE run_id='ncs-v1';
""")
    canonical = read(database, "onet:skill:2.B.3.e")
    exact = read(database, "urn:jobtology:onet-detail:element:2.B.3.e")
    assert canonical["items"] == exact["items"]
    assert len(canonical["items"]) == 1
    assert canonical["items"][0]["target"]["id"] == "urn:jobtology:onet-detail:element:2.B.3.e"
    database.execute(
        "UPDATE onet_detail.node SET properties=jsonb_set(properties,'{element_id}',%s::jsonb) WHERE id='urn:jobtology:onet-detail:element:2.B.3.e'",
        (json.dumps("different"),),
    )
    assert read(database, "onet:skill:2.B.3.e")["items"] == []
    assert read(database, "onet:skill:" + "x" * (500 - len("onet:skill:")))["total"] == 0
    with pytest.raises(Exception, match="INVALID_CROSSWALK_FILTER"):
        read(database, "onet:skill:" + "x" * (501 - len("onet:skill:")))
