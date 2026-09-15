"""Native attachment HTTP/parser/error/replay checks against synthetic local fixtures.
Requires the initialized disposable ontology PostgreSQL/Hop containers. No live requests.
Only the copied test pipeline's request URL is redirected to the local HTTP fixture;
production artifacts, policy, signatures, parser and ledger paths are unchanged.
"""
from pathlib import Path
import json,subprocess,shutil,tempfile,uuid,io,zipfile,base64,xml.etree.ElementTree as E
from checks import ROOT,sql,q,js
HOP='jobtology-ontology-test-hop';MOCK='jobtology-attachment-test-mock';NET='jobtology-ontology-test'
WORK=Path(tempfile.mkdtemp(prefix='jobtology-attachment-native-'));REMOTE='/tmp/'+WORK.name

def cmd(args):
 p=subprocess.run(args,text=True,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr[-3000:])
 return p.stdout.strip()
def pdf(text,title=None):
 content=('BT /F1 12 Tf 30 180 Td ('+text+') Tj ET').encode()
 objs=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
 if title is not None:objs.append(b'<< /Title ('+title+b') >>')
 out=b'%PDF-1.4\n';offsets=[]
 for i,o in enumerate(objs,1):offsets.append(len(out));out+=str(i).encode()+b' 0 obj\n'+o+b'\nendobj\n'
 size=str(len(objs)+1).encode()
 xref=len(out);out+=b'xref\n0 '+size+b'\n0000000000 65535 f \n'+b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets)
 return out+b'trailer\n<< /Root 1 0 R /Size '+size+(b' /Info 6 0 R' if title is not None else b'')+b' >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'
def run(file,params,label,ok=True):
 path=WORK/(label+'.log')
 with path.open('w') as f:
  p=subprocess.run(['docker','exec','-e','HOP_CONFIG_FOLDER='+REMOTE+'/config','-e','HOP_OPTIONS=-Xmx1024m -Djavax.xml.transform.TransformerFactory=com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl','-w','/opt/hop',HOP,'bash','hop-run.sh','-j','attachment-native','-r','attachment-local','-f',REMOTE+'/project/attachments/'+file,'-p',','.join(k+'='+str(v) for k,v in params.items()),'-l','Basic'],stdout=f,stderr=subprocess.STDOUT)
 assert (p.returncode==0)==ok,(label,path.read_text()[-4500:])
 print(label,'passed',flush=True)
