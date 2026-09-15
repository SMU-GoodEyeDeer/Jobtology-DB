-- Product-role decisions are inferred claims, not source-supplied posting fields.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.occupation_proposal (
 proposal_id text PRIMARY KEY,
 proposal_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 posting_entity_id text NOT NULL REFERENCES ontology.entity,
 posting_revision_id text NOT NULL REFERENCES ontology.revision,
 parent_id text REFERENCES ontology.occupation_proposal,
 created_in_release text NOT NULL REFERENCES ontology.corpus_release,
 document jsonb NOT NULL,
 source_binding jsonb NOT NULL,
 source_binding_hash text NOT NULL,
 catalogue_snapshot_id text NOT NULL REFERENCES editorial.snapshot,
 catalogue_binding jsonb NOT NULL,
 occupation_id text REFERENCES ontology.entity,
 occupation_revision_id text REFERENCES ontology.revision,
 disposition text NOT NULL CHECK(disposition IN ('MATCH','OUT_OF_SCOPE','UNRESOLVED')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ontology_occupation_proposal_latest ON ontology.occupation_proposal(posting_revision_id,proposal_no DESC);
CREATE TABLE IF NOT EXISTS ontology.occupation_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 review_id uuid NOT NULL UNIQUE,
 proposal_id text NOT NULL REFERENCES ontology.occupation_proposal,
 decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
 reviewer text NOT NULL,
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant')),
 notes text NOT NULL,
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ontology_occupation_decision_latest ON ontology.occupation_decision(proposal_id,decision_id DESC);
CREATE TABLE IF NOT EXISTS ontology.occupation_freeze (
 release_id text PRIMARY KEY REFERENCES ontology.review_freeze,
 proposal_cutoff bigint NOT NULL,
 decision_cutoff bigint NOT NULL,
 frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 policy_version text NOT NULL DEFAULT 'reviewed-product-occupation-v1'
);
CREATE TABLE IF NOT EXISTS ontology.occupation_selection (
 release_id text NOT NULL REFERENCES ontology.occupation_freeze,
 entity_id text NOT NULL,
 posting_revision_id text NOT NULL REFERENCES ontology.revision,
 proposal_id text REFERENCES ontology.occupation_proposal,
 decision_id bigint REFERENCES ontology.occupation_decision,
 outcome text NOT NULL CHECK(outcome IN ('EXTRACTION_NOT_ACCEPTED','NOT_PROPOSED','SOURCE_CHANGED','CATALOGUE_CHANGED',
  'PENDING','REJECTED','UNRESOLVED','OUT_OF_SCOPE','MATCHED')),
 PRIMARY KEY(release_id,entity_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.posting_selection
);
CREATE TABLE IF NOT EXISTS ontology.occupation_membership (
 release_id text PRIMARY KEY REFERENCES ontology.occupation_freeze,
 manifest jsonb NOT NULL,
 manifest_hash text NOT NULL
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['occupation_proposal','occupation_decision','occupation_freeze','occupation_selection','occupation_membership'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||name AND tgrelid=('ontology.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.occupation_source_v1(id text,entity text) RETURNS jsonb LANGUAGE sql STABLE AS $$
WITH selection AS (SELECT * FROM ontology.posting_selection WHERE release_id=id AND entity_id=entity),
 duties AS (SELECT c.* FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id)
  WHERE m.release_id=id AND m.entity_id=entity AND c.kind='DUTY'),
 positions AS (SELECT p.* FROM ontology.release_position m JOIN ontology.position_claim p USING(position_id)
  WHERE m.release_id=id AND m.entity_id=entity),
 evidence AS (SELECT e.*,a.source_field,a.text_sha256 AS artifact_text_hash,a.input_sha256 AS artifact_input_hash
  FROM ontology.evidence_span e JOIN ontology.text_artifact a USING(artifact_id) WHERE e.evidence_id IN (
   SELECT x.evidence_id FROM ontology.claim_evidence x JOIN duties d USING(claim_id)
   UNION SELECT x.evidence_id FROM ontology.position_evidence x JOIN positions p USING(position_id)))
SELECT jsonb_build_object('posting_entity_id',p.entity_id,'posting_revision_id',p.posting_revision_id,
 'posting_payload_hash',r.payload_hash,'title',r.name,'source_hash',p.source_hash,'input_scope',
  coalesce(p.source_data#>>'{_input,contract}','inline-fields'),
 'extraction_revision_id',p.extraction_revision_id,'extraction_decision_id',p.decision_id,'extraction_outcome',p.outcome,
 'duties_status',p.extraction->>'duties_status',
 'duties',coalesce((SELECT jsonb_agg(to_jsonb(d)||jsonb_build_object(
  'position_ids',coalesce((SELECT jsonb_agg(x.position_id ORDER BY x.position_id) FROM ontology.claim_position x WHERE x.claim_id=d.claim_id),'[]'),
  'evidence',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY part_index) FROM ontology.claim_evidence x WHERE x.claim_id=d.claim_id),'[]')) ORDER BY d.claim_id) FROM duties d),'[]'),
 'positions',coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY position_id) FROM positions p),'[]'),
 'evidence',coalesce((SELECT jsonb_agg(to_jsonb(e) ORDER BY evidence_id) FROM evidence e),'[]'))
