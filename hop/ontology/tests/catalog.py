# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# Run: uv run hop/ontology/tests/catalog.py (disposable Docker PostgreSQL only).
import json
import os
import subprocess

from run import PG, ROOT, boot, cmd, expect_error, fixture, load_sources, sql


def check() -> None:
    load_sources(fixture())
    sql("SELECT ontology.capture_posting_census_v1('fixture-job_alio')")
    sql("SELECT ontology.prepare_release('catalog-fixture'); SELECT ontology.assemble_sources('catalog-fixture')")
    sql("SELECT ontology.bind_observations_v1('catalog-fixture')")
    expect_error("SELECT ontology.seal_graph('catalog-fixture')", 'FREEZE_REVIEWS_FIRST')
    sql("SELECT ontology.prepare_catalog_source_v1('catalog-fixture')")
    expect_error(
        "SELECT catalog.approve_catalog_release('catalog-fixture','fixture-neo','operator','source-only')",
        'CATALOG_RELEASE_NOT_VERIFIED',
    )
    sql("SELECT ontology.seal_catalog_source_v1('catalog-fixture')")
    manifest = json.loads(sql("SELECT manifest FROM ontology.corpus_release WHERE release_id='catalog-fixture'"))
    sql("""INSERT INTO ontology.graph_load(load_id,release_id,database_id,manifest_hash,state,
        finished_at,node_count,edge_count) SELECT 'fixture-load','catalog-fixture','fixture-neo',manifest_hash,
        'VERIFIED',clock_timestamp(),(manifest->>'nodes')::bigint,(manifest->>'edges')::bigint
        FROM ontology.corpus_release WHERE release_id='catalog-fixture';
        UPDATE ontology.corpus_release SET graph_verified_at=clock_timestamp() WHERE release_id='catalog-fixture'""")
    approval = sql("SELECT catalog.approve_catalog_release('catalog-fixture','fixture-neo','operator','source-only')")
    assert approval == sql("SELECT catalog.approve_catalog_release('catalog-fixture','fixture-neo','operator','retry')")
    cmd(['docker', 'exec', '-i', PG, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
         '-v', 'release_id=catalog-fixture', '-v', 'database_id=fixture-neo',
         '-v', 'actor=operator', '-v', 'reason=replay', '-U', 'postgres', '-d', 'ontologytest'],
        input=(ROOT / 'hop/ontology/catalog_approve.psql').read_text())
    sql((ROOT / 'hop/ontology/sql/019_catalog_approval.sql').read_text())
    assert approval == sql('SELECT approval_id FROM catalog.catalog_active_release')
    assert sql("SELECT count(*) FROM catalog.catalog_approval") == '1'
    assert sql("SELECT count(*) FROM ontology.active_release") == '0'
    expect_error("SELECT ontology.query_summary_v1()", 'NO_ACTIVE_ONTOLOGY_RELEASE')
    expect_error("SELECT ontology.activate_release('catalog-fixture','fixture','not ready')", 'RELEASE_NOT_READY_FOR_ACTIVATION')
    context = json.loads(sql('SELECT catalog.catalog_context_v1()'))
    assert context['release_id'] == 'catalog-fixture'
    assert context['manifest_hash'] and context['data_as_of']
    assert context['source_profile'] == {'kind': 'SOURCE_ONLY', 'analysis_available': False,
                                         'capabilities': ['entities', 'source_relations']}
    page = json.loads(sql("SELECT catalog.catalog_entities_v1(NULL,'jobPosting',1,0)"))
    assert len(page['items']) == 1 and page['items'][0]['kind'] == 'jobPosting'
    entity = json.loads(sql("SELECT catalog.catalog_entity_v1(NULL,'urn:jobtology:jobPosting:job_alio:001')"))
    assert 'eligibility_text' not in entity['entity']['source_facts']
    assert 'review' not in entity and 'claims' not in entity
    relations = json.loads(sql("SELECT catalog.catalog_relations_v1(NULL,'urn:jobtology:jobPosting:job_alio:001')"))
    assert any(item['predicate'] == 'POSTED_BY' for item in relations['items'])
    assert all(item['assertion_kind'] == 'SOURCE_FACT' for item in relations['items'])
    summary = json.loads(sql('SELECT catalog.catalog_summary_v1()'))
    assert summary['posting_selection_outcomes']['SELECTION_PENDING'] == 1
    assert manifest['mode'] == 'SOURCE_ONLY'
    assert sql("SELECT count(*) FROM ontology.review_freeze WHERE release_id='catalog-fixture'") == '0'
    assert manifest['nodes'] > 0 and manifest['edges'] > 0
    expect_error("SELECT catalog.catalog_entities_v1(NULL,'skill')", 'INVALID_CATALOG_ENTITY_KIND')
    expect_error("SELECT catalog.catalog_entities_v1(NULL,NULL,101,0)", 'INVALID_CATALOG_PAGE')
    expect_error("SELECT catalog.catalog_entities_v1(NULL,NULL,1,-1)", 'INVALID_CATALOG_PAGE')
    expect_error("SELECT catalog.catalog_context_v1('other')", 'CATALOG_RELEASE_NOT_APPROVED')

    sql((ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text())
    assert json.loads(sql("SET ROLE jobtology_catalog_reader; SELECT catalog.catalog_summary_v1()"))['release_id'] == 'catalog-fixture'
    expect_error('SET ROLE jobtology_catalog_reader; SELECT * FROM ontology.revision', 'permission denied')
    expect_error('SET ROLE jobtology_catalog_reader; SELECT ontology.query_entity_v1(NULL,NULL,true)', 'permission denied')
    expect_error('SET ROLE jobtology_catalog_reader; SELECT catalog._approved_release()', 'permission denied')
    expect_error("SET ROLE jobtology_catalog_reader; SELECT catalog.approve_catalog_release('catalog-fixture','fixture-neo','x','y')", 'permission denied')
    expect_error('SET ROLE jobtology_catalog_reader; SELECT * FROM catalog.catalog_active_release', 'permission denied')

    expect_error("BEGIN; ALTER TABLE ontology.graph_node DISABLE TRIGGER USER; "
                 "UPDATE ontology.graph_node SET content_hash='drift' WHERE release_id='catalog-fixture'; "
                 "SELECT catalog.catalog_context_v1(); COMMIT", 'CATALOG_APPROVAL_STALE')
    expect_error("BEGIN; UPDATE ingestion.record SET normalized='{}'::jsonb "
                 "WHERE run_id='fixture-ncs_career_path'; SELECT catalog.catalog_context_v1(); COMMIT",
                 'PINNED_SOURCE_CHANGED')
    sql("INSERT INTO ontology.graph_load(load_id,release_id,database_id,manifest_hash,state) "
        "SELECT 'reload-running','catalog-fixture','fixture-neo',manifest_hash,'RUNNING' "
        "FROM ontology.corpus_release WHERE release_id='catalog-fixture'")
    expect_error('SELECT catalog.catalog_context_v1()', 'CATALOG_APPROVAL_STALE')
    sql("UPDATE ontology.graph_load SET state='FAILED',finished_at=clock_timestamp() WHERE load_id='reload-running'")
    expect_error('SELECT catalog.catalog_context_v1()', 'CATALOG_APPROVAL_STALE')
    expect_error("SELECT catalog.approve_catalog_release('catalog-fixture','fixture-neo','x','y')", 'CATALOG_GRAPH_LOAD_NOT_VERIFIED')
    expect_error("BEGIN; UPDATE ontology.corpus_release SET state='FAILED' WHERE release_id='catalog-fixture'; "
                 "SELECT catalog.catalog_context_v1(); COMMIT", 'CATALOG_RELEASE_UNAVAILABLE')
    sql("UPDATE ontology.corpus_release SET state='REVOKED',revoked_at=clock_timestamp() WHERE release_id='catalog-fixture'")
    expect_error('SELECT catalog.catalog_context_v1()', 'CATALOG_RELEASE_UNAVAILABLE')
    expect_error("SELECT catalog.approve_catalog_release('catalog-fixture','fixture-neo','x','y')", 'CATALOG_RELEASE_NOT_VERIFIED')
    print('CATALOG CONTRACT CHECKS PASSED', flush=True)


if __name__ == '__main__':
    try:
        boot()
        check()
    finally:
        if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):
            subprocess.run(['docker', 'rm', '-fv', PG], capture_output=True, check=False)
