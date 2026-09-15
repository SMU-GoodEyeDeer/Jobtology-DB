"""Reviewed duplicate groups in disposable PostgreSQL 18 and native Hop 2.19.

No remote host, source requests, attachments or paid inference. Source postings
and reviewer/model provenance below are explicit synthetic fixtures.
"""
from pathlib import Path
import copy
import json
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'hop/ontology/tests'))
import run
suffix=uuid.uuid4().hex[:10]
run.PG='jobtology-duplicates-pg-'+suffix
import native
native.PG=run.PG;native.HOP='jobtology-duplicates-hop-'+suffix;native.NET='jobtology-duplicates-'+suffix
sql,q,js,err=run.sql,run.q,run.js,run.expect_error
POSTING='urn:jobtology:jobPosting:job_alio:'

def read(expression):return json.loads(sql('SELECT '+expression))
def prepare(name,job='fixture-job_alio'):
    sql('SELECT ontology.prepare_release('+q(name)+','+js({'job_alio':job})+'); SELECT ontology.assemble_sources('+q(name)+'); '
        'SELECT ontology.freeze_reviews('+q(name)+'); SELECT ontology.assemble_claims('+q(name)+')')
def context(family,members,name='duplicates-v1'):
    return read('ontology.query_duplicate_input_v1('+q(name)+','+q(family)+','+q('{'+','.join(POSTING+p for p in members)+'}')+'::text[],true)')
def proposal(family,members,name='duplicates-v1'):
    return context(family,members,name)['proposal_template']|dict(actor='fixture-author',resolver_version='fixture-manual-v1',
        reason='Synthetic duplicate notices: inspect complete source fields and identities, not title alone.')
def capture(doc):return sql('SELECT ontology.capture_duplicate_v1('+js(doc)+')')
def decide(pid,choice='ACCEPT',who='fixture-independent',kind='human',rid=None):
    args=[rid or str(uuid.uuid4()),pid,choice,who,kind,'Synthetic independent full-record comparison.']
    return 'SELECT ontology.decide_duplicate_v1('+','.join(q(v) for v in args)+')'
def freeze(name):sql('SELECT ontology.freeze_duplicates_v1('+q(name)+')')
def report(name):return read('ontology.query_duplicates_v1('+q(name)+',true)')
def outcomes(name):return {r['selection']['cluster_id']:r['selection']['outcome'] for r in report(name)['selections']}
def members(name):return {m['entity_id'].rsplit(':',1)[-1]:m for m in report(name)['members']}
def fingerprint():
    tables=sql("SELECT quote_ident(schemaname)||'.'||quote_ident(tablename) FROM pg_tables WHERE schemaname IN ('ontology','ingestion','enrichment','attachment') ORDER BY 1").splitlines()
    union=' UNION ALL '.join('SELECT '+q(t)+" AS name,ontology.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')) AS h FROM "+t+' t' for t in tables)
    return sql('SELECT ontology.hash(jsonb_object_agg(name,h)) FROM ('+union+') t')
def source(name,at,rows):
    sql('INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at) VALUES('+q(name)+",'job_alio','FULL','fixture','READY',"+q(at)+','+q(at)+"::timestamptz+interval '1 minute'); "
        'INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES('+q(name)+",'all','FILE',1); "
        'INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at) VALUES('+q(name)+",'doc','all',1,'fixture.json',"+
        'encode(sha256(convert_to('+q(name)+",'UTF8')),'hex'),1,'UTF-8',200,"+q(at)+"::timestamptz+interval '30 seconds',true,now())")
    for idx,row in enumerate(rows):
        key=row['posting_id']+':'+row['representation']
        sql('INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES('+q(name)+",'doc',"+q(str(idx))+','+q(key)+','+js(row)+','+js(row)+')')


