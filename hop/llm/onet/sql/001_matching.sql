-- Separate metadata -> O*NET inference. No existing matcher/catalogue body changes.
BEGIN;
SELECT retention.gate();
CREATE SCHEMA IF NOT EXISTS onet_matching;

CREATE OR REPLACE FUNCTION onet_matching.hash(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to('jobtology-onet-matching-v1:'||value::text,'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION onet_matching.metadata(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) FROM jsonb_each(value)
 WHERE key IN('title','role','job_functions','job_position_raw','positions','duties_text',
  'description_text','ncs_category_names')
$$;
CREATE TABLE IF NOT EXISTS onet_matching.budget (
 budget_key text PRIMARY KEY CHECK(budget_key='ONET_POSTING_LINK_2026_10_14'),
 cap_usd numeric NOT NULL CHECK(cap_usd=40), created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO onet_matching.budget(budget_key,cap_usd) VALUES('ONET_POSTING_LINK_2026_10_14',40)
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS onet_matching.task (
 task_id text PRIMARY KEY CHECK(task_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$'),
 budget_key text NOT NULL DEFAULT 'ONET_POSTING_LINK_2026_10_14' REFERENCES onet_matching.budget,
 release_id text NOT NULL REFERENCES classification.catalog_release,
 database_id text NOT NULL, catalog_hash text NOT NULL,
 settings jsonb NOT NULL CHECK(jsonb_typeof(settings)='object'), settings_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.input (
 task_id text NOT NULL REFERENCES onet_matching.task,
 posting_identity text NOT NULL,
 source_id text NOT NULL CHECK(source_id IN('job_alio','nara_job','jobkorea')),
 source_run_id text NOT NULL, source_record_id text NOT NULL,
 source_facts jsonb NOT NULL, source_facts_sha256 text NOT NULL,
 source_fields jsonb NOT NULL, candidates jsonb NOT NULL CHECK(jsonb_typeof(candidates)='array'),
 request_body jsonb NOT NULL CHECK(jsonb_typeof(request_body)='object'),
 source_hash text NOT NULL, candidates_hash text NOT NULL, request_hash text NOT NULL,
 input_hash text NOT NULL, ordinal bigint NOT NULL,
 PRIMARY KEY(task_id,posting_identity), UNIQUE(task_id,ordinal)
);
CREATE TABLE IF NOT EXISTS onet_matching.freeze (
 task_id text PRIMARY KEY REFERENCES onet_matching.task, manifest_hash text NOT NULL,
 input_count bigint NOT NULL CHECK(input_count>0), frozen_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.freeze_chunk (
 task_id text NOT NULL REFERENCES onet_matching.task, start_ordinal bigint NOT NULL CHECK(start_ordinal>0),
 input_count integer NOT NULL CHECK(input_count BETWEEN 1 AND 500), chunk_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(task_id,start_ordinal)
);
CREATE TABLE IF NOT EXISTS onet_matching.source_pin (
 task_id text NOT NULL REFERENCES onet_matching.task, run_id text NOT NULL,
 source_id text NOT NULL, content_sha256 text NOT NULL, verified_at timestamptz NOT NULL,
 PRIMARY KEY(task_id,run_id)
);
CREATE TABLE IF NOT EXISTS onet_matching.batch (
 batch_id text PRIMARY KEY,
 task_id text NOT NULL REFERENCES onet_matching.task,
 phase text NOT NULL CHECK(phase IN('PILOT','FULL')),
 max_requests integer NOT NULL CHECK(max_requests BETWEEN 1 AND 1000),
 max_cost_usd numeric NOT NULL CHECK(max_cost_usd BETWEEN 0.001 AND 40),
 selection_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.attempt (
 attempt_id text PRIMARY KEY, batch_id text NOT NULL REFERENCES onet_matching.batch,
 task_id text NOT NULL, posting_identity text NOT NULL,
 ordinal bigint NOT NULL,
 state text NOT NULL CHECK(state IN('PLANNED','SKIPPED','RESERVED','VALIDATED','REJECTED','ERROR','BUDGET_BLOCKED')),
 reserve_usd numeric, reserved_at timestamptz, http_status integer,
 response_body text, response_id text, actual_model text, provider text, is_byok boolean,
 prompt_tokens bigint, completion_tokens bigint, router_cost_usd numeric, upstream_cost_usd numeric,
 cost_usd numeric, parsed_output jsonb, issues jsonb NOT NULL DEFAULT '[]', latency_ms bigint,
 completed_at timestamptz,
 FOREIGN KEY(task_id,posting_identity) REFERENCES onet_matching.input,
 UNIQUE(task_id,posting_identity), CHECK(cost_usd IS NULL OR cost_usd>=0),
 CHECK(reserve_usd IS NULL OR reserve_usd>0)
);
CREATE INDEX IF NOT EXISTS onet_attempt_batch_state ON onet_matching.attempt(batch_id,state,ordinal);
CREATE INDEX IF NOT EXISTS onet_attempt_spend ON onet_matching.attempt(task_id,reserved_at) WHERE reserved_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS onet_matching.execution (
 batch_id text NOT NULL REFERENCES onet_matching.batch,
 execution_token uuid PRIMARY KEY, workers integer NOT NULL CHECK(workers BETWEEN 1 AND 16),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.request_owner (
 attempt_id text PRIMARY KEY REFERENCES onet_matching.attempt,
 execution_token uuid NOT NULL REFERENCES onet_matching.execution(execution_token),
 claimed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.execution_stop (
 execution_token uuid PRIMARY KEY REFERENCES onet_matching.execution(execution_token),
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 200), stopped_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.execution_end (
 execution_token uuid PRIMARY KEY REFERENCES onet_matching.execution(execution_token),
 state text NOT NULL CHECK(state IN('COMPLETE','STOPPED')), ended_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.scale_gate (
 task_id text PRIMARY KEY REFERENCES onet_matching.task,
 actor text NOT NULL CHECK(length(btrim(actor))>0), notes text NOT NULL CHECK(length(btrim(notes))>0),
 accounting jsonb NOT NULL, approved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION onet_matching.immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'ONET_MATCHING_IMMUTABLE_HISTORY'; END $$;
DO $install$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['budget','task','input','freeze','freeze_chunk','source_pin','batch','execution','request_owner','execution_stop','execution_end','scale_gate'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS immutable_history ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON onet_matching.%I FOR EACH ROW EXECUTE FUNCTION onet_matching.immutable()',tab);
  EXECUTE format('DROP TRIGGER IF EXISTS immutable_truncate ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON onet_matching.%I FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.immutable()',tab);
 END LOOP;
 FOREACH tab IN ARRAY ARRAY['budget','task','input','freeze','freeze_chunk','source_pin','batch','attempt','execution','request_owner','execution_stop','execution_end','scale_gate'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS retention_freeze ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.%I FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',tab);
 END LOOP;
END $install$;
CREATE OR REPLACE FUNCTION onet_matching.input_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM onet_matching.freeze WHERE task_id=NEW.task_id)
 THEN RAISE EXCEPTION 'ONET_MATCHING_INPUT_INSERT_AFTER_FREEZE'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER frozen_input_insert BEFORE INSERT ON onet_matching.input
 FOR EACH ROW EXECUTE FUNCTION onet_matching.input_insert_guard();
CREATE OR REPLACE FUNCTION onet_matching.attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP IN('DELETE','TRUNCATE') THEN RAISE EXCEPTION 'ONET_MATCHING_IMMUTABLE_ATTEMPT_HISTORY'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state NOT IN('PLANNED','SKIPPED') OR NEW.reserved_at IS NOT NULL OR NEW.reserve_usd IS NOT NULL
   OR NEW.cost_usd IS NOT NULL THEN RAISE EXCEPTION 'ONET_MATCHING_ATTEMPT_REQUIRES_PLANNING'; END IF;
 ELSE
  IF (NEW.attempt_id,NEW.batch_id,NEW.task_id,NEW.posting_identity,NEW.ordinal)
   IS DISTINCT FROM (OLD.attempt_id,OLD.batch_id,OLD.task_id,OLD.posting_identity,OLD.ordinal)
   OR (OLD.state='PLANNED' AND NEW.state NOT IN('RESERVED','BUDGET_BLOCKED'))
   OR (OLD.state='RESERVED' AND (NEW.state NOT IN('VALIDATED','REJECTED','ERROR')
    OR (NEW.reserve_usd,NEW.reserved_at) IS DISTINCT FROM (OLD.reserve_usd,OLD.reserved_at)))
   OR OLD.state NOT IN('PLANNED','RESERVED')
  THEN RAISE EXCEPTION 'ONET_MATCHING_IMMUTABLE_ATTEMPT_HISTORY'; END IF;
 END IF;
 IF NEW.state='RESERVED' AND (NEW.reserve_usd IS NULL OR NEW.reserved_at IS NULL)
 THEN RAISE EXCEPTION 'ONET_MATCHING_RESERVATION_REQUIRED'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER immutable_attempt_lifecycle BEFORE INSERT OR UPDATE OR DELETE ON onet_matching.attempt
 FOR EACH ROW EXECUTE FUNCTION onet_matching.attempt_guard();
CREATE OR REPLACE TRIGGER immutable_attempt_truncate BEFORE TRUNCATE ON onet_matching.attempt
 FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.attempt_guard();

-- Active catalogue pointers alone are insufficient during a partial graph rollover.
CREATE OR REPLACE FUNCTION onet_matching.assert_catalog(release text,database text) RETURNS void
LANGUAGE plpgsql STABLE SET jit=off AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM classification.catalog_current c
  JOIN classification.catalog_release r ON r.release_id=c.release_id AND r.state='READY'
  JOIN classification.graph_target t ON t.database_id=c.database_id AND t.release_id=c.release_id AND t.load_id=c.load_id
  JOIN classification.graph_load l ON l.load_id=c.load_id AND l.database_id=c.database_id
    AND l.release_id=c.release_id AND l.manifest_hash=r.manifest_hash AND l.state='VERIFIED'
  WHERE c.scheme_id='ONET' AND c.release_id=release AND c.database_id=database)
  OR EXISTS(SELECT 1 FROM classification.graph_load WHERE database_id=database AND state='RUNNING')
  OR EXISTS(SELECT 1 FROM classification.graph_load failed JOIN classification.catalog_current c
    ON c.database_id=failed.database_id JOIN classification.graph_load verified ON verified.load_id=c.load_id
    WHERE failed.database_id=database AND failed.state='FAILED' AND failed.started_at>verified.started_at)
  OR EXISTS(SELECT 1 FROM retention.writer WHERE kind='ONET_CATALOG_GRAPH')
 THEN RAISE EXCEPTION 'ONET_MATCHING_CATALOG_NOT_READY_VERIFIED_OR_ROLLOVER'; END IF;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.create_task(id text,release text,database text,opts jsonb) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE existing onet_matching.task; catalog text; BEGIN
 PERFORM retention.gate();
 PERFORM onet_matching.assert_catalog(release,database);
 IF jsonb_typeof(opts) IS DISTINCT FROM 'object' OR NOT opts ?& ARRAY[
  'max_cost_usd','request_reserve_usd','max_output_tokens','max_matches','endpoint','model',
  'prompt_hash','retrieval_hash','read_timeout_ms','request_delay_ms','execute_requests']
  OR EXISTS(SELECT 1 FROM jsonb_each(opts) WHERE key IN('max_cost_usd','request_reserve_usd','max_output_tokens',
   'max_matches','endpoint','model','prompt_hash','retrieval_hash','read_timeout_ms','request_delay_ms','execute_requests')
   AND value='null'::jsonb)
  OR (opts->>'max_cost_usd')::numeric NOT BETWEEN 0.001 AND 40
  OR (opts->>'request_reserve_usd')::numeric NOT BETWEEN 0.001 AND 1
  OR (opts->>'max_output_tokens')::integer NOT BETWEEN 256 AND 2048
  OR (opts->>'max_matches')::integer NOT BETWEEN 1 AND 3
  OR (opts->>'read_timeout_ms')::integer NOT BETWEEN 1000 AND 600000
  OR (opts->>'request_delay_ms')::integer NOT BETWEEN 0 AND 60000
  OR opts->>'execute_requests' NOT IN('Y','N')
  OR opts->>'prompt_hash' !~ '^[0-9a-f]{64}$' OR opts->>'retrieval_hash' !~ '^[0-9a-f]{64}$'
  OR (opts->>'endpoint' IS DISTINCT FROM 'https://openrouter.ai/api/v1/chat/completions'
   AND NOT (coalesce(current_setting('jobtology.isolated_fixture',true),'') ~ '^[0-9a-f]{12}$'
    AND opts->>'endpoint' ~ ('^http://jobtology-onet-test-'||current_setting('jobtology.isolated_fixture',true)||'-mock:[0-9]{1,5}/chat/completions$')))
  OR opts->>'model' IS DISTINCT FROM 'openai/gpt-5.6-luna'
  OR NOT EXISTS(SELECT 1 FROM onet_matching.prompt_contract p WHERE p.prompt_hash=opts->>'prompt_hash')
 THEN RAISE EXCEPTION 'ONET_MATCHING_INVALID_OPTIONS'; END IF;
 SELECT manifest_hash INTO STRICT catalog FROM classification.catalog_release WHERE release_id=release;
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO existing FROM onet_matching.task WHERE task_id=id;
 IF FOUND THEN
  IF (existing.release_id,existing.database_id,existing.settings,existing.catalog_hash)
   IS DISTINCT FROM (release,database,opts,catalog) THEN RAISE EXCEPTION 'ONET_MATCHING_TASK_CHANGED'; END IF;
 ELSE
  INSERT INTO onet_matching.task(task_id,release_id,database_id,catalog_hash,settings,settings_hash)
  VALUES(id,release,database,catalog,opts,onet_matching.hash(opts));
 END IF;
 RETURN jsonb_build_object('task_id',id,'release_id',release,'catalog_hash',catalog,'settings_hash',onet_matching.hash(opts),'cap_usd',40);
END $$;

CREATE OR REPLACE FUNCTION onet_matching.freeze_inputs(id text,manifest jsonb,start_position bigint DEFAULT 1) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE t onet_matching.task; row jsonb; facts jsonb; fields jsonb; candidates jsonb; request jsonb;
 identity text; digest text; binding text; n bigint; previous onet_matching.freeze_chunk; run text;
 contract record; userdata jsonb; expected_schema jsonb; expected_candidates jsonb;
BEGIN
 PERFORM retention.gate(); SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=id;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 SELECT * INTO STRICT contract FROM onet_matching.prompt_contract WHERE prompt_hash=t.settings->>'prompt_hash';
 IF jsonb_typeof(manifest) IS DISTINCT FROM 'array' OR jsonb_array_length(manifest) NOT BETWEEN 1 AND 500
  OR octet_length(manifest::text)>16777216 OR start_position IS NULL OR start_position<1
 THEN RAISE EXCEPTION 'ONET_MATCHING_INVALID_MANIFEST'; END IF;
 digest:=onet_matching.hash(manifest);
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-freeze:'||id,0));
 SELECT * INTO previous FROM onet_matching.freeze_chunk WHERE task_id=id AND start_ordinal=start_position;
 IF FOUND THEN
  IF previous.chunk_hash<>digest THEN RAISE EXCEPTION 'ONET_MATCHING_FROZEN_MANIFEST_CHANGED'; END IF;
  RETURN jsonb_build_object('task_id',id,'start_ordinal',start_position,'input_count',previous.input_count,'chunk_hash',digest,'replay',true);
 END IF;
 IF EXISTS(SELECT 1 FROM onet_matching.freeze WHERE task_id=id) THEN RAISE EXCEPTION 'ONET_MATCHING_INPUT_INSERT_AFTER_FREEZE'; END IF;
 IF (SELECT count(*) FROM onet_matching.input WHERE task_id=id)<>start_position-1
 THEN RAISE EXCEPTION 'ONET_MATCHING_NONCONTIGUOUS_FREEZE'; END IF;
 n:=start_position-1;
 -- Retained READY source proofs are immutable and were independently verified
 -- by the source loader. Bind their exact proof without repeating full historical
 -- validators. The coordinator binds an exact live graph cohort before freezing.
 FOR run IN SELECT DISTINCT value->>'source_run_id' FROM jsonb_array_elements(manifest) LOOP
  INSERT INTO onet_matching.source_pin(task_id,run_id,source_id,content_sha256,verified_at)
  SELECT id,p.run_id,p.source_id,p.content_sha256,p.verified_at FROM ingestion.source_graph_projection p
  WHERE p.run_id=run AND p.state='READY' AND p.verified_at IS NOT NULL
   AND p.loader_version='hop-graph-batchfree-v1' ON CONFLICT DO NOTHING;
  IF NOT EXISTS(SELECT 1 FROM onet_matching.source_pin pin JOIN ingestion.source_graph_projection p USING(run_id)
   WHERE pin.task_id=id AND pin.run_id=run AND p.state='READY'
   AND pin.content_sha256=p.content_sha256 AND pin.verified_at=p.verified_at)
  THEN RAISE EXCEPTION 'ONET_MATCHING_SOURCE_PROOF_NOT_READY'; END IF;
 END LOOP;
 FOR row IN SELECT value FROM jsonb_array_elements(manifest) LOOP
  n:=n+1; identity:=coalesce(row->>'posting_identity',row->>'posting_id');
  facts:=coalesce(row->'source_facts',row->'source_facts_json');
  IF jsonb_typeof(facts)='string' THEN facts:=(facts#>>'{}')::jsonb; END IF;
  fields:=onet_matching.metadata(facts); candidates:=row->'candidates'; request:=row->'request_body';
  IF identity IS NULL OR jsonb_typeof(facts) IS DISTINCT FROM 'object'
   OR row->>'source_facts_sha256' IS DISTINCT FROM encode(sha256(convert_to(facts::text,'UTF8')),'hex')
   OR row->'source_fields' IS DISTINCT FROM fields
   OR NOT EXISTS(SELECT 1 FROM ingestion.source_graph_membership m JOIN ingestion.source_graph_record_evidence e USING(run_id,record_id)
    WHERE m.run_id=row->>'source_run_id' AND m.identity_id=identity AND m.kind='JobPosting'
    AND e.source_record_id=row->>'source_record_id')
   OR NOT EXISTS(SELECT 1 FROM ingestion.source_graph_projection p WHERE p.run_id=row->>'source_run_id'
    AND p.source_id=row->>'source_id' AND p.state='READY')
  THEN RAISE EXCEPTION 'ONET_MATCHING_SOURCE_PROVENANCE_CHANGED: %',identity; END IF;
  IF jsonb_typeof(candidates) IS DISTINCT FROM 'array' OR jsonb_array_length(candidates)>40
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(candidates) c
    LEFT JOIN classification.term term ON term.release_id=t.release_id AND term.term_kind='OCCUPATION'
      AND term.code=c->>'occupation_code'
    WHERE term.term_id IS NULL OR c->>'term_id' IS DISTINCT FROM term.term_id
     OR coalesce(c->>'label',c->>'preferred_label') IS DISTINCT FROM term.preferred_label
     OR c->>'description' IS DISTINCT FROM term.description)
   OR (SELECT count(DISTINCT c->>'occupation_code') FROM jsonb_array_elements(candidates) c)<>jsonb_array_length(candidates)
  THEN RAISE EXCEPTION 'ONET_MATCHING_CANDIDATES_NOT_PINNED'; END IF;
  IF jsonb_typeof(request) IS DISTINCT FROM 'object' OR request->>'model' IS DISTINCT FROM t.settings->>'model'
   OR request->'stream' IS DISTINCT FROM 'false'::jsonb
   OR request#>'{provider,only}' IS DISTINCT FROM '["openai"]'::jsonb
   OR request#>'{provider,allow_fallbacks}' IS DISTINCT FROM 'false'::jsonb
   OR request#>'{provider,require_parameters}' IS DISTINCT FROM 'true'::jsonb
   OR (request#>>'{provider,max_price,prompt}')::numeric IS DISTINCT FROM 0.20
   OR (request#>>'{provider,max_price,completion}')::numeric IS DISTINCT FROM 1.20
   OR (request->>'max_tokens')::integer IS DISTINCT FROM (t.settings->>'max_output_tokens')::integer
   OR jsonb_typeof(request->'messages') IS DISTINCT FROM 'array' OR jsonb_array_length(request->'messages')<>2
   OR request#>>'{response_format,type}' IS DISTINCT FROM 'json_schema'
   OR request#>'{response_format,json_schema,strict}' IS DISTINCT FROM 'true'::jsonb
   OR length(request::text)>100000 OR octet_length(request::text)+256>=272000
   OR 1.05*(0.25*(octet_length(request::text)+256)+1.20*(t.settings->>'max_output_tokens')::integer)/1000000
       >(t.settings->>'request_reserve_usd')::numeric
  THEN RAISE EXCEPTION 'ONET_MATCHING_REQUEST_OR_RESERVATION_INVALID'; END IF;
  IF request#>>'{messages,0,role}' IS DISTINCT FROM 'system' OR request#>>'{messages,1,role}' IS DISTINCT FROM 'user'
   OR request#>>'{messages,0,content}' IS DISTINCT FROM contract.prompt_text
   OR NOT coalesce((request#>>'{messages,1,content}') IS JSON OBJECT WITH UNIQUE KEYS,false)
   OR EXISTS(SELECT 1 FROM jsonb_object_keys(request) k WHERE k NOT IN('model','messages','temperature',
      'max_tokens','response_format','provider','reasoning','stream'))
   OR request#>>'{reasoning,effort}' IS DISTINCT FROM 'none'
  THEN RAISE EXCEPTION 'ONET_MATCHING_PROMPT_BINDING_INVALID'; END IF;
  userdata:=(request#>>'{messages,1,content}')::jsonb;
  SELECT coalesce(jsonb_agg(jsonb_build_object('occupation_code',c->>'occupation_code','term_id',c->>'term_id',
    'label',c->>'label','description',c->'description') ORDER BY ordinal),'[]'::jsonb) INTO expected_candidates
  FROM jsonb_array_elements(candidates) WITH ORDINALITY x(c,ordinal);
  IF userdata IS DISTINCT FROM jsonb_build_object('contract',contract.version,'max_matches',(t.settings->>'max_matches')::integer,
   'source_fields',fields,'candidates',expected_candidates,'allowed_evidence_fields',
    jsonb_build_array('title','role','job_functions','job_position_raw','positions','duties_text','description_text'))
  THEN RAISE EXCEPTION 'ONET_MATCHING_REQUEST_SOURCE_CANDIDATES_MISMATCH'; END IF;
  expected_schema:=jsonb_set(contract.schema,'{properties,matches,maxItems}',
    to_jsonb(CASE WHEN candidates='[]'::jsonb THEN 0 ELSE (t.settings->>'max_matches')::integer END));
  IF candidates<>'[]'::jsonb THEN expected_schema:=jsonb_set(expected_schema,
   '{properties,matches,items,properties,occupation_code,enum}',
   (SELECT jsonb_agg(c->'occupation_code' ORDER BY ordinal) FROM jsonb_array_elements(candidates) WITH ORDINALITY x(c,ordinal))); END IF;
  IF request#>'{response_format,json_schema,schema}' IS DISTINCT FROM expected_schema
   OR request#>>'{response_format,json_schema,name}' IS DISTINCT FROM 'ko_onet_metadata_occupation_v1'
  THEN RAISE EXCEPTION 'ONET_MATCHING_REQUEST_SCHEMA_MISMATCH'; END IF;
  binding:=onet_matching.hash(jsonb_build_array(identity,row->>'source_id',row->>'source_run_id',row->>'source_record_id',
   row->>'source_facts_sha256',fields,candidates,request,t.catalog_hash,t.settings_hash));
  INSERT INTO onet_matching.input VALUES(id,identity,row->>'source_id',row->>'source_run_id',row->>'source_record_id',facts,
   row->>'source_facts_sha256',fields,candidates,request,onet_matching.hash(fields),onet_matching.hash(candidates),
   onet_matching.hash(request),binding,n);
 END LOOP;
 INSERT INTO onet_matching.freeze_chunk(task_id,start_ordinal,input_count,chunk_hash) VALUES(id,start_position,jsonb_array_length(manifest),digest);
 RETURN jsonb_build_object('task_id',id,'start_ordinal',start_position,'input_count',jsonb_array_length(manifest),'chunk_hash',digest);
END $$;
CREATE OR REPLACE FUNCTION onet_matching.finalize_freeze(id text,expected_count bigint,expected_hash text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE t onet_matching.task; count_rows bigint; digest text; frozen onet_matching.freeze;
BEGIN
 PERFORM retention.gate(); SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=id;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-freeze:'||id,0));
 SELECT count(*),encode(sha256(convert_to(string_agg(input_hash,E'\n' ORDER BY ordinal),'UTF8')),'hex')
 INTO count_rows,digest FROM onet_matching.input WHERE task_id=id;
 IF count_rows IS DISTINCT FROM expected_count OR count_rows=0 OR
  (SELECT max(ordinal) FROM onet_matching.input WHERE task_id=id)<>count_rows
  OR expected_hash IS NOT NULL AND expected_hash IS DISTINCT FROM digest
  OR t.settings ? 'frozen_input_count' AND (t.settings->>'frozen_input_count')::bigint<>count_rows
 THEN RAISE EXCEPTION 'ONET_MATCHING_INCOMPLETE_FREEZE'; END IF;
 SELECT * INTO frozen FROM onet_matching.freeze WHERE task_id=id;
 IF FOUND AND (frozen.input_count,frozen.manifest_hash) IS DISTINCT FROM (count_rows,digest)
 THEN RAISE EXCEPTION 'ONET_MATCHING_FROZEN_MANIFEST_CHANGED'; END IF;
 INSERT INTO onet_matching.freeze(task_id,manifest_hash,input_count) VALUES(id,digest,count_rows) ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('task_id',id,'input_count',count_rows,'manifest_hash',digest);
END $$;

CREATE OR REPLACE FUNCTION onet_matching.plan_batch(id text,batch_key text,selection jsonb,phase text DEFAULT 'PILOT',calls integer DEFAULT 36,batch_cap numeric DEFAULT 0.25)
RETURNS jsonb LANGUAGE plpgsql SET jit=off AS $$
DECLARE t onet_matching.task; chosen jsonb; i onet_matching.input; existing onet_matching.batch; ordinal bigint:=0;
BEGIN
 PERFORM retention.gate(); SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=id;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 IF NOT EXISTS(SELECT 1 FROM onet_matching.freeze WHERE task_id=id) THEN RAISE EXCEPTION 'ONET_MATCHING_INPUTS_NOT_FROZEN'; END IF;
 IF phase NOT IN('PILOT','FULL') OR calls NOT BETWEEN 1 AND 1000 OR calls IS NULL
  OR jsonb_typeof(selection) IS DISTINCT FROM 'array' OR jsonb_array_length(selection) NOT BETWEEN 1 AND 1000
  OR (phase='PILOT' AND (calls>60 OR jsonb_array_length(selection)>60 OR batch_cap>0.5))
  OR batch_cap IS NULL OR batch_cap NOT BETWEEN 0.001 AND 40
  OR (phase='FULL' AND NOT EXISTS(SELECT 1 FROM onet_matching.scale_gate WHERE task_id=id))
 THEN RAISE EXCEPTION 'ONET_MATCHING_BATCH_OR_SCALE_GATE_INVALID'; END IF;
 SELECT jsonb_agg(identity ORDER BY identity) INTO chosen FROM (
  SELECT DISTINCT CASE WHEN jsonb_typeof(value)='string' THEN value#>>'{}'
   ELSE coalesce(value->>'posting_identity',value->>'posting_id') END AS identity FROM jsonb_array_elements(selection)) s;
 IF jsonb_array_length(chosen)<>jsonb_array_length(selection) OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(chosen) k
  WHERE NOT EXISTS(SELECT 1 FROM onet_matching.input WHERE task_id=id AND posting_identity=k))
 THEN RAISE EXCEPTION 'ONET_MATCHING_SELECTION_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO existing FROM onet_matching.batch WHERE batch_id=batch_key;
 IF FOUND THEN
  IF (existing.task_id,existing.selection_hash,existing.phase,existing.max_requests,existing.max_cost_usd)
   IS DISTINCT FROM (id,onet_matching.hash(chosen),phase,calls,batch_cap) THEN RAISE EXCEPTION 'ONET_MATCHING_BATCH_CHANGED'; END IF;
 ELSE
  INSERT INTO onet_matching.batch(batch_id,task_id,phase,max_requests,max_cost_usd,selection_hash)
  VALUES(batch_key,id,phase,calls,batch_cap,onet_matching.hash(chosen));
  FOR i IN SELECT * FROM onet_matching.input WHERE task_id=id AND posting_identity IN(SELECT jsonb_array_elements_text(chosen)) ORDER BY posting_identity LOOP
   ordinal:=ordinal+1;
   IF EXISTS(SELECT 1 FROM onet_matching.attempt WHERE task_id=id AND posting_identity=i.posting_identity)
   THEN RAISE EXCEPTION 'ONET_MATCHING_INPUT_ALREADY_PLANNED'; END IF;
   INSERT INTO onet_matching.attempt(attempt_id,batch_id,task_id,posting_identity,ordinal,state,parsed_output,issues,completed_at)
   VALUES(gen_random_uuid()::text,batch_key,id,i.posting_identity,ordinal,
    CASE WHEN i.candidates='[]'::jsonb THEN 'SKIPPED' ELSE 'PLANNED' END,
    CASE WHEN i.candidates='[]'::jsonb THEN jsonb_build_object('outcome','abstained','matches','[]'::jsonb,
      'abstain_reason','No suitable O*NET candidate was retrieved from frozen listing metadata.') END,
    CASE WHEN i.candidates='[]'::jsonb THEN '["NO_CANDIDATES"]'::jsonb ELSE '[]'::jsonb END,
    CASE WHEN i.candidates='[]'::jsonb THEN clock_timestamp() END);
  END LOOP;
 END IF;
 RETURN onet_matching.batch_status(batch_key);
END $$;

CREATE OR REPLACE FUNCTION onet_matching.task_status(id text) RETURNS jsonb LANGUAGE sql STABLE SET jit=off AS $$
 SELECT jsonb_build_object('task_id',t.task_id,'budget_key',t.budget_key,'cap_usd',b.cap_usd,
  'task_cap_usd',(t.settings->>'max_cost_usd')::numeric,'release_id',t.release_id,'database_id',t.database_id,
  'catalog_hash',t.catalog_hash,'settings_hash',t.settings_hash,'frozen_input_count',f.input_count,'manifest_hash',f.manifest_hash,
  'accounting_usd',coalesce((SELECT sum(coalesce(a.cost_usd,a.reserve_usd)) FROM onet_matching.attempt a
    JOIN onet_matching.task x USING(task_id) WHERE x.budget_key=t.budget_key AND a.reserved_at IS NOT NULL),0),
  'known_cost_usd',coalesce((SELECT sum(a.cost_usd) FROM onet_matching.attempt a JOIN onet_matching.task x USING(task_id)
    WHERE x.budget_key=t.budget_key AND a.reserved_at IS NOT NULL),0),
  'unknown_holds', (SELECT count(*) FROM onet_matching.attempt a JOIN onet_matching.task x USING(task_id)
    WHERE x.budget_key=t.budget_key AND a.reserved_at IS NOT NULL AND a.cost_usd IS NULL),
  'paid_attempts',(SELECT count(*) FROM onet_matching.attempt a WHERE a.task_id=t.task_id AND a.reserved_at IS NOT NULL),
  'states',(SELECT coalesce(jsonb_object_agg(state,n),'{}'::jsonb) FROM(SELECT state,count(*) n FROM onet_matching.attempt WHERE task_id=id GROUP BY state) s),
  'scale_approved',EXISTS(SELECT 1 FROM onet_matching.scale_gate WHERE task_id=id),
  'remaining_inputs',(SELECT count(*) FROM onet_matching.input i WHERE i.task_id=id AND NOT EXISTS(
    SELECT 1 FROM onet_matching.attempt a WHERE a.task_id=id AND a.posting_identity=i.posting_identity)))
 FROM onet_matching.task t JOIN onet_matching.budget b USING(budget_key) LEFT JOIN onet_matching.freeze f USING(task_id) WHERE t.task_id=id
$$;
CREATE OR REPLACE FUNCTION onet_matching.batch_status(id text) RETURNS jsonb LANGUAGE sql STABLE SET jit=off AS $$
 SELECT jsonb_build_object('batch_id',b.batch_id,'task_id',b.task_id,'phase',b.phase,'max_requests',b.max_requests,'max_cost_usd',b.max_cost_usd,
  'execution_token',e.execution_token,'workers',e.workers,'stop_reason',s.reason,'execution_state',finish.state,
  'accounting_usd',coalesce((SELECT sum(coalesce(cost_usd,reserve_usd)) FROM onet_matching.attempt WHERE batch_id=id AND reserved_at IS NOT NULL),0),
  'known_cost_usd',coalesce((SELECT sum(cost_usd) FROM onet_matching.attempt WHERE batch_id=id),0),
  'unknown_holds',(SELECT count(*) FROM onet_matching.attempt WHERE batch_id=id AND reserved_at IS NOT NULL AND cost_usd IS NULL),
  'states',(SELECT coalesce(jsonb_object_agg(state,n),'{}'::jsonb) FROM(SELECT state,count(*) n FROM onet_matching.attempt WHERE batch_id=id GROUP BY state) x))
 FROM onet_matching.batch b LEFT JOIN LATERAL (SELECT * FROM onet_matching.execution e WHERE e.batch_id=b.batch_id ORDER BY started_at DESC,execution_token DESC LIMIT 1) e ON true
 LEFT JOIN onet_matching.execution_stop s ON s.execution_token=e.execution_token
 LEFT JOIN onet_matching.execution_end finish ON finish.execution_token=e.execution_token WHERE b.batch_id=id
$$;
CREATE OR REPLACE FUNCTION onet_matching.approve_scale(id text,actor text,notes text) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE accounting jsonb; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 accounting:=onet_matching.task_status(id);
 IF accounting IS NULL OR nullif(btrim(actor),'') IS NULL OR nullif(btrim(notes),'') IS NULL
  OR (accounting->>'unknown_holds')::bigint<>0 OR (accounting->>'paid_attempts')::bigint=0
  OR NOT EXISTS(SELECT 1 FROM onet_matching.attempt a JOIN onet_matching.batch b USING(batch_id)
    WHERE a.task_id=id AND b.phase='PILOT' AND a.state='VALIDATED' AND a.is_byok=true AND a.cost_usd IS NOT NULL)
  OR EXISTS(SELECT 1 FROM onet_matching.attempt a WHERE a.task_id=id AND a.reserved_at IS NOT NULL
    AND (a.state='RESERVED' OR a.is_byok IS DISTINCT FROM true OR a.actual_model IS DISTINCT FROM 'openai/gpt-5.6-luna'))
 THEN RAISE EXCEPTION 'ONET_MATCHING_SCALE_REQUIRES_MEASURED_REVIEWED_BYOK_PILOT'; END IF;
 INSERT INTO onet_matching.scale_gate(task_id,actor,notes,accounting) VALUES(id,actor,notes,accounting) ON CONFLICT DO NOTHING;
 RETURN onet_matching.task_status(id);
END $$;

CREATE OR REPLACE FUNCTION onet_matching.start_execution(id text,worker_count integer,resume boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE b onet_matching.batch; t onet_matching.task; token uuid; previous onet_matching.execution; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO STRICT b FROM onet_matching.batch WHERE batch_id=id;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=b.task_id;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 IF worker_count IS NULL OR worker_count NOT BETWEEN 1 AND 16 THEN RAISE EXCEPTION 'ONET_MATCHING_INVALID_WORKERS'; END IF;
 IF t.settings->>'execute_requests'='N' THEN RETURN jsonb_build_object('batch_id',id,'execute_requests','N'); END IF;
 SELECT * INTO previous FROM onet_matching.execution WHERE batch_id=id ORDER BY started_at DESC,execution_token DESC LIMIT 1;
 IF FOUND THEN
  IF NOT resume OR
   (NOT EXISTS(SELECT 1 FROM onet_matching.execution_stop WHERE execution_token=previous.execution_token)
    AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end WHERE execution_token=previous.execution_token))
   OR EXISTS(SELECT 1 FROM onet_matching.attempt x JOIN onet_matching.task xt USING(task_id)
      WHERE xt.budget_key=t.budget_key AND x.reserved_at IS NOT NULL AND (x.state='RESERVED' OR x.cost_usd IS NULL))
   OR NOT EXISTS(SELECT 1 FROM onet_matching.attempt WHERE batch_id=id AND state='PLANNED')
  THEN RAISE EXCEPTION 'ONET_MATCHING_EXECUTION_ALREADY_STARTED_NO_RETRY'; END IF;
  INSERT INTO onet_matching.execution_end(execution_token,state) VALUES(previous.execution_token,'STOPPED') ON CONFLICT DO NOTHING;
 END IF;
 token:=gen_random_uuid(); INSERT INTO onet_matching.execution(batch_id,execution_token,workers) VALUES(id,token,worker_count);
 RETURN jsonb_build_object('batch_id',id,'execution_token',token,'workers',worker_count);
END $$;
CREATE OR REPLACE FUNCTION onet_matching.request_context(aid text,token uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET jit=off AS $$
DECLARE t onet_matching.task; BEGIN
 SELECT task.* INTO t FROM onet_matching.attempt a JOIN onet_matching.task task USING(task_id)
 JOIN onet_matching.execution e ON e.batch_id=a.batch_id AND e.execution_token=token
 WHERE a.attempt_id=aid AND a.state='PLANNED' AND task.settings->>'execute_requests'='Y'
  AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_stop WHERE execution_token=token)
  AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end WHERE execution_token=token);
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 IF EXISTS(SELECT 1 FROM onet_matching.attempt x JOIN onet_matching.task xt USING(task_id)
  WHERE xt.budget_key=t.budget_key AND x.reserved_at IS NOT NULL AND
   (x.state<>'RESERVED' AND (x.cost_usd IS NULL OR x.is_byok IS DISTINCT FROM true)
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
 IF (SELECT count(*) FROM onet_matching.attempt x JOIN onet_matching.request_owner o USING(attempt_id)
  WHERE o.execution_token=token AND x.state='RESERVED')>=workers THEN RETURN false; END IF;
 -- Never reserve the entire cohort. Each worker reserves only its next POST.
 SELECT coalesce(sum(coalesce(x.cost_usd,x.reserve_usd)),0) INTO held FROM onet_matching.attempt x
  JOIN onet_matching.task xt USING(task_id) WHERE xt.budget_key=t.budget_key AND x.reserved_at IS NOT NULL;
 SELECT coalesce(sum(coalesce(cost_usd,reserve_usd)),0) INTO own_held FROM onet_matching.attempt WHERE task_id=t.task_id AND reserved_at IS NOT NULL;
 SELECT count(*) INTO paid FROM onet_matching.attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL;
 SELECT coalesce(sum(coalesce(cost_usd,reserve_usd)),0) INTO batch_held FROM onet_matching.attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL;
 reserve:=(t.settings->>'request_reserve_usd')::numeric;
 IF held+reserve>(SELECT cap_usd FROM onet_matching.budget WHERE budget_key=t.budget_key)
  OR own_held+reserve>(t.settings->>'max_cost_usd')::numeric OR batch_held+reserve>b.max_cost_usd OR paid>=b.max_requests
 THEN UPDATE onet_matching.attempt SET state='BUDGET_BLOCKED',issues='["COMBINED_ACCOUNTING_CAP_OR_REQUEST_COUNT"]' WHERE attempt_id=aid;
  INSERT INTO onet_matching.execution_stop(execution_token,reason) VALUES(token,'BUDGET_OR_REQUEST_COUNT') ON CONFLICT DO NOTHING;
  RETURN false;
 END IF;
 -- Same frozen paid request cannot be retried under a fresh task identity.
 IF EXISTS(SELECT 1 FROM onet_matching.attempt old JOIN onet_matching.input oi USING(task_id,posting_identity)
  JOIN onet_matching.task ot USING(task_id) JOIN onet_matching.input current ON current.task_id=a.task_id AND current.posting_identity=a.posting_identity
  WHERE old.reserved_at IS NOT NULL AND ot.budget_key=t.budget_key AND oi.posting_identity=current.posting_identity
   AND oi.source_hash=current.source_hash AND oi.request_hash=current.request_hash AND ot.catalog_hash=t.catalog_hash)
 THEN RAISE EXCEPTION 'ONET_MATCHING_ALREADY_PAID_NO_RETRY'; END IF;
 UPDATE onet_matching.attempt SET state='RESERVED',reserve_usd=reserve,reserved_at=clock_timestamp() WHERE attempt_id=aid;
 INSERT INTO onet_matching.request_owner(attempt_id,execution_token) VALUES(aid,token);
 RETURN true;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.stop_execution(token uuid,why text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 INSERT INTO onet_matching.execution_stop(execution_token,reason) VALUES(token,why) ON CONFLICT DO NOTHING;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.end_execution(token uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE id text; final text; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT batch_id INTO STRICT id FROM onet_matching.execution WHERE execution_token=token;
 IF EXISTS(SELECT 1 FROM onet_matching.attempt WHERE batch_id=id AND state='RESERVED')
 THEN RAISE EXCEPTION 'ONET_MATCHING_UNSETTLED_RESERVATIONS'; END IF;
 final:=CASE WHEN EXISTS(SELECT 1 FROM onet_matching.execution_stop WHERE execution_token=token)
  OR EXISTS(SELECT 1 FROM onet_matching.attempt WHERE batch_id=id AND state IN('PLANNED','ERROR','BUDGET_BLOCKED'))
  THEN 'STOPPED' ELSE 'COMPLETE' END;
 INSERT INTO onet_matching.execution_end(execution_token,state) VALUES(token,final) ON CONFLICT DO NOTHING;
 RETURN onet_matching.batch_status(id);
END $$;
COMMIT;
