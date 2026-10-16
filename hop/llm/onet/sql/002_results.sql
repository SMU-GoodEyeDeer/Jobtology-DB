-- Provider response and exact source-leaf validation, separate from strict duty linking.
BEGIN;
SELECT retention.gate();
CREATE OR REPLACE FUNCTION onet_matching.string_leaves(value jsonb) RETURNS TABLE(leaf text)
LANGUAGE sql IMMUTABLE STRICT AS $$
 WITH RECURSIVE walk(value) AS (
  SELECT value UNION ALL
  SELECT child.value FROM walk CROSS JOIN LATERAL (
   SELECT value FROM jsonb_each(CASE WHEN jsonb_typeof(walk.value)='object' THEN walk.value ELSE '{}'::jsonb END)
   UNION ALL SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(walk.value)='array' THEN walk.value ELSE '[]'::jsonb END)
  ) child
 ) SELECT value#>>'{}' FROM walk WHERE jsonb_typeof(value)='string'
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
  OR (output->>'outcome'='abstained' AND (jsonb_array_length(output->'matches')<>0 OR length(btrim(output->>'abstain_reason'))=0))
 THEN errors:=errors||'["OUTCOME_OR_MATCH_LIMIT"]'::jsonb; END IF;
 FOR match IN SELECT value FROM jsonb_array_elements(output->'matches') LOOP
  rank:=rank+1; code:=match->>'occupation_code';
  IF jsonb_typeof(match) IS DISTINCT FROM 'object' OR NOT match ?& ARRAY['occupation_code','match_rank','reason','evidence']
   OR (SELECT count(*) FROM jsonb_object_keys(match))<>4 OR code !~ '^[0-9]{2}-[0-9]{4}\.[0-9]{2}$'
   OR code=ANY(seen) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(candidates) c WHERE c->>'occupation_code'=code)
   OR match->'match_rank' IS DISTINCT FROM to_jsonb(rank) OR match->>'match_rank' !~ '^[1-3]$'
   OR jsonb_typeof(match->'reason') IS DISTINCT FROM 'string' OR nullif(btrim(match->>'reason'),'') IS NULL
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
    OR jsonb_typeof(citation->'quote') IS DISTINCT FROM 'string' OR nullif(btrim(quote),'') IS NULL
    OR length(quote) NOT BETWEEN 2 AND 500
    OR NOT EXISTS(SELECT 1 FROM onet_matching.string_leaves(source->field) s WHERE position(quote IN s.leaf)>0)
   THEN errors:=errors||'["INVALID_EXACT_SOURCE_CITATION"]'::jsonb; END IF;
  END LOOP;
 END LOOP;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION onet_matching.response_cost(envelope jsonb) RETURNS numeric LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE router numeric; upstream numeric; BEGIN
 IF jsonb_typeof(envelope#>'{usage,cost}') IS DISTINCT FROM 'number' THEN RETURN NULL; END IF;
 router:=(envelope#>>'{usage,cost}')::numeric;
 IF router<0 THEN RETURN NULL; END IF;
 IF envelope#>'{usage,is_byok}'='false'::jsonb THEN RETURN router; END IF;
 IF envelope#>'{usage,is_byok}' IS DISTINCT FROM 'true'::jsonb
  OR jsonb_typeof(envelope#>'{usage,cost_details,upstream_inference_cost}') IS DISTINCT FROM 'number'
 THEN RETURN NULL; END IF;
 upstream:=(envelope#>>'{usage,cost_details,upstream_inference_cost}')::numeric;
 IF upstream<0 THEN RETURN NULL; END IF;
 RETURN router+upstream;
END $$;

CREATE OR REPLACE FUNCTION onet_matching.save_response(aid text,status integer,body text,elapsed bigint) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; t onet_matching.task; i onet_matching.input;
 envelope jsonb; output jsonb; content text; errors jsonb:='[]'; charged numeric; router numeric; upstream numeric;
 prompt_count bigint; output_count bigint; token uuid;
BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid FOR UPDATE;
 IF a.state<>'RESERVED' THEN RAISE EXCEPTION 'ONET_MATCHING_RESPONSE_WITHOUT_RESERVATION'; END IF;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 SELECT * INTO STRICT i FROM onet_matching.input WHERE task_id=a.task_id AND posting_identity=a.posting_identity;
 IF status=0 THEN errors:='["TRANSPORT_ERROR_UNKNOWN_CHARGE"]';
 ELSIF octet_length(body)>8388608 THEN errors:='["RESPONSE_TOO_LARGE_UNKNOWN_CHARGE"]';
 ELSE
  BEGIN
   IF NOT coalesce(body IS JSON OBJECT WITH UNIQUE KEYS,false) THEN RAISE EXCEPTION 'JSON'; END IF;
   envelope:=body::jsonb;
  EXCEPTION WHEN OTHERS THEN errors:='["INVALID_RESPONSE_JSON_UNKNOWN_CHARGE"]'; END;
  IF envelope IS NOT NULL THEN
   charged:=onet_matching.response_cost(envelope);
   IF jsonb_typeof(envelope#>'{usage,cost}')='number' THEN router:=(envelope#>>'{usage,cost}')::numeric; END IF;
   IF jsonb_typeof(envelope#>'{usage,cost_details,upstream_inference_cost}')='number' THEN upstream:=(envelope#>>'{usage,cost_details,upstream_inference_cost}')::numeric; END IF;
   IF envelope#>>'{usage,prompt_tokens}' ~ '^[0-9]{1,12}$' THEN prompt_count:=(envelope#>>'{usage,prompt_tokens}')::bigint; END IF;
   IF envelope#>>'{usage,completion_tokens}' ~ '^[0-9]{1,12}$' THEN output_count:=(envelope#>>'{usage,completion_tokens}')::bigint; END IF;
   IF envelope#>'{usage,is_byok}' IS DISTINCT FROM 'true'::jsonb THEN errors:=errors||'["EXPECTED_OPENAI_BYOK_ROUTE"]'::jsonb; END IF;
   IF charged IS NULL THEN errors:=errors||'["UNKNOWN_COMBINED_CHARGE"]'::jsonb; END IF;
   IF charged>a.reserve_usd THEN errors:=errors||'["CHARGE_EXCEEDED_CONSERVATIVE_RESERVATION"]'::jsonb; END IF;
   IF envelope->>'model' IS DISTINCT FROM t.settings->>'model'
    OR lower(coalesce(envelope->>'provider','')) IS DISTINCT FROM 'openai'
   THEN errors:=errors||'["UNEXPECTED_MODEL_OR_PROVIDER"]'::jsonb; END IF;
   IF status<>200 OR envelope ? 'error' THEN errors:=errors||'["PROVIDER_ERROR"]'::jsonb;
   ELSIF jsonb_typeof(envelope->'choices') IS DISTINCT FROM 'array' THEN errors:=errors||'["MISSING_CHOICES"]'::jsonb;
   ELSIF jsonb_array_length(envelope->'choices')<>1 OR envelope#>>'{choices,0,finish_reason}' IS DISTINCT FROM 'stop'
     OR coalesce(envelope#>>'{choices,0,message,refusal}','')<>'' THEN errors:=errors||'["INCOMPLETE_OR_REFUSED"]'::jsonb;
   ELSE
    content:=envelope#>>'{choices,0,message,content}';
    BEGIN
     IF NOT coalesce(content IS JSON OBJECT WITH UNIQUE KEYS,false) THEN RAISE EXCEPTION 'JSON'; END IF;
     output:=content::jsonb;
    EXCEPTION WHEN OTHERS THEN errors:=errors||'["INVALID_OUTPUT_JSON"]'::jsonb; END;
   END IF;
  END IF;
 END IF;
 IF output IS NOT NULL THEN
  errors:=errors||onet_matching.schema_issues(output,i.request_body#>'{response_format,json_schema,schema}')
   ||onet_matching.output_issues(output,i.source_fields,i.candidates,(t.settings->>'max_matches')::integer);
 END IF;
 UPDATE onet_matching.attempt SET state=CASE WHEN errors='[]'::jsonb THEN 'VALIDATED' WHEN status<>200 THEN 'ERROR' ELSE 'REJECTED' END,
  http_status=status,response_body=CASE WHEN octet_length(body)<=8388608 THEN body END,
  response_id=envelope->>'id',actual_model=envelope->>'model',provider=envelope->>'provider',
  is_byok=(envelope#>'{usage,is_byok}'='true'::jsonb),prompt_tokens=prompt_count,completion_tokens=output_count,
  router_cost_usd=router,upstream_cost_usd=upstream,cost_usd=charged,parsed_output=output,issues=errors,
  latency_ms=elapsed,completed_at=clock_timestamp() WHERE attempt_id=aid;
 IF charged IS NULL OR envelope#>'{usage,is_byok}' IS DISTINCT FROM 'true'::jsonb OR charged>a.reserve_usd
  OR envelope->>'model' IS DISTINCT FROM t.settings->>'model' OR lower(coalesce(envelope->>'provider','')) IS DISTINCT FROM 'openai'
 THEN
  -- Already admitted workers may settle; all subsequent admissions stop.
  FOR token IN SELECT e.execution_token FROM onet_matching.execution e JOIN onet_matching.batch b USING(batch_id)
   JOIN onet_matching.task x USING(task_id) WHERE x.budget_key=t.budget_key
    AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end finish WHERE finish.execution_token=e.execution_token) LOOP
   INSERT INTO onet_matching.execution_stop(execution_token,reason) VALUES(token,'UNKNOWN_CHARGE_ROUTE_OR_RESERVATION_BREACH') ON CONFLICT DO NOTHING;
  END LOOP;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION onet_matching.eligible_inputs(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce(jsonb_agg(i.posting_identity ORDER BY i.posting_identity),'[]'::jsonb)
 FROM onet_matching.input i WHERE i.task_id=id AND NOT EXISTS(
  SELECT 1 FROM onet_matching.attempt a WHERE a.task_id=id AND a.posting_identity=i.posting_identity)
$$;
CREATE OR REPLACE FUNCTION onet_matching.results(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object('posting_identity',a.posting_identity,'source_id',i.source_id,
  'source_fields',i.source_fields,'attempt_id',a.attempt_id,'state',a.state,'issues',a.issues,
  'output',a.parsed_output,'actual_model',a.actual_model,'provider',a.provider,'is_byok',a.is_byok,
  'cost_usd',a.cost_usd,'router_cost_usd',a.router_cost_usd,'upstream_cost_usd',a.upstream_cost_usd,
  'source_hash',i.source_hash,'input_hash',i.input_hash) ORDER BY a.ordinal),'[]'::jsonb)
 FROM onet_matching.attempt a JOIN onet_matching.input i USING(task_id,posting_identity) WHERE a.batch_id=id
$$;
COMMIT;
