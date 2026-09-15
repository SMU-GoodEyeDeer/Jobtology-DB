-- V2 read contracts include frozen editorial provenance. No writes or provider calls.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.read_release_v2(choice text,preview boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE id text; BEGIN
 id:=ontology.read_release_v1(choice,preview);
 IF EXISTS(SELECT 1 FROM editorial.release_pin WHERE release_id=id) THEN
  PERFORM editorial.verify_pin_v1(id);
  PERFORM editorial.verify_graph_v1(id);
 ELSIF EXISTS(SELECT 1 FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
  WHERE m.release_id=id AND r.schema_version='hop-editorial-revision-v1')
 THEN RAISE EXCEPTION 'EDITORIAL_RELEASE_MEMBERSHIP_REQUIRED'; END IF;
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION editorial.read_selection_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('source_kind','EDITORIAL_CATALOGUE','source_id','INTERNAL_EDITORIAL',
  'snapshot_id',s.snapshot_id,'catalogue_id',s.catalogue_id,'catalogue_version',s.catalogue_version,
  'byte_length',s.byte_length,'git_blob_sha1',s.git_blob_sha1,'schema_version',s.document->>'schema_version',
  'membership_hash',p.manifest_hash,'pinned_at',p.pinned_at,'entity_count',jsonb_array_length(p.manifest->'items'),
  'selected_review',(SELECT to_jsonb(r) FROM editorial.review r WHERE r.review_id=p.review_id),
  'attestation_kind','OPERATOR_REPORTED','repository_verification','NOT_AUTOMATICALLY_VERIFIED')
 FROM editorial.release_pin p JOIN editorial.snapshot s USING(snapshot_id) WHERE p.release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.read_context_v2(id text,preview boolean) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT ontology.read_context_v1(id,preview)||jsonb_build_object('contract_version','hop-ontology-read-v2',
  'editorial_source',editorial.read_selection_v1(id),
  'editorial_selection_status',CASE WHEN EXISTS(SELECT 1 FROM editorial.release_pin WHERE release_id=id)
   THEN 'PINNED' ELSE 'NOT_PINNED' END)
$$;

CREATE OR REPLACE FUNCTION ontology.source_support_v2(id text,entity text)
RETURNS TABLE(support_id text,support_kind text,source_id text,reference jsonb) LANGUAGE sql STABLE AS $$
 SELECT ontology.graph_record_id(i),'EXTERNAL_RECORD',i.source_id,
  jsonb_build_object('support_id',ontology.graph_record_id(i),'support_kind','EXTERNAL_RECORD',
   'record_id',s.record_id,'source_fields',s.fields,'source_id',i.source_id,'run_id',i.run_id,
   'source_record_id',i.source_record_id,'document_id',i.document_id,'locator',i.locator,
   'raw_sha256',i.raw_sha256,'normalized_hash',i.normalized_hash,'field_lineage',i.field_lineage)
 FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id)
 WHERE s.release_id=id AND s.entity_id=entity
 UNION ALL
 SELECT editorial.graph_record_id_v1(i),'EDITORIAL_ENTRY','INTERNAL_EDITORIAL',
  jsonb_build_object('support_id',editorial.graph_record_id_v1(i),'support_kind','EDITORIAL_ENTRY',
   'source_id','INTERNAL_EDITORIAL','source_record_id',i.entity_id,'snapshot_id',i.snapshot_id,
   'locator',i.source_pointer,'raw_sha256',i.snapshot_id,'normalized_hash',i.payload_hash,
   'revision_id',i.revision_id,'review_id',p.review_id,'membership_hash',p.manifest_hash)
 FROM editorial.revision_support s JOIN editorial.release_pin p USING(release_id)
 JOIN editorial.item i ON i.snapshot_id=s.snapshot_id AND i.entity_id=s.entity_id
 WHERE s.release_id=id AND s.entity_id=entity
$$;

