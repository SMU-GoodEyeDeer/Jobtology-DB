"""Range accounting and condition-shape regressions; no paid inference."""
import copy
import json
from v6_checks import record, atom, group


def range_row(first, last=None, disposition='procedure', context=None, duplicate=None):
    return dict(first_id=first,last_id=last or first,disposition=disposition,context_kind=context,
        reason='Synthetic source disposition',duplicate_of=duplicate)


def output(*requirements, ranges=None):
    return dict(positions=[],duties=[],requirements=list(requirements),duties_status='not_stated',unhandled_ranges=ranges or [])


def check_v7_text(sql,js):
    schema=json.loads(sql("SELECT output_schema FROM enrichment.prompt WHERE version='ko-v7' AND stage='extract'"))
    def shape(o):return json.loads(sql(f'SELECT enrichment.schema_issues_v6({js(o)},{js(schema)})'))
    def issues(o,s):
        assert shape(o)==[],shape(o)
        return json.loads(sql(f'SELECT enrichment.output_issues_v7({js(o)},{js(s)})'))
    source=dict(eligibility_text='의사면허증 소지자',description_text='보수\n\n연봉 5000만원\r\n주 40시간 근무')
    good=output(record('의사면허증 소지자'),ranges=[range_row('description_text:1','description_text:4','document_context','employment_terms')])
    assert issues(good,source)==[],issues(good,source)
    expanded=json.loads(sql(f'SELECT enrichment.expand_ranges_v7({js(good)},{js(source)})'))
    assert [p['evidence_id'] for p in expanded['unhandled_passages']]==['description_text:1','description_text:3','description_text:4']
    hydrated=json.loads(sql(f'SELECT enrichment.hydrate_v7({js(good)},{js(source)})'))
    assert hydrated['schema_version']=='ko-v7' and hydrated['source_ranges']==good['unhandled_ranges']
    coverage={r['evidence_id']:r for r in hydrated['source_coverage']}
    assert coverage['eligibility_text:1']['disposition']=='cited'
    assert coverage['description_text:3']['context_kind']=='employment_terms'
    assert all(coverage['description_text:'+str(n)]['range_index']==0 for n in [1,3,4])
    old=json.loads(sql(f'SELECT enrichment.hydrate_v6({js(expanded)},{js(source)})'))
    assert old['requirements']==hydrated['requirements'],'Range encoding changed canonical conditions'
    assert hydrated['provider_output_hash']==hydrated['normalization']['provider_output_hash']
    # Schema correlation prevents the pilot's 31 redundant single-atom trees.
    broken=copy.deepcopy(good);broken['requirements'][0]['condition']=atom('의사면허증 소지자')
    assert shape(broken)
    combined='자격증 소지 및 (경력 7년 또는 관련업무 15년)'
    tree=group('all_of',atom('자격증 소지'),group('any_of',atom('경력 7년'),atom('관련업무 15년')))
    nested=output(record(combined,tree))
    assert issues(nested,dict(eligibility_text=combined))==[]
    for logic in ['any_of','conditional','single']:
        bad=copy.deepcopy(nested);bad['requirements'][0]['logic']=logic;assert shape(bad)
    for rows,expected in [
        ([range_row('description_text:1','description_text:999')],'UNKNOWN_RANGE_BOUNDARY'),
        ([range_row('description_text:4','description_text:1')],'INVALID_RANGE_ORDER_OR_FIELD'),
        ([range_row('description_text:1','eligibility_text:1')],'INVALID_RANGE_ORDER_OR_FIELD'),
        ([range_row('description_text:1','description_text:4'),range_row('description_text:3')],'OVERLAPPING_RANGES'),
        ([range_row('description_text:1',disposition='document_context')],'INVALID_CONTEXT_KIND'),
        ([range_row('description_text:1',context='employment_terms')],'INVALID_CONTEXT_KIND'),
        ([range_row('description_text:1','description_text:4','duplicate',duplicate='eligibility_text:1')],'INVALID_DUPLICATE_RANGE')]:
        bad=copy.deepcopy(good);bad['unhandled_ranges']=rows
        assert any(expected in x for x in issues(bad,source)),expected
    conflict=copy.deepcopy(good);conflict['unhandled_ranges'].append(range_row('eligibility_text:1'))
    assert any('CONFLICTING_DISPOSITION' in x for x in issues(conflict,source))
    missing=copy.deepcopy(good);missing['unhandled_ranges'][0]['last_id']='description_text:3'
    assert 'coverage:UNACCOUNTED_PASSAGE:description_text:4' in issues(missing,source)
    metadata=copy.deepcopy(good);metadata['unhandled_ranges'].append(range_row('title:1'))
    assert any('NON_NARRATIVE_RANGE' in x for x in issues(metadata,source|dict(title='개발자 채용')))
    # A broad context range cannot make explicit restrictions disappear.
    for condition in ['의사면허증 소지자','장애인 가점 3%','응시자격: 경력 3년 이상','정년 만60세 이하인 자']:
        s=dict(description_text='보수\n'+condition)
        hiding=output(ranges=[range_row('description_text:1','description_text:2','document_context','employment_terms')])
        assert any('UNPROVEN_DOCUMENT_CONTEXT' in x for x in issues(hiding,s)),condition
    # A form heading is required; saying "form" in the reason is not evidence.
    form=dict(description_text='입사지원서\n성명\n자격증 번호\n연락처')
    rows=[range_row('description_text:1','description_text:4','document_context','application_form')]
    assert issues(output(ranges=rows),form)==[]
    assert any('UNPROVEN_DOCUMENT_CONTEXT' in x for x in issues(output(ranges=rows),dict(description_text='채용 조건\n성명\n자격증 번호\n연락처')))
    # Expanded headings remain distinct from actual requirements.
    headings=dict(description_text='채용 분야 및 인원\n제출 서류\n근무 예정지')
    assert issues(output(ranges=[range_row('description_text:1','description_text:3','heading')]),headings)==[]
    bad_heading=output(ranges=[range_row('description_text:1','description_text:2','heading')])
    assert any('UNPROVEN_HEADING' in x for x in issues(bad_heading,dict(description_text='제출 서류\n의사면허증 소지자')))
    # Historical safety cases still fail rather than being relabeled context.
    absence='결격사유에 해당하지 않은 자'
    assert any('ABSENCE_AS_EXCLUSION' in x for x in issues(output(record(absence,kind='exclusion')),dict(eligibility_text=absence)))
    credentials='의사면허증 및 전문의 자격증 소지자'
    assert 'requirements:COMPOUND_CREDENTIAL_LOGIC_REQUIRED' in issues(output(record(credentials)),dict(eligibility_text=credentials))
    medical=record(credentials,group('all_of',dict(op='atom',parts=['의사면허증','소지자'],children=[]),atom('전문의 자격증 소지자')))
    assert issues(output(medical),dict(eligibility_text=credentials))==[]
    incomplete=output(record('의사면허증 소지자'))
    assert any('NUMERIC_QUALIFIER_OMITTED' in x for x in issues(incomplete,dict(eligibility_text='의사면허증 소지자 및 경력 3년 이상')))
    # PDF split-word evidence stays in separate original fragments.
    split=record('국내전문학');split['text_parts']=['국내전문학','술지에 게재한 연구실적'];split['evidence_ids']=['eligibility_text:1','eligibility_text:2']
    s=dict(eligibility_text='국내전문학\n술지에 게재한 연구실적')
    assert issues(output(split),s)==[]
    joined=copy.deepcopy(split);joined['text_parts']=['국내전문학술지에 게재한 연구실적']
    assert any('UNSUPPORTED_FRAGMENT' in x for x in issues(output(joined),s))
    assert json.loads(sql("SELECT enrichment.coverage_v7('{\"positions\":[],\"duties\":[],\"requirements\":[],\"unhandled_ranges\":[]}','{}')"))==[]
    print('V7 range expansion, context, condition grammar and evidence regressions passed',flush=True)


