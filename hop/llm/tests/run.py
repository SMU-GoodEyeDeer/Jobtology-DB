"""Disposable SQL + native Hop integration checks; never calls a paid model.

Run: python hop/llm/tests/run.py
Requires Docker and openssl. Uses postgres:17-alpine, apache/hop:2.19.0,
neo4j:5.26-community and python:3.13-alpine images.
All fixtures are synthetic Korean postings. Real-data/model quality is a separate evaluation.
"""
from pathlib import Path
import copy
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
PREFIX = 'jobtology-llm-test'
PG, HOP, MOCK, NEO = PREFIX+'-pg', PREFIX+'-hop', PREFIX+'-mock', PREFIX+'-neo'
WORK = Path(tempfile.mkdtemp(prefix='jobtology-llm-tests-'))
REMOTE = '/tmp/llm-test'
def request_count():
    file=WORK/'requests.jsonl'
    return len(file.read_text().splitlines()) if file.exists() else 0

def cmd(args, **kw):
    p=subprocess.run(args, capture_output=True, text=True, **kw)
    if p.returncode: raise RuntimeError(str(args)+': '+p.stderr[-5000:])
    return p

def sql(text):
    return cmd(['docker','exec','-i',PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','hoptest'],input=text).stdout.strip()

def q(value): return "'"+str(value).replace("'","''")+"'"
def js(value): return q(json.dumps(value,ensure_ascii=False))+'::jsonb'

def seed():
    sql('DROP SCHEMA IF EXISTS enrichment CASCADE; DROP SCHEMA IF EXISTS ingestion CASCADE;')
    sql((ROOT/'docs/hop-migration/schema.sql').read_text())
    sql("""CREATE VIEW ingestion.validation_issue AS SELECT NULL::text AS run_id,NULL::text AS issue WHERE false;
CREATE VIEW ingestion.latest_ready_run AS SELECT DISTINCT ON(source_id) * FROM ingestion.run WHERE state='READY' AND mode<>'SMOKE' ORDER BY source_id,created_at DESC,run_id DESC;
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES('test-jobs','job_alio','FULL','test','READY'),('test-ncs','ncs_competency','FULL','test','READY');
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) SELECT run_id,'test','FILE',1 FROM ingestion.run;
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected)
SELECT run_id,'test','test',1,'synthetic.json',repeat('0',64),1,'UTF-8',200,now(),true FROM ingestion.run;
""")
    for posting,n in [
      ('001',dict(title='데이터 엔지니어 채용',eligibility_text='담당 업무: 데이터베이스 설계 및 구축\n필수: SQL 자격증 또는 데이터 자격증 중 하나',preference_text='우대: 데이터 분석 경력',ncs_category_codes='R600020')),
      ('002',dict(title='행정 직원 채용',eligibility_text='학력 및 경력 제한 없음. 자세한 직무는 첨부파일 참조.',ncs_category_codes='R600002'))]:
        for rep in ('list','detail'):
            data=n|dict(posting_id=posting,representation=rep)
            sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES('test-jobs','test',{q(posting+rep)},{q(posting+':'+rep)},'{{}}',{js(data)})")
    for code,name,definition in [('2001020101_24v1','데이터베이스 설계','데이터 요구사항에 따라 데이터베이스를 설계하는 능력'),('2001020102_24v1','데이터베이스 구축','데이터베이스 환경과 테이블을 구축하는 능력'),('0201010101_20v1','사업 기획','사업 계획을 작성하는 능력')]:
        data=dict(code=code,name=name,definition=definition,occupation_code=code[:8],occupation_name='DB엔지니어링',classification_names=['정보통신'],level=4)
        sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES('test-ncs','test',{q(code)},{q(code)},'{{}}',{js(data)})")
    for path in sorted((ROOT/'hop/llm/sql').glob('*.sql')): sql(path.read_text())
    # Reinstallation must preserve everything, including frozen prompt versions.
    for path in sorted((ROOT/'hop/llm/sql').glob('*.sql')): sql(path.read_text())
    if (ROOT/'hop/retention/sql/001_retention.sql').exists():
        sql((ROOT/'docs/hop-migration/operations.sql').read_text())
        sql((ROOT/'hop/retention/sql/001_retention.sql').read_text())

def extraction(source):
    if '담당 업무' not in source.get('eligibility_text',''):
        return dict(positions=[],duties=[],requirements=[],duties_status='attachment_required')
    def ev(field,quote): return dict(field=field,quote=quote)
    duty='데이터베이스 설계 및 구축'
    req='SQL 자격증 또는 데이터 자격증 중 하나'
    return dict(positions=[],duties=[dict(position=None,text=duty,evidence=ev('eligibility_text',duty))],
      requirements=[dict(position=None,category='qualification',importance='required',logic='any_of',text=req,evidence=ev('eligibility_text',req))],duties_status='explicit')

def stage():
    project=WORK/'project';shutil.copytree(ROOT/'hop',project)
    (project/'metadata/rdbms').mkdir(exist_ok=True)
    (project/'metadata/rdbms/jobtology-postgres.json').write_text(json.dumps(dict(name='jobtology-postgres',rdbms={'POSTGRESQL':dict(pluginId='POSTGRESQL',pluginName='PostgreSQL',accessType=0,hostname='',databaseName='',port='5432',manualUrl=f'jdbc:postgresql://{PG}:5432/hoptest',username='postgres',password='',sshTunnelEnabled=False,attributes={'SUPPORTS_BOOLEAN_DATA_TYPE':'Y','SUPPORTS_TIMESTAMP_DATA_TYPE':'Y'})})))
    (project/'metadata/neo4j-connection').mkdir(exist_ok=True)
    (project/'metadata/neo4j-connection/jobtology-neo4j.json').write_text(json.dumps(dict(name='jobtology-neo4j',server=NEO,databaseName='neo4j',boltPort='7687',username='neo4j',password='test-auth-disabled',automatic=False,routing=False,usingEncryption=False,manualUrls=['bolt://'+NEO+':7687'],connectionTimeout='10000',maxTransactionRetryTime='0')))
    config=WORK/'config';config.mkdir()
    (config/'hop-config.json').write_text(json.dumps(dict(projectsConfig=dict(enabled=True,projectMandatory=True,defaultProject='llm-test',projectConfigurations=[dict(projectName='llm-test',projectHome=REMOTE+'/project',configFilename='project-config.json',readOnly=False)],lifecycleEnvironments=[],projectLifecycles=[]))))
    (WORK/'key.csv').write_text('api_key\ndummy-test-key\n')
    cmd(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(WORK/'key.pem'),'-out',str(WORK/'cert.pem'),'-days','1','-subj','/CN='+MOCK,'-addext','subjectAltName=DNS:'+MOCK])
    subprocess.run(['docker','rm','-f',MOCK],capture_output=True)
    cmd(['docker','run','-d','--name',MOCK,'--network',PREFIX,'-v',str(WORK)+':/test','-v',str(ROOT/'hop/llm/tests/mock_server.py')+':/mock.py:ro','python:3.13-alpine','python','/mock.py'])
    cmd(['docker','exec','-u','root',HOP,'mkdir','-p',REMOTE])
    for path in (project,config,WORK/'key.csv',WORK/'cert.pem'):cmd(['docker','cp',str(path),HOP+':'+REMOTE+'/'])
    cmd(['docker','exec','-u','root',HOP,'rm','-f',REMOTE+'/truststore'])
    cmd(['docker','exec','-u','root',HOP,'keytool','-importcert','-noprompt','-alias','llm-test','-file',REMOTE+'/cert.pem','-keystore',REMOTE+'/truststore','-storepass','test-only'])
    cmd(['docker','exec','-u','root',HOP,'chown','-R','hop:hop',REMOTE])
    return f'https://{MOCK}:8443/chat/completions'

def run_hop(file,params,name):
    p=subprocess.run(['docker','exec','-e','HOP_CONFIG_FOLDER='+REMOTE+'/config','-e','HOP_OPTIONS=-Xmx768m -Djavax.net.ssl.trustStore='+REMOTE+'/truststore -Djavax.net.ssl.trustStorePassword=test-only','-w','/opt/hop',HOP,'bash','hop-run.sh','-j','llm-test','-r','llm-local','-f',REMOTE+'/project/llm/'+file,'-p',','.join(k+'='+str(v) for k,v in params.items()),'-l','Basic'],text=True,capture_output=True)
    (WORK/(name+'.log')).write_text(p.stdout+p.stderr)
    assert p.returncode==0,(name,(p.stdout+p.stderr)[-6000:])
    assert 'dummy-test-key' not in p.stdout+p.stderr,'Credential leaked to log'
    print(name,'passed',flush=True)

def unit_checks():
    good=extraction(dict(eligibility_text='담당 업무: 데이터베이스 설계 및 구축\n필수: SQL 자격증 또는 데이터 자격증 중 하나'))
    source=json.loads(sql("SELECT source_data FROM enrichment.test_case WHERE posting_id='001' LIMIT 1"))
    assert sql(f"SELECT enrichment.output_issues('extract',{js(good)},{js(source)},NULL,'[]',8)")=='[]'
    bad=copy.deepcopy(good);bad['duties'][0]['evidence']['quote']='존재하지 않는 업무'
    assert 'UNSUPPORTED_EVIDENCE' in sql(f"SELECT enrichment.output_issues('extract',{js(bad)},{js(source)},NULL,'[]',8)")
    bad=copy.deepcopy(good);bad['requirements'][0]['evidence']=dict(field='preference_text',quote='우대: 데이터 분석 경력');bad['requirements'][0]['text']='데이터 분석 경력'
    assert 'PREFERENCE_AS_REQUIRED' in sql(f"SELECT enrichment.output_issues('extract',{js(bad)},{js(source)},NULL,'[]',8)")
    for bad in [[],{},good|dict(extra=True),good|dict(duties=None),good|dict(duties_status=4)]:
        assert sql(f"SELECT enrichment.schema_issues({js(bad)},output_schema) FROM enrichment.prompt WHERE version='ko-v1' AND stage='extract'")!='[]'
    outside=dict(matches=[dict(competency_code='invented',duty_index=4,reason='fake')],outcome='matched')
    issues=sql(f"SELECT enrichment.output_issues('categorize',{js(outside)},'{"{}"}',{js(good)},'[]',8)")
    assert 'UNKNOWN_DUTY' in issues and 'CODE_OUTSIDE_SHORTLIST' in issues
    print('Independent schema/evidence/category checks passed',flush=True)

def gold_checks():
    labels=dict(requirements=[dict(field='eligibility_text',quote='SQL 자격증 또는 데이터 자격증 중 하나',category='qualification',importance='required',logic='any_of')],
      duties=[dict(field='eligibility_text',quote='데이터베이스 설계 및 구축')],ncs_codes=['2001020101_24v1'],requirements_complete=True,duties_complete=True,ncs_complete=True)
    empty=dict(requirements=[],duties=[],ncs_codes=[],requirements_complete=False,duties_complete=True,ncs_complete=True)
    document=dict(dataset_id='test-ko',reviewer='synthetic-fixture-author',cases=[dict(posting_id='001',labels=labels),dict(posting_id='002',labels=empty)])
    (WORK/'gold.json').write_text(json.dumps(document,ensure_ascii=False))
    cmd(['docker','cp',str(WORK/'gold.json'),HOP+':'+REMOTE+'/gold.json'])
    run_hop('import_gold.hwf',dict(GOLD_FILE=REMOTE+'/gold.json'),'import-gold')
    assert sql('SELECT count(*) FROM enrichment.gold')=='2'

def response_checks(params):
    settings=json.loads(sql('SELECT settings FROM enrichment.batch ORDER BY created_at DESC LIMIT 1'))
    settings['max_requests']=30;settings['max_cost_usd']=5
    bid=str(uuid.uuid4())
    sql(f"SELECT enrichment.plan_batch({q(bid)},'EVAL','test-ko','LATEST','LATEST',{js(settings)}); SELECT enrichment.plan_stage({q(bid)},'extract')")
    aid=sql(f"SELECT attempt_id FROM enrichment.attempt WHERE batch_id={q(bid)} ORDER BY item_id LIMIT 1")
    sql(f'SELECT enrichment.reserve_request({q(aid)})')
    try:sql(f'SELECT enrichment.reserve_request({q(aid)})');raise AssertionError('Duplicate request reservation allowed')
    except RuntimeError as e:assert 'REQUEST_NOT_PLANNED' in str(e)
    sql(f"SELECT enrichment.save_response({q(aid)},429,'{{\"error\":{{\"message\":\"rate limited\"}}}}',20)")
    assert sql(f'SELECT state FROM enrichment.attempt WHERE attempt_id={q(aid)}')=='ERROR'
    assert sql(f'SELECT cost_usd IS NULL AND reserved_usd>0 FROM enrichment.attempt WHERE attempt_id={q(aid)}')=='t'
    pending=sql(f"SELECT attempt_id FROM enrichment.attempt WHERE batch_id={q(bid)} AND state='PLANNED' LIMIT 1")
    sql(f'SELECT enrichment.reserve_request({q(pending)})')
    assert sql(f"SELECT state='ERROR' AND reserved_at IS NULL AND reserved_usd=0 AND http_status IS NULL AND issues ? 'NOT_SENT_AFTER_PROVIDER_ERROR' FROM enrichment.attempt WHERE attempt_id={q(pending)}")=='t'
    # Provider selection is validated, reaches the JSON request, and changes its cache key.
    provider_keys=[]
    for provider in (None,'deepinfra','fireworks'):
        other=str(uuid.uuid4());options=settings.copy()
        options.pop('provider_only',None)
        if provider: options['provider_only']=provider
        sql(f"SELECT enrichment.plan_batch({q(other)},'EVAL','test-ko','LATEST','LATEST',{js(options)}); SELECT enrichment.plan_stage({q(other)},'extract')")
        request=json.loads(sql(f"SELECT request_body FROM enrichment.attempt WHERE batch_id={q(other)} LIMIT 1"))
        assert request['provider']==dict(require_parameters=True,allow_fallbacks=False,**({'only':[provider]} if provider else {}))
        provider_keys.append(sql(f"SELECT a.cache_key FROM enrichment.attempt a JOIN enrichment.item i USING(item_id) WHERE a.batch_id={q(other)} AND i.posting_id='001'"))
    assert len(set(provider_keys))==3,'Provider changes must invalidate the output cache'
    for invalid in ('','DeepInfra','deepinfra,fireworks','https://example.com',[],None):
        try:
            sql(f"SELECT enrichment.plan_batch({q(str(uuid.uuid4()))},'EVAL','test-ko','LATEST','LATEST',{js(settings|dict(provider_only=invalid))})")
            raise AssertionError('Invalid provider slug accepted')
        except RuntimeError as e: assert 'INVALID_PROVIDER_SLUG' in str(e)
    # Exercise malformed JSON, truncation, refusal, schema violations and duplicate keys
    # against independent response envelopes, without using the model/mock server.
    failures=[('not-json','INVALID_RESPONSE_JSON'),
      (json.dumps(dict(choices=[dict(finish_reason='length',message=dict(content='{}'))])),'INCOMPLETE_OR_REFUSED'),
      (json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='{}',refusal='cannot'))])),'INCOMPLETE_OR_REFUSED'),
      (json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='{}'))])),'REQUIRED'),
      ('{"choices":[],"choices":[]}','INVALID_RESPONSE_JSON')]
    for raw,issue in failures:
        other=str(uuid.uuid4());sql(f"SELECT enrichment.plan_batch({q(other)},'EVAL','test-ko','LATEST','LATEST',{js(settings)}); SELECT enrichment.plan_stage({q(other)},'extract')")
        att=sql(f'SELECT attempt_id FROM enrichment.attempt WHERE batch_id={q(other)} LIMIT 1')
        sql(f'SELECT enrichment.reserve_request({q(att)}); SELECT enrichment.save_response({q(att)},200,{q(raw)},1)')
        assert issue in sql(f'SELECT issues FROM enrichment.attempt WHERE attempt_id={q(att)}')
    sql(f'SELECT enrichment.finish_batch({q(bid)})')
    print('Reservation, unknown-charge, malformed/refused/truncated response checks passed',flush=True)

