"""Destructive fixtures ONLY in dedicated disposable containers. No live data, credentials or APIs."""
from pathlib import Path
import json,os,shutil,subprocess,tempfile,time,uuid,hashlib
import xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3]
PREFIX='jobtology-retention-test';PG=PREFIX+'-pg';HOP=PREFIX+'-hop';NEO=PREFIX+'-neo'
WORK=Path(tempfile.mkdtemp(prefix=PREFIX+'-'));REMOTE='/tmp/retention-test'
def cmd(args,**kw):
 p=subprocess.run(args,text=True,capture_output=True,**kw)
 if p.returncode:raise RuntimeError(str(args)+': '+p.stderr[-5000:]+p.stdout[-1500:])
 return p.stdout.strip()
def sql(s):return cmd(['docker','exec','-i',PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','hoptest'],input=s)
def q(s):return "'"+str(s).replace("'","''")+"'"
def js(o):return q(json.dumps(o,ensure_ascii=False))+'::jsonb'
def neo(s):return cmd(['docker','exec',NEO,'cypher-shell','--format','plain',s])
def fail(s,expected):
 try:sql(s)
 except RuntimeError as e:assert expected in str(e),str(e)
 else:raise AssertionError('Expected '+expected)
def run(file,params,name,ok=True):
 p=subprocess.run(['docker','exec','-e','HOP_CONFIG_FOLDER='+REMOTE+'/config','-e','HOP_OPTIONS=-Xmx768m','-w','/opt/hop',HOP,'bash','hop-run.sh','-j','retention-test','-r','retention-local','-f',REMOTE+'/project/'+file,'-p',','.join(k+'='+str(v) for k,v in params.items()),'-l','Basic'],text=True,capture_output=True)
 (WORK/(name+'.log')).write_text(p.stdout+p.stderr)
 assert (p.returncode==0)==ok,(name,(p.stdout+p.stderr)[-6500:])
 print(name,'passed',flush=True)
def stage():
 project=WORK/'project';shutil.copytree(ROOT/'hop',project)
 (project/'metadata/rdbms').mkdir(exist_ok=True)
 (project/'metadata/rdbms/jobtology-postgres.json').write_text(json.dumps(dict(name='jobtology-postgres',rdbms={'POSTGRESQL':dict(pluginId='POSTGRESQL',pluginName='PostgreSQL',accessType=0,hostname='',databaseName='',port='5432',manualUrl=f'jdbc:postgresql://{PG}:5432/hoptest',username='postgres',password='',sshTunnelEnabled=False,attributes={'SUPPORTS_BOOLEAN_DATA_TYPE':'Y','SUPPORTS_TIMESTAMP_DATA_TYPE':'Y'})})))
 (project/'metadata/neo4j-connection').mkdir(exist_ok=True)
 (project/'metadata/neo4j-connection/jobtology-neo4j.json').write_text(json.dumps(dict(name='jobtology-neo4j',server=NEO,databaseName='neo4j',boltPort='7687',username='neo4j',password='unused',automatic=False,routing=False,usingEncryption=False,manualUrls=['bolt://'+NEO+':7687'],connectionTimeout='10000',maxTransactionRetryTime='0')))
 config=WORK/'config';config.mkdir()
 (config/'hop-config.json').write_text(json.dumps(dict(projectsConfig=dict(enabled=True,projectMandatory=True,defaultProject='retention-test',projectConfigurations=[dict(projectName='retention-test',projectHome=REMOTE+'/project',configFilename='project-config.json',readOnly=False)],lifecycleEnvironments=[],projectLifecycles=[]))))
 cmd(['docker','exec','-u','root',HOP,'mkdir','-p',REMOTE])
 for path in (project,config):cmd(['docker','cp',str(path),HOP+':'+REMOTE+'/'])
 cmd(['docker','exec','-u','root',HOP,'chown','-R','hop:hop',REMOTE])

def seed():
 sql((ROOT/'docs/hop-migration/schema.sql').read_text())
 sql("CREATE VIEW ingestion.validation_issue AS SELECT NULL::text AS run_id,NULL::text AS issue WHERE false;")
 sql((ROOT/'docs/hop-migration/operations.sql').read_text())
 for f in sorted((ROOT/'hop/llm/sql').glob('*.sql')):sql(f.read_text())
 ids=[]; graph_statements=[]
 for index,age in enumerate([70,60,50,40,30,20,10,0]):
  rid=str(uuid.uuid4());ids.append(rid)
  path=f'{REMOTE}/project/data/job-alio-raw/{rid}/index/page-1.json'
  sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at) VALUES({q(rid)},'job_alio','FULL','fixture','READY',now()-interval '{age} days'); INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(rid)},'index','FILE',1); INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) VALUES({q(rid)},'doc','index',1,{q(rid+'/index/page-1.json')},'{hashlib.sha256(b"{}").hexdigest()}',2,'UTF-8',200,now()-interval '{age} days',true); INSERT INTO ingestion.graph_export(run_id,loader_version) VALUES({q(rid)},'fixture');")
  cmd(['docker','exec','-u','hop',HOP,'mkdir','-p',str(Path(path).parent)])
  cmd(['docker','exec','-i','-u','hop',HOP,'tee',path],input='{}')
  postings=['A']+(['B'] if index<2 else [])
  for posting in postings:
   for representation in ('list','detail'):
    data=dict(kind='JobPosting',posting_id=posting,representation=representation,title='한국어 채용 '+posting,eligibility_text='SQL 필수 '+str(index))
    recid=sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(rid)},'doc',{q(posting+representation)},{q(posting+':'+representation)},{js(data)},{js(data)}) RETURNING record_id")
    gid='hop:'+rid+':'+recid
    graph_statements.append(f"MERGE (b:ingestionBatch {{id:'{rid}'}}) SET b.source_id='job_alio',b.state='READY',b.serving_scope='STAGING' MERGE (e:entity:jobPosting {{id:'job-alio:posting:{posting}'}}) SET e.name='한국어 채용 {posting}' CREATE (r:ingestionRecord {{id:'{gid}',source_id:'job_alio'}}) CREATE (b)-[:HAS_RECORD]->(r) CREATE (r)-[:REFERS_TO {{field:'posting_id'}}]->(e);")
 neo('\n'.join(graph_statements))
 # Shared LLM graph entity must survive source cleanup.
 neo("MATCH (p:jobPosting {id:'job-alio:posting:B'}) CREATE (p)-[:HAS_ENRICHMENT]->(:jobEnrichment {id:'preserve-me',state:'READY'});")
 return ids

