"""Repair selection respects newer revisions and unresolved in-flight attempts."""
import json
import uuid


def check_repair_selection(sql, js, q):
    suffix=uuid.uuid4().hex
    posting='repair-guard-'+suffix
    old,new,flight,changed,ev=['guard-'+name+'-'+suffix for name in ('old','new','flight','changed','eval')]
    value=sql("SELECT settings FROM enrichment.batch WHERE NOT settings ? 'input_kind' AND settings ? 'extract_model' ORDER BY created_at DESC LIMIT 1")
    options=json.loads(value) if value else dict(extract_model='test/extractor',categorize_model='test/categorizer',
        extra_params={},candidate_limit=40,max_matches=8,max_input_chars=60000,max_output_tokens=6000,max_requests=2,
        request_reserve_usd=.05,max_cost_usd=.25,daily_budget_usd=5,request_delay_ms=1,read_timeout_ms=1000,endpoint='https://example.invalid/chat/completions')
    options.update(execute_requests='N',reuse_cache='N',limit=1,posting_ids=posting,prompt_version='ko-v6',acceptance_policy='REVIEW')
    options.pop('repair_batch_id',None)
    def plan(bid,mode='ENRICH',dataset='NULL'):
        return f"SELECT enrichment.plan_batch({q(bid)},{q(mode)},{dataset},'test-jobs','test-ncs',{js(options)}); SELECT enrichment.plan_stage({q(bid)},'extract'); UPDATE enrichment.batch SET state='PARTIAL' WHERE batch_id={q(bid)}; UPDATE enrichment.attempt SET state='REJECTED',issues='[\"fixture:BAD_EXTRACTION\"]' WHERE batch_id={q(bid)};"
    def item(bid): return f'(SELECT item_id FROM enrichment.item WHERE batch_id={q(bid)})'
    def available(bid): return f'enrichment.repair_reasons_v6({item(bid)}) IS NOT NULL'
    # These dummy revisions test selection only; they are never semantic acceptance fixtures.
    script=f"""BEGIN;
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
SELECT 'test-jobs',document_id,{q(posting)}||(normalized->>'representation'),{q(posting)}||':'||(normalized->>'representation'),source_payload,
 normalized||jsonb_build_object('posting_id',{q(posting)}) FROM ingestion.record WHERE run_id='test-jobs' AND normalized->>'posting_id'='001';
{plan(old)}
SELECT jsonb_build_object('before_revision',{available(old)});
{plan(new)}
INSERT INTO enrichment.repair_item(item_id,prior_item_id,prior_attempt_id,trigger_issues,previous_output)
SELECT {item(new)},item_id,extraction_id,'["fixture:BAD_EXTRACTION"]','{{}}' FROM enrichment.item WHERE batch_id={q(old)};
INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason)
VALUES({q(new)},{item(new)},'{{}}','{{}}','fixture','Selection only');
SELECT jsonb_build_object('old_protected_pending',NOT ({available(old)}),'pending_protected',NOT ({available(new)}));
-- New review arrived after the request was planned: the reservation rechecks.
UPDATE enrichment.attempt SET state='PLANNED' WHERE batch_id={q(new)};
UPDATE enrichment.batch SET state='RUNNING',settings=jsonb_set(settings,'{{execute_requests}}','"Y"') WHERE batch_id={q(new)};
SELECT enrichment.reserve_request((SELECT extraction_id FROM enrichment.item WHERE batch_id={q(new)}));
SELECT jsonb_build_object('protected_request_not_sent',state='ERROR' AND reserved_at IS NULL AND issues ? 'REPAIR_INPUT_SUPERSEDED_OR_PROTECTED') FROM enrichment.attempt WHERE batch_id={q(new)};
UPDATE enrichment.batch SET state='PARTIAL' WHERE batch_id={q(new)};
SELECT enrichment.decide_extraction({q(new)},'ACCEPT','fixture','assistant','Selection only');
SELECT jsonb_build_object('old_protected_accepted',NOT ({available(old)}),'accepted_protected',NOT ({available(new)}));
SELECT enrichment.decide_extraction({q(new)},'REJECT','fixture','assistant','Selection only');
SELECT jsonb_build_object('old_not_resurrected',NOT ({available(old)}),'latest_rejected_repairable',{available(new)});
{plan(flight)}
UPDATE enrichment.attempt SET state='RESERVED' WHERE batch_id={q(flight)};
SELECT jsonb_build_object('reserved_elsewhere_blocks',NOT ({available(new)}));
UPDATE enrichment.attempt SET state='ERROR' WHERE batch_id={q(flight)};
SELECT jsonb_build_object('settled_elsewhere_unblocks',{available(new)});
-- A newer revision from different content must not hide repairs for this pinned content.
{plan(changed)}
UPDATE enrichment.item SET source_data=source_data||'{{"title":"different input"}}'::jsonb WHERE batch_id={q(changed)};
UPDATE enrichment.item SET source_hash=enrichment.hash(source_data::text) WHERE batch_id={q(changed)};
INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason)
VALUES({q(changed)},{item(changed)},'{{}}','{{}}','fixture','Different content');
SELECT jsonb_build_object('different_hash_does_not_hide',{available(new)});
-- Production revisions never suppress a frozen EVAL retry.
INSERT INTO enrichment.dataset(dataset_id,job_run_id,ncs_run_id,seed,requested_size) VALUES({q(ev)},'test-jobs','test-ncs','fixture',1);
INSERT INTO enrichment.test_case(dataset_id,posting_id,source_data,source_hash,stratum,ordinal)
SELECT {q(ev)},posting_id,source_data,source_hash,'fixture',1 FROM enrichment.item WHERE batch_id={q(new)};
{plan(ev,'EVAL',q(ev))}
SELECT jsonb_build_object('evaluation_isolated',{available(ev)});
ROLLBACK;"""
    result=sql(script)
    checks={k:v for line in result.splitlines() if line.startswith('{') for k,v in json.loads(line).items()}
    assert len(checks)==12 and all(checks.values()),checks
    print('Cross-batch pending/accepted/rejected, changed-content, in-flight and EVAL repair guards passed',flush=True)


