-- Immutable attachment-aware source inputs. Historical inline items are unchanged.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.verify_item_input(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE i enrichment.item;b enrichment.input_bundle;j text; BEGIN
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=id;
 SELECT x.* INTO b FROM enrichment.item_input a JOIN enrichment.input_bundle x USING(bundle_id) WHERE a.item_id=id;
 IF NOT FOUND THEN
  IF i.source_data ? '_input' THEN RAISE EXCEPTION 'INPUT_BUNDLE_BINDING_REQUIRED'; END IF;
  RETURN;
 END IF;
 SELECT job_run_id INTO STRICT j FROM enrichment.batch WHERE batch_id=i.batch_id;
 IF b.job_run_id<>j OR b.posting_id<>i.posting_id OR b.source_data IS DISTINCT FROM i.source_data
  OR b.source_hash IS DISTINCT FROM i.source_hash THEN RAISE EXCEPTION 'ITEM_INPUT_BUNDLE_MISMATCH'; END IF;
 PERFORM attachment.verify_input_bundle(b.bundle_id);
END $$;
CREATE OR REPLACE FUNCTION enrichment.prepare_input_dataset(id text,ncs text,ids text[]) RETURNS void LANGUAGE plpgsql AS $$
DECLARE jobs text;n text;b text;expected jsonb;actual jsonb; BEGIN
 PERFORM retention.gate();
 IF id !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$' OR cardinality(ids) IS NULL OR cardinality(ids) NOT BETWEEN 1 AND 1000
  OR cardinality(ids)<>(SELECT count(DISTINCT x) FROM unnest(ids) x) THEN RAISE EXCEPTION 'INVALID_INPUT_DATASET_SELECTION'; END IF;
 FOREACH b IN ARRAY ids LOOP PERFORM attachment.verify_input_bundle(b); END LOOP;
 IF (SELECT count(DISTINCT job_run_id) FROM enrichment.input_bundle WHERE bundle_id=ANY(ids))<>1 OR
  (SELECT count(DISTINCT posting_id) FROM enrichment.input_bundle WHERE bundle_id=ANY(ids))<>cardinality(ids)
 THEN RAISE EXCEPTION 'INPUT_DATASET_REQUIRES_ONE_SNAPSHOT_AND_UNIQUE_POSTINGS'; END IF;
 SELECT min(job_run_id),jsonb_object_agg(posting_id,bundle_id) INTO jobs,expected FROM enrichment.input_bundle WHERE bundle_id=ANY(ids);
 n:=enrichment.resolve_snapshot(ncs,'ncs_competency');
 PERFORM pg_advisory_xact_lock(hashtextextended('llm-dataset:'||id,0));
 IF EXISTS(SELECT 1 FROM enrichment.dataset WHERE dataset_id=id) THEN
  SELECT jsonb_object_agg(posting_id,bundle_id) INTO actual FROM enrichment.test_case_input WHERE dataset_id=id;
  IF actual IS DISTINCT FROM expected OR NOT EXISTS(SELECT 1 FROM enrichment.dataset WHERE dataset_id=id AND job_run_id=jobs AND ncs_run_id=n)
  THEN RAISE EXCEPTION 'DATASET_IS_FROZEN_USE_A_NEW_ID'; END IF;
  RETURN;
 END IF;
 INSERT INTO enrichment.dataset(dataset_id,job_run_id,ncs_run_id,seed,requested_size)
 VALUES(id,jobs,n,'attachment-input-bundles',cardinality(ids));
 INSERT INTO enrichment.test_case(dataset_id,posting_id,source_data,source_hash,stratum,ordinal)
 SELECT id,posting_id,source_data,source_hash,'attachment_review',row_number() OVER(ORDER BY posting_id)
 FROM enrichment.input_bundle WHERE bundle_id=ANY(ids);
 INSERT INTO enrichment.test_case_input SELECT id,posting_id,bundle_id FROM enrichment.input_bundle WHERE bundle_id=ANY(ids);
END $$;
-- Exact passage IDs/text are sufficient for model citations; full offsets and
-- field ownership remain in source_passages_v2 and immutable input evidence.
CREATE OR REPLACE FUNCTION enrichment.model_passages(n jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE WHEN n#>>'{_input,contract}'='attachment-input-v2' THEN
  (SELECT coalesce(jsonb_agg(jsonb_build_object('id',p->'id','text',p->'text') ORDER BY ordinal),'[]')
   FROM jsonb_array_elements(enrichment.source_passages_v2(n)) WITH ORDINALITY a(p,ordinal))
  ELSE enrichment.source_passages_v2(n) END
$$;
-- Compact model-facing layout retains all block spans and table ownership without
-- repeating audit hashes/private lineage in each request. v1 requests are unchanged.
CREATE OR REPLACE FUNCTION enrichment.document_context(n jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE output jsonb:='{}';f record;v jsonb;layout jsonb;part record;sections jsonb; BEGIN
 IF n#>>'{_input,contract}'<>'attachment-input-v2' THEN RETURN n#>'{_input,fields}'; END IF;
 FOR f IN SELECT * FROM jsonb_each(n#>'{_input,fields}') LOOP
  v:=f.value;
  IF v->>'parser_version'='hwpx-xml-structure-v1' THEN
   sections:='{}';
   FOR part IN SELECT DISTINCT x->>'section_no' section_no,x->>'entry_name' entry_name FROM jsonb_array_elements(v->'sections') x LOOP
    sections:=sections||jsonb_build_object(part.section_no,jsonb_build_object('entry',part.entry_name,
     'blocks',(SELECT jsonb_agg(jsonb_build_array(
       1+length(left(n->>f.key,(x->>'start')::integer))-length(replace(left(n->>f.key,(x->>'start')::integer),E'\n','')),
       1+length(left(n->>f.key,(x->>'end')::integer))-length(replace(left(n->>f.key,(x->>'end')::integer),E'\n','')),
       x->'paragraph_no',x->'table_no',x->'cell_no')||
       CASE WHEN x->>'context_role'='body' THEN '[]'::jsonb ELSE jsonb_build_array(x->'context_role') END ORDER BY z)
       FROM jsonb_array_elements(v->'sections') WITH ORDINALITY a(x,z) WHERE x->>'section_no'=part.section_no),
     'tables',(SELECT coalesce(jsonb_agg(jsonb_build_array(x->'table_no',x->'parent_table_no',x->'parent_cell_no',x->'rows',x->'cols') ORDER BY z),'[]')
       FROM jsonb_array_elements(v->'tables') WITH ORDINALITY a(x,z) WHERE x->>'section_no'=part.section_no),
     'cells',(SELECT coalesce(jsonb_agg(jsonb_build_array(x->'cell_no',x->'table_no',x->'row_no',x->'col_no',x->'row_span',x->'col_span',x->'is_header') ORDER BY z),'[]')
       FROM jsonb_array_elements(v->'cells') WITH ORDINALITY a(x,z) WHERE x->>'section_no'=part.section_no)));
   END LOOP;
   layout:=jsonb_build_object('block_columns',jsonb_build_array('first_line','last_line','paragraph','table','cell','role'),
    'block_defaults',jsonb_build_object('role','body'),
    'table_columns',jsonb_build_array('table','parent_table','parent_cell','rows','cols'),
    'cell_columns',jsonb_build_array('cell','table','row','col','row_span','col_span','header'),'sections',sections);
   v:=(v-ARRAY['sections','tables','cells'])||jsonb_build_object('layout',layout);
  END IF;
  output:=output||jsonb_build_object(f.key,v);
 END LOOP;
 RETURN output;
END $$;
COMMENT ON TABLE enrichment.input_bundle IS 'Frozen content plus document/section lineage. Content hashes omit attempt IDs and disk paths to permit identical-content reuse; bundle IDs retain exact source bindings.';
COMMIT;
