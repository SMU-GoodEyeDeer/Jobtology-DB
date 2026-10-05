#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run: uv run hop/ontology/tests/live_ncs_demand.py
# ──────────────────
from __future__ import annotations

import json
import subprocess
import uuid

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


def seed() -> None:
    units = [dict(kind='Competency', code=code, name=name, level=4,
                  occupation_code='20010201', occupation_name='정보기술개발')
             for code, name in [('2001020101_24v1', '데이터베이스 설계'),
                                ('2001020102_24v1', '데이터베이스 구축')]]
    run.load_sources({'job_alio': [], 'nara_job': [], 'ncs_competency': units,
                      'ncs_qualification': [
                          dict(kind='QualificationMapping', competency_code='2001020101_24v1',
                               qualification_code='T5H0', qualification_name='정보기술 자격')]})
    for publication_id, source, state, created in [
        ('old', 'job_alio', 'READY', '2026-08-01'),
        ('job', 'job_alio', 'READY', '2026-09-02'),
        ('nara', 'nara_job', 'READY', '2026-09-03'),
        ('failed', 'job_alio', 'FAILED', '2026-09-04'),
    ]:
        run.sql('INSERT INTO enrichment.link_publication'
                '(publication_id,source_hash,job_run_id,ncs_run_id,state,created_at) VALUES('
                f'{run.q(publication_id)},repeat(\'a\',64),'
                f'{run.q("fixture-" + source)},\'fixture-ncs_competency\','
                f'{run.q(state)},{run.q(created)})')
        for lineage in (('job_alio', 'nara_job') if publication_id == 'job' else (source,)):
            run.sql('INSERT INTO enrichment.link_publication_source_run'
                    '(publication_id,source_id,run_id) VALUES('
                    f'{run.q(publication_id)},{run.q(lineage)},'
                    f'{run.q("fixture-" + lineage)})')

    def add(publication: str, posting: str, source: str, source_posting: str,
            title: str, links: list[dict]) -> None:
        payload = dict(source_id=source, source_posting_id=source_posting, name=title,
                       extraction_reviewer='PRIVATE', links=links)
        if publication == 'job':
            payload.pop('source_id')
        value = run.js(payload)
        identity = ('job-alio:posting:' if source == 'job_alio'
                    else 'source:posting:nara_job:') + source_posting
        run.sql('INSERT INTO enrichment.link_publication_item'
                '(publication_id,posting_id,enrichment_id,posting_identity,name,payload,'
                'payload_hash) '
                f'VALUES({run.q(publication)},{run.q(posting)},\'reviewed:fixture\','
                f'{run.q(identity)},{run.q(title)},{value},'
                f'enrichment.hash(({value})::text))')

    def link(code: str, kind: str, duty: str) -> dict:
        return dict(competency_code=code, reviewer_kind=kind,
                    reviewer='PRIVATE', review_notes='PRIVATE', reason='PRIVATE',
                    decision_id='PRIVATE', candidate_id='PRIVATE',
                    duty={'text': duty, 'position': '개발자'})

    a = '2001020101_24v1'
    b = '2001020102_24v1'
    add('old', 'stale', 'job_alio', '000', '오래된 공고', [link(a, 'assistant', 'stale')])
    add('job', 'P1', 'job_alio', '100', '데이터 엔지니어',
        [link(a, 'assistant', '설계'), link(a, 'human', '모델링')])
    add('job', 'P2', 'job_alio', '300', '백엔드 개발자', [link(b, 'assistant', '구축')])
    add('nara', 'P1', 'nara_job', '200', '공공 개발자',
        [link(a, 'assistant', '설계'), link(a, 'human', '검토')])
    add('failed', 'bad', 'job_alio', '999', '실패 공고', [link(a, 'human', 'failure')])
    for publication, posting, source_id, identity in [
        ('job', 'ambiguous', None, 'opaque'),
        ('nara', 'conflicting', 'nara_job', 'job-alio:posting:conflicting'),
    ]:
        payload = dict(source_posting_id=posting, name='PRIVATE attribution',
                       links=[link('2001020199_24v1', 'assistant', 'PRIVATE')])
        if source_id is not None:
            payload['source_id'] = source_id
        value = run.js(payload)
        run.sql('INSERT INTO enrichment.link_publication_item'
                '(publication_id,posting_id,enrichment_id,posting_identity,name,payload,'
                'payload_hash) '
                f"VALUES({run.q(publication)},{run.q(posting)},'reviewed:fixture',{run.q(identity)},"
                f"'PRIVATE attribution',{value},enrichment.hash(({value})::text))")