def neo(query):return cmd(['docker','exec',NEO,'cypher-shell','--format','plain',query]).stdout

def graph_checks(params):
    for _ in range(60):
        try:neo('RETURN 1;');break
        except RuntimeError:time.sleep(.5)
    neo("CREATE (:jobPosting {id:'job-alio:posting:001'}),(:jobPosting {id:'job-alio:posting:002'}),(:ncsCompetency {id:'ncs:unit:2001020101_24v1'});")
    eval_item=sql("SELECT item_id FROM enrichment.result WHERE mode='EVAL' AND state='VALIDATED' LIMIT 1")
    try:sql(f"SELECT enrichment.review_item({q(eval_item)},'ACCEPT','tester')");raise AssertionError('EVAL accepted into publication')
    except RuntimeError as e:assert 'ONLY_VALIDATED_ENRICH' in str(e)
    run_hop('enrich.hwf',params|dict(REUSE_CACHE='Y'),'enrich-for-review')
    batch=sql("SELECT batch_id FROM enrichment.batch WHERE mode='ENRICH' ORDER BY created_at DESC LIMIT 1")
    item=sql(f"SELECT item_id FROM enrichment.item WHERE batch_id={q(batch)} AND posting_id='001'")
    run_hop('review_item.hwf',dict(ITEM_ID=item,DECISION='ACCEPT',REVIEWER='fixture-author'),'accept-enrichment')
    run_hop('publish_reviewed.hwf',dict(BATCH_ID=batch),'publish-reviewed')
    assert '1' in neo("MATCH (:jobEnrichment {state:'READY',decision:'ACCEPT'})-[r:ALIGNS_WITH_NCS {accepted:true}]->() RETURN count(r);")
    before=neo('MATCH (n) RETURN count(n);')+neo('MATCH ()-[r]->() RETURN count(r);')
    run_hop('publish_reviewed.hwf',dict(BATCH_ID=batch),'repeat-graph')
    assert before==neo('MATCH (n) RETURN count(n);')+neo('MATCH ()-[r]->() RETURN count(r);')
    run_hop('review_item.hwf',dict(ITEM_ID=item,DECISION='REJECT',REVIEWER='fixture-author'),'reject-enrichment')
    run_hop('publish_reviewed.hwf',dict(BATCH_ID=batch),'sync-rejection')
    assert neo("MATCH (e:jobEnrichment {decision:'REJECT'})-[r:ALIGNS_WITH_NCS]->() RETURN r.accepted;").strip().lower().endswith('false')
    assert sql(f'SELECT enrichment_id IS NULL FROM enrichment.current_posting WHERE posting_id=\'001\'')=='t'
    # A new source snapshot with changed content must not reuse the old extraction.
    sql("""INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES('test-jobs-v2','job_alio','FULL','test','READY');
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES('test-jobs-v2','test','FILE',1);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected)
VALUES('test-jobs-v2','test','test',1,'changed-synthetic.json',repeat('0',64),1,'UTF-8',200,now(),true);
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
SELECT 'test-jobs-v2',document_id,locator,source_record_id,source_payload,
CASE WHEN normalized->>'posting_id'='001' THEN normalized||'{"title":"변경된 데이터 엔지니어 채용"}'::jsonb ELSE normalized END
FROM ingestion.record WHERE run_id='test-jobs';""")
    settings=json.loads(sql(f'SELECT settings FROM enrichment.batch WHERE batch_id={q(batch)}'));settings['execute_requests']='N'
    changed=str(uuid.uuid4());sql(f"SELECT enrichment.plan_batch({q(changed)},'ENRICH',NULL,'LATEST','LATEST',{js(settings)}); SELECT enrichment.plan_stage({q(changed)},'extract')")
    assert sql(f"SELECT a.batch_id={q(changed)} FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.batch_id={q(changed)} AND i.posting_id='001'")=='t'
    assert sql(f"SELECT a.batch_id<>{q(changed)} FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.batch_id={q(changed)} AND i.posting_id='002'")=='t'
    print('EVAL isolation, reviewed publication, idempotence, revocation, changed-content cache checks passed',flush=True)

