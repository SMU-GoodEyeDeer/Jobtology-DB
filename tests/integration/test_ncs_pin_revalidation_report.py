"""Opt-in synthetic PostgreSQL checks; creates and drops its own unique test DB."""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ncs_pin_report_integration", ROOT / "hop/operations/report_ncs_pin_revalidation.py"
)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)
CODE = "20010201"


@pytest.fixture
def database():
    dsn = os.environ.get("JOBTOLOGY_NCS_REPORT_TEST_ADMIN_DSN")
    if not dsn:
        pytest.skip("Set JOBTOLOGY_NCS_REPORT_TEST_ADMIN_DSN to a disposable local PG17+ server")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    settings = conninfo_to_dict(dsn)
    if settings.get("host") not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail("This fixture requires an explicitly supplied loopback disposable server")
    name = "ncs_pin_report_" + uuid.uuid4().hex + "_test"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            test_dsn = make_conninfo(dsn, dbname=name)
            with psycopg.connect(test_dsn, autocommit=True) as connection:
                connection.execute("""
CREATE SCHEMA ingestion; CREATE SCHEMA enrichment; CREATE SCHEMA catalog;
CREATE TABLE ingestion.run(run_id text PRIMARY KEY,source_id text,state text,mode text);
INSERT INTO ingestion.run VALUES
 ('old','ncs_competency','READY','FULL'),('current','ncs_competency','READY','FULL');
CREATE VIEW ingestion.latest_ready_run AS SELECT * FROM ingestion.run WHERE run_id='current';
CREATE TABLE ingestion.ready_record(run_id text,source_id text,normalized jsonb);
CREATE FUNCTION enrichment.hash(v text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS
 $$ SELECT encode(sha256(convert_to(v,'UTF8')),'hex') $$;
CREATE TABLE enrichment.metadata_occupation_catalog(
 ncs_run_id text,occupation_code text,catalog_hash text,PRIMARY KEY(ncs_run_id,occupation_code));
CREATE TABLE catalog.fixture_associations(
 occupation_scheme text,catalog_pin text,occupation_code text,catalog_hash text);
CREATE FUNCTION catalog._inferred_occupation_rows(codes text[]) RETURNS SETOF
 catalog.fixture_associations LANGUAGE sql STABLE AS
 $$ SELECT * FROM catalog.fixture_associations WHERE occupation_code=ANY(codes) $$;
INSERT INTO ingestion.ready_record SELECT pin,'ncs_competency',jsonb_build_object(
 'occupation_code','20010201','occupation_name','소프트웨어','code',code,
 'name','단위','definition','정의','classification_names',jsonb_build_array('대','중','소'))
 FROM unnest(ARRAY['old','current']) pin CROSS JOIN unnest(ARRAY['unit-b','unit-a']) code;
INSERT INTO enrichment.metadata_occupation_catalog
 SELECT 'old','20010201',enrichment.hash(jsonb_agg(normalized ORDER BY normalized->>'code')::text)
 FROM ingestion.ready_record WHERE run_id='old';
INSERT INTO catalog.fixture_associations
 SELECT 'NCS','old',occupation_code,catalog_hash
 FROM enrichment.metadata_occupation_catalog CROSS JOIN generate_series(1,3);
""")
                yield connection, test_dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def read(database):
    _, dsn = database
    value = report.capture(dsn, "current", [CODE])
    return report.build_report(value, "current", [CODE])


def without_observation_time(value):
    return {key: item for key, item in value.items() if key != "observed_at"}


def test_real_postgres_hash_order_change_missing_and_frozen_drift(database):
    connection, _ = database
    initial = read(database)
    assert initial["rows"][0]["status"] == "PIN_CHANGED_CONTENT_EQUAL"
    assert initial["counts"]["backend_associations"]["PIN_CHANGED_CONTENT_EQUAL"] == 3
    assert datetime.fromisoformat(initial["observed_at"]).utcoffset() is not None
    assert initial["observation_basis"] == (
        "Database transaction timestamp; not source collection time"
    )
    assert without_observation_time(read(database)) == without_observation_time(initial)
    # Physical insertion order differs; the historical SQL formula still agrees.
    connection.execute("""
WITH removed AS (DELETE FROM ingestion.ready_record WHERE run_id='current' RETURNING *)
INSERT INTO ingestion.ready_record SELECT * FROM removed ORDER BY normalized->>'code' DESC
""")
    assert without_observation_time(read(database)) == without_observation_time(initial)
    connection.execute("""UPDATE ingestion.ready_record SET normalized=jsonb_set(
 normalized,'{definition}','"changed"') WHERE run_id='current'""")
    assert read(database)["rows"][0]["status"] == "TARGET_CHANGED"
    # A complete current archive containing another target proves scoped absence.
    connection.execute("""UPDATE ingestion.ready_record SET normalized=jsonb_set(
 normalized,'{occupation_code}','"20010202"') WHERE run_id='current'""")
    assert read(database)["rows"][0]["status"] == "TARGET_MISSING"
    connection.execute("UPDATE enrichment.metadata_occupation_catalog SET catalog_hash='wrong'")
    assert read(database)["rows"][0]["status"] == "UNVERIFIABLE"


@pytest.mark.parametrize("mutation", [
    "UPDATE ingestion.ready_record SET normalized=normalized-'classification_names' "
    "WHERE run_id='current' AND normalized->>'code'='unit-b'",
    "UPDATE ingestion.ready_record SET normalized=jsonb_set(normalized,"
    "'{classification_names}','[\"a\",null,\"c\"]') WHERE run_id='current'",
    "UPDATE ingestion.ready_record SET normalized=jsonb_set(normalized,"
    "'{classification_names}','\"scalar\"') WHERE run_id='current'",
    "UPDATE ingestion.ready_record SET normalized=jsonb_set(normalized,"
    "'{classification_names}','[\"other\",\"b\",\"c\"]') "
    "WHERE run_id='current' AND normalized->>'code'='unit-b'",
    "INSERT INTO ingestion.ready_record SELECT * FROM ingestion.ready_record "
    "WHERE run_id='current' LIMIT 1",
    "DELETE FROM ingestion.ready_record WHERE run_id='old'",
    "UPDATE catalog.fixture_associations SET catalog_hash='v2-context-hash'",
])
def test_real_postgres_ambiguous_archive_is_unverifiable(database, mutation):
    connection, _ = database
    connection.execute(mutation)
    assert read(database)["rows"][0]["status"] == "UNVERIFIABLE"


def test_database_read_only_guard_rejects_a_writing_reader(database):
    connection, dsn = database
    connection.execute("""
CREATE OR REPLACE FUNCTION catalog._inferred_occupation_rows(codes text[]) RETURNS SETOF
 catalog.fixture_associations LANGUAGE plpgsql VOLATILE AS $$ BEGIN
 INSERT INTO catalog.fixture_associations SELECT * FROM catalog.fixture_associations LIMIT 1;
 RETURN QUERY SELECT * FROM catalog.fixture_associations WHERE occupation_code=ANY(codes);
END $$
""")
    import psycopg

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        report.capture(dsn, "current", [CODE])
    count = connection.execute("SELECT count(*) FROM catalog.fixture_associations").fetchone()[0]
    assert count == 3