def main():
 project=WORK/'project';shutil.copytree(ROOT/'hop/attachments',project/'attachments');shutil.copytree(ROOT/'hop/metadata',project/'metadata')
 (project/'metadata/rdbms').mkdir(exist_ok=True)
 (project/'metadata/rdbms/jobtology-postgres.json').write_text(json.dumps(dict(name='jobtology-postgres',rdbms={'POSTGRESQL':dict(pluginId='POSTGRESQL',pluginName='PostgreSQL',accessType=0,hostname='',databaseName='',port='5432',manualUrl='jdbc:postgresql://jobtology-ontology-test-pg:5432/ontologytest',username='postgres',password='',sshTunnelEnabled=False,attributes={'SUPPORTS_BOOLEAN_DATA_TYPE':'Y','SUPPORTS_TIMESTAMP_DATA_TYPE':'Y'})})))
 (project/'project-config.json').write_text(json.dumps({'metadataBaseFolder':'${PROJECT_HOME}/metadata'}))
 p=project/'attachments/process_file.hpl';tree=E.parse(p);n=tree.find("transform[name='Reserved file']/sql")
 n.text=n.text.replace('d.request_url,',"replace(d.request_url,'https://www.alio.go.kr','http://jobtology-attachment-test-mock:8080') AS request_url,")
 tree.write(p,encoding='UTF-8',xml_declaration=True)
 conf=WORK/'config';conf.mkdir()
 (conf/'hop-config.json').write_text(json.dumps(dict(projectsConfig=dict(enabled=True,projectMandatory=True,defaultProject='attachment-native',projectConfigurations=[dict(projectName='attachment-native',projectHome=REMOTE+'/project',configFilename='project-config.json',readOnly=False)],lifecycleEnvironments=[],projectLifecycles=[]))))
 for a in [['docker','exec','-u','root',HOP,'mkdir','-p',REMOTE],['docker','cp',str(project),HOP+':'+REMOTE+'/'],['docker','cp',str(conf),HOP+':'+REMOTE+'/'],['docker','exec','-u','root',HOP,'chown','-R','hop:hop',REMOTE]]:cmd(a)
 buf=io.BytesIO()
 with zipfile.ZipFile(buf,'w') as z:
  z.writestr('mimetype','application/hwp+zip')
  z.writestr('Contents/section0.xml','<?xml version="1.0" encoding="UTF-8"?><section><p>데이터베이스 설계 및 구축</p><p>자격증 A 또는 B</p></section>')
  z.writestr('Preview/PrvText.txt','DO NOT USE THIS PREVIEW')
  z.writestr('Contents/header.xml','<fonts>NOT SOURCE TEXT</fonts>')
 bodies=[pdf('Database design'),b'<html>Homepage instead of a PDF</html>',b'%PDF-1.4\nnot a valid PDF',pdf(''),buf.getvalue(),bytes.fromhex('d0cf11e0a1b11ae1'),pdf('Readable body despite title metadata',b'Title\\000suffix')]
 fixture=WORK/'fixture';fixture.mkdir()
 for i,b in enumerate(bodies,1):(fixture/str(i)).write_bytes(b)
 (fixture/'server.py').write_text('''from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  i=parse_qs(urlparse(self.path).query)['fileNo'][0]
  b=Path('/fixture/'+i).read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.send_header('Content-Type','application/octet-stream');self.end_headers();self.wfile.write(b)
 def log_message(self,*args):print(self.path,flush=True)
HTTPServer(('0.0.0.0',8080),H).serve_forever()
''')
 if subprocess.run(['docker','inspect',MOCK],capture_output=True).returncode==0:raise RuntimeError('A previous attachment mock exists; inspect it before rerunning.')
 cmd(['docker','run','-d','--name',MOCK,'--network',NET,'-v',str(fixture)+':/fixture:ro','python:3.13-alpine','python','/fixture/server.py'])
 run_id='attachment-native-'+uuid.uuid4().hex[:10];batch=run_id+'-batch'
 files=[dict(recrutAtchFileNo=i,atchFileNm='fixture.'+(['pdf']*4+['hwpx','hwp','pdf'])[i-1],atchFileType='C',url='https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='+str(i)) for i in range(1,8)]
 sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES({q(run_id)},'job_alio','FULL','fixture','READY');INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(run_id)},'all','FILE',1);INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) VALUES({q(run_id)},'doc','all',1,'fixture.json',repeat('a',64),1,'UTF-8',200,now(),true);INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(run_id)},'doc','0','100:detail',{js(dict(files=files))},'{{}}');")
 try:
  run('install.hwf',{},'install')
  params=dict(BATCH_ID=batch,JOB_RUN_ID=run_id,MAX_FILES=7,EXECUTE_DOWNLOADS='N')
  run('process_snapshot.hwf',params,'plan-without-http')
  assert cmd(['docker','logs',MOCK])==''
  params['EXECUTE_DOWNLOADS']='Y';run('process_snapshot.hwf',params,'process-and-isolate-errors')
  result=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_array(d.file_ordinal,a.state,a.issue) ORDER BY d.file_ordinal) FROM attachment.document d JOIN attachment.attempt a USING(document_id) WHERE d.batch_id={q(batch)}"))
  assert [r[1] for r in result]==['PARSED','UNEXPECTED_CONTENT','PARSE_ERROR','NO_TEXT','PARSED','PARSE_ERROR','PARSED'],result
  meta=json.loads(sql(f"SELECT jsonb_build_object('raw',a.parser_metadata_raw,'decoded',a.parser_metadata,'changes',a.metadata_normalization,'hash_ok',a.parser_metadata_hash=attachment.hash(a.parser_metadata_raw)) FROM attachment.document d JOIN attachment.attempt a USING(document_id) WHERE d.batch_id={q(batch)} AND d.file_ordinal=7"))
  assert '\x00' in json.loads(meta['raw'])['dc:title'] and '\ufffd' in meta['decoded']['dc:title'],meta
  assert meta['changes']['affected_fields']==['dc:title','pdf:docinfo:title'] and meta['hash_ok'],meta
  text=sql(f"SELECT string_agg(s.content,'\n' ORDER BY s.section_no) FROM attachment.document d JOIN attachment.attempt a USING(document_id) JOIN attachment.section s USING(attempt_id) WHERE d.batch_id={q(batch)} AND d.file_ordinal=5")
  assert '데이터베이스 설계 및 구축' in text and '자격증 A 또는 B' in text and 'DO NOT' not in text and 'NOT SOURCE' not in text,text
  before=sql(f"SELECT jsonb_agg(a ORDER BY attempt_id) FROM attachment.attempt a JOIN attachment.document d USING(document_id) WHERE d.batch_id={q(batch)}")
  requests=cmd(['docker','logs',MOCK]);assert len(requests.splitlines())==7,requests
  run('process_snapshot.hwf',params,'replay-without-http')
  assert cmd(['docker','logs',MOCK])==requests
  assert before==sql(f"SELECT jsonb_agg(a ORDER BY attempt_id) FROM attachment.attempt a JOIN attachment.document d USING(document_id) WHERE d.batch_id={q(batch)}")
  assert sql(f"SELECT count(*) FROM retention.writer w JOIN attachment.attempt a ON w.writer_id=a.attempt_id JOIN attachment.document d USING(document_id) WHERE d.batch_id={q(batch)}")=='0'
  (WORK/'result.json').write_text(json.dumps(dict(batch_id=batch,outcomes=result,requests=7,unchanged_replay=True),ensure_ascii=False,indent=2))
  print('NATIVE ATTACHMENT CHECKS PASSED',WORK,flush=True)
 finally:subprocess.run(['docker','rm','-fv',MOCK],capture_output=True)
if __name__=='__main__':main()