def policy_and_export_checks(params):
    run_hop('enrich.hwf',params|dict(REUSE_CACHE='Y',ACCEPTANCE_POLICY='VALIDATED'),'automatic-validated-policy')
    bid=sql("SELECT batch_id FROM enrichment.batch WHERE mode='ENRICH' ORDER BY created_at DESC LIMIT 1")
    assert sql(f"SELECT count(*) FROM enrichment.result WHERE batch_id={q(bid)} AND decision='ACCEPT' AND reviewer='policy:validated-v1'")=='2'
    run_hop('evaluate.hwf',params|dict(REUSE_CACHE='Y',ACCEPTANCE_POLICY='VALIDATED'),'eval-isolated-under-auto-policy')
    bid=sql("SELECT batch_id FROM enrichment.batch WHERE mode='EVAL' ORDER BY created_at DESC LIMIT 1")
    assert sql(f"SELECT count(*) FROM enrichment.result WHERE batch_id={q(bid)} AND decision IS NOT NULL")=='0'
    path=REMOTE+'/review-'+uuid.uuid4().hex+'.json'
    run_hop('export_review_file.hwf',dict(DATASET_ID='test-ko',REVIEW_FILE=path),'export-review-file')
    document=json.loads(cmd(['docker','exec',HOP,'cat',path]).stdout)
    assert document['dataset_id']=='test-ko' and len(document['cases'])==2 and document['reviewer']==''
    assert document['cases'][0]['source_data'] and 'labels' in document['cases'][0]
    print('Automatic acceptance, EVAL isolation, and review-file export checks passed',flush=True)

