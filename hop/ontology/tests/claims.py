"""Review-selection and evidence semantics with independent synthetic source assertions.

No network inference. All mutations target the disposable ontologytest database.
"""
import copy
import json
import os
import subprocess
from run import boot, fixture, load_sources, sql, js, q, expect_error, PG


def fixture_output():
    atom = lambda text: dict(op='atom', parts=[text], children=[])
    requirement = dict(position_ids=['p1'], category='qualification', kind='eligibility', logic='all_of',
        evidence_ids=['eligibility_text:3'],
        text_parts=['내과, 응급의학과 전문의 자격 소지자 및 경력 2년 이상'],
        expression=[dict(op='all_of', parts=[], children=[1, 4]),
            dict(op='any_of', parts=[], children=[2, 3]),
            atom('내과 전문의 자격 소지자'), atom('응급의학과 전문의 자격 소지자'), atom('경력 2년 이상')])
    preference = dict(position_ids=[], category='other', kind='preference', logic='conditional',
        evidence_ids=['preference_text:1'], text_parts=['장애인 우대(단, 필수지원자격 미충족 시 제외)'],
        expression=[dict(op='except', parts=[], children=[1, 2]),
            atom('장애인 우대'), atom('필수지원자격 미충족 시 제외')])
    return dict(positions=[dict(id='p1', name='데이터 엔지니어', evidence_ids=['title:1'])],
        duties=[dict(position_ids=['p1'], evidence_ids=['eligibility_text:2'], text_parts=['데이터베이스 설계', '구축'])],
        requirements=[requirement, preference], duties_status='explicit')


def seed_item(posting, mode='ENRICH', raw=None, state='VALIDATED', batch_suffix=''):
    bid='claims-'+posting+batch_suffix
    source=json.loads(sql(f"SELECT enrichment.source_fields(normalized) FROM ingestion.job_posting WHERE posting_id={q(posting)}"))
    if mode=='EVAL':
        sql("INSERT INTO enrichment.dataset(dataset_id,job_run_id,ncs_run_id,seed,requested_size) VALUES('claims-eval','fixture-job_alio','fixture-ncs_competency','fixed',1) ON CONFLICT DO NOTHING")
    sql(f"INSERT INTO enrichment.batch(batch_id,mode,dataset_id,job_run_id,ncs_run_id,ncs_hash,settings,state) VALUES({q(bid)},{q(mode)},"
        f"{'NULL' if mode=='ENRICH' else q('claims-eval')},'fixture-job_alio','fixture-ncs_competency','fixture',"
        "'{\"prompt_version\":\"ko-v4\",\"acceptance_policy\":\"REVIEW\"}','COMPLETE')")
    sql(f"INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal,extraction_id) VALUES({q(bid)},{q(bid)},{q(posting)},{js(source)},enrichment.hash({js(source)}::text),1,{q(bid+'-extract')})")
    sql(f"INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,state,raw_output,parsed_output,issues) VALUES({q(bid+'-extract')},{q(bid)},{q(bid)},'extract','fixture','{{}}',{q(state)},"
        f"{js(raw) if raw is not None else 'NULL'},"
        f"{'enrichment.hydrate_v4('+js(raw)+','+js(source)+')' if raw is not None else 'NULL'},"
        f"{js([] if state=='VALIDATED' else ['synthetic:REJECTED'])})")
    return bid


def capture(item, raw=None, parent=None):
    return sql(f"SELECT enrichment.capture_extraction({q(item)},'synthetic-reviewer','Reviewed fixture',"
        f"{js(raw) if raw is not None else 'NULL'},{q(parent) if parent else 'NULL'})")


def decide(revision, decision='ACCEPT'):
    sql(f"SELECT enrichment.decide_extraction({q(revision)},{q(decision)},'synthetic-reviewer','assistant','Fixture semantic decision')")