FROM selection p JOIN ontology.revision r ON r.revision_id=p.posting_revision_id
$$;

CREATE OR REPLACE FUNCTION ontology.occupation_catalogue_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('snapshot_id',p.snapshot_id,'source_contract',s.document->>'schema_version',
  'definitions',coalesce((SELECT jsonb_agg(jsonb_build_object('entity_id',i.entity_id,'revision_id',i.revision_id,
   'payload_hash',i.payload_hash,'payload',i.payload) ORDER BY i.entity_id) FROM editorial.item i WHERE i.snapshot_id=p.snapshot_id),'[]'))
 FROM editorial.release_pin p JOIN editorial.snapshot s USING(snapshot_id) WHERE p.release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.capture_occupation_v1(doc jsonb) RETURNS text LANGUAGE plpgsql AS $$
DECLARE errors jsonb; source jsonb; catalogue jsonb; source_hash text; target ontology.revision%ROWTYPE;
 id text; previous text; field text; canonical jsonb; expected jsonb; BEGIN
 errors:=enrichment.schema_issues_v6(doc,(SELECT schema FROM ontology.occupation_contract WHERE version='hop-product-occupation-proposal-v1'));
 IF errors<>'[]' THEN RAISE EXCEPTION 'INVALID_OCCUPATION_PROPOSAL: %',errors; END IF;
 PERFORM ontology.require_preparing(doc->>'release_id');
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=doc->>'release_id' AND manifest_hash IS NOT NULL)
 THEN RAISE EXCEPTION 'OCCUPATION_RELEASE_ALREADY_SEALED'; END IF;
 PERFORM ontology.verify_claims(doc->>'release_id');
 PERFORM editorial.verify_pin_v1(doc->>'release_id');
 source:=ontology.occupation_source_v1(doc->>'release_id',doc->>'posting_entity_id');
 IF source IS NULL THEN RAISE EXCEPTION 'OCCUPATION_POSTING_NOT_IN_REVIEWED_RELEASE'; END IF;
 source_hash:=ontology.hash(source);
 IF doc->>'source_binding_hash'<>source_hash THEN RAISE EXCEPTION 'OCCUPATION_SOURCE_BINDING_MISMATCH'; END IF;
 catalogue:=ontology.occupation_catalogue_v1(doc->>'release_id');
 IF doc->>'catalogue_snapshot_id'<>catalogue->>'snapshot_id' THEN RAISE EXCEPTION 'OCCUPATION_CATALOGUE_MISMATCH'; END IF;
 IF nullif(btrim(doc->>'actor'),'') IS NULL OR nullif(btrim(doc->>'reason'),'') IS NULL OR nullif(btrim(doc->>'resolver_version'),'') IS NULL
 THEN RAISE EXCEPTION 'OCCUPATION_PROVENANCE_REQUIRED'; END IF;
 IF (doc->>'method'='MODEL_INFERRED' AND (doc->>'actor_kind'<>'assistant' OR
   nullif(btrim(doc->>'model_id'),'') IS NULL OR nullif(btrim(doc->>'prompt_version'),'') IS NULL)) OR
  (doc->>'method'='MANUAL' AND (doc->>'actor_kind'<>'human' OR doc->>'model_id' IS NOT NULL OR doc->>'prompt_version' IS NOT NULL))
 THEN RAISE EXCEPTION 'OCCUPATION_METHOD_PROVENANCE_MISMATCH'; END IF;
 FOREACH field IN ARRAY ARRAY['considered_duty_ids','considered_position_ids','evidence_ids'] LOOP
  SELECT coalesce(jsonb_agg(v ORDER BY v COLLATE "C"),'[]') INTO canonical
   FROM (SELECT DISTINCT jsonb_array_elements_text(doc->field) v) x;
  IF jsonb_array_length(canonical)<>jsonb_array_length(doc->field) THEN RAISE EXCEPTION 'DUPLICATE_OCCUPATION_REFERENCE'; END IF;
  doc:=jsonb_set(doc,ARRAY[field],canonical);
 END LOOP;
 SELECT coalesce(jsonb_agg(d->>'claim_id' ORDER BY d->>'claim_id' COLLATE "C"),'[]') INTO expected FROM jsonb_array_elements(source->'duties') d;
 IF doc->'considered_duty_ids'<>expected THEN RAISE EXCEPTION 'OCCUPATION_ALL_DUTIES_REQUIRED'; END IF;
 SELECT coalesce(jsonb_agg(p->>'position_id' ORDER BY p->>'position_id' COLLATE "C"),'[]') INTO expected FROM jsonb_array_elements(source->'positions') p;
 IF doc->'considered_position_ids'<>expected THEN RAISE EXCEPTION 'OCCUPATION_ALL_POSITIONS_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(doc->'evidence_ids') e WHERE NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(source->'evidence') x WHERE x->>'evidence_id'=e))
 THEN RAISE EXCEPTION 'OCCUPATION_EVIDENCE_OUTSIDE_SOURCE'; END IF;
 IF (doc->>'disposition'='MATCH')<>(doc->>'occupation_id' IS NOT NULL) OR
  (doc->>'disposition'='UNRESOLVED')<>(doc->>'unresolved_reason' IS NOT NULL)
 THEN RAISE EXCEPTION 'OCCUPATION_OUTCOME_FIELDS'; END IF;
 IF doc->>'disposition'<>'UNRESOLVED' AND (source->>'extraction_outcome'<>'ACCEPTED' OR
  source->>'duties_status' IS DISTINCT FROM 'explicit' OR jsonb_array_length(source->'duties')=0)
 THEN RAISE EXCEPTION 'OCCUPATION_REVIEWED_DUTIES_REQUIRED'; END IF;
 IF doc->>'disposition'<>'UNRESOLVED' AND NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(source->'duties') d CROSS JOIN LATERAL jsonb_array_elements(d->'evidence') e
  WHERE doc->'evidence_ids' @> jsonb_build_array(e->>'evidence_id'))
 THEN RAISE EXCEPTION 'OCCUPATION_DUTY_EVIDENCE_REQUIRED'; END IF;
 IF doc->>'disposition'='MATCH' THEN
  SELECT r.* INTO target FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
   JOIN editorial.item i ON i.snapshot_id=doc->>'catalogue_snapshot_id' AND i.entity_id=m.entity_id AND i.revision_id=r.revision_id
   WHERE m.release_id=doc->>'release_id' AND m.entity_id=doc->>'occupation_id' AND r.kind='occupation'
    AND r.payload->>'scheme_id'='urn:jobtology:conceptScheme:product-occupations';
  IF NOT FOUND THEN RAISE EXCEPTION 'OCCUPATION_TARGET_NOT_IN_CATALOGUE'; END IF;
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('occupation:'||(source->>'posting_revision_id'),0));
 id:=ontology.hash(jsonb_build_object('document',doc-'release_id','source_binding',source,'catalogue_binding',catalogue));
 IF EXISTS(SELECT 1 FROM ontology.occupation_proposal WHERE proposal_id=id) THEN RETURN id; END IF;
 SELECT proposal_id INTO previous FROM ontology.occupation_proposal
  WHERE posting_revision_id=source->>'posting_revision_id' ORDER BY proposal_no DESC LIMIT 1;
 IF doc->>'parent_id' IS DISTINCT FROM previous THEN RAISE EXCEPTION 'STALE_OCCUPATION_PARENT'; END IF;
 INSERT INTO ontology.occupation_proposal(proposal_id,posting_entity_id,posting_revision_id,parent_id,created_in_release,document,
  source_binding,source_binding_hash,catalogue_snapshot_id,catalogue_binding,occupation_id,occupation_revision_id,disposition)
 VALUES(id,doc->>'posting_entity_id',source->>'posting_revision_id',previous,doc->>'release_id',doc,source,source_hash,
  doc->>'catalogue_snapshot_id',catalogue,target.entity_id,target.revision_id,doc->>'disposition');
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION ontology.decide_occupation_v1(review uuid,proposal text,choice text,actor text,actor_kind text,rationale text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE p ontology.occupation_proposal%ROWTYPE; prior ontology.occupation_decision%ROWTYPE; id bigint; BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF review IS NULL THEN RAISE EXCEPTION 'OCCUPATION_REVIEW_ID_REQUIRED'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('occupation-review:'||review::text,0));
 SELECT * INTO prior FROM ontology.occupation_decision WHERE review_id=review;
 IF FOUND THEN
  IF ROW(prior.proposal_id,prior.decision,prior.reviewer,prior.reviewer_kind,prior.notes)
   IS DISTINCT FROM ROW(proposal,choice,actor,actor_kind,rationale)
  THEN RAISE EXCEPTION 'OCCUPATION_REVIEW_ID_CONFLICT'; END IF;
  RETURN prior.decision_id;
 END IF;
 SELECT * INTO p FROM ontology.occupation_proposal WHERE proposal_id=proposal;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_OCCUPATION_PROPOSAL'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('occupation:'||p.posting_revision_id,0));
 IF EXISTS(SELECT 1 FROM ontology.occupation_proposal n WHERE n.posting_revision_id=p.posting_revision_id AND n.proposal_no>p.proposal_no)
 THEN RAISE EXCEPTION 'OCCUPATION_PROPOSAL_SUPERSEDED'; END IF;
 IF choice IS NULL OR choice NOT IN ('ACCEPT','REJECT') OR actor_kind IS NULL OR actor_kind NOT IN ('human','assistant') OR
  nullif(btrim(actor),'') IS NULL OR nullif(btrim(rationale),'') IS NULL
 THEN RAISE EXCEPTION 'OCCUPATION_REVIEW_FIELDS_REQUIRED'; END IF;
 IF btrim(actor)=btrim(p.document->>'actor') THEN RAISE EXCEPTION 'INDEPENDENT_OCCUPATION_REVIEW_REQUIRED'; END IF;
 INSERT INTO ontology.occupation_decision(review_id,proposal_id,decision,reviewer,reviewer_kind,notes)
 VALUES(review,proposal,choice,actor,actor_kind,rationale) RETURNING decision_id INTO id;
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION ontology.occupation_candidates_v1(id text,proposal_cut bigint,decision_cut bigint)
RETURNS TABLE(entity_id text,posting_revision_id text,proposal_id text,decision_id bigint,outcome text) LANGUAGE sql STABLE AS $$
SELECT s.entity_id,s.posting_revision_id,p.proposal_id,d.decision_id,
 CASE WHEN s.outcome<>'ACCEPTED' THEN 'EXTRACTION_NOT_ACCEPTED'
  WHEN p.proposal_id IS NULL THEN 'NOT_PROPOSED'
  WHEN p.source_binding IS DISTINCT FROM ontology.occupation_source_v1(id,s.entity_id) THEN 'SOURCE_CHANGED'
  WHEN p.catalogue_binding IS DISTINCT FROM ontology.occupation_catalogue_v1(id) THEN 'CATALOGUE_CHANGED'
  WHEN d.decision_id IS NULL THEN 'PENDING'
  WHEN d.decision='REJECT' THEN 'REJECTED'
  WHEN p.disposition='MATCH' THEN 'MATCHED'
  ELSE p.disposition END
