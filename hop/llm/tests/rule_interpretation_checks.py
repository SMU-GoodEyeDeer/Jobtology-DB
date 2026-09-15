"""Source-bound rule interpretation, explicit effects and three-valued activation."""
import copy
import json
from itertools import product


def atom(text): return dict(op='atom',parts=[text],children=[])
def group(op,*children): return dict(op=op,parts=[],children=list(children))
def rule(id,action,parts,ids,guard=None,target=None):
    return dict(id=id,action=action,statement_parts=parts,evidence_ids=ids,guard=guard,target_rule_id=target)
def document(*rules): return dict(schema_version='guarded-rules-v1',rules=list(rules))


def check_rule_interpretation(t):
    sql,js,q=t.sql,t.js,t.q
    source=dict(title='조건 해석 검증용 공고',eligibility_text='병역의무 불이행 사실이 없는 자\n단, 최종 합격자 발표일까지 전역예정자로서 전형절차에 응시 가능자 지원 가능',
        preference_text='장애인에게 만점의 3%를 가산함.\n다만 점수가 40% 미만이거나 점수로 환산할 수 없는 시험은 가점을 적용하지 않음.\n면접위원 2/3 이상 “하” 또는 “양” 평정이면 가점을 적용하지 않음.')
    eligibility=source['eligibility_text'].splitlines();preference=source['preference_text'].splitlines()
    raw=dict(positions=[],duties=[],duties_status='not_stated',unhandled_passages=[],requirements=[
        dict(position_ids=[],category='other',kind='eligibility',logic='conditional',text_parts=eligibility,
            evidence_ids=['eligibility_text:1','eligibility_text:2'],condition=group('except',*map(atom,eligibility))),
        dict(position_ids=[],category='other',kind='preference',logic='conditional',text_parts=preference,
            evidence_ids=['preference_text:1','preference_text:2','preference_text:3'],
            condition=group('except',atom(preference[0]),group('any_of',*map(atom,preference[1:]))))])
    assert sql(f'SELECT enrichment.output_issues_v6({js(raw)},{js(source)})')=='[]'
    sql(f"""INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state)
VALUES('rule-fixture','ENRICH','test-jobs','test-ncs','fixture','{{"prompt_version":"ko-v6"}}','COMPLETE');
INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal,extraction_id)
VALUES('rule-fixture','rule-fixture','rule-fixture',{js(source)},enrichment.hash({js(source)}::text),1,'rule-fixture-attempt');
INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,state,raw_output,parsed_output)
VALUES('rule-fixture-attempt','rule-fixture','rule-fixture','extract','fixture','{{}}','VALIDATED',{js(raw)},enrichment.hydrate_v6({js(raw)},{js(source)}));""")
    revision=sql("SELECT enrichment.capture_extraction('rule-fixture','fixture','Synthetic source ambiguity')")
    original=sql("SELECT to_jsonb(a) FROM enrichment.attempt a WHERE attempt_id='rule-fixture-attempt'")
    mandatory=rule('service','REQUIRE',[eligibility[0]],['eligibility_text:1'])
    permission=rule('permission','PERMIT',['지원 가능'],['eligibility_text:2'],
        group('all_of',atom('최종 합격자 발표일까지 전역예정자로서'),atom('전형절차에 응시 가능자')))
    military=document(mandatory,permission)
    bonus=document(rule('bonus','PREFER',['장애인에게 만점의 3%를 가산함.'],['preference_text:1'],atom('장애인')),
        rule('low_score','DISABLE',['가점을 적용하지 않음.'],['preference_text:2'],
            group('any_of',atom('점수가 40% 미만'),atom('점수로 환산할 수 없는 시험')),target='bonus'),
        rule('poor_interview','DISABLE',['가점을 적용하지 않음.'],['preference_text:3'],
            atom('면접위원 2/3 이상 “하” 또는 “양” 평정'),target='bonus'))
    ids=[]
    def upload(doc,index,parent=None,label=''):
        package=dict(revision_id=revision,requirement_index=index,parent_id=parent,actor='fixture-interpreter',reason='Explicit source effects',document=doc)
        path=t.WORK/('interpretation-'+label+'.json');path.write_text(json.dumps(package,ensure_ascii=False))
        t.cmd(['docker','cp',str(path),t.HOP+':'+t.REMOTE+'/'+path.name])
        t.run_hop('import_rule_interpretation.hwf',dict(INTERPRETATION_FILE=t.REMOTE+'/'+path.name),'rule-native-import-'+label)
        return sql(f'SELECT interpretation_id FROM enrichment.current_rule_interpretation WHERE revision_id={q(revision)} AND requirement_index={index}')
    for index,doc in enumerate([military,bonus]):
        ids.append(upload(doc,index,label=str(index)))
    before_count=sql('SELECT count(*) FROM enrichment.rule_interpretation')
    assert upload(bonus,1,label='replay')==ids[1]
    assert sql('SELECT count(*) FROM enrichment.rule_interpretation')==before_count
    assert sql('SELECT count(*) FROM enrichment.rule_interpretation_decision')=='0'
    def preview(id,observations):return json.loads(sql(f'SELECT enrichment.rule_activation_preview({q(id)},{js(observations)})'))
    for expected,attend in product((False,True),repeat=2):
        result={r['rule_id']:r for r in preview(ids[0],{'permission/0':expected,'permission/1':attend})}
        assert result['service']['active'] is True and result['service']['action']=='REQUIRE'
        assert result['permission']['active']==(expected and attend)
    # A permission never disables the independent service condition.
    for disabled,low,unscored,poor in product((False,True),repeat=4):
        result={r['rule_id']:r for r in preview(ids[1],dict(bonus=disabled,**{'low_score/0':low,'low_score/1':unscored,'poor_interview':poor}))}
        assert result['bonus']['active']==(disabled and not(low or unscored or poor)),result
    assert {r['rule_id']:r['active'] for r in preview(ids[1],{})}['bonus'] is None
    assert {r['rule_id']:r['active'] for r in preview(ids[1],{'bonus':False})}['bonus'] is False
    assert {r['rule_id']:r['active'] for r in preview(ids[1],{'bonus':True,'low_score/0':False,'low_score/1':False})}['bonus'] is None
    def fail(query,expected):
        try:sql(query)
        except RuntimeError as error:assert expected in str(error),str(error)
        else:raise AssertionError('Expected '+expected)
    fail(f"SELECT enrichment.rule_activation_preview({q(ids[1])},'{{\"made_up\":true}}')",'UNKNOWN_PREDICATE_OBSERVATION')
    fail(f"SELECT enrichment.rule_activation_preview({q(ids[1])},'{{\"bonus\":1}}')",'PREDICATE_OBSERVATION_MUST_BE_BOOLEAN')
    claim=json.loads(sql(f"SELECT extraction->'requirements'->1 FROM enrichment.extraction_revision WHERE revision_id={q(revision)}"))
    def issues(doc):return json.loads(sql(f'SELECT enrichment.rule_interpretation_issues({js(doc)},{js(claim)},{js(source)})'))
    for mutate,expected in [
        (lambda d:d['rules'][0].update(statement_parts=['발명된 보너스']),'rules:UNSUPPORTED_STATEMENT'),
        (lambda d:d['rules'][0]['guard'].update(parts=['발명된 조건']),'rules:UNSUPPORTED_GUARD'),
        (lambda d:d['rules'][0].update(evidence_ids=['eligibility_text:1']),'rules:EVIDENCE_OUTSIDE_REQUIREMENT_OR_DUPLICATE'),
        (lambda d:d['rules'][1].update(target_rule_id='missing'),'rules:UNKNOWN_TARGET'),
        (lambda d:d['rules'][1].update(target_rule_id='low_score'),'rules:CYCLIC_TARGETS'),
        (lambda d:d['rules'][0].update(target_rule_id='low_score'),'rules:INVALID_TARGET_ROLE'),
        (lambda d:d['rules'][1]['guard'].update(children=[atom('점수가 40% 미만')]),'rules:INVALID_PREDICATE_GROUP')]:
        bad=copy.deepcopy(bonus);mutate(bad);assert expected in issues(bad),(expected,issues(bad))
    # Surrounding citations cannot support the uncited line between them.
    bad=document(rule('gap','PREFER',['점수가 40% 미만'],['preference_text:1','preference_text:3']))
    assert 'rules:UNSUPPORTED_STATEMENT' in issues(bad)
    bad=document(rule('gap','PREFER',['장애인'],['preference_text:1','preference_text:3'],atom('점수가 40% 미만')))
    assert 'rules:UNSUPPORTED_GUARD' in issues(bad)
    decision=dict(INTERPRETATION_ID=ids[0],DECISION='ACCEPT',REVIEWER='fixture-reviewer',REVIEWER_KIND='assistant',NOTES='Synthetic condition effects independently checked')
    t.run_hop('review_rule_interpretation.hwf',decision,'rule-native-review')
    corrected=copy.deepcopy(military);corrected['rules'][1]['id']='permit_apply'
    new=upload(corrected,0,parent=ids[0],label='correction')
    assert new!=ids[0]
    assert sql(f'SELECT decision IS NULL FROM enrichment.current_rule_interpretation WHERE interpretation_id={q(new)}')=='t'
    fail(f"SELECT enrichment.decide_rule_interpretation({q(ids[0])},'ACCEPT','fixture','assistant','Stale')",'INTERPRETATION_SUPERSEDED')
    # Identical historical replay is idempotent; a genuinely new correction needs the current parent.
    changed=copy.deepcopy(corrected);changed['rules'][1]['id']='another_permission'
    fail(f"SELECT enrichment.capture_rule_interpretation({q(revision)},0,'fixture','Wrong parent',{js(changed)},{q(ids[0])})",'STALE_INTERPRETATION_PARENT')
    fail(f"UPDATE enrichment.rule_interpretation SET actor='rewritten' WHERE interpretation_id={q(new)}",'APPEND_ONLY_REVIEW_HISTORY')
    assert original==sql("SELECT to_jsonb(a) FROM enrichment.attempt a WHERE attempt_id='rule-fixture-attempt'")
    assert sql(f'SELECT count(*) FROM enrichment.extraction_decision WHERE revision_id={q(revision)}')=='0'
    print('Native rule import/replay/review, 4 permission and 16 bonus truth-table cases, UNKNOWN, exact grounding and correction history passed',flush=True)
