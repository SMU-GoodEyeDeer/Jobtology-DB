-- Reparse archived original bytes with the existing document-processor service.
-- Original Tika/HWPX outcomes and frozen model inputs remain untouched.
BEGIN;
SELECT retention.gate();
CREATE TABLE IF NOT EXISTS attachment.processor_batch (
 batch_id text PRIMARY KEY, attachment_batch_ids text[] NOT NULL,
 parser_revision text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS attachment.processor_document (
 parse_id text PRIMARY KEY, batch_id text NOT NULL REFERENCES attachment.processor_batch,
 attempt_id text NOT NULL REFERENCES attachment.attempt, raw_hash text NOT NULL,
 state text NOT NULL DEFAULT 'PLANNED' CHECK(state IN ('PLANNED','RUNNING','PARSED','NO_TEXT','PARSE_ERROR')),
 result jsonb, result_hash text, issue text, finished_at timestamptz,
 UNIQUE(batch_id,attempt_id)
);
CREATE TABLE IF NOT EXISTS attachment.processor_reuse (
 parse_id text PRIMARY KEY REFERENCES attachment.processor_document,
 previous_parse_id text NOT NULL REFERENCES attachment.processor_document,
 reused_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS processor_reusable_hash ON attachment.processor_document(raw_hash) WHERE state='PARSED';
CREATE OR REPLACE FUNCTION attachment.prepare_processor(id text,batches_text text,revision text,cap integer)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE batches text[]:=string_to_array(batches_text,'|'); b text; old attachment.processor_batch; BEGIN
 PERFORM retention.gate();
 IF nullif(id,'') IS NULL THEN id:=gen_random_uuid()::text; END IF;
 IF id !~ '^[A-Za-z0-9_-]{1,100}$' OR revision !~ '^[A-Za-z0-9._-]{1,160}$' OR revision IS NULL OR cap IS NULL OR cap NOT BETWEEN 1 AND 10000
 OR cardinality(batches) IS NULL OR cardinality(batches) NOT BETWEEN 1 AND 100
 OR cardinality(batches)<>(SELECT count(DISTINCT x) FROM unnest(batches) x)
 THEN RAISE EXCEPTION 'INVALID_PROCESSOR_PLAN'; END IF;
 FOREACH b IN ARRAY batches LOOP PERFORM attachment.check_source(b); PERFORM attachment.verify_batch(b); END LOOP;
 SELECT * INTO old FROM attachment.processor_batch WHERE batch_id=id;
 IF FOUND THEN
  IF old.attachment_batch_ids IS DISTINCT FROM batches OR old.parser_revision IS DISTINCT FROM revision
  THEN RAISE EXCEPTION 'PROCESSOR_PLAN_IS_IMMUTABLE'; END IF;
  IF (SELECT count(*) FROM attachment.processor_document WHERE batch_id=id)>cap THEN RAISE EXCEPTION 'PROCESSOR_CAP_EXCEEDED'; END IF;
  RETURN id;
 END IF;
 INSERT INTO attachment.processor_batch(batch_id,attachment_batch_ids,parser_revision) VALUES(id,batches,revision);
 INSERT INTO attachment.processor_document(parse_id,batch_id,attempt_id,raw_hash)
 SELECT attachment.hash(jsonb_build_array(id,a.attempt_id,a.raw_hash,revision)::text),id,a.attempt_id,a.raw_hash
 FROM attachment.attempt a JOIN attachment.document d USING(document_id)
 WHERE d.batch_id=ANY(batches) AND d.disposition='PLANNED' AND a.http_status=200
 AND a.raw_hash IS NOT NULL AND a.byte_length BETWEEN 1 AND 67108864
 AND a.state IN ('ARCHIVED_ONLY','PARSED','PARSE_ERROR','NO_TEXT','NEEDS_REVIEW')
 AND NOT EXISTS(SELECT 1 FROM attachment.document newer WHERE newer.posting_id=d.posting_id
  AND newer.file_ordinal=d.file_ordinal AND newer.batch_id=ANY(batches)
  AND array_position(batches,newer.batch_id)>array_position(batches,d.batch_id));
 IF (SELECT count(*) FROM attachment.processor_document WHERE batch_id=id)>cap THEN RAISE EXCEPTION 'PROCESSOR_CAP_EXCEEDED'; END IF;
 -- Preserve the exact text and block identifiers for unchanged bytes. The
 -- manifest records the new snapshot separately from the reusable model input.
 INSERT INTO attachment.processor_reuse(parse_id,previous_parse_id)
 SELECT p.parse_id,prior.parse_id FROM attachment.processor_document p
 CROSS JOIN LATERAL (SELECT x.parse_id FROM attachment.processor_document x
  JOIN attachment.processor_batch xb ON xb.batch_id=x.batch_id
  WHERE x.raw_hash=p.raw_hash AND xb.parser_revision=revision AND x.state='PARSED'
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(x.result#>'{structure,members}','[]')) m WHERE m->>'state'='PARSE_ERROR')
  AND x.result_hash=attachment.hash(x.result::text)
  ORDER BY x.finished_at DESC,x.parse_id DESC LIMIT 1) prior WHERE p.batch_id=id;
 UPDATE attachment.processor_document p SET state=prior_result.state,result=prior_result.result,
 result_hash=prior_result.result_hash,issue=prior_result.issue,finished_at=clock_timestamp()
 FROM attachment.processor_reuse reuse JOIN attachment.processor_document prior_result ON prior_result.parse_id=reuse.previous_parse_id
 WHERE p.parse_id=reuse.parse_id AND p.batch_id=id;
 RETURN id;
END $$;
-- Explicit repair operation, never an implicit cross-version cache hit. Existing
-- successful text stays byte-identical; only missing/failed rows use the new
-- parser revision. Each copied result retains its actual producing revision.
CREATE OR REPLACE FUNCTION attachment.reuse_processor_successes(target text,source text) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE count_rows integer; BEGIN
 IF coalesce(source,'')='' THEN RETURN 0; END IF;
 PERFORM retention.gate(); PERFORM attachment.verify_processor(source);
 IF NOT EXISTS(SELECT 1 FROM attachment.processor_batch WHERE batch_id=target AND batch_id<>source)
 THEN RAISE EXCEPTION 'DISTINCT_PROCESSOR_TARGET_REQUIRED'; END IF;
 INSERT INTO attachment.processor_reuse(parse_id,previous_parse_id)
 SELECT p.parse_id,prior.parse_id FROM attachment.processor_document p
 CROSS JOIN LATERAL (SELECT x.parse_id FROM attachment.processor_document x
   WHERE x.batch_id=source AND x.raw_hash=p.raw_hash AND x.state='PARSED'
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(x.result#>'{structure,members}','[]')) m WHERE m->>'state'='PARSE_ERROR')
   AND x.result_hash=attachment.hash(x.result::text) ORDER BY x.parse_id LIMIT 1) prior
 WHERE p.batch_id=target AND p.state='PLANNED' ON CONFLICT DO NOTHING;
 UPDATE attachment.processor_document p SET state=prior.state,result=prior.result,
  result_hash=prior.result_hash,issue=prior.issue,finished_at=clock_timestamp()
 FROM attachment.processor_reuse r JOIN attachment.processor_document prior ON prior.parse_id=r.previous_parse_id
 WHERE p.batch_id=target AND p.parse_id=r.parse_id AND p.state='PLANNED';
 GET DIAGNOSTICS count_rows=ROW_COUNT; RETURN count_rows;
END $$;
CREATE OR REPLACE FUNCTION attachment.reserve_processor(id text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE request text; BEGIN
 PERFORM retention.gate();
 UPDATE attachment.processor_document SET state='RUNNING' WHERE parse_id=id AND state='PLANNED';
 IF NOT FOUND THEN RAISE EXCEPTION 'PROCESSOR_PLAN_REQUIRED'; END IF;
 PERFORM retention.enter_writer(id,'ATTACHMENT',id);
 SELECT jsonb_build_object('path',a.raw_path,'extension',d.extension,'raw_hash',p.raw_hash)::text INTO STRICT request
 FROM attachment.processor_document p JOIN attachment.attempt a USING(attempt_id)
 JOIN attachment.document d USING(document_id) WHERE p.parse_id=id AND a.raw_hash=p.raw_hash;
 RETURN request;
END $$;
CREATE OR REPLACE FUNCTION attachment.save_processor(id text,status integer,body text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p attachment.processor_document;b attachment.processor_batch;v jsonb;s jsonb;last_end integer:=0;n integer:=0; BEGIN
 SELECT * INTO STRICT p FROM attachment.processor_document WHERE parse_id=id AND state='RUNNING' FOR UPDATE;
 SELECT * INTO STRICT b FROM attachment.processor_batch WHERE batch_id=p.batch_id;
 BEGIN
  v:=body::jsonb;
  IF status<>200 OR v->>'state' NOT IN ('PARSED','NO_TEXT') THEN
   RAISE EXCEPTION '%',CASE WHEN v->>'issue' ~ '^[A-Z_]{1,100}$' THEN v->>'issue' ELSE 'PARSER_REQUEST_FAILED' END;
  END IF;
  IF v->>'contract' IS DISTINCT FROM 'document-processor-v1' OR v->>'parser_revision' IS DISTINCT FROM b.parser_revision
  OR v->>'raw_hash' IS DISTINCT FROM p.raw_hash OR v->>'text_hash' IS DISTINCT FROM attachment.hash(v->>'markdown')
  OR jsonb_typeof(v->'sections') IS DISTINCT FROM 'array' OR jsonb_typeof(v->'structure') IS DISTINCT FROM 'object'
  OR jsonb_typeof(v->'semantic') IS DISTINCT FROM 'object' OR jsonb_typeof(v->'warnings') IS DISTINCT FROM 'array'
  THEN RAISE EXCEPTION 'PARSER_RESPONSE_BINDING_MISMATCH'; END IF;
  FOR s IN SELECT jsonb_array_elements(v->'sections') LOOP
   n:=n+1;
   IF (s->>'section_no')::integer<>n OR (s->>'start')::integer<>(last_end+CASE WHEN n=1 THEN 0 ELSE 2 END)
   OR (s->>'end')::integer<=(s->>'start')::integer OR nullif(s->>'locator','') IS NULL
   OR s->>'content_hash' IS DISTINCT FROM attachment.hash(substring(v->>'markdown' FROM 1+(s->>'start')::integer FOR (s->>'end')::integer-(s->>'start')::integer))
   THEN RAISE EXCEPTION 'PARSER_BLOCK_MISMATCH'; END IF;
   last_end:=(s->>'end')::integer;
  END LOOP;
  IF last_end<>length(v->>'markdown') OR (v->>'state'='PARSED' AND n=0) THEN RAISE EXCEPTION 'PARSER_TEXT_COVERAGE_MISMATCH'; END IF;
  UPDATE attachment.processor_document SET state=v->>'state',result=v,result_hash=attachment.hash(v::text),finished_at=clock_timestamp() WHERE parse_id=id;
 EXCEPTION WHEN OTHERS THEN
  UPDATE attachment.processor_document SET state='PARSE_ERROR',issue=SQLERRM,finished_at=clock_timestamp() WHERE parse_id=id;
 END;
END $$;
CREATE OR REPLACE FUNCTION attachment.finish_processor(id text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 UPDATE attachment.processor_document SET state='PARSE_ERROR',issue='PARSER_TRANSPORT_OR_CHILD_FAILURE',finished_at=clock_timestamp()
 WHERE parse_id=id AND state='RUNNING';
 PERFORM retention.leave_writer(id);
END $$;
CREATE OR REPLACE FUNCTION attachment.verify_processor(id text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM attachment.processor_batch WHERE batch_id=id) THEN RAISE EXCEPTION 'PROCESSOR_BATCH_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM attachment.processor_document WHERE batch_id=id AND state IN ('PLANNED','RUNNING'))
 THEN RAISE EXCEPTION 'PROCESSOR_BATCH_INCOMPLETE'; END IF;
 IF EXISTS(SELECT 1 FROM attachment.processor_document p JOIN attachment.attempt a USING(attempt_id)
 WHERE p.batch_id=id AND (p.raw_hash<>a.raw_hash OR p.result_hash IS DISTINCT FROM attachment.hash(p.result::text)))
 THEN RAISE EXCEPTION 'PROCESSOR_RESULT_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION attachment.build_processor_input(jobs text,posting text,id text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE b attachment.processor_batch;v jsonb;data jsonb;manifest jsonb;fields jsonb;
 doc jsonb;binding jsonb;documents jsonb:='[]';bindings jsonb:='[]';p attachment.processor_document;field text; BEGIN
 SELECT * INTO STRICT b FROM attachment.processor_batch WHERE batch_id=id;
 PERFORM attachment.verify_processor(id);
 v:=attachment.build_input_bundle(jobs,posting,b.attachment_batch_ids);
 data:=v->'source_data';manifest:=v->'manifest';fields:=data#>'{_input,fields}';
 FOR doc IN SELECT jsonb_array_elements(data#>'{_input,documents}') LOOP
  SELECT value INTO STRICT binding FROM jsonb_array_elements(manifest->'documents') WHERE value->'file_ordinal'=doc->'file_ordinal';
  field:=doc->>'field';
  IF field IS NOT NULL THEN data:=data-field;fields:=fields-field; END IF;
  field:=NULL;
  SELECT * INTO p FROM attachment.processor_document WHERE batch_id=id AND attempt_id=binding->>'attempt_id';
  IF p.state='PARSED' THEN
   field:='attachment_'||(doc->>'file_ordinal')||'_'||(doc#>>'{metadata,recrutAtchFileNo}');
   data:=data||jsonb_build_object(field,p.result->>'markdown');
   fields:=fields||jsonb_build_object(field,jsonb_build_object(
    'file_id',doc#>>'{metadata,recrutAtchFileNo}','file_ordinal',doc->'file_ordinal',
    'name',doc#>>'{metadata,atchFileNm}','role',doc#>>'{metadata,atchFileType}',
    'raw_hash',p.raw_hash,'parser_version',p.result->>'parser_version','parser_revision',p.result->>'parser_revision',
    'text_hash',p.result->>'text_hash','separator',E'\n\n','offset_unit','unicode-codepoint-zero-half-open',
    'sections',p.result->'sections','warnings',p.result->'warnings'));
  END IF;
  documents:=documents||jsonb_build_array(doc||jsonb_build_object('field',field,'original_outcome',doc->'outcome',
   'outcome',coalesce(p.state,doc->>'outcome'),'processor_state',coalesce(p.state,'NOT_PREPARED'),
   'processor_issue',p.issue,'text_source','DOCUMENT_PROCESSOR'));
  bindings:=bindings||jsonb_build_array(binding||jsonb_build_object('field',field,'processor_parse_id',p.parse_id,
   'processor_result_hash',p.result_hash,'original_parse_sections',binding->'sections','sections',coalesce(p.result->'sections','[]')));
 END LOOP;
 data:=jsonb_set(data,'{_input}',jsonb_build_object('contract','attachment-input-v2','fields',fields,'documents',documents));
 manifest:=manifest||jsonb_build_object('contract','document-processor-input-v1','processor_batch_id',id,'documents',bindings);
 RETURN jsonb_build_object('source_data',data,'manifest',manifest);
END $$;
CREATE OR REPLACE FUNCTION attachment.prepare_processor_inputs(jobs text,id text,postings text,cap integer,dataset text,ncs text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE ids text[];bundles text[]:='{}';p text;v jsonb;bid text; BEGIN
 PERFORM retention.gate();
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_INPUT_POSTING_CAP'; END IF;
 IF coalesce(postings,'')='' THEN SELECT array_agg(posting_id ORDER BY posting_id) INTO ids FROM ingestion.job_posting WHERE run_id=jobs;
 ELSE ids:=string_to_array(postings,'|'); END IF;
 IF cardinality(ids) IS NULL OR cardinality(ids) NOT BETWEEN 1 AND cap OR cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x)
 THEN RAISE EXCEPTION 'INVALID_OR_EXCESSIVE_INPUT_POSTING_SELECTION'; END IF;
 FOREACH p IN ARRAY ids LOOP
  v:=attachment.build_processor_input(jobs,p,id);bid:=attachment.hash(v::text);
  INSERT INTO enrichment.input_bundle(bundle_id,job_run_id,posting_id,source_data,source_hash,manifest)
  VALUES(bid,jobs,p,v->'source_data',attachment.hash((v->'source_data')::text),v->'manifest') ON CONFLICT DO NOTHING;
  bundles:=array_append(bundles,bid);
 END LOOP;
 IF coalesce(dataset,'')<>'' THEN PERFORM enrichment.prepare_input_dataset(dataset,ncs,bundles); END IF;
 RETURN jsonb_build_object('bundle_ids',array_to_string(bundles,'|'),'postings',cardinality(ids),'dataset_id',nullif(dataset,''));
END $$;
CREATE OR REPLACE FUNCTION attachment.verify_input_bundle(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b record;v jsonb;batches text[];structures text[]; BEGIN
 SELECT * INTO STRICT b FROM enrichment.input_bundle WHERE bundle_id=id;
 SELECT array_agg(x ORDER BY n) INTO batches FROM jsonb_array_elements_text(b.manifest->'attachment_batch_ids') WITH ORDINALITY a(x,n);
 CASE b.manifest->>'contract'
 WHEN 'attachment-input-v1' THEN v:=attachment.build_input_bundle(b.job_run_id,b.posting_id,batches);
 WHEN 'attachment-input-v2' THEN
  SELECT array_agg(x ORDER BY n) INTO structures FROM jsonb_array_elements_text(b.manifest->'hwpx_batch_ids') WITH ORDINALITY a(x,n);
  v:=attachment.build_structured_input(b.job_run_id,b.posting_id,batches,structures);
 WHEN 'document-processor-input-v1' THEN v:=attachment.build_processor_input(b.job_run_id,b.posting_id,b.manifest->>'processor_batch_id');
 ELSE RAISE EXCEPTION 'UNKNOWN_ATTACHMENT_INPUT_CONTRACT'; END CASE;
 IF b.bundle_id IS DISTINCT FROM attachment.hash(v::text) OR b.source_data IS DISTINCT FROM v->'source_data'
 OR b.manifest IS DISTINCT FROM v->'manifest' OR b.source_hash IS DISTINCT FROM attachment.hash(b.source_data::text)
 THEN RAISE EXCEPTION 'IMMUTABLE_INPUT_BUNDLE_CHANGED'; END IF;
END $$;
COMMIT;
