-- Reversible grouping of distinct source postings; never merge/delete identities.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.duplicate_proposal (
 proposal_id text PRIMARY KEY, proposal_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 cluster_id uuid NOT NULL, parent_id text REFERENCES ontology.duplicate_proposal,
 created_in_release text NOT NULL REFERENCES ontology.corpus_release,
 document jsonb NOT NULL, source_binding jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ontology_duplicate_proposal_family ON ontology.duplicate_proposal(cluster_id,proposal_no DESC);
CREATE TABLE IF NOT EXISTS ontology.duplicate_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, review_id uuid NOT NULL UNIQUE,
 proposal_id text NOT NULL REFERENCES ontology.duplicate_proposal,
 decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')), reviewer text NOT NULL,
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant')), notes text NOT NULL,
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ontology_duplicate_decision_latest ON ontology.duplicate_decision(proposal_id,decision_id DESC);
CREATE TABLE IF NOT EXISTS ontology.duplicate_freeze (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release, proposal_cutoff bigint NOT NULL,
 decision_cutoff bigint NOT NULL, policy_version text NOT NULL DEFAULT 'reviewed-duplicate-groups-v1',
 frozen_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.duplicate_selection (
 release_id text NOT NULL REFERENCES ontology.duplicate_freeze, cluster_id uuid NOT NULL,
 proposal_id text NOT NULL REFERENCES ontology.duplicate_proposal, decision_id bigint REFERENCES ontology.duplicate_decision,
 outcome text NOT NULL CHECK(outcome IN ('PENDING','REJECTED','ACCEPTED','MEMBER_OUTSIDE_RELEASE','SOURCE_CHANGED')),
 PRIMARY KEY(release_id,cluster_id)
);
CREATE TABLE IF NOT EXISTS ontology.duplicate_member (
 release_id text NOT NULL REFERENCES ontology.duplicate_freeze, entity_id text NOT NULL,
 revision_id text NOT NULL REFERENCES ontology.revision, group_id text NOT NULL,
 cluster_id uuid, proposal_id text REFERENCES ontology.duplicate_proposal, decision_id bigint REFERENCES ontology.duplicate_decision,
 PRIMARY KEY(release_id,entity_id), FOREIGN KEY(release_id,entity_id) REFERENCES ontology.release_revision,
 CHECK((cluster_id IS NULL)=(proposal_id IS NULL) AND (cluster_id IS NULL)=(decision_id IS NULL))
);
CREATE TABLE IF NOT EXISTS ontology.duplicate_membership (
 release_id text PRIMARY KEY REFERENCES ontology.duplicate_freeze, manifest jsonb NOT NULL,
 manifest_hash text NOT NULL CHECK(manifest_hash=ontology.hash(manifest))
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['duplicate_proposal','duplicate_decision','duplicate_freeze','duplicate_selection','duplicate_member','duplicate_membership'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||name AND tgrelid=('ontology.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.duplicate_source_v1(id text,members jsonb) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE result jsonb; BEGIN
 IF jsonb_typeof(members) IS DISTINCT FROM 'array' OR jsonb_array_length(members) NOT BETWEEN 2 AND 1000
 THEN RAISE EXCEPTION 'DUPLICATE_MEMBERS_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(members) e WHERE jsonb_typeof(e)<>'string')
  OR members IS DISTINCT FROM (SELECT jsonb_agg(x ORDER BY x COLLATE "C") FROM (SELECT DISTINCT jsonb_array_elements_text(members) x) v)
 THEN RAISE EXCEPTION 'DUPLICATE_MEMBER_SET_NOT_CANONICAL'; END IF;
 SELECT jsonb_agg(jsonb_build_object('revision',to_jsonb(r)-'created_at',
  'source_support',coalesce((SELECT jsonb_agg(jsonb_build_object('record_id',i.record_id,'source_id',i.source_id,
   'run_id',i.run_id,'source_record_id',i.source_record_id,'document_id',i.document_id,'locator',i.locator,
   'raw_sha256',i.raw_sha256,'normalized_hash',i.normalized_hash,'source_fields',s.fields,'field_lineage',i.field_lineage)
   ORDER BY i.record_id) FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id)
   WHERE s.release_id=id AND s.entity_id=m.entity_id),'[]')) ORDER BY m.entity_id COLLATE "C")
 INTO result FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
 WHERE m.release_id=id AND r.kind='jobPosting' AND members ? m.entity_id;
 IF coalesce(jsonb_array_length(result),0)<>jsonb_array_length(members)
 THEN RAISE EXCEPTION 'DUPLICATE_POSTING_NOT_IN_RELEASE'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(result) e WHERE jsonb_array_length(e->'source_support')=0
  OR e->'revision'->>'payload_hash' IS DISTINCT FROM ontology.hash(e->'revision'->'payload'))
 THEN RAISE EXCEPTION 'DUPLICATE_SOURCE_EVIDENCE_REQUIRED'; END IF;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.capture_duplicate_v1(doc jsonb) RETURNS text LANGUAGE plpgsql AS $$
DECLARE source jsonb; schema jsonb; family uuid; id text; latest text; BEGIN
 SELECT c.schema INTO schema FROM ontology.duplicate_contract c WHERE version='hop-duplicate-proposal-v1';
 IF schema IS NULL OR enrichment.schema_issues_v6(doc,schema)<>'[]'::jsonb THEN RAISE EXCEPTION 'INVALID_DUPLICATE_PROPOSAL'; END IF;
 BEGIN family:=(doc->>'cluster_id')::uuid; EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'INVALID_DUPLICATE_CLUSTER_ID'; END;
 IF doc->>'cluster_id'<>family::text THEN RAISE EXCEPTION 'INVALID_DUPLICATE_CLUSTER_ID'; END IF;
 PERFORM ontology.require_preparing(doc->>'release_id');
 PERFORM ontology.check_frozen_sources(doc->>'release_id');
 PERFORM ontology.verify_observation_membership_v1(doc->>'release_id');
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-duplicate-family:'||family,0));
 IF EXISTS(SELECT 1 FROM jsonb_each(doc) e WHERE e.key IN ('actor','reason','resolver_version') AND nullif(btrim(e.value#>>'{}'),'') IS NULL)
 THEN RAISE EXCEPTION 'DUPLICATE_PROVENANCE_REQUIRED'; END IF;
 IF (doc->>'method'='MANUAL' AND (doc->>'actor_kind'<>'human' OR doc->>'model_id' IS NOT NULL OR doc->>'prompt_version' IS NOT NULL))
  OR (doc->>'method'='MODEL_INFERRED' AND (doc->>'actor_kind'<>'assistant' OR nullif(btrim(doc->>'model_id'),'') IS NULL OR nullif(btrim(doc->>'prompt_version'),'') IS NULL))
 THEN RAISE EXCEPTION 'DUPLICATE_METHOD_PROVENANCE_MISMATCH'; END IF;
 source:=ontology.duplicate_source_v1(doc->>'release_id',doc->'member_ids');
 IF doc->>'source_binding_hash' IS DISTINCT FROM ontology.hash(source) THEN RAISE EXCEPTION 'DUPLICATE_SOURCE_BINDING_MISMATCH'; END IF;
 id:=ontology.hash(jsonb_build_object('document',doc-'release_id','source_binding',source));
 IF EXISTS(SELECT 1 FROM ontology.duplicate_proposal WHERE proposal_id=id) THEN RETURN id; END IF;
 SELECT proposal_id INTO latest FROM ontology.duplicate_proposal WHERE cluster_id=family ORDER BY proposal_no DESC LIMIT 1;
 IF doc->>'parent_id' IS DISTINCT FROM latest THEN RAISE EXCEPTION 'STALE_DUPLICATE_PARENT'; END IF;
 INSERT INTO ontology.duplicate_proposal(proposal_id,cluster_id,parent_id,created_in_release,document,source_binding)
 VALUES(id,family,latest,doc->>'release_id',doc,source);
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION ontology.import_duplicate_v1(raw bytea) RETURNS text LANGUAGE plpgsql AS $$
DECLARE doc text; BEGIN
 IF raw IS NULL OR octet_length(raw) NOT BETWEEN 1 AND 1048576 THEN RAISE EXCEPTION 'DUPLICATE_PROPOSAL_FILE_SIZE'; END IF;
 doc:=convert_from(raw,'UTF8');
 IF NOT (doc IS JSON OBJECT WITH UNIQUE KEYS) THEN RAISE EXCEPTION 'DUPLICATE_PROPOSAL_JSON_OBJECT_REQUIRED'; END IF;
 RETURN ontology.capture_duplicate_v1(doc::jsonb);
END $$;

CREATE OR REPLACE FUNCTION ontology.decide_duplicate_v1(review_uuid uuid,id text,choice text,who text,kind text,explanation text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE p ontology.duplicate_proposal%ROWTYPE; old ontology.duplicate_decision%ROWTYPE; result bigint; BEGIN
 PERFORM retention.gate(); IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF review_uuid IS NULL OR choice IS NULL OR choice NOT IN ('ACCEPT','REJECT') OR nullif(btrim(who),'') IS NULL
  OR kind IS NULL OR kind NOT IN ('human','assistant') OR nullif(btrim(explanation),'') IS NULL
 THEN RAISE EXCEPTION 'DUPLICATE_REVIEW_FIELDS_REQUIRED'; END IF;
 SELECT * INTO p FROM ontology.duplicate_proposal WHERE proposal_id=id;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_DUPLICATE_PROPOSAL'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-duplicate-family:'||p.cluster_id,0));
 SELECT * INTO old FROM ontology.duplicate_decision WHERE review_id=review_uuid;
 IF FOUND THEN
  IF (old.proposal_id,old.decision,old.reviewer,old.reviewer_kind,old.notes) IS DISTINCT FROM (id,choice,who,kind,explanation)
  THEN RAISE EXCEPTION 'DUPLICATE_REVIEW_ID_CONFLICT'; END IF;
  RETURN old.decision_id;
 END IF;
 IF who=p.document->>'actor' THEN RAISE EXCEPTION 'INDEPENDENT_DUPLICATE_REVIEW_REQUIRED'; END IF;
 IF id IS DISTINCT FROM (SELECT proposal_id FROM ontology.duplicate_proposal WHERE cluster_id=p.cluster_id ORDER BY proposal_no DESC LIMIT 1)
 THEN RAISE EXCEPTION 'DUPLICATE_PROPOSAL_SUPERSEDED'; END IF;
 INSERT INTO ontology.duplicate_decision(review_id,proposal_id,decision,reviewer,reviewer_kind,notes)
 VALUES(review_uuid,id,choice,who,kind,explanation) RETURNING decision_id INTO result;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.duplicate_candidates_v1(id text,proposal_cut bigint,decision_cut bigint)
RETURNS TABLE(cluster_id uuid,proposal_id text,decision_id bigint,outcome text) LANGUAGE sql STABLE AS $$
 WITH latest AS (SELECT DISTINCT ON(cluster_id) * FROM ontology.duplicate_proposal WHERE proposal_no<=proposal_cut ORDER BY cluster_id,proposal_no DESC)
 SELECT p.cluster_id,p.proposal_id,d.decision_id,
  CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(p.source_binding) b LEFT JOIN ontology.release_revision m
    ON m.release_id=id AND m.entity_id=b->'revision'->>'entity_id' WHERE m.entity_id IS NULL) THEN 'MEMBER_OUTSIDE_RELEASE'
   WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(p.source_binding) b JOIN ontology.release_revision m
    ON m.release_id=id AND m.entity_id=b->'revision'->>'entity_id' WHERE m.revision_id IS DISTINCT FROM b->'revision'->>'revision_id') THEN 'SOURCE_CHANGED'
   WHEN d.decision='REJECT' THEN 'REJECTED' WHEN d.decision='ACCEPT' THEN 'ACCEPTED' ELSE 'PENDING' END
 FROM latest p LEFT JOIN LATERAL (SELECT * FROM ontology.duplicate_decision WHERE proposal_id=p.proposal_id
  AND decision_id<=decision_cut ORDER BY decision_id DESC LIMIT 1) d ON true
 WHERE EXISTS(SELECT 1 FROM ontology.release_revision m WHERE m.release_id=id AND p.document->'member_ids' ? m.entity_id)
$$;

CREATE OR REPLACE FUNCTION ontology.duplicate_member_candidates_v1(id text)
RETURNS SETOF ontology.duplicate_member LANGUAGE sql STABLE AS $$
 WITH accepted AS (
  SELECT s.cluster_id,s.proposal_id,s.decision_id,jsonb_array_elements_text(p.document->'member_ids') AS entity_id
  FROM ontology.duplicate_selection s JOIN ontology.duplicate_proposal p USING(proposal_id) WHERE s.release_id=id AND s.outcome='ACCEPTED')
 SELECT m.release_id,m.entity_id,m.revision_id,
  CASE WHEN a.cluster_id IS NULL THEN 'posting/'||m.entity_id ELSE 'duplicate/'||a.cluster_id END,
  a.cluster_id,a.proposal_id,a.decision_id
 FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id) LEFT JOIN accepted a ON a.entity_id=m.entity_id
 WHERE m.release_id=id AND r.kind='jobPosting'
$$;

CREATE OR REPLACE FUNCTION ontology.duplicate_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','reviewed-duplicate-groups-v1',
  'freeze',(SELECT to_jsonb(f) FROM ontology.duplicate_freeze f WHERE release_id=id),
  'posting_count',(SELECT count(*) FROM ontology.duplicate_member WHERE release_id=id),
  'group_count',(SELECT count(DISTINCT group_id) FROM ontology.duplicate_member WHERE release_id=id),
  'member_hash',ontology.hash(coalesce((SELECT jsonb_agg(m ORDER BY entity_id COLLATE "C") FROM ontology.duplicate_member m WHERE release_id=id),'[]')),
  'selection_hash',ontology.hash(coalesce((SELECT jsonb_agg(jsonb_build_object('selection',to_jsonb(s),'proposal',to_jsonb(p),'review',to_jsonb(d)) ORDER BY s.cluster_id)
   FROM ontology.duplicate_selection s JOIN ontology.duplicate_proposal p USING(proposal_id)
   LEFT JOIN ontology.duplicate_decision d USING(decision_id) WHERE s.release_id=id),'[]')))
$$;

CREATE OR REPLACE FUNCTION ontology.verify_duplicates_v1(id text) RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE f ontology.duplicate_freeze%ROWTYPE; p ontology.duplicate_proposal%ROWTYPE; BEGIN
 SELECT * INTO f FROM ontology.duplicate_freeze WHERE release_id=id;
 IF NOT FOUND THEN
  IF EXISTS(SELECT 1 FROM ontology.duplicate_member WHERE release_id=id) OR EXISTS(SELECT 1 FROM ontology.duplicate_membership WHERE release_id=id)
   OR EXISTS(SELECT 1 FROM ontology.duplicate_selection WHERE release_id=id) THEN RAISE EXCEPTION 'DUPLICATE_FREEZE_REQUIRED'; END IF;
  RETURN;
 END IF;
 PERFORM ontology.check_frozen_sources(id); PERFORM ontology.verify_observation_membership_v1(id);
 IF EXISTS((SELECT cluster_id,proposal_id,decision_id,outcome FROM ontology.duplicate_selection WHERE release_id=id EXCEPT
    SELECT * FROM ontology.duplicate_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff)) UNION ALL
   (SELECT * FROM ontology.duplicate_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff) EXCEPT
    SELECT cluster_id,proposal_id,decision_id,outcome FROM ontology.duplicate_selection WHERE release_id=id))
 THEN RAISE EXCEPTION 'DUPLICATE_SELECTION_CHANGED'; END IF;
 FOR p IN SELECT * FROM ontology.duplicate_proposal WHERE proposal_id IN (SELECT proposal_id FROM ontology.duplicate_selection WHERE release_id=id) LOOP
  IF p.source_binding IS DISTINCT FROM ontology.duplicate_source_v1(p.created_in_release,p.document->'member_ids')
   OR p.proposal_id<>ontology.hash(jsonb_build_object('document',p.document-'release_id','source_binding',p.source_binding))
   OR p.document->>'source_binding_hash' IS DISTINCT FROM ontology.hash(p.source_binding)
   OR p.document->>'cluster_id' IS DISTINCT FROM p.cluster_id::text OR p.document->>'parent_id' IS DISTINCT FROM p.parent_id
   OR p.document->>'release_id' IS DISTINCT FROM p.created_in_release
  THEN RAISE EXCEPTION 'DUPLICATE_PROPOSAL_CHANGED'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM ontology.duplicate_member_candidates_v1(id) GROUP BY entity_id HAVING count(*)>1)
 THEN RAISE EXCEPTION 'OVERLAPPING_ACCEPTED_DUPLICATE_CLUSTERS'; END IF;
 IF EXISTS((SELECT * FROM ontology.duplicate_member WHERE release_id=id EXCEPT SELECT * FROM ontology.duplicate_member_candidates_v1(id))
  UNION ALL (SELECT * FROM ontology.duplicate_member_candidates_v1(id) EXCEPT SELECT * FROM ontology.duplicate_member WHERE release_id=id))
 THEN RAISE EXCEPTION 'DUPLICATE_MEMBERS_CHANGED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ontology.duplicate_membership WHERE release_id=id AND manifest=ontology.duplicate_manifest_v1(id) AND manifest_hash=ontology.hash(manifest))
 THEN RAISE EXCEPTION 'DUPLICATE_MEMBERSHIP_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.freeze_duplicates_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE manifest jsonb; BEGIN
 PERFORM ontology.require_preparing(id);
 IF EXISTS(SELECT 1 FROM ontology.duplicate_freeze WHERE release_id=id) THEN PERFORM ontology.verify_duplicates_v1(id);RETURN; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest_hash IS NOT NULL)
 THEN RAISE EXCEPTION 'DUPLICATE_RELEASE_ALREADY_SEALED'; END IF;
 PERFORM ontology.check_frozen_sources(id); PERFORM ontology.verify_observation_membership_v1(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.release_revision WHERE release_id=id) THEN RAISE EXCEPTION 'ASSEMBLE_SOURCE_REVISIONS_FIRST'; END IF;
 LOCK TABLE ontology.duplicate_proposal,ontology.duplicate_decision IN SHARE MODE;
 INSERT INTO ontology.duplicate_freeze(release_id,proposal_cutoff,decision_cutoff)
 SELECT id,(SELECT coalesce(max(proposal_no),0) FROM ontology.duplicate_proposal),(SELECT coalesce(max(decision_id),0) FROM ontology.duplicate_decision);
 INSERT INTO ontology.duplicate_selection SELECT id,c.* FROM ontology.duplicate_freeze f
  CROSS JOIN LATERAL ontology.duplicate_candidates_v1(id,f.proposal_cutoff,f.decision_cutoff) c WHERE f.release_id=id;
 IF EXISTS(SELECT 1 FROM ontology.duplicate_member_candidates_v1(id) GROUP BY entity_id HAVING count(*)>1)
 THEN RAISE EXCEPTION 'OVERLAPPING_ACCEPTED_DUPLICATE_CLUSTERS'; END IF;
 INSERT INTO ontology.duplicate_member SELECT * FROM ontology.duplicate_member_candidates_v1(id);
 manifest:=ontology.duplicate_manifest_v1(id);
 INSERT INTO ontology.duplicate_membership VALUES(id,manifest,ontology.hash(manifest));
 PERFORM ontology.verify_duplicates_v1(id);
