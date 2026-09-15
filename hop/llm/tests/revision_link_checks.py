"""Reviewed-revision-only inference, budget gates and independent link provenance."""
import copy
import json
import uuid


def check_revision_links(t, params):
    sql, js, q = t.sql, t.js, t.q
    def reject(query, message):
        try:
            sql(query)
        except RuntimeError as exc:
            assert message in str(exc), str(exc)
        else:
            raise AssertionError('Expected '+message)
    params=params|dict(PROMPT_VERSION='ko-v6', JOB_RUN_ID='test-jobs', NCS_RUN_ID='test-ncs', REUSE_CACHE='N')
    t.run_hop('enrich.hwf',params,'revision-link-source-fixture')
    bid=sql("SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1")
    options=json.loads(sql(f'SELECT settings FROM enrichment.batch WHERE batch_id={q(bid)}'))|dict(actor='fixture-linker')
    items=json.loads(sql(f'SELECT jsonb_agg(to_jsonb(i) ORDER BY ordinal) FROM enrichment.item i WHERE batch_id={q(bid)}'))
    revisions=[]
    for item in items:
        rid=sql(f"SELECT enrichment.capture_extraction({q(item['item_id'])},'fixture','Synthetic source review')")
        revisions.append(rid)
    opts=options|dict(execute_requests='N')
    def plan(revisions, options=opts, ncs='test-ncs', jobs='test-jobs'):
        name='revision-link-'+uuid.uuid4().hex
        sql(f'SELECT enrichment.plan_revision_batch({q(name)},{q(jobs)},{q(ncs)},{js(options)},{q("|".join(revisions))})')
        return name
    for selection, message in [([revisions[0]],'REVISION_REQUIRES_ACCEPTANCE'),
        ([revisions[0],revisions[0]],'INVALID_REVISION_SELECTION'),(['f'*64],'UNKNOWN_OR_NONPRODUCTION_REVISION')]:
        reject(f"SELECT enrichment.plan_revision_batch('bad','test-jobs','test-ncs',{js(opts)},{q('|'.join(selection))})",message)
    # Corrected duties are intentionally different from the old provider attempt.
    old=revisions[0]
    raw=json.loads(sql(f'SELECT raw_output FROM enrichment.extraction_revision WHERE revision_id={q(old)}'))
    corrected=copy.deepcopy(raw);corrected['duties'][0]['text_parts']=['데이터베이스 설계']
    revised=sql(f"SELECT enrichment.capture_extraction({q(items[0]['item_id'])},'fixture-editor','Narrow to the explicit design duty',{js(corrected)},{q(old)})")
    revisions[0]=revised
    for rid in revisions+[old]:
        sql(f"SELECT enrichment.decide_extraction({q(rid)},'ACCEPT','fixture-source-reviewer','assistant','Synthetic source checked')")
    reject(f"SELECT enrichment.plan_revision_batch('bad','test-jobs','test-ncs',{js(opts)},{q(old)})",'REVISION_SUPERSEDED')
    reject(f"SELECT enrichment.plan_revision_batch('bad','test-jobs','test-ncs',{js(opts|dict(actor=''))},{q(revised)})",'LINK_IMPORT_ACTOR_REQUIRED')
    original_attempts=sql(f"SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_id) FROM enrichment.attempt a WHERE batch_id={q(bid)}")
    original_reviews=sql('SELECT jsonb_agg(to_jsonb(d) ORDER BY decision_id) FROM enrichment.extraction_decision d')
    workflow_params=params|dict(REVISION_IDS='|'.join(revisions), ACTOR='fixture-linker', ACCEPTANCE_POLICY='REVIEW')
    count=t.request_count()
    t.run_hop('categorize_reviewed.hwf',workflow_params|dict(EXECUTE_REQUESTS='N',API_KEY_FILE='/does-not-exist'),'revision-link-native-dry')
    dry=sql("SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1")
    assert t.request_count()==count
    assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(dry)} AND stage='extract'")=='0'
    reject(f"SELECT enrichment.plan_stage({q(dry)},'extract')",'REVISION_BATCH_CANNOT_EXTRACT')
    t.run_hop('categorize_reviewed.hwf',workflow_params,'revision-link-native-paid-mock')
    new=sql("SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1")
    report=json.loads(sql(f'SELECT to_jsonb(r) FROM enrichment.batch_report r WHERE batch_id={q(new)}'))
    assert report['requests']==1 and report['validated']==2 and report['state']=='COMPLETE',report
    assert report['reported_cost_usd']==0.001 and t.request_count()==count+1
    assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(new)} AND stage='extract'")=='0'
    row=json.loads(sql(f"SELECT to_jsonb(i) FROM enrichment.item i WHERE batch_id={q(new)} AND posting_id='001'"))
    request=json.loads(sql(f"SELECT request_body FROM enrichment.attempt WHERE attempt_id={q(row['categorization_id'])}"))
    user=json.loads(request['messages'][1]['content'])
    assert [d['text'] for d in user['duties']]==['데이터베이스 설계'],user
    assert user['source_context']['positions']==corrected['positions'] and user['source_context']['source_passages']
    assert request['trace']['extraction_revision_id']==revised
    assert sql(f"SELECT string_agg(outcome,',' ORDER BY outcome) FROM enrichment.revision_link_result lr JOIN enrichment.item i USING(item_id) WHERE i.batch_id={q(new)}")=='NO_EXPLICIT_DUTIES,matched'
    assert sql(f"SELECT enrichment.import_revision_links({q(row['item_id'])},'fixture-replay')")=='1'
    candidate=sql(f"SELECT candidate_id FROM enrichment.link_candidate WHERE revision_id={q(revised)}")
    assert sql(f"SELECT count(*) FROM enrichment.link_decision WHERE candidate_id={q(candidate)}")=='0'
    reject(f"SELECT enrichment.review_item({q(row['item_id'])},'ACCEPT','fixture','No blanket acceptance')",'REVISION_BATCH_REQUIRES_PER_LINK_REVIEW')
    # Cache reuse does not cause a second charge, and the imported result keeps its own lineage.
    t.run_hop('categorize_reviewed.hwf',workflow_params|dict(REUSE_CACHE='Y'),'revision-link-native-cache')
    assert t.request_count()==count+1
    # A rejected candidate prevents reuse of the corresponding cached response.
    sql(f"SELECT enrichment.decide_link({q(candidate)},'REJECT','fixture-link-reviewer','assistant','Synthetic domain rejection')")
    t.run_hop('categorize_reviewed.hwf',workflow_params|dict(REUSE_CACHE='Y'),'revision-link-rejected-cache')
    assert t.request_count()==count+2
    assert sql(f"SELECT decision FROM enrichment.latest_link_decision WHERE candidate_id={q(candidate)}")=='REJECT'
    assert sql(f"SELECT count(*) FROM enrichment.link_support WHERE candidate_id={q(candidate)}")=='3'
    budget_count=t.request_count()
    t.run_hop('categorize_reviewed.hwf',workflow_params|dict(MAX_COST_USD='0.01',REQUEST_RESERVE_USD='0.10'),'revision-link-native-budget')
    budget_batch=sql("SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1")
    assert t.request_count()==budget_count
    assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(budget_batch)} AND state='BUDGET_BLOCKED'")=='1'
    assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(budget_batch)} AND reserved_at IS NOT NULL")=='0'
    # The same revision may be checked against a newer, independently pinned NCS snapshot.
    sql("""INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES('revision-new-ncs','ncs_competency','FULL','test','READY');
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES('revision-new-ncs','test','FILE',1);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected)
SELECT 'revision-new-ncs',document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected FROM ingestion.document WHERE run_id='test-ncs';
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
SELECT 'revision-new-ncs',document_id,locator,source_record_id,source_payload,normalized FROM ingestion.record WHERE run_id='test-ncs';""")
    t.run_hop('categorize_reviewed.hwf',workflow_params|dict(NCS_RUN_ID='revision-new-ncs'),'revision-link-new-ncs')
    assert sql(f"SELECT count(DISTINCT ncs_run_id) FROM enrichment.link_candidate WHERE revision_id={q(revised)}")=='2'
    assert sql(f"SELECT decision FROM enrichment.latest_link_decision WHERE candidate_id={q(candidate)}")=='REJECT'
    assert original_attempts==sql(f"SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_id) FROM enrichment.attempt a WHERE batch_id={q(bid)}")
    assert original_reviews==sql('SELECT jsonb_agg(to_jsonb(d) ORDER BY decision_id) FROM enrichment.extraction_decision d')
    # Reservation and response both recheck revocation. Charged responses are retained.
    planned=plan([revised],options|dict(limit=1,execute_requests='Y'))
    tamper=sql(f"BEGIN; UPDATE enrichment.item SET source_data=source_data||'{{\"title\":\"changed\"}}'::jsonb WHERE batch_id={q(planned)}; SELECT enrichment.revision_input_issue(item_id) FROM enrichment.item WHERE batch_id={q(planned)}; ROLLBACK;")
    assert 'REVISION_INPUT_CHANGED' in tamper
    sql(f"SELECT enrichment.plan_stage({q(planned)},'categorize')")
    aid=sql(f'SELECT categorization_id FROM enrichment.item WHERE batch_id={q(planned)}')
    sql(f"SELECT enrichment.decide_extraction({q(revised)},'REJECT','fixture','assistant','Revoked before reservation'); SELECT enrichment.reserve_request({q(aid)})")
    a=json.loads(sql(f'SELECT to_jsonb(a) FROM enrichment.attempt a WHERE attempt_id={q(aid)}'))
    assert a['state']=='ERROR' and a['reserved_at'] is None and 'REVISION_ACCEPTANCE_CHANGED' in a['issues'],a
    sql(f"SELECT enrichment.decide_extraction({q(revised)},'ACCEPT','fixture','assistant','Restore synthetic acceptance')")
    planned=plan([revised],options|dict(limit=1,execute_requests='Y'))
    sql(f"SELECT enrichment.plan_stage({q(planned)},'categorize')")
    aid=sql(f'SELECT categorization_id FROM enrichment.item WHERE batch_id={q(planned)}')
    sql(f"SELECT enrichment.reserve_request({q(aid)}); SELECT enrichment.decide_extraction({q(revised)},'REJECT','fixture','assistant','Revoked while request is in flight')")
    output=dict(matches=[],outcome='no_supported_match')
    response=dict(id='fixture-charged',model='fixture',choices=[dict(finish_reason='stop',message=dict(content=json.dumps(output)))],usage=dict(cost=0.002,prompt_tokens=100,completion_tokens=20))
    sql(f"SELECT enrichment.save_response({q(aid)},200,{q(json.dumps(response))},10); SELECT enrichment.finish_batch({q(planned)})")
    a=json.loads(sql(f'SELECT to_jsonb(a) FROM enrichment.attempt a WHERE attempt_id={q(aid)}'))
    assert a['state']=='REJECTED' and a['cost_usd']==0.002 and a['raw_output']==output,a
    failed_item=sql(f'SELECT item_id FROM enrichment.item WHERE batch_id={q(planned)}')
    reject(f"SELECT enrichment.import_revision_links({q(failed_item)},'fixture')",'REVISION_ACCEPTANCE_CHANGED')
    assert sql(f'SELECT state FROM enrichment.batch WHERE batch_id={q(planned)}')=='PARTIAL'
    # No immutable binding or imported rationale may be rewritten.
    for query in [f"UPDATE enrichment.revision_input SET extraction_hash='fake' WHERE item_id={q(row['item_id'])}",
        f"DELETE FROM enrichment.link_support WHERE candidate_id={q(candidate)}"]:
        reject(query,'APPEND_ONLY_REVIEW_HISTORY')
    print('Reviewed-revision native categorization, corrected duties, replay, cache, rejection, new NCS, budget ledger and revocation checks passed',flush=True)
