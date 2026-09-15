"""Native Hop/parser/PG/Neo4j integration. Synthetic reviews, zero model calls."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,time,uuid
import run as t
ROOT=t.ROOT
PREFIX='jobtology-link-test-'+uuid.uuid4().hex[:8]
t.PREFIX=PREFIX;t.PG=PREFIX+'-pg';t.HOP=PREFIX+'-hop';t.NEO=PREFIX+'-neo';t.MOCK=PREFIX+'-mock'
PARSER=PREFIX+'-parser';REV='7541e87c0b45d8d209cd3c110f7bf09c72666779'
q,js,sql,cmd=t.q,t.js,t.sql,t.cmd

def run_module(module,file,params,label,ok=True):
 result=subprocess.run(['docker','exec','-e','HOP_CONFIG_FOLDER='+t.REMOTE+'/config','-e','HOP_OPTIONS=-Xmx768m','-w','/opt/hop',t.HOP,'bash','hop-run.sh','-j','llm-test','-r',('attachment-local' if module=='attachments' else 'llm-local'),'-f',t.REMOTE+'/project/'+module+'/'+file,'-p',','.join(k+'='+str(v) for k,v in params.items()),'-l','Basic'],capture_output=True,text=True)
 (t.WORK/(label+'.log')).write_text(result.stdout+result.stderr)
 assert (result.returncode==0)==ok,(label,(result.stdout+result.stderr)[-7000:])
 print(label,'passed',flush=True)

def setup():
 archive=t.WORK/'archive';archive.mkdir();archive.chmod(0o777)
 cmd(['docker','network','create','--internal',PREFIX])
 for name,image,args in [(t.PG,'postgres:17-alpine',['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=hoptest']), (t.HOP,'apache/hop:2.19.0',['--entrypoint','/bin/sleep','-v',str(archive)+':/documents']), (t.NEO,'neo4j:5.26-community',['-e','NEO4J_AUTH=none','-e','NEO4J_server_memory_heap_initial__size=256m','-e','NEO4J_server_memory_heap_max__size=512m','-e','NEO4J_server_memory_pagecache_size=128m'])]:
  cmd(['docker','run','-d','--name',name,'--network',PREFIX]+args+[image]+(['infinity'] if name==t.HOP else []))
 for _ in range(90):
  if subprocess.run(['docker','exec',t.PG,'pg_isready','-h','127.0.0.1','-U','postgres','-d','hoptest'],capture_output=True).returncode==0:break
  time.sleep(.5)
 t.seed()
 for f in sorted((ROOT/'hop/attachments/sql').glob('*.sql')):sql(f.read_text())
 t.stage()
 cmd(['docker','run','-d','--name',PARSER,'--network',PREFIX,'--read-only','--tmpfs','/tmp:rw,nosuid,size=512m','--memory','2g','--cpus','2','-v',str(archive)+':/documents:ro','jobtology-document-parser:20260914'])
 for _ in range(90):
  try:t.neo('RETURN 1;');break
  except RuntimeError:time.sleep(.5)
 return archive

def parser_checks(archive):
 samples=ROOT.parent/'document-processor/tests/doc_samples/new_test'
 fixtures=[('hwp',samples/'02_사용용_주택임대차표준계약서.hwp'),('hwpx',samples/'style_test_hwpx.hwpx')]
 files=[dict(recrutAtchFileNo=i,atchFileNm='fixture.'+ext,atchFileType='C',url='https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='+str(i)) for i,(ext,_) in enumerate(fixtures,1)]
 sql(f"UPDATE ingestion.record SET source_payload={js(dict(files=files))} WHERE source_record_id='001:detail'; UPDATE ingestion.record SET source_payload='{{\"files\":[]}}' WHERE source_record_id='002:detail'; SELECT attachment.prepare('documents','test-jobs','','/documents',2)")
 for ordinal,(ext,path) in enumerate(fixtures,1):
  document=sql(f"SELECT document_id FROM attachment.document WHERE batch_id='documents' AND file_ordinal={ordinal}")
  attempt=sql(f'SELECT attachment.reserve({q(document)})'); target=archive/(attempt+'.'+ext);shutil.copyfile(path,target);target.chmod(0o644)
  digest=hashlib.sha256(target.read_bytes()).hexdigest()
  sql(f"SELECT attachment.archive({q(attempt)},200,'',{q(digest)},{target.stat().st_size},NULL); SELECT attachment.finish_attempt({q(attempt)},false,1)")
 params=dict(BATCH_ID='parser',ATTACHMENT_BATCH_IDS='documents',PARSER_REVISION=REV,MAX_DOCUMENTS=2,PARSER_ENDPOINT='http://'+PARSER+':8080/parse')
 run_module('attachments','install_processor.hwf',{},'native-parser-install')
 run_module('attachments','parse_documents.hwf',params,'parser-plan-only')
 assert sql("SELECT count(*) FROM attachment.processor_document WHERE state='PLANNED'")=='2'
 run_module('attachments','parse_documents.hwf',params|dict(EXECUTE_PARSING='Y'),'parse-real-hwp-hwpx')
 rows=json.loads(sql("SELECT jsonb_agg(jsonb_build_object('state',state,'issue',issue,'chars',length(result->>'markdown'))) FROM attachment.processor_document"))
 assert all(x['state']=='PARSED' and x['chars']>0 for x in rows),rows
 before=sql("SELECT jsonb_agg(p ORDER BY parse_id)::text FROM attachment.processor_document p")
 run_module('attachments','parse_documents.hwf',params|dict(EXECUTE_PARSING='Y'),'parser-replay')
 assert before==sql("SELECT jsonb_agg(p ORDER BY parse_id)::text FROM attachment.processor_document p")
 run_module('attachments','prepare_processor_inputs.hwf',dict(JOB_RUN_ID='test-jobs',PROCESSOR_BATCH_ID='parser',POSTING_LIMIT=2,DATASET_ID='parser-eval'),'freeze-parser-inputs')
 assert sql("SELECT count(*) FROM enrichment.input_bundle WHERE manifest->>'contract'='document-processor-input-v2'")=='2'
 sql('SELECT attachment.verify_input_bundle(bundle_id) FROM enrichment.input_bundle')
 assert sql("SELECT count(*) FROM enrichment.input_bundle b WHERE b.source_data IS DISTINCT FROM attachment.build_processor_input(b.job_run_id,b.posting_id,'parser')->'source_data'")=='0'
 assert sql("SELECT count(*) FROM enrichment.input_bundle WHERE source_data ? 'attachment_1_1'")=='1'
 assert sql('SELECT count(*) FROM retention.writer')=='0'
 print('parser outcomes',rows,flush=True)
 # Source changes must invalidate current selection even when a review exists.
 return rows

def archive_reuse_checks():
 run_module('attachments','install_downloads.hwf',{},'native-download-install')
 run_module('attachments','download_snapshot.hwf',dict(BATCH_ID='reused-downloads',JOB_RUN_ID='test-jobs',RAW_ROOT='/documents',MAX_FILES=2,EXECUTE_DOWNLOADS='Y'),'reuse-existing-originals')
 assert sql("SELECT count(*) FROM attachment.archive_reuse")=='2'
 assert sql("SELECT count(DISTINCT raw_path) FROM attachment.attempt")=='2'
 sql("SELECT attachment.prepare_processor('reparse-archives','reused-downloads','"+REV+"',2)")
 assert sql("SELECT count(*) FROM attachment.processor_document WHERE batch_id='reparse-archives'")=='2'
 assert sql("SELECT count(*) FROM attachment.attempt a JOIN attachment.document d USING(document_id) WHERE d.batch_id='reused-downloads' AND a.state='ARCHIVED_ONLY'")=='2'
 assert sql('SELECT count(*) FROM retention.writer')=='0'
 print('Native archive reuse passed without network downloads',flush=True)

def parser_reuse_checks():
 sql("SELECT attachment.prepare_processor('reuse-parse','reused-downloads','"+REV+"',2)")
 assert sql("SELECT count(*) FROM attachment.processor_document WHERE batch_id='reuse-parse' AND state='PARSED'")=='2'
 assert sql("SELECT count(*) FROM attachment.processor_reuse r JOIN attachment.processor_document p USING(parse_id) WHERE p.batch_id='reuse-parse'")=='2'
 assert sql("SELECT count(*) FROM attachment.processor_reuse r JOIN attachment.processor_document p USING(parse_id) JOIN attachment.processor_document old ON old.parse_id=r.previous_parse_id WHERE p.result IS DISTINCT FROM old.result")=='0'
 run_module('attachments','parse_documents.hwf',dict(BATCH_ID='explicit-repair',ATTACHMENT_BATCH_IDS='documents',PARSER_REVISION='new-repair-version',MAX_DOCUMENTS=2,REUSE_SUCCESS_FROM_BATCH='parser',EXECUTE_PARSING='Y',PARSER_ENDPOINT='http://unused.invalid'),'explicit-cross-version-repair')
 assert sql("SELECT count(*) FROM attachment.processor_document WHERE batch_id='explicit-repair' AND state='PARSED'")=='2'
 assert sql("SELECT attachment.build_processor_input('test-jobs','001','explicit-repair')->'source_data' = attachment.build_processor_input('test-jobs','001','parser')->'source_data'")=='t'
 print('Parser reuses exact text and locators for unchanged bytes, including explicit repair',flush=True)

def incremental_checks():
 run_module('llm','install_incremental_linking.hwf',{},'native-incremental-install')
 params=dict(POSTING_LIMIT=2,PROMPT_VERSION='ko-link-v1',EXECUTE_REQUESTS='Y',ENDPOINT='https://'+t.MOCK+':8443/chat/completions',API_KEY_FILE=t.REMOTE+'/key.csv',EXTRACT_MODEL='test/extractor',CATEGORIZE_MODEL='test/categorizer',REQUEST_DELAY_MS=1,READ_TIMEOUT_MS=5000)
 t.run_hop('enrich_changed.hwf',params,'enrich-pending-documents')
 assert sql("SELECT state FROM enrichment.batch ORDER BY created_at DESC LIMIT 1")=='COMPLETE'
 assert sql("SELECT count(*) FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) WHERE b.batch_id=(SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1) AND a.stage='extract' AND a.state='VALIDATED'")=='2'
 before=sql('SELECT count(*) FROM enrichment.batch');calls=t.request_count()
 t.run_hop('enrich_changed.hwf',params,'skip-successful-unchanged-inputs')
 assert before==sql('SELECT count(*) FROM enrichment.batch')
 assert calls==t.request_count()
 print('Native incremental selection and no-work branch passed',flush=True)

def duty_scope_checks():
 params=dict(POSTING_LIMIT=2,PROMPT_VERSION='ko-link-v1',EXECUTE_REQUESTS='Y',ENDPOINT='https://'+t.MOCK+':8443/chat/completions',API_KEY_FILE=t.REMOTE+'/key.csv',EXTRACT_MODEL='test/extractor',CATEGORIZE_MODEL='test/categorizer',REQUEST_DELAY_MS=1,READ_TIMEOUT_MS=5000,ACCEPTANCE_POLICY='REVIEW')
 t.run_hop('enrich.hwf',params,'native-duty-only-enrichment')
 item=sql("SELECT i.item_id FROM enrichment.item i JOIN enrichment.batch b USING(batch_id) WHERE b.settings->>'prompt_version'='ko-link-v1' AND i.posting_id='001' ORDER BY b.created_at DESC LIMIT 1")
 assert sql(f"SELECT a.parsed_output->>'extraction_scope' FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.item_id={q(item)}")=='DUTIES_ONLY'
 assert sql(f"SELECT jsonb_array_length(a.parsed_output->'requirements') FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.item_id={q(item)}")=='0'
 t.run_hop('capture_extraction.hwf',dict(ITEM_ID=item,ACTOR='synthetic-test',REASON='Duty-only contract test'),'capture-duty-only-extraction')
 assert sql(f"SELECT extraction->>'extraction_scope' FROM enrichment.extraction_revision WHERE item_id={q(item)}")=='DUTIES_ONLY'
 assert sql('SELECT count(*) FROM enrichment.extraction_decision')=='0'
 print('Duty-only native request, validation, accounting and independent capture passed',flush=True)

def publication_checks():
 # These decisions are explicitly synthetic. Never copy fixture reviews to production.
 source=dict(title='데이터 엔지니어 채용',duties_text='데이터베이스 설계 및 구축')
 sql(f"UPDATE ingestion.record SET normalized=normalized||{js(source)} WHERE source_record_id LIKE '001:%'")
 h=sql("SELECT enrichment.linking_input_hash('test-jobs','001')")
 source=json.loads(sql("SELECT enrichment.source_fields(normalized) FROM ingestion.job_posting WHERE run_id='test-jobs' AND posting_id='001'"))
 extraction=dict(positions=[],duties=[dict(text='데이터베이스 설계 및 구축',position_ids=[],evidence=dict(field='duties_text',quote='데이터베이스 설계 및 구축'))],requirements=[],duties_status='explicit')
 sql(f"INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state) VALUES('review-fixture','ENRICH','test-jobs','test-ncs','fixture','{{\"prompt_version\":\"synthetic-test\",\"extract_model\":\"no-model\"}}','COMPLETE'); INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal) VALUES('review-item','review-fixture','001',{js(source)},{q(h)},1); INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason) VALUES('revision-fixture','review-item',{js(extraction)},{js(extraction)},'synthetic-fixture','Test only'); SELECT enrichment.decide_extraction('revision-fixture','ACCEPT','test-author','assistant','Synthetic source checked');")
 sql("INSERT INTO enrichment.ncs_catalog(run_id,code,name,definition) SELECT 'test-ncs','2001020101_24v1','데이터베이스 설계','데이터 요구사항에 따라 데이터베이스를 설계하는 능력' ON CONFLICT DO NOTHING; INSERT INTO enrichment.link_candidate(candidate_id,revision_id,ncs_run_id,competency_code,duty_index,reason,origin,actor) VALUES('candidate-fixture','revision-fixture','test-ncs','2001020101_24v1',0,'Synthetic definition matches the stated duty','reviewer','test-author'); SELECT enrichment.decide_link('candidate-fixture','ACCEPT','test-author','assistant','Synthetic exact duty and unit checked')")
 t.neo("CREATE (:jobPosting {id:'job-alio:posting:001'}),(:jobPosting {id:'job-alio:posting:002'}),(:ncsCompetency {id:'ncs:unit:2001020101_24v1'}),(:Person {id:'unrelated-fixture'});")
 run_module('llm','install_link_publication.hwf',{},'native-publication-install')
 assert sql("SELECT outcome FROM enrichment.linking_status WHERE posting_id='001'")=='ACCEPTED_LINKS'
 assert sql("SELECT ncs_links->0->>'candidate_origin' FROM enrichment.linking_status WHERE posting_id='001'")=='reviewer'
 run_module('llm','publish_links.hwf',dict(PUBLICATION_ID='links-first'),'publish-independent-links')
 assert t.neo("MATCH (e:reviewedNcsEnrichment {current:true})-[r:ALIGNS_WITH_NCS {accepted:true}]->() RETURN count(r);").strip().endswith('1')
 origin_output=t.neo("MATCH (e:reviewedNcsEnrichment {current:true})-[r:ALIGNS_WITH_NCS {accepted:true}]->() RETURN r.origin+':'+r.candidate_origin;")
 assert origin_output.strip().splitlines()[-1].strip('"')=='REVIEWER_INFERENCE:reviewer',origin_output
 before=t.neo('MATCH (n) RETURN count(n);')+t.neo('MATCH ()-[r]->() RETURN count(r);')
 run_module('llm','publish_links.hwf',dict(PUBLICATION_ID='links-first'),'publication-replay')
 assert before==t.neo('MATCH (n) RETURN count(n);')+t.neo('MATCH ()-[r]->() RETURN count(r);')
 sql("SELECT enrichment.decide_link('candidate-fixture','REJECT','test-author','assistant','Synthetic revocation')")
 run_module('llm','publish_links.hwf',dict(PUBLICATION_ID='links-first'),'reject-changed-publication',False)
 run_module('llm','publish_links.hwf',dict(PUBLICATION_ID='links-revoked'),'publish-link-revocation')
 assert t.neo("MATCH (e:reviewedNcsEnrichment {current:true})-[r:ALIGNS_WITH_NCS {accepted:true}]->() RETURN count(r);").strip().endswith('0')
 assert sql("SELECT extraction IS NOT NULL FROM enrichment.linking_status WHERE posting_id='001'")=='t'
 # A changed posting suppresses the old extraction, including its graph current flag.
 sql("UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{duties_text}','\"변경된 업무\"') WHERE source_record_id LIKE '001:%'")
 run_module('llm','publish_links.hwf',dict(PUBLICATION_ID='links-changed'),'publish-source-change')
 assert sql("SELECT outcome FROM enrichment.linking_status WHERE posting_id='001'")=='PENDING_EXTRACTION'
 assert t.neo('MATCH (e:reviewedNcsEnrichment {current:true}) RETURN count(e);').strip().endswith('0')
 assert t.neo("MATCH (p:Person {id:'unrelated-fixture'}) RETURN count(p);").strip().endswith('1')
 assert sql('SELECT count(*) FROM retention.writer')=='0'
 assert sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL AND actual_model NOT LIKE 'test/%'")=='0'
 print('publication replay, revocation, source change and private-node preservation passed',flush=True)

def main():
 print('fixture',t.WORK,flush=True)
 try:
  archive=setup();rows=parser_checks(archive);archive_reuse_checks();parser_reuse_checks();incremental_checks();duty_scope_checks();publication_checks()
  (t.WORK/'report.json').write_text(json.dumps(dict(parser_outcomes=rows,publication=True,replay=True,revocation=True,source_change=True,provider_calls=0),indent=2))
  print('LINKED INGESTION NATIVE CHECKS PASSED',t.WORK,flush=True)
 finally:
  if not os.environ.get('KEEP_LINK_TEST'):
   for name in [PARSER,t.MOCK,t.HOP,t.NEO,t.PG]:subprocess.run(['docker','rm','-fv',name],capture_output=True)
   subprocess.run(['docker','network','rm',PREFIX],capture_output=True)
if __name__=='__main__':main()
