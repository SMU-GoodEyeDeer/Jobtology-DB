"""Run installed ontology workflows in disposable native Hop; source fixtures are separate."""
from pathlib import Path
import json,subprocess,tempfile,os,shutil
from run import ROOT,PG,cmd,sql
HOP='jobtology-ontology-test-hop';NET='jobtology-ontology-test';WORK=Path(tempfile.mkdtemp(prefix='jobtology-ontology-native-'));REMOTE='/tmp/ontology-test'

def stage(database='ontologytest',neo=None):
 if subprocess.run(['docker','network','inspect',NET],capture_output=True).returncode:cmd(['docker','network','create','--internal',NET])
 subprocess.run(['docker','network','connect',NET,PG],capture_output=True)
 if subprocess.run(['docker','inspect',HOP],capture_output=True).returncode:cmd(['docker','run','-d','--name',HOP,'--network',NET,'--entrypoint','/bin/sleep','apache/hop:2.19.0','infinity'])
 project=WORK/'project';shutil.copytree(ROOT/'hop',project)
 (project/'metadata/rdbms').mkdir(exist_ok=True)
 (project/'metadata/rdbms/jobtology-postgres.json').write_text(json.dumps(dict(name='jobtology-postgres',rdbms={'POSTGRESQL':dict(pluginId='POSTGRESQL',pluginName='PostgreSQL',accessType=0,hostname='',databaseName='',port='5432',manualUrl=f'jdbc:postgresql://{PG}:5432/{database}',username='postgres',password='',sshTunnelEnabled=False,attributes={'SUPPORTS_BOOLEAN_DATA_TYPE':'Y','SUPPORTS_TIMESTAMP_DATA_TYPE':'Y'})})))
 if neo:
  (project/'metadata/neo4j-connection').mkdir(exist_ok=True)
  (project/'metadata/neo4j-connection/jobtology-neo4j.json').write_text(json.dumps(dict(name='jobtology-neo4j',server=neo,databaseName='neo4j',boltPort='7687',username='neo4j',password='test-auth-disabled',automatic=False,routing=False,usingEncryption=False,manualUrls=['bolt://'+neo+':7687'],connectionTimeout='10000',maxTransactionRetryTime='0')))
 config=WORK/'config';config.mkdir()
 (config/'hop-config.json').write_text(json.dumps(dict(projectsConfig=dict(enabled=True,projectMandatory=True,defaultProject='ontology-test',projectConfigurations=[dict(projectName='ontology-test',projectHome=REMOTE+'/project',configFilename='project-config.json',readOnly=False)],lifecycleEnvironments=[],projectLifecycles=[]))))
 cmd(['docker','exec','-u','root',HOP,'mkdir','-p',REMOTE])
 for path in [project,config]:cmd(['docker','cp',str(path),HOP+':'+REMOTE+'/'])
 cmd(['docker','exec','-u','root',HOP,'chown','-R','hop:hop',REMOTE])

def run(file,params,label,success=True):
 path=WORK/(label+'.log')
 with path.open('w') as log:
  p=subprocess.run(['docker','exec','-e','HOP_CONFIG_FOLDER='+REMOTE+'/config','-e','HOP_OPTIONS=-Xmx1024m','-w','/opt/hop',HOP,'bash','hop-run.sh','-j','ontology-test','-r','ontology-local','-f',REMOTE+'/project/ontology/'+file,'-p',','.join(k+'='+str(v) for k,v in params.items()),'-l','Basic'],text=True,stdout=log,stderr=subprocess.STDOUT)
 assert (p.returncode==0)==success,(label,path.read_text()[-5500:])
 print(label,'passed',flush=True)

if __name__=='__main__':
 try:
  stage();run('install.hwf',{},'native-installer')
  run('prepare_release.hwf',dict(RELEASE_ID='native-fixture'),'native-source-assembly')
  before=sql("SELECT jsonb_agg(m ORDER BY entity_id)::text FROM ontology.release_revision m WHERE release_id='native-fixture'")
  run('prepare_release.hwf',dict(RELEASE_ID='native-fixture'),'native-source-replay')
  assert before==sql("SELECT jsonb_agg(m ORDER BY entity_id)::text FROM ontology.release_revision m WHERE release_id='native-fixture'")
  run('prepare_release.hwf',dict(RELEASE_ID='native-fixture',JOB_RUN_ID='unknown'),'reject-source-reselection',False)
  # claims.py supplies reviewed fixtures, including a newer NCS run. Pin the old
  # version here to prove native assembly follows the release rather than LATEST.
  if sql("SELECT count(*) FROM ontology.review_freeze WHERE release_id='review-fixture'")=='1':
   from claims import digest
   run('prepare_release.hwf',dict(RELEASE_ID='native-reviewed',NCS_RUN_ID='fixture-ncs_competency'),'native-reviewed-source-assembly')
   run('assemble_reviewed.hwf',dict(RELEASE_ID='native-reviewed'),'native-reviewed-claims')
   assert sql("SELECT count(*) FROM ontology.release_claim WHERE release_id='native-reviewed'")=='4'
   assert sql("SELECT count(*) FROM ontology.release_mapping WHERE release_id='native-reviewed'")=='1'
   before=digest('native-reviewed')
   run('assemble_reviewed.hwf',dict(RELEASE_ID='native-reviewed'),'native-reviewed-replay')
   assert digest('native-reviewed')==before
   run('assemble_reviewed.hwf',dict(RELEASE_ID='missing-release'),'reject-unprepared-claims',False)
  print('NATIVE ONTOLOGY CHECKS PASSED',WORK,flush=True)
 finally:
  if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):subprocess.run(['docker','rm','-fv',HOP],capture_output=True)