def check_repair_selection_native(t):
    """Planning fails before key access; reservation fails before HTTP."""
    sql,js,q=t.sql,t.js,t.q
    suffix=uuid.uuid4().hex
    posting='native-guard-'+suffix
    old,request,new=['native-'+name+'-'+suffix for name in ('old','request','new')]
    sql(f"""INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
SELECT 'test-jobs',document_id,{q(posting)}||(normalized->>'representation'),
 {q(posting)}||':'||(normalized->>'representation'),source_payload,
 normalized||jsonb_build_object('posting_id',{q(posting)})
FROM ingestion.record WHERE run_id='test-jobs' AND normalized->>'posting_id'='001';""")
    opts=dict(extract_model='test/extractor',categorize_model='test/categorizer',prompt_version='ko-v6',
        extra_params={},limit=1,posting_ids=posting,candidate_limit=40,max_matches=8,max_input_chars=60000,
        max_output_tokens=6000,max_requests=2,request_reserve_usd=.05,max_cost_usd=.25,daily_budget_usd=5,
        request_delay_ms=1,read_timeout_ms=1000,endpoint='https://'+t.MOCK+':8443/chat/completions',
        execute_requests='N',reuse_cache='N',acceptance_policy='REVIEW')
    def plan(bid,options):
        sql(f"SELECT enrichment.plan_batch({q(bid)},'ENRICH',NULL,'test-jobs','test-ncs',{js(options)}); SELECT enrichment.plan_stage({q(bid)},'extract');")
    plan(old,opts)
    sql(f"UPDATE enrichment.batch SET state='PARTIAL' WHERE batch_id={q(old)}; UPDATE enrichment.attempt SET state='REJECTED',issues='[\"fixture:rejected\"]' WHERE batch_id={q(old)}")
    plan(request,opts|dict(execute_requests='Y',repair_batch_id=old))
    plan(new,opts)
    sql(f"UPDATE enrichment.batch SET state='PARTIAL' WHERE batch_id={q(new)}; INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason) SELECT {q(new)},item_id,'{{}}','{{}}','fixture','Selection only' FROM enrichment.item WHERE batch_id={q(new)}")
    aid=sql(f'SELECT extraction_id FROM enrichment.item WHERE batch_id={q(request)}')
    count=t.request_count()
    t.run_hop('request.hpl',dict(ATTEMPT_ID=aid,API_KEY_FILE=t.REMOTE+'/key.csv'),'repair-native-reservation-protection')
    assert count==t.request_count()
    assert sql(f"SELECT state='ERROR' AND reserved_at IS NULL AND issues ? 'REPAIR_INPUT_SUPERSEDED_OR_PROTECTED' FROM enrichment.attempt WHERE attempt_id={q(aid)}")=='t'
    sql(f'SELECT enrichment.finish_batch({q(request)})')
    before=sql('SELECT count(*) FROM enrichment.batch')
    try:
        t.run_hop('enrich.hwf',dict(JOB_RUN_ID='test-jobs',NCS_RUN_ID='test-ncs',POSTING_IDS=posting,
            POSTING_LIMIT=1,REPAIR_BATCH_ID=old,PROMPT_VERSION='ko-v6',EXECUTE_REQUESTS='N',
            API_KEY_FILE='/missing.csv'),'repair-native-plan-protection')
    except AssertionError as error:
        # The all-excluded selection reaches the empty-input gate first.
        assert 'NO_POSTINGS_FOR_LLM_BATCH' in str(error),str(error)
    else:
        raise AssertionError('Native planner retried protected source')
    assert count==t.request_count() and before==sql('SELECT count(*) FROM enrichment.batch')
    print('NATIVE REPAIR PLANNING AND RESERVATION GUARDS PASSED',t.WORK,flush=True)
