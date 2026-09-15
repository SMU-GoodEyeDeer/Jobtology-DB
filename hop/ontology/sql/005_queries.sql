-- Versioned, read-only release queries. They neither accept claims nor activate releases.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.read_release_v1(choice text,preview boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE id text; used_pointer boolean; r ontology.corpus_release%ROWTYPE;
BEGIN
 IF preview IS NULL THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_READ_MODE'; END IF;
 id:=nullif(btrim(choice),'');used_pointer:=id IS NULL;
 IF id IS NULL THEN
  SELECT release_id INTO id FROM ontology.active_release WHERE singleton;
  IF id IS NULL THEN RAISE EXCEPTION 'NO_ACTIVE_ONTOLOGY_RELEASE'; END IF;
 END IF;
 SELECT * INTO r FROM ontology.corpus_release WHERE release_id=id;
 IF NOT FOUND THEN RAISE EXCEPTION 'ONTOLOGY_RELEASE_NOT_FOUND'; END IF;
 IF r.state='REVOKED' THEN RAISE EXCEPTION 'CORPUS_RELEASE_REVOKED'; END IF;
 IF r.state='FAILED' THEN RAISE EXCEPTION 'ONTOLOGY_RELEASE_FAILED'; END IF;
 IF NOT preview AND ((used_pointer AND r.state<>'ACTIVE') OR
  (r.state='ACTIVE' AND NOT EXISTS(SELECT 1 FROM ontology.active_release a
   JOIN ontology.activation_event e ON e.event_id=a.event_id AND e.release_id=a.release_id
   WHERE a.singleton AND a.release_id=id)))
 THEN RAISE EXCEPTION 'ONTOLOGY_ACTIVE_POINTER_MISMATCH'; END IF;
 IF NOT preview AND (r.state NOT IN ('ACTIVE','SUPERSEDED') OR r.manifest IS NULL OR
  r.manifest_hash IS DISTINCT FROM ontology.hash(r.manifest) OR r.graph_verified_at IS NULL OR
  NOT EXISTS(SELECT 1 FROM ontology.activation_event e WHERE e.release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.publication_issue i WHERE i.release_id=id))
 THEN RAISE EXCEPTION 'ONTOLOGY_RELEASE_NOT_PUBLISHED'; END IF;
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION ontology.read_context_v1(id text,preview boolean)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract_version','hop-ontology-read-v1','release_id',r.release_id,
  'read_mode',CASE WHEN preview THEN 'PREVIEW' ELSE 'PUBLISHED' END,'release_state',r.state,
  'manifest_hash',r.manifest_hash,'data_as_of',r.data_as_of,'pipeline_version',r.pipeline_version,
  'methodology_version',r.methodology_version,'graph_verified_at',r.graph_verified_at,
  'review_frozen_at',f.frozen_at)
 FROM ontology.corpus_release r LEFT JOIN ontology.review_freeze f USING(release_id) WHERE r.release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.query_summary_v1(release_choice text DEFAULT NULL,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; result jsonb;
BEGIN
 id:=ontology.read_release_v1(release_choice,preview);
 WITH postings AS MATERIALIZED (
  SELECT m.entity_id,coalesce(p.outcome,'SELECTION_PENDING') AS outcome,p.extraction
  FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id)
  LEFT JOIN ontology.posting_selection p ON p.release_id=m.release_id AND p.entity_id=m.entity_id
  WHERE m.release_id=id AND v.kind='jobPosting'
 ), counts AS (SELECT count(*) AS total,count(*) FILTER(WHERE outcome='ACCEPTED') AS accepted FROM postings)
 SELECT ontology.read_context_v1(id,preview)||jsonb_build_object(
  'sources',coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY source_id) FROM ontology.source_pin p WHERE release_id=id),'[]'),
  'source_coverage',coalesce((SELECT jsonb_agg(to_jsonb(c) ORDER BY source_id) FROM ontology.source_coverage c WHERE release_id=id),'[]'),
  'entity_counts',coalesce((SELECT jsonb_object_agg(kind,n) FROM (
   SELECT v.kind,count(*) n FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id=id GROUP BY v.kind) x),'{}'),
  'posting_review',jsonb_build_object('denominator',total,'accepted_numerator',accepted,
   'accepted_fraction',accepted::numeric/nullif(total,0),
   'outcomes',coalesce((SELECT jsonb_object_agg(outcome,n) FROM (SELECT outcome,count(*) n FROM postings GROUP BY outcome) x),'{}'),
   'meaning','Review completion among release-selected postings; not capability coverage, extraction accuracy or occupational demand.'),
  'accepted_claim_counts',coalesce((SELECT jsonb_object_agg(kind,n) FROM (
   SELECT c.kind,count(*) n FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id) WHERE m.release_id=id GROUP BY c.kind) x),'{}'),
  'link_outcomes',coalesce((SELECT jsonb_object_agg(outcome,n) FROM (
   SELECT outcome,count(*) n FROM ontology.link_selection WHERE release_id=id GROUP BY outcome) x),'{}'),
  'accepted_mappings',(SELECT count(*) FROM ontology.release_mapping WHERE release_id=id),
  'publication_issues',coalesce((SELECT jsonb_agg(issue ORDER BY issue) FROM (
   SELECT DISTINCT issue FROM ontology.publication_issue WHERE release_id=id) x),'[]')) INTO result FROM counts;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.query_entities_v1(release_choice text DEFAULT NULL,entity_kind text DEFAULT NULL,
 page_size integer DEFAULT 100,cursor_value text DEFAULT NULL,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; selected_kind text; selected_hash text; cursor_data jsonb; last_id text; rows jsonb; next_cursor text;
BEGIN
 id:=ontology.read_release_v1(release_choice,preview);selected_kind:=nullif(entity_kind,'');
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_PAGE_SIZE'; END IF;
 IF selected_kind IS NOT NULL AND selected_kind NOT IN ('organization','jobPosting','occupation','ncsClass','ncsCompetency','ncsUnitFamily',
  'qualification','examSession','careerRank','conceptScheme','skill','majorConcept','course','courseInstance','actionTemplate','place')
 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_ENTITY_KIND'; END IF;
 SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(m.entity_id,m.revision_id) ORDER BY m.entity_id COLLATE "C"),'[]'))
 INTO selected_hash FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id)
 WHERE m.release_id=id AND (selected_kind IS NULL OR v.kind=selected_kind);
 IF nullif(cursor_value,'') IS NOT NULL THEN
  BEGIN
   IF length(cursor_value)>4096 THEN RAISE EXCEPTION 'CURSOR_TOO_LONG'; END IF;
   cursor_data:=convert_from(decode(cursor_value,'base64'),'UTF8')::jsonb;
   IF jsonb_typeof(cursor_data) IS DISTINCT FROM 'object' OR jsonb_typeof(cursor_data->'last_id') IS DISTINCT FROM 'string'
    OR nullif(cursor_data->>'last_id','') IS NULL OR
    cursor_data-'last_id' IS DISTINCT FROM jsonb_build_object('contract','hop-ontology-cursor-v1',
     'release_id',id,'entity_kind',selected_kind,'selection_hash',selected_hash)
   THEN RAISE EXCEPTION 'CURSOR_SCOPE_MISMATCH'; END IF;
   last_id:=cursor_data->>'last_id';
  EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_CURSOR'; END;
 END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY entity_id COLLATE "C"),'[]') INTO rows FROM (
  SELECT m.entity_id,m.revision_id,v.kind,v.name,v.payload_hash,v.schema_version
  FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id)
  WHERE m.release_id=id AND (selected_kind IS NULL OR v.kind=selected_kind) AND (last_id IS NULL OR m.entity_id COLLATE "C">last_id COLLATE "C")
  ORDER BY m.entity_id COLLATE "C" LIMIT page_size+1) x;
 IF jsonb_array_length(rows)>page_size THEN
  rows:=rows-page_size;
  next_cursor:=replace(encode(convert_to(jsonb_build_object('contract','hop-ontology-cursor-v1','release_id',id,
   'entity_kind',selected_kind,'selection_hash',selected_hash,'last_id',rows->-1->>'entity_id')::text,'UTF8'),'base64'),E'\n','');
 END IF;
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('entity_kind',selected_kind,'items',rows,'next_cursor',next_cursor);
END $$;

