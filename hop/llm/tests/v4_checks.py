"""Independent regressions for source interpretation; no paid calls."""
import copy
import json


def check_v4(sql, js, q, run_hop, params, neo):
    source = dict(education='석사,박사', eligibility_text='내과, 응급의학과 전문의 자격 소지자')
    def atom(text): return dict(op='atom', parts=[text], children=[])
    req = dict(position_ids=[], category='qualification', kind='eligibility', logic='any_of',
        text_parts=[source['eligibility_text']], evidence_ids=['eligibility_text:1'],
        expression=[dict(op='any_of', parts=[], children=[1, 2]),
            atom('내과 전문의 자격 소지자'), atom('응급의학과 전문의 자격 소지자')])
    good = dict(positions=[], duties=[], requirements=[req], duties_status='not_stated')
    def issues(o, src=source): return sql(f'SELECT enrichment.output_issues_v4({js(o)},{js(src)})')
    assert issues(good) == '[]', issues(good)
    hydrated = json.loads(sql(f'SELECT enrichment.hydrate_v4({js(good)},{js(source)})'))
    assert hydrated['schema_version'] == 'ko-v4' and hydrated['normalization']['changed']
    assert hydrated['requirements'][0]['expression'][1]['parts'] == ['내과', '전문의 자격 소지자']
    assert hydrated['requirements'][0]['expression'][1]['text'] == '내과 전문의 자격 소지자'
    degree = hydrated['requirements'][-1]
    assert (degree['kind'], degree['logic'], degree['applicability']) == ('eligibility', 'any_of', 'posting_metadata')
    assert [n['text'] for n in degree['expression'][1:]] == ['석사', '박사']
    assert degree['evidence'] == dict(field='education', quote='석사,박사')
    for education, kind, logic, applicability in [
        ('학력무관', 'unrestricted', 'single', 'posting_metadata'),
        ('고졸', 'eligibility', 'single', 'posting_metadata'),
        ('학력무관,고졸', 'eligibility', 'unspecified', 'unresolved_positions')]:
        src = source | dict(education=education)
        assert issues(good, src) == '[]', issues(good, src)
        value = json.loads(sql(f'SELECT enrichment.hydrate_v4({js(good)},{js(src)})'))['requirements'][-1]
        assert (value['kind'], value['logic'], value['applicability']) == (kind, logic, applicability)
    assert 'UNKNOWN_SOURCE_VALUE' in issues(good, source | dict(education='미확인 학력 코드'))
    # Incorrect model interpretation of the dedicated metadata is replaced, while
    # narrative requirements remain independently subject to semantic checks.
    bad_degree = req | dict(category='education', kind='unrestricted', logic='single',
        text_parts=['석사,박사'], evidence_ids=['education:1'], expression=[])
    fixed = json.loads(sql(f'SELECT enrichment.hydrate_v4({js(good | dict(requirements=[bad_degree]))},{js(source)})'))
    assert len(fixed['requirements']) == 1 and fixed['requirements'][0]['kind'] == 'eligibility'
    for edit, wanted in [
        (lambda o:o['requirements'][0]['expression'][1].update(parts=['내과 경력 99년']), 'UNSUPPORTED_FRAGMENT'),
        (lambda o:o['requirements'][0]['expression'][0].update(children=[0, 2]), 'INVALID_CHILD'),
        (lambda o:o['requirements'][0].update(kind='unrestricted'), 'UNPROVEN_UNRESTRICTED')]:
        bad = copy.deepcopy(good); edit(bad)
        assert wanted in issues(bad), (wanted, issues(bad))
    src = dict(preference_text='장애인 우대(단, 필수지원자격 미충족 시 제외)')
    flat = good | dict(requirements=[req | dict(category='other', kind='preference', logic='single',
        expression=[], evidence_ids=['preference_text:1'], text_parts=[src['preference_text']])])
    assert 'EXCEPTION_WITHOUT_CONDITIONAL' in issues(flat, src)
    src = dict(title='환경미화 직원 채용', eligibility_text='환경미화')
    bare = good | dict(requirements=[], duties_status='explicit', duties=[dict(
        position_ids=[], text_parts=['환경미화'], evidence_ids=['eligibility_text:1'])])
    assert 'TITLE_ONLY_REVIEW_REQUIRED' in issues(bare, src)
    src = dict(selection_text='서류심사 및 면접시험')
    procedure = bare | dict(duties=[dict(position_ids=[], text_parts=[src['selection_text']], evidence_ids=['selection_text:1'])])
    assert 'RECRUITMENT_PROCEDURE_REVIEW_REQUIRED' in issues(procedure, src)
    src = dict(duties_text='담당 업무: 면접심사 운영')
    hr_duty = bare | dict(duties=[dict(position_ids=[], text_parts=['면접심사 운영'], evidence_ids=['duties_text:1'])])
    assert issues(hr_duty, src) == '[]', issues(hr_duty, src)
    src = dict(title='일반(공통) 및 정보기술(IT) 채용')
    combined = good | dict(requirements=[], positions=[dict(id='p1', name='일반(공통) 및 정보기술(IT)', evidence_ids=['title:1'])])
    assert 'COMBINED_ROLES' in issues(combined, src)
    run_hop('evaluate.hwf', params | dict(PROMPT_VERSION='ko-v4'), 'v4-native-two-stage')
    report = json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert report['validated'] == 2 and report['requests'] == 3, report
    assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(report['batch_id'])} AND stage='extract' AND raw_output IS NOT NULL AND parsed_output->>'schema_version'='ko-v4'") == '2'
    try:
        sql(f"SELECT enrichment.plan_batch('test-v4-unsafe','ENRICH','test-ko','LATEST','LATEST',"
            f"(SELECT settings || '{{\"acceptance_policy\":\"VALIDATED\"}}'::jsonb FROM enrichment.batch WHERE batch_id={q(report['batch_id'])}))")
        raise AssertionError('Unevaluated v4 policy accepted')
    except RuntimeError as e:
        assert 'V4_REQUIRES_INDEPENDENT_SEMANTIC_REVIEW' in str(e), str(e)
    print('V4 source education, mixed scope, unchanged-word proof, exception/title/procedure gates and native execution passed', flush=True)