def prepare(name):
    sql(f"SELECT ontology.prepare_release({q(name)}); SELECT ontology.assemble_sources({q(name)})")


def assemble(name):
    sql(f"SELECT ontology.freeze_reviews({q(name)}); SELECT ontology.assemble_claims({q(name)}); SELECT ontology.verify_claims({q(name)})")


def digest(name):
    return sql(f"""SELECT ontology.hash(jsonb_build_object(
      'selections',(SELECT jsonb_agg(s ORDER BY entity_id) FROM ontology.posting_selection s WHERE release_id={q(name)}),
      'claims',(SELECT jsonb_agg(c ORDER BY claim_id) FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id) WHERE release_id={q(name)}),
      'positions',(SELECT jsonb_agg(c ORDER BY position_id) FROM ontology.release_position m JOIN ontology.position_claim c USING(position_id) WHERE release_id={q(name)}),
      'links',(SELECT jsonb_agg(c ORDER BY mapping_id) FROM ontology.release_mapping m JOIN ontology.mapping_claim c USING(mapping_id) WHERE release_id={q(name)})
    ))""")


def check():
    sources=fixture()
    jobs=[]
    for posting in ['001','002','003','004','005','006']:
        for original in sources['job_alio']:
            jobs.append(original | dict(posting_id=posting, title='데이터 엔지니어 채용', education='학력무관,고졸',
                eligibility_text='😀 참고: 데이터베이스 설계\r\n담당 업무: 데이터베이스\t설계 및 구축\n내과, 응급의학과 전문의 자격 소지자 및 경력 2년 이상',
                preference_text='장애인 우대(단, 필수지원자격 미충족 시 제외)\r\n연락처 안내'))
    sources['job_alio']=jobs
    load_sources(sources)
    sql("INSERT INTO enrichment.ncs_catalog SELECT run_id,normalized->>'code',normalized->>'name',normalized->>'definition',normalized->>'occupation_code',normalized->>'occupation_name' FROM ingestion.ready_record WHERE source_id='ncs_competency'")
    raw=fixture_output()
    item=seed_item('001',raw=raw); revision=capture(item); decide(revision)
    seed_item('002',raw=raw)  # validated is not accepted
    seed_item('003',state='REJECTED')
    seed_item('005',mode='EVAL',raw=raw)  # never production
    item6=seed_item('006',raw=raw); rev6=capture(item6); decide(rev6)
    corrected=copy.deepcopy(raw);corrected['duties'][0]['text_parts']=['데이터베이스 설계']
    newer6=capture(item6,corrected,rev6)  # latest correction pending: no fallback
    accepted=sql(f"SELECT enrichment.propose_link({q(revision)},'2001020101_24v2',0,'Explicit database-design duty','synthetic','model')")
    rejected=sql(f"SELECT enrichment.propose_link({q(revision)},'2001020102_24v1',0,'Fixture candidate subsequently rejected','synthetic','model')")
    sql(f"SELECT enrichment.decide_link({q(accepted)},'ACCEPT','synthetic','assistant','Fixture definition checked'); SELECT enrichment.decide_link({q(rejected)},'REJECT','synthetic','assistant','Fixture rejection')")
    prepare('review-fixture'); assemble('review-fixture')
    outcomes=json.loads(sql("SELECT jsonb_object_agg(right(entity_id,3),outcome) FROM ontology.posting_selection WHERE release_id='review-fixture'"))
    assert outcomes=={'001':'ACCEPTED','002':'REVIEW_REQUIRED','003':'PROCESSING_FAILED','004':'NOT_PROCESSED','005':'NOT_PROCESSED','006':'REVIEW_REQUIRED'},outcomes
    assert sql("SELECT count(*) FROM ontology.release_position WHERE release_id='review-fixture'")=='1'
    claims=json.loads(sql("SELECT jsonb_agg(c ORDER BY kind,ordinal) FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id) WHERE release_id='review-fixture'"))
    assert len(claims)==4,claims
    duty=next(c for c in claims if c['kind']=='DUTY')
    req=next(c for c in claims if c['category']=='qualification')
    edu=next(c for c in claims if c['category']=='education')
    assert edu['applicability']=='unresolved_positions' and edu['logic']=='unspecified' and edu['condition_kind']=='eligibility',edu
    assert req['logic']=='all_of' and req['applicability']=='explicit_positions'
    edges=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_array(parent_index,ordinal,child_index) ORDER BY parent_index,ordinal) FROM ontology.condition_child WHERE claim_id={q(req['claim_id'])}"))
    assert edges==[[0,0,1],[0,1,4],[1,0,2],[1,1,3]],edges
    assert sql(f"SELECT count(*) FROM ontology.condition_evidence WHERE claim_id={q(req['claim_id'])} AND node_index=2")=='2','Shared suffix evidence was flattened'
    evidence=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_object('start',e.start_offset,'end',e.end_offset,'quote',e.excerpt,'text',a.normalized_text) ORDER BY ce.part_index) FROM ontology.claim_evidence ce JOIN ontology.evidence_span e USING(evidence_id) JOIN ontology.text_artifact a USING(artifact_id) WHERE ce.claim_id={q(duty['claim_id'])}"))
    for ev in evidence: assert ev['text'][ev['start']:ev['end']]==ev['quote'],ev
    assert evidence[0]['quote']=='데이터베이스\t설계' and evidence[0]['start']==evidence[0]['text'].index('데이터베이스\t설계'),evidence
    assert evidence[0]['start']>evidence[0]['text'].index('\n'),'Matched repeated phrase outside cited line'
    all_spans=json.loads(sql("SELECT jsonb_agg(jsonb_build_object('start',e.start_offset,'end',e.end_offset,'quote',e.excerpt,'text',a.normalized_text)) FROM ontology.evidence_span e JOIN ontology.text_artifact a USING(artifact_id)"))
    for ev in all_spans: assert ev['text'][ev['start']:ev['end']]==ev['quote'],ev
    # Independent code-point assertion includes an emoji and composed Hangul.
    decomposed='한';normalized='앞😀 '+decomposed+'\r\n끝'
    ev=json.loads(sql(f"SELECT to_jsonb(s) FROM ontology.locate_fragment(ontology.normalize_text({q(normalized)}),'한') s"))
    assert ev=={'start_offset':3,'end_offset':4,'excerpt':'한'},ev
    assert sql("SELECT count(*) FROM ontology.release_mapping WHERE release_id='review-fixture'")=='1'
    assert sql("SELECT min(assertion_kind) FROM ontology.mapping_claim")=='MODEL_INFERRED'
    assert sql("SELECT count(*) FROM ontology.claim_position")=='2','Posting metadata inherited a position'
    before=digest('review-fixture');assemble('review-fixture');assert digest('review-fixture')==before
    # A later rejection is copied only into the new release, never the frozen one.
    sql(f"SELECT enrichment.decide_link({q(accepted)},'REJECT','synthetic','assistant','Later reconsideration')")
    prepare('review-after-link-rejection');assemble('review-after-link-rejection')
    assert sql("SELECT count(*) FROM ontology.release_claim WHERE release_id='review-after-link-rejection'")=='4'
    assert sql("SELECT count(*) FROM ontology.release_mapping WHERE release_id='review-after-link-rejection'")=='0'
    assert digest('review-fixture')==before
    # Reuse identical claims/positions across releases rather than duplicating entities.
    assert sql("SELECT count(*) FROM ontology.claim")=='4'
    assert sql("SELECT count(*) FROM ontology.position_claim")=='1'
    decide(revision,'REJECT')
    prepare('review-after-extraction-rejection');assemble('review-after-extraction-rejection')
    assert sql("SELECT count(*) FROM ontology.release_claim WHERE release_id='review-after-extraction-rejection'")=='0'
    assert digest('review-fixture')==before
    expect_error("UPDATE ontology.evidence_span SET excerpt='invented'",'IMMUTABLE_ONTOLOGY_RECORD')
    expect_error("DELETE FROM ontology.posting_selection WHERE release_id='review-fixture'",'IMMUTABLE_ONTOLOGY_RECORD')
    expect_error("SELECT ontology.locate_fragment('source','invented')",'UNSUPPORTED_ONTOLOGY_FRAGMENT')
    expect_error("BEGIN; UPDATE ontology.corpus_release SET state='READY' WHERE release_id='review-fixture'; SELECT ontology.store_fragment('review-fixture','urn:jobtology:jobPosting:job_alio:001','{}','text'); COMMIT;",'ONTOLOGY_RELEASE_NOT_PREPARING')
    expect_error("BEGIN; ALTER TABLE ontology.claim DISABLE TRIGGER USER; UPDATE ontology.claim SET text='tampered'; SELECT ontology.verify_claims('review-fixture'); COMMIT;",'ONTOLOGY_CLAIM_CONTENT_MISMATCH')
    expect_error("BEGIN; ALTER TABLE ontology.evidence_span DISABLE TRIGGER USER; UPDATE ontology.evidence_span SET start_offset=start_offset+1; SELECT ontology.verify_claims('review-fixture'); COMMIT;",'ONTOLOGY_EVIDENCE_OFFSET_MISMATCH')
    # NCS freshness belongs to the pinned release, not whatever is latest later.
    decide(revision)
    sql(f"SELECT enrichment.decide_link({q(accepted)},'ACCEPT','synthetic','assistant','Restore fixture link')")
    sql("""INSERT INTO ingestion.run SELECT (jsonb_populate_record(NULL::ingestion.run,to_jsonb(r)||jsonb_build_object('run_id','new-ncs','created_at',now()))).* FROM ingestion.run r WHERE run_id='fixture-ncs_competency';
INSERT INTO ingestion.partition SELECT (jsonb_populate_record(NULL::ingestion.partition,to_jsonb(r)||'{"run_id":"new-ncs"}'::jsonb)).* FROM ingestion.partition r WHERE run_id='fixture-ncs_competency';
INSERT INTO ingestion.document SELECT (jsonb_populate_record(NULL::ingestion.document,to_jsonb(r)||'{"run_id":"new-ncs"}'::jsonb)).* FROM ingestion.document r WHERE run_id='fixture-ncs_competency';
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags)
SELECT 'new-ncs',document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags FROM ingestion.record WHERE run_id='fixture-ncs_competency';""")
    prepare('review-new-ncs');assemble('review-new-ncs')
    assert sql("SELECT count(*) FROM ontology.release_claim WHERE release_id='review-new-ncs'")=='4'
    assert sql("SELECT count(*) FROM ontology.release_mapping WHERE release_id='review-new-ncs'")=='0'
    assert sql("SELECT count(*) FROM ontology.link_selection WHERE release_id='review-new-ncs' AND outcome='NCS_SNAPSHOT_MISMATCH'")=='2'
    sql("SELECT ontology.prepare_release('review-pinned-old-ncs','{\"ncs_competency\":\"fixture-ncs_competency\"}'); SELECT ontology.assemble_sources('review-pinned-old-ncs')")
    assemble('review-pinned-old-ncs')
    assert sql("SELECT count(*) FROM ontology.release_mapping WHERE release_id='review-pinned-old-ncs'")=='1'
    # Saved fixtures let native workflows verify frozen selection/replay independently.
    print('REVIEWED CLAIM CHECKS PASSED: six posting outcomes, EVAL exclusion, latest correction, independent link rejection, nested logic, exact Unicode evidence, source reuse and frozen decisions',flush=True)


if __name__=='__main__':
    try:boot();check()
    finally:
        if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):subprocess.run(['docker','rm','-fv',PG],capture_output=True)
