-- Generator input; included by 030_metadata_occupation_native.sql, not installed separately.
CREATE OR REPLACE FUNCTION enrichment.plan_metadata_occupation_batch(id text,jobs text,ncs text,opts jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE j text; n text; nh text; settings jsonb; selected text[]; source record;
 i text; a text; candidates jsonb; binding jsonb; data jsonb; request jsonb; schema jsonb;
 p enrichment.prompt%ROWTYPE; cache text; reused text; status text; ordinal integer:=0; catalog jsonb;
BEGIN
 PERFORM retention.gate();
 IF id !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$' OR jsonb_typeof(opts) IS DISTINCT FROM 'object' OR
 NOT opts ?& ARRAY['categorize_model','extra_params','limit','candidate_limit','max_matches',
 'max_input_chars','max_output_tokens','max_requests','request_reserve_usd','max_cost_usd','daily_budget_usd',
 'request_delay_ms','read_timeout_ms','execute_requests','reuse_cache','endpoint'] OR
 (opts->>'limit')::integer NOT BETWEEN 1 AND 10000 OR
 (opts->>'candidate_limit')::integer NOT BETWEEN 1 AND 30 OR
 (opts->>'max_matches')::integer NOT BETWEEN 1 AND 2 OR
 (opts->>'max_input_chars')::integer NOT BETWEEN 1000 AND 100000 OR
 (opts->>'max_output_tokens')::integer NOT BETWEEN 256 AND 2048 OR
 (opts->>'max_requests')::integer NOT BETWEEN 1 AND 10000 OR
 (opts->>'request_reserve_usd')::numeric NOT BETWEEN 0.001 AND 1 OR
 (opts->>'max_cost_usd')::numeric NOT BETWEEN 0.001 AND 50 OR
 (opts->>'daily_budget_usd')::numeric NOT BETWEEN 0.001 AND 50 OR
 (opts->>'request_delay_ms')::integer NOT BETWEEN 0 AND 60000 OR
 (opts->>'read_timeout_ms')::integer NOT BETWEEN 1000 AND 600000 OR
 opts->>'execute_requests' NOT IN ('Y','N') OR opts->>'reuse_cache' NOT IN ('Y','N') OR
 nullif(opts->>'categorize_model','') IS NULL OR
 (opts->>'endpoint' IS DISTINCT FROM 'https://openrouter.ai/api/v1/chat/completions' AND
  NOT(coalesce(current_setting('jobtology.isolated_fixture',true),'') ~ '^[0-9a-f]{12}$' AND
   opts->>'endpoint' ~ ('^http://jobtology-jobkorea-test-'||current_setting('jobtology.isolated_fixture',true)||'-mock:[0-9]{1,5}/chat/completions$')
   AND opts->>'categorize_model'='fixture/metadata'))
 THEN RAISE EXCEPTION 'INVALID_METADATA_OCCUPATION_OPTIONS'; END IF;
 IF opts->>'endpoint'='https://openrouter.ai/api/v1/chat/completions' AND
  (opts->>'categorize_model' IS DISTINCT FROM 'openai/gpt-5.6-luna' OR opts->>'provider_only' IS DISTINCT FROM 'openai')
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REQUIRES_PRICED_MODEL_AND_PROVIDER'; END IF;
 IF opts->>'temperature' IS NOT NULL AND (opts->>'temperature')::numeric NOT BETWEEN 0 AND 2
 THEN RAISE EXCEPTION 'INVALID_TEMPERATURE'; END IF;
 IF opts->>'reasoning_effort' IS NOT NULL AND opts->>'reasoning_effort' NOT IN ('none','minimal','low','medium','high')
 THEN RAISE EXCEPTION 'INVALID_REASONING_EFFORT'; END IF;
 IF opts ? 'provider_only' AND (jsonb_typeof(opts->'provider_only') IS DISTINCT FROM 'string' OR
  opts->>'provider_only' !~ '^[a-z0-9][a-z0-9_./-]{0,127}$')
 THEN RAISE EXCEPTION 'INVALID_PROVIDER_SLUG'; END IF;
 IF jsonb_typeof(opts->'extra_params') IS DISTINCT FROM 'object' OR EXISTS(
 SELECT 1 FROM jsonb_object_keys(opts->'extra_params') k WHERE k NOT IN ('top_p','seed','frequency_penalty','presence_penalty')) OR
 EXISTS(SELECT 1 FROM jsonb_each(opts->'extra_params') WHERE jsonb_typeof(value)<>'number') OR
 coalesce((opts#>>'{extra_params,top_p}')::numeric,1) NOT BETWEEN 0 AND 1 OR
 coalesce((opts#>>'{extra_params,frequency_penalty}')::numeric,0) NOT BETWEEN -2 AND 2 OR
 coalesce((opts#>>'{extra_params,presence_penalty}')::numeric,0) NOT BETWEEN -2 AND 2
 THEN RAISE EXCEPTION 'INVALID_EXTRA_PARAMS'; END IF;
 IF nullif(opts->>'posting_ids','') IS NOT NULL THEN
  selected:=string_to_array(opts->>'posting_ids','|');
  IF cardinality(selected)=0 OR cardinality(selected)>(opts->>'limit')::integer OR
   cardinality(selected)<>(SELECT count(DISTINCT v) FROM unnest(selected) v) OR
   EXISTS(SELECT 1 FROM unnest(selected) v WHERE v !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$')
  THEN RAISE EXCEPTION 'INVALID_POSTING_SELECTION'; END IF;
 END IF;
 j:=enrichment.resolve_snapshot(jobs,'jobkorea'); n:=enrichment.resolve_snapshot(ncs,'ncs_competency');
 catalog:=enrichment.prepare_metadata_occupation_catalog(n);
 nh:=catalog->>'catalog_hash';
 IF nh IS NULL THEN RAISE EXCEPTION 'EMPTY_NCS_CATALOG'; END IF;
 settings:=opts||jsonb_build_object('metadata_scope','NCS_OCCUPATION_INFERENCE_V1','prompt_version','ko-metadata-occupation-v1',
  'job_source_id','jobkorea','extract_model','unused/metadata-only','acceptance_policy','REVIEW');
 PERFORM pg_advisory_xact_lock(hashtextextended('metadata-occupation-batch:'||id,0));
 IF EXISTS(SELECT 1 FROM enrichment.batch WHERE batch_id=id) THEN
  IF NOT EXISTS(SELECT 1 FROM enrichment.batch WHERE batch_id=id AND job_run_id=j AND ncs_run_id=n AND settings=plan_metadata_occupation_batch.settings)
  THEN RAISE EXCEPTION 'METADATA_BATCH_IS_IMMUTABLE'; END IF;
  RETURN jsonb_build_object('batch_id',id,'job_run_id',j,'ncs_run_id',n,'replay',true);
 END IF;
 SELECT * INTO STRICT p FROM enrichment.prompt WHERE version='ko-metadata-occupation-v1' AND stage='categorize';
 INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state)
 VALUES(id,'ENRICH',j,n,nh,settings,CASE WHEN opts->>'execute_requests'='Y' THEN 'RUNNING' ELSE 'PLANNED' END);
 FOR source IN SELECT DISTINCT ON (b.posting_id) b.* FROM enrichment.input_bundle b
 WHERE b.job_run_id=j AND b.source_data#>>'{_input,contract}'='jobkorea-input-v1'
 AND (selected IS NULL OR b.posting_id=ANY(selected))
 AND (selected IS NOT NULL OR NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_binding prior
  JOIN enrichment.item old ON old.item_id=prior.item_id
  JOIN enrichment.attempt oa ON oa.attempt_id=old.categorization_id
  WHERE prior.job_run_id=j AND prior.ncs_run_id=n AND old.posting_id=b.posting_id AND prior.source_hash=b.source_hash
  AND (oa.state IN ('VALIDATED','SKIPPED') OR oa.reserved_at IS NOT NULL)))
 ORDER BY b.posting_id,b.created_at,b.bundle_id LIMIT (opts->>'limit')::integer LOOP
  PERFORM enrichment.verify_input_bundle(source.bundle_id);
  ordinal:=ordinal+1; i:=gen_random_uuid()::text; a:=gen_random_uuid()::text;
  INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal)
  VALUES(i,id,source.posting_id,source.source_data,source.source_hash,ordinal);
  INSERT INTO enrichment.item_input(item_id,bundle_id) VALUES(i,source.bundle_id);
  candidates:=enrichment.metadata_occupation_candidates(n,source.source_data,(opts->>'candidate_limit')::integer);
  binding:=enrichment.bind_metadata_occupation_item(i,source.bundle_id,candidates);
  schema:=p.output_schema;
  schema:=jsonb_set(schema,'{properties,matches,maxItems}',to_jsonb((opts->>'max_matches')::integer));
  IF jsonb_array_length(candidates)>0 THEN
   schema:=jsonb_set(schema,'{properties,matches,items,properties,occupation_code}',jsonb_build_object('type','string','enum',
    (SELECT jsonb_agg(c->'occupation_code') FROM jsonb_array_elements(candidates) c)));
  ELSE schema:=jsonb_set(schema,'{properties,matches,maxItems}','0'); END IF;
  data:=jsonb_build_object('metadata',enrichment.metadata_occupation_fields(source.source_data),
   'candidates',(SELECT coalesce(jsonb_agg(jsonb_build_object('occupation_code',c->'occupation_code',
    'occupation_name',c->'occupation_name','classification_names',c->'classification_names',
    'representative_unit_names',(SELECT coalesce(jsonb_agg(u.value ORDER BY u.ordinal),'[]')
     FROM jsonb_array_elements(c->'unit_names') WITH ORDINALITY u(value,ordinal) WHERE u.ordinal<=3))),'[]')
    FROM jsonb_array_elements(candidates) c),
   'max_matches',(opts->>'max_matches')::integer);
  request:=jsonb_build_object('model',opts->>'categorize_model','messages',jsonb_build_array(
   jsonb_build_object('role','system','content',p.system_prompt),jsonb_build_object('role','user','content',data::text)),
   'response_format',jsonb_build_object('type','json_schema','json_schema',jsonb_build_object('name','jobtology_metadata_occupation','strict',true,'schema',schema)),
   'provider',jsonb_build_object('require_parameters',true,'allow_fallbacks',false,
    'max_price',jsonb_build_object('prompt',0.20,'completion',1.20)),
   'max_tokens',(opts->>'max_output_tokens')::integer,'stream',false)
   || (opts->'extra_params');
  IF opts->>'provider_only' IS NOT NULL THEN request:=jsonb_set(request,'{provider,only}',jsonb_build_array(opts->>'provider_only')); END IF;
  IF opts->>'temperature' IS NOT NULL THEN request:=request||jsonb_build_object('temperature',(opts->>'temperature')::numeric); END IF;
  IF opts->>'reasoning_effort' IS NOT NULL THEN request:=request||jsonb_build_object('reasoning',jsonb_build_object('effort',opts->>'reasoning_effort','exclude',true)); END IF;
  cache:=enrichment.hash(jsonb_build_object('request',request,'prompt_hash',p.content_hash,'endpoint',opts->>'endpoint',
   'metadata_hash',binding->>'metadata_hash','candidates_hash',binding->>'candidates_hash',
   'ncs_hash',nh,'validator','metadata-occupation-v1','retriever','metadata-occupation-lexical-v1')::text);
  reused:=NULL;
  IF opts->>'reuse_cache'='Y' THEN
   SELECT old.attempt_id INTO reused FROM enrichment.attempt old JOIN enrichment.batch ob ON ob.batch_id=old.batch_id
   WHERE old.cache_key=cache AND (old.state='VALIDATED' OR (old.batch_id=id AND old.state='PLANNED'))
   AND ob.settings->>'metadata_scope'='NCS_OCCUPATION_INFERENCE_V1'
   AND NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_result r
    JOIN LATERAL(SELECT decision FROM enrichment.metadata_occupation_decision d WHERE d.result_id=r.result_id ORDER BY decision_id DESC LIMIT 1) d ON true
    WHERE r.attempt_id=old.attempt_id AND d.decision='REJECT')
   ORDER BY old.completed_at DESC,old.attempt_id LIMIT 1;
  END IF;
  IF reused IS NOT NULL THEN a:=reused;
  ELSE
   status:=CASE WHEN jsonb_array_length(candidates)=0 THEN 'SKIPPED' ELSE 'PLANNED' END;
   request:=request||jsonb_build_object('session_id',id,'trace',jsonb_build_object('trace_id',replace(i,'-',''),
    'trace_name','JobKorea inferred occupation','span_name','metadata_occupation','environment','staging',
    'release','ko-metadata-occupation-v1','posting_id',source.posting_id,'batch_id',id,'attempt_id',a,
    'job_run_id',j,'ncs_run_id',n,'source_bundle_id',source.bundle_id,'binding_hash',binding->>'binding_hash'));
   IF status<>'SKIPPED' AND (length(request::text)>(opts->>'max_input_chars')::integer OR octet_length(request::text)+256>=272000 OR
    1.05*(0.25*(octet_length(request::text)+256)+1.20*(opts->>'max_output_tokens')::integer)/1000000
     >(opts->>'request_reserve_usd')::numeric) THEN status:='REJECTED'; END IF;
   INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,candidates,state,parsed_output,issues,completed_at)
   VALUES(a,id,i,'categorize',cache,request,candidates,status,
    CASE WHEN status='SKIPPED' THEN jsonb_build_object('outcome','abstained','matches','[]'::jsonb,'abstain_reason','No occupation candidates retrieved from supplied metadata.') END,
    CASE WHEN status='SKIPPED' THEN '["NO_METADATA_OCCUPATION_CANDIDATES"]'::jsonb WHEN status='REJECTED' THEN '["INPUT_OR_COST_BOUND_EXCEEDED"]'::jsonb ELSE '[]'::jsonb END,
    CASE WHEN status IN ('SKIPPED','REJECTED') THEN clock_timestamp() END);
  END IF;
  UPDATE enrichment.item SET categorization_id=a WHERE item_id=i;
 END LOOP;
 IF selected IS NOT NULL AND ordinal<>cardinality(selected) THEN RAISE EXCEPTION 'INCOMPLETE_FROZEN_METADATA_SELECTION'; END IF;
 RETURN jsonb_build_object('batch_id',id,'job_run_id',j,'ncs_run_id',n,'postings',ordinal,'metadata_scope','NCS_OCCUPATION_INFERENCE_V1',
  'planned_requests',(SELECT count(*) FROM enrichment.attempt WHERE batch_id=id AND state='PLANNED'),
  'no_candidate_abstentions',(SELECT count(*) FROM enrichment.attempt WHERE batch_id=id AND state='SKIPPED'));
END $$;

CREATE OR REPLACE FUNCTION enrichment.finish_metadata_occupation_batch(id text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b enrichment.batch%ROWTYPE; current_item record; result jsonb; BEGIN
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=id FOR UPDATE;
 IF b.settings->>'metadata_scope' IS DISTINCT FROM 'NCS_OCCUPATION_INFERENCE_V1' THEN RAISE EXCEPTION 'METADATA_BATCH_REQUIRED'; END IF;
 FOR current_item IN SELECT i.item_id,a.state FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.categorization_id
 WHERE i.batch_id=id ORDER BY i.ordinal LOOP
  PERFORM enrichment.verify_item_input(current_item.item_id);
  IF current_item.state IN ('VALIDATED','SKIPPED') THEN
   PERFORM enrichment.capture_metadata_occupation_result(current_item.item_id,'native-metadata-occupation-planner');
   UPDATE enrichment.item SET state='VALIDATED' WHERE item_id=current_item.item_id;
  ELSIF current_item.state IN ('REJECTED','ERROR','BUDGET_BLOCKED') THEN UPDATE enrichment.item SET state='REJECTED' WHERE item_id=current_item.item_id;
  END IF;
 END LOOP;
 IF b.settings->>'execute_requests'='Y' THEN
  UPDATE enrichment.batch SET state=CASE WHEN EXISTS(SELECT 1 FROM enrichment.item WHERE batch_id=id AND state<>'VALIDATED')
   THEN 'PARTIAL' ELSE 'COMPLETE' END,completed_at=clock_timestamp() WHERE batch_id=id;
 END IF;
 SELECT jsonb_build_object('batch_id',actual.batch_id,'state',actual.state,'job_run_id',actual.job_run_id,'ncs_run_id',actual.ncs_run_id,
  'postings',(SELECT count(*) FROM enrichment.item WHERE batch_id=id),
  'validated',(SELECT count(*) FROM enrichment.item WHERE batch_id=id AND state='VALIDATED'),
  'matched',(SELECT count(*) FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id=id AND r.output->>'outcome'='matched'),
  'abstained',(SELECT count(*) FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id=id AND r.output->>'outcome'='abstained'),
  'cached_postings',(SELECT count(*) FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.categorization_id WHERE i.batch_id=id AND a.item_id<>i.item_id),
  'not_sent_requests',(SELECT count(*) FROM enrichment.attempt WHERE batch_id=id AND reserved_at IS NULL AND state IN ('PLANNED','BUDGET_BLOCKED')),
  'requests',(SELECT count(*) FROM enrichment.attempt WHERE batch_id=id AND reserved_at IS NOT NULL),
  'reported_cost_usd',(SELECT coalesce(sum(cost_usd),0) FROM enrichment.attempt WHERE batch_id=id AND reserved_at IS NOT NULL),
  'accounted_cost_usd',(SELECT coalesce(sum(enrichment.accounted_cost(state,cost_usd,reserved_usd)),0) FROM enrichment.attempt WHERE batch_id=id AND reserved_at IS NOT NULL),
  'unknown_cost_requests',(SELECT count(*) FROM enrichment.attempt WHERE batch_id=id AND reserved_at IS NOT NULL AND cost_usd IS NULL))
 INTO result FROM enrichment.batch actual WHERE actual.batch_id=id;
 RETURN result;
END $$;