def preview(mode,n,keep=2):
 id=str(uuid.uuid4());sql(f"SELECT retention.preview({q(id)},'job_alio',{q(mode)},{n},{keep},{q(REMOTE+'/project/data')})")
 return id

def checks(ids):
 # Match every deployed source workflow's RAW_ROOT default, including ncs-raw.
 for directory,source in [('alio','alio_organization'),('job_alio','job_alio'),('ncs_competency','ncs_competency'),('ncs_qualification','ncs_qualification'),('qnet_schedule','qnet_schedule'),('ncs_career_path','ncs_career_path')]:
  root=E.parse(ROOT/f'hop/ingestions/{directory}/full.hwf').findtext('parameters/parameter[name="RAW_ROOT"]/default_value').replace('${PROJECT_HOME}',REMOTE+'/project')
  assert sql(f"SELECT retention.resolve_raw_path({q(source)},{q(REMOTE+'/project/data')},'run/example.json')")==root+'/run/example.json'
 # Reinstallation and native preview do not delete a single source or raw file.
 before=sql('SELECT count(*) FROM ingestion.record')
 run('retention/install.hwf',{},'native-installer-repeat')
 run('retention/preview.hwf',dict(SOURCE_ID='job_alio',SELECTION_MODE='OLDEST_COUNT',AMOUNT=2),'preview-two')
 p=sql('SELECT plan_id FROM retention.plan ORDER BY created_at DESC LIMIT 1')
 assert sql('SELECT count(*) FROM ingestion.record')==before
 assert sql(f"SELECT count(*) FROM retention.plan_run WHERE plan_id={q(p)} AND selected")=='2'
 assert sql(f"SELECT string_agg(run_id,',' ORDER BY created_at) FROM retention.plan_run WHERE plan_id={q(p)} AND selected")==','.join(ids[:2])
 age=preview('OLDER_THAN_DAYS',45)
 assert sql(f"SELECT count(*) FROM retention.plan_run WHERE plan_id={q(age)} AND selected")=='3'
 # New references invalidate a saved plan; they must not silently change its candidates.
 sql(f"INSERT INTO ingestion.dependency VALUES({q(ids[-1])},'job_alio',{q(ids[0])})")
 fail(f"SELECT retention.begin_execution({q(p)},'owner',{q(REMOTE+'/project/data')})",'STALE_PLAN')
 protected=preview('OLDEST_COUNT',1)
 assert sql(f"SELECT run_id FROM retention.plan_run WHERE plan_id={q(protected)} AND selected")==ids[1]
 sql(f"DELETE FROM ingestion.dependency WHERE input_run_id={q(ids[0])}")
 # Frozen evaluation batches and the rolling request ledger pin runs.
 sql(f"INSERT INTO enrichment.dataset VALUES('protected',{q(ids[2])},{q(ids[3])},'test',1,now())")
 assert sql(f'SELECT retention.protection({q(ids[2])},2)')=='EVALUATION_DATASET'
 sql(f"INSERT INTO ingestion.request_attempt(run_id,source_id,partition_id,page_no,confirmation_no) VALUES({q(ids[4])},'job_alio','index',1,0) ON CONFLICT(run_id,partition_id,page_no,confirmation_no) DO UPDATE SET reserved_at=clock_timestamp()")
 assert sql(f'SELECT retention.protection({q(ids[4])},2)')=='REQUEST_QUOTA_WINDOW'
 sql("SELECT retention.enter_writer('busy-writer','fixture','fixture')")
 fail(f"SELECT retention.begin_execution({q(p)},'owner',{q(REMOTE+'/project/data')})",'WRITERS_BUSY')
 sql("SELECT retention.leave_writer('busy-writer')")
 # Unsafe path is rejected before maintenance or graph/file writes.
 old=sql(f"SELECT raw_path FROM ingestion.document WHERE run_id={q(ids[0])}")
 sql(f"UPDATE ingestion.document SET raw_path={q(REMOTE+'/project/data/job-alio-raw/'+ids[0]+'/../other.json')} WHERE run_id={q(ids[0])}")
 unsafe=preview('OLDEST_COUNT',1)
 fail(f"SELECT retention.begin_execution({q(unsafe)},'owner',{q(REMOTE+'/project/data')})",'UNSAFE_RAW_PATH')
 sql(f"UPDATE ingestion.document SET raw_path={q(old)} WHERE run_id={q(ids[0])}")
 # Enter and release a synthetic crashed executor; maintenance must remain active.
 sql(f"SELECT retention.begin_execution({q(p)},'owner',{q(REMOTE+'/project/data')})")
 fail(f"SELECT retention.begin_execution({q(p)},'second',{q(REMOTE+'/project/data')})",'EXECUTOR_ALREADY_RUNNING')
 fail("SELECT retention.enter_writer('blocked','test','test')",'RETENTION_ACTIVE')
 fail("UPDATE ingestion.run SET policy_revision='changed'",'RETENTION_ACTIVE')
 sql(f"SELECT retention.release_executor({q(p)},'owner')")
 fail("UPDATE ingestion.run SET policy_revision='changed'",'RETENTION_ACTIVE')
 assert sql('SELECT count(*) FROM ingestion.refresh_queue')=='0'
 # Failure after archive: wrong ownership must stop before files/PG deletion, then resume.
 neo(f"MATCH (b:ingestionBatch {{id:'{ids[0]}'}}) SET b.serving_scope='WRONG'")
 run('retention/execute.hwf',dict(PLAN_ID=p),'ownership-failure',False)
 assert 'Graph ownership/count verification failed' in (WORK/'ownership-failure.log').read_text()
 assert sql('SELECT count(*) FROM ingestion.record')==before
 assert sql(f"SELECT owner_id IS NULL AND state='ACTIVE' FROM retention.plan WHERE plan_id={q(p)}")=='t'
 neo(f"MATCH (b:ingestionBatch {{id:'{ids[0]}'}}) SET b.serving_scope='STAGING'")
 # A file may already be absent after an interrupted deletion before its checkpoint.
 raw_file=sql(f"SELECT raw_path FROM retention.plan_file WHERE plan_id={q(p)} AND run_id={q(ids[0])}")
 cmd(['docker','exec',HOP,'rm',raw_file])
 run('retention/execute.hwf',dict(PLAN_ID=p),'execute-resume')
 assert sql(f"SELECT state FROM retention.plan WHERE plan_id={q(p)}")=='COMPLETE'
 assert sql('SELECT count(*) FROM ingestion.run')=='6'
 assert sql('SELECT count(*) FROM retention.archive_record')=='4'
 assert sql("SELECT normalized->>'eligibility_text' FROM retention.last_known_job_posting WHERE posting_id='B'")=='SQL 필수 1'
 assert sql("SELECT archived AND NOT in_latest_snapshot FROM retention.last_known_job_posting WHERE posting_id='B'")=='t'
 assert sql("SELECT NOT archived AND in_latest_snapshot FROM retention.last_known_job_posting WHERE posting_id='A'")=='t'
 assert '4' in neo("MATCH (a:archivedRecord {state:'READY'}) RETURN count(a);")
 assert '2' in neo('MATCH (e:jobPosting) RETURN count(e);')
 assert '1' in neo("MATCH (:jobEnrichment {id:'preserve-me'}) RETURN count(*);")
 assert '6' in neo('MATCH (b:ingestionBatch) RETURN count(b);')
 assert sql(f"SELECT count(*) FROM retention.plan_file WHERE plan_id={q(p)} AND deleted_at IS NULL")=='0'
 assert cmd(['docker','exec',HOP,'test','!','-e',raw_file])==''
 # Idempotent execution of a completed plan must not select or delete extra runs.
 run('retention/execute.hwf',dict(PLAN_ID=p),'completed-plan-noop')
 assert sql('SELECT count(*) FROM ingestion.run')=='6'
 # An invalid graph load must release the writer lease on its error path.
 run('graph/load_snapshot.hwf',dict(RUN_ID='no-such-run'),'guarded-graph-failure',False)
 assert sql('SELECT count(*) FROM retention.writer')=='0'
 print('ALL RETENTION CHECKS PASSED. Logs:',WORK,flush=True)

