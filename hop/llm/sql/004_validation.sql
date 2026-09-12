BEGIN;
-- Validator for the deliberately small JSON Schema subset used by these prompts.
-- This independently checks provider output; provider-side strict mode is not trusted alone.
CREATE OR REPLACE FUNCTION enrichment.schema_issues(v jsonb, s jsonb, path text DEFAULT '$')
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]'; actual text; wanted jsonb; k text; x jsonb; idx integer:=0;
BEGIN
 actual:=jsonb_typeof(v); wanted:=s->'type';
 IF actual='number' AND v::text ~ '^-?[0-9]+$' AND
  (wanted='"integer"'::jsonb OR wanted @> '["integer"]'::jsonb) THEN actual:='integer'; END IF;
 IF actual IS NULL OR NOT (wanted=to_jsonb(actual) OR
  (jsonb_typeof(wanted)='array' AND wanted @> jsonb_build_array(actual))) THEN
  RETURN jsonb_build_array(path||':TYPE');
 END IF;
 IF s ? 'enum' AND NOT (s->'enum' @> jsonb_build_array(v)) THEN errors:=errors||jsonb_build_array(path||':ENUM'); END IF;
 IF actual='object' THEN
  FOR k IN SELECT jsonb_array_elements_text(coalesce(s->'required','[]')) LOOP
   IF NOT v ? k THEN errors:=errors||jsonb_build_array(path||'.'||k||':REQUIRED'); END IF;
  END LOOP;
  FOR k,x IN SELECT * FROM jsonb_each(v) LOOP
   IF s->'properties' ? k THEN errors:=errors||enrichment.schema_issues(x,s->'properties'->k,path||'.'||k);
   ELSIF s->'additionalProperties'='false'::jsonb THEN errors:=errors||jsonb_build_array(path||':EXTRA_PROPERTY'); END IF;
  END LOOP;
 ELSIF actual='array' THEN
  IF jsonb_array_length(v)>coalesce((s->>'maxItems')::integer,2147483647) THEN errors:=errors||jsonb_build_array(path||':TOO_MANY_ITEMS'); END IF;
  FOR x IN SELECT jsonb_array_elements(v) LOOP
   errors:=errors||enrichment.schema_issues(x,s->'items',path||'['||idx||']'); idx:=idx+1;
  END LOOP;
 ELSIF actual='string' THEN
  IF length(v#>>'{}')<coalesce((s->>'minLength')::integer,0) OR
     length(v#>>'{}')>coalesce((s->>'maxLength')::integer,2147483647)
  THEN errors:=errors||jsonb_build_array(path||':STRING_LENGTH'); END IF;
 ELSIF actual IN ('number','integer') THEN
  IF (s ? 'minimum' AND (v::text)::numeric<(s->>'minimum')::numeric) OR
     (s ? 'maximum' AND (v::text)::numeric>(s->>'maximum')::numeric)
  THEN errors:=errors||jsonb_build_array(path||':NUMBER_RANGE'); END IF;
 END IF;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.output_issues(step text, output jsonb, source jsonb, extraction jsonb, candidates jsonb, max_matches integer)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]'; section text; x jsonb; field text; quote text; value text; n integer;
BEGIN
 IF step='extract' THEN
  FOREACH section IN ARRAY ARRAY['positions','duties','requirements'] LOOP
   FOR x IN SELECT jsonb_array_elements(output->section) LOOP
    field:=x#>>'{evidence,field}'; quote:=x#>>'{evidence,quote}';
    value:=CASE WHEN section='positions' THEN x->>'name' ELSE x->>'text' END;
    IF nullif(btrim(quote),'') IS NULL OR length(btrim(quote))<2 OR
     coalesce(position(quote in source->>field),0)=0 OR coalesce(position(value in quote),0)=0
    THEN errors:=errors||jsonb_build_array(section||':UNSUPPORTED_EVIDENCE'); END IF;
    IF section<>'positions' AND x->>'position' IS NOT NULL AND NOT EXISTS(
      SELECT 1 FROM jsonb_array_elements(output->'positions') p WHERE p->>'name'=x->>'position')
    THEN errors:=errors||jsonb_build_array(section||':UNKNOWN_POSITION'); END IF;
    IF section='duties' AND field NOT IN ('eligibility_text','selection_text','duties_text','description_text')
    THEN errors:=errors||'["duties:NON_DUTY_FIELD"]'::jsonb; END IF;
    IF section='requirements' THEN
     IF field='preference_text' AND x->>'importance'<>'preferred' THEN errors:=errors||'["requirements:PREFERENCE_AS_REQUIRED"]'::jsonb; END IF;
     IF x->>'logic'='any_of' AND quote !~* '(또는|혹은|중.{0,15}(하나|1개|1가지)|\mOR\M|/)' THEN errors:=errors||'["requirements:UNSUPPORTED_ALTERNATIVE"]'::jsonb; END IF;
    END IF;
   END LOOP;
   IF (SELECT count(*) FROM jsonb_array_elements(output->section)) <>
      (SELECT count(DISTINCT v) FROM jsonb_array_elements(output->section) v)
   THEN errors:=errors||jsonb_build_array(section||':DUPLICATE'); END IF;
  END LOOP;
  IF (jsonb_array_length(output->'duties')>0) IS DISTINCT FROM (output->>'duties_status'='explicit')
  THEN errors:=errors||'["duties:STATUS_MISMATCH"]'::jsonb; END IF;
 ELSE
  IF jsonb_array_length(output->'matches')>max_matches THEN errors:=errors||'["matches:TOO_MANY"]'::jsonb; END IF;
  IF (jsonb_array_length(output->'matches')>0) IS DISTINCT FROM (output->>'outcome'='matched')
  THEN errors:=errors||'["matches:OUTCOME_MISMATCH"]'::jsonb; END IF;
  FOR x IN SELECT jsonb_array_elements(output->'matches') LOOP
   n:=(x->>'duty_index')::integer;
   IF n<0 OR n>=jsonb_array_length(extraction->'duties') THEN errors:=errors||'["matches:UNKNOWN_DUTY"]'::jsonb; END IF;
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(candidates) c WHERE c->>'code'=x->>'competency_code')
   THEN errors:=errors||'["matches:CODE_OUTSIDE_SHORTLIST"]'::jsonb; END IF;
  END LOOP;
  IF (SELECT count(*) FROM jsonb_array_elements(output->'matches')) <>
     (SELECT count(DISTINCT jsonb_build_array(m.value->'competency_code',m.value->'duty_index')) FROM jsonb_array_elements(output->'matches') m(value))
  THEN errors:=errors||'["matches:DUPLICATE"]'::jsonb; END IF;
 END IF;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.save_response(aid text, status integer, body text, elapsed bigint)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE a enrichment.attempt%ROWTYPE; b enrichment.batch%ROWTYPE; i enrichment.item%ROWTYPE;
 envelope jsonb; output jsonb; ext jsonb; errors jsonb:='[]'; content text; schema jsonb;
 prompt_count bigint; output_count bigint; charged numeric;
