"""Regression cases independent of the real-model comparison. Synthetic source only."""
import copy
import json

def check_v2(sql,js,q,run_hop,params,neo):
    source=dict(title='간호사 및 행정직 채용',education='석사,박사',
        eligibility_text='[간호사 및 행정직]\r\n자격증 소지 및\n  (경력 7년 또는 관련업무 15년)\n\n소아청소년과, 응급의학과 전문의 자격 소지자\n국가공무원법상 결격사유가 없는 자',
        disqualification_text='파산자로서 복권되지 아니한 자',preference_text='장애인 우대')
    passages=json.loads(sql(f'SELECT enrichment.source_passages_v2({js(source)})'))
    assert next(p for p in passages if p['id']=='eligibility_text:3')['text']=='  (경력 7년 또는 관련업무 15년)'
    def req(text,ids,**opts):
        return dict(position_ids=[],category='other',kind='eligibility',logic='single',text=text,evidence_ids=ids,expression=[])|opts
    def atom(text):return dict(op='atom',text=text,children=[])
    edu=req('석사,박사',['education:1'],category='education',logic='any_of',expression=[dict(op='any_of',text='',children=[1,2]),atom('석사'),atom('박사')])
    nested=req('자격증 소지 및 (경력 7년 또는 관련업무 15년)',['eligibility_text:2','eligibility_text:3'],position_ids=['p1','p2'],logic='all_of',
       expression=[dict(op='all_of',text='',children=[1,2]),atom('자격증 소지'),dict(op='any_of',text='',children=[3,4]),atom('경력 7년'),atom('관련업무 15년')])
    exclusion=req(source['disqualification_text'],['disqualification_text:1'],kind='exclusion')
    positive=req('국가공무원법상 결격사유가 없는 자',['eligibility_text:6'])
    good=dict(positions=[dict(id='p1',name='간호사',evidence_ids=['eligibility_text:1']),dict(id='p2',name='행정직',evidence_ids=['eligibility_text:1'])],
       duties=[],requirements=[edu,nested,exclusion,positive],duties_status='not_stated')
    def issues(output,src=source):return json.loads(sql(f'SELECT enrichment.output_issues_v2({js(output)},{js(src)})'))
    assert sql(f"SELECT enrichment.schema_issues({js(good)},output_schema) FROM enrichment.prompt WHERE stage='extract' AND version='ko-v2'")=='[]'
    assert issues(good)==[],issues(good)
    positive_source=dict(disqualification_text='국가공무원법 제33조의 규정에 저촉되지 않는 자')
    positive_only=dict(positions=[],duties=[],requirements=[req(positive_source['disqualification_text'],['disqualification_text:1'])],duties_status='not_stated')
    assert issues(positive_only,positive_source)==[]
    hydrated=json.loads(sql(f'SELECT enrichment.hydrate_v2({js(good)},{js(source)})'))
    assert hydrated['requirements'][1]['evidence']['quote']=='자격증 소지 및\n  (경력 7년 또는 관련업무 15년)'
    assert set(hydrated['requirements'][1]['position_names'])=={'간호사','행정직'}
    assert hydrated['requirements'][2]['importance']=='excluded'
    for edit,wanted in [
      (lambda o:o['requirements'][2].update(kind='eligibility'),'EXCLUSION_AS_ELIGIBILITY'),
      (lambda o:o['requirements'][3].update(kind='exclusion'),'ABSENCE_AS_EXCLUSION'),
      (lambda o:o['requirements'].pop(0),'EDUCATION_OMITTED'),
      (lambda o:o['requirements'][1].update(position_ids=['p1 및 p2']),'UNKNOWN_POSITION_ID'),
      (lambda o:o['requirements'][1].update(evidence_ids=['invented:1']),'UNKNOWN_EVIDENCE_ID'),
      (lambda o:o['requirements'][1].update(evidence_ids=['eligibility_text:2','education:1']),'MIXED_EVIDENCE_FIELDS'),
      (lambda o:o['requirements'][1]['expression'][2].update(children=[0,4]),'INVALID_CHILD'),
      (lambda o:o['requirements'][1]['expression'][3].update(text='경력 99년'),'UNSUPPORTED_ATOM'),
      (lambda o:o['requirements'][1].update(text='면허만 있으면 경력 제한 없음'),'UNSUPPORTED_TEXT'),
    ]:
        bad=copy.deepcopy(good);edit(bad)
        assert any(wanted in x for x in issues(bad)),(wanted,issues(bad))
    medical=req('소아청소년과, 응급의학과 전문의 자격 소지자',['eligibility_text:5'],logic='any_of',expression=[dict(op='any_of',text='',children=[1,2]),atom('소아청소년과'),atom('응급의학과')])
    assert issues(good|dict(requirements=[edu,medical]))==[]
    # A quoted long passage cannot hide an omitted label outside the extracted text.
    gold=dict(field='eligibility_text',quote='관련업무 15년',category='other',importance='required',logic='all_of',kind='eligibility')
    pred=hydrated['requirements'][1]
    assert sql(f"SELECT enrichment.label_matches({js(pred)},{js(gold)},'requirements')")=='t'
    assert sql(f"SELECT enrichment.label_matches({js(pred|dict(text='자격증 소지'))},{js(gold)},'requirements')")=='f'
    src=dict(education='학력무관',eligibility_text='경력 제한 없음')
    free=dict(positions=[],duties=[],requirements=[req('학력무관',['education:1'],category='education',kind='unrestricted')],duties_status='not_stated')
    assert issues(free,src)==[]
    bad=copy.deepcopy(free);bad['requirements'][0]['kind']='eligibility'
    assert 'UNRESTRICTED_AS_REQUIRED' in str(issues(bad,src))
    # A compound noun with Korean particles should retrieve its specialist unit.
    sql("""INSERT INTO enrichment.ncs_catalog VALUES
     ('test-ncs','0202020209_23v3','노사갈등 해결','노사갈등 해결은 노무관련 위법사항과 고충처리에 대응하는 능력이다.','02020202','노무관리'),
     ('test-ncs','1202020201_16v2','장례 접수 안내','장례식장 이용자에게 장례 접수를 안내하는 능력이다.','12020202','장례지도') ON CONFLICT DO NOTHING;""")
    for duty,code in [('노무관련 구제신청 및 진정사건 대리','0202020209_23v3'),('장례서비스 제공','1202020201_16v2')]:
        rows=json.loads(sql(f"SELECT enrichment.candidates_v2('test-ncs','{{}}',{js(dict(duties=[dict(text=duty)]))},2)"))
        assert code in [r['code'] for r in rows],rows
    run_hop('evaluate.hwf',params|dict(PROMPT_VERSION='ko-v2'),'v2-native-two-stage')
    report=json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert report['validated']==2 and report['requests']==3,report
    bid=report['batch_id']
    assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(bid)} AND stage='extract' AND raw_output IS NOT NULL AND parsed_output->>'schema_version'='ko-v2'")=='2'
    run_hop('enrich.hwf',params|dict(PROMPT_VERSION='ko-v2'),'v2-enrich-for-review')
    bid=sql("SELECT batch_id FROM enrichment.batch WHERE mode='ENRICH' ORDER BY created_at DESC LIMIT 1")
    item=sql(f"SELECT item_id FROM enrichment.item WHERE batch_id={q(bid)} AND posting_id='001'")
    run_hop('review_item.hwf',dict(ITEM_ID=item,DECISION='ACCEPT',REVIEWER='synthetic-fixture-author'),'v2-review')
    run_hop('publish_reviewed.hwf',dict(BATCH_ID=bid),'v2-publish')
    assert 'true' in neo("MATCH (:jobEnrichment {id:'"+item+"'})-[r:ALIGNS_WITH_NCS {accepted:true}]->() RETURN r.evidence_quote CONTAINS '데이터베이스 설계';").lower()
    print('V2 evidence, exclusion, education, nested logic, shared positions, retrieval and native publication checks passed',flush=True)
