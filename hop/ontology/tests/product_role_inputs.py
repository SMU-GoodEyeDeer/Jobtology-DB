#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run: uv run hop/ontology/tests/product_role_inputs.py
# ──────────────────
from __future__ import annotations

import json
import subprocess
import uuid

import live_ncs_demand
import run


def response(query: str) -> dict:
    return json.loads(run.sql(query))


def error(query: str, message: str) -> None:
    try:
        run.sql(query)
    except RuntimeError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError(f'Expected {message}')


def check() -> None:
    live_ncs_demand.seed()
    for locator, item in enumerate([
        dict(kind='Competency', code='2001020101_20v1', name='데이터베이스 설계 구버전',
             level=3, occupation_code='20010201', occupation_name='정보기술개발'),
        dict(kind='Competency', code='2001020201_24v1', name='서버프로그램 구현',
             level=5, occupation_code='20010202', occupation_name='응용SW개발'),
        dict(kind='Competency', code='2001020103_24v1', name='네트워크 운영',
             level=5, occupation_code='20010201', occupation_name='정보기술개발'),
    ], start=100):
        value = run.js(item)
        run.sql('INSERT INTO ingestion.record'
                '(run_id,document_id,locator,source_record_id,source_payload,normalized) '
                f"VALUES('fixture-ncs_competency','doc',{run.q(str(locator))},"
                f'{run.q(item["code"])},{value},{value})')
    qual = dict(kind='QualificationMapping', competency_code='2001020101_24v1',
                qualification_code='T5H1', qualification_name='정보기술 고급',
                minimum_training_hours=40, total_training_hours=410)
    value = run.js(qual)
    run.sql('INSERT INTO ingestion.record'
            '(run_id,document_id,locator,source_record_id,source_payload,normalized) '
            f"VALUES('fixture-ncs_qualification','doc','101','T5H1',{value},{value})")
    nara_payload = dict(source_id='nara_job', source_posting_id='400', name='망 운영',
                        links=[dict(competency_code='2001020103_24v1',
                                    reviewer_kind='human', duty={'text': '운영'})])
    value = run.js(nara_payload)
    run.sql('INSERT INTO enrichment.link_publication_item'
            '(publication_id,posting_id,enrichment_id,posting_identity,name,payload,payload_hash) '
            f"VALUES('nara','N2','reviewed:fixture','nara:N2','망 운영',{value},"
            f'enrichment.hash(({value})::text))')

    # Given: READY competency/qualification snapshots and two selected reviewed publications.
    # When: inputs for a requested eight-digit occupation code are read.
    inputs = response("SELECT catalog.product_role_inputs_v1(ARRAY['20010201'])")
    # Then: every version and exact mapping appears, without private review data.
    assert set(inputs) == {'contract_version', 'sources', 'units', 'qualifications', 'evidence',
                           'linked_postings'}
    assert inputs['contract_version'] == 'jobtology-product-role-inputs-v1'
    assert inputs['sources'] == [
        {'source_id': 'ncs_competency', 'run_id': 'fixture-ncs_competency',
         'data_as_of': '2026-09-01T00:01:00+00:00'},
        {'source_id': 'ncs_qualification', 'run_id': 'fixture-ncs_qualification',
         'data_as_of': '2026-09-01T00:01:00+00:00'},
        {'source_id': 'link_publication', 'publication_id': 'job',
         'created_at': '2026-09-02T00:00:00+00:00', 'posting_source': 'job_alio',
         'run_id': 'fixture-job_alio', 'is_latest_publication': True},
        {'source_id': 'link_publication', 'publication_id': 'nara',
         'created_at': '2026-09-03T00:00:00+00:00', 'posting_source': 'nara_job',
         'run_id': 'fixture-nara_job', 'is_latest_publication': True},
    ]
    assert [u['code'] for u in inputs['units']] == ['2001020101_20v1',
                                                     '2001020101_24v1',
                                                     '2001020102_24v1',
                                                     '2001020103_24v1']
    assert inputs['units'][0] == {
        'code': '2001020101_20v1', 'base_code': '2001020101',
        'name': '데이터베이스 설계 구버전', 'level': 3,
        'occupation_code': '20010201', 'occupation_name': '정보기술개발'}
    assert inputs['qualifications'] == [
        {'competency_code': '2001020101_24v1', 'qualification_code': 'T5H0',
         'qualification_name': '정보기술 자격', 'minimum_training_hours': None,
         'total_training_hours': None},
        {'competency_code': '2001020101_24v1', 'qualification_code': 'T5H1',
         'qualification_name': '정보기술 고급', 'minimum_training_hours': 40,
         'total_training_hours': 410},
    ]
    assert inputs['evidence'] == [
        {'competency_code': '2001020101_24v1', 'postings': 2, 'links': 4,
         'publication_ids': ['job', 'nara']},
        {'competency_code': '2001020102_24v1', 'postings': 1, 'links': 1,
         'publication_ids': ['job']},
        {'competency_code': '2001020103_24v1', 'postings': 1, 'links': 1,
         'publication_ids': ['nara']},
    ]
    # Then: each attributable posting appears once per source with its distinct codes,
    # so the BE can derive a duplicate-free demand denominator per role.
    assert inputs['linked_postings'] == [
        {'posting_key': 'job_alio:P1', 'competency_codes': ['2001020101_24v1']},
        {'posting_key': 'job_alio:P2', 'competency_codes': ['2001020102_24v1']},
        {'posting_key': 'nara_job:N2', 'competency_codes': ['2001020103_24v1']},
        {'posting_key': 'nara_job:P1', 'competency_codes': ['2001020101_24v1']},
    ]
    assert not any(secret in json.dumps(inputs, ensure_ascii=False)
                   for secret in ('PRIVATE', 'reviewer', 'decision_id', 'reason', 'notes',
                                  'stale', 'failure'))
    other = response("SELECT catalog.product_role_inputs_v1(ARRAY['20010202'])")
    assert [unit['code'] for unit in other['units']] == ['2001020201_24v1']
    assert other['evidence'] == [] and other['qualifications'] == []
    assert other['linked_postings'] == []
    assert response("SELECT catalog.product_role_inputs_v1(ARRAY['20010201','20010201'])") == inputs
    for query in ('SELECT catalog.product_role_inputs_v1(NULL)',
                  "SELECT catalog.product_role_inputs_v1(ARRAY[]::text[])",
                  "SELECT catalog.product_role_inputs_v1(ARRAY['2001020'])",
                  "SELECT catalog.product_role_inputs_v1(ARRAY['20010201',NULL])",
                  "SELECT catalog.product_role_inputs_v1(ARRAY['2001020x'])"):
        error(query, 'INVALID_PRODUCT_ROLE_INPUT')

    grants = (run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text()
    run.sql(grants)
    assert response('SET ROLE jobtology_catalog_reader; '
                    "SELECT catalog.product_role_inputs_v1(ARRAY['20010201'])") == inputs
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM ingestion.competency',
          'permission denied')
    # Given: a newer READY job publication with a verified pin but no rows.
    live_ncs_demand.seed_newer_empty_source_pin_does_not_mask_historical_evidence()
    # When: product-role inputs are read after the empty publication.
    newest = response("SELECT catalog.product_role_inputs_v1(ARRAY['20010201'])")
    # Then: the empty pin does not mask attributable earlier evidence.
    assert [source['publication_id'] for source in newest['sources'][2:]] == ['job', 'nara']
    assert newest['evidence'] == inputs['evidence']
    live_ncs_demand.seed_legacy_and_newer_nara()
    historical = response("SELECT catalog.product_role_inputs_v1(ARRAY['20010201'])")
    assert [source['publication_id'] for source in historical['sources'][2:]] == [
        'legacy-job', 'newer-nara']
    assert historical['evidence'] == [
        {'competency_code': '2001020101_24v1', 'postings': 1, 'links': 1,
         'publication_ids': ['newer-nara']},
        {'competency_code': '2001020102_24v1', 'postings': 1, 'links': 1,
         'publication_ids': ['legacy-job']},
    ]
    assert historical['linked_postings'] == [
        {'posting_key': 'job_alio:L1', 'competency_codes': ['2001020102_24v1']},
        {'posting_key': 'nara_job:N3', 'competency_codes': ['2001020101_24v1']},
    ]
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE run_id='fixture-ncs_qualification'")
    optional = response("SELECT catalog.product_role_inputs_v1(ARRAY['20010201'])")
    assert len(optional['sources']) == 3 and optional['qualifications'] == []
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE run_id='fixture-ncs_competency'")
    error("SELECT catalog.product_role_inputs_v1(ARRAY['20010201'])", 'LIVE_SOURCE_UNAVAILABLE')


if __name__ == '__main__':
    run.PG = f'jobtology-role-input-test-{uuid.uuid4().hex[:12]}'
    try:
        run.boot()
        check()
        print('PRODUCT ROLE INPUT CHECKS PASSED', flush=True)
    finally:
        subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
