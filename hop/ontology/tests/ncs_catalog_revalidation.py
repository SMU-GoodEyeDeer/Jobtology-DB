"""Actual PostgreSQL full-catalog revalidation boundaries, using synthetic archives."""
# ruff: noqa: E501
from __future__ import annotations

import subprocess
import uuid

import run
from live_feed import error, response


def check() -> None:
    first, second = run.fixture()['ncs_competency'][1:]
    second = second | dict(code='2001020201_24v1', occupation_code='20010202', occupation_name='응용SW엔지니어링')
    units = [first, second]
    original = 'fixture-ncs_competency'
    current = 'qa-ncs-current'
    run.load_sources({'ncs_competency': units})
    response(f'SELECT enrichment.prepare_metadata_occupation_catalog({run.q(original)})')

    def clone(pin: str, created: str) -> None:
        run.sql("INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at) "
                f"VALUES({run.q(pin)},'ncs_competency','FULL','fixture','READY',{run.q(created)},{run.q(created)}); "
                "INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) "
                f"VALUES({run.q(pin)},'all','FILE',1); "
                "INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at) "
                f"SELECT {run.q(pin)},document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at "
                f"FROM ingestion.document WHERE run_id={run.q(original)}; "
                "INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) "
                f"SELECT {run.q(pin)},document_id,locator,source_record_id,source_payload,normalized "
                f"FROM ingestion.record WHERE run_id={run.q(original)}")

    clone(current, '2026-09-03T00:00:00Z')
    before = response(f'SELECT catalog._ncs_catalog_full_snapshot({run.q(original)})')
    after = response(f'SELECT catalog._ncs_catalog_full_snapshot({run.q(current)})')
    assert before['unit_count'] == after['unit_count'] == 2
    assert before['occupation_count'] == after['occupation_count'] == 2
    assert before['catalog_hash'] == after['catalog_hash']
    assert before['context_hash'] == after['context_hash']
    assert before['frozen_catalog_mismatches'] == before['frozen_context_mismatches'] == 0
    assert after['frozen_catalog_count'] == after['frozen_context_count'] == 0
    normal_hash = before['occupation_catalog_hashes']['20010201']
    qualifier_query = f"SELECT catalog._ncs_catalog_revalidation({run.q(original)},'20010201',{run.q(normal_hash)})"
    assert run.sql(qualifier_query) == ''
    operator = f'SELECT catalog.revalidate_ncs_catalog({run.q(original)},{run.q(current)})'
    proof = response(operator)
    assert proof['policy'] == 'FULL_CONTEXT_EQUAL_V1'
    assert proof['original_pin'] == original and proof['current_pin'] == current
    assert proof['proof']['review_status_changed'] is False and proof['proof']['paid_calls'] == 0
    assert proof['unit_count'] == proof['occupation_count'] == 2
    assert response(operator) == proof  # Replay preserves the original verification timestamp.
    qualifier = response(qualifier_query)
    assert qualifier == dict(original_pin=original, current_pin=current, policy='FULL_CONTEXT_EQUAL_V1',
                             context_hash=proof['context_hash'], verified_at=proof['verified_at'])
    assert run.sql(f"SELECT catalog._ncs_catalog_revalidation({run.q(original)},'20010201','wrong-hash')") == ''
    assert run.sql(f"SELECT catalog._ncs_catalog_revalidation({run.q(original)},'99999999',{run.q(normal_hash)})") == ''
    assert run.sql('SELECT count(*) FROM catalog.ncs_catalog_revalidation') == '1'

    # A matching target alone is insufficient: changes anywhere in the full
    # retrieval catalog invalidate a revalidation request, even on replay.
    for statement, expected in (
            ("UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{definition}','\"changed non-target definition\"') "
             f"WHERE run_id={run.q(current)} AND normalized->>'occupation_code'='20010202'", 'FULL_CONTEXT_CHANGED'),
            ("UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{classification_names}','[\"변경\",\"정보기술\",\"정보기술개발\"]') "
             f"WHERE run_id={run.q(current)} AND normalized->>'occupation_code'='20010202'", 'FULL_CONTEXT_CHANGED'),
            (f"DELETE FROM ingestion.record WHERE run_id={run.q(current)} AND normalized->>'occupation_code'='20010202'", 'FULL_CONTEXT_CHANGED'),
            ("INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) "
             f"SELECT {run.q(current)},document_id,'added','added',source_payload,normalized||"
             "'{\"code\":\"2001020301_24v1\",\"occupation_code\":\"20010203\"}'::jsonb "
             f"FROM ingestion.record WHERE run_id={run.q(current)} LIMIT 1", 'FULL_CONTEXT_CHANGED'),
            ("INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) "
             f"SELECT {run.q(current)},document_id,'duplicate','duplicate',source_payload,normalized "
             f"FROM ingestion.record WHERE run_id={run.q(current)} LIMIT 1", 'ARCHIVE_UNVERIFIABLE'),
            ("INSERT INTO enrichment.metadata_occupation_catalog(ncs_run_id,occupation_code,occupation_name,classification_names,unit_names,search_text,catalog_hash) "
             f"VALUES({run.q(original)},'99999999','unexpected','[]','[]','unexpected','wrong')", 'FROZEN_CONTEXT_UNVERIFIABLE')):
        error('BEGIN; ' + statement + '; ' + operator + '; ROLLBACK', 'NCS_REVALIDATION_' + expected)
    assert response(operator) == proof
    for statement in (
            "UPDATE catalog.ncs_catalog_revalidation SET policy='FULL_CONTEXT_EQUAL_V1'",
            'DELETE FROM catalog.ncs_catalog_revalidation', 'TRUNCATE catalog.ncs_catalog_revalidation'):
        error(statement, 'IMMUTABLE_NCS_CATALOG_REVALIDATION')
    error('SET ROLE jobtology_catalog_reader; ' + operator, 'permission denied')
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM catalog.ncs_catalog_revalidation', 'permission denied')
    error('SET ROLE jobtology_catalog_reader; ' + qualifier_query, 'permission denied')
    error(f'SET ROLE jobtology_catalog_reader; SELECT catalog._ncs_catalog_full_snapshot({run.q(original)})', 'permission denied')
    error(f'SELECT catalog.revalidate_ncs_catalog({run.q(original)},{run.q(original)})', 'INVALID_NCS_REVALIDATION_PINS')
    # A later pin does not inherit a previous verification, even with equal data.
    clone('qa-ncs-rollover', '2026-09-04T00:00:00Z')
    assert run.sql(qualifier_query) == ''
    error(operator, 'NCS_REVALIDATION_REQUIRES_EXACT_READY_PINS')
    rollover = response(f"SELECT catalog.revalidate_ncs_catalog({run.q(original)},'qa-ncs-rollover')")
    assert rollover['current_pin'] == 'qa-ncs-rollover'
    assert response(qualifier_query)['current_pin'] == 'qa-ncs-rollover'
    assert run.sql('SELECT count(*) FROM catalog.ncs_catalog_revalidation') == '2'
    migration = (run.ROOT / 'hop/ontology/sql/035_ncs_catalog_revalidation.sql').read_text()
    run.sql(migration)
    assert response(f"SELECT catalog.revalidate_ncs_catalog({run.q(original)},'qa-ncs-rollover')") == rollover
    # Optional LLM matching tables are not a prerequisite for installing the
    # ontology readers. Revalidation itself fails closed when they are absent.
    replay = migration.removeprefix('BEGIN;').removesuffix('COMMIT;\n')
    without_matching = 'BEGIN; DROP SCHEMA enrichment CASCADE; ' + replay
    assert run.sql(without_matching + 'SELECT true; ROLLBACK;') == 't'
    error(without_matching + f'SELECT catalog._ncs_catalog_full_snapshot({run.q(original)}); ROLLBACK;',
          'NCS_REVALIDATION_MATCHING_CATALOG_UNAVAILABLE')
    print('FULL NCS CATALOG REVALIDATION CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run.PG = 'jobtology-ncs-revalidation-test' + '-' + uuid.uuid4().hex[:12]
    try:
        run.boot()
        run.sql((run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text())
        check()
    finally:
        subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