CREATE OR REPLACE FUNCTION ontology.query_evidence_v1(release_choice text,evidence_choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; result jsonb;
BEGIN
 id:=ontology.read_release_v1(release_choice,preview);
 SELECT ontology.read_context_v1(id,preview)||jsonb_build_object('evidence',to_jsonb(e),
  'artifact',jsonb_build_object('artifact_id',a.artifact_id,'posting_entity_id',a.posting_id,'source_field',a.source_field,
   'input_sha256',a.input_sha256,'normalized_text_sha256',a.text_sha256,'normalization_version',a.normalization_version),
  'source_records',coalesce((SELECT jsonb_agg(jsonb_build_object('record_id',i.record_id,'source_id',i.source_id,
   'run_id',i.run_id,'source_record_id',i.source_record_id,'document_id',i.document_id,'locator',i.locator,
   'raw_sha256',i.raw_sha256,'source_field',s.source_field,'field_lineage',i.field_lineage,
   'retrieved_at',d.retrieved_at) ORDER BY i.record_id,s.source_field)
   FROM ontology.artifact_source s JOIN ontology.input_record i USING(release_id,record_id)
   JOIN ingestion.document d ON d.run_id=i.run_id AND d.document_id=i.document_id
   WHERE s.release_id=id AND s.artifact_id=a.artifact_id),'[]'),
  'source_url',(SELECT v.payload->>'source_url' FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id)
   WHERE m.release_id=id AND m.entity_id=a.posting_id),
  'document',(SELECT jsonb_build_object('bundle_id',d.bundle_id,'file_id',d.descriptor->'file_id',
   'name',d.descriptor->'name','role',d.descriptor->'role','source_url',ad.source_url,
   'raw_sha256',d.binding->'raw_hash','parser_version',d.descriptor->'parser_version',
   'sections',coalesce((SELECT jsonb_agg(to_jsonb(s) ORDER BY section_index) FROM ontology.document_section s
    WHERE s.release_id=id AND s.artifact_id=a.artifact_id AND s.normalized_start<e.end_offset AND s.normalized_end>e.start_offset),'[]'))
   FROM ontology.artifact_document d JOIN attachment.attempt t USING(attempt_id)
   JOIN attachment.document ad ON ad.document_id=t.document_id WHERE d.release_id=id AND d.artifact_id=a.artifact_id))
 INTO result FROM ontology.evidence_span e JOIN ontology.text_artifact a USING(artifact_id)
 WHERE e.evidence_id=evidence_choice AND EXISTS(SELECT 1 FROM ontology.release_evidence r WHERE r.release_id=id AND r.evidence_id=e.evidence_id);
 IF result IS NULL THEN RAISE EXCEPTION 'ONTOLOGY_EVIDENCE_NOT_IN_RELEASE'; END IF;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.query_entity_v1(release_choice text,entity_choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; v ontology.revision%ROWTYPE; result jsonb; p ontology.posting_selection%ROWTYPE;
BEGIN
 id:=ontology.read_release_v1(release_choice,preview);
 SELECT r.* INTO v FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
 WHERE m.release_id=id AND m.entity_id=entity_choice;
 IF NOT FOUND THEN RAISE EXCEPTION 'ONTOLOGY_ENTITY_NOT_IN_RELEASE'; END IF;
 result:=ontology.read_context_v1(id,preview)||jsonb_build_object('entity',to_jsonb(v)-'created_at',
  'source_support',coalesce((SELECT jsonb_agg(jsonb_build_object('record_id',s.record_id,'source_fields',s.fields,
   'source_id',i.source_id,'run_id',i.run_id,'source_record_id',i.source_record_id,'document_id',i.document_id,
   'locator',i.locator,'raw_sha256',i.raw_sha256,'normalized_hash',i.normalized_hash,'field_lineage',i.field_lineage) ORDER BY s.record_id)
   FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id)
   WHERE s.release_id=id AND s.entity_id=entity_choice),'[]'),
  'relations',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY relation_id) FROM (
   SELECT r.relation_id,r.subject_id,r.predicate,r.object_id,r.qualifiers,r.assertion_kind,r.acceptance_policy,
    sv.revision_id AS subject_revision_id,sv.name AS subject_name,ov.revision_id AS object_revision_id,ov.name AS object_name,
    jsonb_agg(jsonb_build_object('record_id',m.record_id,'source_fields',m.source_fields) ORDER BY m.record_id) AS support
   FROM ontology.release_relation m JOIN ontology.source_relation r USING(relation_id)
   JOIN ontology.release_revision sm ON sm.release_id=m.release_id AND sm.entity_id=r.subject_id
   JOIN ontology.revision sv ON sv.revision_id=sm.revision_id
   JOIN ontology.release_revision om ON om.release_id=m.release_id AND om.entity_id=r.object_id
   JOIN ontology.revision ov ON ov.revision_id=om.revision_id
   WHERE m.release_id=id AND entity_choice IN (r.subject_id,r.object_id)
   GROUP BY r.relation_id,sv.revision_id,ov.revision_id) x),'[]'));
 IF v.kind<>'jobPosting' THEN RETURN result; END IF;
 SELECT * INTO p FROM ontology.posting_selection WHERE release_id=id AND entity_id=entity_choice;
 result:=result||jsonb_build_object('extraction',jsonb_build_object('outcome',coalesce(p.outcome,'SELECTION_PENDING'),
  'source_hash',p.source_hash,'revision_id',p.extraction_revision_id,'decision_id',p.decision_id,
  'review',p.provenance->'review','issues',p.provenance->'issues','duties_status',p.extraction->>'duties_status',
  'input_scope',CASE WHEN p.release_id IS NULL THEN 'UNSELECTED' ELSE coalesce(p.source_data#>>'{_input,contract}','inline-fields') END),
  'positions',coalesce((SELECT jsonb_agg(to_jsonb(c)||jsonb_build_object('evidence_id',e.evidence_id) ORDER BY c.local_id)
   FROM ontology.release_position m JOIN ontology.position_claim c USING(position_id) LEFT JOIN ontology.position_evidence e USING(position_id)
   WHERE m.release_id=id AND m.entity_id=entity_choice),'[]'),
  'claims',coalesce((SELECT jsonb_agg(to_jsonb(c)||jsonb_build_object(
   'positions',coalesce((SELECT jsonb_agg(x.position_id ORDER BY x.position_id) FROM ontology.claim_position x
    JOIN ontology.release_position rp USING(position_id) WHERE x.claim_id=c.claim_id AND rp.release_id=id AND rp.entity_id=entity_choice),'[]'),
   'evidence',coalesce((SELECT jsonb_agg(to_jsonb(e) ORDER BY part_index) FROM ontology.claim_evidence e WHERE e.claim_id=c.claim_id),'[]'),
   'conditions',coalesce((SELECT jsonb_agg(to_jsonb(n)||jsonb_build_object(
    'children',coalesce((SELECT jsonb_agg(child_index ORDER BY ordinal) FROM ontology.condition_child x WHERE x.claim_id=n.claim_id AND x.parent_index=n.node_index),'[]'),
    'evidence',coalesce((SELECT jsonb_agg(to_jsonb(e) ORDER BY part_index) FROM ontology.condition_evidence e WHERE e.claim_id=n.claim_id AND e.node_index=n.node_index),'[]'))
    ORDER BY node_index) FROM ontology.condition_node n WHERE n.claim_id=c.claim_id),'[]')) ORDER BY c.kind,c.ordinal)
   FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id) WHERE m.release_id=id AND m.entity_id=entity_choice),'[]'),
  'link_decisions',coalesce((SELECT jsonb_agg(jsonb_build_object('candidate_id',l.candidate_id,'outcome',l.outcome,
   'decision_id',l.decision_id,'review',l.review) ORDER BY l.candidate_id) FROM ontology.link_selection l
   WHERE l.release_id=id AND l.entity_id=entity_choice),'[]'),
  'mappings',coalesce((SELECT jsonb_agg(to_jsonb(c)||jsonb_build_object('candidate_id',m.candidate_id,
   'target_entity_id',t.entity_id,'target_name',t.name,'target_payload',t.payload) ORDER BY c.mapping_id)
   FROM ontology.release_mapping m JOIN ontology.mapping_claim c USING(mapping_id)
   JOIN ontology.release_claim rc ON rc.release_id=m.release_id AND rc.claim_id=c.duty_claim_id
   JOIN ontology.release_revision rm ON rm.release_id=m.release_id AND rm.revision_id=c.target_revision_id
   JOIN ontology.revision t ON t.revision_id=rm.revision_id WHERE m.release_id=id AND rc.entity_id=entity_choice),'[]'),
  'rule_decisions',coalesce((SELECT jsonb_agg(jsonb_build_object('interpretation_id',s.interpretation_id,
   'requirement_index',s.requirement_index,'outcome',s.outcome,'decision_id',s.decision_id,'review',s.review)
   ORDER BY requirement_index) FROM ontology.rule_selection s WHERE s.release_id=id AND s.entity_id=entity_choice),'[]'),
  'rules',coalesce((SELECT jsonb_agg(to_jsonb(r)||jsonb_build_object('evidence',coalesce((SELECT jsonb_agg(to_jsonb(e)
    ORDER BY node_path,part_index) FROM ontology.rule_evidence e WHERE e.release_id=id AND e.interpretation_id=r.interpretation_id AND e.local_id=r.local_id),'[]'))
   ORDER BY r.claim_id,r.ordinal) FROM ontology.guarded_rule r WHERE r.release_id=id AND r.entity_id=entity_choice),'[]'),
  'interpretation_notice','Reviewed source text and expression trees do not establish resolved capability targets or executable applicant eligibility.');
 RETURN result;
END $$;
COMMENT ON FUNCTION ontology.query_summary_v1(text,boolean) IS 'Distinct release-selected posting review counts. Not a cohort, occupational demand denominator, or capability coverage score.';
COMMENT ON FUNCTION ontology.read_release_v1(text,boolean) IS 'Read gate only. PREVIEW never activates a release. Revoked and failed releases cannot be read, including previews.';
COMMIT;
