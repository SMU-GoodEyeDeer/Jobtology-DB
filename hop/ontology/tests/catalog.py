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
    sql((ROOT / 'hop/ontology/sql/024_sealed_catalog.sql').read_text())
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
    expect_error("SET ROLE jobtology_catalog_reader; SELECT catalog._context('catalog-fixture')",
                 'permission denied')
    expect_error("SET ROLE jobtology_catalog_reader; SELECT catalog._source_inventory('catalog-fixture')",
                 'permission denied')
    expect_error("SET ROLE jobtology_catalog_reader; SELECT catalog.approve_catalog_release('catalog-fixture','fixture-neo','x','y')", 'permission denied')
    expect_error('SET ROLE jobtology_catalog_reader; SELECT * FROM catalog.catalog_active_release', 'permission denied')

    assert sql("SELECT generation=1 AND contract_version='hop-catalog-source-v1' "
               "AND node_count>0 AND edge_count>0 AND length(membership_hash)=64 "
               "FROM catalog.integrity_attestation WHERE release_id='catalog-fixture'") == 't'
    for table in ('source_pin', 'release_source_run', 'input_record', 'release_revision',
                  'revision_support', 'release_relation', 'observation_freeze',
                  'observation_history_member', 'posting_observation',
                  'observation_membership', 'entity_observation_state', 'graph_node',
                  'graph_edge', 'catalog_source_mode'):
        if table not in ('graph_node', 'graph_edge'):
            expect_error(f"INSERT INTO ontology.{table} SELECT * FROM ontology.{table} "
                         "WHERE release_id='catalog-fixture' ON CONFLICT DO NOTHING",
                         'SEALED_CATALOG_WRITE_FENCE')
        expect_error(f'TRUNCATE ontology.{table} CASCADE', 'SEALED_CATALOG_TRUNCATE_FENCE')
    expect_error("INSERT INTO ontology.graph_node SELECT release_id,'forbidden-node',labels,"
                 "properties,content_hash FROM ontology.graph_node WHERE release_id='catalog-fixture' LIMIT 1",
                 'SEALED_CATALOG_WRITE_FENCE')
    expect_error("INSERT INTO ontology.graph_edge SELECT release_id,'forbidden-edge',subject_id,"
                 "predicate,object_id,properties,content_hash FROM ontology.graph_edge "
                 "WHERE release_id='catalog-fixture' LIMIT 1", 'SEALED_CATALOG_WRITE_FENCE')
    sql("INSERT INTO ontology.graph_node SELECT * FROM ontology.graph_node "
        "WHERE release_id='catalog-fixture' ON CONFLICT DO NOTHING")
    for table, predicate in (('run', "run_id='fixture-job_alio'"),
                             ('partition', "run_id='fixture-job_alio'"),
                             ('document', "run_id='fixture-job_alio'"),
                             ('record', "run_id='fixture-job_alio'")):
        override = 'OVERRIDING SYSTEM VALUE' if table == 'record' else ''
        expect_error(f"INSERT INTO ingestion.{table} {override} SELECT * FROM ingestion.{table} "
                     f'WHERE {predicate} ON CONFLICT DO NOTHING', 'SEALED_CATALOG_WRITE_FENCE')
        expect_error(f'TRUNCATE ingestion.{table} CASCADE', 'SEALED_CATALOG_TRUNCATE_FENCE')
    expect_error("UPDATE ingestion.record SET normalized='{}'::jsonb "
                 "WHERE run_id='fixture-ncs_career_path'", 'SEALED_CATALOG_WRITE_FENCE')
    expect_error("DELETE FROM ingestion.document WHERE run_id='fixture-job_alio'",
                 'SEALED_CATALOG_WRITE_FENCE')
    expect_error("UPDATE ontology.corpus_release SET manifest_hash=repeat('a',64) "
                 "WHERE release_id='catalog-fixture'", 'SEALED_CATALOG_RELEASE_IMMUTABLE')
    expect_error("UPDATE ontology.corpus_release SET created_at=created_at+interval '1 second' "
                 "WHERE release_id='catalog-fixture'", 'SEALED_CATALOG_RELEASE_IMMUTABLE')
    expect_error('SET ROLE jobtology_catalog_reader; SELECT * FROM catalog.integrity_attestation',
                 'permission denied')
    expect_error("SET ROLE jobtology_catalog_reader; INSERT INTO catalog.catalog_active_release "
                 "VALUES(true,1)", 'permission denied')
    expect_error("SET ROLE jobtology_catalog_reader; ALTER TABLE ontology.graph_node DISABLE TRIGGER USER",
                 'permission denied')
    assert json.loads(sql("BEGIN READ ONLY; SET ROLE jobtology_catalog_reader; "
                          "SELECT catalog.catalog_context_v1(); COMMIT"))['release_id'] == 'catalog-fixture'
    sql("INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at) "
        "VALUES('unrelated-future','job_alio','FULL','fixture','READY',now(),now())")
    choices = json.dumps({source: 'fixture-' + source for source in fixture()})
    sql("SELECT ontology.prepare_release('catalog-next', '" + choices + "'::jsonb); "
        "SELECT ontology.assemble_sources('catalog-next')")
    assert sql("SELECT count(*) FROM ontology.release_revision WHERE release_id='catalog-next'") != '0'
    assert json.loads(sql('SELECT catalog.catalog_context_v1()'))['release_id'] == 'catalog-fixture'
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