def main():
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode!=0
    try:
        run.boot();sources=run.fixture();jobs=[]
        for posting in ['001','002','003','004','005']:
            title='같은 채용의 백엔드 개발자' if posting in ['001','002','003'] else '별도 채용 '+posting
            jobs.extend(r|dict(posting_id=posting,title=title,organization_code='C001',organization_name='동일 기관명',
                source_url='https://example.org/notice/'+posting,recruitment_type='신입',regions='서울',
                eligibility_text='서버 API 개발 및 데이터베이스 운영',education='',preference_text='') for r in sources['job_alio'])
        sources['job_alio']=jobs;run.load_sources(sources);prepare('duplicates-v1')
        original_source=sql("SELECT ontology.source_fingerprint('fixture-job_alio')")
        native.stage();native.run('../cohorts/install.hwf',{},'duplicates-native-install')
        family=str(uuid.uuid4());overlap=str(uuid.uuid4());model_family=str(uuid.uuid4())
        initial=report('duplicates-v1');assert initial['selection_status']=='NOT_FROZEN' and initial['members']==[]
        ctx=context(family,['002','001']);doc=proposal(family,['001','002'])
        assert ctx['proposal_template']['member_ids']==[POSTING+'001',POSTING+'002']
        assert ctx['current_proposal'] is None and ctx['current_decision'] is None
        assert len(ctx['source_binding'])==2
        for entry in ctx['source_binding']:
            assert len(entry['source_support'])==2
            assert entry['revision']['payload']['organization_id']=='urn:jobtology:organization:alio:C001'
            assert entry['revision']['payload']['primary_occupation_id'] is None
        errors=[(doc|dict(source_binding_hash='0'*64),'DUPLICATE_SOURCE_BINDING_MISMATCH'),
            (doc|dict(member_ids=[POSTING+'002',POSTING+'001']),'DUPLICATE_MEMBER_SET_NOT_CANONICAL'),
            (doc|dict(member_ids=[POSTING+'001',POSTING+'001']),'DUPLICATE_MEMBER_SET_NOT_CANONICAL'),
            (doc|dict(member_ids=[POSTING+'001']),'INVALID_DUPLICATE_PROPOSAL'),
            (doc|dict(member_ids=[POSTING+'001',POSTING+'999']),'DUPLICATE_POSTING_NOT_IN_RELEASE'),
            (doc|dict(cluster_id='not-a-uuid'),'INVALID_DUPLICATE_CLUSTER_ID'),
            (doc|dict(actor=' '),'DUPLICATE_PROVENANCE_REQUIRED'),
            (doc|dict(actor_kind='assistant'),'DUPLICATE_METHOD_PROVENANCE_MISMATCH'),
            (doc|dict(method='MODEL_INFERRED',actor_kind='assistant'),'DUPLICATE_METHOD_PROVENANCE_MISMATCH'),
            (doc|dict(confidence=1),'INVALID_DUPLICATE_PROPOSAL')]
        for bad,error in errors:err('SELECT ontology.capture_duplicate_v1('+js(bad)+')',error)
        err("SELECT ontology.import_duplicate_v1(convert_to('{\"x\":1,\"x\":2}','UTF8'))",'DUPLICATE_PROPOSAL_JSON_OBJECT_REQUIRED')
        err("SELECT ontology.import_duplicate_v1(''::bytea)",'DUPLICATE_PROPOSAL_FILE_SIZE')
        assert sql('SELECT count(*) FROM ontology.duplicate_proposal')=='0'
        file=native.WORK/'duplicate.json';file.write_text(json.dumps(doc,ensure_ascii=False))
        subprocess.run(['docker','cp',str(file),native.HOP+':'+native.REMOTE+'/duplicate.json'],check=True,capture_output=True)
        native.run('../cohorts/import_duplicate.hwf',dict(PROPOSAL_FILE=native.REMOTE+'/duplicate.json'),'duplicates-native-import')
        pid=capture(doc);assert sql('SELECT count(*) FROM ontology.duplicate_proposal')=='1'
        native.run('../cohorts/import_duplicate.hwf',dict(PROPOSAL_FILE=native.REMOTE+'/duplicate.json'),'duplicates-native-import-replay')
        err(decide(pid,who='fixture-author'),'INDEPENDENT_DUPLICATE_REVIEW_REQUIRED')
        rid=str(uuid.uuid4());params=dict(REVIEW_ID=rid,PROPOSAL_ID=pid,DECISION='ACCEPT',REVIEWER='fixture-independent',REVIEWER_KIND='human',NOTES='Synthetic independent full-record comparison.')
        native.run('../cohorts/review_duplicate.hwf',params,'duplicates-native-review')
        native.run('../cohorts/review_duplicate.hwf',params,'duplicates-native-review-replay')
        assert sql('SELECT count(*) FROM ontology.duplicate_decision')=='1'
        err(decide(pid,choice='REJECT',rid=rid),'DUPLICATE_REVIEW_ID_CONFLICT')
        conflict=capture(proposal(overlap,['002','003']));sql(decide(conflict))
        native.run('../cohorts/freeze_duplicates.hwf',dict(RELEASE_ID='duplicates-v1'),'duplicates-native-overlap-rejected',False)
        assert sql("SELECT (SELECT count(*) FROM ontology.duplicate_freeze)+(SELECT count(*) FROM ontology.duplicate_selection)+(SELECT count(*) FROM ontology.duplicate_member)+(SELECT count(*) FROM ontology.duplicate_membership)")=='0'
        sql(decide(conflict,choice='REJECT'))
        native.run('../cohorts/freeze_duplicates.hwf',dict(RELEASE_ID='duplicates-v1'),'duplicates-native-freeze')
        first=report('duplicates-v1');frozen=first['membership']['manifest_hash'];rows=members('duplicates-v1')
        assert outcomes('duplicates-v1')=={family:'ACCEPTED',overlap:'REJECTED'}
        assert len(rows)==5 and rows['001']['group_id']==rows['002']['group_id']=='duplicate/'+family
        assert all(rows[p]['cluster_id'] is None for p in ['003','004','005'])
        assert first['membership']['manifest']['posting_count']==5 and first['membership']['manifest']['group_count']==4
        assert all(s['confidence'] is None and s['confidence_state']=='UNASSESSED' for s in first['selections'])
        freeze('duplicates-v1');assert report('duplicates-v1')==first
        err("UPDATE ontology.corpus_release SET manifest=ontology.graph_inventory_manifest('duplicates-v1') WHERE release_id='duplicates-v1'",'DUPLICATE_GRAPH_INTEGRATION_REQUIRED')
        assert sql("SELECT count(*) FROM ontology.graph_node WHERE release_id='duplicates-v1'")=='0'

        # Release context alone does not mint another proposal for identical inputs.
        prepare('duplicates-same-source')
        assert capture(doc|dict(release_id='duplicates-same-source'))==pid
        assert sql('SELECT count(*) FROM ontology.duplicate_proposal')=='2'
        assert context(family,['001','002'],'duplicates-same-source')['current_proposal']['created_in_release']=='duplicates-v1'

        # Installing the guard does not change legacy source-only graph sealing.
        prepare('duplicates-legacy');sql("SELECT ontology.seal_graph('duplicates-legacy')")
        assert report('duplicates-legacy')['selection_status']=='NOT_FROZEN'
        err("SELECT ontology.freeze_duplicates_v1('duplicates-legacy')",'ONTOLOGY_RELEASE_NOT_PREPARING_OR_ALREADY_SEALED')

        # Repeated source observations keep content revisions and duplicate review.
        source('duplicates-refresh','2026-09-02T00:00:00Z',jobs);prepare('duplicates-refreshed','duplicates-refresh');freeze('duplicates-refreshed')
        assert outcomes('duplicates-refreshed')[family]=='ACCEPTED'
        assert members('duplicates-refreshed')['001']['revision_id']==rows['001']['revision_id']
        assert members('duplicates-refreshed')['001']['proposal_id']==pid
        assert report('duplicates-refreshed')['selections'][next(i for i,s in enumerate(report('duplicates-refreshed')['selections']) if s['selection']['cluster_id']==family)]['proposal']['source_binding']==ctx['source_binding']
        changed=[r|dict(title='변경된 채용 내용') if r['posting_id']=='001' else r for r in jobs]
        source('duplicates-changed','2026-09-03T00:00:00Z',changed);prepare('duplicates-changed','duplicates-changed');freeze('duplicates-changed')
        assert outcomes('duplicates-changed')[family]=='SOURCE_CHANGED'
        assert len({m['group_id'] for m in members('duplicates-changed').values()})==5
        source('duplicates-missing','2026-09-04T00:00:00Z',[r for r in jobs if r['posting_id']!='002'])
        prepare('duplicates-missing','duplicates-missing');freeze('duplicates-missing')
        assert outcomes('duplicates-missing')[family]=='MEMBER_OUTSIDE_RELEASE' and len(members('duplicates-missing'))==4

        # A pending correction never falls back to the first accepted proposal.
        newer=proposal(family,['001','002'])|dict(reason='Synthetic corrected comparison pending review.')
        newer_id=capture(newer);prepare('duplicates-pending');freeze('duplicates-pending')
        assert outcomes('duplicates-pending')[family]=='PENDING'
        assert len({m['group_id'] for m in members('duplicates-pending').values()})==5
        err(decide(pid),'DUPLICATE_PROPOSAL_SUPERSEDED')
        assert sql(decide(pid,rid=rid))=='1'
        err('SELECT ontology.capture_duplicate_v1('+js(newer|dict(parent_id=None,reason='Stale edit'))+')','STALE_DUPLICATE_PARENT')
        sql(decide(newer_id,choice='REJECT'));prepare('duplicates-rejected');freeze('duplicates-rejected')
        assert outcomes('duplicates-rejected')[family]=='REJECTED'
        # Changing group membership is a new reviewed proposal, not destructive merging.
        replacement=proposal(family,['001','003'])|dict(reason='Synthetic replacement group; old releases keep member 002.')
        replacement_id=capture(replacement);sql(decide(replacement_id));prepare('duplicates-replaced');freeze('duplicates-replaced')
        replaced=members('duplicates-replaced')
        assert replaced['001']['group_id']==replaced['003']['group_id']=='duplicate/'+family
        assert replaced['002']['cluster_id'] is None and members('duplicates-v1')==rows
        # Model provenance and assistant review remain explicit, with no confidence fabrication.
        sql(decide(replacement_id,choice='REJECT'))
        modeled=proposal(model_family,['001','002'])|dict(actor='fixture-model',actor_kind='assistant',method='MODEL_INFERRED',model_id='fixture/not-a-live-model',prompt_version='fixture-prompt-v1')
        modeled_id=capture(modeled);sql(decide(modeled_id,kind='assistant'));prepare('duplicates-model-fixture');freeze('duplicates-model-fixture')
        selected=next(s for s in report('duplicates-model-fixture')['selections'] if s['selection']['cluster_id']==model_family)
        assert selected['review_status']=='ASSISTANT_REVIEWED' and selected['proposal']['document']['model_id']=='fixture/not-a-live-model'
        source('duplicates-empty-source','2026-09-05T00:00:00Z',[])
        prepare('duplicates-empty','duplicates-empty-source');freeze('duplicates-empty')
        empty=report('duplicates-empty')
        assert empty['selection_status']=='FROZEN' and empty['members']==[] and empty['selections']==[]
        assert empty['membership']['manifest']['posting_count']==empty['membership']['manifest']['group_count']==0
        assert report('duplicates-v1')==first
        assert sql("SELECT ontology.source_fingerprint('fixture-job_alio')")==original_source
        assert sql('SELECT count(*) FROM enrichment.attempt')=='0' and sql('SELECT count(*) FROM attachment.attempt')=='0'
        assert sql("SELECT count(*) FROM ontology.corpus_release WHERE state='ACTIVE'")=='0'

        # Integrity/read gates and native parameter bindings; all failed writes roll back.
        err("DELETE FROM ontology.duplicate_member",'IMMUTABLE_ONTOLOGY_RECORD')
        err("BEGIN; ALTER TABLE ontology.duplicate_member DISABLE TRIGGER USER; DELETE FROM ontology.duplicate_member WHERE release_id='duplicates-v1'; SELECT ontology.verify_duplicates_v1('duplicates-v1'); COMMIT",'DUPLICATE_MEMBERS_CHANGED')
        err("BEGIN; ALTER TABLE ontology.duplicate_selection DISABLE TRIGGER USER; UPDATE ontology.duplicate_selection SET outcome='PENDING' WHERE release_id='duplicates-v1'; SELECT ontology.verify_duplicates_v1('duplicates-v1'); COMMIT",'DUPLICATE_SELECTION_CHANGED')
        err("BEGIN; ALTER TABLE ontology.duplicate_proposal DISABLE TRIGGER USER; UPDATE ontology.duplicate_proposal SET source_binding='[]' WHERE proposal_id="+q(pid)+"; SELECT ontology.verify_duplicates_v1('duplicates-v1'); COMMIT",'DUPLICATE_PROPOSAL_CHANGED')
        err("BEGIN; ALTER TABLE ontology.duplicate_membership DISABLE TRIGGER USER; DELETE FROM ontology.duplicate_membership WHERE release_id='duplicates-v1'; SELECT ontology.query_duplicates_v1('duplicates-v1',true); COMMIT",'DUPLICATE_MEMBERSHIP_CHANGED')
        err("SELECT ontology.query_duplicates_v1('duplicates-v1',false)",'ONTOLOGY_RELEASE_NOT_PUBLISHED')
        err("SELECT ontology.query_duplicates_v1(NULL,true)",'NO_ACTIVE_ONTOLOGY_RELEASE')
        err("SELECT ontology.query_duplicates_v1('duplicates-v1',NULL)",'INVALID_ONTOLOGY_READ_MODE')
        for state,error in [('FAILED','ONTOLOGY_RELEASE_FAILED'),('REVOKED','CORPUS_RELEASE_REVOKED')]:
            err("BEGIN; UPDATE ontology.corpus_release SET state="+q(state)+" WHERE release_id='duplicates-v1'; SELECT ontology.query_duplicates_v1('duplicates-v1',true); COMMIT",error)
        protected=fingerprint()
        native.run('../cohorts/read_duplicate_input.hwf',dict(RELEASE_ID='duplicates-v1',CLUSTER_ID=family,MEMBER_IDS=POSTING+'002|'+POSTING+'001',PREVIEW='Y'),'duplicates-native-input-read')
        native.run('../cohorts/read_duplicates.hwf',dict(RELEASE_ID='duplicates-v1',PREVIEW='Y'),'duplicates-native-membership-read')
        native.run('../cohorts/read_duplicates.hwf',dict(RELEASE_ID='duplicates-v1',PREVIEW='bad'),'duplicates-native-invalid-preview',False)
        assert fingerprint()==protected,'Read workflows mutated source/proposal/review/graph data'
        native.run('../cohorts/install.hwf',{},'duplicates-native-install-replay')
        assert fingerprint()==protected and report('duplicates-v1')==first
        result=dict(result='PASS',postings=5,original_groups=4,original_duplicate_members=2,
            refresh_reuse=True,cross_release_import='SAME_PROPOSAL_ID',empty_release='FROZEN_ZERO',legacy_source_seal='UNCHANGED',
            changed_source='SOURCE_CHANGED',missing_member='MEMBER_OUTSIDE_RELEASE',
            pending_correction='NO_ACCEPTANCE_FALLBACK',group_replacement='HISTORICAL_MEMBERSHIP_PRESERVED',
            overlap='ATOMIC_REJECTION',graph_seal='BLOCKED_UNTIL_INTEGRATION',read_fingerprint=protected,
            provider_calls=0,production_changes=False,native_log_directory=str(native.WORK))
        (native.WORK/'duplicate-report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    finally:
        subprocess.run(['docker','rm','-fv',native.HOP,run.PG],capture_output=True)
        subprocess.run(['docker','network','rm',native.NET],capture_output=True)

if __name__=='__main__':main()
