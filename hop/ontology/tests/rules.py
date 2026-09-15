"""Native rule projection, independently checked against source and truth tables."""
from pathlib import Path
import copy
import json
import sys
from itertools import product
from run import ROOT,boot,fixture,load_sources,sql,js,q,expect_error
import native
import graph
sys.path.insert(0,str(ROOT/'hop/llm/tests'))
from rule_interpretation_checks import atom,group,rule,document


def check_projection_guards():
    # Equal words on another, uncited line are still the wrong evidence.
    expect_error("""BEGIN; ALTER TABLE ontology.rule_evidence DISABLE TRIGGER ontology_immutable_rule_evidence;
UPDATE ontology.rule_evidence target SET evidence_id=(SELECT evidence_id FROM ontology.rule_evidence WHERE release_id='rules-first' AND local_id='poor_interview' AND node_path='$statement')
WHERE release_id='rules-first' AND local_id='low_score' AND node_path='$statement';
SELECT ontology.verify_rules('rules-first'); COMMIT;""",'ONTOLOGY_RULE_EVIDENCE_MISMATCH')
    expect_error("""BEGIN; CREATE OR REPLACE FUNCTION ontology.graph_node_candidates(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
SELECT 'reserved-fixture',ARRAY['fixture'],'{"id":"collision"}'::jsonb $$;
SELECT ontology.seal_graph('rules-pending'); COMMIT;""",'GRAPH_RESERVED_NODE_PROPERTY')
    expect_error("""BEGIN; CREATE OR REPLACE FUNCTION ontology.graph_edge_candidates(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
SELECT 'a','b','c','{"release_id":"collision"}'::jsonb $$;
SELECT ontology.seal_graph('rules-pending'); COMMIT;""",'GRAPH_RESERVED_EDGE_PROPERTY')