FROM ontology.posting_selection s LEFT JOIN LATERAL (
 SELECT * FROM ontology.occupation_proposal n WHERE n.posting_revision_id=s.posting_revision_id AND n.proposal_no<=proposal_cut
 ORDER BY proposal_no DESC LIMIT 1) p ON true LEFT JOIN LATERAL (
 SELECT * FROM ontology.occupation_decision r WHERE r.proposal_id=p.proposal_id AND r.decision_id<=decision_cut
 ORDER BY decision_id DESC LIMIT 1) d ON true WHERE s.release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.occupation_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('format','hop-product-occupation-membership-v1','release_id',id,
  'freeze',(SELECT to_jsonb(f) FROM ontology.occupation_freeze f WHERE release_id=id),
  'catalogue_binding',ontology.occupation_catalogue_v1(id),
  'posting_count',(SELECT count(*) FROM ontology.posting_selection WHERE release_id=id),
  'selection_count',(SELECT count(*) FROM ontology.occupation_selection WHERE release_id=id),
  'selection_hash',(SELECT ontology.hash(coalesce(jsonb_agg(to_jsonb(s) ORDER BY entity_id),'[]')) FROM ontology.occupation_selection s WHERE release_id=id),
  'proposal_hash',(SELECT ontology.hash(coalesce(jsonb_agg(to_jsonb(p) ORDER BY proposal_id),'[]')) FROM ontology.occupation_proposal p
   WHERE p.proposal_id IN (SELECT proposal_id FROM ontology.occupation_selection WHERE release_id=id)),
  'decision_hash',(SELECT ontology.hash(coalesce(jsonb_agg(to_jsonb(d) ORDER BY decision_id),'[]')) FROM ontology.occupation_decision d
   WHERE d.decision_id IN (SELECT decision_id FROM ontology.occupation_selection WHERE release_id=id)))
