"""Native input preparation and EVAL/ENRICH planning. No HTTP/key/model access."""
from pathlib import Path
import json,subprocess,shutil,tempfile,uuid
from checks import ROOT,sql,q
HOP='jobtology-ontology-test-hop'
WORK=Path(tempfile.mkdtemp(prefix='jobtology-native-inputs-'));REMOTE='/tmp/'+WORK.name

def cmd(args):
 p=subprocess.run(args,text=True,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr[-3000:])
 return p.stdout.strip()
def run(file,params,label):
 path=WORK/(label+'.log')
 with path.open('w') as log:
  p=subprocess.run(['docker','exec','-e','HOP_CONFIG_FOLDER='+REMOTE+'/config','-e','HOP_OPTIONS=-Xmx1024m -Djavax.xml.transform.TransformerFactory=com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl','-w','/opt/hop',HOP,'bash','hop-run.sh','-j','input-native','-r','attachment-local','-f',REMOTE+'/project/'+file,'-p',','.join(k+'='+str(v) for k,v in params.items()),'-l','Basic'],stdout=log,stderr=subprocess.STDOUT)
 assert p.returncode==0,(label,path.read_text()[-4000:])
 print(label,'passed',flush=True)
def main():
 fixtures=json.loads(Path('/tmp/jobtology-attachments/input-checks-result.json').read_text())
 project=WORK/'project';project.mkdir()
 for sub in ['llm','attachments','metadata']:shutil.copytree(ROOT/'hop'/sub,project/sub)
 (project/'metadata/rdbms').mkdir(exist_ok=True)
 (project/'metadata/rdbms/jobtology-postgres.json').write_text(json.dumps(dict(name='jobtology-postgres',rdbms={'POSTGRESQL':dict(pluginId='POSTGRESQL',pluginName='PostgreSQL',accessType=0,hostname='',databaseName='',port='5432',manualUrl='jdbc:postgresql://jobtology-ontology-test-pg:5432/ontologytest',username='postgres',password='',sshTunnelEnabled=False,attributes={'SUPPORTS_BOOLEAN_DATA_TYPE':'Y','SUPPORTS_TIMESTAMP_DATA_TYPE':'Y'})})))
 (project/'project-config.json').write_text(json.dumps({'metadataBaseFolder':'${PROJECT_HOME}/metadata'}))
 conf=WORK/'config';conf.mkdir()
 (conf/'hop-config.json').write_text(json.dumps(dict(projectsConfig=dict(enabled=True,projectMandatory=True,defaultProject='input-native',projectConfigurations=[dict(projectName='input-native',projectHome=REMOTE+'/project',configFilename='project-config.json',readOnly=False)],lifecycleEnvironments=[],projectLifecycles=[]))))
 for a in [['docker','exec','-u','root',HOP,'mkdir','-p',REMOTE],['docker','cp',str(project),HOP+':'+REMOTE+'/'],['docker','cp',str(conf),HOP+':'+REMOTE+'/'],['docker','exec','-u','root',HOP,'chown','-R','hop:hop',REMOTE]]:cmd(a)
 run('llm/install.hwf',{},'install-llm');run('attachments/install.hwf',{},'install-attachments')
 dataset='attachment-native-input-'+uuid.uuid4().hex[:10]
 params=dict(JOB_RUN_ID=fixtures['source_run'],ATTACHMENT_BATCH_IDS='|'.join(fixtures['batch_ids']),POSTING_IDS='100|101',POSTING_LIMIT=2,DATASET_ID=dataset,NCS_RUN_ID=fixtures['ncs_run'])
 run('attachments/prepare_inputs.hwf',params,'prepare-native-inputs')
 before=sql(f"SELECT jsonb_agg(c ORDER BY posting_id) FROM enrichment.test_case c WHERE dataset_id={q(dataset)}")
 run('attachments/prepare_inputs.hwf',params,'replay-native-inputs')
 assert before==sql(f"SELECT jsonb_agg(c ORDER BY posting_id) FROM enrichment.test_case c WHERE dataset_id={q(dataset)}")
 bundles=sql(f"SELECT string_agg(bundle_id,'|' ORDER BY posting_id) FROM enrichment.test_case_input WHERE dataset_id={q(dataset)}")
 opts=dict(JOB_RUN_ID=fixtures['source_run'],NCS_RUN_ID=fixtures['ncs_run'],DATASET_ID=dataset,PROMPT_VERSION='ko-v6',EXTRACT_MODEL='fixture/model',CATEGORIZE_MODEL='fixture/model',POSTING_LIMIT=2,MAX_INPUT_CHARS=200000,EXECUTE_REQUESTS='N',ACCEPTANCE_POLICY='REVIEW',API_KEY_FILE='/deliberately-missing-key.csv')
 run('llm/evaluate.hwf',opts,'evaluate-planning-without-key')
 opts['INPUT_BUNDLE_IDS']=bundles
 run('llm/enrich.hwf',opts,'enrich-planning-without-key')
 batches=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_object('batch_id',b.batch_id,'mode',b.mode,'state',b.state,'items',(SELECT count(*) FROM enrichment.item WHERE batch_id=b.batch_id),'bindings',(SELECT count(*) FROM enrichment.item i JOIN enrichment.item_input x USING(item_id) WHERE i.batch_id=b.batch_id),'reserved',(SELECT count(*) FROM enrichment.attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL))) FROM enrichment.batch b WHERE (dataset_id={q(dataset)} OR settings->>'input_bundle_ids'={q(bundles)})"))
 assert len(batches)==2,batches
 assert all(b['items']==b['bindings']==2 and b['reserved']==0 and b['state']=='PLANNED' for b in batches),batches
 (WORK/'result.json').write_text(json.dumps(dict(dataset_id=dataset,inputs_unchanged_on_replay=True,batches=batches),indent=2))
 print('NATIVE INPUT PLANNING CHECKS PASSED',WORK,flush=True)
if __name__=='__main__':main()