def check():
    boot()
    source=dict(title='조건 검증 담당자',eligibility_text='병역의무 불이행 사실이 없는 자\n단, 최종 합격자 발표일까지 전역예정자로서 전형절차에 응시 가능자 지원 가능',
        preference_text='장애인에게 만점의 3%를 가산함.\n다만 점수가 40% 미만이거나 점수로 환산할 수 없는 시험은 가점을 적용하지 않음.\n면접위원 2/3 이상 “하” 또는 “양” 평정이면 가점을 적용하지 않음.')
    records=fixture()
    records['job_alio']=[r|source|dict(education=None) for r in records['job_alio']]
    load_sources(records)
    source=json.loads(sql("SELECT enrichment.source_fields(normalized) FROM ingestion.job_posting WHERE posting_id='001'"))
    eligibility=source['eligibility_text'].splitlines();preference=source['preference_text'].splitlines()
    raw=dict(positions=[dict(id='p1',name='조건 검증 담당자',evidence_ids=['title:1'])],duties=[],duties_status='not_stated',unhandled_passages=[],requirements=[
        dict(position_ids=['p1'],category='other',kind='eligibility',logic='conditional',text_parts=eligibility,
            evidence_ids=['eligibility_text:1','eligibility_text:2'],condition=group('except',*map(atom,eligibility))),
        dict(position_ids=['p1'],category='other',kind='preference',logic='conditional',text_parts=preference,
            evidence_ids=['preference_text:1','preference_text:2','preference_text:3'],
            condition=group('except',atom(preference[0]),group('any_of',*map(atom,preference[1:]))))])
    assert sql(f'SELECT enrichment.output_issues_v6({js(raw)},{js(source)})')=='[]'
    sql(f"""INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state)
VALUES('rules','ENRICH','fixture-job_alio','fixture-ncs_competency','fixture','{{"prompt_version":"ko-v6"}}','COMPLETE');
INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal,extraction_id)
VALUES('rules','rules','001',{js(source)},enrichment.hash({js(source)}::text),1,'rules-attempt');
INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,state,raw_output,parsed_output)
VALUES('rules-attempt','rules','rules','extract','fixture','{{}}','VALIDATED',{js(raw)},enrichment.hydrate_v6({js(raw)},{js(source)}));""")
    revision=sql("SELECT enrichment.capture_extraction('rules','fixture','Synthetic source expressions')")
    extraction=json.loads(sql(f'SELECT extraction FROM enrichment.extraction_revision WHERE revision_id={q(revision)}'))
    assert len(extraction['requirements'])==2
    sql(f"SELECT enrichment.decide_extraction({q(revision)},'ACCEPT','fixture','assistant','Synthetic full extraction checked')")
    docs=[document(rule('service','REQUIRE',[eligibility[0]],['eligibility_text:1']),
        rule('permission','PERMIT',['지원 가능'],['eligibility_text:2'],group('all_of',atom('최종 합격자 발표일까지 전역예정자로서'),atom('전형절차에 응시 가능자')))),
        document(rule('bonus','PREFER',['장애인에게 만점의 3%를 가산함.'],['preference_text:1'],atom('장애인')),
        rule('low_score','DISABLE',['가점을 적용하지 않음.'],['preference_text:2'],group('any_of',atom('점수가 40% 미만'),atom('점수로 환산할 수 없는 시험')),target='bonus'),
        rule('poor_interview','DISABLE',['가점을 적용하지 않음.'],['preference_text:3'],atom('면접위원 2/3 이상 “하” 또는 “양” 평정'),target='bonus'))]
    interpretation_ids=[]
    for idx,doc in enumerate(docs):
        rid=sql(f"SELECT enrichment.capture_rule_interpretation({q(revision)},{idx},'fixture','Explicit source effects',{js(doc)})")
        interpretation_ids.append(rid)
        sql(f"SELECT enrichment.decide_rule_interpretation({q(rid)},'ACCEPT','fixture','assistant','Synthetic rule semantics checked')")
    original=sql("SELECT to_jsonb(a) FROM enrichment.attempt a WHERE attempt_id='rules-attempt'")
    graph.boot_neo();native.stage(neo=graph.NEO);graph.clear_fixture_graph()
    native.run('install.hwf',{},'rules-native-installer')
    native.run('prepare_release.hwf',dict(RELEASE_ID='rules-first'),'rules-source-assembly')
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID='rules-first'),'rules-claim-assembly')
    # Every statement, predicate and target is read back independently of graph candidates.
    stored=json.loads(sql("SELECT jsonb_agg(jsonb_build_object('index',s.requirement_index,'rule',r.rule_data) ORDER BY s.requirement_index,r.ordinal) FROM ontology.guarded_rule r JOIN ontology.rule_selection s USING(release_id,interpretation_id) WHERE r.release_id='rules-first'"))
    assert stored==[dict(index=idx,rule=r) for idx,d in enumerate(docs) for r in d['rules']]
    assert sql("SELECT count(*) FROM ontology.rule_predicate WHERE release_id='rules-first'")=='8'
    assert sql("SELECT count(*) FROM ontology.rule_evidence WHERE release_id='rules-first'")=='11'
    assert sql("SELECT bool_and(position_ids='[\"p1\"]') FROM ontology.guarded_rule WHERE release_id='rules-first'")=='t'
    # Correcting an interpretation never silently changes a frozen release.
    corrected=copy.deepcopy(docs[0]);corrected['rules'][1]['id']='permit_apply'
    pending=sql(f"SELECT enrichment.capture_rule_interpretation({q(revision)},0,'fixture','New pending interpretation',{js(corrected)},{q(interpretation_ids[0])})")
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID='rules-first'),'rules-frozen-replay')
    assert sql("SELECT count(*) FROM ontology.guarded_rule WHERE release_id='rules-first'")=='5'
    native.run('load_release.hwf',dict(RELEASE_ID='rules-first'),'rules-native-graph-load')
    assert graph.neo("MATCH (r:guardedRule) RETURN count(r)").splitlines()[-1]=='5'
    assert graph.neo("MATCH (r:guardedRule {action:'DISABLE'})-[e:DISABLES]->(b:guardedRule {local_id:'bonus'}) WHERE e.release_id='rules-first' RETURN count(r)").splitlines()[-1]=='2'
    assert graph.neo("MATCH (r:guardedRule {action:'PERMIT'})-[e:DISABLES]->() RETURN count(e)").splitlines()[-1]=='0'
    assert graph.neo("MATCH (r:guardedRule {action:'PERMIT'})-[:GUARDED_BY {release_id:'rules-first'}]->(p:rulePredicate)-[:HAS_CHILD {release_id:'rules-first'}]->(a:rulePredicate) RETURN p.operator,collect(a.parts[0])").splitlines()[-1].startswith('"all_of",')
    # Inspect graph text/structure and evaluate it in a small independent oracle.
    graph_rules=[dict(zip(['id','action','rule_id','parts'],r)) for r in json.loads(graph.neo("MATCH (r:guardedRule) RETURN collect([r.local_id,r.action,r.rule_id,r.statement_parts])").splitlines()[-1])]
    expected_rules={r['id']:r for d in docs for r in d['rules']}
    assert {r['id']:dict(action=r['action'],parts=r['parts']) for r in graph_rules}=={k:dict(action=v['action'],parts=v['statement_parts']) for k,v in expected_rules.items()}
    predicates=[dict(zip(['rule_id','path','operator','parts'],r)) for r in json.loads(graph.neo("MATCH (p:rulePredicate) RETURN collect([p.rule_id,p.node_path,p.operator,p.parts])").splitlines()[-1])]
    nodes={(p['rule_id'],p['path']):p for p in predicates}
    ids={r['id']:r['rule_id'] for r in graph_rules}
    expected_predicates={}
    def flatten_expected(rid,node,path=''):
        if node is None:return
        expected_predicates[(rid,path)]=dict(rule_id=rid,path=path,operator=node['op'],parts=node['parts'])
        for ordinal,child in enumerate(node['children']):flatten_expected(rid,child,path+'/'+str(ordinal))
    for local,doc in expected_rules.items():flatten_expected(ids[local],doc['guard'])
    assert nodes==expected_predicates,'Graph changed predicate text, operator or tree paths'
    def predicate(rid,path,obs):
        n=nodes.get((rid,path))
        if n is None:return True
        if n['operator']=='atom':return obs[path]
        children=[p for (r,p) in nodes if r==rid and p.rsplit('/',1)[0]==path and p!=path]
        values=[predicate(rid,p,obs) for p in sorted(children)]
        return all(values) if n['operator']=='all_of' else any(values) if n['operator']=='any_of' else not values[0]
    for due,attend in product((False,True),repeat=2):
        assert predicate(ids['permission'],'',{'/0':due,'/1':attend})==(due and attend)
        assert predicate(ids['service'],'',{}) is True
    for beneficiary,low,unscored,poor in product((False,True),repeat=4):
        active=predicate(ids['bonus'],'',{'':beneficiary}) and not(
            predicate(ids['low_score'],'',{'/0':low,'/1':unscored}) or predicate(ids['poor_interview'],'',{'':poor}))
        assert active==(beneficiary and not(low or unscored or poor))
    sealed=sql("SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='rules-first'")
    native.run('load_release.hwf',dict(RELEASE_ID='rules-first'),'rules-native-graph-replay')
    assert sealed==sql("SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='rules-first'")
    native.run('prepare_release.hwf',dict(RELEASE_ID='rules-pending'),'rules-new-source-assembly')
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID='rules-pending'),'rules-pending-interpretation-excluded')
    assert sql("SELECT count(*) FROM ontology.guarded_rule WHERE release_id='rules-pending'")=='3'
    assert sql(f"SELECT outcome FROM ontology.rule_selection WHERE release_id='rules-pending' AND interpretation_id={q(pending)}")=='REVIEW_REQUIRED'
    sql(f"SELECT enrichment.decide_rule_interpretation({q(interpretation_ids[1])},'REJECT','fixture','assistant','Revoke bonus interpretation')")
    native.run('prepare_release.hwf',dict(RELEASE_ID='rules-revoked'),'rules-revocation-source-assembly')
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID='rules-revoked'),'rules-revoked-interpretation-excluded')
    assert sql("SELECT count(*) FROM ontology.guarded_rule WHERE release_id='rules-revoked'")=='0'
    # Extraction revocation independently prevents a still-accepted interpretation.
    sql(f"SELECT enrichment.decide_rule_interpretation({q(pending)},'ACCEPT','fixture','assistant','Synthetic permission checked'); SELECT enrichment.decide_extraction({q(revision)},'REJECT','fixture','assistant','Extraction held')")
    native.run('prepare_release.hwf',dict(RELEASE_ID='rules-extraction-held'),'rules-extraction-hold-source')
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID='rules-extraction-held'),'rules-extraction-hold-excludes-interpretations')
    assert sql("SELECT bool_and(outcome='EXTRACTION_NOT_ACCEPTED') FROM ontology.rule_selection WHERE release_id='rules-extraction-held'")=='t'
    assert original==sql("SELECT to_jsonb(a) FROM enrichment.attempt a WHERE attempt_id='rules-attempt'")
    assert sql("SELECT count(*) FROM ontology.active_release")=='0'
    expect_error("SELECT ontology.activate_release('rules-first','fixture','No completed serving contract')",'RELEASE_NOT_READY_FOR_ACTIVATION')
    check_projection_guards()
    print('NATIVE GUARDED RULE ONTOLOGY CHECKS PASSED',native.WORK,flush=True)
    Path('/tmp/jobtology-ontology/final-rule-ontology-work.txt').write_text(str(native.WORK))


if __name__=='__main__':check()