def extra_checks():
 # A subsequent plan replaces only the archived A version, preserving disappeared B.
 p=preview('OLDEST_COUNT',1)
 run('retention/execute.hwf',dict(PLAN_ID=p),'second-plan-updates-archive')
 assert sql("SELECT record_payload->'normalized'->>'eligibility_text' FROM retention.archive_record WHERE source_record_id='A:list'")=='SQL 필수 5'
 assert sql("SELECT record_payload->'normalized'->>'eligibility_text' FROM retention.archive_record WHERE source_record_id='B:list'")=='SQL 필수 1'
 assert sql('SELECT count(*) FROM retention.archive_record')=='4'
 old=str(uuid.uuid4());latest=str(uuid.uuid4());oldpath=None
 for rid,age,year in [(old,50,2025),(latest,0,2026)]:
  path=f'{REMOTE}/project/data/qnet_schedule-raw/{rid}/Q001/page-1.json'
  if rid==old:oldpath=path
  data=dict(kind='ExamSession',qualification_code='Q001',year=year,round='1',category_code='1',name='한국어 자격 시험')
  sid=f'Q001:{year}:1:1'
  sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at) VALUES({q(rid)},'qnet_schedule','FULL','fixture','READY',now()-interval '{age} days'); INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(rid)},'Q001','FILE',1); INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) VALUES({q(rid)},'doc','Q001',1,{q(rid+'/Q001/page-1.json')},'{hashlib.sha256(b"{}").hexdigest()}',2,'UTF-8',200,now()-interval '{age} days',true); INSERT INTO ingestion.graph_export(run_id,loader_version) VALUES({q(rid)},'fixture');")
  rec=sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(rid)},'doc','1',{q(sid)},{js(data)},{js(data)}) RETURNING record_id")
  cmd(['docker','exec',HOP,'mkdir','-p',str(Path(path).parent)])
  cmd(['docker','exec','-i',HOP,'tee',path],input='{}')
  neo(f"CREATE (b:ingestionBatch {{id:'{rid}',source_id:'qnet_schedule',state:'READY',serving_scope:'STAGING'}}) CREATE (r:ingestionRecord {{id:'hop:{rid}:{rec}'}}) MERGE (e:entity:qualification {{id:'qnet:qualification:Q001'}}) CREATE (b)-[:HAS_RECORD]->(r) CREATE (r)-[:REFERS_TO {{field:'qualification_code'}}]->(e);")
 p=str(uuid.uuid4());sql(f"SELECT retention.preview({q(p)},'qnet_schedule','OLDER_THAN_DAYS',30,1,{q(REMOTE+'/project/data')})")
 assert sql(f"SELECT run_id FROM retention.plan_run WHERE plan_id={q(p)} AND selected")==old
 cmd(['docker','exec','-i',HOP,'tee',oldpath],input='unexpected changed bytes')
 run('retention/execute.hwf',dict(PLAN_ID=p),'changed-raw-file-blocked',False)
 assert 'hash or deletion verification failed' in (WORK/'changed-raw-file-blocked.log').read_text()
 assert sql(f"SELECT count(*) FROM ingestion.run WHERE run_id={q(old)}")=='1'
 assert cmd(['docker','exec',HOP,'cat',oldpath])=='unexpected changed bytes'
 assert sql(f"SELECT graph_deleted FROM retention.plan_run WHERE plan_id={q(p)} AND selected")=='t'
 cmd(['docker','exec','-i',HOP,'tee',oldpath],input='{}')
 run('retention/execute.hwf',dict(PLAN_ID=p),'qnet-age-resume')
 assert sql("SELECT count(*) FROM retention.last_known_record WHERE source_id='qnet_schedule'")=='2'
 assert sql("SELECT normalized->>'year' FROM retention.last_known_record WHERE source_id='qnet_schedule' AND archived")=='2025'
 assert sql("SELECT count(*) FROM retention.plan WHERE state='ACTIVE'")=='0'
 print('Archive replacement, Q-Net age deletion and changed-file recovery passed. Logs:',WORK,flush=True)

def main():
 try:
  cmd(['docker','network','create','--internal',PREFIX])
  for name,image,args in [(PG,'postgres:17-alpine',['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=hoptest']),(HOP,'apache/hop:2.19.0',['--entrypoint','/bin/sleep']),(NEO,'neo4j:5.26-community',['-e','NEO4J_AUTH=none','-e','NEO4J_server_memory_heap_initial__size=256m','-e','NEO4J_server_memory_heap_max__size=512m','-e','NEO4J_server_memory_pagecache_size=128m'])]:
   cmd(['docker','run','-d','--name',name,'--network',PREFIX]+args+[image]+(['infinity'] if name==HOP else []))
  for _ in range(60):
   try:sql('SELECT 1');neo('RETURN 1');break
   except RuntimeError:time.sleep(.5)
  stage();ids=seed()
  sql((ROOT/'hop/retention/sql/001_retention.sql').read_text())
  checks(ids);extra_checks()
 finally:
  if not os.environ.get('KEEP_RETENTION_TEST_CONTAINERS'):
   subprocess.run(['docker','rm','-fv',HOP,PG,NEO],capture_output=True)
   subprocess.run(['docker','network','rm',PREFIX],capture_output=True)
if __name__=='__main__':main()
