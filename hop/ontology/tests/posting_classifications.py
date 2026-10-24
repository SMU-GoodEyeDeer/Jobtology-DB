"""Synthetic source-vs-inferred posting classification contract checks.

Run after run.boot() against a disposable database. No source or provider calls.
"""
# SQL fixture literals retain full pinned evidence for review.
# ruff: noqa: E501
from __future__ import annotations

import json
import subprocess
import uuid

import run
from live_feed import error, response


def check() -> None:
    listing = dict(kind='JobPosting', representation='local_listing', metadata_accepted=True,
                   title='개발', organization_name='기업', regions='서울', deadline_kind='ROLLING',
                   deadline_basis='USER_POLICY')
    alio = dict(kind='JobPosting', posting_id='A', organization_name='기관', title='원문 분류 공고',
                ncs_category_codes='20010203', ncs_category_names='원문 분야',
                date_posted='2026-09-01', closing_date='2027-01-01')
    run.load_sources({'jobkorea': [listing | dict(posting_id=str(key)) for key in range(42, 48)],
                      'job_alio': [alio | dict(representation=part) for part in ('list', 'detail')],
                      'ncs_competency': run.fixture()['ncs_competency']})
    run.sql("INSERT INTO enrichment.metadata_occupation_catalog"
            "(ncs_run_id,occupation_code,occupation_name,classification_names,unit_names,search_text,catalog_hash) "
            "SELECT 'fixture-ncs_competency',code,'분류','[]','[]','분류','catalog-hash' "
            "FROM (VALUES('20010201'),('20010202'),('20010203')) codes(code)")
    pins = json.loads(run.sql("SELECT jsonb_object_agg(normalized->>'posting_id',"
                              "encode(sha256(convert_to(normalized::text,'UTF8')),'hex')) "
                              "FROM ingestion.record WHERE run_id='fixture-jobkorea'"))
    original = run.sql("SELECT pg_get_functiondef('catalog._inferred_occupation_rows(text[],text[])'::regprocedure)")
    definition = original[:original.index('AS $function$')]
    rows = []
    for key, code, normalized_hash, source_fact_hash, freshness, scheme, review in (
            ('42', '20010201', pins['42'], None, 'CURRENT', 'NCS', 'UNREVIEWED'),
            ('43', '20010201', pins['43'], None, 'STALE', 'NCS', 'UNREVIEWED'),
            ('44', '20010201', '0' * 64, None, 'CURRENT', 'NCS', 'UNREVIEWED'),
            ('45', '20010201', None, None, 'CURRENT', 'NCS', 'UNREVIEWED'),
            ('46', '20010202', pins['46'], None, 'CURRENT', 'NCS', 'HUMAN_REVIEWED'),
            ('46', '15-1252.00', None, pins['46'], 'CURRENT', 'ONET', 'ASSISTANT_REVIEWED'),
            ('missing', '20010201', '0' * 64, None, 'CURRENT', 'NCS', 'UNREVIEWED')):
        values = [f'jobkorea:{key}', f'source:posting:{key}', 'jobkorea', 'fixture-jobkorea',
                  scheme, code, '분류 ' + code, scheme + ':' + key, review, 'STAGING', 'UNASSESSED',
                  'original-source-hash', normalized_hash, source_fact_hash, 'original-catalog-pin',
                  'catalog-hash', freshness]
        rows.append('SELECT ' + ','.join(('NULL' if value is None else run.q(value)) + '::text' for value in values))
    # One adapter read for a normal page; category filtering permits one NCS-only
    # match batch and one page enrichment batch, regardless of page cardinality.
    adapter = definition + """AS $function$ BEGIN
IF nextval('qa_adapter_calls')>current_setting('qa.adapter_limit')::integer
 THEN RAISE EXCEPTION 'REPEATED_ADAPTER_SCAN'; END IF;
RETURN QUERY """ + ' UNION ALL '.join(rows) + '; END $function$; '
    setup = ('BEGIN; CREATE TEMP SEQUENCE qa_adapter_calls; '
             "CREATE OR REPLACE FUNCTION catalog._live_source_fact_hash(source text,value jsonb) "
             "RETURNS text LANGUAGE plpgsql AS $facts$ BEGIN "
             "IF value->>'posting_id'<>'46' THEN RAISE EXCEPTION 'UNRELATED_ONET_HASH'; END IF; "
             "RETURN encode(sha256(convert_to(value::text,'UTF8')),'hex'); END $facts$; " + adapter)

    def read(query: str, limit: int = 1):
        return json.loads(run.sql(setup + "DO $limit$ BEGIN PERFORM set_config('qa.adapter_limit',"
                                  + run.q(limit) + ",true); END $limit$; " + query + '; ROLLBACK;'))

    page = read('SELECT catalog.live_postings_v1()')
    assert page['total'] == 7
    assert page['filters']['ncs_match_scope'] == 'SOURCE_OR_CURRENT_INFERRED'
    items = {item['posting_id']: item for item in page['items']}
    assert items['jobkorea:42']['ncs_categories'] == []
    assert items['A']['ncs_categories'] == [dict(code='20010203', name='원문 분야')]
    assert items['A']['occupation_associations'] == []
    assert items['jobkorea:47']['occupation_associations'] == []
    inferred = items['jobkorea:42']['occupation_associations'][0]
    assert inferred['occupation_code'] == '20010201'
    assert inferred['review_status'] == 'UNREVIEWED' and inferred['stage'] == 'STAGING'
    assert inferred['basis'] == 'METADATA_INFERRED' and inferred['competency_evidence'] is False
    assert inferred['confidence'] is None and inferred['confidence_state'] == 'UNASSESSED'
    assert inferred['catalog_pins']['pin'] == 'original-catalog-pin'
    assert inferred['source_pins']['normalized_hash'] == pins['42']
    assert 'posting' not in inferred  # No recursive payloads.
    assert items['jobkorea:43']['occupation_associations'][0]['catalog_freshness'] == 'STALE'
    assert items['jobkorea:44']['occupation_associations'][0]['source_freshness'] == 'STALE'
    assert items['jobkorea:45']['occupation_associations'][0]['source_freshness'] == 'UNKNOWN'
    assert {a['review_status'] for a in items['jobkorea:46']['occupation_associations']} == {'HUMAN_REVIEWED', 'ASSISTANT_REVIEWED'}
    detail = read("SELECT catalog.live_posting_v1('jobkorea:42')")
    assert detail['item'] == items['jobkorea:42']
    prefix = read("SELECT catalog.live_postings_v1(NULL,'200102')", limit=2)
    assert prefix['total'] == 3
    assert [item['posting_id'] for item in prefix['items']] == ['jobkorea:42', 'jobkorea:46', 'A']
    exact = read("SELECT catalog.live_postings_v1(NULL,'20010201')", limit=2)
    assert exact['total'] == 1 and exact['items'][0] == items['jobkorea:42']
    source = read("SELECT catalog.live_postings_v1(NULL,'원문 분야')")
    assert source['total'] == 1 and source['items'][0] == items['A']
    second = read("SELECT catalog.live_postings_v1(NULL,'200102',NULL,NULL,1,1)", limit=2)
    assert second['total'] == 3 and second['items'] == [items['jobkorea:46']]
    assert read('SELECT catalog.live_postings_v1(NULL,NULL,NULL,NULL,20,100)')['items'] == []
    assert read("SELECT catalog.live_postings_v1('no match','200102')")['total'] == 0
    assert read("SELECT catalog.live_postings_v1(NULL,'99999999')")['total'] == 0
    assert read("SET ROLE jobtology_catalog_reader; SELECT catalog.live_posting_v1('jobkorea:42')")['item'] == items['jobkorea:42']
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM catalog._live_occupation_associations()', 'permission denied')
    error("SET ROLE jobtology_catalog_reader; SELECT catalog._live_ncs_filter_codes('200102')", 'permission denied')
    migration = (run.ROOT / 'hop/ontology/sql/033_posting_occupation_classifications.sql').read_text()
    before = response('SELECT catalog.live_postings_v1()')
    run.sql(migration)
    assert response('SELECT catalog.live_postings_v1()') == before
    assert run.sql("SELECT pg_get_functiondef('catalog._inferred_occupation_rows(text[],text[])'::regprocedure)") == original
    print('POSTING CLASSIFICATION SQL PROJECTION CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run.PG = 'jobtology-posting-classifications-test' + '-' + uuid.uuid4().hex[:12]
    try:
        run.boot()
        run.sql((run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text())
        check()
    finally:
        subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
