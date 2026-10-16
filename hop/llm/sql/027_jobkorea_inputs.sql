-- Local JobKorea observations become frozen, exact-evidence model input.
-- Install after the existing LLM contracts; the source adapter is optional
-- until JobKorea preparation is invoked. No ingestion evidence is modified.
BEGIN;

-- Exact selected-input lookup stays indexed as local datasets grow. The index
-- stores the existing source-qualified ID expression; it changes no evidence.
CREATE INDEX IF NOT EXISTS jobkorea_llm_posting_lookup
 ON ingestion.record(run_id,('ext-jobkorea-'||enrichment.hash(source_record_id)))
 WHERE document_id='local-json';
CREATE INDEX IF NOT EXISTS input_bundle_snapshot_posting_lookup
 ON enrichment.input_bundle(job_run_id,posting_id);

CREATE OR REPLACE FUNCTION enrichment.is_jobkorea_input_field(n jsonb,f text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(n#>>'{_input,contract}'='jobkorea-input-v1'
  AND f IN ('role','experience_raw','job_functions','company_name_raw','salary_raw',
   'work_hours','company_size','company_type','industry','benefits_text','application_method')
  AND jsonb_typeof(n->f)='string' AND length(btrim(n->>f))>0
  AND n#>ARRAY['_input','fields',f,'text_hash']=to_jsonb(enrichment.hash(n->>f))
  AND n#>>ARRAY['_input','fields',f,'evidence_role']='LISTING_METADATA',false)
$$;

-- Keep the historical inline whitelist and its hashes exactly unchanged.
CREATE OR REPLACE FUNCTION enrichment.input_fields(n jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT enrichment.source_fields(n)||coalesce(jsonb_object_agg(key,value),'{}') FROM jsonb_each(n)
 WHERE enrichment.is_attachment_field(n,key) OR enrichment.is_jobkorea_input_field(n,key)
$$;

CREATE OR REPLACE FUNCTION enrichment.build_jobkorea_input(jobs text,posting text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE r record; receipt record; doc record; parsed record; physical record; data jsonb:='{}'; fields jsonb:='{}'; audit_fields jsonb:='{}';
 metadata jsonb; f text; k text; evidence_role text; v text; descriptor jsonb; document jsonb; dataset jsonb;
BEGIN
 IF jobs IS NULL OR jobs='LATEST' OR posting IS NULL OR posting !~ '^ext-jobkorea-[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'JOBKOREA_INPUT_REQUIRES_EXACT_SNAPSHOT_AND_POSTING'; END IF;
 IF to_regclass('ingestion.jobkorea_import') IS NULL
 THEN RAISE EXCEPTION 'JOBKOREA_SOURCE_ADAPTER_REQUIRED'; END IF;
 -- READY is sealed by the source adapter after whole-file validation. Recheck
 -- the selected row/receipt here rather than rescanning every unrelated row
 -- for each model item. File scope never establishes provider completeness.
 IF NOT EXISTS(SELECT 1 FROM ingestion.run u WHERE u.run_id=jobs AND u.source_id='jobkorea'
  AND u.state='READY' AND u.mode='REPLAY')
 THEN RAISE EXCEPTION 'LLM_REQUIRES_VALID_READY_SNAPSHOT: jobkorea'; END IF;
 SELECT * INTO STRICT receipt FROM ingestion.jobkorea_import WHERE run_id=jobs;
 SELECT * INTO STRICT r FROM ingestion.ready_record WHERE run_id=jobs AND source_id='jobkorea' AND document_id='local-json'
  AND 'ext-jobkorea-'||enrichment.hash(source_record_id)=posting;
 SELECT * INTO STRICT doc FROM ingestion.document WHERE run_id=jobs AND document_id=r.document_id;
 IF NOT receipt.loaded OR receipt.error_code IS NOT NULL OR receipt.processed_at IS NULL
  OR receipt.scope<>'FILE_ONLY' OR receipt.provider_complete
  OR receipt.payload_sha256 IS DISTINCT FROM receipt.file_sha256
  OR receipt.document_id IS DISTINCT FROM r.document_id OR doc.transport<>'LOCAL_FILE'
  OR doc.raw_sha256 IS DISTINCT FROM receipt.file_sha256 OR doc.http_status IS NOT NULL
  OR doc.provider_result IS NOT NULL OR NOT doc.selected OR doc.verified_at IS NULL
  OR EXISTS(SELECT 1 FROM ingestion.jobkorea_issue i WHERE i.run_id=jobs AND i.severity='ERROR')
 THEN RAISE EXCEPTION 'JOBKOREA_INPUT_SOURCE_BINDING_INVALID'; END IF;
 SELECT * INTO STRICT parsed FROM ingestion.normalize_jobkorea_row(r.source_payload,r.locator);
 IF r.normalized IS DISTINCT FROM parsed.normalized OR r.field_lineage IS DISTINCT FROM parsed.field_lineage
  OR r.quality_flags IS DISTINCT FROM parsed.quality_flags OR parsed.errors<>'[]'::jsonb
  OR r.source_record_id IS DISTINCT FROM r.normalized->>'posting_id'
 THEN RAISE EXCEPTION 'JOBKOREA_INPUT_SOURCE_NORMALIZATION_CHANGED'; END IF;

 -- Evidence strings are copied from the supplied object without trimming,
 -- formatting or synthesized labels. Normalized facts are separate context.
 FOR f,k IN SELECT * FROM (VALUES
  ('title','job_title'),('company_name_raw','company_name'),('organization_name','company_name'),
  ('role','job_position'),('education','education_level'),('experience_raw','experience_level'),
  ('employment_type','employment_type'),('regions','work_location'),('job_functions','job_functions'),
  ('salary_raw','salary'),('work_hours','work_hours'),('company_size','company_size'),
  ('company_type','company_type'),('industry','industry'),('benefits_text','benefits'),
  ('application_method','application_method'),
  ('description_text',CASE WHEN jsonb_typeof(r.source_payload->'description_text')='string'
    AND nullif(btrim(r.source_payload->>'description_text'),'') IS NOT NULL
   THEN 'description_text' ELSE 'job_description_text' END)) mapping(field,source_key) LOOP
  v:=r.source_payload->>k;
  IF jsonb_typeof(r.normalized->f) IS DISTINCT FROM 'string'
   OR jsonb_typeof(r.source_payload->k) IS DISTINCT FROM 'string' OR nullif(btrim(v),'') IS NULL THEN CONTINUE; END IF;
  evidence_role:=CASE WHEN f='description_text' THEN 'SUPPLIED_NARRATIVE' ELSE 'LISTING_METADATA' END;
  data:=data||jsonb_build_object(f,v);
  fields:=fields||jsonb_build_object(f,jsonb_build_object('source_key',k,
   'basis','SOURCE_FIELD','evidence_role',evidence_role,'text_hash',enrichment.hash(v),
   'offset_unit','unicode-codepoint-one-inclusive'));
  audit_fields:=audit_fields||jsonb_build_object(f,fields->f||jsonb_build_object('source_locator',r.locator||'/'||k));
 END LOOP;
 SELECT coalesce(jsonb_object_agg(key,value),'{}') INTO metadata FROM jsonb_each(r.normalized)
 WHERE key IN ('title','organization_name','company_name_raw','employer_identity_kind','role',
  'education','experience_raw','employment_type','regions','job_functions','salary_raw','work_hours',
  'company_size','company_type','industry','benefits_text','benefits_tags','application_method','headcount',
  'application_start_date','application_start_at','application_start_precision','application_start_timezone',
  'deadline_kind','deadline_basis','deadline_date','deadline_at','deadline_precision','deadline_timezone',
  'deadline_display_label','source_status','content_status','scope','provider_complete');
 descriptor:=jsonb_build_object('kind','FULL_DESCRIPTION','outcome',r.normalized->>'content_status',
  'field',CASE WHEN data ? 'description_text' THEN 'description_text' END,
  'text_source',CASE WHEN data ? 'description_text' THEN 'SUPPLIED_LOCAL_TEXT' ELSE 'LOCAL_CONTENT_ABSENT' END);
 data:=data||jsonb_build_object('_input',jsonb_build_object('contract','jobkorea-input-v1',
  'assembly_version','jobkorea-local-metadata-v1','source_id','jobkorea','fields',fields,'metadata',metadata,
  'documents',jsonb_build_array(descriptor),'quality_flags',r.quality_flags,
  'metadata_extraction_eligible',true,'full_description_eligible',data ? 'description_text',
  'content_status',r.normalized->>'content_status','scope','FILE_ONLY','provider_complete',false));
 -- Audit-only exact run, local document and import bindings are omitted from
 -- model-facing content so identical observations retain a reusable hash.
 document:=jsonb_build_object('source_document_id',r.document_id,'source_locator',r.locator,
  'record_id',r.record_id,'source_record_id',r.source_record_id,'raw_record_hash',enrichment.hash(r.source_payload::text),
  'normalized_hash',enrichment.hash(r.normalized::text),'field_lineage_hash',enrichment.hash(r.field_lineage::text),
  'quality_flags_hash',enrichment.hash(r.quality_flags::text));
 -- NDJSON locators name physical lines, not JSON Pointers. Exact UTF-8 byte
 -- provenance stays in the audit manifest; identical model evidence and the
 -- historical JSON-array manifests retain their original bytes and hashes.
 IF to_jsonb(receipt)->>'file_format'='NDJSON' THEN
  IF to_regclass('ingestion.jobkorea_ndjson_line') IS NULL
   OR to_regprocedure('ingestion.jobkorea_ndjson_row_hash(text,bigint)') IS NULL OR r.locator !~ '^line:[1-9][0-9]*$'
  THEN RAISE EXCEPTION 'JOBKOREA_INPUT_LINE_PROVENANCE_MISSING'; END IF;
  EXECUTE 'SELECT l.*,ingestion.jobkorea_ndjson_row_hash(l.run_id,l.line_number) AS verified_row_sha256
   FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=$1 AND l.line_number=$2'
   INTO STRICT physical USING jobs,substring(r.locator FROM 6)::bigint;
  IF physical.source_record_id IS DISTINCT FROM r.source_record_id
   OR physical.row_sha256 IS DISTINCT FROM physical.verified_row_sha256
  THEN RAISE EXCEPTION 'JOBKOREA_INPUT_LINE_PROVENANCE_CHANGED'; END IF;
  document:=document||jsonb_build_object('locator_kind','NDJSON_PHYSICAL_LINE',
   'physical_line',physical.line_number,'byte_offset',physical.byte_offset,'byte_length',physical.byte_length,
   'raw_line_sha256',physical.raw_sha256,'offset_unit','utf8-byte-zero-half-open');
  SELECT coalesce(jsonb_object_agg(key,value||jsonb_build_object('locator_kind','NDJSON_PHYSICAL_LINE',
   'physical_line',physical.line_number)),'{}') INTO audit_fields FROM jsonb_each(audit_fields);
 END IF;
 IF to_regclass('ingestion.jobkorea_dataset_provenance') IS NOT NULL THEN
  EXECUTE 'SELECT provenance FROM ingestion.jobkorea_dataset_provenance WHERE run_id=$1' INTO dataset USING jobs;
 END IF;
 RETURN jsonb_build_object('source_data',data,'manifest',jsonb_build_object('contract','jobkorea-input-v1',
  'assembly_version','jobkorea-local-metadata-v1','source_id','jobkorea','job_run_id',jobs,'posting_id',posting,
  'source_hash',enrichment.hash(data::text),'file_sha256',receipt.file_sha256,
  'row_manifest_sha256',receipt.row_manifest_sha256,'parser_version',receipt.parser_version,
  'policy_revision',receipt.policy_revision,
  'received_at',to_char(receipt.received_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'imported_at',to_char(receipt.imported_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'processed_at',to_char(receipt.processed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'scraped_at',to_char(receipt.scraped_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'scope','FILE_ONLY',
  'provider_complete',false,'absence_is_closure',false,'document',document,'fields',audit_fields)||
  CASE WHEN dataset IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('dataset_provenance',dataset) END);
END $$;

-- Listing facts remain deterministic source context, including role/category
-- observations and policy-derived deadlines. They never become inferred work.
-- The historical hydration expression is unchanged for every older contract.
CREATE OR REPLACE FUNCTION enrichment.hydrate_link_v1(output jsonb,source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 WITH hydrated AS (SELECT enrichment.hydrate_v3(output,source)||
  '{"schema_version":"ko-link-v1","extraction_scope":"DUTIES_ONLY"}'::jsonb AS value)
 SELECT CASE WHEN source#>>'{_input,contract}'='jobkorea-input-v1'
  THEN jsonb_set(value,'{source_metadata}',source#>'{_input,metadata}') ELSE value END FROM hydrated
$$;

CREATE OR REPLACE FUNCTION enrichment.verify_jobkorea_input_bundle(id text) RETURNS void
LANGUAGE plpgsql AS $$ DECLARE b enrichment.input_bundle; v jsonb; BEGIN
 SELECT * INTO STRICT b FROM enrichment.input_bundle WHERE bundle_id=id;
 IF b.manifest->>'contract' IS DISTINCT FROM 'jobkorea-input-v1'
  OR b.source_data#>>'{_input,contract}' IS DISTINCT FROM 'jobkorea-input-v1'
 THEN RAISE EXCEPTION 'UNKNOWN_JOBKOREA_INPUT_CONTRACT'; END IF;
 v:=enrichment.build_jobkorea_input(b.job_run_id,b.posting_id);
 IF b.bundle_id IS DISTINCT FROM enrichment.hash(v::text) OR b.source_data IS DISTINCT FROM v->'source_data'
  OR b.manifest IS DISTINCT FROM v->'manifest' OR b.source_hash IS DISTINCT FROM enrichment.hash(b.source_data::text)
 THEN RAISE EXCEPTION 'IMMUTABLE_INPUT_BUNDLE_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.verify_input_bundle(id text) RETURNS void
LANGUAGE plpgsql AS $$ DECLARE contract text; BEGIN
 SELECT manifest->>'contract' INTO STRICT contract FROM enrichment.input_bundle WHERE bundle_id=id;
 IF contract='jobkorea-input-v1' THEN PERFORM enrichment.verify_jobkorea_input_bundle(id);
 ELSE PERFORM attachment.verify_input_bundle(id); END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.prepare_jobkorea_input_bundle(jobs text,posting text) RETURNS text
LANGUAGE plpgsql AS $$ DECLARE v jsonb; id text; BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('jobkorea-input-provenance:'||jobs,0));
 v:=enrichment.build_jobkorea_input(jobs,posting);id:=enrichment.hash(v::text);
 INSERT INTO enrichment.input_bundle(bundle_id,job_run_id,posting_id,source_data,source_hash,manifest)
 VALUES(id,jobs,posting,v->'source_data',enrichment.hash((v->'source_data')::text),v->'manifest') ON CONFLICT DO NOTHING;
 PERFORM enrichment.verify_jobkorea_input_bundle(id);
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION enrichment.prepare_jobkorea_inputs(jobs text,postings text,cap integer) RETURNS jsonb
LANGUAGE plpgsql AS $$ DECLARE ids text[]; bundles text[]:='{}'; p text; BEGIN
 PERFORM retention.gate();
 IF jobs IS NULL OR jobs='LATEST' OR nullif(postings,'') IS NULL OR cap IS NULL OR cap NOT BETWEEN 1 AND 10000
 THEN RAISE EXCEPTION 'JOBKOREA_INPUT_EXPLICIT_SELECTION_REQUIRED'; END IF;
 ids:=string_to_array(postings,'|');
 IF cardinality(ids) NOT BETWEEN 1 AND cap OR cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x)
  OR EXISTS(SELECT 1 FROM unnest(ids) x WHERE x !~ '^ext-jobkorea-[0-9a-f]{64}$')
 THEN RAISE EXCEPTION 'INVALID_OR_EXCESSIVE_INPUT_POSTING_SELECTION'; END IF;
 PERFORM enrichment.assert_snapshot(jobs,'jobkorea');
 FOR p IN SELECT unnest(ids) ORDER BY 1 LOOP
  bundles:=array_append(bundles,enrichment.prepare_jobkorea_input_bundle(jobs,p));
 END LOOP;
 RETURN jsonb_build_object('job_run_id',jobs,'input_contract','jobkorea-input-v1',
  'bundle_ids',array_to_string(bundles,'|'),'postings',cardinality(ids),
  'total_input_chars',(SELECT sum(length(source_data::text)) FROM enrichment.input_bundle WHERE bundle_id=ANY(bundles)));
END $$;

CREATE OR REPLACE TRIGGER immutable_input_bundle_truncate BEFORE TRUNCATE ON enrichment.input_bundle
 FOR EACH STATEMENT EXECUTE FUNCTION enrichment.append_only_review();

-- Installing/replaying LLM before the optional source importer is supported.
DO $$ BEGIN
 IF to_regclass('ingestion.jobkorea_import') IS NOT NULL THEN
  EXECUTE $view$CREATE OR REPLACE VIEW ingestion.llm_posting AS
   SELECT 'job_alio'::text AS source_id,p.run_id,p.posting_id,p.normalized FROM ingestion.job_posting p
   UNION ALL
   SELECT 'nara_job',p.run_id,'ext-nara_job-'||enrichment.hash(p.posting_id),p.normalized FROM ingestion.nara_job_posting p
   UNION ALL
   SELECT 'jobkorea',r.run_id,'ext-jobkorea-'||enrichment.hash(r.source_record_id),r.normalized
    FROM ingestion.ready_record r WHERE r.source_id='jobkorea' AND r.document_id='local-json' $view$;
 END IF;
END $$;

COMMENT ON FUNCTION enrichment.build_jobkorea_input(text,text) IS
 'Versioned structured listing metadata and exact supplied narrative evidence. No provider requests, invented duties, employer IDs or scrape timestamps. FILE_ONLY is not a provider census.';
COMMIT;