$$;

CREATE OR REPLACE FUNCTION ontology.verify_occupations_v1(id text) RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE f ontology.occupation_freeze%ROWTYPE; p ontology.occupation_proposal%ROWTYPE; BEGIN
 SELECT * INTO f FROM ontology.occupation_freeze WHERE release_id=id;
 IF NOT FOUND THEN RETURN; END IF;
 PERFORM ontology.verify_claims(id);
 PERFORM editorial.verify_pin_v1(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.occupation_membership m WHERE m.release_id=id AND m.manifest=ontology.occupation_manifest_v1(id)
  AND m.manifest_hash=ontology.hash(m.manifest)) THEN RAISE EXCEPTION 'OCCUPATION_MEMBERSHIP_CHANGED'; END IF;
 IF EXISTS((SELECT entity_id,posting_revision_id,proposal_id,decision_id,outcome FROM ontology.occupation_selection WHERE release_id=id
  EXCEPT SELECT * FROM ontology.occupation_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff)) UNION ALL
  (SELECT * FROM ontology.occupation_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff)
   EXCEPT SELECT entity_id,posting_revision_id,proposal_id,decision_id,outcome FROM ontology.occupation_selection WHERE release_id=id))
 THEN RAISE EXCEPTION 'OCCUPATION_SELECTION_CHANGED'; END IF;
 FOR p IN SELECT * FROM ontology.occupation_proposal WHERE proposal_id IN (SELECT proposal_id FROM ontology.occupation_selection WHERE release_id=id) LOOP
  IF p.source_binding_hash<>ontology.hash(p.source_binding) OR p.proposal_id<>ontology.hash(jsonb_build_object(
    'document',p.document-'release_id','source_binding',p.source_binding,'catalogue_binding',p.catalogue_binding)) OR
   p.posting_entity_id IS DISTINCT FROM p.source_binding->>'posting_entity_id' OR
   p.posting_revision_id IS DISTINCT FROM p.source_binding->>'posting_revision_id' OR
   p.posting_entity_id IS DISTINCT FROM p.document->>'posting_entity_id' OR
   p.source_binding_hash IS DISTINCT FROM p.document->>'source_binding_hash' OR
   p.catalogue_snapshot_id IS DISTINCT FROM p.catalogue_binding->>'snapshot_id' OR
   p.catalogue_snapshot_id IS DISTINCT FROM p.document->>'catalogue_snapshot_id' OR
   p.parent_id IS DISTINCT FROM p.document->>'parent_id' OR
   p.created_in_release IS DISTINCT FROM p.document->>'release_id' OR
   p.occupation_id IS DISTINCT FROM p.document->>'occupation_id' OR p.disposition IS DISTINCT FROM p.document->>'disposition' OR
   p.occupation_revision_id IS DISTINCT FROM (SELECT i.revision_id FROM editorial.item i
    WHERE i.snapshot_id=p.catalogue_snapshot_id AND i.entity_id=p.occupation_id AND i.kind='occupation')
  THEN RAISE EXCEPTION 'OCCUPATION_PROPOSAL_CHANGED'; END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.freeze_occupations_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE proposal_cut bigint; decision_cut bigint; manifest jsonb; BEGIN
 PERFORM ontology.require_preparing(id);
 IF EXISTS(SELECT 1 FROM ontology.occupation_freeze WHERE release_id=id) THEN PERFORM ontology.verify_occupations_v1(id);RETURN; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest_hash IS NOT NULL)
 THEN RAISE EXCEPTION 'OCCUPATION_RELEASE_ALREADY_SEALED'; END IF;
 PERFORM ontology.verify_claims(id); PERFORM editorial.verify_pin_v1(id);
 LOCK TABLE ontology.occupation_proposal,ontology.occupation_decision IN SHARE MODE;
 SELECT coalesce(max(proposal_no),0) INTO proposal_cut FROM ontology.occupation_proposal;
 SELECT coalesce(max(decision_id),0) INTO decision_cut FROM ontology.occupation_decision;
 INSERT INTO ontology.occupation_freeze(release_id,proposal_cutoff,decision_cutoff) VALUES(id,proposal_cut,decision_cut);
 INSERT INTO ontology.occupation_selection SELECT id,c.* FROM ontology.occupation_candidates_v1(id,proposal_cut,decision_cut) c;
 manifest:=ontology.occupation_manifest_v1(id);
 INSERT INTO ontology.occupation_membership VALUES(id,manifest,ontology.hash(manifest));
 PERFORM ontology.verify_occupations_v1(id);