def seed_newer_empty_source_pin_does_not_mask_historical_evidence() -> None:
    run.sql("INSERT INTO enrichment.link_publication"
            "(publication_id,source_hash,job_run_id,ncs_run_id,state,created_at) VALUES"
            "('empty-job',repeat('a',64),'fixture-job_alio',"
            "'fixture-ncs_competency','READY','2026-09-05'); "
            "INSERT INTO enrichment.link_publication_source_run"
            "(publication_id,source_id,run_id) VALUES"
             "('empty-job','job_alio','fixture-job_alio')")


def seed_legacy_and_newer_nara() -> None:
    run.sql("INSERT INTO enrichment.link_publication"
            "(publication_id,source_hash,job_run_id,ncs_run_id,state,created_at) VALUES"
            "('legacy-job',repeat('a',64),'fixture-job_alio',"
            "'fixture-ncs_competency','READY','2026-09-06'),"
            "('newer-nara',repeat('a',64),'fixture-nara_job',"
            "'fixture-ncs_competency','READY','2026-09-07');"
            "INSERT INTO enrichment.link_publication_source_run"
            "(publication_id,source_id,run_id) VALUES"
            "('newer-nara','nara_job','fixture-nara_job')")
    for publication, posting, identity, payload in [
        ('legacy-job', 'L1', 'job-alio:posting:legacy',
         {'links': [
             {'competency_code': '2001020102_24v1', 'reviewer_kind': 'assistant'}]}),
        ('legacy-job', 'L2', 'source:posting:nara_job:conflict',
         {'source_id': 'nara_job', 'links': [
             {'competency_code': '2001020199_24v1', 'reviewer_kind': 'assistant'}]}),
        ('newer-nara', 'N3', 'source:posting:nara_job:recent',
         {'source_id': 'nara_job', 'source_posting_id': 'recent', 'links': [
             {'competency_code': '2001020101_24v1', 'reviewer_kind': 'human'}]}),
    ]:
        value = run.js(payload)
        run.sql('INSERT INTO enrichment.link_publication_item'
                '(publication_id,posting_id,enrichment_id,posting_identity,name,payload,payload_hash) '
                f"VALUES({run.q(publication)},{run.q(posting)},'reviewed:fixture',"
                f"{run.q(identity)},'fixture',{value},enrichment.hash(({value})::text))")


