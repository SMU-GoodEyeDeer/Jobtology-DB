-- Explicit v2 input selection; v1 bundles retain their original reconstruction.
BEGIN;
SELECT retention.gate();
CREATE OR REPLACE FUNCTION attachment.hwpx_layout(id text) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE s attachment.hwpx_structure;blocks jsonb;tables jsonb;cells jsonb;entries jsonb;body text; BEGIN
 SELECT * INTO STRICT s FROM attachment.hwpx_structure WHERE structure_id=id;
 IF s.state<>'VERIFIED' OR s.body_hash IS DISTINCT FROM attachment.hash(s.body_text)
 THEN RAISE EXCEPTION 'VERIFIED_HWPX_TEXT_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM attachment.hwpx_entry WHERE structure_id=id AND
  (raw_hash<>encode(sha256(raw_bytes),'hex') OR byte_length<>octet_length(raw_bytes))) OR
  EXISTS(SELECT 1 FROM attachment.hwpx_block WHERE structure_id=id AND content_hash<>attachment.hash(content))
 THEN RAISE EXCEPTION 'HWPX_STRUCTURE_CHANGED'; END IF;
 SELECT string_agg(content,E'\n' ORDER BY section_no,block_no),jsonb_agg(jsonb_build_object(
  'section_no',section_no,'entry_name',entry_name,'block_no',block_no,'paragraph_no',paragraph_no,
  'table_no',table_no,'cell_no',cell_no,'context_role',context_role,'first_event',first_event,'last_event',last_event,
  'locator_kind','hwpx_block','locator','zip:'||entry_name||'#block:'||block_no,
  'start',start_offset,'end',start_offset+length(content),'content_hash',content_hash) ORDER BY section_no,block_no)
 INTO body,blocks FROM (SELECT b.*,e.section_no,coalesce(sum(length(b.content)+1) OVER(ORDER BY e.section_no,b.block_no
  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)::integer AS start_offset
  FROM attachment.hwpx_entries(id) e JOIN attachment.hwpx_block b ON b.structure_id=id AND b.entry_name=e.entry_name
  WHERE length(btrim(b.content,E' \t\r\n'||U&'\3000\00a0'))>0) a;
 IF body IS DISTINCT FROM s.body_text THEN RAISE EXCEPTION 'HWPX_BODY_CHANGED'; END IF;
 SELECT coalesce(jsonb_agg((to_jsonb(t)-'structure_id')||jsonb_build_object('section_no',e.section_no) ORDER BY e.section_no,t.table_no),'[]')
 INTO tables FROM attachment.hwpx_table t JOIN attachment.hwpx_entries(id) e USING(entry_name) WHERE t.structure_id=id;
 SELECT coalesce(jsonb_agg((to_jsonb(c)-'structure_id')||jsonb_build_object('section_no',e.section_no) ORDER BY e.section_no,c.cell_no),'[]')
 INTO cells FROM attachment.hwpx_cell c JOIN attachment.hwpx_entries(id) e USING(entry_name) WHERE c.structure_id=id;
 SELECT jsonb_agg(jsonb_build_object('entry_name',entry_name,'raw_hash',raw_hash,'byte_length',byte_length) ORDER BY entry_name)
 INTO entries FROM attachment.hwpx_entry WHERE structure_id=id;
 RETURN jsonb_build_object('sections',blocks,'tables',tables,'cells',cells,'entries',entries);
END $$;
CREATE OR REPLACE FUNCTION attachment.build_structured_input(jobs text,posting text,batches text[],structures text[]) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v jsonb;data jsonb;manifest jsonb;fields jsonb;documents jsonb:='[]';bindings jsonb:='[]';doc jsonb;binding jsonb;
 b text;d attachment.document;s attachment.hwpx_structure;layout jsonb;field text;old_field text;descriptor jsonb; BEGIN
 IF cardinality(structures) IS NULL OR cardinality(structures) NOT BETWEEN 1 AND 100 OR
  cardinality(structures)<>(SELECT count(DISTINCT x) FROM unnest(structures) x) THEN RAISE EXCEPTION 'EXACT_HWPX_BATCHES_REQUIRED'; END IF;
 FOREACH b IN ARRAY structures LOOP
  IF NOT EXISTS(SELECT 1 FROM attachment.hwpx_batch WHERE batch_id=b AND job_run_id=jobs AND attachment_batch_ids=batches)
  THEN RAISE EXCEPTION 'HWPX_INPUT_SNAPSHOT_MISMATCH'; END IF;
  PERFORM attachment.verify_hwpx_batch(b);
 END LOOP;
 v:=attachment.build_input_bundle(jobs,posting,batches);data:=v->'source_data';manifest:=v->'manifest';fields:=data#>'{_input,fields}';
 FOR doc IN SELECT value FROM jsonb_array_elements(data#>'{_input,documents}') LOOP
  SELECT value INTO STRICT binding FROM jsonb_array_elements(manifest->'documents') WHERE value->'file_ordinal'=doc->'file_ordinal';
  SELECT * INTO STRICT d FROM attachment.document WHERE document_id=binding->>'document_id';
  IF d.extension='hwpx' AND d.disposition='PLANNED' THEN
   old_field:=doc->>'field';field:=NULL;layout:=NULL;
   IF old_field IS NOT NULL THEN data:=data-old_field;fields:=fields-old_field; END IF;
   SELECT h.* INTO s FROM attachment.hwpx_structure h JOIN unnest(structures) WITH ORDINALITY b(id,priority) ON b.id=h.batch_id
    WHERE h.attempt_id=binding->>'attempt_id' ORDER BY b.priority DESC LIMIT 1;
   IF s.state='VERIFIED' THEN
    IF s.raw_hash IS DISTINCT FROM binding->>'raw_hash' THEN RAISE EXCEPTION 'HWPX_INPUT_BYTES_MISMATCH'; END IF;
    layout:=attachment.hwpx_layout(s.structure_id);field:='attachment_'||d.file_ordinal||'_'||(d.metadata->>'recrutAtchFileNo');
    data:=data||jsonb_build_object(field,s.body_text);
    descriptor:=jsonb_build_object('file_id',d.metadata->>'recrutAtchFileNo','file_ordinal',d.file_ordinal,
     'name',d.metadata->>'atchFileNm','role',d.metadata->>'atchFileType','raw_hash',s.raw_hash,
     'parser_version',s.parser_version,'text_hash',s.body_hash,'separator',E'\n',
     'offset_unit','unicode-codepoint-zero-half-open','sections',layout->'sections',
     'tables',layout->'tables','cells',layout->'cells','structure_issues',s.issues);
    fields:=fields||jsonb_build_object(field,descriptor);
   END IF;
   doc:=doc||jsonb_build_object('field',field,'text_source','HWPX_STRUCTURE',
    'structure_state',coalesce(s.state,'NOT_PREPARED'),'structure_issues',coalesce(s.issues,'[]'::jsonb));
   binding:=binding||jsonb_build_object('field',field,'sections',coalesce(layout->'sections','[]'::jsonb),
    'original_parse_sections',binding->'sections','structure_id',s.structure_id,'structure_batch_id',s.batch_id,
    'structure_entries',layout->'entries','structure_layout_hash',attachment.hash(layout::text));
  END IF;
  documents:=documents||jsonb_build_array(doc);bindings:=bindings||jsonb_build_array(binding);
 END LOOP;
 data:=jsonb_set(data,'{_input}',jsonb_build_object('contract','attachment-input-v2','fields',fields,'documents',documents));
 manifest:=manifest||jsonb_build_object('contract','attachment-input-v2','hwpx_batch_ids',to_jsonb(structures),'documents',bindings);
 RETURN jsonb_build_object('source_data',data,'manifest',manifest);
END $$;
CREATE OR REPLACE FUNCTION attachment.prepare_structured_input(jobs text,posting text,batches text[],structures text[]) RETURNS text
LANGUAGE plpgsql AS $$ DECLARE v jsonb;id text; BEGIN
 PERFORM retention.gate();
 v:=attachment.build_structured_input(jobs,posting,batches,structures);id:=attachment.hash(v::text);
 INSERT INTO enrichment.input_bundle(bundle_id,job_run_id,posting_id,source_data,source_hash,manifest)
 VALUES(id,jobs,posting,v->'source_data',attachment.hash((v->'source_data')::text),v->'manifest') ON CONFLICT DO NOTHING;
 RETURN id;
END $$;
CREATE OR REPLACE FUNCTION attachment.verify_input_bundle(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b record;v jsonb;batches text[];structures text[]; BEGIN
 SELECT * INTO STRICT b FROM enrichment.input_bundle WHERE bundle_id=id;
 SELECT array_agg(x ORDER BY n) INTO batches FROM jsonb_array_elements_text(b.manifest->'attachment_batch_ids') WITH ORDINALITY a(x,n);
 IF b.manifest->>'contract'='attachment-input-v1' THEN v:=attachment.build_input_bundle(b.job_run_id,b.posting_id,batches);
 ELSIF b.manifest->>'contract'='attachment-input-v2' THEN
  SELECT array_agg(x ORDER BY n) INTO structures FROM jsonb_array_elements_text(b.manifest->'hwpx_batch_ids') WITH ORDINALITY a(x,n);
  v:=attachment.build_structured_input(b.job_run_id,b.posting_id,batches,structures);
 ELSE RAISE EXCEPTION 'UNKNOWN_ATTACHMENT_INPUT_CONTRACT'; END IF;
 IF b.bundle_id IS DISTINCT FROM attachment.hash(v::text) OR b.source_data IS DISTINCT FROM v->'source_data'
  OR b.manifest IS DISTINCT FROM v->'manifest' OR b.source_hash IS DISTINCT FROM attachment.hash(b.source_data::text)
 THEN RAISE EXCEPTION 'IMMUTABLE_INPUT_BUNDLE_CHANGED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.prepare_structured_inputs(jobs text,batch_ids text,structure_ids text,posting_ids text,cap integer,dataset text,ncs text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE ids text[];batches text[]:=string_to_array(batch_ids,'|');structures text[]:=string_to_array(structure_ids,'|');bundles text[]:='{}';p text; BEGIN
 PERFORM retention.gate();
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_INPUT_POSTING_CAP'; END IF;
 IF coalesce(posting_ids,'')='' THEN SELECT array_agg(posting_id ORDER BY posting_id) INTO ids FROM ingestion.job_posting WHERE run_id=jobs;
 ELSE ids:=string_to_array(posting_ids,'|'); END IF;
 IF cardinality(ids) IS NULL OR cardinality(ids) NOT BETWEEN 1 AND cap OR
  cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x) OR EXISTS(SELECT 1 FROM unnest(ids) x WHERE x !~ '^[0-9]+$')
 THEN RAISE EXCEPTION 'INVALID_OR_EXCESSIVE_INPUT_POSTING_SELECTION'; END IF;
 FOREACH p IN ARRAY ids LOOP bundles:=array_append(bundles,attachment.prepare_structured_input(jobs,p,batches,structures)); END LOOP;
 IF coalesce(dataset,'')<>'' THEN PERFORM enrichment.prepare_input_dataset(dataset,ncs,bundles); END IF;
 RETURN jsonb_build_object('bundle_ids',array_to_string(bundles,'|'),'postings',cardinality(ids),'dataset_id',nullif(dataset,''),
  'total_input_chars',(SELECT sum(length(source_data::text)) FROM enrichment.input_bundle WHERE bundle_id=ANY(bundles)));
END $$;
COMMIT;
