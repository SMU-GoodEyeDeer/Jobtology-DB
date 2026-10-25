"""The crosswalk's bounded source reader equals SQL031 after exact ID filtering."""

# SQL fixture literals retain their complete source shape.
# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path
from typing import Any, LiteralString, cast

import pytest
from psycopg import Connection, sql

from .test_ncs_onet_crosswalk import database as database

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def source_database(database: Connection[Any]) -> Connection[Any]:
    connection = database
    connection.execute("""
ALTER TABLE ingestion.run ADD created_at timestamptz DEFAULT '2026-01-01', ADD completed_at timestamptz DEFAULT '2026-01-02';
CREATE OR REPLACE VIEW ingestion.latest_ready_run AS
 SELECT DISTINCT ON(source_id) * FROM ingestion.run WHERE state='READY' AND mode<>'SMOKE'
 ORDER BY source_id,created_at DESC,run_id DESC;
CREATE TABLE ingestion.document(run_id text,document_id text,selected boolean);
CREATE TABLE ingestion.record(run_id text,document_id text,record_id text,normalized jsonb);
INSERT INTO ingestion.run(run_id,source_id,state,mode,created_at) VALUES
 ('jk-old','jobkorea','READY','FULL','2026-01-01'),('jk-new','jobkorea','READY','FULL','2026-01-03'),
 ('jk-smoke','jobkorea','READY','SMOKE','2026-01-04'),('jk-failed','jobkorea','FAILED','FULL','2026-01-05'),
 ('alio-old','job_alio','READY','FULL','2026-01-01'),('alio-new','job_alio','READY','FULL','2026-01-03'),
 ('nara-old','nara_job','READY','FULL','2026-01-01'),('nara-new','nara_job','READY','FULL','2026-01-03');
INSERT INTO ingestion.document SELECT run_id,'selected',true FROM ingestion.run;
INSERT INTO ingestion.document VALUES('jk-new','unselected',false);
INSERT INTO ingestion.record VALUES
 ('jk-old','selected','old42','{"kind":"JobPosting","posting_id":"42","representation":"local_listing","metadata_accepted":true,"title":"old"}'),
 ('jk-old','selected','old43','{"kind":"JobPosting","posting_id":"43","representation":"local_listing","metadata_accepted":true,"title":"delta omission"}'),
 ('jk-new','selected','new42a','{"kind":"JobPosting","posting_id":"42","representation":"local_listing","metadata_accepted":true,"title":"superseded tie"}'),
 ('jk-new','selected','new42z','{"kind":"JobPosting","posting_id":"42","representation":"local_listing","metadata_accepted":true,"title":"new"}'),
 ('jk-new','selected','bad43','{"kind":"JobPosting","posting_id":"43","representation":"local_listing","metadata_accepted":false,"title":"not accepted"}'),
 ('jk-new','unselected','bad44','{"kind":"JobPosting","posting_id":"44","representation":"local_listing","metadata_accepted":true}'),
 ('jk-smoke','selected','smoke','{"kind":"JobPosting","posting_id":"42","representation":"local_listing","metadata_accepted":true}'),
 ('jk-failed','selected','failed','{"kind":"JobPosting","posting_id":"42","representation":"local_listing","metadata_accepted":true}'),
 ('alio-old','selected','alio-old','{"kind":"JobPosting","posting_id":"42","representation":"list","title":"old alio"}'),
 ('alio-new','selected','alio-new','{"kind":"JobPosting","posting_id":"42","representation":"list","title":"current alio"}'),
 ('nara-old','selected','nara-old','{"kind":"JobPosting","posting_id":"42","representation":"list","title":"old nara"}');
INSERT INTO ingestion.record SELECT 'nara-new','selected',representation,
 jsonb_build_object('kind','JobPosting','posting_id','42','representation',representation,
  'title','current nara','nullable',CASE WHEN representation='list' THEN 'preserved' END)
 FROM unnest(ARRAY['list','detail','positions','files']) representation;
INSERT INTO ingestion.record SELECT 'nara-new','selected','incomplete',
 '{"kind":"JobPosting","posting_id":"43","representation":"list","title":"incomplete"}'::jsonb;
CREATE SEQUENCE catalog.qa_alio_calls;
CREATE FUNCTION catalog._live_job_postings(run text) RETURNS TABLE(posting_id text,normalized jsonb)
LANGUAGE plpgsql STABLE AS $$ BEGIN
 PERFORM nextval('catalog.qa_alio_calls');
 RETURN QUERY SELECT r.normalized->>'posting_id',r.normalized FROM ingestion.record r
 WHERE r.run_id=run AND r.normalized->>'representation'='list';
END $$;
""")
    original = (ROOT / "hop/ontology/sql/031_multi_source_live_postings.sql").read_text()
    original = (
        "CREATE OR REPLACE FUNCTION catalog._live_source_observations()"
        + original.split("CREATE OR REPLACE FUNCTION catalog._live_source_observations()", 1)[
            1
        ].split("$$;", 1)[0]
        + "$$;"
    )
    # The crosswalk fixture's no-arg stub has the shorter return shape.
    connection.execute("DROP FUNCTION catalog._live_source_observations() CASCADE")
    connection.execute(sql.SQL(cast(LiteralString, original)))
    connection.execute("DROP FUNCTION catalog._live_source_observations(text[])")
    connection.execute(
        sql.SQL(
            cast(
                LiteralString,
                (ROOT / "hop/ontology/sql/036_crosswalk_reader_performance.sql").read_text(),
            )
        )
    )
    return connection


