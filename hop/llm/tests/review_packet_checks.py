"""Native bulk review checks. Only disposable fixtures and mock model requests."""
import json,subprocess
import linked_ingestion as l

def main():
 t=l.t;sql=l.sql
 try:
  print('fixture',t.WORK,flush=True);l.setup()
  t.run_hop('enrich.hwf',dict(POSTING_LIMIT=2,PROMPT_VERSION='ko-link-v1',EXECUTE_REQUESTS='Y',ENDPOINT='https://'+t.MOCK+':8443/chat/completions',API_KEY_FILE=t.REMOTE+'/key.csv',EXTRACT_MODEL='test/extractor',CATEGORIZE_MODEL='test/categorizer',REQUEST_DELAY_MS=1,READ_TIMEOUT_MS=5000,ACCEPTANCE_POLICY='REVIEW'),'mock-production-results')
  batch=sql("SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1")
  remote=t.REMOTE+'/project/data/review.json'
  t.run_hop('install_link_review.hwf',{},'native-review-installer')
  # A terminal mixed-quality batch must expose good cases and list failed ones.
  partial=sql("BEGIN; UPDATE enrichment.batch SET state='PARTIAL' WHERE batch_id='%s'; "
   "UPDATE enrichment.attempt SET state='REJECTED',issues='[\"fixture:BAD_EVIDENCE\"]' "
   "WHERE attempt_id=(SELECT extraction_id FROM enrichment.item WHERE batch_id='%s' ORDER BY ordinal LIMIT 1); "
   "SELECT enrichment.prepare_link_review('%s','',2,'synthetic-partial-test'); ROLLBACK"%(batch,batch,batch))
  partial_packet=json.loads(next(line for line in partial.splitlines() if line.startswith('{')))
  assert len(partial_packet['cases'])==1 and len(partial_packet['omitted'])==1
  assert partial_packet['omitted'][0]['state']=='REJECTED'
  corrected=sql("BEGIN; UPDATE enrichment.batch SET state='PARTIAL' WHERE batch_id='%s'; "
   "UPDATE enrichment.attempt SET state='REJECTED' WHERE attempt_id="
   "(SELECT extraction_id FROM enrichment.item WHERE batch_id='%s' ORDER BY ordinal LIMIT 1); "
   "SELECT enrichment.capture_extraction(i.item_id,'synthetic-correction-test','Checked fixture correction',a.raw_output) "
   "FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id "
   "WHERE i.batch_id='%s' ORDER BY ordinal LIMIT 1; "
   "SELECT enrichment.prepare_link_review('%s','',2,'synthetic-corrected-review'); ROLLBACK"%(batch,batch,batch,batch))
  corrected_packet=json.loads(next(line for line in corrected.splitlines() if line.startswith('{')))
  assert len(corrected_packet['cases'])==2 and not corrected_packet['omitted']
  options=dict(BATCH_ID=batch,POSTING_LIMIT=2,ACTOR='synthetic-packet-test',REVIEW_FILE=remote)
  t.run_hop('export_link_review.hwf',options,'native-review-export')
  packet=json.loads(t.cmd(['docker','exec',t.HOP,'cat',remote]).stdout)
  assert len(packet['cases'])==2 and not packet['omitted']
  assert sql('SELECT count(*) FROM enrichment.extraction_decision')=='0'
  assert sql('SELECT count(*) FROM enrichment.link_decision')=='0'
  packet.update(reviewer='synthetic-packet-test',reviewer_kind='assistant')
  def write(name,value):
   p=t.WORK/name;p.write_text(json.dumps(value,ensure_ascii=False));p.chmod(0o644)
   r=t.REMOTE+'/project/data/'+name;t.cmd(['docker','cp',str(p),t.HOP+':'+r]);return r
  l.run_module('llm','import_link_review.hwf',dict(REVIEW_FILE=write('undecided.json',packet)),'reject-undecided-file',ok=False)
  for case in packet['cases']:
   case.update(extraction_decision='ACCEPT',extraction_notes='Synthetic fixture source and duties checked')
   for link in case['links']:link.update(decision='ACCEPT',notes='Synthetic fixture definition and duty checked')
  reviewed=write('reviewed.json',packet)
  l.run_module('llm','import_link_review.hwf',dict(REVIEW_FILE=reviewed),'native-review-import')
  assert sql('SELECT count(*) FROM enrichment.extraction_decision')=='2'
  links=sql('SELECT count(*) FROM enrichment.link_decision')
  assert int(links)>0
  l.run_module('llm','import_link_review.hwf',dict(REVIEW_FILE=reviewed),'review-replay-no-duplicates')
  assert sql('SELECT count(*) FROM enrichment.extraction_decision')=='2'
  assert sql('SELECT count(*) FROM enrichment.link_decision')==links
  packet['cases'][0]['extraction_notes']='An old review file must not overwrite a later decision'
  l.run_module('llm','import_link_review.hwf',dict(REVIEW_FILE=write('stale.json',packet)),'reject-stale-review',ok=False)
  # Two decisions are one transaction: the first valid change must roll back if
  # the second case contains changed source/context.
  t.run_hop('export_link_review.hwf',options|dict(REVIEW_FILE=t.REMOTE+'/project/data/fresh.json'),'export-current-decisions')
  fresh=json.loads(t.cmd(['docker','exec',t.HOP,'cat',t.REMOTE+'/project/data/fresh.json']).stdout)
  fresh.update(reviewer='synthetic-packet-test',reviewer_kind='assistant')
  for case in fresh['cases']:case.update(extraction_decision='REJECT',extraction_notes='Synthetic rollback test')
  fresh['cases'][1]['source_hash']='0'*64
  l.run_module('llm','import_link_review.hwf',dict(REVIEW_FILE=write('changed-context.json',fresh)),'reject-edited-context-and-rollback',ok=False)
  assert sql('SELECT count(*) FROM enrichment.extraction_decision')=='2'
  assert sql('SELECT count(*) FROM enrichment.link_decision')==links
  assert sql('SELECT count(*) FROM enrichment.link_review_import')=='1'
  print('NATIVE REVIEW PACKET CHECKS PASSED',flush=True)
 finally:
  for name in [l.PARSER,t.MOCK,t.NEO,t.HOP,t.PG]:subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  subprocess.run(['docker','network','rm',l.PREFIX],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if __name__=='__main__':main()
