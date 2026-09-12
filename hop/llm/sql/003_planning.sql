BEGIN;
CREATE OR REPLACE FUNCTION enrichment.prepare_dataset(id text, jobs text, ncs text, size integer, sample_seed text)
RETURNS void LANGUAGE plpgsql AS $$ DECLARE j text; n text; BEGIN
 IF id !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$' OR size NOT BETWEEN 1 AND 1000 OR
 nullif(sample_seed,'') IS NULL THEN RAISE EXCEPTION 'INVALID_DATASET_OPTIONS'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('llm-dataset:'||id,0));
 IF EXISTS(SELECT 1 FROM enrichment.dataset WHERE dataset_id=id) THEN
   IF NOT EXISTS(SELECT 1 FROM enrichment.dataset WHERE dataset_id=id AND requested_size=size
    AND seed=sample_seed AND (jobs='LATEST' OR job_run_id=jobs) AND (ncs='LATEST' OR ncs_run_id=ncs))
   THEN RAISE EXCEPTION 'DATASET_IS_FROZEN_USE_A_NEW_ID'; END IF;
   RETURN;
 END IF;
 j:=enrichment.resolve_snapshot(jobs,'job_alio'); n:=enrichment.resolve_snapshot(ncs,'ncs_competency');
 INSERT INTO enrichment.dataset(dataset_id,job_run_id,ncs_run_id,seed,requested_size) VALUES(id,j,n,sample_seed,size);
 INSERT INTO enrichment.test_case(dataset_id,posting_id,source_data,source_hash,stratum,ordinal)
 WITH src AS MATERIALIZED (
  SELECT posting_id,enrichment.source_fields(normalized) AS data,
   CASE WHEN normalized->>'eligibility_text' ~ '(또는|혹은|중 하나)' THEN 'alternatives'
        WHEN normalized->>'eligibility_text' ~ '(A0[0-9]|B0[0-9]|분야별|직무별)' THEN 'multiple_positions'
        WHEN normalized::text ~ '(첨부|붙임)' THEN 'attachment_reference'
        WHEN normalized->>'eligibility_text' ~ '(경력.*무관|제한 없음|제한없음)' THEN 'unrestricted'
        ELSE 'general' END AS stratum
  FROM ingestion.job_posting WHERE run_id=j
 ), ranked AS (
  SELECT *,row_number() OVER(PARTITION BY stratum ORDER BY enrichment.hash(sample_seed||posting_id),posting_id) AS r FROM src
 ), picked AS (
  SELECT *,row_number() OVER(ORDER BY r,stratum,posting_id) AS ordinal FROM ranked ORDER BY r,stratum,posting_id LIMIT size
 ) SELECT id,posting_id,data,enrichment.hash(data::text),stratum,ordinal FROM picked;
 IF NOT FOUND THEN RAISE EXCEPTION 'NO_POSTINGS_FOR_DATASET'; END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.plan_batch(id text, run_mode text, dataset text, jobs text, ncs text, opts jsonb)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE j text; n text; nh text; s text; BEGIN
 IF run_mode NOT IN ('EVAL','ENRICH') OR jsonb_typeof(opts) IS DISTINCT FROM 'object' OR
 NOT opts ?& ARRAY['extract_model','categorize_model','prompt_version','extra_params','limit','candidate_limit','max_matches',
 'max_input_chars','max_output_tokens','max_requests','request_reserve_usd','max_cost_usd','daily_budget_usd',
 'request_delay_ms','read_timeout_ms','execute_requests','reuse_cache','endpoint','acceptance_policy'] OR
 (opts->>'limit')::integer NOT BETWEEN 1 AND 10000 OR
 (opts->>'candidate_limit')::integer NOT BETWEEN 1 AND 100 OR
 (opts->>'max_matches')::integer NOT BETWEEN 1 AND 20 OR
 (opts->>'max_input_chars')::integer NOT BETWEEN 1000 AND 200000 OR
 (opts->>'max_output_tokens')::integer NOT BETWEEN 256 AND 32000 OR
 (opts->>'max_requests')::integer NOT BETWEEN 1 AND 20000 OR
 (opts->>'request_reserve_usd')::numeric NOT BETWEEN 0.001 AND 100 OR
 (opts->>'max_cost_usd')::numeric NOT BETWEEN 0.001 AND 10000 OR
 (opts->>'daily_budget_usd')::numeric NOT BETWEEN 0.001 AND 10000 OR
 (opts->>'request_delay_ms')::integer NOT BETWEEN 0 AND 60000 OR
 (opts->>'read_timeout_ms')::integer NOT BETWEEN 1000 AND 600000 OR
 opts->>'execute_requests' NOT IN ('Y','N') OR opts->>'reuse_cache' NOT IN ('Y','N') OR
 opts->>'acceptance_policy' NOT IN ('REVIEW','VALIDATED') OR
 opts->>'endpoint' !~ '^https://[^/?#@]+(/[^?#]*)?/chat/completions$' OR
 nullif(opts->>'extract_model','') IS NULL OR nullif(opts->>'categorize_model','') IS NULL
 THEN RAISE EXCEPTION 'INVALID_LLM_OPTIONS'; END IF;
 IF opts->>'temperature' IS NOT NULL AND (opts->>'temperature')::numeric NOT BETWEEN 0 AND 2
 THEN RAISE EXCEPTION 'INVALID_TEMPERATURE'; END IF;
 IF opts->>'reasoning_effort' IS NOT NULL AND opts->>'reasoning_effort' NOT IN
 ('none','minimal','low','medium','high','xhigh','max') THEN RAISE EXCEPTION 'INVALID_REASONING_EFFORT'; END IF;
 IF jsonb_typeof(opts->'extra_params') IS DISTINCT FROM 'object' OR EXISTS(
 SELECT 1 FROM jsonb_object_keys(opts->'extra_params') k WHERE k NOT IN ('top_p','seed','frequency_penalty','presence_penalty'))
 THEN RAISE EXCEPTION 'EXTRA_PARAMS_ALLOW_TOP_P_SEED_FREQUENCY_PENALTY_PRESENCE_PENALTY_ONLY'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_each(opts->'extra_params') WHERE jsonb_typeof(value)<>'number') OR
 coalesce((opts#>>'{extra_params,top_p}')::numeric,1) NOT BETWEEN 0 AND 1 OR
 coalesce((opts#>>'{extra_params,frequency_penalty}')::numeric,0) NOT BETWEEN -2 AND 2 OR
 coalesce((opts#>>'{extra_params,presence_penalty}')::numeric,0) NOT BETWEEN -2 AND 2
 THEN RAISE EXCEPTION 'INVALID_EXTRA_PARAMS'; END IF;
 IF run_mode='EVAL' THEN
  SELECT job_run_id,ncs_run_id INTO j,n FROM enrichment.dataset WHERE dataset_id=plan_batch.dataset;
  IF j IS NULL THEN RAISE EXCEPTION 'PREPARE_EVALUATION_DATASET_FIRST'; END IF;
 ELSE j:=enrichment.resolve_snapshot(jobs,'job_alio'); n:=enrichment.resolve_snapshot(ncs,'ncs_competency'); END IF;
 PERFORM enrichment.assert_snapshot(j,'job_alio'); PERFORM enrichment.assert_snapshot(n,'ncs_competency');
 FOREACH s IN ARRAY ARRAY['extract','categorize'] LOOP
  IF NOT EXISTS(SELECT 1 FROM enrichment.prompt WHERE version=opts->>'prompt_version' AND stage=s)
  THEN RAISE EXCEPTION 'UNKNOWN_PROMPT_VERSION'; END IF;
 END LOOP;
 INSERT INTO enrichment.ncs_catalog(run_id,code,name,definition,occupation_code,occupation_name)
 SELECT run_id,code,name,definition,occupation_code,occupation_name FROM ingestion.competency WHERE run_id=n
 ON CONFLICT DO NOTHING;
 SELECT enrichment.hash(string_agg(jsonb_build_array(code,name,definition,occupation_code,occupation_name)::text,E'\n' ORDER BY code))
 INTO nh FROM enrichment.ncs_catalog WHERE run_id=n;
 IF nh IS NULL THEN RAISE EXCEPTION 'EMPTY_NCS_CATALOG'; END IF;
 INSERT INTO enrichment.batch(batch_id,mode,dataset_id,job_run_id,ncs_run_id,ncs_hash,settings,state)
 VALUES(id,run_mode,CASE WHEN run_mode='EVAL' THEN plan_batch.dataset END,j,n,nh,opts,
 CASE WHEN opts->>'execute_requests'='Y' THEN 'RUNNING' ELSE 'PLANNED' END);
 IF run_mode='EVAL' THEN
  INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal,gold_id)
  SELECT gen_random_uuid()::text,id,c.posting_id,c.source_data,c.source_hash,c.ordinal,
  (SELECT g.gold_id FROM enrichment.gold g WHERE g.dataset_id=c.dataset_id AND g.posting_id=c.posting_id ORDER BY gold_id DESC LIMIT 1)
  FROM enrichment.test_case c WHERE dataset_id=plan_batch.dataset ORDER BY ordinal LIMIT (opts->>'limit')::integer;
 ELSE
  INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal)
  SELECT gen_random_uuid()::text,id,posting_id,enrichment.source_fields(normalized),
   enrichment.hash(enrichment.source_fields(normalized)::text),row_number() OVER(ORDER BY posting_id)
  FROM ingestion.job_posting WHERE run_id=j ORDER BY posting_id LIMIT (opts->>'limit')::integer;
 END IF;
 IF NOT FOUND THEN RAISE EXCEPTION 'NO_POSTINGS_FOR_LLM_BATCH'; END IF;
END $$;

-- Deterministic Korean substring/token retrieval. The model sees only this shortlist.
-- Category codes add a small ranking hint, never create a candidate without lexical evidence.
CREATE OR REPLACE FUNCTION enrichment.candidates(ncs_run text, source jsonb, extraction jsonb, cap integer)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH query AS (
  SELECT string_agg(d->>'text',' ') AS text FROM jsonb_array_elements(extraction->'duties') d
 ), tokens AS MATERIALIZED (
  SELECT DISTINCT regexp_replace(token,'(으로|에서|하는|한다|합니다)$','') AS token
  FROM query,regexp_split_to_table(lower(text),'[^가-힣a-z0-9]+') token
  WHERE length(token) BETWEEN 2 AND 40 AND token NOT IN ('업무','직무','관련','담당','수행','관리','지원','대한','통한')
  ORDER BY token LIMIT 80
 ), scored AS (
  SELECT c.*,sum(CASE WHEN position(t.token in lower(c.name))>0 THEN 6
                   WHEN position(t.token in lower(coalesce(c.occupation_name,'')))>0 THEN 3 ELSE 1 END)
       + CASE WHEN position('R6000'||left(c.code,2) in coalesce(source->>'ncs_category_codes',''))>0 THEN 1 ELSE 0 END AS score
  FROM enrichment.ncs_catalog c JOIN tokens t ON position(t.token in
   lower(c.name||' '||coalesce(c.occupation_name,'')||' '||coalesce(c.definition,'')))>0
  WHERE c.run_id=ncs_run GROUP BY c.run_id,c.code
 ), selected AS (SELECT * FROM scored ORDER BY score DESC,code LIMIT cap)
 SELECT coalesce(jsonb_agg(jsonb_build_object('code',code,'name',name,'definition',definition,
 'occupation_code',occupation_code,'occupation_name',occupation_name,'retrieval_score',score) ORDER BY score DESC,code),'[]') FROM selected
$$;

CREATE OR REPLACE FUNCTION enrichment.plan_stage(id text, step text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b enrichment.batch%ROWTYPE; i enrichment.item%ROWTYPE; p enrichment.prompt%ROWTYPE;
 ext jsonb; cand jsonb; request jsonb; user_data jsonb; key text; aid text; reused text; status text; model text;
BEGIN
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=id FOR UPDATE;
 IF step NOT IN ('extract','categorize') OR b.state NOT IN ('PLANNED','RUNNING') THEN RAISE EXCEPTION 'INVALID_STAGE_STATE'; END IF;
 SELECT * INTO STRICT p FROM enrichment.prompt WHERE version=b.settings->>'prompt_version' AND stage=step;
 model:=b.settings->>(CASE WHEN step='extract' THEN 'extract_model' ELSE 'categorize_model' END);
 FOR i IN SELECT * FROM enrichment.item WHERE batch_id=id ORDER BY ordinal LOOP
  IF (step='extract' AND i.extraction_id IS NOT NULL) OR (step='categorize' AND i.categorization_id IS NOT NULL) THEN CONTINUE; END IF;
  cand:='[]'; status:='PLANNED'; ext:=NULL;
  IF step='extract' THEN user_data:=jsonb_build_object('source',i.source_data);
  ELSE
   SELECT parsed_output INTO ext FROM enrichment.attempt WHERE attempt_id=i.extraction_id AND state='VALIDATED';
   IF ext IS NULL THEN CONTINUE; END IF;
   IF jsonb_array_length(ext->'duties')=0 THEN status:='SKIPPED';
   ELSE cand:=enrichment.candidates(b.ncs_run_id,i.source_data,ext,(b.settings->>'candidate_limit')::integer);
        IF jsonb_array_length(cand)=0 THEN status:='SKIPPED'; END IF;
   END IF;
   user_data:=jsonb_build_object('duties',ext->'duties','candidates',cand,'max_matches',(b.settings->>'max_matches')::integer);
  END IF;
  request:=jsonb_build_object('model',model,'messages',jsonb_build_array(
   jsonb_build_object('role','system','content',p.system_prompt),jsonb_build_object('role','user','content',user_data::text)),
   'response_format',jsonb_build_object('type','json_schema','json_schema',jsonb_build_object('name','jobtology_'||step,'strict',true,'schema',p.output_schema)),
   'provider',jsonb_build_object('require_parameters',true,'allow_fallbacks',false),
   'max_tokens',(b.settings->>'max_output_tokens')::integer,'stream',false) || (b.settings->'extra_params');
  IF b.settings->>'temperature' IS NOT NULL THEN request:=request||jsonb_build_object('temperature',(b.settings->>'temperature')::numeric); END IF;
  IF b.settings->>'reasoning_effort' IS NOT NULL THEN request:=request||jsonb_build_object('reasoning',jsonb_build_object('effort',b.settings->>'reasoning_effort','exclude',true)); END IF;
  key:=enrichment.hash(jsonb_build_object('request',request,'prompt_version',b.settings->>'prompt_version','endpoint',b.settings->>'endpoint','source_hash',i.source_hash,
   'ncs_hash',CASE WHEN step='categorize' THEN b.ncs_hash END,'validator','ko-v1','retriever','lexical-ko-v1')::text);
  reused:=NULL;
  IF b.settings->>'reuse_cache'='Y' AND status='PLANNED' THEN
   SELECT a.attempt_id INTO reused FROM enrichment.attempt a JOIN enrichment.batch ob USING(batch_id)
   WHERE a.cache_key=key AND a.state='VALIDATED' AND ob.mode=b.mode
   AND NOT EXISTS(SELECT 1 FROM enrichment.review r WHERE r.item_id=a.item_id AND r.decision='REJECT')
   ORDER BY a.completed_at DESC,a.attempt_id LIMIT 1;
  END IF;
  IF reused IS NOT NULL THEN aid:=reused;
  ELSE
   aid:=gen_random_uuid()::text;
   request:=request||jsonb_build_object('session_id',id,'trace',jsonb_build_object('trace_id',replace(i.item_id,'-',''),
    'trace_name','Korean job enrichment','span_name',step,'generation_name',step||':'||model,
    'environment',CASE WHEN b.mode='EVAL' THEN 'evaluation' ELSE 'staging' END,
    'release',b.settings->>'prompt_version','posting_id',i.posting_id,'batch_id',id,'attempt_id',aid,
    'job_run_id',b.job_run_id,'ncs_run_id',b.ncs_run_id,'source_hash',i.source_hash,'dataset_id',b.dataset_id));
   INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,candidates,state,parsed_output,issues,completed_at)
   VALUES(aid,id,i.item_id,step,key,request,cand,
    CASE WHEN length(request::text)>(b.settings->>'max_input_chars')::integer THEN 'REJECTED' ELSE status END,
    CASE WHEN status='SKIPPED' THEN '{"matches":[],"outcome":"no_supported_match"}'::jsonb END,
    CASE WHEN length(request::text)>(b.settings->>'max_input_chars')::integer THEN '["INPUT_TOO_LARGE"]'::jsonb
         WHEN status='SKIPPED' THEN jsonb_build_array(CASE WHEN jsonb_array_length(ext->'duties')=0 THEN 'NO_EXPLICIT_DUTIES' ELSE 'NO_RETRIEVAL_CANDIDATES' END) ELSE '[]'::jsonb END,
    CASE WHEN status='SKIPPED' OR length(request::text)>(b.settings->>'max_input_chars')::integer THEN clock_timestamp() END);
  END IF;
  UPDATE enrichment.item SET extraction_id=CASE WHEN step='extract' THEN aid ELSE extraction_id END,
   categorization_id=CASE WHEN step='categorize' THEN aid ELSE categorization_id END WHERE item_id=i.item_id;
 END LOOP;
END $$;

-- A reservation survives an unknown transport outcome. No automatic POST retries.
CREATE OR REPLACE FUNCTION enrichment.reserve_request(aid text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE a enrichment.attempt%ROWTYPE; b enrichment.batch%ROWTYPE; spent numeric; daily numeric; calls integer;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-llm-spend',0));
 SELECT * INTO STRICT a FROM enrichment.attempt WHERE attempt_id=aid FOR UPDATE;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=a.batch_id;
 IF a.state<>'PLANNED' OR b.state<>'RUNNING' OR b.settings->>'execute_requests'<>'Y' THEN RAISE EXCEPTION 'REQUEST_NOT_PLANNED'; END IF;
 SELECT count(*),coalesce(sum(greatest(reserved_usd,coalesce(cost_usd,0))),0) INTO calls,spent
 FROM enrichment.attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL;
 SELECT coalesce(sum(greatest(reserved_usd,coalesce(cost_usd,0))),0) INTO daily
 FROM enrichment.attempt WHERE reserved_at>clock_timestamp()-INTERVAL '24 hours';
 IF calls >= (b.settings->>'max_requests')::integer OR
 spent+(b.settings->>'request_reserve_usd')::numeric>(b.settings->>'max_cost_usd')::numeric OR
 daily+(b.settings->>'request_reserve_usd')::numeric>(b.settings->>'daily_budget_usd')::numeric THEN
  UPDATE enrichment.attempt SET state='BUDGET_BLOCKED',issues='["REQUEST_OR_SPEND_LIMIT"]',completed_at=clock_timestamp() WHERE attempt_id=aid;
 ELSE
  UPDATE enrichment.attempt SET state='RESERVED',reserved_usd=(b.settings->>'request_reserve_usd')::numeric,reserved_at=clock_timestamp() WHERE attempt_id=aid;
 END IF;
END $$;
COMMIT;