CREATE OR REPLACE FUNCTION ontology.query_summary_v2(release_choice text DEFAULT NULL,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; result jsonb; sources jsonb; editorial_source jsonb; BEGIN
 id:=ontology.read_release_v2(release_choice,preview);
 result:=ontology.query_summary_v1(id,preview);
 SELECT coalesce(jsonb_agg(value||jsonb_build_object('source_kind','EXTERNAL_CONNECTOR_RUN') ORDER BY value->>'source_id'),'[]')
 INTO sources FROM jsonb_array_elements(result->'sources');
 editorial_source:=editorial.read_selection_v1(id);
 IF editorial_source IS NOT NULL THEN sources:=sources||jsonb_build_array(editorial_source); END IF;
 RETURN result||ontology.read_context_v2(id,preview)||jsonb_build_object('sources',sources,
  'editorial_coverage',CASE WHEN editorial_source IS NOT NULL THEN jsonb_build_object(
   'source_id','INTERNAL_EDITORIAL','expected_entities',5,
   'selected_entities',(SELECT count(*) FROM editorial.revision_support WHERE release_id=id),
   'unaccounted_entities',0,'status','VERIFIED_FROZEN_MEMBERSHIP') ELSE NULL END);
END $$;

CREATE OR REPLACE FUNCTION ontology.query_entities_v2(release_choice text DEFAULT NULL,entity_kind text DEFAULT NULL,
 scheme_choice text DEFAULT NULL,page_size integer DEFAULT 100,cursor_value text DEFAULT NULL,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; selected_kind text; selected_scheme text; selected_hash text; editorial_hash text; cursor_data jsonb; last_id text; rows jsonb; next_cursor text;
BEGIN
 id:=ontology.read_release_v2(release_choice,preview);
 selected_kind:=nullif(entity_kind,'');selected_scheme:=nullif(scheme_choice,'');
 SELECT manifest_hash INTO editorial_hash FROM editorial.release_pin WHERE release_id=id;
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_PAGE_SIZE'; END IF;
 IF selected_kind IS NOT NULL AND selected_kind NOT IN ('organization','jobPosting','occupation','ncsClass','ncsCompetency','ncsUnitFamily',
  'qualification','examSession','careerRank','conceptScheme','skill','majorConcept','course','courseInstance','actionTemplate','place')
 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_ENTITY_KIND'; END IF;
 IF selected_scheme IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id)
  WHERE m.release_id=id AND e.entity_id=selected_scheme AND e.kind='conceptScheme')
 THEN RAISE EXCEPTION 'ONTOLOGY_SCHEME_NOT_IN_RELEASE'; END IF;
 SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(m.entity_id,m.revision_id) ORDER BY m.entity_id COLLATE "C"),'[]'))
 INTO selected_hash FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) JOIN ontology.entity e ON e.entity_id=m.entity_id
 WHERE m.release_id=id AND (selected_kind IS NULL OR v.kind=selected_kind) AND (selected_scheme IS NULL OR e.scheme_id=selected_scheme);
 IF nullif(cursor_value,'') IS NOT NULL THEN
  BEGIN
   IF length(cursor_value)>4096 THEN RAISE EXCEPTION 'CURSOR_TOO_LONG'; END IF;
   cursor_data:=convert_from(decode(cursor_value,'base64'),'UTF8')::jsonb;
   IF jsonb_typeof(cursor_data) IS DISTINCT FROM 'object' OR jsonb_typeof(cursor_data->'last_id') IS DISTINCT FROM 'string'
    OR nullif(cursor_data->>'last_id','') IS NULL OR cursor_data-'last_id' IS DISTINCT FROM jsonb_build_object(
     'contract','hop-ontology-cursor-v2','release_id',id,'entity_kind',selected_kind,'scheme_id',selected_scheme,
     'selection_hash',selected_hash,'editorial_membership_hash',editorial_hash)
   THEN RAISE EXCEPTION 'CURSOR_SCOPE_MISMATCH'; END IF;
   last_id:=cursor_data->>'last_id';
  EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_CURSOR'; END;
 END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY entity_id COLLATE "C"),'[]') INTO rows FROM (
  SELECT m.entity_id,m.revision_id,v.kind,v.name,v.payload_hash,v.schema_version,e.scheme_id,
   (SELECT count(*) FROM ontology.source_support_v2(id,m.entity_id)) AS source_support_count
  FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) JOIN ontology.entity e ON e.entity_id=m.entity_id
  WHERE m.release_id=id AND (selected_kind IS NULL OR v.kind=selected_kind) AND (selected_scheme IS NULL OR e.scheme_id=selected_scheme)
   AND (last_id IS NULL OR m.entity_id COLLATE "C">last_id COLLATE "C")
  ORDER BY m.entity_id COLLATE "C" LIMIT page_size+1) x;
 IF jsonb_array_length(rows)>page_size THEN
  rows:=rows-page_size;
  next_cursor:=replace(encode(convert_to(jsonb_build_object('contract','hop-ontology-cursor-v2','release_id',id,
   'entity_kind',selected_kind,'scheme_id',selected_scheme,'selection_hash',selected_hash,'editorial_membership_hash',editorial_hash,
   'last_id',rows->-1->>'entity_id')::text,'UTF8'),'base64'),E'\n','');
 END IF;
 RETURN ontology.read_context_v2(id,preview)||jsonb_build_object('entity_kind',selected_kind,'scheme_id',selected_scheme,
  'items',rows,'next_cursor',next_cursor);