def check() -> None:
    seed()
    singleton = run.sql("SELECT catalog._live_link_item_source('nara','{}'::jsonb,'opaque') IS NULL")
    ambiguous = run.sql("SELECT catalog._live_link_item_source('job','{}'::jsonb,'opaque') IS NULL")
    assert singleton == 't' and ambiguous == 't'
    # Given: READY publications per lineage, plus older READY and newer FAILED rows.
    # When: the demand page is read without any sealed catalog approval.
    page = response('SELECT catalog.live_ncs_demand_v1()')
    # Then: only the latest READY publication for each source contributes.
    assert set(page) == {'contract_version', 'sources', 'review', 'filters',
                         'limit', 'offset', 'total', 'items'}
    assert page['contract_version'] == 'hop-live-ncs-demand-v1'
    assert page['sources'] == [
        {'source_id': 'link_publication', 'publication_id': 'job',
         'created_at': '2026-09-02T00:00:00+00:00', 'posting_source': 'job_alio',
         'run_id': 'fixture-job_alio', 'is_latest_publication': True},
        {'source_id': 'link_publication', 'publication_id': 'nara',
         'created_at': '2026-09-03T00:00:00+00:00', 'posting_source': 'nara_job',
         'run_id': 'fixture-nara_job', 'is_latest_publication': True},
    ]
    assert page['review'] == {'link_reviewer_kinds': {'assistant': 3, 'human': 2}}
    assert page['filters'] == {'ncs_prefix': None}
    assert (page['limit'], page['offset'], page['total']) == (20, 0, 2)
    first, second = page['items']
    assert set(first) == {'competency_code', 'competency_name', 'ncs_occupation_code',
                          'ncs_occupation_name', 'postings', 'links', 'evidence',
                          'related_qualifications'}
    assert first['competency_code'] == '2001020101_24v1'
    assert first['competency_name'] == '데이터베이스 설계'
    assert (first['ncs_occupation_code'], first['ncs_occupation_name']) == (
        '20010201', '정보기술개발')
    assert (first['postings'], first['links']) == (2, 4)
    assert first['evidence'] == [
        {'source_id': 'job_alio', 'source_posting_id': '100', 'title': '데이터 엔지니어',
          'position': '개발자', 'duty': '설계', 'publication_id': 'job',
          'created_at': '2026-09-02T00:00:00+00:00'},
        {'source_id': 'job_alio', 'source_posting_id': '100', 'title': '데이터 엔지니어',
          'position': '개발자', 'duty': '모델링', 'publication_id': 'job',
          'created_at': '2026-09-02T00:00:00+00:00'},
        {'source_id': 'nara_job', 'source_posting_id': '200', 'title': '공공 개발자',
          'position': '개발자', 'duty': '설계', 'publication_id': 'nara',
          'created_at': '2026-09-03T00:00:00+00:00'},
    ]
    assert first['related_qualifications'] == [{'qualification_code': 'T5H0',
                                                'qualification_name': '정보기술 자격'}]
    assert (second['competency_code'], second['postings'], second['links']) == (
        '2001020102_24v1', 1, 1)
    assert second['related_qualifications'] == []
    assert not any(secret in json.dumps(page, ensure_ascii=False)
                   for secret in ('"reviewer"', 'review_notes', 'reason', 'decision_id',
                                   'candidate_id', 'PRIVATE', 'stale', 'failure'))

    assert response("SELECT catalog.live_ncs_demand_v1('20010201',1,1)")['items'][0] == second
    assert response("SELECT catalog.live_ncs_demand_v1('20')")['total'] == 2
    assert response("SELECT catalog.live_ncs_demand_v1('20010202')")['items'] == []
    assert response("SELECT catalog.live_ncs_demand_v1('  ')")['filters'] == {'ncs_prefix': None}
    for query in ("SELECT catalog.live_ncs_demand_v1('1')",
                  "SELECT catalog.live_ncs_demand_v1('123456789')",
                  "SELECT catalog.live_ncs_demand_v1('20%')"):
        error(query, 'INVALID_LIVE_FILTER')
    for query in ("SELECT catalog.live_ncs_demand_v1(NULL,NULL,0)",
                  "SELECT catalog.live_ncs_demand_v1(NULL,101,0)",
                  "SELECT catalog.live_ncs_demand_v1(NULL,0,0)",
                  "SELECT catalog.live_ncs_demand_v1(NULL,1,-1)"):
        error(query, 'INVALID_LIVE_PAGE')

    grants = (run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text()
    run.sql(grants)
    assert response('SET ROLE jobtology_catalog_reader; '
                    'SELECT catalog.live_ncs_demand_v1()')['total'] == 2
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM enrichment.link_publication_item',
          'permission denied')
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM catalog._live_link_publications_with_provenance()',
          'permission denied')
    error("SET ROLE jobtology_catalog_reader; "
          "SELECT catalog._live_link_item_source('job','{}'::jsonb,'opaque')", 'permission denied')

    # Given: a newer READY job publication pins the same source but has zero items.
    seed_newer_empty_source_pin_does_not_mask_historical_evidence()
    # When: the reader asks for NCS demand.
    newest = response('SELECT catalog.live_ncs_demand_v1()')
    # Then: an empty input pin cannot mask the older, attributable JOB-ALIO evidence.
    assert [source['publication_id'] for source in newest['sources']] == ['job', 'nara']
    assert newest['sources'][0]['is_latest_publication'] is False
    assert newest['total'] == 2
    assert newest['review'] == {'link_reviewer_kinds': {'assistant': 3, 'human': 2}}

    # Given: a legacy publication has no pin rows, and a newer nara-only publication exists.
    seed_legacy_and_newer_nara()
    # When: the same source-attributed selector is used.
    historical = response('SELECT catalog.live_ncs_demand_v1()')
    # Then: legacy JOB-ALIO wins by actual items and its run; conflict is excluded.
    assert [(s['posting_source'], s['publication_id'], s['run_id'], s['is_latest_publication'])
            for s in historical['sources']] == [
                ('job_alio', 'legacy-job', 'fixture-job_alio', True),
                ('nara_job', 'newer-nara', 'fixture-nara_job', True)]
    assert [(item['competency_code'], item['postings'], item['links'])
            for item in historical['items']] == [
                ('2001020101_24v1', 1, 1), ('2001020102_24v1', 1, 1)]
    assert historical['items'][1]['evidence'][0]['publication_id'] == 'legacy-job'
    assert historical['items'][1]['evidence'][0]['created_at'] == '2026-09-06T00:00:00+00:00'
    # Legacy payloads omit source_posting_id; it is derived from the verified identity.
    assert historical['items'][1]['evidence'][0]['source_posting_id'] == 'legacy'


if __name__ == '__main__':
    run.PG = f'jobtology-live-demand-test-{uuid.uuid4().hex[:12]}'
    try:
        run.boot()
        check()
        print('LIVE NCS DEMAND CHECKS PASSED', flush=True)
    finally:
        subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
