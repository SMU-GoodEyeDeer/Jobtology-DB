"""Product-role review and frozen reuse in disposable PostgreSQL/native Hop.

Synthetic Korean source bodies and decisions only; no remote host, attachments,
LLM requests, catalogue approval or production writes.
"""
from pathlib import Path
import copy
import hashlib
import json
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'hop/ontology/tests'))
import run
suffix=uuid.uuid4().hex[:10]
run.PG='jobtology-occupation-pg-'+suffix
import native
import claims
native.PG=run.PG;native.HOP='jobtology-occupation-hop-'+suffix;native.NET='jobtology-occupation-'+suffix
sql,q,js,err=run.sql,run.q,run.js,run.expect_error
POSTING='urn:jobtology:jobPosting:job_alio:'
ROLE='urn:jobtology:occupation:product:'

def read(expression):return json.loads(sql('SELECT '+expression))
def inspect(release,posting):return read('ontology.query_occupation_input_v1('+q(release)+','+q(POSTING+posting)+',true)')
def results(release):
    doc=read('ontology.query_occupations_v1('+q(release)+',true)')
    items=doc['current_candidates'] if doc['selection_status']=='NOT_FROZEN' else [p['selection'] for p in doc['postings']]
    return {r['entity_id'].split(':')[-1]:r['outcome'] for r in items}
def proposal(release,posting,role=None,reason=None):
    context=inspect(release,posting);source=context['source_binding']
    d=context['proposal_template']|dict(actor='fixture-author',resolver_version='fixture-review-v1',
        reason='Synthetic duty and complete catalogue comparison only.')
    if role:
        d.update(disposition='MATCH',occupation_id=ROLE+role,unresolved_reason=None)
    elif reason:
        d.update(disposition='UNRESOLVED',unresolved_reason=reason)
    else:
        d.update(disposition='OUT_OF_SCOPE',unresolved_reason=None)
    d['evidence_ids']=sorted({e['evidence_id'] for duty in source['duties'] for e in duty['evidence']})
    return d
def capture(doc):return sql('SELECT ontology.capture_occupation_v1('+js(doc)+')')
def decision(pid,choice='ACCEPT',actor='fixture-independent',kind='human',review_id=None):
    values=[review_id or str(uuid.uuid4()),pid,choice,actor,kind,'Synthetic independent source and catalogue review.']
    return 'SELECT ontology.decide_occupation_v1('+','.join(q(v) for v in values)+')'
def capture_catalogue(doc):
    raw=(json.dumps(doc,ensure_ascii=False,indent=2)+'\n').encode();sha=hashlib.sha256(raw).hexdigest()
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    sql('SELECT editorial.capture_v1(decode('+q(raw.hex())+",'hex'),"+q(sha)+','+q(blob)+')')
    sql('SELECT editorial.review_v1('+q(str(uuid.uuid4()))+','+q(sha)+",'ACCEPT','fixture-catalogue-reviewer','human',"
        "'Synthetic fixture: not an actual review or Git merge',"+q('1'*40)+",'fixture-only:main')")
    return sha
def prepare(release,snapshot):
    sql('SELECT ontology.prepare_release('+q(release)+'); SELECT ontology.assemble_sources('+q(release)+'); '+
        'SELECT editorial.pin_v1('+q(release)+','+q(snapshot)+'); SELECT ontology.freeze_reviews('+q(release)+'); '+
        'SELECT ontology.assemble_claims('+q(release)+'); SELECT ontology.verify_claims('+q(release)+')')
def freeze(release):sql('SELECT ontology.freeze_occupations_v1('+q(release)+')')
def fingerprint(release):return sql('SELECT manifest_hash FROM ontology.occupation_membership WHERE release_id='+q(release))
def stage_file(name,value):
    path=native.WORK/name;path.write_text(json.dumps(value,ensure_ascii=False))
    subprocess.run(['docker','cp',str(path),native.HOP+':'+native.REMOTE+'/'+name],check=True,capture_output=True)
    return native.REMOTE+'/'+name