END $$;

CREATE OR REPLACE VIEW ontology.primary_product_occupation AS
SELECT s.release_id,s.entity_id,s.posting_revision_id,p.proposal_id,d.decision_id,p.occupation_id,p.occupation_revision_id,
 p.document->>'method' AS method,p.document->>'resolver_version' AS resolver_version,
 p.document->'evidence_ids' AS evidence_ids,d.reviewer,d.reviewer_kind,d.reviewed_at,
 CASE WHEN d.reviewer_kind='human' THEN 'HUMAN_ACCEPTED' ELSE 'ASSISTANT_REVIEWED' END AS review_state,
 NULL::numeric AS confidence,'UNASSESSED'::text AS confidence_state
FROM ontology.occupation_selection s JOIN ontology.occupation_proposal p USING(proposal_id)
 JOIN ontology.occupation_decision d USING(decision_id) WHERE s.outcome='MATCHED';

-- Native file import rejects duplicate JSON keys before PostgreSQL jsonb can erase them.
CREATE OR REPLACE FUNCTION ontology.import_occupation_v1(raw bytea) RETURNS text LANGUAGE plpgsql AS $$
DECLARE doc text; BEGIN
 IF raw IS NULL OR octet_length(raw) NOT BETWEEN 1 AND 1048576 THEN RAISE EXCEPTION 'OCCUPATION_PROPOSAL_FILE_SIZE'; END IF;
 doc:=convert_from(raw,'UTF8');
 IF NOT (doc IS JSON OBJECT WITH UNIQUE KEYS) THEN RAISE EXCEPTION 'OCCUPATION_PROPOSAL_JSON_OBJECT_REQUIRED'; END IF;
 RETURN ontology.capture_occupation_v1(doc::jsonb);
