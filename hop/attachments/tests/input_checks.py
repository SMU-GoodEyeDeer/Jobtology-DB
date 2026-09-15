"""Versioned input/evidence/cache tests in the disposable ontology database.
No real HTTP or model calls; synthetic acceptance is never a production review.
"""
import json,uuid,sys
from pathlib import Path
from checks import ROOT,sql,q,js,bad
sys.path.insert(0,str(ROOT/'hop/llm/tests'))
from v6_checks import check_v6_text

def main():
 for p in sorted((ROOT/'hop/llm/sql').glob('*.sql')):sql(p.read_text())
 for p in sorted((ROOT/'hop/attachments/sql').glob('*.sql')):sql(p.read_text())
 name='attachment-input-'+uuid.uuid4().hex[:10];run=name+'-source'
 files=[dict(recrutAtchFileNo=i,atchFileNm='문서.'+ext,atchFileType=role,url='https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='+str(i)) for i,(role,ext) in enumerate([('A','pdf'),('B','pdf'),('C','zip')],1)]
 sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES({q(run)},'job_alio','FULL','fixture','READY');INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(run)},'all','FILE',1);INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) VALUES({q(run)},'doc','all',1,'fixture.json',repeat('a',64),1,'UTF-8',200,now(),true);")
 for posting,attachments in [('100',files),('101',[])]:
  for representation in ['list','detail']:
   data=dict(posting_id=posting,representation=representation,title='기술직',organization_name='시험기관')
   sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(run)},'doc',{q(posting+representation)},{q(posting+':'+representation)},{js(dict(files=attachments))},{js(data)})")
 xml='<html xmlns="http://www.w3.org/1999/xhtml"><body><div class="page"><p>데이터베이스 설계 및 구축</p></div><div class="page"><p>의사면허증 소지자</p></div></body></html>'
 def attachment_batch(suffix,title):
  b=name+'-'+suffix
  sql(f"SELECT attachment.prepare({q(b)},{q(run)},'', '/tmp/attachment-input',20)")
  doc=sql(f"SELECT document_id FROM attachment.document WHERE batch_id={q(b)} AND disposition='PLANNED'")
  a=sql('SELECT attachment.reserve('+q(doc)+')')
  sql(f"SELECT attachment.archive({q(a)},200,NULL,repeat('a',64),100,NULL);SELECT attachment.save_parse({q(a)},{q(xml)},{q(json.dumps({'Content-Type':'application/pdf','dc:title':title}))},repeat('a',64));SELECT attachment.finish_attempt({q(a)},true,0)")
  return b,a
 first,a1=attachment_batch('first','First parse title')
 second,a2=attachment_batch('second','Independent parser metadata')
 def bundle(posting,batches):return sql(f"SELECT attachment.prepare_input_bundle({q(run)},{q(posting)},ARRAY[{','.join(q(x) for x in batches)}])")
 b1=bundle('100',[first]);b2=bundle('100',[second]);b0=bundle('101',[first]);assert b1!=b2
 assert bundle('100',[first])==b1
 rows=json.loads(sql(f"SELECT jsonb_agg(to_jsonb(b) ORDER BY bundle_id) FROM enrichment.input_bundle b WHERE bundle_id IN ({q(b1)},{q(b2)})"))
 assert rows[0]['source_data']==rows[1]['source_data'] and rows[0]['source_hash']==rows[1]['source_hash']
 source=rows[0]['source_data'];field='attachment_1_1';assert source[field]=='데이터베이스 설계 및 구축\n의사면허증 소지자'
 assert source['_input']['fields'][field]['sections']==[
  dict(section_no=1,locator_kind='page',locator='page:1',content_hash=__import__('hashlib').sha256('데이터베이스 설계 및 구축'.encode()).hexdigest(),start=0,end=14),
  dict(section_no=2,locator_kind='page',locator='page:2',content_hash=__import__('hashlib').sha256('의사면허증 소지자'.encode()).hexdigest(),start=15,end=24)],source['_input']['fields'][field]['sections']
 assert [x['outcome'] for x in source['_input']['documents']]==['PARSED','APPLICATION_FORM','UNSUPPORTED_FORMAT']
 assert '/tmp/' not in json.dumps(source) and a1 not in json.dumps(source)
 passages=json.loads(sql('SELECT enrichment.source_passages_v2('+js(source)+')'))
 for p in passages:assert source[p['field']][p['start']-1:p['end']]==p['text'],p
 good=dict(positions=[],duties=[dict(position_ids=[],text_parts=['데이터베이스 설계 및 구축'],evidence_ids=[field+':1'])],requirements=[dict(position_ids=[],category='qualification',kind='eligibility',logic='single',text_parts=['의사면허증 소지자'],evidence_ids=[field+':2'],condition=None)],duties_status='explicit',unhandled_passages=[])
 # Check both the advertised JSON schema and semantic/evidence validators.
 schema=json.loads(sql("SELECT output_schema FROM enrichment.prompt WHERE version='ko-v6' AND stage='extract'"))
 shape=json.loads(sql(f'SELECT enrichment.schema_issues_v6({js(good)},{js(schema)})'));assert shape==[],shape
 assert json.loads(sql(f'SELECT enrichment.output_issues_v6({js(good)},{js(source)})'))==[]
 missing=good|{'requirements':[]}
 assert any('UNACCOUNTED_PASSAGE:'+field+':2' in x for x in json.loads(sql(f'SELECT enrichment.output_issues_v6({js(missing)},{js(source)})')))
 hidden=source|{'attachment_999_99':'FAKE'}
 assert 'attachment_999_99' not in json.loads(sql('SELECT enrichment.input_fields('+js(hidden)+')'))
 bad(f"UPDATE enrichment.input_bundle SET source_hash=source_hash WHERE bundle_id={q(b1)}",'APPEND_ONLY_REVIEW_HISTORY')
 bad(f"BEGIN;UPDATE attachment.attempt SET parsed_xml='<changed/>' WHERE attempt_id={q(a1)};SELECT attachment.verify_input_bundle({q(b1)});COMMIT;",'ATTACHMENT_PARSE_CHANGED')
 ncs=sql("SELECT run_id FROM ingestion.run WHERE source_id='ncs_competency' AND state='READY' AND mode<>'SMOKE' ORDER BY created_at LIMIT 1")
 dataset=name+'-eval';ids=f'ARRAY[{q(b1)},{q(b0)}]'
 sql(f"SELECT enrichment.prepare_input_dataset({q(dataset)},{q(ncs)},{ids});SELECT enrichment.prepare_input_dataset({q(dataset)},{q(ncs)},{ids})")
 bad(f"SELECT enrichment.prepare_input_dataset({q(dataset)},{q(ncs)},ARRAY[{q(b2)},{q(b0)}])",'DATASET_IS_FROZEN_USE_A_NEW_ID')
 opts=dict(extract_model='fixture/model',categorize_model='fixture/model',prompt_version='ko-v6',extra_params={},limit=2,candidate_limit=40,max_matches=8,max_input_chars=200000,max_output_tokens=6000,max_requests=4,request_reserve_usd=.1,max_cost_usd=1,daily_budget_usd=20,request_delay_ms=0,read_timeout_ms=10000,execute_requests='N',reuse_cache='N',endpoint='https://fixture.invalid/chat/completions',acceptance_policy='REVIEW')
 for suffix,mode,bundles in [('enrich','ENRICH',[b1,b0]),('eval','EVAL',None),('repeat','ENRICH',[b2,b0])]:
  batch=name+'-'+suffix;settings=opts|({'input_bundle_ids':'|'.join(bundles)} if bundles else {})
  sql(f"SELECT enrichment.plan_batch({q(batch)},{q(mode)},{q(dataset)},{q(run)},{q(ncs)},{js(settings)});SELECT enrichment.plan_stage({q(batch)},'extract')")
  item=sql(f"SELECT item_id FROM enrichment.item WHERE batch_id={q(batch)} AND posting_id='100'")
  request=json.loads(sql(f"SELECT request_body FROM enrichment.attempt WHERE item_id={q(item)} AND stage='extract'"))
  user=json.loads(request['messages'][1]['content']);assert user['source_documents']==source['_input']['fields']
  assert len(user['source_passages'])==len(passages)
  assert sql(f"SELECT count(*) FROM enrichment.item_input x JOIN enrichment.item i USING(item_id) WHERE i.batch_id={q(batch)}")=='2'
  if mode=='EVAL':bad(f"SELECT enrichment.capture_extraction({q(item)},'fixture','synthetic', {js(good)})",'EVAL_CANNOT_ENTER_PRODUCTION_REVIEW')
  else:
   rid=sql(f"SELECT enrichment.capture_extraction({q(item)},'fixture','synthetic source validation only',{js(good)})")
   assert rid
 keys=json.loads(sql(f"SELECT jsonb_agg(a.cache_key ORDER BY b.batch_id) FROM enrichment.batch b JOIN enrichment.item i USING(batch_id) JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE b.batch_id IN ({q(name+'-enrich')},{q(name+'-repeat')}) AND i.posting_id='100'"));assert len(set(keys))==1,keys
 # Revision-only categorization keeps the full document input and makes no new
 # extraction attempt. These are disposable synthetic review decisions only.
 sql(f"SELECT enrichment.decide_extraction({q(rid)},'ACCEPT','synthetic fixture','policy','Test binding only')")
 revision_batch=name+'-revision';revision_opts=opts|dict(input_bundle_ids=b2,actor='synthetic fixture')
 sql(f"SELECT enrichment.plan_revision_batch({q(revision_batch)},{q(run)},{q(ncs)},{js(revision_opts)},{q(rid)});SELECT enrichment.plan_stage({q(revision_batch)},'categorize')")
 assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(revision_batch)} AND stage='extract'")=='0'
 assert sql(f"SELECT count(*) FROM enrichment.item_input x JOIN enrichment.item i USING(item_id) WHERE i.batch_id={q(revision_batch)}")=='1'
 # Existing inline Korean condition semantics must remain unchanged.
 check_v6_text(sql,js)
 print('ATTACHMENT INPUT CHECKS PASSED',name,flush=True)
 return dict(source_run=run,batch_ids=[first,second],bundle_ids=[b1,b0],ncs_run=ncs,dataset_id=dataset)
if __name__=='__main__':
 result=main();Path('/tmp/jobtology-attachments/input-checks-result.json').write_text(json.dumps(result,indent=2))
