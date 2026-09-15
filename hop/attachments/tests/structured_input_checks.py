"""Evidence-preserving v2 bindings, compact model context, isolation and cache tests."""
import json,hashlib,uuid,sys
from pathlib import Path
from checks import sql,q,js,bad

def check(result,run_native=None):
 name='structured-input-'+uuid.uuid4().hex[:10];cases=result['synthetic_cases'];jobs=cases['job_run_id'];parent=cases['batch_id'];structure=parent
 before=sql("SELECT enrichment.hash(coalesce(jsonb_agg(b ORDER BY bundle_id),'[]')::text) FROM enrichment.input_bundle b WHERE manifest->>'contract'='attachment-input-v1'")
 ids=[]
 for case in cases['cases']:
  posting=case['posting_id']
  bid=sql(f"SELECT attachment.prepare_structured_input({q(jobs)},{q(posting)},ARRAY[{q(parent)}],ARRAY[{q(structure)}])")
  assert bid==sql(f"SELECT attachment.prepare_structured_input({q(jobs)},{q(posting)},ARRAY[{q(parent)}],ARRAY[{q(structure)}])")
  ids.append(bid);sql(f'SELECT attachment.verify_input_bundle({q(bid)})')
  b=json.loads(sql(f'SELECT to_jsonb(b) FROM enrichment.input_bundle b WHERE bundle_id={q(bid)}'))
  source=b['source_data'];docs=source['_input']['documents'];fields=source['_input']['fields']
  assert source['_input']['contract']=='attachment-input-v2' and docs[0]['structure_state']==case['state']
  if case['state']=='VERIFIED':
   assert len(fields)==1
   for field,desc in fields.items():
    body=source[field];assert hashlib.sha256(body.encode()).hexdigest()==desc['text_hash']
    original_blocks=json.loads(sql(f"SELECT jsonb_object_agg(entry_name||':'||block_no,content) FROM attachment.hwpx_block WHERE structure_id={q(case['structure_id'])}"))
    for section in desc['sections']:
     excerpt=body[section['start']:section['end']]
     assert hashlib.sha256(excerpt.encode()).hexdigest()==section['content_hash']
     actual=original_blocks[section['entry_name']+':'+str(section['block_no'])]
     assert excerpt==actual
    passages=json.loads(sql('SELECT enrichment.source_passages_v2('+js(source)+')'))
    for p in passages:
     if p['field']==field:assert body[p['start']-1:p['end']]==p['text']
    compact=json.loads(sql('SELECT enrichment.document_context('+js(source)+')'))[field]['layout']
    for section_no,part in compact['sections'].items():
     for key in ['blocks','tables','cells']:
      expanded=[(compact.get('block_defaults',{}) if key=='blocks' else {})|dict(zip(compact[key[:-1]+'_columns'],row)) for row in part[key]]
      original=[dict(x,first_line=1+body[:x['start']].count('\n'),last_line=1+body[:x['end']].count('\n')) if key=='blocks' else x for x in (desc['sections'] if key=='blocks' else desc[key]) if str(x['section_no'])==section_no]
      mapping={'section':'section_no','block':'block_no','paragraph':'paragraph_no','table':'table_no','cell':'cell_no','role':'context_role','row':'row_no','col':'col_no','header':'is_header','parent_table':'parent_table_no','parent_cell':'parent_cell_no'}
      assert expanded==[{k:x.get(mapping.get(k,k)) for k in compact[key[:-1]+'_columns']} for x in original]
  else:assert fields=={} and not any(k.startswith('attachment_') for k in source)
  assert '/tmp/' not in json.dumps(source) and case['structure_id'] not in json.dumps(source)
  bad(f"UPDATE enrichment.input_bundle SET source_data=source_data WHERE bundle_id={q(bid)}",'APPEND_ONLY_REVIEW_HISTORY')
 assert before==sql("SELECT enrichment.hash(coalesce(jsonb_agg(b ORDER BY bundle_id),'[]')::text) FROM enrichment.input_bundle b WHERE manifest->>'contract'='attachment-input-v1'")
 bad(f"SELECT attachment.prepare_structured_input({q(jobs)},'200',ARRAY[{q(parent)}],ARRAY[{q(result['batch_id'])}])",'HWPX_INPUT_SNAPSHOT_MISMATCH')
 ncs=sql("SELECT run_id FROM ingestion.run WHERE source_id='ncs_competency' AND state='READY' AND mode<>'SMOKE' ORDER BY created_at LIMIT 1")
 dataset=name+'-eval';sql(f"SELECT enrichment.prepare_input_dataset({q(dataset)},{q(ncs)},ARRAY[{','.join(q(x) for x in ids)}])")
 opts=dict(extract_model='fixture/model',categorize_model='fixture/model',prompt_version='ko-v6',extra_params={},limit=20,candidate_limit=40,max_matches=8,max_input_chars=200000,max_output_tokens=16000,max_requests=24,request_reserve_usd=.05,max_cost_usd=2,daily_budget_usd=10,request_delay_ms=0,read_timeout_ms=10000,execute_requests='N',reuse_cache='Y',endpoint='https://fixture.invalid/chat/completions',acceptance_policy='REVIEW')
 sql(f"SELECT enrichment.plan_batch({q(name)},'EVAL',{q(dataset)},{q(jobs)},{q(ncs)},{js(opts)});SELECT enrichment.plan_stage({q(name)},'extract')")
 planned=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_object('posting',i.posting_id,'body',a.request_body,'state',a.state)) FROM enrichment.item i JOIN enrichment.attempt a USING(item_id) WHERE i.batch_id={q(name)}"))
 assert len(planned)==len(ids)
 for item in planned:
  assert item['state']=='PLANNED',item['state']
  user=json.loads(item['body']['messages'][1]['content']);assert user['input_contract']=='attachment-input-v2'
  assert 'column-labelled arrays' in user['input_instructions']
  source=json.loads(sql(f"SELECT source_data FROM enrichment.item WHERE batch_id={q(name)} AND posting_id={q(item['posting'])}"))
  originals=json.loads(sql('SELECT enrichment.source_passages_v2('+js(source)+')'))
  assert user['source_passages']==[{k:p[k] for k in ['id','text']} for p in originals]
 assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(name)} AND reserved_at IS NOT NULL")=='0'
 # The real notice exercises request size with all paragraph and cell contexts.
 real_jobs=jobs;real_parent=parent;real_posting=next(x['posting_id'] for x in cases['cases'] if x['case']=='real_notice')
 original=sql(f"SELECT attachment.prepare_input_bundle({q(real_jobs)},{q(real_posting)},ARRAY[{q(real_parent)}])")
 real=sql(f"SELECT attachment.prepare_structured_input({q(real_jobs)},{q(real_posting)},ARRAY[{q(real_parent)}],ARRAY[{q(structure)}])")
 v1before=sql(f'SELECT to_jsonb(b) FROM enrichment.input_bundle b WHERE bundle_id={q(original)}')
 real_dataset=name+'-real';sql(f"SELECT enrichment.prepare_input_dataset({q(real_dataset)},{q(ncs)},ARRAY[{q(real)}]);SELECT enrichment.plan_batch({q(real_dataset)},'EVAL',{q(real_dataset)},{q(real_jobs)},{q(ncs)},{js(opts)});SELECT enrichment.plan_stage({q(real_dataset)},'extract')")
 info=json.loads(sql(f"SELECT jsonb_build_object('state',state,'chars',length(request_body::text),'issues',issues) FROM enrichment.attempt WHERE batch_id={q(real_dataset)}"))
 assert info['state']=='PLANNED',info
 assert v1before==sql(f'SELECT to_jsonb(b) FROM enrichment.input_bundle b WHERE bundle_id={q(original)}')
 if run_native:
  alternate=structure+'-repeat'
  run_native('structure_hwpx.hwf',dict(BATCH_ID=alternate,JOB_RUN_ID=real_jobs,ATTACHMENT_BATCH_IDS=real_parent,POSTING_IDS=real_posting,MAX_DOCUMENTS=2),'independent-structure-repeat')
  other=sql(f"SELECT attachment.prepare_structured_input({q(real_jobs)},{q(real_posting)},ARRAY[{q(real_parent)}],ARRAY[{q(alternate)}])")
  assert other!=real
  hashes=json.loads(sql(f"SELECT jsonb_agg(source_hash) FROM enrichment.input_bundle WHERE bundle_id IN ({q(real)},{q(other)})"));assert len(set(hashes))==1
  assert sql(f"SELECT source_data=(SELECT source_data FROM enrichment.input_bundle WHERE bundle_id={q(other)}) FROM enrichment.input_bundle WHERE bundle_id={q(real)}")=='t'
  prepared_dataset=name+'-native'
  run_native('prepare_structured_inputs.hwf',dict(JOB_RUN_ID=jobs,ATTACHMENT_BATCH_IDS=parent,HWPX_BATCH_IDS=structure,POSTING_IDS='200|211',POSTING_LIMIT=2,DATASET_ID=prepared_dataset,NCS_RUN_ID=ncs),'prepare-native-structured-inputs')
  assert sql(f"SELECT count(*) FROM enrichment.test_case_input WHERE dataset_id={q(prepared_dataset)}")=='2'
 return dict(dataset=dataset,bundles=len(ids),real_dataset=real_dataset,real_request=info,real_bundle_id=real)
if __name__=='__main__':
 result=check(json.loads(Path(sys.argv[1]).read_text()));print('STRUCTURED INPUT CHECKS PASSED',json.dumps(result))