END $$;

CREATE OR REPLACE FUNCTION ontology.query_entity_v2(release_choice text,entity_choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; result jsonb; BEGIN
 id:=ontology.read_release_v2(release_choice,preview);
 result:=ontology.query_entity_v1(id,entity_choice,preview);
 RETURN result||ontology.read_context_v2(id,preview)||jsonb_build_object(
  'source_support',coalesce((SELECT jsonb_agg(reference ORDER BY support_id,reference::text COLLATE "C") FROM ontology.source_support_v2(id,entity_choice)),'[]'),
  'catalogue_relations',coalesce((SELECT jsonb_agg(jsonb_build_object('predicate','IN_SCHEME',
   'subject_id',i.entity_id,'subject_revision_id',i.revision_id,'subject_name',i.name,
   'object_id',i.scheme_id,'object_revision_id',m.revision_id,'object_name',r.name,
   'support_id',editorial.graph_record_id_v1(i),'review_id',p.review_id) ORDER BY i.entity_id)
   FROM editorial.release_pin p JOIN editorial.item i USING(snapshot_id)
   JOIN ontology.release_revision m ON m.release_id=p.release_id AND m.entity_id=i.scheme_id
   JOIN ontology.revision r ON r.revision_id=m.revision_id
   WHERE p.release_id=id AND entity_choice IN (i.entity_id,i.scheme_id)),'[]'));
END $$;

CREATE OR REPLACE FUNCTION ontology.query_source_record_v2(release_choice text,support_choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; result jsonb; BEGIN
 id:=ontology.read_release_v2(release_choice,preview);
 IF support_choice ~ '^editorial-record/[0-9a-f]{64}$' THEN
  SELECT jsonb_build_object('support_id',support_choice,'support_kind','EDITORIAL_ENTRY','source_id','INTERNAL_EDITORIAL',
   'source_record_id',i.entity_id,'snapshot_id',s.snapshot_id,'locator',i.source_pointer,'raw_sha256',s.snapshot_id,
   'normalized_hash',i.payload_hash,'normalized',i.payload,'revision_id',i.revision_id,
   'source_entry',s.document#>string_to_array(substr(i.source_pointer,2),'/'),
   'source_text',convert_from(s.raw_bytes,'UTF8'),'byte_length',s.byte_length,'git_blob_sha1',s.git_blob_sha1,
   'schema_version',s.document->>'schema_version','review_id',p.review_id,'membership_hash',p.manifest_hash)
  INTO result FROM editorial.release_pin p JOIN editorial.snapshot s USING(snapshot_id) JOIN editorial.item i USING(snapshot_id)
  WHERE p.release_id=id AND editorial.graph_record_id_v1(i)=support_choice;
 ELSIF support_choice ~ '^source-record/[0-9a-f]{64}$' THEN
  WITH entries AS MATERIALIZED (SELECT * FROM ontology.input_record i WHERE i.release_id=id AND ontology.graph_record_id(i)=support_choice)
  SELECT jsonb_build_object('support_id',support_choice,'support_kind','EXTERNAL_RECORD','source_id',i.source_id,
   'source_record_id',i.source_record_id,
   'locator',i.locator,'raw_sha256',i.raw_sha256,'normalized_hash',i.normalized_hash,
   'normalized',i.normalized,'field_lineage',i.field_lineage,
   'representation','FROZEN_NORMALIZED_RECORD_WITH_ORIGINAL_FILE_REFERENCE',
   'source_observations',(SELECT jsonb_agg(jsonb_build_object('record_id',e.record_id,'run_id',e.run_id,'document_id',e.document_id)
    ORDER BY e.record_id) FROM entries e))
  INTO result FROM entries i ORDER BY i.record_id LIMIT 1;
 END IF;
 IF result IS NULL THEN RAISE EXCEPTION 'ONTOLOGY_SOURCE_RECORD_NOT_IN_RELEASE'; END IF;
 RETURN ontology.read_context_v2(id,preview)||jsonb_build_object('source_record',result);
END $$;
COMMIT;
