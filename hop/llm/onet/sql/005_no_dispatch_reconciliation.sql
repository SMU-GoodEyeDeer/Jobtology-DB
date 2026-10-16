
-- Additive reviewed reconciliation; original terminal cost/response/history stays exact.
BEGIN;
SELECT retention.gate();
DO $qualified_base$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.task_status(text)') AND md5(prosrc) IN('24522164b57fd05018cd1a86e734ef93','9abc69146930b1c47e422b6847566601')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: task_status'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.batch_status(text)') AND md5(prosrc) IN('045757a93fa62ec3822e6a5fdba959a9','265ecd462f85dfab8f740247a5063ca8')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: batch_status'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.start_execution(text,integer,boolean)') AND md5(prosrc) IN('485341449be5258b66d5c9a2c73c4aac','224e6af1602d1d75ab28c3230c06927b')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: start_execution'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.request_context(text,uuid)') AND md5(prosrc) IN('0038f351b44b55beeb2b00c8fc37d56b','d55d4eb831346539ef7c072471ae131f')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: request_context'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.admit_request(text,uuid)') AND md5(prosrc) IN('f691da9f2b3b3d732441161a5d984452','81636efb4599001461d69a20d7c201b8','dc1c58b84d2f33a32b0cf9f5c953171f','564f4d5654739f815bb8508c0c9e169b')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: admit_request'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.approve_scale(text,text,text)') AND md5(prosrc) IN('95a85dc896d2be94d217cfe6b9dcf36d','1fa1f3a12a0d70572a156a421250976e')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: approve_scale'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.eligible_inputs(text)') AND md5(prosrc) IN('bc697d07482d84ecddbd61c390cb9451','69cd5d94fd54ac5f57b0ebe6088d0e92')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: eligible_inputs'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.output_issues(jsonb,jsonb,jsonb,integer)') AND md5(prosrc) IN('3522c0c2dbbca498ea9cf56abbe6f7b3','fbe8725c79675669155946e580a47a60')) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: output_issues'; END IF;
END $qualified_base$;

