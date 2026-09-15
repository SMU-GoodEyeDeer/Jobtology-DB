"""Attachment SQL invariants in an initialized disposable ontology fixture.

Run the ontology fixture first (hop/ontology/tests/run.py with its keep flag), then
this file. It adds uniquely named source/batch fixtures; no live credentials or HTTP.
Native success/error/replay evidence is recorded separately in the completion ledger.
"""
from pathlib import Path
import json,subprocess,uuid,hashlib
ROOT=Path(__file__).resolve().parents[3]
PG='jobtology-ontology-test-pg';DB='ontologytest'
def sql(text):
 p=subprocess.run(['docker','exec','-i',PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',DB],input=text,text=True,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr)
 return p.stdout.strip()
def q(v):return "'"+str(v).replace("'","''")+"'"
def js(v):return q(json.dumps(v,ensure_ascii=False))+'::jsonb'
def bad(query,reason):
 try:sql(query)
 except RuntimeError as e:assert reason in str(e),str(e)
 else:raise AssertionError('Expected '+reason)
def body(code,content,ext):return sql(f"SELECT attachment.body_issue({code},decode('{content.hex()}','hex'),{q(ext)})")
def main():
 for p in sorted((ROOT/'hop/attachments/sql').glob('*.sql')):sql(p.read_text())
 name='attachment-check-'+uuid.uuid4().hex[:10];run=name+'-source'
 files=[]
 for i,(role,ext) in enumerate([('A','pdf'),('C','hwp'),('C','hwpx'),('B','pdf'),('Z','pdf'),('A','exe'),('A','pdf')],1):
  files.append(dict(recrutAtchFileNo=i,atchFileNm='문서.'+ext,atchFileType=role,url='https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='+str(i)))
 files[-1]['url']='https://example.invalid/private'
 sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES({q(run)},'job_alio','FULL','fixture','READY');INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(run)},'all','FILE',1);INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) VALUES({q(run)},'doc','all',1,'fixture.json',repeat('a',64),1,'UTF-8',200,now(),true);INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(run)},'doc','0','100:detail',{js(dict(files=files))},'{{}}'),({q(run)},'doc','1','101:detail','{{\"files\":[]}}','{{}}');")
 prep=lambda id,ids='',root='/tmp/attachment-tests',cap=10:f'SELECT attachment.prepare({q(id)},{q(run)},{q(ids)},{q(root)},{cap})'
 bad(prep(name+'-over',cap=2),'ATTACHMENT_CAP_EXCEEDED')
 assert sql(f"SELECT count(*) FROM attachment.batch WHERE batch_id={q(name+'-over')}")=='0'
 for root in ['relative','/tmp/../escape','/tmp/./escape','/tmp//escape','/tmp/x\\y','/tmp/a\nb']:
  bad(prep(name+'-path',root=root),'INVALID_ATTACHMENT_ROOT')
 bad(prep(name+'-unknown',ids='999'),'POSTING_NOT_IN_SNAPSHOT')
 bad(f"BEGIN;INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) SELECT run_id,document_id,'duplicate',source_record_id,source_payload,normalized FROM ingestion.record WHERE run_id={q(run)} AND source_record_id='100:detail';"+prep(name+'-ambiguous')+';COMMIT;','AMBIGUOUS_SOURCE_POSTING')
 assert sql(prep(name))==name
 before=sql(f"SELECT jsonb_agg(d ORDER BY document_id) FROM attachment.document d WHERE batch_id={q(name)}")
 assert sql(prep(name))==name and before==sql(f"SELECT jsonb_agg(d ORDER BY document_id) FROM attachment.document d WHERE batch_id={q(name)}")
 bad(prep(name,ids='100'),'ATTACHMENT_SELECTION_IS_IMMUTABLE')
 assert sql(f"SELECT retention.protection({q(run)},0)")=='ATTACHMENT_BATCH'
 assert sql(f"SELECT attachment_count FROM attachment.report WHERE batch_id={q(name)} AND posting_id='101'")=='0'
 assert sql(f"SELECT string_agg(disposition,',' ORDER BY file_ordinal) FROM attachment.document WHERE batch_id={q(name)}")=='PLANNED,PLANNED,PLANNED,APPLICATION_FORM,ROLE_REVIEW,UNSUPPORTED_FORMAT,INVALID_URL'
 # The metadata URL is pinned as source provenance; downloads use the same
 # numeric file ID at the working official ALIO endpoint, including A/C-only.
 ac=name+'-ac-only'
 assert sql(f"SELECT attachment.prepare_downloads({q(ac)},{q(run)},'100','/tmp/attachment-tests',3,'A_C_ONLY')")==ac
 resolved=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_object('id',metadata->>'recrutAtchFileNo','source',source_url,'request',request_url,'disposition',disposition) ORDER BY file_ordinal) FROM attachment.document WHERE batch_id={q(ac)}"))
 assert [r['disposition'] for r in resolved]==['PLANNED','PLANNED','PLANNED','APPLICATION_FORM','ROLE_REVIEW','UNSUPPORTED_FORMAT','INVALID_URL'],resolved
 for r in resolved[:3]:
  assert r['source']=='https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='+r['id'],r
  assert r['request']=='https://www.alio.go.kr/download/download.json?fileNo='+r['id'],r
 assert all(r['request'] is None for r in resolved[3:]),resolved
 bad(f"SELECT attachment.prepare_downloads({q(ac)},{q(run)},'100','/tmp/attachment-tests',3,'DEFAULT')",'ATTACHMENT_SELECTION_IS_IMMUTABLE')
 bad(f"SELECT attachment.verify_batch({q(name)})",'ATTACHMENT_BATCH_INCOMPLETE')
 assert body(200,b'<html>not a PDF</html>','pdf')=='UNEXPECTED_CONTENT'
 assert body(200,b'<html>portal home</html>','hwp')=='UNEXPECTED_CONTENT'
 assert body(200,b'<html>portal home</html>','hwpx')=='UNEXPECTED_CONTENT'
 assert body(403,b'%PDF-1.4','pdf')=='HTTP_ERROR'
 assert body(200,b'','pdf')=='EMPTY_DOCUMENT'
 assert body(200,b'%PDF-1.4','pdf')==''
 assert body(200,bytes.fromhex('d0cf11e0a1b11ae1'),'hwp')==''
 assert body(200,b'PK\x03\x04','hwpx')==''
 bad(f"BEGIN;UPDATE ingestion.record SET source_payload=source_payload||'{{\"changed\":true}}' WHERE run_id={q(run)};SELECT attachment.check_source({q(name)});COMMIT;",'ATTACHMENT_SOURCE_CHANGED')
 docs=json.loads(sql(f"SELECT jsonb_agg(document_id ORDER BY file_ordinal) FROM attachment.document WHERE batch_id={q(name)} AND disposition='PLANNED'"))
 attempts=[]
 for doc in docs:
  attempt=sql('SELECT attachment.reserve('+q(doc)+')');attempts.append(attempt)
  bad('SELECT attachment.reserve('+q(doc)+')','duplicate key')
  sql(f"SELECT attachment.archive({q(attempt)},200,'{{}}',repeat('a',64),100,NULL)")
  bad(f"SELECT attachment.assert_hash({q(attempt)},repeat('b',64))",'ATTACHMENT_BYTES_CHANGED')
 xml='<html xmlns="http://www.w3.org/1999/xhtml"><body><div class="page"><p>데이터베이스 설계</p></div><div class="page"><p>자격증 A 또는 B</p></div></body></html>'
 sql(f"SELECT attachment.save_parse({q(attempts[0])},{q(xml)},{q(json.dumps({'Content-Type':'application/pdf'}))},repeat('a',64));SELECT attachment.finish_attempt({q(attempts[0])},true,0)")
 assert json.loads(sql(f"SELECT jsonb_agg(jsonb_build_array(locator,content) ORDER BY section_no) FROM attachment.section WHERE attempt_id={q(attempts[0])}"))==[['page:1','데이터베이스 설계'],['page:2','자격증 A 또는 B']]
 bad(f"SELECT attachment.save_parse({q(attempts[0])},{q(xml)},'{{}}',repeat('a',64))",'ATTACHMENT_BYTES_CHANGED')
 # A parser returning no source text must not become a usable extraction.
 sql(f"SELECT attachment.save_parse({q(attempts[1])},'<html xmlns=\"http://www.w3.org/1999/xhtml\"><body/></html>','{{\"Content-Type\":\"application/x-hwp-v5\"}}',repeat('a',64));SELECT attachment.finish_attempt({q(attempts[1])},true,0)")
 assert sql(f"SELECT state FROM attachment.attempt WHERE attempt_id={q(attempts[1])}")=='NO_TEXT'
 xml='<html xmlns="http://www.w3.org/1999/xhtml"><body>'+''.join('<div class="package-entry"><h1>'+n+'</h1><p>'+t+'</p></div>' for n,t in [('Preview/PrvText.txt','잘못된 미리보기'),('Contents/header.xml','글꼴'),('Contents/section2.xml','두 번째 본문'),('Contents/section0.xml','첫 번째 본문')])+'</body></html>'
 sql(f"SELECT attachment.save_parse({q(attempts[2])},{q(xml)},'{{\"Content-Type\":\"application/hwp+zip\"}}',repeat('a',64));SELECT attachment.finish_attempt({q(attempts[2])},true,0)")
 assert json.loads(sql(f"SELECT jsonb_agg(jsonb_build_array(locator,content) ORDER BY section_no) FROM attachment.section WHERE attempt_id={q(attempts[2])}"))==[['zip:Contents/section0.xml','첫 번째 본문'],['zip:Contents/section2.xml','두 번째 본문']]
 assert sql(f"SELECT state||':'||issue FROM attachment.attempt WHERE attempt_id={q(attempts[2])}")=='NEEDS_REVIEW:NONCONTIGUOUS_HWPX_SECTIONS'
 sql(f"SELECT attachment.verify_batch({q(name)})")
 assert sql(f"SELECT count(*) FROM retention.writer WHERE writer_id IN ({','.join(q(x) for x in attempts)})")=='0'
 # File parse exceptions are accounted for and release their writer.
 other=name+'-failed';sql(prep(other,ids='100'))
 doc=sql(f"SELECT document_id FROM attachment.document WHERE batch_id={q(other)} AND file_ordinal=1")
 a=sql('SELECT attachment.reserve('+q(doc)+')')
 sql(f"SELECT attachment.archive({q(a)},200,NULL,repeat('a',64),10,NULL);SELECT attachment.finish_attempt({q(a)},false,1)")
 assert sql(f"SELECT state FROM attachment.attempt WHERE attempt_id={q(a)}")=='PARSE_ERROR'
 assert sql(f"SELECT count(*) FROM retention.writer WHERE writer_id={q(a)}")=='0'
 # JSON compatibility preserves raw metadata, literal escapes and exact body text.
 raw=json.dumps({'Content-Type':'application/pdf','dc:title':'한글\x00\x00제목',
  'pdf:docinfo:title':'\\\x00','literal':'\\u0000','unchanged':'원래\ufffd문자'})
 decoded=json.loads(sql('SELECT attachment.decode_metadata('+q(raw)+')'))
 expected=json.loads(raw);expected['dc:title']='한글\ufffd\ufffd제목';expected['pdf:docinfo:title']='\\\ufffd'
 assert decoded['metadata']==expected,decoded
 assert decoded['normalization']==dict(policy='json-nul-to-replacement-v1',nul_escape_count=3,
  affected_fields=['dc:title','pdf:docinfo:title']),decoded
 # Mixed odd/even backslash runs, adjacent escapes, arrays and escaped JSON keys.
 for count in range(7):
  value='\\'*count+'\x00'+'\\u0000'+'\x00'
  got=json.loads(sql('SELECT attachment.decode_metadata('+q(json.dumps({'x':[value]}))+')'))
  assert got['metadata']['x']==[value.replace('\x00','\ufffd')],got
  assert got['normalization']['nul_escape_count']==2,got
  assert got['normalization']['affected_fields']==['x'],got
 bad("SELECT attachment.decode_metadata('[]')",'PARSER_METADATA_OBJECT_REQUIRED')
 bad("SELECT attachment.decode_metadata(NULL)",'PARSER_METADATA_REQUIRED')
 xml='<html xmlns="http://www.w3.org/1999/xhtml"><body><div class="page"><p>의사면허증 및 전문의 자격증 소지자</p></div></body></html>'
 for suffix,metadata,outcome in [('title',raw,'PARSED'),('other',json.dumps({'Content-Type':'application/pdf','subject':['A\x00B']}),'NEEDS_REVIEW')]:
  batch=name+'-'+suffix;sql(prep(batch,ids='100'))
  doc=sql(f"SELECT document_id FROM attachment.document WHERE batch_id={q(batch)} AND file_ordinal=1")
  attempt=sql('SELECT attachment.reserve('+q(doc)+')')
  sql(f"SELECT attachment.archive({q(attempt)},200,NULL,repeat('a',64),100,NULL);SELECT attachment.save_parse({q(attempt)},{q(xml)},{q(metadata)},repeat('a',64));SELECT attachment.finish_attempt({q(attempt)},true,0)")
  row=json.loads(sql(f"SELECT to_jsonb(a) FROM attachment.attempt a WHERE attempt_id={q(attempt)}"))
  assert row['state']==outcome,row
  assert row['parser_metadata_raw']==metadata and row['parser_metadata_hash']==hashlib.sha256(metadata.encode()).hexdigest()
  assert row['parsed_xml']==xml and row['parse_storage_version']=='xml-jsonb-v2'
  assert sql(f"SELECT parsed_hash=attachment.hash(jsonb_build_object('storage_version',parse_storage_version,'xml',parsed_xml,'metadata_raw',parser_metadata_raw)::text) FROM attachment.attempt WHERE attempt_id={q(attempt)}")=='t'
  assert sql(f"SELECT content FROM attachment.section WHERE attempt_id={q(attempt)}")=='의사면허증 및 전문의 자격증 소지자'
 # Reinstallation must not reinterpret old metadata or hashes.
 before=sql('SELECT attachment.hash(jsonb_agg(a ORDER BY attempt_id)::text) FROM attachment.attempt a')
 sql((ROOT/'hop/attachments/sql/001_documents.sql').read_text())
 assert before==sql('SELECT attachment.hash(jsonb_agg(a ORDER BY attempt_id)::text) FROM attachment.attempt a')
 print('ATTACHMENT SQL CHECKS PASSED',name)
if __name__=='__main__':main()
