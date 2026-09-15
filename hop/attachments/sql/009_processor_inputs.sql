-- Per-posting evidence verification: avoid hashing every document for every item.
-- Existing v1 bundles retain their original construction/verification contract.
BEGIN;
CREATE OR REPLACE FUNCTION attachment.build_processor_input_v2(jobs text,posting text,id text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE b attachment.processor_batch;header attachment.posting;d attachment.document;a attachment.attempt;
 p attachment.processor_document;inline jsonb;data jsonb;fields jsonb:='{}';documents jsonb:='[]';bindings jsonb:='[]';
 field text;current_payload jsonb;count_files integer:=0;descriptor jsonb; BEGIN
 SELECT * INTO STRICT b FROM attachment.processor_batch WHERE batch_id=id;
 SELECT x.* INTO STRICT header FROM attachment.posting x
 JOIN unnest(b.attachment_batch_ids) WITH ORDINALITY priority(batch_id,n) ON priority.batch_id=x.batch_id
 WHERE x.posting_id=posting ORDER BY priority.n DESC LIMIT 1;
 IF EXISTS(SELECT 1 FROM attachment.batch x WHERE x.batch_id=ANY(b.attachment_batch_ids) AND x.job_run_id<>jobs)
 THEN RAISE EXCEPTION 'ATTACHMENT_INPUT_SNAPSHOT_MISMATCH'; END IF;
 SELECT source_payload INTO STRICT current_payload FROM ingestion.ready_record WHERE run_id=jobs AND source_record_id=posting||':detail';
 IF header.source_hash IS DISTINCT FROM attachment.hash(current_payload::text) OR header.files IS DISTINCT FROM current_payload->'files'
 THEN RAISE EXCEPTION 'POSTING_ATTACHMENT_SOURCE_CHANGED'; END IF;
 inline:=enrichment.inline_posting_source(jobs,posting);data:=inline;
 FOR d IN SELECT DISTINCT ON(x.file_ordinal) x.* FROM attachment.document x
 JOIN unnest(b.attachment_batch_ids) WITH ORDINALITY priority(batch_id,n) ON priority.batch_id=x.batch_id
 WHERE x.posting_id=posting ORDER BY x.file_ordinal,priority.n DESC LOOP
  count_files:=count_files+1;
  IF d.metadata IS DISTINCT FROM header.files->(d.file_ordinal-1) THEN RAISE EXCEPTION 'ATTACHMENT_METADATA_BINDING_MISMATCH'; END IF;
  SELECT * INTO a FROM attachment.attempt WHERE document_id=d.document_id;
  IF d.disposition='PLANNED' AND (a.attempt_id IS NULL OR a.finished_at IS NULL) THEN RAISE EXCEPTION 'POSTING_DOWNLOAD_INCOMPLETE'; END IF;
  SELECT * INTO p FROM attachment.processor_document WHERE batch_id=id AND attempt_id=a.attempt_id;
  IF p.state IN ('PLANNED','RUNNING') THEN RAISE EXCEPTION 'POSTING_PARSE_INCOMPLETE'; END IF;
  IF p.parse_id IS NOT NULL AND (p.raw_hash IS DISTINCT FROM a.raw_hash OR p.result_hash IS DISTINCT FROM attachment.hash(p.result::text))
  THEN RAISE EXCEPTION 'PROCESSOR_RESULT_CHANGED'; END IF;
  field:=NULL;
  IF p.state='PARSED' THEN
   field:='attachment_'||d.file_ordinal||'_'||(d.metadata->>'recrutAtchFileNo');
   data:=data||jsonb_build_object(field,p.result->>'markdown');
   fields:=fields||jsonb_build_object(field,jsonb_build_object('file_id',d.metadata->>'recrutAtchFileNo',
    'file_ordinal',d.file_ordinal,'name',d.metadata->>'atchFileNm','role',d.metadata->>'atchFileType',
    'raw_hash',p.raw_hash,'parser_version',p.result->>'parser_version','parser_revision',p.result->>'parser_revision',
    'text_hash',p.result->>'text_hash','separator',E'\n\n','offset_unit','unicode-codepoint-zero-half-open',
    'sections',p.result->'sections','warnings',p.result->'warnings')||
    CASE WHEN p.result#>>'{structure,format}'='zip' THEN jsonb_build_object('archive_members',
     (SELECT jsonb_agg(m-ARRAY['structure','semantic','normalization'] ORDER BY (m->>'ordinal')::integer)
      FROM jsonb_array_elements(p.result#>'{structure,members}') m)) ELSE '{}'::jsonb END);
  END IF;
  descriptor:=jsonb_build_object('file_ordinal',d.file_ordinal,'metadata',d.metadata,'disposition',d.disposition,
   'outcome',coalesce(p.state,a.state,d.disposition),'issue',a.issue,'raw_hash',a.raw_hash,'field',field,
   'original_outcome',coalesce(a.state,d.disposition),'processor_state',coalesce(p.state,'NOT_PREPARED'),
   'processor_issue',p.issue,'text_source','DOCUMENT_PROCESSOR');
  documents:=documents||jsonb_build_array(descriptor);
  bindings:=bindings||jsonb_build_array(jsonb_build_object('file_ordinal',d.file_ordinal,'document_id',d.document_id,
   'batch_id',d.batch_id,'attempt_id',a.attempt_id,'raw_path',a.raw_path,'raw_hash',a.raw_hash,
   'field',field,'processor_parse_id',p.parse_id,'processor_result_hash',p.result_hash,'sections',coalesce(p.result->'sections','[]')));
 END LOOP;
 IF count_files<>jsonb_array_length(header.files) THEN RAISE EXCEPTION 'ATTACHMENT_INPUT_COVERAGE_MISMATCH'; END IF;
 data:=data||jsonb_build_object('_input',jsonb_build_object('contract','attachment-input-v2','fields',fields,'documents',documents));
 RETURN jsonb_build_object('source_data',data,'manifest',jsonb_build_object('contract','document-processor-input-v2',
  'job_run_id',jobs,'posting_id',posting,'inline_hash',attachment.hash(inline::text),
  'source_document_id',header.source_document_id,'source_locator',header.source_locator,'source_hash',header.source_hash,
  'attachment_batch_ids',to_jsonb(b.attachment_batch_ids),'processor_batch_id',id,'documents',bindings));
END $$;
CREATE OR REPLACE FUNCTION attachment.prepare_processor_inputs(jobs text,id text,postings text,cap integer,dataset text,ncs text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE ids text[];bundles text[]:='{}';p text;v jsonb;bid text;b text; BEGIN
 PERFORM retention.gate(); PERFORM attachment.verify_processor(id);
 FOR b IN SELECT unnest(attachment_batch_ids) FROM attachment.processor_batch WHERE batch_id=id LOOP
  PERFORM attachment.check_source(b);PERFORM attachment.verify_batch(b);
 END LOOP;
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_INPUT_POSTING_CAP'; END IF;
 IF coalesce(postings,'')='' THEN SELECT array_agg(posting_id ORDER BY posting_id) INTO ids FROM ingestion.job_posting WHERE run_id=jobs;
 ELSE ids:=string_to_array(postings,'|'); END IF;
 IF cardinality(ids) IS NULL OR cardinality(ids) NOT BETWEEN 1 AND cap OR cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x)
 THEN RAISE EXCEPTION 'INVALID_OR_EXCESSIVE_INPUT_POSTING_SELECTION'; END IF;
 FOREACH p IN ARRAY ids LOOP
  v:=attachment.build_processor_input_v2(jobs,p,id);bid:=attachment.hash(v::text);
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
 WHEN 'document-processor-input-v2' THEN v:=attachment.build_processor_input_v2(b.job_run_id,b.posting_id,b.manifest->>'processor_batch_id');
 ELSE RAISE EXCEPTION 'UNKNOWN_ATTACHMENT_INPUT_CONTRACT'; END CASE;
 IF b.bundle_id IS DISTINCT FROM attachment.hash(v::text) OR b.source_data IS DISTINCT FROM v->'source_data'
 OR b.manifest IS DISTINCT FROM v->'manifest' OR b.source_hash IS DISTINCT FROM attachment.hash(b.source_data::text)
 THEN RAISE EXCEPTION 'IMMUTABLE_INPUT_BUNDLE_CHANGED'; END IF;
END $$;
COMMIT;