def main():
    try:
        if subprocess.run(['docker','network','inspect',PREFIX],capture_output=True).returncode:
            cmd(['docker','network','create','--internal',PREFIX])
        for name,image,args in [(PG,'postgres:17-alpine',['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=hoptest']), (HOP,'apache/hop:2.19.0',['--entrypoint','/bin/sleep']), (NEO,'neo4j:5.26-community',['-e','NEO4J_AUTH=none','-e','NEO4J_server_memory_heap_initial__size=256m','-e','NEO4J_server_memory_heap_max__size=512m','-e','NEO4J_server_memory_pagecache_size=128m'])]:
            if subprocess.run(['docker','inspect',name],capture_output=True).returncode:
                cmd(['docker','run','-d','--name',name,'--network',PREFIX]+args+[image]+(['infinity'] if name==HOP else []))
        for _ in range(60):
            if subprocess.run(['docker','exec',PG,'psql','-X','-qAt','-U','postgres','-d','hoptest','-c','SELECT 1'],capture_output=True).returncode==0:break
            time.sleep(.25)
        else:
            raise RuntimeError('Disposable PostgreSQL did not finish creating hoptest')
        seed();endpoint=stage()
        neo('MATCH (n) DETACH DELETE n;') if subprocess.run(['docker','exec',NEO,'cypher-shell','--format','plain','RETURN 1;'],capture_output=True).returncode==0 else None
        run_hop('install.hwf',{},'native-installer')
        run_hop('prepare_evaluation.hwf',dict(DATASET_ID='test-ko',DATASET_SIZE=2),'prepare-dataset')
        unit_checks()
        gold_checks()
        run_hop('evaluate.hwf',dict(DATASET_ID='test-ko',POSTING_LIMIT=2,PROMPT_VERSION='ko-v1'),'dry-run')
        assert request_count()==0 and sql('SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL')=='0'
        params=dict(DATASET_ID='test-ko',POSTING_LIMIT=2,PROMPT_VERSION='ko-v1',EXECUTE_REQUESTS='Y',ENDPOINT=endpoint,API_KEY_FILE=REMOTE+'/key.csv',EXTRACT_MODEL='test/extractor',CATEGORIZE_MODEL='test/categorizer',PROVIDER_ONLY='deepinfra',REQUEST_DELAY_MS=1,READ_TIMEOUT_MS=5000)
        run_hop('evaluate.hwf',params,'native-two-stage')
        assert request_count()==3,f'Expected two extracts and one categorization, got {request_count()}'
        assert all(json.loads(line)['provider']['only']==['deepinfra'] for line in (WORK/'requests.jsonl').read_text().splitlines())
        report=json.loads(sql("SELECT row_to_json(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1"))
        assert report['state']=='COMPLETE' and report['validated']==2 and report['requests']==3,report
        assert report['labeled_postings']==2 and report['requirement_recall']==1 and report['ncs_precision']==1 and report['correct_abstentions']==1,report
        run_hop('evaluate.hwf',params|dict(REUSE_CACHE='Y'),'cache-repeat')
        assert request_count()==3,'Unchanged output was charged again'
        assert sql("SELECT extraction_cache_hits FROM enrichment.batch_report ORDER BY created_at DESC LIMIT 1")=='2'
        run_hop('evaluate.hwf',params|dict(MAX_REQUESTS=1),'request-budget')
        assert request_count()==4,'Request cap did not stop calls'
        assert sql("SELECT state FROM enrichment.batch_report ORDER BY created_at DESC LIMIT 1")=='PARTIAL'
        run_hop('evaluate.hwf',params|dict(EXTRACT_MODEL='test/rate-limited'),'rate-limit-stops-batch')
        limited=[json.loads(line) for line in (WORK/'requests.jsonl').read_text().splitlines() if json.loads(line)['model']=='test/rate-limited']
        assert {r['trace']['posting_id'] for r in limited}=={'001'},'Later postings were sent after a rate limit'
        assert len({r['trace']['attempt_id'] for r in limited})==1
        # Hop 2.19's HttpClient5 repeats HTTP 429 once below the transform's
        # retryTimes=0 setting. This is an upstream transport limitation, not a
        # second reserved attempt; retain this observable behavior in the test.
        assert len(limited)==2,'Revisit the documented Hop 2.19 HTTP retry limitation'
        assert sql("SELECT requests=1 AND state='PARTIAL' FROM enrichment.batch_report ORDER BY created_at DESC LIMIT 1")=='t'
        assert sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id=(SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1) AND reserved_at IS NULL AND issues ? 'NOT_SENT_AFTER_PROVIDER_ERROR'")=='1'
        response_checks(params)
        graph_checks(params)
        policy_and_export_checks(params)
        from v2_checks import check_v2
        check_v2(sql,js,q,run_hop,params,neo)
        from v3_checks import check_v3
        check_v3(sql,js,q,run_hop,params,neo)
        from v4_checks import check_v4
        check_v4(sql,js,q,run_hop,params,neo)
        from budget_checks import check_budget
        check_budget(sql,js,q)
        from review_checks import check_review
        check_review(sql,js,q,run_hop,params,cmd,HOP,REMOTE,WORK)
        from v5_checks import check_v5
        check_v5(sql,js,q,run_hop,params,request_count)
        from v6_checks import check_v6_native
        check_v6_native(sql,js,q,run_hop,params,request_count)
        from revision_link_checks import check_revision_links
        import sys
        check_revision_links(sys.modules[__name__],params)
        from repair_selection_checks import check_repair_selection, check_repair_selection_native
        check_repair_selection(sql,js,q)
        check_repair_selection_native(sys.modules[__name__])
        from rule_interpretation_checks import check_rule_interpretation
        check_rule_interpretation(sys.modules[__name__])
        from v7_checks import check_v7_native
        check_v7_native(sql,js,q,run_hop,params,request_count)
        from busy_wait_checks import check_busy_wait
        check_busy_wait(sys.modules[__name__])
        print('ALL CHECKS PASSED. Logs:',WORK,flush=True)
    finally:
        if not os.environ.get('KEEP_LLM_TEST_CONTAINERS'):
            subprocess.run(['docker','rm','-fv',HOP,PG,MOCK,NEO],capture_output=True)
            subprocess.run(['docker','network','rm',PREFIX],capture_output=True)

if __name__=='__main__':main()
