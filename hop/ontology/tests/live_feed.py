#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run: uv run hop/ontology/tests/live_feed.py
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
        assert (message in str(exc) if message == 'permission denied'
                else f'ERROR:  {message}\n' in str(exc)), str(exc)
    else:
        raise AssertionError(f'Expected {message}')


def check() -> None:
    # Given: current READY sources and a stale, older READY job snapshot.
    job = dict(kind='JobPosting', organization_code='C001', organization_name='한빛 기관',
               date_posted='2026-09-01', closing_date='2026-10-10', ongoing=True,
               regions='서울, 부산, ,', employment_type='정규직, 비정규직',
               recruitment_type='공채', education='학력무관',
               ncs_category_codes='R600002,R600020',
               ncs_category_names='경영.회계.사무,정보통신', headcount=3,
               eligibility_text='PRIVATE eligibility', preference_text='PRIVATE preference',
               selection_text='PRIVATE selection', disqualification_text='PRIVATE disqualification')
    jobs = [
        job | dict(posting_id='B', title='데이터 엔지니어', source_url='https://example.org/B'),
        job | dict(posting_id='A', title='데이터 분석가', source_url='없음',
                   closing_date='2026-10-10', ncs_category_codes='R600002,R600020,R600099',
                   ncs_category_names='경영.회계.사무,정보통신'),
        job | dict(posting_id='C', title='행정 담당', organization_name='다른 기관',
                   regions='제주', closing_date=None, date_posted=None, source_url='http://example.org/C',
                   ncs_category_codes=None, ncs_category_names=None),
    ]
    records = {
        'job_alio': [item | dict(representation=representation) for item in jobs
                     for representation in ('list', 'detail')],
        'qnet_schedule': [
            dict(kind='ExamSession', qualification_code='T5H0', year=2026, round=2,
                 category_code='C', name='정기 시험 2회', dates={
                     'docRegStartDt': '2026-10-01', 'docRegEndDt': '2026-10-02',
                     'docExamStartDt': '2026-10-10', 'docExamEndDt': 'bad',
                     'docPassDt': '2026-10-20', 'pracRegStartDt': '2026-11-01',
                     'pracRegEndDt': '2026-11-02', 'pracExamStartDt': '2026-11-10',
                     'pracExamEndDt': '2026-11-11', 'pracPassDt': '2026-11-20'}),
            dict(kind='ExamSession', qualification_code='T5H0', year=2026, round=1,
                 category_code='C', name='정기 시험 1회', dates={'docRegStartDt': '2026-09-01'}),
            dict(kind='ExamSession', qualification_code='ZZ', year=2026, round=1,
                 category_code='D', name='기타', dates={'docRegStartDt': 'invalid'}),
        ],
        'ncs_qualification': [dict(kind='QualificationMapping', qualification_code='T5H0',
                                   qualification_name='정보기술 자격', competency_code='1'),
                              dict(kind='QualificationMapping', qualification_code='T5H0',
                                   qualification_name='정보기술 자격', competency_code='2')],
    }
    run.load_sources(records)
    run.sql("INSERT INTO ingestion.run"
            "(run_id,source_id,mode,policy_revision,state,created_at,completed_at) "
            "VALUES('old-job','job_alio','FULL','fixture','READY','2026-08-01','2026-08-02')")
    run.sql("INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) "
            "VALUES('old-job','all','FILE',1); INSERT INTO ingestion.document"
            "(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,"
            "http_status,retrieved_at,selected,verified_at) VALUES"
            "('old-job','doc','all',1,'old.json',repeat('a',64),1,'UTF-8',200,"
            "'2026-08-01',true,now())")
    for index, representation in enumerate(('list', 'detail')):
        stale = job | dict(posting_id='OLD', title='STALE', representation=representation)
        run.sql("INSERT INTO ingestion.record"
                "(run_id,document_id,locator,source_record_id,source_payload,normalized) "
                f"VALUES('old-job','doc',{run.q(str(index))},{run.q('OLD:' + representation)},"
                f'{run.js(stale)},{run.js(stale)})')

    # Given: both list/detail pairs exist in a current and an older run.
    # When: the bounded live helper assembles the current run.
    merged = run.sql("WITH expected AS (SELECT posting_id,normalized FROM ingestion.job_posting "
                     "WHERE run_id='fixture-job_alio'), actual AS (SELECT * FROM "
                     "catalog._live_job_postings('fixture-job_alio')) "
                     "SELECT NOT EXISTS(SELECT * FROM expected EXCEPT SELECT * FROM actual) "
                     "AND NOT EXISTS(SELECT * FROM actual EXCEPT SELECT * FROM expected) "
                     "AND NOT EXISTS(SELECT 1 FROM actual WHERE posting_id='OLD')")
    # Then: no merge result differs and no older-run posting appears.
    assert merged == 't'

    # When: list, detail, and exam feed are read before any catalog approval.
    page = response('SELECT catalog.live_postings_v1()')
    detail = response("SELECT catalog.live_posting_v1('A')")
    exams = response('SELECT catalog.live_exam_sessions_v1()')
    # Then: only current source runs, strict projection, stable order and totals.
    page_keys = {'contract_version', 'sources', 'filters', 'limit', 'offset', 'total', 'items'}
    assert set(page) == page_keys
    assert page['contract_version'] == 'hop-live-source-v1'
    assert page['sources'] == [{'source_id': 'job_alio', 'run_id': 'fixture-job_alio',
                                'data_as_of': '2026-09-01T00:01:00+00:00'}]
    assert page['filters'] == {'q': None, 'ncs_category': None, 'region': None, 'open_on': None}
    assert (page['limit'], page['offset'], page['total']) == (20, 0, 3)
    assert [item['posting_id'] for item in page['items']] == ['A', 'B', 'C']
    item = page['items'][0]
    assert set(item) == {'posting_id', 'source_id', 'title', 'organization_code', 'organization_name',
                         'date_posted', 'closing_date', 'ongoing', 'regions',
                         'employment_types', 'recruitment_type', 'education',
                         'ncs_categories', 'headcount', 'source_url'}
    assert item['regions'] == ['서울', '부산']
    assert item['employment_types'] == ['정규직', '비정규직']
    assert item['ncs_categories'] == [{'code': 'R600002', 'name': '경영.회계.사무'},
                                      {'code': 'R600020', 'name': '정보통신'},
                                      {'code': 'R600099', 'name': None}]
    assert item['source_url'] is None and page['items'][1]['source_url'] == 'https://example.org/B'
    assert page['items'][2]['closing_date'] is None and page['items'][2]['date_posted'] is None
    assert page['items'][2]['ncs_categories'] == []
    assert set(detail) == {'contract_version', 'sources', 'item'} and detail['item'] == item
    for value in (page, detail, exams):
        assert not any(field in json.dumps(value, ensure_ascii=False) for field in
                       ('eligibility_text', 'preference_text', 'selection_text',
                        'disqualification_text', 'PRIVATE'))

    first = response("SELECT catalog.live_postings_v1('데이터',NULL,NULL,NULL,1,0)")
    assert [i['posting_id'] for i in first['items']] == ['A']
    assert response("SELECT catalog.live_postings_v1(' 데이터 ',NULL,NULL,NULL,1,1)")['total'] == 2
    assert response("SELECT catalog.live_postings_v1(' %_ ',NULL,NULL,NULL,20,0)")['total'] == 0
    ncs_page = response("SELECT catalog.live_postings_v1(NULL,'r600020')")
    assert ncs_page['total'] == 2, ncs_page
    assert response("SELECT catalog.live_postings_v1(NULL,'정보통신')")['total'] == 2
    assert response("SELECT catalog.live_postings_v1(NULL,NULL,'부산')")['total'] == 2
    assert response("SELECT catalog.live_postings_v1(NULL,NULL,NULL,'2026-10-11')")['total'] == 1
    last = response("SELECT catalog.live_postings_v1('  ',NULL,NULL,NULL,1,2)")
    assert last['items'][0]['posting_id'] == 'C'
    assert response("SELECT catalog.live_postings_v1(NULL,NULL,NULL,NULL,1,9)")['items'] == []
    dated = response("SELECT catalog.live_postings_v1(NULL,NULL,NULL,'2026-09-01')")
    assert dated['filters']['open_on'] == '2026-09-01'

    assert set(exams) == page_keys
    assert exams['contract_version'] == 'hop-live-source-v1' and exams['total'] == 3
    assert [s['source_id'] for s in exams['sources']] == ['qnet_schedule', 'ncs_qualification']
    assert exams['filters'] == {'qualification': None, 'from': None, 'to': None}
    assert [s['round'] for s in exams['items']] == [1, 2, 1]
    assert set(exams['items'][1]) == {'qualification_code', 'qualification_name', 'year',
                                     'round', 'category_code', 'name', 'written', 'practical'}
    assert exams['items'][1]['qualification_name'] == '정보기술 자격'
    assert exams['items'][1]['written'] == {'registration_start': '2026-10-01',
                                           'registration_end': '2026-10-02',
                                           'exam_start': '2026-10-10', 'exam_end': None,
                                           'result_date': '2026-10-20'}
    assert exams['items'][1]['practical']['result_date'] == '2026-11-20'
    assert set(exams['items'][1]['practical']) == set(exams['items'][1]['written'])
    assert exams['items'][2]['qualification_name'] is None
    assert response("SELECT catalog.live_exam_sessions_v1('정보기술')")['total'] == 2
    assert response("SELECT catalog.live_exam_sessions_v1('T5H0')")['total'] == 2
    assert response("SELECT catalog.live_exam_sessions_v1(NULL,'2026-11-10',"
                    "'2026-11-10')")['total'] == 1
    assert response("SELECT catalog.live_exam_sessions_v1(NULL,'2026-10-01',"
                    "'2026-10-01')")['total'] == 1
    second_exam = response("SELECT catalog.live_exam_sessions_v1(NULL,NULL,NULL,1,1)")
    assert second_exam['items'][0]['round'] == 2
    assert response("SELECT catalog.live_exam_sessions_v1(NULL,'2027-01-01')")['items'] == []

    for query in ("SELECT catalog.live_postings_v1(NULL,NULL,NULL,NULL,NULL,0)",
                  "SELECT catalog.live_postings_v1(NULL,NULL,NULL,NULL,101,0)",
                  "SELECT catalog.live_postings_v1(NULL,NULL,NULL,NULL,1,-1)",
                  "SELECT catalog.live_exam_sessions_v1(NULL,NULL,NULL,0,0)",
                  "SELECT catalog.live_exam_sessions_v1(NULL,NULL,NULL,1,NULL)"):
        error(query, 'INVALID_LIVE_PAGE')
    for query in ("SELECT catalog.live_postings_v1(repeat('a',101))",
                  "SELECT catalog.live_posting_v1(NULL)",
                  "SELECT catalog.live_posting_v1('  ')",
                  "SELECT catalog.live_exam_sessions_v1(repeat('a',101))",
                  "SELECT catalog.live_exam_sessions_v1(NULL,'2026-11-01','2026-10-01')"):
        error(query, 'INVALID_LIVE_FILTER')
    error("SELECT catalog.live_posting_v1('OLD')", 'LIVE_POSTING_NOT_FOUND')
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE run_id='fixture-job_alio'")
    assert response('SELECT catalog.live_postings_v1()')['items'][0]['posting_id'] == 'OLD'
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE run_id='old-job'")
    error('SELECT catalog.live_postings_v1()', 'LIVE_SOURCE_UNAVAILABLE')
    error("SELECT catalog.live_posting_v1('A')", 'LIVE_SOURCE_UNAVAILABLE')
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE run_id='fixture-qnet_schedule'")
    error('SELECT catalog.live_exam_sessions_v1()', 'LIVE_SOURCE_UNAVAILABLE')
    run.sql("UPDATE ingestion.run SET state='READY' "
            "WHERE run_id IN ('fixture-job_alio','fixture-qnet_schedule')")
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE run_id='fixture-ncs_qualification'")
    optional = response('SELECT catalog.live_exam_sessions_v1()')
    assert [s['source_id'] for s in optional['sources']] == ['qnet_schedule']
    assert optional['items'][0]['qualification_name'] is None

    # Privilege admin applies grants; reader has only function execute, never raw views.
    run.sql((run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text())
    assert response('SET ROLE jobtology_catalog_reader; '
                    'SELECT catalog.live_postings_v1()')['total'] == 3
    assert response('SET ROLE jobtology_catalog_reader; '
                    "SELECT catalog.live_posting_v1('A')")['item']['posting_id'] == 'A'
    assert response('SET ROLE jobtology_catalog_reader; '
                    'SELECT catalog.live_exam_sessions_v1()')['total'] == 3
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM ingestion.record', 'permission denied')
    error('SET ROLE jobtology_catalog_reader; SELECT * FROM ingestion.job_posting',
          'permission denied')
    error("SET ROLE jobtology_catalog_reader; "
          "SELECT * FROM catalog._live_job_postings('fixture-job_alio')", 'permission denied')
    grants = (run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text()
    run.sql('GRANT USAGE ON SCHEMA ingestion TO jobtology_catalog_reader')
    error(grants, 'CATALOG_READER_PRIVILEGE_LEAK')
    run.sql('REVOKE USAGE ON SCHEMA ingestion FROM jobtology_catalog_reader; CREATE SCHEMA cs; '
            'GRANT USAGE ON SCHEMA cs TO jobtology_catalog_reader')
    error(grants, 'CATALOG_READER_PRIVILEGE_LEAK')
    run.sql('REVOKE USAGE ON SCHEMA cs FROM jobtology_catalog_reader')
    run.sql(grants)
    check_multi_source(job)
    print('LIVE SOURCE FEED CHECKS PASSED', flush=True)


def check_multi_source(alio: dict) -> None:
    # Metadata-only JobKorea postings participate without a detail pair or inferred NCS.
    listing = dict(kind='JobPosting', representation='local_listing', metadata_accepted=True,
                   organization_name='잡코리아 기업', employer_identity_kind='NAME_UNVERIFIED',
                   content_status='MISSING', source_status='UNKNOWN',
                   application_start_date='2027-01-01', regions='서울',
                   employment_type='정규직', deadline_kind='ROLLING',
                   description_text='PRIVATE description')
    run.load_sources({'jobkorea': [
        listing | dict(posting_id='123', title='데이터 채용', closing_date='2026-12-31',
                       application_start_date='2026-09-01'),
        listing | dict(posting_id='124', title='상시 채용', closing_date=None,
                       application_start_date=None),
        listing | dict(posting_id='125', title='날짜 미상', closing_date='UNKNOWN'),
        listing | dict(posting_id='rejected', metadata_accepted=False),
        listing | dict(posting_id='unaccepted', metadata_accepted=None),
        listing | dict(posting_id='wrong-kind', kind='Other'),
        listing | dict(posting_id='wrong-representation', representation='detail'),
    ]})
    # The same native ID exists in ALIO, where its historical bare ID stays stable.
    for index, representation in enumerate(('list', 'detail')):
        value = alio | dict(posting_id='123', title='ALIO same ID', representation=representation)
        run.sql('INSERT INTO ingestion.record'
                '(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES '
                f"('fixture-job_alio','doc','collision-{index}',{run.q('123:' + representation)},"
                f'{run.js(value)},{run.js(value)})')
    run.sql("INSERT INTO ingestion.document"
            "(run_id,document_id,partition_id,page_no,attempt_no,raw_path,raw_sha256,byte_length,"
            "encoding,http_status,retrieved_at,selected) VALUES "
            "('fixture-jobkorea','unselected','all',1,2,'other.json',repeat('b',64),1,'UTF-8',"
            "200,now(),false)")
    excluded = listing | dict(posting_id='unselected')
    run.sql('INSERT INTO ingestion.record'
            '(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES '
            f"('fixture-jobkorea','unselected','0','unselected',{run.js(excluded)},{run.js(excluded)})")
    # An older READY, newer failed/loading and newer SMOKE snapshot cannot leak records.
    for run_id, state, mode, created in (
            ('jk-old', 'READY', 'FULL', '2026-08-01'),
            ('jk-failed', 'FAILED', 'FULL', '2026-10-01'),
            ('jk-loading', 'LOADING', 'FULL', '2026-10-02'),
            ('jk-smoke', 'READY', 'SMOKE', '2026-10-03')):
        run.sql('INSERT INTO ingestion.run'
                '(run_id,source_id,mode,policy_revision,state,created_at,completed_at) VALUES '
                f"({run.q(run_id)},'jobkorea',{run.q(mode)},'fixture',{run.q(state)},"
                f"{run.q(created)},{run.q(created)});")
        run.sql('INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) '
                f"VALUES({run.q(run_id)},'all','FILE',1); INSERT INTO ingestion.document "
                '(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,'
                'http_status,retrieved_at,selected) VALUES '
                f"({run.q(run_id)},'doc','all',1,'shadow.json',repeat('c',64),1,'UTF-8',200,now(),true)")
        value = listing | dict(posting_id=run_id, title='excluded snapshot')
        run.sql('INSERT INTO ingestion.record'
                '(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES '
                f"({run.q(run_id)},'doc','0',{run.q(run_id)},{run.js(value)},{run.js(value)})")

    page = response('SELECT catalog.live_postings_v1()')
    assert page['total'] == 7, page
    assert [item['posting_id'] for item in page['items']] == [
        'jobkorea:123', 'jobkorea:124', 'jobkorea:125', '123', 'A', 'B', 'C']
    assert page['sources'] == [
        {'source_id': source, 'run_id': 'fixture-' + source,
         'data_as_of': '2026-09-01T00:01:00+00:00'} for source in ('jobkorea', 'job_alio')]
    assert [item['source_id'] for item in page['items']] == ['jobkorea'] * 3 + ['job_alio'] * 4
    # ALIO deadlines are earlier; priority must apply globally before LIMIT/OFFSET.
    assert [i['posting_id'] for i in response(
        'SELECT catalog.live_postings_v1(NULL,NULL,NULL,NULL,2,0)')['items']] == [
            'jobkorea:123', 'jobkorea:124']
    assert [i['posting_id'] for i in response(
        'SELECT catalog.live_postings_v1(NULL,NULL,NULL,NULL,2,2)')['items']] == [
            'jobkorea:125', '123']
    detail = response("SELECT catalog.live_posting_v1('jobkorea:123')")
    assert detail['item'] == page['items'][0]
    assert detail['sources'] == page['sources'][:1]
    native = response("SELECT catalog.live_posting_v1('123')")
    assert native['item']['title'] == 'ALIO same ID'
    assert native['sources'] == page['sources'][1:]
    for item in page['items'][:3]:
        assert item['ncs_categories'] == [] and item['date_posted'] is None
        assert item['organization_code'] is None and item['ongoing'] is None
        assert 'PRIVATE' not in json.dumps(item)
    assert all(item['closing_date'] is None for item in page['items'][1:3])
    assert response("SELECT catalog.live_postings_v1('잡코리아')")['total'] == 3
    assert response("SELECT catalog.live_postings_v1('데이터')")['total'] == 3
    assert response("SELECT catalog.live_postings_v1(NULL,'정보통신')")['total'] == 3
    assert response("SELECT catalog.live_postings_v1(NULL,NULL,'서울')")['total'] == 6
    # Application-start evidence governs availability but never becomes date_posted.
    available = response("SELECT catalog.live_postings_v1(NULL,NULL,NULL,'2026-10-11')")
    assert [i['posting_id'] for i in available['items']] == ['jobkorea:123', 'jobkorea:124', 'C']
    assert response("SELECT catalog.live_postings_v1('날짜 미상',NULL,NULL,'2026-10-11')")['total'] == 0
    for missing in ('jobkorea:rejected', 'jobkorea:unaccepted', 'jobkorea:unselected',
                    'jobkorea:jk-old', 'jobkorea:jk-failed', 'jobkorea:jk-loading',
                    'jobkorea:jk-smoke', 'jobkorea:wrong-kind', 'jobkorea:wrong-representation',
                    'jobkorea:missing', 'nara_job:123'):
        error(f'SELECT catalog.live_posting_v1({run.q(missing)})', 'LIVE_POSTING_NOT_FOUND')
    # Additive installation/replay retains the reader's grants on existing functions.
    migration = (run.ROOT / 'hop/ontology/sql/031_multi_source_live_postings.sql').read_text()
    run.sql(migration)
    assert response('SET ROLE jobtology_catalog_reader; '
                    'SELECT catalog.live_postings_v1()') == page
    error("SET ROLE jobtology_catalog_reader; SELECT * FROM "
          "catalog._live_source_postings('fixture-jobkorea','jobkorea')", 'permission denied')
    assert run.sql("SELECT NOT EXISTS(SELECT 1 FROM pg_proc p, "
                   "LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                   "WHERE p.oid='catalog._live_source_postings(text,text)'::regprocedure "
                   "AND a.grantee=0 AND a.privilege_type='EXECUTE')") == 't'
    # Missing one supported source still permits the other; missing both is unavailable.
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE source_id='job_alio'")
    assert response('SELECT catalog.live_postings_v1()')['total'] == 3
    error("SELECT catalog.live_posting_v1('123')", 'LIVE_SOURCE_UNAVAILABLE')
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE source_id='jobkorea'")
    error('SELECT catalog.live_postings_v1()', 'LIVE_SOURCE_UNAVAILABLE')
    error("SELECT catalog.live_posting_v1('jobkorea:123')", 'LIVE_SOURCE_UNAVAILABLE')
    error("SELECT catalog.live_posting_v1('unsupported:123')", 'LIVE_POSTING_NOT_FOUND')


if __name__ == '__main__':
    run.PG = f'jobtology-live-feed-test-{uuid.uuid4().hex[:12]}'
    try:
        run.boot()
        check()
    finally:
        subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