END $$;

-- Reads only already selected evidence; no attachment fetching or inference.
CREATE OR REPLACE FUNCTION ontology.query_occupation_input_v1(choice text,entity text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; source jsonb; catalogue jsonb; latest ontology.occupation_proposal%ROWTYPE; BEGIN
 id:=ontology.read_release_v2(choice,preview); PERFORM ontology.verify_claims(id); PERFORM editorial.verify_pin_v1(id);
 source:=ontology.occupation_source_v1(id,entity);
 IF source IS NULL THEN RAISE EXCEPTION 'OCCUPATION_POSTING_NOT_IN_REVIEWED_RELEASE'; END IF;
 catalogue:=ontology.occupation_catalogue_v1(id);
 SELECT * INTO latest FROM ontology.occupation_proposal WHERE posting_revision_id=source->>'posting_revision_id' ORDER BY proposal_no DESC LIMIT 1;
 RETURN ontology.read_context_v2(id,preview)||jsonb_build_object('occupation_contract_version','hop-product-occupation-input-v1',
  'source_binding',source,'source_binding_hash',ontology.hash(source),'catalogue_binding',catalogue,
  'current_proposal',CASE WHEN latest.proposal_id IS NOT NULL THEN to_jsonb(latest) END,
  'current_decision',(SELECT to_jsonb(d) FROM ontology.occupation_decision d
   WHERE d.proposal_id=latest.proposal_id ORDER BY decision_id DESC LIMIT 1),
  'proposal_template',jsonb_build_object('schema_version','hop-product-occupation-proposal-v1','release_id',id,
   'posting_entity_id',entity,'parent_id',latest.proposal_id,'source_binding_hash',ontology.hash(source),
   'catalogue_snapshot_id',catalogue->>'snapshot_id','actor','','actor_kind','human','method','MANUAL',
   'model_id',NULL,'prompt_version',NULL,'resolver_version','','reason','',
   'disposition','UNRESOLVED','occupation_id',NULL,'unresolved_reason','INSUFFICIENT_EVIDENCE',
   'considered_duty_ids',coalesce((SELECT jsonb_agg(d->>'claim_id' ORDER BY d->>'claim_id') FROM jsonb_array_elements(source->'duties') d),'[]'),
   'considered_position_ids',coalesce((SELECT jsonb_agg(p->>'position_id' ORDER BY p->>'position_id') FROM jsonb_array_elements(source->'positions') p),'[]'),
   'evidence_ids','[]'::jsonb));
END $$;

CREATE OR REPLACE FUNCTION ontology.query_occupations_v1(choice text,preview boolean DEFAULT false) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; BEGIN
 id:=ontology.read_release_v2(choice,preview);PERFORM ontology.verify_claims(id);PERFORM editorial.verify_pin_v1(id);
 PERFORM ontology.verify_occupations_v1(id);
 RETURN ontology.read_context_v2(id,preview)||jsonb_build_object('occupation_contract_version','hop-product-occupation-read-v1',
  'selection_status',CASE WHEN EXISTS(SELECT 1 FROM ontology.occupation_freeze WHERE release_id=id) THEN 'FROZEN' ELSE 'NOT_FROZEN' END,
  'membership',(SELECT to_jsonb(m) FROM ontology.occupation_membership m WHERE release_id=id),
  'current_candidates',CASE WHEN NOT EXISTS(SELECT 1 FROM ontology.occupation_freeze WHERE release_id=id)
   THEN (SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY entity_id),'[]') FROM ontology.occupation_candidates_v1(id,
    (SELECT coalesce(max(proposal_no),0) FROM ontology.occupation_proposal),
    (SELECT coalesce(max(decision_id),0) FROM ontology.occupation_decision)) c) ELSE NULL END,
  'postings',coalesce((SELECT jsonb_agg(jsonb_build_object('entity_id',s.entity_id,'posting_revision_id',s.posting_revision_id,
   'selection',to_jsonb(o),'primary_product_occupation',(SELECT to_jsonb(p) FROM ontology.primary_product_occupation p
    WHERE p.release_id=id AND p.entity_id=s.entity_id)) ORDER BY s.entity_id)
   FROM ontology.posting_selection s LEFT JOIN ontology.occupation_selection o USING(release_id,entity_id) WHERE s.release_id=id),'[]'),
  'publication_notice','Product-role review is not calibrated confidence. OUT_OF_SCOPE and UNRESOLVED are not occupation assignments. Graph loading and serving activation require separate steps.');
END $$;

CREATE OR REPLACE FUNCTION ontology.guard_occupation_manifest_v1() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE m ontology.occupation_membership%ROWTYPE; BEGIN
 SELECT * INTO m FROM ontology.occupation_membership WHERE release_id=NEW.release_id;
 IF FOUND AND NEW.manifest IS NOT NULL THEN
  PERFORM ontology.verify_occupations_v1(NEW.release_id);
  IF NEW.manifest->'occupation_membership' IS DISTINCT FROM m.manifest OR NEW.manifest->>'occupation_membership_hash' IS DISTINCT FROM m.manifest_hash
  THEN RAISE EXCEPTION 'OCCUPATION_GRAPH_INTEGRATION_REQUIRED'; END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_occupation_manifest_guard' AND tgrelid='ontology.corpus_release'::regclass) THEN
  CREATE TRIGGER ontology_occupation_manifest_guard BEFORE UPDATE OF manifest,manifest_hash ON ontology.corpus_release
  FOR EACH ROW EXECUTE FUNCTION ontology.guard_occupation_manifest_v1();
 END IF;
END $$;
COMMIT;
