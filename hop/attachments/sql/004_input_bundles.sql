-- Optional LLM input bridge. Install llm/install.hwf before preparing inputs.
-- Functions are deferred PL/pgSQL so attachment-only installation remains valid.
BEGIN;
CREATE OR REPLACE FUNCTION attachment.build_input_bundle(jobs text,posting text,batches text[]) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE b text;p attachment.posting;d record;a attachment.attempt;data jsonb;inline jsonb;
 fields jsonb:='{}';documents jsonb:='[]';bindings jsonb:='[]';sections jsonb;text_value text;
 field text;count_files integer:=0;wanted jsonb;descriptor jsonb; BEGIN
 IF cardinality(batches) IS NULL OR cardinality(batches) NOT BETWEEN 1 AND 100 OR
  cardinality(batches)<>(SELECT count(DISTINCT v) FROM unnest(batches) v) THEN RAISE EXCEPTION 'EXACT_ATTACHMENT_BATCHES_REQUIRED'; END IF;
 FOREACH b IN ARRAY batches LOOP
  IF NOT EXISTS(SELECT 1 FROM attachment.batch WHERE batch_id=b AND job_run_id=jobs) THEN RAISE EXCEPTION 'ATTACHMENT_INPUT_SNAPSHOT_MISMATCH'; END IF;
  PERFORM attachment.verify_batch(b);
 END LOOP;
 SELECT x.* INTO p FROM attachment.posting x JOIN unnest(batches) WITH ORDINALITY b(id,priority) ON b.id=x.batch_id
 WHERE x.posting_id=posting ORDER BY b.priority DESC LIMIT 1;
 IF NOT FOUND THEN RAISE EXCEPTION 'POSTING_HAS_NO_ATTACHMENT_PLAN'; END IF;
 SELECT enrichment.source_fields(normalized) INTO STRICT inline FROM ingestion.job_posting WHERE run_id=jobs AND posting_id=posting;
 data:=inline;
 FOR d IN SELECT DISTINCT ON(x.file_ordinal) x.* FROM attachment.document x
  JOIN unnest(batches) WITH ORDINALITY b(id,priority) ON b.id=x.batch_id
  WHERE x.posting_id=posting ORDER BY x.file_ordinal,b.priority DESC LOOP
  count_files:=count_files+1;wanted:=p.files->(d.file_ordinal-1);
  IF wanted IS DISTINCT FROM d.metadata THEN RAISE EXCEPTION 'ATTACHMENT_METADATA_BINDING_MISMATCH'; END IF;
  SELECT * INTO a FROM attachment.attempt WHERE document_id=d.document_id;
  field:=NULL;sections:='[]';
  IF a.state='PARSED' THEN
   IF a.raw_hash IS NULL OR a.parsed_hash IS NULL OR NOT EXISTS(SELECT 1 FROM attachment.section WHERE attempt_id=a.attempt_id)
   THEN RAISE EXCEPTION 'PARSED_ATTACHMENT_EVIDENCE_MISSING'; END IF;
   IF a.parsed_hash IS DISTINCT FROM (CASE a.parse_storage_version
    WHEN 'xml-jsonb-v1' THEN attachment.hash(jsonb_build_object('xml',a.parsed_xml,'metadata',a.parser_metadata)::text)
    WHEN 'xml-jsonb-v2' THEN attachment.hash(jsonb_build_object('storage_version','xml-jsonb-v2','xml',a.parsed_xml,'metadata_raw',a.parser_metadata_raw)::text) END)
   THEN RAISE EXCEPTION 'ATTACHMENT_PARSE_CHANGED'; END IF;
   IF EXISTS(SELECT 1 FROM attachment.section s WHERE s.attempt_id=a.attempt_id AND s.content_hash<>attachment.hash(s.content))
   THEN RAISE EXCEPTION 'ATTACHMENT_SECTION_CHANGED'; END IF;
   SELECT string_agg(s.content,E'\n' ORDER BY s.section_no),jsonb_agg(jsonb_build_object(
    'section_no',s.section_no,'locator_kind',s.locator_kind,'locator',s.locator,'content_hash',s.content_hash,
    'start',s.start_offset,'end',s.start_offset+length(s.content)) ORDER BY s.section_no)
   INTO text_value,sections FROM (SELECT s.*,coalesce(sum(length(s.content)+1) OVER(ORDER BY s.section_no
    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)::integer AS start_offset
    FROM attachment.section s WHERE s.attempt_id=a.attempt_id) s;
   field:='attachment_'||d.file_ordinal||'_'||(d.metadata->>'recrutAtchFileNo');
   data:=data||jsonb_build_object(field,text_value);
   fields:=fields||jsonb_build_object(field,jsonb_build_object('file_id',d.metadata->>'recrutAtchFileNo',
    'file_ordinal',d.file_ordinal,'name',d.metadata->>'atchFileNm','role',d.metadata->>'atchFileType',
    'raw_hash',a.raw_hash,'parser_version',a.parser_version,'text_hash',attachment.hash(text_value),
    'separator',E'\n','offset_unit','unicode-codepoint-zero-half-open','sections',sections));
  END IF;
  descriptor:=jsonb_build_object('file_ordinal',d.file_ordinal,'metadata',d.metadata,'disposition',d.disposition,
   'outcome',coalesce(a.state,d.disposition),'issue',a.issue,'raw_hash',a.raw_hash,'field',field);
  documents:=documents||jsonb_build_array(descriptor);
  bindings:=bindings||jsonb_build_array(jsonb_build_object('file_ordinal',d.file_ordinal,
   'document_id',d.document_id,'batch_id',d.batch_id,'attempt_id',a.attempt_id,'raw_path',a.raw_path,
   'raw_hash',a.raw_hash,'parsed_hash',a.parsed_hash,'parse_storage_version',a.parse_storage_version,
   'field',field,'sections',sections));
 END LOOP;
 IF count_files<>jsonb_array_length(p.files) THEN RAISE EXCEPTION 'ATTACHMENT_INPUT_COVERAGE_MISMATCH'; END IF;
 data:=data||jsonb_build_object('_input',jsonb_build_object('contract','attachment-input-v1','fields',fields,'documents',documents));
 RETURN jsonb_build_object('source_data',data,'manifest',jsonb_build_object('contract','attachment-input-v1',
  'job_run_id',jobs,'posting_id',posting,'inline_hash',attachment.hash(inline::text),
  'source_document_id',p.source_document_id,'source_locator',p.source_locator,'source_hash',p.source_hash,
  'attachment_batch_ids',to_jsonb(batches),'documents',bindings));
END $$;
CREATE OR REPLACE FUNCTION attachment.prepare_input_bundle(jobs text,posting text,batches text[]) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE v jsonb;id text; BEGIN
 PERFORM retention.gate();
 IF to_regclass('enrichment.input_bundle') IS NULL THEN RAISE EXCEPTION 'INSTALL_LLM_INPUT_SCHEMA_FIRST'; END IF;
 v:=attachment.build_input_bundle(jobs,posting,batches);id:=attachment.hash(v::text);
 INSERT INTO enrichment.input_bundle(bundle_id,job_run_id,posting_id,source_data,source_hash,manifest)
 VALUES(id,jobs,posting,v->'source_data',attachment.hash((v->'source_data')::text),v->'manifest') ON CONFLICT DO NOTHING;
 RETURN id;
END $$;
CREATE OR REPLACE FUNCTION attachment.verify_input_bundle(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b record;v jsonb;batches text[]; BEGIN
 SELECT * INTO STRICT b FROM enrichment.input_bundle WHERE bundle_id=id;
 SELECT array_agg(x ORDER BY n) INTO batches FROM jsonb_array_elements_text(b.manifest->'attachment_batch_ids') WITH ORDINALITY a(x,n);
 v:=attachment.build_input_bundle(b.job_run_id,b.posting_id,batches);
 IF b.bundle_id IS DISTINCT FROM attachment.hash(v::text) OR b.source_data IS DISTINCT FROM v->'source_data'
  OR b.manifest IS DISTINCT FROM v->'manifest' OR b.source_hash IS DISTINCT FROM attachment.hash(b.source_data::text)
 THEN RAISE EXCEPTION 'IMMUTABLE_INPUT_BUNDLE_CHANGED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.prepare_inputs(jobs text,batch_ids text,posting_ids text,cap integer,dataset text,ncs text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE ids text[];batches text[]:=string_to_array(batch_ids,'|');bundles text[]:='{}';p text; BEGIN
 PERFORM retention.gate();
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_INPUT_POSTING_CAP'; END IF;
 IF coalesce(posting_ids,'')='' THEN
  SELECT array_agg(posting_id ORDER BY posting_id) INTO ids FROM ingestion.job_posting WHERE run_id=jobs;
 ELSE ids:=string_to_array(posting_ids,'|'); END IF;
 IF cardinality(ids) IS NULL OR cardinality(ids) NOT BETWEEN 1 AND cap OR
  cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x) OR
  EXISTS(SELECT 1 FROM unnest(ids) x WHERE x !~ '^[0-9]+$') THEN RAISE EXCEPTION 'INVALID_OR_EXCESSIVE_INPUT_POSTING_SELECTION'; END IF;
 FOREACH p IN ARRAY ids LOOP bundles:=array_append(bundles,attachment.prepare_input_bundle(jobs,p,batches)); END LOOP;
 IF coalesce(dataset,'')<>'' THEN PERFORM enrichment.prepare_input_dataset(dataset,ncs,bundles); END IF;
 RETURN jsonb_build_object('bundle_ids',array_to_string(bundles,'|'),'postings',cardinality(ids),'dataset_id',nullif(dataset,''),
  'total_input_chars',(SELECT sum(length(source_data::text)) FROM enrichment.input_bundle WHERE bundle_id=ANY(bundles)));
END $$;
COMMIT;