END $$;

-- A future cohort/graph adapter must carry this membership before a frozen
-- duplicate release can be sealed. Existing releases without a freeze are unchanged.
CREATE OR REPLACE FUNCTION ontology.duplicate_release_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.manifest IS NOT NULL AND EXISTS(SELECT 1 FROM ontology.duplicate_freeze WHERE release_id=NEW.release_id) THEN
  PERFORM ontology.verify_duplicates_v1(NEW.release_id);
  IF NEW.manifest->'duplicate_membership' IS DISTINCT FROM (SELECT to_jsonb(m) FROM ontology.duplicate_membership m WHERE release_id=NEW.release_id)
  THEN RAISE EXCEPTION 'DUPLICATE_GRAPH_INTEGRATION_REQUIRED'; END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_duplicate_release_guard' AND tgrelid='ontology.corpus_release'::regclass) THEN
  CREATE TRIGGER ontology_duplicate_release_guard BEFORE INSERT OR UPDATE OF manifest ON ontology.corpus_release
  FOR EACH ROW EXECUTE FUNCTION ontology.duplicate_release_guard_v1();
 END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.query_duplicate_input_v1(choice text,family uuid,members text[],preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; source jsonb; canonical jsonb; current ontology.duplicate_proposal%ROWTYPE; BEGIN
 id:=ontology.read_release_v1(choice,preview);
 IF family IS NULL THEN RAISE EXCEPTION 'INVALID_DUPLICATE_CLUSTER_ID'; END IF;
 SELECT jsonb_agg(m ORDER BY m COLLATE "C") INTO canonical FROM (SELECT DISTINCT unnest(members) m) x;
 source:=ontology.duplicate_source_v1(id,canonical);
 SELECT * INTO current FROM ontology.duplicate_proposal WHERE cluster_id=family ORDER BY proposal_no DESC LIMIT 1;
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('contract','reviewed-duplicate-groups-v1',
  'source_binding',source,'source_binding_hash',ontology.hash(source),
  'current_proposal',CASE WHEN current.proposal_id IS NULL THEN NULL ELSE to_jsonb(current) END,
  'current_decision',(SELECT to_jsonb(d) FROM ontology.duplicate_decision d WHERE d.proposal_id=current.proposal_id ORDER BY decision_id DESC LIMIT 1),
  'proposal_template',jsonb_build_object('schema_version','hop-duplicate-proposal-v1','release_id',id,'cluster_id',family,
   'parent_id',current.proposal_id,'member_ids',canonical,'source_binding_hash',ontology.hash(source),
   'actor','','actor_kind','human','method','MANUAL','model_id',NULL,'prompt_version',NULL,'resolver_version','','reason',''),
  'notice','Current proposal/decision are editing context, not a frozen release selection. Title equality alone is not proof of duplication.');
END $$;

CREATE OR REPLACE FUNCTION ontology.query_duplicates_v1(choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; BEGIN
 id:=ontology.read_release_v1(choice,preview);PERFORM ontology.verify_duplicates_v1(id);
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('contract','reviewed-duplicate-groups-v1',
  'selection_status',CASE WHEN EXISTS(SELECT 1 FROM ontology.duplicate_freeze WHERE release_id=id) THEN 'FROZEN' ELSE 'NOT_FROZEN' END,
  'membership',(SELECT to_jsonb(m) FROM ontology.duplicate_membership m WHERE release_id=id),
  'selections',coalesce((SELECT jsonb_agg(jsonb_build_object('selection',to_jsonb(s),'proposal',to_jsonb(p),'review',to_jsonb(d),
   'review_status',CASE WHEN s.outcome='ACCEPTED' THEN CASE d.reviewer_kind WHEN 'human' THEN 'HUMAN_ACCEPTED' ELSE 'ASSISTANT_REVIEWED' END ELSE s.outcome END,
   'confidence',NULL,'confidence_state','UNASSESSED') ORDER BY s.cluster_id)
   FROM ontology.duplicate_selection s JOIN ontology.duplicate_proposal p USING(proposal_id)
   LEFT JOIN ontology.duplicate_decision d USING(decision_id) WHERE s.release_id=id),'[]'),
  'members',coalesce((SELECT jsonb_agg(to_jsonb(m)||jsonb_build_object('name',r.name) ORDER BY m.entity_id COLLATE "C")
   FROM ontology.duplicate_member m JOIN ontology.revision r USING(revision_id) WHERE m.release_id=id),'[]'),
  'current_candidates',CASE WHEN NOT EXISTS(SELECT 1 FROM ontology.duplicate_freeze WHERE release_id=id)
   THEN coalesce((SELECT jsonb_agg(to_jsonb(c) ORDER BY cluster_id) FROM ontology.duplicate_candidates_v1(id,
    (SELECT coalesce(max(proposal_no),0) FROM ontology.duplicate_proposal),(SELECT coalesce(max(decision_id),0) FROM ontology.duplicate_decision)) c),'[]') ELSE NULL END,
  'notice','Groups preserve every source posting. An ungrouped posting is not proof of uniqueness. Representative selection, cohort eligibility, statistics and graph/publication integration remain separate.');
END $$;
COMMIT;
