"""Native HWPX archive/structure test using the existing verified local real pilot.
No external requests; original saved archive is read without modification.
"""
from pathlib import Path
import json,subprocess,shutil,tempfile,uuid,zipfile,hashlib,xml.etree.ElementTree as E
from checks import ROOT,sql,q
HOP='jobtology-ontology-test-hop';WORK=Path(tempfile.mkdtemp(prefix='jobtology-hwpx-native-'));REMOTE='/tmp/'+WORK.name

def cmd(args):
 p=subprocess.run(args,capture_output=True,text=True)
 if p.returncode:raise RuntimeError(p.stderr[-2500:])
 return p.stdout.strip()
def run(file,params,label):
 with (WORK/(label+'.log')).open('w') as log:
  p=subprocess.run(['docker','exec','-e','HOP_CONFIG_FOLDER='+REMOTE+'/config','-e','HOP_OPTIONS=-Xmx1024m -Djavax.xml.transform.TransformerFactory=com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl','-w','/opt/hop',HOP,'bash','hop-run.sh','-j','hwpx-native','-r','attachment-local','-f',REMOTE+'/project/attachments/'+file,'-p',','.join(k+'='+str(v) for k,v in params.items()),'-l','Basic'],stdout=log,stderr=subprocess.STDOUT)
 assert p.returncode==0,(label,(WORK/(label+'.log')).read_text()[-4000:])
 print(label,'passed',flush=True)
def main():
 project=WORK/'project';project.mkdir()
 for sub in ['attachments','metadata']:shutil.copytree(ROOT/'hop'/sub,project/sub)
 (project/'metadata/rdbms').mkdir(exist_ok=True)
 (project/'metadata/rdbms/jobtology-postgres.json').write_text(json.dumps(dict(name='jobtology-postgres',rdbms={'POSTGRESQL':dict(pluginId='POSTGRESQL',pluginName='PostgreSQL',accessType=0,hostname='',databaseName='',port='5432',manualUrl='jdbc:postgresql://jobtology-ontology-test-pg:5432/ontologytest',username='postgres',password='',sshTunnelEnabled=False,attributes={'SUPPORTS_BOOLEAN_DATA_TYPE':'Y','SUPPORTS_TIMESTAMP_DATA_TYPE':'Y'})})))
 (project/'project-config.json').write_text(json.dumps({'metadataBaseFolder':'${PROJECT_HOME}/metadata'}))
 conf=WORK/'config';conf.mkdir();(conf/'hop-config.json').write_text(json.dumps(dict(projectsConfig=dict(enabled=True,projectMandatory=True,defaultProject='hwpx-native',projectConfigurations=[dict(projectName='hwpx-native',projectHome=REMOTE+'/project',configFilename='project-config.json',readOnly=False)],lifecycleEnvironments=[],projectLifecycles=[]))))
 for a in [['docker','exec','-u','root',HOP,'mkdir','-p',REMOTE],['docker','cp',str(project),HOP+':'+REMOTE+'/'],['docker','cp',str(conf),HOP+':'+REMOTE+'/'],['docker','exec','-u','root',HOP,'chown','-R','hop:hop',REMOTE]]:cmd(a)
 run('install.hwf',{},'install')
 batch='hwpx-native-'+uuid.uuid4().hex[:10];params=dict(BATCH_ID=batch,JOB_RUN_ID='attachment-source-pilot',ATTACHMENT_BATCH_IDS='real-attachment-pilot-v2',POSTING_IDS='304739',MAX_DOCUMENTS=2)
 run('structure_hwpx.hwf',params,'real-hwpx-structure')
 row=json.loads(sql(f"SELECT to_jsonb(s) FROM attachment.hwpx_structure s WHERE batch_id={q(batch)}"))
 assert row['state']=='VERIFIED',row
 sid=row['structure_id'];original=Path('/tmp/jobtology-attachments/parsed-data/3073720.hwpx')
 from hwpx_oracle import verify
 checked=verify(row,original);counts=checked['counts'];entries=checked['entries']
 assert counts['tables']==37 and counts['cells']==852,counts
 before=sql(f"SELECT to_jsonb(s) FROM attachment.hwpx_structure s WHERE structure_id={q(sid)}")
 run('structure_hwpx.hwf',params,'replay-hwpx-structure')
 assert before==sql(f"SELECT to_jsonb(s) FROM attachment.hwpx_structure s WHERE structure_id={q(sid)}")
 assert 'Starting pipeline [process_hwpx]' not in (WORK/'replay-hwpx-structure.log').read_text()
 assert sql(f"SELECT count(*) FROM retention.writer WHERE writer_id={q(sid)}")=='0'
 result=dict(batch_id=batch,structure_id=sid,counts=counts,body_chars=len(row['body_text']),issues=row['issues'],entries=entries,work=str(WORK))
 from hwpx_cases import check_cases
 result['synthetic_cases']=check_cases(run,cmd,WORK,REMOTE,HOP)
 from structured_input_checks import check
 result['input_checks']=check(result,run)
 (WORK/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('NATIVE HWPX STRUCTURE CHECKS PASSED',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