CREATE TABLE IF NOT EXISTS onet_matching.no_dispatch_reconciliation (
 reconciliation_id text PRIMARY KEY, attempt_id text NOT NULL UNIQUE REFERENCES onet_matching.attempt,
 response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[0-9a-f]{64}$'),
 effective_cost_usd numeric NOT NULL CHECK(effective_cost_usd=0),
 basis text NOT NULL CHECK(basis='OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER'),
 actor text NOT NULL CHECK(length(btrim(actor))>0), notes text NOT NULL CHECK(length(btrim(notes))>0),
 evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
 reconciled_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.task_stop (
 task_id text PRIMARY KEY REFERENCES onet_matching.task, actor text NOT NULL CHECK(length(btrim(actor))>0),
 notes text NOT NULL CHECK(length(btrim(notes))>0), stopped_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $install$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['no_dispatch_reconciliation','task_stop'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS immutable_history ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON onet_matching.%I FOR EACH ROW EXECUTE FUNCTION onet_matching.immutable()',tab);
  EXECUTE format('DROP TRIGGER IF EXISTS immutable_truncate ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON onet_matching.%I FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.immutable()',tab);
  EXECUTE format('DROP TRIGGER IF EXISTS retention_freeze ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.%I FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',tab);
 END LOOP;
END $install$;

-- Exact Python 3.12 str.strip() Unicode whitespace set. Raw quote lengths stay
-- unchanged: only the nonblank check uses trimming, as in the pinned Python code.
CREATE OR REPLACE FUNCTION onet_matching.python_strip(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT btrim(value,(SELECT string_agg(chr(code),'') FROM unnest(ARRAY[
  9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,
  8199,8200,8201,8202,8232,8233,8239,8287,12288]) code))
$$;
CREATE OR REPLACE VIEW onet_matching.accounted_attempt AS
 SELECT a.*,coalesce(a.cost_usd,r.effective_cost_usd) AS effective_cost_usd,r.reconciliation_id
 FROM onet_matching.attempt a LEFT JOIN onet_matching.no_dispatch_reconciliation r USING(attempt_id);

CREATE OR REPLACE FUNCTION onet_matching.no_dispatch_response_issue(status integer,body text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE envelope jsonb; funnel jsonb; entry jsonb; ordinal integer:=0; previous integer:=2147483647; count_now integer;
 expected text[]:=ARRAY['Initial Endpoints','Filter by Regional Surcharge','Filter by Tier Endpoint Rows','Filter by Allowed Providers'];
BEGIN
 IF status IS DISTINCT FROM 404 OR NOT coalesce(body IS JSON OBJECT WITH UNIQUE KEYS,false)
 THEN RETURN 'NOT_EVIDENCED_PRE_DISPATCH_404'; END IF;
 envelope:=body::jsonb;
 IF (SELECT count(*) FROM jsonb_object_keys(envelope))<>1 OR NOT envelope ? 'error'
  OR jsonb_typeof(envelope->'error') IS DISTINCT FROM 'object' THEN RETURN 'NOT_ROUTER_ONLY_ERROR'; END IF;
 IF envelope#>'{error,code}' IS DISTINCT FROM '404'::jsonb
  OR strpos(coalesce(envelope#>>'{error,message}',''),'No endpoints found that can handle the requested parameters.') IS DISTINCT FROM 1
  OR envelope#>>'{error,metadata,failed_routing_step}' IS DISTINCT FROM 'Filter by Parameters'
  OR jsonb_typeof(envelope#>'{error,metadata}') IS DISTINCT FROM 'object'
 THEN RETURN 'NOT_PARAMETER_FILTER_NO_ENDPOINT'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_object_keys(envelope->'error') k WHERE k NOT IN('message','code','metadata'))
  OR EXISTS(SELECT 1 FROM jsonb_object_keys(envelope#>'{error,metadata}') k WHERE k NOT IN('routing_funnel','failed_routing_step'))
 THEN RETURN 'UNEXPECTED_ROUTING_OR_PROVIDER_EVIDENCE'; END IF;
 funnel:=envelope#>'{error,metadata,routing_funnel}';
 IF jsonb_typeof(funnel) IS DISTINCT FROM 'array' OR jsonb_array_length(funnel)<>4 THEN RETURN 'ROUTING_FUNNEL_REQUIRED'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(funnel) LOOP
  ordinal:=ordinal+1;
  IF jsonb_typeof(entry) IS DISTINCT FROM 'object' OR entry->>'step' IS DISTINCT FROM expected[ordinal]
   OR coalesce(entry->>'endpoint_count','') !~ '^[1-9][0-9]{0,3}$'
   OR EXISTS(SELECT 1 FROM jsonb_object_keys(entry) k WHERE k NOT IN('step','endpoint_count','reason'))
  THEN RETURN 'ROUTING_FUNNEL_NOT_EXACT_PRE_DISPATCH_SHAPE'; END IF;
  count_now:=(entry->>'endpoint_count')::integer;
  IF count_now>previous OR ordinal=4 AND count_now<>1 THEN RETURN 'ROUTING_FUNNEL_COUNTS_INCONSISTENT'; END IF;
  previous:=count_now;
 END LOOP;
 RETURN NULL;
EXCEPTION WHEN OTHERS THEN RETURN 'INVALID_ROUTING_EVIDENCE';
END $$;
CREATE OR REPLACE FUNCTION onet_matching.assert_no_dispatch_reconciliation(aid text,response_hash text,actor text,notes text,evidence jsonb) RETURNS void LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; t onet_matching.task; i onet_matching.input; r onet_matching.no_dispatch_reconciliation;
 issue text; digest text; id text; before_at timestamptz; after_at timestamptz; key text;
BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid FOR UPDATE;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 SELECT * INTO STRICT i FROM onet_matching.input WHERE task_id=a.task_id AND posting_identity=a.posting_identity;
 digest:=encode(sha256(convert_to(a.response_body,'UTF8')),'hex');
 IF a.state IS DISTINCT FROM 'ERROR' OR a.http_status IS DISTINCT FROM 404 OR a.reserved_at IS NULL
  OR a.cost_usd IS NOT NULL OR a.response_id IS NOT NULL OR a.actual_model IS NOT NULL OR a.provider IS NOT NULL
  OR a.router_cost_usd IS NOT NULL OR a.upstream_cost_usd IS NOT NULL OR a.prompt_tokens IS NOT NULL
  OR a.completion_tokens IS NOT NULL OR a.parsed_output IS NOT NULL
  OR response_hash IS DISTINCT FROM digest
  OR t.settings->>'endpoint' IS DISTINCT FROM 'https://openrouter.ai/api/v1/chat/completions'
  OR i.request_body->>'model' IS DISTINCT FROM 'openai/gpt-5.6-luna'
  OR i.request_body#>'{provider,only}' IS DISTINCT FROM '["openai"]'::jsonb
  OR i.request_body#>'{provider,allow_fallbacks}' IS DISTINCT FROM 'false'::jsonb
  OR i.request_body#>'{provider,require_parameters}' IS DISTINCT FROM 'true'::jsonb
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_REQUIRES_EXACT_UNCHARGED_ROUTER_ATTEMPT'; END IF;
 issue:=onet_matching.no_dispatch_response_issue(a.http_status,a.response_body);
 IF issue IS NOT NULL THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_NOT_NO_DISPATCH: %',issue; END IF;
 IF nullif(onet_matching.python_strip(actor),'') IS NULL OR nullif(onet_matching.python_strip(notes),'') IS NULL
  OR jsonb_typeof(evidence) IS DISTINCT FROM 'object' OR NOT evidence ?& ARRAY[
   'basis','response_export_sha256','accounting_before_sha256','accounting_after_sha256',
   'accounting_before_basis','checked_before_at','checked_after_at','router_usage_before_usd',
   'router_usage_after_usd','byok_usage_before_usd','byok_usage_after_usd']
  OR evidence->>'basis' IS DISTINCT FROM 'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER'
  OR evidence->>'accounting_before_basis' IS DISTINCT FROM 'RETAINED_TOOL_RESPONSE_TRANSCRIPT'
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END IF;
 FOREACH key IN ARRAY ARRAY['response_export_sha256','accounting_before_sha256','accounting_after_sha256'] LOOP
  IF coalesce(evidence->>key,'') !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['router_usage_before_usd','router_usage_after_usd','byok_usage_before_usd','byok_usage_after_usd'] LOOP
  IF coalesce(evidence->>key,'') !~ '^[0-9]{1,20}(\.[0-9]{1,20})?$' THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END IF;
 END LOOP;
 BEGIN
  before_at:=(evidence->>'checked_before_at')::timestamptz; after_at:=(evidence->>'checked_after_at')::timestamptz;
 EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END;
 IF before_at IS NULL OR after_at IS NULL OR before_at>=a.reserved_at OR after_at<a.completed_at
  OR (evidence->>'router_usage_before_usd')::numeric<>(evidence->>'router_usage_after_usd')::numeric
  OR (evidence->>'byok_usage_before_usd')::numeric<>(evidence->>'byok_usage_after_usd')::numeric
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_COUNTERS_OR_OBSERVATION_TIMES_INCONSISTENT'; END IF;
 RETURN;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.reconcile_no_dispatch(aid text,response_hash text,actor text,notes text,evidence jsonb)
RETURNS jsonb LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; r onet_matching.no_dispatch_reconciliation; digest text; id text;
BEGIN
 PERFORM onet_matching.assert_no_dispatch_reconciliation(aid,response_hash,actor,notes,evidence);
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid;
 digest:=encode(sha256(convert_to(a.response_body,'UTF8')),'hex');
 id:=onet_matching.hash(jsonb_build_array('reviewed-no-dispatch-v1',aid,digest,actor,notes,evidence));
 SELECT * INTO r FROM onet_matching.no_dispatch_reconciliation WHERE attempt_id=aid;
 IF FOUND AND r.reconciliation_id<>id THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_IS_IMMUTABLE'; END IF;
 INSERT INTO onet_matching.no_dispatch_reconciliation(reconciliation_id,attempt_id,response_sha256,effective_cost_usd,basis,actor,notes,evidence)
 VALUES(id,aid,digest,0,'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER',actor,notes,evidence) ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('reconciliation_id',id,'attempt_id',aid,'response_sha256',digest,'effective_cost_usd',0,
  'original_cost_usd',a.cost_usd,'original_state',a.state,'basis','OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER');
END $$;
CREATE OR REPLACE FUNCTION onet_matching.stop_task(id text,actor text,notes text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE token uuid; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 IF nullif(onet_matching.python_strip(actor),'') IS NULL OR nullif(onet_matching.python_strip(notes),'') IS NULL
 THEN RAISE EXCEPTION 'ONET_MATCHING_TASK_STOP_REQUIRES_REVIEW'; END IF;
 INSERT INTO onet_matching.task_stop(task_id,actor,notes) VALUES(id,actor,notes) ON CONFLICT DO NOTHING;
 FOR token IN SELECT e.execution_token FROM onet_matching.execution e JOIN onet_matching.batch b USING(batch_id)
  WHERE b.task_id=id AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end finish WHERE finish.execution_token=e.execution_token) LOOP
  INSERT INTO onet_matching.execution_stop(execution_token,reason) VALUES(token,'TASK_ABANDONED_BY_COORDINATOR') ON CONFLICT DO NOTHING;
 END LOOP;
 RETURN onet_matching.task_status(id);
END $$;

CREATE OR REPLACE FUNCTION onet_matching.reconciliation_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM onet_matching.assert_no_dispatch_reconciliation(NEW.attempt_id,NEW.response_sha256,NEW.actor,NEW.notes,NEW.evidence);
 IF NEW.effective_cost_usd IS DISTINCT FROM 0 OR NEW.basis IS DISTINCT FROM 'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER'
  OR NEW.reconciliation_id IS DISTINCT FROM onet_matching.hash(jsonb_build_array('reviewed-no-dispatch-v1',
    NEW.attempt_id,NEW.response_sha256,NEW.actor,NEW.notes,NEW.evidence))
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INSERT_NOT_VERIFIED'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER verified_reconciliation_insert BEFORE INSERT ON onet_matching.no_dispatch_reconciliation
 FOR EACH ROW EXECUTE FUNCTION onet_matching.reconciliation_insert_guard();
CREATE OR REPLACE FUNCTION onet_matching.task_status(id text) RETURNS jsonb LANGUAGE sql STABLE SET jit=off AS $$
 SELECT jsonb_build_object('task_id',t.task_id,'budget_key',t.budget_key,'cap_usd',b.cap_usd,
  'task_cap_usd',(t.settings->>'max_cost_usd')::numeric,'release_id',t.release_id,'database_id',t.database_id,
  'catalog_hash',t.catalog_hash,'settings_hash',t.settings_hash,'frozen_input_count',f.input_count,'manifest_hash',f.manifest_hash,
  'accounting_usd',coalesce((SELECT sum(coalesce(a.effective_cost_usd,a.reserve_usd)) FROM onet_matching.accounted_attempt a
    JOIN onet_matching.task x USING(task_id) WHERE x.budget_key=t.budget_key AND a.reserved_at IS NOT NULL),0),
  'known_cost_usd',coalesce((SELECT sum(a.effective_cost_usd) FROM onet_matching.accounted_attempt a JOIN onet_matching.task x USING(task_id)
    WHERE x.budget_key=t.budget_key AND a.reserved_at IS NOT NULL),0),
  'unknown_holds', (SELECT count(*) FROM onet_matching.accounted_attempt a JOIN onet_matching.task x USING(task_id)
    WHERE x.budget_key=t.budget_key AND a.reserved_at IS NOT NULL AND a.effective_cost_usd IS NULL),
  'paid_attempts',(SELECT count(*) FROM onet_matching.accounted_attempt a WHERE a.task_id=t.task_id AND a.reserved_at IS NOT NULL),
  'states',(SELECT coalesce(jsonb_object_agg(state,n),'{}'::jsonb) FROM(SELECT state,count(*) n FROM onet_matching.accounted_attempt WHERE task_id=id GROUP BY state) s),
  'state',CASE WHEN EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=id) THEN 'STOPPED' ELSE 'ACTIVE' END,'no_dispatch_reconciliations',(SELECT count(*) FROM onet_matching.no_dispatch_reconciliation r JOIN onet_matching.attempt a USING(attempt_id) WHERE a.task_id=id),'scale_approved',EXISTS(SELECT 1 FROM onet_matching.scale_gate WHERE task_id=id),
  'remaining_inputs',(SELECT count(*) FROM onet_matching.input i WHERE i.task_id=id AND NOT EXISTS(
    SELECT 1 FROM onet_matching.accounted_attempt a WHERE a.task_id=id AND a.posting_identity=i.posting_identity)))
 FROM onet_matching.task t JOIN onet_matching.budget b USING(budget_key) LEFT JOIN onet_matching.freeze f USING(task_id) WHERE t.task_id=id
$$;
CREATE OR REPLACE FUNCTION onet_matching.batch_status(id text) RETURNS jsonb LANGUAGE sql STABLE SET jit=off AS $$
 SELECT jsonb_build_object('batch_id',b.batch_id,'task_id',b.task_id,'phase',b.phase,'max_requests',b.max_requests,'max_cost_usd',b.max_cost_usd,
  'execution_token',e.execution_token,'workers',e.workers,'stop_reason',s.reason,'execution_state',finish.state,
  'accounting_usd',coalesce((SELECT sum(coalesce(effective_cost_usd,reserve_usd)) FROM onet_matching.accounted_attempt WHERE batch_id=id AND reserved_at IS NOT NULL),0),
  'known_cost_usd',coalesce((SELECT sum(effective_cost_usd) FROM onet_matching.accounted_attempt WHERE batch_id=id),0),
  'unknown_holds',(SELECT count(*) FROM onet_matching.accounted_attempt WHERE batch_id=id AND reserved_at IS NOT NULL AND effective_cost_usd IS NULL),
  'states',(SELECT coalesce(jsonb_object_agg(state,n),'{}'::jsonb) FROM(SELECT state,count(*) n FROM onet_matching.accounted_attempt WHERE batch_id=id GROUP BY state) x))
 FROM onet_matching.batch b LEFT JOIN LATERAL (SELECT * FROM onet_matching.execution e WHERE e.batch_id=b.batch_id ORDER BY started_at DESC,execution_token DESC LIMIT 1) e ON true
 LEFT JOIN onet_matching.execution_stop s ON s.execution_token=e.execution_token
 LEFT JOIN onet_matching.execution_end finish ON finish.execution_token=e.execution_token WHERE b.batch_id=id
$$;
CREATE OR REPLACE FUNCTION onet_matching.start_execution(id text,worker_count integer,resume boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE b onet_matching.batch; t onet_matching.task; token uuid; previous onet_matching.execution; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO STRICT b FROM onet_matching.batch WHERE batch_id=id;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=b.task_id;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 IF EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=t.task_id) THEN RAISE EXCEPTION 'ONET_MATCHING_TASK_STOPPED'; END IF;
 IF worker_count IS NULL OR worker_count NOT BETWEEN 1 AND 16 THEN RAISE EXCEPTION 'ONET_MATCHING_INVALID_WORKERS'; END IF;
 IF t.settings->>'execute_requests'='N' THEN RETURN jsonb_build_object('batch_id',id,'execute_requests','N'); END IF;
 SELECT * INTO previous FROM onet_matching.execution WHERE batch_id=id ORDER BY started_at DESC,execution_token DESC LIMIT 1;
 IF FOUND THEN
  IF NOT resume OR
   (NOT EXISTS(SELECT 1 FROM onet_matching.execution_stop WHERE execution_token=previous.execution_token)
    AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end WHERE execution_token=previous.execution_token))
   OR EXISTS(SELECT 1 FROM onet_matching.accounted_attempt x JOIN onet_matching.task xt USING(task_id)
      WHERE xt.budget_key=t.budget_key AND x.reserved_at IS NOT NULL AND (x.state='RESERVED' OR x.effective_cost_usd IS NULL))
   OR NOT EXISTS(SELECT 1 FROM onet_matching.accounted_attempt WHERE batch_id=id AND state='PLANNED')
  THEN RAISE EXCEPTION 'ONET_MATCHING_EXECUTION_ALREADY_STARTED_NO_RETRY'; END IF;
  INSERT INTO onet_matching.execution_end(execution_token,state) VALUES(previous.execution_token,'STOPPED') ON CONFLICT DO NOTHING;
 END IF;
 token:=gen_random_uuid(); INSERT INTO onet_matching.execution(batch_id,execution_token,workers) VALUES(id,token,worker_count);
 RETURN jsonb_build_object('batch_id',id,'execution_token',token,'workers',worker_count);
END $$;
CREATE OR REPLACE FUNCTION onet_matching.request_context(aid text,token uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET jit=off AS $$
DECLARE t onet_matching.task; BEGIN
 SELECT task.* INTO t FROM onet_matching.accounted_attempt a JOIN onet_matching.task task USING(task_id)
 JOIN onet_matching.execution e ON e.batch_id=a.batch_id AND e.execution_token=token
 WHERE a.attempt_id=aid AND a.state='PLANNED' AND task.settings->>'execute_requests'='Y'
  AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_stop WHERE execution_token=token)
  AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end WHERE execution_token=token);
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=t.task_id) THEN RETURN NULL; END IF;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 IF EXISTS(SELECT 1 FROM onet_matching.accounted_attempt x JOIN onet_matching.task xt USING(task_id)
  WHERE xt.budget_key=t.budget_key AND x.reserved_at IS NOT NULL AND
   (x.state<>'RESERVED' AND (x.effective_cost_usd IS NULL OR (x.is_byok IS DISTINCT FROM true AND x.reconciliation_id IS NULL))
    OR x.state='RESERVED' AND NOT EXISTS(SELECT 1 FROM onet_matching.request_owner o
       JOIN onet_matching.execution active USING(execution_token) WHERE o.attempt_id=x.attempt_id
       AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end WHERE execution_token=active.execution_token)
       AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_stop WHERE execution_token=active.execution_token))))
 THEN RETURN NULL; END IF;
 RETURN t.settings;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.admit_request(aid text,token uuid) RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; b onet_matching.batch; t onet_matching.task; workers integer;
 held numeric; own_held numeric; batch_held numeric; reserve numeric; paid bigint; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 IF onet_matching.request_context(aid,token) IS NULL THEN RETURN false; END IF;
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid FOR UPDATE;
 SELECT * INTO STRICT b FROM onet_matching.batch WHERE batch_id=a.batch_id;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 SELECT e.workers INTO STRICT workers FROM onet_matching.execution e WHERE execution_token=token;
 IF (SELECT count(*) FROM onet_matching.accounted_attempt x JOIN onet_matching.request_owner o USING(attempt_id)
  WHERE o.execution_token=token AND x.state='RESERVED')>=workers THEN RETURN false; END IF;
 -- Never reserve the entire cohort. Each worker reserves only its next POST.
 SELECT coalesce(sum(coalesce(x.effective_cost_usd,x.reserve_usd)),0) INTO held FROM onet_matching.accounted_attempt x
  JOIN onet_matching.task xt USING(task_id) WHERE xt.budget_key=t.budget_key AND x.reserved_at IS NOT NULL;
 SELECT coalesce(sum(coalesce(effective_cost_usd,reserve_usd)),0) INTO own_held FROM onet_matching.accounted_attempt WHERE task_id=t.task_id AND reserved_at IS NOT NULL;
 SELECT count(*) INTO paid FROM onet_matching.accounted_attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL;
 SELECT coalesce(sum(coalesce(effective_cost_usd,reserve_usd)),0) INTO batch_held FROM onet_matching.accounted_attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL;
 reserve:=(t.settings->>'request_reserve_usd')::numeric;
 IF held+reserve>(SELECT cap_usd FROM onet_matching.budget WHERE budget_key=t.budget_key)
  OR own_held+reserve>(t.settings->>'max_cost_usd')::numeric OR batch_held+reserve>b.max_cost_usd OR paid>=b.max_requests
 THEN UPDATE onet_matching.attempt SET state='BUDGET_BLOCKED',issues='["COMBINED_ACCOUNTING_CAP_OR_REQUEST_COUNT"]' WHERE attempt_id=aid;
  INSERT INTO onet_matching.execution_stop(execution_token,reason) VALUES(token,'BUDGET_OR_REQUEST_COUNT') ON CONFLICT DO NOTHING;
  RETURN false;
 END IF;
 -- Same frozen paid request cannot be retried under a fresh task identity.
 IF EXISTS(SELECT 1 FROM onet_matching.accounted_attempt old JOIN onet_matching.input oi USING(task_id,posting_identity)
  JOIN onet_matching.task ot USING(task_id) JOIN onet_matching.input current ON current.task_id=a.task_id AND current.posting_identity=a.posting_identity
  WHERE old.reserved_at IS NOT NULL AND ot.budget_key=t.budget_key AND oi.posting_identity=current.posting_identity
   AND oi.source_hash=current.source_hash AND oi.request_hash=current.request_hash AND ot.catalog_hash=t.catalog_hash)
 THEN RAISE EXCEPTION 'ONET_MATCHING_ALREADY_PAID_NO_RETRY'; END IF;
 UPDATE onet_matching.attempt SET state='RESERVED',reserve_usd=reserve,reserved_at=clock_timestamp() WHERE attempt_id=aid;
 INSERT INTO onet_matching.request_owner(attempt_id,execution_token) VALUES(aid,token);
 RETURN true;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.approve_scale(id text,actor text,notes text) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE accounting jsonb; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 accounting:=onet_matching.task_status(id);
 IF accounting IS NULL OR EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=id) OR nullif(btrim(actor),'') IS NULL OR nullif(btrim(notes),'') IS NULL
  OR (accounting->>'unknown_holds')::bigint<>0 OR (accounting->>'paid_attempts')::bigint=0
  OR NOT EXISTS(SELECT 1 FROM onet_matching.accounted_attempt a JOIN onet_matching.batch b USING(batch_id)
    WHERE a.task_id=id AND b.phase='PILOT' AND a.state='VALIDATED' AND a.is_byok=true AND a.effective_cost_usd IS NOT NULL)
  OR EXISTS(SELECT 1 FROM onet_matching.accounted_attempt a WHERE a.task_id=id AND a.reserved_at IS NOT NULL AND a.reconciliation_id IS NULL
    AND (a.state='RESERVED' OR a.is_byok IS DISTINCT FROM true OR a.actual_model IS DISTINCT FROM 'openai/gpt-5.6-luna'))
 THEN RAISE EXCEPTION 'ONET_MATCHING_SCALE_REQUIRES_MEASURED_REVIEWED_BYOK_PILOT'; END IF;
 INSERT INTO onet_matching.scale_gate(task_id,actor,notes,accounting) VALUES(id,actor,notes,accounting) ON CONFLICT DO NOTHING;
 RETURN onet_matching.task_status(id);
END $$;
CREATE OR REPLACE FUNCTION onet_matching.eligible_inputs(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce(jsonb_agg(i.posting_identity ORDER BY i.posting_identity),'[]'::jsonb)
 FROM onet_matching.input i WHERE i.task_id=id AND NOT EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=id) AND NOT EXISTS(
  SELECT 1 FROM onet_matching.accounted_attempt a WHERE a.task_id=id AND a.posting_identity=i.posting_identity)
$$;
CREATE OR REPLACE FUNCTION onet_matching.output_issues(output jsonb,source jsonb,candidates jsonb,max_matches integer)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]'; match jsonb; citation jsonb; seen text[]:='{}'; rank integer:=0; code text; field text; quote text;
BEGIN
 IF jsonb_typeof(output) IS DISTINCT FROM 'object' OR NOT output ?& ARRAY['outcome','matches','abstain_reason']
  OR (SELECT count(*) FROM jsonb_object_keys(output))<>3
  OR jsonb_typeof(output->'outcome') IS DISTINCT FROM 'string' OR output->>'outcome' NOT IN('matched','abstained')
  OR jsonb_typeof(output->'matches') IS DISTINCT FROM 'array'
  OR jsonb_typeof(output->'abstain_reason') IS DISTINCT FROM 'string'
  OR length(output->>'abstain_reason')>500 THEN RETURN '["OUTPUT_SHAPE"]'; END IF;
 IF jsonb_array_length(output->'matches')>max_matches OR max_matches NOT BETWEEN 1 AND 3
  OR (output->>'outcome'='matched' AND (jsonb_array_length(output->'matches')=0 OR output->>'abstain_reason'<>''))
  OR (output->>'outcome'='abstained' AND (jsonb_array_length(output->'matches')<>0 OR length(onet_matching.python_strip(output->>'abstain_reason'))=0))
 THEN errors:=errors||'["OUTCOME_OR_MATCH_LIMIT"]'::jsonb; END IF;
 FOR match IN SELECT value FROM jsonb_array_elements(output->'matches') LOOP
  rank:=rank+1; code:=match->>'occupation_code';
  IF jsonb_typeof(match) IS DISTINCT FROM 'object' OR NOT match ?& ARRAY['occupation_code','match_rank','reason','evidence']
   OR (SELECT count(*) FROM jsonb_object_keys(match))<>4 OR code !~ '^[0-9]{2}-[0-9]{4}\.[0-9]{2}$'
   OR code=ANY(seen) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(candidates) c WHERE c->>'occupation_code'=code)
   OR match->'match_rank' IS DISTINCT FROM to_jsonb(rank) OR match->>'match_rank' !~ '^[1-3]$'
   OR jsonb_typeof(match->'reason') IS DISTINCT FROM 'string' OR nullif(onet_matching.python_strip(match->>'reason'),'') IS NULL
   OR length(match->>'reason') NOT BETWEEN 1 AND 500
   OR jsonb_typeof(match->'evidence') IS DISTINCT FROM 'array'
  THEN errors:=errors||'["MATCH_SHAPE_CODE_RANK_OR_REASON"]'::jsonb; CONTINUE; END IF;
  seen:=array_append(seen,code);
  IF jsonb_array_length(match->'evidence') NOT BETWEEN 1 AND 3 THEN errors:=errors||'["EVIDENCE_COUNT"]'::jsonb; END IF;
  FOR citation IN SELECT value FROM jsonb_array_elements(match->'evidence') LOOP
   field:=citation->>'field'; quote:=citation->>'quote';
   IF jsonb_typeof(citation) IS DISTINCT FROM 'object' OR NOT citation ?& ARRAY['field','quote']
    OR (SELECT count(*) FROM jsonb_object_keys(citation))<>2
    OR field NOT IN('title','role','job_functions','job_position_raw','positions','duties_text','description_text')
    OR jsonb_typeof(citation->'quote') IS DISTINCT FROM 'string' OR nullif(onet_matching.python_strip(quote),'') IS NULL
    OR length(quote) NOT BETWEEN 2 AND 500
    OR NOT EXISTS(SELECT 1 FROM onet_matching.string_leaves(source->field) s WHERE position(quote IN s.leaf)>0)
   THEN errors:=errors||'["INVALID_EXACT_SOURCE_CITATION"]'::jsonb; END IF;
  END LOOP;
 END LOOP;
 RETURN errors;
END $$;
COMMIT;