def observations(connection: Connection[Any], choices: list[str] | None) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], row[0])
        for row in connection.execute(
            "SELECT to_jsonb(p) FROM catalog._live_source_observations(%s) p ORDER BY source_id,posting_id",
            (choices,),
        ).fetchall()
    ]


def test_bounded_source_observations_equal_the_existing_projection(
    source_database: Connection[Any],
) -> None:
    original = [
        row[0]
        for row in source_database.execute(
            "SELECT to_jsonb(p) FROM catalog._live_source_observations() p ORDER BY source_id,posting_id"
        ).fetchall()
    ]
    assert observations(source_database, None) == original
    assert len(original) == 4
    assert [(p["source_id"], p["posting_id"]) for p in original] == [
        ("job_alio", "42"),
        ("jobkorea", "jobkorea:42"),
        ("jobkorea", "jobkorea:43"),
        ("nara_job", "nara_job:42"),
    ]
    for choices in (
        [],
        ["jobkorea:42"],
        ["jobkorea:43"],
        ["42"],
        ["nara_job:42"],
        ["nara_job:43"],
        ["jobkorea:44"],
        ["missing"],
        ["42", "jobkorea:42", "nara_job:42"],
        ["jobkorea:42", "jobkorea:42"],
    ):
        assert observations(source_database, choices) == [
            p for p in original if p["posting_id"] in choices
        ]
    assert observations(source_database, ["jobkorea:42"])[0]["normalized"]["title"] == "new"
    assert observations(source_database, ["jobkorea:43"])[0]["run_id"] == "jk-old"
    assert observations(source_database, ["nara_job:42"])[0]["normalized"]["nullable"] == "preserved"
    before = observations(source_database, None)
    source_database.execute(
        sql.SQL(
            cast(
                LiteralString,
                (ROOT / "hop/ontology/sql/036_crosswalk_reader_performance.sql").read_text(),
            )
        )
    )
    assert observations(source_database, None) == before
    assert source_database.execute("""
SELECT has_function_privilege('public','catalog._live_source_observations(text[])','EXECUTE')
""").fetchone() == (False,)


def test_bounded_source_observations_skip_unrequested_source_readers(
    source_database: Connection[Any],
) -> None:
    source_database.execute("SELECT setval('catalog.qa_alio_calls',1,false)")
    assert observations(source_database, ["jobkorea:42"])
    assert observations(source_database, ["nara_job:42"])
    assert observations(source_database, []) == []
    assert source_database.execute("SELECT is_called FROM catalog.qa_alio_calls").fetchone() == (False,)
    assert observations(source_database, ["42"])
    assert source_database.execute(
        "SELECT last_value,is_called FROM catalog.qa_alio_calls"
    ).fetchone() == (1, True)