def check_v7_native(sql,js,q,run_hop,params,request_count):
    check_v7_text(sql,js)
    params=params|dict(JOB_RUN_ID='test-jobs',NCS_RUN_ID='test-ncs',PROMPT_VERSION='ko-v7',REUSE_CACHE='N')
    before=request_count()
    run_hop('evaluate.hwf',params,'v7-native-two-stage')
    report=json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert report['validated']==2 and report['requests']==3,report
    assert request_count()==before+3
    bid=report['batch_id']
    rows=json.loads(sql(f"SELECT jsonb_agg(a) FROM enrichment.attempt a WHERE batch_id={q(bid)} AND stage='extract'"))
    assert all(a['state']=='VALIDATED' and a['parsed_output']['schema_version']=='ko-v7' for a in rows)
    assert all('unhandled_ranges' in a['raw_output'] and 'source_coverage' in a['parsed_output'] for a in rows)
    run_hop('evaluate.hwf',params|dict(REUSE_CACHE='Y'),'v7-native-cache-replay')
    assert request_count()==before+3
    run_hop('enrich.hwf',params,'v7-native-production-review')
    item=sql("SELECT i.item_id FROM enrichment.item i JOIN enrichment.batch b USING(batch_id) WHERE b.mode='ENRICH' AND b.settings->>'prompt_version'='ko-v7' AND i.posting_id='001' ORDER BY b.created_at DESC LIMIT 1")
    run_hop('capture_extraction.hwf',dict(ITEM_ID=item,ACTOR='v7-fixture',REASON='Synthetic range evidence review'),'v7-native-capture')
    assert sql(f"SELECT extraction->>'schema_version' FROM enrichment.extraction_revision WHERE item_id={q(item)}")=='ko-v7'
    assert sql(f"SELECT count(*) FROM enrichment.extraction_decision d JOIN enrichment.extraction_revision r USING(revision_id) WHERE r.item_id={q(item)}")=='0'
    print('V7 native EVAL/ENRICH, cache isolation and review capture passed',flush=True)
    from source_bound_checks import check_source_bound_native
    check_source_bound_native(sql,js,q,run_hop,params,request_count,item)
