-- Reviewed position-level country/experience/scope. Source payloads stay unchanged.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.cohort_profile_proposal (
 proposal_id text PRIMARY KEY,proposal_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 posting_entity_id text NOT NULL REFERENCES ontology.entity,posting_revision_id text NOT NULL REFERENCES ontology.revision,
 parent_id text REFERENCES ontology.cohort_profile_proposal,created_in_release text NOT NULL REFERENCES ontology.corpus_release,
 document jsonb NOT NULL,source_binding jsonb NOT NULL,evidence_bindings jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ontology_cohort_profile_latest ON ontology.cohort_profile_proposal(posting_entity_id,proposal_no DESC);
CREATE TABLE IF NOT EXISTS ontology.cohort_profile_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,review_id uuid NOT NULL UNIQUE,
 proposal_id text NOT NULL REFERENCES ontology.cohort_profile_proposal,decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
 reviewer text NOT NULL,reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant')),
 notes text NOT NULL,reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ontology_cohort_profile_decision_latest ON ontology.cohort_profile_decision(proposal_id,decision_id DESC);
CREATE TABLE IF NOT EXISTS ontology.cohort_profile_freeze (
 release_id text PRIMARY KEY REFERENCES ontology.requirement_freeze,proposal_cutoff bigint NOT NULL,decision_cutoff bigint NOT NULL,
 policy_version text NOT NULL DEFAULT 'reviewed-cohort-profiles-v1',frozen_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.cohort_profile_selection (
 release_id text NOT NULL REFERENCES ontology.cohort_profile_freeze,entity_id text NOT NULL,posting_revision_id text NOT NULL REFERENCES ontology.revision,
 proposal_id text REFERENCES ontology.cohort_profile_proposal,decision_id bigint REFERENCES ontology.cohort_profile_decision,
 outcome text NOT NULL CHECK(outcome IN ('EXTRACTION_NOT_ACCEPTED','NOT_PROPOSED','SOURCE_CHANGED','PENDING','REJECTED','UNRESOLVED','REVIEWED')),
 PRIMARY KEY(release_id,entity_id),FOREIGN KEY(release_id,entity_id) REFERENCES ontology.posting_selection
);
CREATE TABLE IF NOT EXISTS ontology.cohort_profile_membership (
 release_id text PRIMARY KEY REFERENCES ontology.cohort_profile_freeze,manifest jsonb NOT NULL,
 manifest_hash text NOT NULL CHECK(manifest_hash=ontology.hash(manifest))
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['cohort_profile_proposal','cohort_profile_decision','cohort_profile_freeze','cohort_profile_selection','cohort_profile_membership'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||name AND tgrelid=('ontology.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_profile_source_v1(id text,entity text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('posting_entity_id',p.entity_id,'posting_revision_id',p.posting_revision_id,
  'posting_payload_hash',r.payload_hash,'posting_payload',r.payload,'source_hash',p.source_hash,
  'input_scope',coalesce(p.source_data#>>'{_input,contract}','inline-fields'),'input_binding',p.source_data->'_input',
  'extraction_revision_id',p.extraction_revision_id,'extraction_decision_id',p.decision_id,'extraction_outcome',p.outcome,
  'fields',coalesce((SELECT jsonb_object_agg(k,ontology.normalize_text(v#>>'{}')) FROM jsonb_each(enrichment.input_fields(p.source_data)) e(k,v)),'{}'),
  'positions',coalesce((SELECT jsonb_agg(to_jsonb(c) ORDER BY c.position_id COLLATE "C")
   FROM ontology.release_position m JOIN ontology.position_claim c USING(position_id) WHERE m.release_id=id AND m.entity_id=entity),'[]'),
  'atoms',coalesce((SELECT jsonb_agg(jsonb_build_object('atom_id',a.source_claim_id||'/'||a.node_index,
   'source_claim_id',a.source_claim_id,'node_index',a.node_index,'source_text',a.source_text,'applicability',a.applicability,
   'selection',to_jsonb(s)-'release_id','source_binding',ontology.requirement_source_v1(a.source_claim_id,a.node_index),
   'typed_requirement',CASE WHEN t.claim_id IS NOT NULL THEN to_jsonb(t)-'release_id' ELSE NULL END)
   ORDER BY a.source_claim_id,a.node_index) FROM ontology.requirement_atom a
   JOIN ontology.requirement_selection s USING(release_id,source_claim_id,node_index)
   LEFT JOIN ontology.typed_requirement t USING(release_id,source_claim_id,node_index)
   WHERE a.release_id=id AND a.entity_id=entity),'[]'))
 FROM ontology.posting_selection p JOIN ontology.revision r ON r.revision_id=p.posting_revision_id
 WHERE p.release_id=id AND p.entity_id=entity
$$;

CREATE OR REPLACE FUNCTION ontology.cohort_profile_atoms_v1(source jsonb,position_key text)
RETURNS TABLE(atom jsonb,scope_known boolean) LANGUAGE sql IMMUTABLE AS $$
 SELECT a, a->>'applicability' IN ('all_positions','posting_metadata') OR
  (a->>'applicability'='explicit_positions' AND a#>'{source_binding,positions}' ? position_key)
 FROM jsonb_array_elements(source->'atoms') a
 WHERE a->>'applicability' IN ('all_positions','posting_metadata')
  OR a#>'{source_binding,positions}' ? position_key OR a->>'applicability' NOT IN ('all_positions','posting_metadata','explicit_positions')
$$;

CREATE OR REPLACE FUNCTION ontology.cohort_profile_evidence_v1(source jsonb,doc jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE e jsonb; field_text text; result jsonb:='[]'; BEGIN
 FOR e IN SELECT x FROM (SELECT DISTINCT x FROM (
  SELECT jsonb_array_elements(doc->'posting_label_evidence') x
  UNION ALL SELECT jsonb_array_elements(t->'country_evidence') FROM jsonb_array_elements(doc->'tracks') t
  UNION ALL SELECT jsonb_array_elements(t->'experience_evidence') FROM jsonb_array_elements(doc->'tracks') t
  UNION ALL SELECT jsonb_array_elements(t->'scope_evidence') FROM jsonb_array_elements(doc->'tracks') t) entries) unique_entries ORDER BY x::text COLLATE "C" LOOP
  field_text:=source->'fields'->>(e->>'field');
  IF field_text IS NULL OR (e->>'start_offset')::integer>=(e->>'end_offset')::integer
   OR (e->>'end_offset')::integer>length(field_text) OR substring(field_text FROM (e->>'start_offset')::integer+1
    FOR (e->>'end_offset')::integer-(e->>'start_offset')::integer) IS DISTINCT FROM e->>'excerpt'
  THEN RAISE EXCEPTION 'COHORT_PROFILE_EVIDENCE_MISMATCH'; END IF;
  result:=result||jsonb_build_array(e||jsonb_build_object('evidence_id',ontology.hash(jsonb_build_array('cohort-profile-evidence-v1',source->>'source_hash',e)),
   'field_text_hash',enrichment.hash(field_text),'excerpt_hash',enrichment.hash(e->>'excerpt'),
   'offset_unit','UNICODE_CODE_POINT','locator_version','half-open-nfc-lf-v1'));
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.validate_cohort_profile_v1(source jsonb,doc jsonb) RETURNS void LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE t jsonb; expected jsonb; chosen jsonb; field text; minimum integer; maximum integer; BEGIN
 IF doc->>'disposition'='UNRESOLVED' THEN
  IF doc->>'unresolved_reason' IS NULL OR doc->'tracks'<>'[]' OR doc->>'posting_experience_label'<>'UNKNOWN' OR doc->'posting_label_evidence'<>'[]'
  THEN RAISE EXCEPTION 'COHORT_PROFILE_UNRESOLVED_FIELDS'; END IF;
  RETURN;
 END IF;
 IF doc->>'unresolved_reason' IS NOT NULL OR source->>'extraction_outcome'<>'ACCEPTED' OR jsonb_array_length(source->'positions')=0
 THEN RAISE EXCEPTION 'COHORT_PROFILE_REVIEWED_POSITIONS_REQUIRED'; END IF;
 SELECT jsonb_agg(p->>'position_id' ORDER BY p->>'position_id' COLLATE "C") INTO expected FROM jsonb_array_elements(source->'positions') p;
 SELECT jsonb_agg(track_value->>'position_id' ORDER BY track_value->>'position_id' COLLATE "C") INTO chosen FROM jsonb_array_elements(doc->'tracks') track_value;
 IF chosen IS DISTINCT FROM expected THEN RAISE EXCEPTION 'COHORT_PROFILE_ALL_POSITIONS_REQUIRED'; END IF;
 IF doc->>'posting_experience_label'<>'UNKNOWN' AND jsonb_array_length(doc->'posting_label_evidence')=0
 THEN RAISE EXCEPTION 'COHORT_PROFILE_LABEL_EVIDENCE_REQUIRED'; END IF;
 FOR t IN SELECT * FROM jsonb_array_elements(doc->'tracks') LOOP
  minimum:=(t->>'minimum_months')::integer;maximum:=(t->>'maximum_months')::integer;
  IF nullif(btrim(t->>'scope_notes'),'') IS NULL THEN RAISE EXCEPTION 'COHORT_PROFILE_SCOPE_NOTES_REQUIRED'; END IF;
  IF t->>'country_scope'<>'UNKNOWN' AND jsonb_array_length(t->'country_evidence')=0 THEN RAISE EXCEPTION 'COHORT_PROFILE_COUNTRY_EVIDENCE_REQUIRED'; END IF;
  IF t->>'experience_policy'='UNKNOWN' THEN
   IF t->>'policy_basis'<>'UNKNOWN' OR minimum IS NOT NULL OR maximum IS NOT NULL OR t->'experience_requirement_ids'<>'[]'
   THEN RAISE EXCEPTION 'COHORT_PROFILE_UNKNOWN_EXPERIENCE_FIELDS'; END IF;
  ELSIF t->>'policy_basis'='UNKNOWN' OR jsonb_array_length(t->'experience_evidence')=0
  THEN RAISE EXCEPTION 'COHORT_PROFILE_EXPERIENCE_EVIDENCE_REQUIRED'; END IF;
  IF t->>'experience_policy' IN ('ENTRY','INTERNSHIP','UNRESTRICTED') AND
   (t->>'policy_basis'<>'EXPLICIT_LABEL' OR coalesce(minimum,0)>0 OR (t->>'experience_policy'='UNRESTRICTED' AND maximum IS NOT NULL))
  THEN RAISE EXCEPTION 'COHORT_PROFILE_EXPLICIT_POLICY_REQUIRED'; END IF;
  IF minimum>maximum THEN RAISE EXCEPTION 'COHORT_PROFILE_EXPERIENCE_RANGE_ORDER'; END IF;
  IF t->>'policy_basis'='PARSED_RANGE' AND minimum IS NULL AND maximum IS NULL THEN RAISE EXCEPTION 'COHORT_PROFILE_RANGE_REQUIRED'; END IF;
  FOREACH field IN ARRAY ARRAY['considered_atom_ids','included_requirement_ids','experience_requirement_ids'] LOOP
   SELECT coalesce(jsonb_agg(x ORDER BY x COLLATE "C"),'[]') INTO chosen FROM (SELECT DISTINCT jsonb_array_elements_text(t->field) x) v;
   IF chosen IS DISTINCT FROM t->field THEN RAISE EXCEPTION 'COHORT_PROFILE_REFERENCE_SET_NOT_CANONICAL'; END IF;
  END LOOP;
  SELECT coalesce(jsonb_agg(atom->>'atom_id' ORDER BY atom->>'atom_id' COLLATE "C"),'[]') INTO expected
   FROM ontology.cohort_profile_atoms_v1(source,t->>'position_id');
  IF t->'considered_atom_ids' IS DISTINCT FROM expected THEN RAISE EXCEPTION 'COHORT_PROFILE_ALL_ATOMS_REQUIRED'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(t->'included_requirement_ids') c WHERE NOT EXISTS(
   SELECT 1 FROM ontology.cohort_profile_atoms_v1(source,t->>'position_id') a
   WHERE a.scope_known AND a.atom#>>'{typed_requirement,claim_id}'=c))
  THEN RAISE EXCEPTION 'COHORT_PROFILE_REQUIREMENT_OUTSIDE_POSITION'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(t->'experience_requirement_ids') c WHERE NOT EXISTS(
   SELECT 1 FROM ontology.cohort_profile_atoms_v1(source,t->>'position_id') a WHERE a.scope_known AND a.atom#>>'{typed_requirement,claim_id}'=c
    AND a.atom#>>'{typed_requirement,requirement_kind}'='EXPERIENCE' AND a.atom#>>'{typed_requirement,necessity}'='REQUIRED'
    AND a.atom#>>'{typed_requirement,polarity}'='POSITIVE'
    AND a.atom#>>'{typed_requirement,condition,context_id}' IS NULL))
  THEN RAISE EXCEPTION 'COHORT_PROFILE_EXPERIENCE_REFERENCE_REQUIRED'; END IF;
  IF t->>'cohort_scope'='REVIEWED_SUBSET' AND EXISTS(SELECT 1 FROM jsonb_array_elements_text(t->'experience_requirement_ids') c
   WHERE NOT (t->'included_requirement_ids' ? c))
  THEN RAISE EXCEPTION 'COHORT_PROFILE_SUBSET_EXPERIENCE_NOT_INCLUDED'; END IF;
  IF (minimum IS NOT NULL AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(source->'atoms') a
    WHERE t->'experience_requirement_ids' ? (a#>>'{typed_requirement,claim_id}') AND (a#>>'{typed_requirement,condition,minimum_months}')::integer=minimum))
   OR (maximum IS NOT NULL AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(source->'atoms') a
    WHERE t->'experience_requirement_ids' ? (a#>>'{typed_requirement,claim_id}') AND (a#>>'{typed_requirement,condition,maximum_months}')::integer=maximum))
  THEN RAISE EXCEPTION 'COHORT_PROFILE_MONTHS_NOT_IN_REVIEWED_CONDITION'; END IF;
  IF t->>'cohort_scope'='UNRESOLVED' AND t->'included_requirement_ids'<>'[]' THEN RAISE EXCEPTION 'COHORT_PROFILE_UNRESOLVED_SCOPE_FIELDS'; END IF;
  IF t->>'cohort_scope'='REVIEWED_SUBSET' AND jsonb_array_length(t->'scope_evidence')=0 THEN RAISE EXCEPTION 'COHORT_PROFILE_SUBSET_EVIDENCE_REQUIRED'; END IF;
  IF ((t->>'entry_track_scoped')::boolean OR (t->>'domestic_track_scoped')::boolean) AND t->>'cohort_scope'<>'REVIEWED_SUBSET'
   THEN RAISE EXCEPTION 'COHORT_PROFILE_TRACK_SCOPE_REQUIRED'; END IF;
  IF (t->>'entry_track_scoped')::boolean AND (t->>'experience_policy' NOT IN ('ENTRY','INTERNSHIP','MIXED') OR coalesce(minimum,0)>0)
   THEN RAISE EXCEPTION 'COHORT_PROFILE_ENTRY_TRACK_POLICY_MISMATCH'; END IF;
  IF (t->>'domestic_track_scoped')::boolean AND t->>'country_scope'<>'MIXED'
   THEN RAISE EXCEPTION 'COHORT_PROFILE_DOMESTIC_TRACK_POLICY_MISMATCH'; END IF;
  IF t->>'cohort_scope'='POSITION' THEN
   IF EXISTS(SELECT 1 FROM ontology.cohort_profile_atoms_v1(source,t->>'position_id') a
    WHERE NOT a.scope_known OR a.atom#>>'{selection,outcome}' IS DISTINCT FROM 'REVIEWED')
   THEN RAISE EXCEPTION 'COHORT_PROFILE_REQUIREMENTS_UNRESOLVED'; END IF;
   SELECT coalesce(jsonb_agg(atom#>>'{typed_requirement,claim_id}' ORDER BY atom#>>'{typed_requirement,claim_id}' COLLATE "C"),'[]') INTO expected
    FROM ontology.cohort_profile_atoms_v1(source,t->>'position_id');
   IF t->'included_requirement_ids' IS DISTINCT FROM expected THEN RAISE EXCEPTION 'COHORT_PROFILE_POSITION_CLAIMS_INCOMPLETE'; END IF;
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.capture_cohort_profile_v1(doc jsonb) RETURNS text LANGUAGE plpgsql AS $$
DECLARE source jsonb;evidence jsonb;id text;latest text; BEGIN
 IF enrichment.schema_issues_v6(doc,(SELECT schema FROM ontology.cohort_profile_contract WHERE version='hop-cohort-profile-proposal-v1'))<>'[]'
 THEN RAISE EXCEPTION 'INVALID_COHORT_PROFILE_PROPOSAL'; END IF;
 PERFORM ontology.require_preparing(doc->>'release_id');PERFORM ontology.verify_claims(doc->>'release_id');
 IF NOT EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=doc->>'release_id') THEN RAISE EXCEPTION 'FREEZE_REQUIREMENTS_BEFORE_COHORT_PROFILE'; END IF;
 PERFORM ontology.verify_requirements_v1(doc->>'release_id');
 source:=ontology.cohort_profile_source_v1(doc->>'release_id',doc->>'posting_entity_id');
 IF source IS NULL THEN RAISE EXCEPTION 'COHORT_PROFILE_POSTING_NOT_IN_RELEASE'; END IF;
 IF doc->>'source_binding_hash' IS DISTINCT FROM ontology.hash(source) THEN RAISE EXCEPTION 'COHORT_PROFILE_SOURCE_BINDING_MISMATCH'; END IF;
 IF nullif(btrim(doc->>'actor'),'') IS NULL OR nullif(btrim(doc->>'resolver_version'),'') IS NULL OR nullif(btrim(doc->>'reason'),'') IS NULL
 THEN RAISE EXCEPTION 'COHORT_PROFILE_PROVENANCE_REQUIRED'; END IF;
 IF (doc->>'method'='MANUAL' AND (doc->>'actor_kind'<>'human' OR doc->>'model_id' IS NOT NULL OR doc->>'prompt_version' IS NOT NULL))
  OR (doc->>'method'='MODEL_INFERRED' AND (doc->>'actor_kind'<>'assistant' OR nullif(btrim(doc->>'model_id'),'') IS NULL OR nullif(btrim(doc->>'prompt_version'),'') IS NULL))
 THEN RAISE EXCEPTION 'COHORT_PROFILE_METHOD_PROVENANCE_MISMATCH'; END IF;
 PERFORM ontology.validate_cohort_profile_v1(source,doc);evidence:=ontology.cohort_profile_evidence_v1(source,doc);
 id:=ontology.hash(jsonb_build_object('document',doc-'release_id','source_binding',source));
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-cohort-profile:'||(doc->>'posting_entity_id'),0));
 IF EXISTS(SELECT 1 FROM ontology.cohort_profile_proposal WHERE proposal_id=id) THEN RETURN id; END IF;
 SELECT proposal_id INTO latest FROM ontology.cohort_profile_proposal WHERE posting_entity_id=doc->>'posting_entity_id' ORDER BY proposal_no DESC LIMIT 1;
 IF latest IS DISTINCT FROM doc->>'parent_id' THEN RAISE EXCEPTION 'STALE_COHORT_PROFILE_PARENT'; END IF;
 INSERT INTO ontology.cohort_profile_proposal(proposal_id,posting_entity_id,posting_revision_id,parent_id,created_in_release,document,source_binding,evidence_bindings)
 VALUES(id,doc->>'posting_entity_id',source->>'posting_revision_id',latest,doc->>'release_id',doc,source,evidence);
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION ontology.import_cohort_profile_v1(raw bytea) RETURNS text LANGUAGE plpgsql AS $$
DECLARE doc text; BEGIN
 IF raw IS NULL OR octet_length(raw) NOT BETWEEN 1 AND 1048576 THEN RAISE EXCEPTION 'COHORT_PROFILE_FILE_SIZE'; END IF;
 doc:=convert_from(raw,'UTF8');IF NOT (doc IS JSON OBJECT WITH UNIQUE KEYS) THEN RAISE EXCEPTION 'COHORT_PROFILE_JSON_OBJECT_REQUIRED'; END IF;
 RETURN ontology.capture_cohort_profile_v1(doc::jsonb);
END $$;

CREATE OR REPLACE FUNCTION ontology.decide_cohort_profile_v1(review_uuid uuid,id text,choice text,who text,kind text,explanation text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE p ontology.cohort_profile_proposal%ROWTYPE;old ontology.cohort_profile_decision%ROWTYPE;result bigint; BEGIN
 PERFORM retention.gate();IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF review_uuid IS NULL OR choice IS NULL OR choice NOT IN ('ACCEPT','REJECT') OR nullif(btrim(who),'') IS NULL
  OR kind IS NULL OR kind NOT IN ('human','assistant') OR nullif(btrim(explanation),'') IS NULL THEN RAISE EXCEPTION 'COHORT_PROFILE_REVIEW_FIELDS_REQUIRED'; END IF;
 SELECT * INTO p FROM ontology.cohort_profile_proposal WHERE proposal_id=id;IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_COHORT_PROFILE_PROPOSAL'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-cohort-profile:'||p.posting_entity_id,0));
 SELECT * INTO old FROM ontology.cohort_profile_decision WHERE review_id=review_uuid;
 IF FOUND THEN
  IF (old.proposal_id,old.decision,old.reviewer,old.reviewer_kind,old.notes) IS DISTINCT FROM (id,choice,who,kind,explanation)
  THEN RAISE EXCEPTION 'COHORT_PROFILE_REVIEW_ID_CONFLICT'; END IF;RETURN old.decision_id;
 END IF;
 IF who=p.document->>'actor' THEN RAISE EXCEPTION 'INDEPENDENT_COHORT_PROFILE_REVIEW_REQUIRED'; END IF;
 IF id IS DISTINCT FROM (SELECT proposal_id FROM ontology.cohort_profile_proposal WHERE posting_entity_id=p.posting_entity_id ORDER BY proposal_no DESC LIMIT 1)
 THEN RAISE EXCEPTION 'COHORT_PROFILE_PROPOSAL_SUPERSEDED'; END IF;
 IF choice='ACCEPT' AND p.document->>'disposition'<>'PROFILE' THEN RAISE EXCEPTION 'UNRESOLVED_COHORT_PROFILE_CANNOT_BE_ACCEPTED'; END IF;
 INSERT INTO ontology.cohort_profile_decision(review_id,proposal_id,decision,reviewer,reviewer_kind,notes)
 VALUES(review_uuid,id,choice,who,kind,explanation) RETURNING decision_id INTO result;RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_profile_candidates_v1(id text,proposal_cut bigint,decision_cut bigint)
RETURNS TABLE(entity_id text,posting_revision_id text,proposal_id text,decision_id bigint,outcome text) LANGUAGE sql STABLE AS $$
 SELECT s.entity_id,s.posting_revision_id,p.proposal_id,d.decision_id,
  CASE WHEN s.outcome<>'ACCEPTED' THEN 'EXTRACTION_NOT_ACCEPTED' WHEN p.proposal_id IS NULL THEN 'NOT_PROPOSED'
   WHEN p.source_binding IS DISTINCT FROM ontology.cohort_profile_source_v1(id,s.entity_id) THEN 'SOURCE_CHANGED'
   WHEN d.decision='REJECT' THEN 'REJECTED' WHEN p.document->>'disposition'='UNRESOLVED' THEN 'UNRESOLVED'
   WHEN d.decision='ACCEPT' THEN 'REVIEWED' ELSE 'PENDING' END
 FROM ontology.posting_selection s LEFT JOIN LATERAL (SELECT * FROM ontology.cohort_profile_proposal
  WHERE posting_entity_id=s.entity_id AND proposal_no<=proposal_cut ORDER BY proposal_no DESC LIMIT 1) p ON true
 LEFT JOIN LATERAL (SELECT * FROM ontology.cohort_profile_decision WHERE proposal_id=p.proposal_id
  AND decision_id<=decision_cut ORDER BY decision_id DESC LIMIT 1) d ON true WHERE s.release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.cohort_profile_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','reviewed-cohort-profiles-v1','freeze',(SELECT to_jsonb(f) FROM ontology.cohort_profile_freeze f WHERE release_id=id),
  'posting_count',(SELECT count(*) FROM ontology.cohort_profile_selection WHERE release_id=id),
  'selection_hash',ontology.hash(coalesce((SELECT jsonb_agg(jsonb_build_object('selection',to_jsonb(s),'proposal',to_jsonb(p),'review',to_jsonb(d),
   'current_source',ontology.cohort_profile_source_v1(id,s.entity_id)) ORDER BY s.entity_id COLLATE "C")
   FROM ontology.cohort_profile_selection s LEFT JOIN ontology.cohort_profile_proposal p USING(proposal_id)
   LEFT JOIN ontology.cohort_profile_decision d USING(decision_id) WHERE s.release_id=id),'[]')))
$$;

CREATE OR REPLACE FUNCTION ontology.verify_cohort_profiles_v1(id text) RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE f ontology.cohort_profile_freeze%ROWTYPE;p ontology.cohort_profile_proposal%ROWTYPE; BEGIN
 SELECT * INTO f FROM ontology.cohort_profile_freeze WHERE release_id=id;
 IF NOT FOUND THEN
  IF EXISTS(SELECT 1 FROM ontology.cohort_profile_selection WHERE release_id=id) OR EXISTS(SELECT 1 FROM ontology.cohort_profile_membership WHERE release_id=id)
  THEN RAISE EXCEPTION 'COHORT_PROFILE_FREEZE_REQUIRED'; END IF;RETURN;
 END IF;
 PERFORM ontology.verify_claims(id);PERFORM ontology.verify_requirements_v1(id);
 IF EXISTS((SELECT entity_id,posting_revision_id,proposal_id,decision_id,outcome FROM ontology.cohort_profile_selection WHERE release_id=id
   EXCEPT SELECT * FROM ontology.cohort_profile_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff)) UNION ALL
  (SELECT * FROM ontology.cohort_profile_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff)
   EXCEPT SELECT entity_id,posting_revision_id,proposal_id,decision_id,outcome FROM ontology.cohort_profile_selection WHERE release_id=id))
 THEN RAISE EXCEPTION 'COHORT_PROFILE_SELECTION_CHANGED'; END IF;
 FOR p IN SELECT * FROM ontology.cohort_profile_proposal WHERE proposal_id IN (SELECT proposal_id FROM ontology.cohort_profile_selection WHERE release_id=id) LOOP
  IF p.source_binding IS DISTINCT FROM ontology.cohort_profile_source_v1(p.created_in_release,p.posting_entity_id)
   OR p.document->>'source_binding_hash' IS DISTINCT FROM ontology.hash(p.source_binding)
   OR p.proposal_id<>ontology.hash(jsonb_build_object('document',p.document-'release_id','source_binding',p.source_binding))
   OR p.posting_revision_id IS DISTINCT FROM p.source_binding->>'posting_revision_id'
   OR p.document->>'posting_entity_id' IS DISTINCT FROM p.posting_entity_id OR p.document->>'parent_id' IS DISTINCT FROM p.parent_id
   OR p.document->>'release_id' IS DISTINCT FROM p.created_in_release
  THEN RAISE EXCEPTION 'COHORT_PROFILE_PROPOSAL_CHANGED'; END IF;
  PERFORM ontology.validate_cohort_profile_v1(p.source_binding,p.document);
  IF p.evidence_bindings IS DISTINCT FROM ontology.cohort_profile_evidence_v1(p.source_binding,p.document)
  THEN RAISE EXCEPTION 'COHORT_PROFILE_EVIDENCE_CHANGED'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM ontology.cohort_profile_membership WHERE release_id=id AND manifest=ontology.cohort_profile_manifest_v1(id) AND manifest_hash=ontology.hash(manifest))
 THEN RAISE EXCEPTION 'COHORT_PROFILE_MEMBERSHIP_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.freeze_cohort_profiles_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE manifest jsonb; BEGIN
 PERFORM ontology.require_preparing(id);PERFORM ontology.verify_claims(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'FREEZE_REQUIREMENTS_BEFORE_COHORT_PROFILE'; END IF;
 PERFORM ontology.verify_requirements_v1(id);
 IF EXISTS(SELECT 1 FROM ontology.cohort_profile_freeze WHERE release_id=id) THEN PERFORM ontology.verify_cohort_profiles_v1(id);RETURN; END IF;
 LOCK TABLE ontology.cohort_profile_proposal,ontology.cohort_profile_decision IN SHARE MODE;
 INSERT INTO ontology.cohort_profile_freeze(release_id,proposal_cutoff,decision_cutoff)
 SELECT id,(SELECT coalesce(max(proposal_no),0) FROM ontology.cohort_profile_proposal),(SELECT coalesce(max(decision_id),0) FROM ontology.cohort_profile_decision);
 INSERT INTO ontology.cohort_profile_selection SELECT id,c.* FROM ontology.cohort_profile_freeze f
  CROSS JOIN LATERAL ontology.cohort_profile_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff) c WHERE f.release_id=id;
 manifest:=ontology.cohort_profile_manifest_v1(id);INSERT INTO ontology.cohort_profile_membership VALUES(id,manifest,ontology.hash(manifest));
 PERFORM ontology.verify_cohort_profiles_v1(id);
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_track_reasons_v1(doc jsonb,t jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 WITH flags AS (SELECT doc->>'posting_experience_label'='MIXED' OR t->>'experience_policy'='MIXED' OR
  (EXISTS(SELECT 1 FROM jsonb_array_elements(doc->'tracks') p WHERE p->>'experience_policy' IN ('ENTRY','INTERNSHIP','UNRESTRICTED'))
   AND EXISTS(SELECT 1 FROM jsonb_array_elements(doc->'tracks') p WHERE p->>'experience_policy'='EXPERIENCED')) AS mixed),
 reasons AS (
  SELECT 'COUNTRY_UNKNOWN'::text reason WHERE t->>'country_scope'='UNKNOWN'
  UNION ALL SELECT 'OUTSIDE_KR' WHERE t->>'country_scope'='NON_KR'
  UNION ALL SELECT 'MIXED_COUNTRY_SCOPE_REQUIRES_REVIEW' WHERE t->>'country_scope'='MIXED' AND
   (t->>'cohort_scope'<>'REVIEWED_SUBSET' OR NOT (t->>'domestic_track_scoped')::boolean)
  UNION ALL SELECT 'REQUIREMENT_SCOPE_UNRESOLVED' WHERE t->>'cohort_scope'='UNRESOLVED'
  UNION ALL SELECT 'MIXED_EXPERIENCE_SCOPE_REQUIRES_REVIEW' FROM flags WHERE mixed AND t->>'cohort_scope'<>'REVIEWED_SUBSET'
  UNION ALL SELECT 'EXPERIENCE_NOT_ENTRY_ELIGIBLE' FROM flags WHERE NOT coalesce((
   (t->>'experience_policy' IN ('ENTRY','INTERNSHIP','UNRESTRICTED') AND t->>'policy_basis'='EXPLICIT_LABEL')
   OR (t->>'experience_policy'='UNKNOWN' AND doc->>'posting_experience_label' IN ('ENTRY','INTERNSHIP'))
   OR ((t->>'maximum_months')::integer<=24)
   OR (mixed AND (t->>'entry_track_scoped')::boolean AND t->>'cohort_scope'='REVIEWED_SUBSET')),false))
 SELECT coalesce(jsonb_agg(reason ORDER BY reason COLLATE "C"),'[]') FROM reasons
$$;

CREATE OR REPLACE VIEW ontology.cohort_profile_track AS
 SELECT s.release_id,s.entity_id,s.posting_revision_id,p.proposal_id,d.decision_id,t->>'position_id' AS position_id,t AS profile,
  p.document->>'posting_experience_label' AS posting_experience_label,
  ontology.cohort_track_reasons_v1(p.document,t) AS exclusion_reasons,
  CASE d.reviewer_kind WHEN 'human' THEN 'HUMAN_ACCEPTED' ELSE 'ASSISTANT_REVIEWED' END AS review_status,
  NULL::numeric AS confidence,'UNASSESSED'::text AS confidence_state
 FROM ontology.cohort_profile_selection s JOIN ontology.cohort_profile_proposal p USING(proposal_id)
 JOIN ontology.cohort_profile_decision d USING(decision_id) CROSS JOIN LATERAL jsonb_array_elements(p.document->'tracks') t
 WHERE s.outcome='REVIEWED';

CREATE OR REPLACE FUNCTION ontology.cohort_profile_release_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.manifest IS NOT NULL AND EXISTS(SELECT 1 FROM ontology.cohort_profile_freeze WHERE release_id=NEW.release_id) THEN
  PERFORM ontology.verify_cohort_profiles_v1(NEW.release_id);
  IF NEW.manifest->'cohort_profile_membership' IS DISTINCT FROM (SELECT to_jsonb(m) FROM ontology.cohort_profile_membership m WHERE release_id=NEW.release_id)
  THEN RAISE EXCEPTION 'COHORT_PROFILE_GRAPH_INTEGRATION_REQUIRED'; END IF;
 END IF;RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='ontology.corpus_release'::regclass AND tgname='ontology_cohort_profile_release_guard') THEN
  CREATE TRIGGER ontology_cohort_profile_release_guard BEFORE INSERT OR UPDATE OF manifest ON ontology.corpus_release
  FOR EACH ROW EXECUTE FUNCTION ontology.cohort_profile_release_guard_v1();
 END IF;
END $$;
COMMIT;