def main(after=None, configure=None):
    try:
        run.boot()
        sources=run.fixture();original=sources['job_alio'];jobs=[];revisions={};items={};outputs={}
        data=[('001','AI 엔지니어','기계학습 모델 학습 및 모델 배포'),
              ('002','백엔드 개발자','서버 API 개발 및 데이터베이스 운영'),
              ('003','프론트엔드 개발자','웹 사용자 화면 개발 및 접근성 개선'),
              ('004','데이터 분석가','통계 분석 및 의사결정 보고서 작성'),
              ('005','간호사','병동 간호 및 투약 관리'),
              ('006','AI 엔지니어','기계학습 모델 학습 및 모델 배포'),
              ('007','채용 안내',''),
              ('008','AI 엔지니어 / 간호사','기계학습 모델 학습 및 모델 배포\n병동 간호 및 투약 관리')]
        for posting,title,duty in data:
            jobs.extend(r|dict(posting_id=posting,title=title,eligibility_text=duty,education='',preference_text='') for r in original)
            outputs[posting]=dict(positions=[dict(id='p1',name=title,evidence_ids=['title:1'])],requirements=[],
                duties=[dict(position_ids=['p1'],evidence_ids=['eligibility_text:1'],text_parts=[duty])] if duty else [],
                duties_status='explicit' if duty else 'not_stated')
        outputs['008']['positions']=[dict(id='p1',name='AI 엔지니어',evidence_ids=['title:1']),dict(id='p2',name='간호사',evidence_ids=['title:1'])]
        outputs['008']['duties']=[dict(position_ids=['p1'],evidence_ids=['eligibility_text:1'],text_parts=[data[0][2]]),
                                  dict(position_ids=['p2'],evidence_ids=['eligibility_text:2'],text_parts=[data[4][2]])]
        sources['job_alio']=jobs
        if configure is not None:configure(sources,outputs)
        run.load_sources(sources)
        for posting,_,_ in data:
            items[posting]=claims.seed_item(posting,raw=outputs[posting]);revisions[posting]=claims.capture(items[posting])
            if posting!='006':claims.decide(revisions[posting])
        protected=sql("SELECT ontology.hash(jsonb_build_object('source',(SELECT jsonb_agg(r ORDER BY record_id) FROM ingestion.record r),"
            "'attempts',(SELECT jsonb_agg(a ORDER BY attempt_id) FROM enrichment.attempt a),'attachments',(SELECT count(*) FROM attachment.attempt)))")
        native.stage();native.run('../editorial/install.hwf',{},'native-occupation-install')
        catalogue=json.loads((ROOT/'hop/editorial/catalogues/product-occupations.v1.yaml').read_text())
        sha=capture_catalogue(catalogue);prepare('roles-v1',sha)
        sql("SELECT ontology.prepare_release('roles-not-assembled'); SELECT ontology.assemble_sources('roles-not-assembled')")
        err("SELECT ontology.query_occupations_v1('roles-not-assembled',true)",'FREEZE_REVIEWS_FIRST')
        sql("SELECT ontology.freeze_reviews('roles-not-assembled'); SELECT ontology.assemble_claims('roles-not-assembled')")
        err("SELECT ontology.query_occupations_v1('roles-not-assembled',true)",'EDITORIAL_PIN_REQUIRED')
        baseline_revisions=sql('SELECT ontology.hash(jsonb_agg(r ORDER BY revision_id)) FROM ontology.revision r')
        assert results('roles-v1')=={p:'EXTRACTION_NOT_ACCEPTED' if p=='006' else 'NOT_PROPOSED' for p,_,_ in data}
        context=inspect('roles-v1','001');assert len(context['catalogue_binding']['definitions'])==5
        assert context['source_binding']['input_scope']=='inline-fields'
        assert context['current_proposal'] is None and context['current_decision'] is None
        source=context['source_binding'];assert source['duties'][0]['text']=='기계학습 모델 학습 및 모델 배포'
        for span in source['evidence']:
            text=sql('SELECT normalized_text FROM ontology.text_artifact WHERE artifact_id='+q(span['artifact_id']))
            assert text[span['start_offset']:span['end_offset']]==span['excerpt']
        d=proposal('roles-v1','001','AI_ENGINEER')
        cases=[(d|{'source_binding_hash':'0'*64},'OCCUPATION_SOURCE_BINDING_MISMATCH'),
               (d|{'catalogue_snapshot_id':'0'*64},'OCCUPATION_CATALOGUE_MISMATCH'),
               (d|{'occupation_id':'urn:jobtology:occupation:ncs:20010201'},'OCCUPATION_TARGET_NOT_IN_CATALOGUE'),
               (d|{'considered_duty_ids':[]},'OCCUPATION_ALL_DUTIES_REQUIRED'),
               (d|{'considered_position_ids':[]},'OCCUPATION_ALL_POSITIONS_REQUIRED'),
               (d|{'evidence_ids':['missing']},'OCCUPATION_EVIDENCE_OUTSIDE_SOURCE'),
               (d|{'evidence_ids':[]},'OCCUPATION_DUTY_EVIDENCE_REQUIRED'),
               (d|{'considered_duty_ids':d['considered_duty_ids']*2},'DUPLICATE_OCCUPATION_REFERENCE'),
               (d|{'occupation_id':None},'OCCUPATION_OUTCOME_FIELDS'),
               (d|{'actor':' '},'OCCUPATION_PROVENANCE_REQUIRED'),
               (d|{'actor_kind':'assistant'},'OCCUPATION_METHOD_PROVENANCE_MISMATCH'),
               (d|{'method':'MODEL_INFERRED','actor_kind':'assistant'},'OCCUPATION_METHOD_PROVENANCE_MISMATCH'),
               (d|{'method':'MODEL_INFERRED','actor_kind':'assistant','model_id':' ','prompt_version':' '},'OCCUPATION_METHOD_PROVENANCE_MISMATCH'),
               (d|{'confidence':0.99},'INVALID_OCCUPATION_PROPOSAL')]
        for bad,message in cases:err('SELECT ontology.capture_occupation_v1('+js(bad)+')',message)
        err('SELECT ontology.import_occupation_v1(convert_to(\'{"x":1,"x":2}\',\'UTF8\'))','OCCUPATION_PROPOSAL_JSON_OBJECT_REQUIRED')
        err("SELECT ontology.import_occupation_v1(''::bytea)",'OCCUPATION_PROPOSAL_FILE_SIZE')
        for posting in ['006','007']:
            err('SELECT ontology.capture_occupation_v1('+js(proposal('roles-v1',posting,'AI_ENGINEER'))+')','OCCUPATION_REVIEWED_DUTIES_REQUIRED')
        mixed=proposal('roles-v1','008',reason='MIXED_ROLES')
        err('SELECT ontology.capture_occupation_v1('+js(mixed|{'considered_position_ids':mixed['considered_position_ids'][:1]})+')','OCCUPATION_ALL_POSITIONS_REQUIRED')
        assert sql('SELECT count(*) FROM ontology.occupation_proposal')=='0'
        file=stage_file('occupation-proposal.json',d)
        native.run('../editorial/import_occupation.hwf',dict(PROPOSAL_FILE=file),'native-occupation-import')
        pid=capture(d);assert sql('SELECT count(*) FROM ontology.occupation_proposal')=='1'
        native.run('../editorial/import_occupation.hwf',dict(PROPOSAL_FILE=file),'native-occupation-import-replay')
        assert sql('SELECT count(*) FROM ontology.occupation_proposal')=='1'
        err(decision(pid,actor='fixture-author'),'INDEPENDENT_OCCUPATION_REVIEW_REQUIRED')
        rid=str(uuid.uuid4());review=dict(REVIEW_ID=rid,PROPOSAL_ID=pid,DECISION='ACCEPT',REVIEWER='fixture-independent',
            REVIEWER_KIND='human',NOTES='Synthetic independent source and catalogue review.')
        native.run('../editorial/review_occupation.hwf',review,'native-occupation-review')
        native.run('../editorial/review_occupation.hwf',review,'native-occupation-review-replay')
        assert sql('SELECT count(*) FROM ontology.occupation_decision')=='1'
        err(decision(pid,choice='REJECT',review_id=rid),'OCCUPATION_REVIEW_ID_CONFLICT')
        proposals={'001':pid}
        for posting,role in [('002','BACKEND_DEVELOPER'),('003','FRONTEND_DEVELOPER'),('004','DATA_ANALYST')]:
            doc=proposal('roles-v1',posting,role)
            if posting=='004':doc.update(actor='fixture-model',actor_kind='assistant',method='MODEL_INFERRED',model_id='fixture/not-a-live-model',prompt_version='fixture-prompt-v1')
            proposals[posting]=capture(doc);sql(decision(proposals[posting],kind='assistant' if posting=='004' else 'human'))
        for posting,reason in [('005',None),('006','EXTRACTION_NOT_ACCEPTED'),('007','NO_REVIEWED_DUTIES'),('008','MIXED_ROLES')]:
            proposals[posting]=capture(proposal('roles-v1',posting,reason=reason));sql(decision(proposals[posting]))
        expected={p:'MATCHED' for p in ['001','002','003','004']}|{'005':'OUT_OF_SCOPE','006':'EXTRACTION_NOT_ACCEPTED','007':'UNRESOLVED','008':'UNRESOLVED'}
        assert results('roles-v1')==expected
        native.run('../editorial/read_occupation_input.hwf',dict(RELEASE_ID='roles-v1',ENTITY_ID=POSTING+'001',PREVIEW='Y'),'native-occupation-input')
        native.run('../editorial/freeze_occupations.hwf',dict(RELEASE_ID='roles-v1'),'native-occupation-freeze')
        frozen=fingerprint('roles-v1');freeze('roles-v1');assert fingerprint('roles-v1')==frozen
        assert results('roles-v1')==expected
        native.run('../editorial/read_occupations.hwf',dict(RELEASE_ID='roles-v1',PREVIEW='Y'),'native-occupation-read')
        matched=read("(SELECT jsonb_agg(to_jsonb(p) ORDER BY entity_id) FROM ontology.primary_product_occupation p WHERE release_id='roles-v1')")
        assert len(matched)==4 and len({p['entity_id'] for p in matched})==4
        assert all(p['confidence'] is None and p['confidence_state']=='UNASSESSED' for p in matched)
        assert matched[3]['review_state']=='ASSISTANT_REVIEWED'
        assert baseline_revisions==sql('SELECT ontology.hash(jsonb_agg(r ORDER BY revision_id)) FROM ontology.revision r')
        # No stale acceptance fallback. Frozen v1 remains stable through every later change.
        newer=proposal('roles-v1','001','AI_ENGINEER');newer['reason']='Synthetic new interpretation awaiting review.'
        newpid=capture(newer);assert newpid!=pid
        err(decision(pid),'OCCUPATION_PROPOSAL_SUPERSEDED')
        assert sql(decision(pid,review_id=rid))=='1','Identical historical review retry must stay idempotent'
        prepare('roles-pending',sha);freeze('roles-pending');assert results('roles-pending')['001']=='PENDING'
        err('SELECT ontology.capture_occupation_v1('+js(newer|{'parent_id':None,'reason':'Stale parent'})+')','STALE_OCCUPATION_PARENT')
        sql(decision(newpid,choice='REJECT'));prepare('roles-rejected',sha);freeze('roles-rejected')
        assert results('roles-rejected')['001']=='REJECTED'
        # A new extraction review is a new source binding even when source content is identical.
        claims.decide(revisions['002']);prepare('roles-source-changed',sha);freeze('roles-source-changed')
        assert results('roles-source-changed')['002']=='SOURCE_CHANGED'
        corrected=copy.deepcopy(outputs['003']);corrected['duties'][0]['text_parts']=['웹 사용자 화면 개발']
        replacement=claims.capture(items['003'],corrected,revisions['003']);claims.decide(replacement)
        prepare('roles-duties-changed',sha);freeze('roles-duties-changed')
        assert results('roles-duties-changed')['003']=='SOURCE_CHANGED'
        # Full catalogue changes invalidate both selected matches and exclusions.
        catalogue2=copy.deepcopy(catalogue);catalogue2['catalogue_version']=2;catalogue2['occupations'][0]['aliases'].append('모델 개발자')
        sha2=capture_catalogue(catalogue2);prepare('roles-catalogue-changed',sha2);freeze('roles-catalogue-changed')
        changed=results('roles-catalogue-changed')
        assert changed['004']=='CATALOGUE_CHANGED' and changed['005']=='CATALOGUE_CHANGED'
        assert changed['003']=='SOURCE_CHANGED'
        assert changed['006']=='EXTRACTION_NOT_ACCEPTED' and changed['002']=='SOURCE_CHANGED'
        assert fingerprint('roles-v1')==frozen and results('roles-v1')==expected
        # Read-mode, source boundary and immutable provenance protections.
        err("SELECT ontology.query_occupations_v1('roles-v1',false)",'ONTOLOGY_RELEASE_NOT_PUBLISHED')
        err("SELECT ontology.query_occupations_v1('roles-v1',NULL)",'INVALID_ONTOLOGY_READ_MODE')
        err("SELECT ontology.query_occupation_input_v1('roles-v1','missing',true)",'OCCUPATION_POSTING_NOT_IN_REVIEWED_RELEASE')
        err('UPDATE ontology.occupation_proposal SET disposition=\'UNRESOLVED\'','IMMUTABLE_ONTOLOGY_RECORD')
        err("BEGIN; ALTER TABLE ontology.occupation_selection DISABLE TRIGGER USER; DELETE FROM ontology.occupation_selection WHERE release_id='roles-v1'; SELECT ontology.verify_occupations_v1('roles-v1'); COMMIT",'OCCUPATION_MEMBERSHIP_CHANGED')
        err("UPDATE ontology.corpus_release SET manifest=ontology.graph_inventory_manifest('roles-v1')-'occupation_membership' WHERE release_id='roles-v1'",'OCCUPATION_GRAPH_INTEGRATION_REQUIRED')
        assert sql("SELECT count(*) FROM ontology.graph_node WHERE release_id='roles-v1'")=='0','Failed seal left partial inventory'
        assert sql("SELECT count(*) FROM ontology.corpus_release WHERE state='ACTIVE'")=='0'
        current=sql("SELECT ontology.hash(jsonb_build_object('source',(SELECT jsonb_agg(r ORDER BY record_id) FROM ingestion.record r),"
            "'attempts',(SELECT jsonb_agg(a ORDER BY attempt_id) FROM enrichment.attempt a),'attachments',(SELECT count(*) FROM attachment.attempt)))")
        assert current==protected,'Occupation review changed source data or provider/attachment attempts'
        for path in sorted((ROOT/'hop/editorial/sql').glob('*.sql')):sql(path.read_text())
        sql("SELECT ontology.verify_occupations_v1('roles-v1')");assert fingerprint('roles-v1')==frozen
        report=dict(result='PASS',synthetic_postings=8,matched_product_roles=4,provider_calls=0,production_changes=False,
            frozen_outcomes=expected,catalogue_change_outcomes=changed,review_replay='IDEMPOTENT',
            stale_parent='REJECTED',independent_review='REQUIRED',confidence='UNASSESSED',
            incomplete_occupation_manifest='REJECTED',source_provider_attachment_fingerprint=protected,
            native_log_directory=str(native.WORK))
        (native.WORK/'occupation-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
        if after is not None:after(native)
    finally:
        subprocess.run(['docker','rm','-fv',native.HOP,run.PG],capture_output=True)
        subprocess.run(['docker','network','rm',native.NET],capture_output=True)

if __name__=='__main__':main()
