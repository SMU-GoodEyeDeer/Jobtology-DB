"""SQL reader projection fixtures; synthetic inference rows, no model/HTTP calls.

Use after run.boot(). The adapter is replaced inside a rolled-back transaction
so this tests current source pin comparisons without creating paid model history.
The original adapters are also executed with empty native histories to validate
all installed NCS references. The ONET branch remains optional on this fixture.
"""
# SQL fixtures keep source/hash literals explicit.
# ruff: noqa: E501
from __future__ import annotations

import json

import run
from live_feed import error, response


def check() -> None:
    assert response('SELECT catalog.inferred_occupation_context_v1()')['total'] == 0
    listing = dict(kind='JobPosting', posting_id='42', representation='local_listing',
                   metadata_accepted=True, title='개발', organization_name='기업',
                   deadline_kind='ROLLING', deadline_basis='USER_POLICY')
    run.load_sources({'jobkorea': [listing, listing | dict(posting_id='unrelated')]})
    pin = run.sql("SELECT encode(sha256(convert_to(normalized::text,'UTF8')),'hex') "
                  "FROM ingestion.record WHERE run_id='fixture-jobkorea' AND normalized->>'posting_id'='42'")
    original = run.sql("SELECT pg_get_functiondef('catalog._inferred_occupation_rows(text[])'::regprocedure)")
    # Test adapter emits known current, stale and unverifiable source pins.
    # It cannot modify a source or approve any competency evidence.
    definition = original[:original.index('AS $function$')].replace('LANGUAGE sql', 'LANGUAGE plpgsql')
    rows = []
    for key, code, source_pin, freshness in (
            ('current', '20010201', pin, 'CURRENT'),
            ('stale', '20010202', '0' * 64, 'STALE'),
            ('unknown', '20010203', None, 'CURRENT')):
        rows.append("SELECT 'jobkorea:42'::text,'source:posting:42'::text,'jobkorea'::text,"
                    "'fixture-jobkorea'::text,'NCS'::text," + run.q(code) + "::text,'occupation'::text,"
                    + run.q(key) + "::text,'UNREVIEWED'::text,'STAGING'::text,'UNASSESSED'::text,"
                    "'input-source-hash'::text," + ('NULL' if source_pin is None else run.q(source_pin))
                    + "::text,NULL::text,'ncs-run'::text,'catalog-hash'::text," + run.q(freshness) + '::text')
    # Each run.sql invocation has its own connection; use a single SQL transaction
    # for adapter replacement/readback, with rollback before returning the JSON.
    sql = ('BEGIN; '
           'CREATE OR REPLACE FUNCTION catalog._live_source_fact_hash(source text,value jsonb) '
           "RETURNS text LANGUAGE plpgsql AS $guard$ BEGIN RAISE EXCEPTION 'UNRELATED_ONET_HASH'; END $guard$; "
           + definition + 'AS $function$ BEGIN RETURN QUERY '
           + ' UNION ALL '.join(rows) + '; END $function$; '
           'SELECT catalog.inferred_occupation_context_v1(); ROLLBACK;')
    value = json.loads(run.sql(sql))
    assert value['total'] == 3 and value['summary']['postings'] == 1
    assert value['summary']['current_associations'] == 1
    assert value['summary']['by_source'] == [dict(source_id='jobkorea', postings=1,
                                                associations=3, source_current_associations=1,
                                                catalog_current_associations=2, current_associations=1)]
    assert [item['source_freshness'] for item in value['items']] == ['CURRENT', 'STALE', 'UNKNOWN']
    assert all(i['confidence'] is None and i['confidence_state'] == 'UNASSESSED'
               and i['basis'] == 'METADATA_INFERRED' and i['stage'] == 'STAGING'
               and i['review_status'] == 'UNREVIEWED' for i in value['items'])
    assert value['items'][0]['posting']['posting_id'] == 'jobkorea:42'
    assert value['items'][0]['posting']['title'] == '개발'
    assert value['summary']['source_current_associations'] == 1
    assert value['summary']['catalog_current_associations'] == 2
    assert value['summary']['by_occupation'][0]['occupation_code'] == '20010201'
    assert value['competency_evidence'] is False and 'evidence' not in value['items'][0]
    filtered = json.loads(run.sql(sql.replace('catalog.inferred_occupation_context_v1()',
                                              "catalog.inferred_occupation_context_v1(ARRAY['20010202'],1,0)")))
    assert filtered['total'] == 1 and filtered['items'][0]['occupation_code'] == '20010202'
    assert filtered['items'] == [value['items'][1]]
    assert filtered['summary']['by_occupation'] == [value['summary']['by_occupation'][1]]
    assert filtered['summary']['stale_associations'] == 1
    for query, expected in (
            ('SELECT catalog.inferred_occupation_context_v1(NULL,0)', 'INVALID_LIVE_PAGE'),
            ("SELECT catalog.inferred_occupation_context_v1(ARRAY['bad'])", 'INVALID_OCCUPATION_CONTEXT_FILTER'),
            ("SELECT catalog.inferred_occupation_context_v1(ARRAY[NULL])", 'INVALID_OCCUPATION_CONTEXT_FILTER')):
        error(query, expected)
    # Exercise the actual optional ONET reader SQL against native-shaped ledger
    # rows. This is a reader fixture, not a graph publication qualification.
    onet_payload = dict(task_id='test-task', occupation_name='Software Developers')
    onet_properties = dict(occupation_code='15-1252.00', release_id='test-release',
                           source_facts_sha256=pin, occupation_content_hash='target-hash',
                           review_status='ASSISTANT_REVIEWED', stage='STAGING',
                           confidence_state='UNASSESSED', catalog_hash='catalog-hash')
    onet_sql = """BEGIN;
CREATE SCHEMA onet_matching; CREATE SCHEMA classification;
CREATE TABLE onet_matching.graph_guard(publication_id text, database_id text, state text, finished_at timestamptz);
CREATE TABLE onet_matching.graph_edge(publication_id text, edge_id text, posting_identity text,
 occupation_identity text, properties jsonb, payload_json text);
CREATE TABLE onet_matching.input(task_id text, posting_identity text, source_id text, source_run_id text, source_facts jsonb);
CREATE TABLE classification.catalog_current(database_id text, release_id text, load_id text);
CREATE TABLE classification.graph_load_node(load_id text, node_id text, content_hash text);
CREATE OR REPLACE FUNCTION ingestion.source_graph_entity_facts(text,text,jsonb) RETURNS jsonb
 LANGUAGE plpgsql IMMUTABLE AS $facts$ BEGIN
 IF $3->>'posting_id'<>'42' THEN RAISE EXCEPTION 'UNRELATED_POSTING_HASH'; END IF;
 RETURN $3; END $facts$;
INSERT INTO onet_matching.graph_guard VALUES('pub','neo','VERIFIED',now());
INSERT INTO classification.catalog_current VALUES('neo','test-release','load');
INSERT INTO classification.graph_load_node VALUES('load','onet:15-1252.00','target-hash');
""" + ("INSERT INTO onet_matching.graph_edge VALUES('pub','edge','source:posting:42',"
        "'onet:15-1252.00'," + run.js(onet_properties) + ','
        + run.q(json.dumps(onet_payload)) + '); '
        "INSERT INTO onet_matching.input VALUES('test-task','source:posting:42','jobkorea',"
        "'fixture-jobkorea'," + run.js(listing) + '); ')
    # The actual adapter's filtered and unfiltered results must agree. An NCS
    # filter must skip ONET parsing, even if unrelated ONET evidence is malformed.
    onet_sql += ("SELECT catalog.inferred_occupation_context_v1(); "
                 "SELECT catalog.inferred_occupation_context_v1(ARRAY['15-1252.00']); "
                 "UPDATE classification.graph_load_node SET content_hash='changed'; "
                 "SELECT catalog.inferred_occupation_context_v1(ARRAY['15-1252.00']); "
                 "UPDATE onet_matching.graph_edge SET payload_json='malformed'; "
                 "SELECT catalog.inferred_occupation_context_v1(ARRAY['20010201']); "
                 "SELECT catalog.inferred_occupation_context_v1(ARRAY[]::text[]); ROLLBACK;")
    onet_all, onet_current, onet_stale, ncs_only, no_codes = [
        json.loads(line) for line in run.sql(onet_sql).splitlines()]
    assert onet_all['items'] == onet_current['items']
    assert onet_all['summary'] == onet_current['summary']
    assert ncs_only['total'] == 0 and no_codes['total'] == 0
    assert onet_current['total'] == 1 and onet_current['summary']['current_associations'] == 1
    assert onet_current['items'][0]['posting_key'] == 'jobkorea:42'
    assert onet_current['items'][0]['source_freshness'] == 'CURRENT'
    assert onet_current['items'][0]['review_status'] == 'ASSISTANT_REVIEWED'
    assert onet_stale['items'][0]['catalog_freshness'] == 'STALE'
    assert onet_stale['summary']['source_current_associations'] == 1
    assert onet_stale['summary']['current_associations'] == 0
    run.sql((run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text())
    assert response('SET ROLE jobtology_catalog_reader; '
                    'SELECT catalog.inferred_occupation_context_v1()')['items'] == []
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM catalog._inferred_occupation_rows()',
          'permission denied')
    before = response('SELECT catalog.inferred_occupation_context_v1()')
    run.sql('REVOKE EXECUTE ON FUNCTION catalog.inferred_occupation_context_v1(text[],integer,integer) '
            'FROM jobtology_catalog_reader')
    run.sql((run.ROOT / 'hop/ontology/sql/032_inferred_occupation_context.sql').read_text())
    run.sql((run.ROOT / 'hop/ontology/sql/033_posting_occupation_classifications.sql').read_text())
    run.sql((run.ROOT / 'hop/ontology/sql/035_ncs_catalog_revalidation.sql').read_text())
    assert response('SET ROLE jobtology_catalog_reader; '
                    'SELECT catalog.inferred_occupation_context_v1()') == before
    assert run.sql("SELECT has_function_privilege('jobtology_catalog_reader',"
                   "'catalog.live_postings_v1(text,text,text,date,integer,integer)','EXECUTE')") == 't'
    assert run.sql("SELECT pg_get_functiondef('catalog._inferred_occupation_rows(text[])'::regprocedure)") == original
    print('INFERRED OCCUPATION CONTEXT SQL PROJECTION CHECKS PASSED', flush=True)
