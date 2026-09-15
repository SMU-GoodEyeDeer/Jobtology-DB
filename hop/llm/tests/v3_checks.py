"""Source-fragment evidence: shared suffixes and separated exceptions without invented text."""
import copy
import json

def check_v3(sql,js,q,run_hop,params,neo):
    source=dict(eligibility_text='내과, 응급의학과 전문의 자격 소지자',
       preference_text='장애인 : 서류심사 우선합격(단, 필수지원자격 미충족 시 제외) 및 면접심사 우대')
    def atom(*parts):return dict(op='atom',parts=list(parts),children=[])
    req=dict(position_ids=[],category='qualification',kind='eligibility',logic='any_of',
      text_parts=[source['eligibility_text']],evidence_ids=['eligibility_text:1'],
      expression=[dict(op='any_of',parts=[],children=[1,2]),atom('내과','전문의 자격 소지자'),atom('응급의학과 전문의 자격 소지자')])
    good=dict(positions=[],duties=[],requirements=[req],duties_status='not_stated')
    def issues(o):return sql(f'SELECT enrichment.output_issues_v3({js(o)},{js(source)})')
    assert sql(f"SELECT enrichment.schema_issues({js(good)},output_schema) FROM enrichment.prompt WHERE version='ko-v3' AND stage='extract'")=='[]'
    assert issues(good)=='[]',issues(good)
    hydrated=json.loads(sql(f'SELECT enrichment.hydrate_v3({js(good)},{js(source)})'))
    assert hydrated['requirements'][0]['expression'][1]['text']=='내과 전문의 자격 소지자'
    assert hydrated['requirements'][0]['evidence']['quote']==source['eligibility_text']
    assert hydrated['schema_version']=='ko-v3'
    for edit,wanted in [
      (lambda o:o['requirements'][0]['expression'][1].update(parts=['내과','경력 99년']),'UNSUPPORTED_FRAGMENT'),
      (lambda o:o['requirements'][0].update(text_parts=['자격 제한 없음']),'UNSUPPORTED_FRAGMENT'),
      (lambda o:o['requirements'][0].update(text_parts=[]),'UNSUPPORTED_FRAGMENT'),
      (lambda o:o['requirements'][0]['expression'][1].update(children=[2]),'UNSUPPORTED_FRAGMENT'),
      (lambda o:o['requirements'][0]['expression'][0].update(parts=['내과']),'GROUP_HAS_PARTS'),
      (lambda o:o['requirements'][0]['expression'][0].update(children=[0,2]),'INVALID_CHILD')]:
        bad=copy.deepcopy(good);edit(bad);assert wanted in issues(bad),(wanted,issues(bad))
    pref=dict(position_ids=[],category='other',kind='preference',logic='conditional',text_parts=[source['preference_text']],
      evidence_ids=['preference_text:1'],expression=[dict(op='except',parts=[],children=[1,2]),
      atom('장애인 : 서류심사 우선합격','및 면접심사 우대'),atom('필수지원자격 미충족 시 제외')])
    assert issues(good|dict(requirements=[pref]))=='[]'
    run_hop('evaluate.hwf',params|dict(PROMPT_VERSION='ko-v3'),'v3-native-two-stage')
    report=json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert report['validated']==2 and report['requests']==3,report
    run_hop('enrich.hwf',params|dict(PROMPT_VERSION='ko-v3'),'v3-enrich-for-review')
    bid=sql("SELECT batch_id FROM enrichment.batch WHERE mode='ENRICH' ORDER BY created_at DESC LIMIT 1")
    item=sql(f"SELECT item_id FROM enrichment.item WHERE batch_id={q(bid)} AND posting_id='001'")
    run_hop('review_item.hwf',dict(ITEM_ID=item,DECISION='ACCEPT',REVIEWER='synthetic-fixture-author'),'v3-review')
    run_hop('publish_reviewed.hwf',dict(BATCH_ID=bid),'v3-publish')
    assert 'true' in neo("MATCH (e:jobEnrichment {id:'"+item+"'})-[r:ALIGNS_WITH_NCS {accepted:true}]->() RETURN e.prompt_version='ko-v3' AND r.evidence_quote CONTAINS '데이터베이스 설계';").lower()
    print('V3 composed evidence, invalid fragments, exceptions, raw/hydrated output and native publication checks passed',flush=True)