BEGIN
 SELECT * INTO STRICT a FROM enrichment.attempt WHERE attempt_id=aid FOR UPDATE;
 IF a.state<>'RESERVED' THEN RAISE EXCEPTION 'RESPONSE_WITHOUT_RESERVATION'; END IF;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=a.batch_id;
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=a.item_id;
 IF status=0 THEN errors:='["TRANSPORT_ERROR_UNKNOWN_CHARGE"]';
 ELSIF octet_length(body)>8388608 THEN errors:='["RESPONSE_TOO_LARGE"]';
 ELSE
  BEGIN
   IF NOT coalesce(body IS JSON OBJECT WITH UNIQUE KEYS,false) THEN RAISE EXCEPTION 'INVALID_JSON'; END IF;
   envelope:=body::jsonb;
  EXCEPTION WHEN OTHERS THEN errors:='["INVALID_RESPONSE_JSON"]'; END;
  IF envelope IS NOT NULL THEN
   IF status<>200 OR envelope ? 'error' THEN errors:=errors||'["PROVIDER_ERROR"]'::jsonb;
   ELSIF jsonb_typeof(envelope->'choices') IS DISTINCT FROM 'array' THEN errors:=errors||'["MISSING_CHOICES"]'::jsonb;
   ELSIF jsonb_array_length(envelope->'choices')<>1 OR envelope#>>'{choices,0,finish_reason}' IS DISTINCT FROM 'stop'
     OR coalesce(envelope#>>'{choices,0,message,refusal}','')<>'' THEN errors:=errors||'["INCOMPLETE_OR_REFUSED"]'::jsonb;
   ELSE
    content:=envelope#>>'{choices,0,message,content}';
    BEGIN
     IF NOT coalesce(content IS JSON OBJECT WITH UNIQUE KEYS,false) THEN RAISE EXCEPTION 'INVALID_JSON'; END IF;
     output:=content::jsonb;
    EXCEPTION WHEN OTHERS THEN errors:=errors||'["INVALID_OUTPUT_JSON"]'::jsonb; END;
   END IF;
   BEGIN
    IF envelope#>>'{usage,prompt_tokens}' ~ '^[0-9]{1,12}$' THEN prompt_count:=(envelope#>>'{usage,prompt_tokens}')::bigint; END IF;
    IF envelope#>>'{usage,completion_tokens}' ~ '^[0-9]{1,12}$' THEN output_count:=(envelope#>>'{usage,completion_tokens}')::bigint; END IF;
    IF jsonb_typeof(envelope#>'{usage,cost}')='number' AND (envelope#>>'{usage,cost}')::numeric>=0
    THEN charged:=(envelope#>>'{usage,cost}')::numeric; END IF;
   EXCEPTION WHEN OTHERS THEN NULL; END;
  END IF;
 END IF;
 IF output IS NOT NULL AND errors='[]' THEN
  schema:=a.request_body#>'{response_format,json_schema,schema}';
  errors:=enrichment.schema_issues(output,schema);
  IF errors='[]' THEN
   SELECT parsed_output INTO ext FROM enrichment.attempt WHERE attempt_id=i.extraction_id;
   errors:=enrichment.output_issues(a.stage,output,i.source_data,ext,a.candidates,(b.settings->>'max_matches')::integer);
  END IF;
 END IF;
 UPDATE enrichment.attempt SET state=CASE WHEN errors='[]' THEN 'VALIDATED' WHEN status=0 OR status<>200 THEN 'ERROR' ELSE 'REJECTED' END,
  http_status=status,response_body=CASE WHEN octet_length(body)<=8388608 THEN body END,
  response_id=envelope->>'id',actual_model=envelope->>'model',provider=envelope->>'provider',
  parsed_output=output,issues=errors,prompt_tokens=prompt_count,completion_tokens=output_count,cost_usd=charged,
  latency_ms=elapsed,completed_at=clock_timestamp() WHERE attempt_id=aid;
END $$;

CREATE OR REPLACE FUNCTION enrichment.finish_batch(id text, failed boolean DEFAULT false)
RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 UPDATE enrichment.item i SET
  state=CASE WHEN EXISTS(SELECT 1 FROM enrichment.attempt e WHERE e.attempt_id=i.extraction_id AND e.state='VALIDATED')
   AND EXISTS(SELECT 1 FROM enrichment.attempt c WHERE c.attempt_id=i.categorization_id AND c.state IN ('VALIDATED','SKIPPED'))
   THEN 'VALIDATED' ELSE 'REJECTED' END,
  issue=CASE WHEN NOT EXISTS(SELECT 1 FROM enrichment.attempt e WHERE e.attempt_id=i.extraction_id AND e.state='VALIDATED') THEN 'EXTRACTION_NOT_VALIDATED'
   WHEN NOT EXISTS(SELECT 1 FROM enrichment.attempt c WHERE c.attempt_id=i.categorization_id AND c.state IN ('VALIDATED','SKIPPED')) THEN 'CATEGORIZATION_NOT_VALIDATED' END
 WHERE i.batch_id=id AND EXISTS(SELECT 1 FROM enrichment.batch b WHERE b.batch_id=id AND b.settings->>'execute_requests'='Y');
 IF NOT failed THEN
  INSERT INTO enrichment.review(item_id,decision,reviewer,notes)
  SELECT i.item_id,'ACCEPT','policy:validated-v1','Automatic schema/evidence policy; not a human quality review.'
  FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
  WHERE b.batch_id=id AND b.mode='ENRICH' AND i.state='VALIDATED'
  AND b.settings->>'execute_requests'='Y' AND b.settings->>'acceptance_policy'='VALIDATED'
  AND NOT EXISTS(SELECT 1 FROM enrichment.review r WHERE r.item_id=i.item_id);
 END IF;
 UPDATE enrichment.batch b SET state=CASE WHEN failed THEN 'FAILED'
  WHEN b.settings->>'execute_requests'='N' THEN 'PLANNED'
  WHEN EXISTS(SELECT 1 FROM enrichment.item i WHERE i.batch_id=id AND i.state<>'VALIDATED') THEN 'PARTIAL' ELSE 'COMPLETE' END,
  completed_at=clock_timestamp() WHERE batch_id=id;
END $$;
COMMIT;
