-- Bind every observed posting to an exact canonical revision, including postings
-- absent from the current full snapshot. No model calls or review acceptance.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.historical_posting_payload_v1(n jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT (n-'kind')||jsonb_build_object('organization_id',ontology.iri('organization','alio:'||(n->>'organization_code')),
  'source_status',CASE n->>'ongoing' WHEN 'true' THEN 'OPEN' WHEN 'false' THEN 'CLOSED' ELSE 'UNKNOWN' END,
  'date_precision','DAY','primary_occupation_id',NULL,'name',n->>'title','aliases',jsonb_build_array(n->>'title'),
  'preferred_label_policy','source-priority-observed-frequency-v1')
$$;

CREATE OR REPLACE FUNCTION ontology.bound_observation_candidates_v1(id text)
RETURNS SETOF ontology.entity_observation_state LANGUAGE sql STABLE AS $$
 WITH states AS (
 SELECT o.release_id,o.entity_id,m.revision_id AS selected_revision_id,'jobPosting'::text AS entity_type,
  'job_alio'::text AS source_id,f.through_run_id AS connector_run_id,o.content_run_id,
  o.first_seen_at,o.last_seen_at,o.consecutive_absence_count,o.serving_state,o.state_reason,
  f.evaluated_at,'posting-observation-membership-v1'::text AS methodology_version
 FROM ontology.posting_observation o JOIN ontology.observation_freeze f USING(release_id)
 JOIN ontology.release_revision m USING(release_id,entity_id) WHERE o.release_id=id
 ) SELECT ontology.hash(to_jsonb(s)),s.* FROM states s
$$;

CREATE OR REPLACE FUNCTION ontology.observation_membership_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','posting-observation-membership-v1','release_id',id,
  'observation_freeze_hash',(SELECT manifest_hash FROM ontology.observation_freeze WHERE release_id=id),
  'observation_freeze',(SELECT to_jsonb(f) FROM ontology.observation_freeze f WHERE release_id=id),
  'source_runs',(SELECT jsonb_agg(r ORDER BY role,source_id,run_id COLLATE "C") FROM ontology.release_source_run r WHERE release_id=id),
  'state_count',(SELECT count(*) FROM ontology.entity_observation_state WHERE release_id=id),
  'state_hash',(SELECT ontology.hash(coalesce(jsonb_agg(s ORDER BY entity_id COLLATE "C"),'[]')) FROM ontology.entity_observation_state s WHERE release_id=id),
  'historical_record_hash',(SELECT ontology.hash(coalesce(jsonb_agg(i ORDER BY i.record_id),'[]')) FROM ontology.input_record i
   JOIN ontology.release_source_run r USING(release_id,run_id) WHERE i.release_id=id AND r.role='HISTORICAL'),
  'historical_support_hash',(SELECT ontology.hash(coalesce(jsonb_agg(s ORDER BY s.entity_id COLLATE "C",s.record_id),'[]')) FROM ontology.revision_support s
   JOIN ontology.input_record i USING(release_id,record_id) JOIN ontology.release_source_run r USING(release_id,run_id) WHERE s.release_id=id AND r.role='HISTORICAL'),
  'historical_relation_hash',(SELECT ontology.hash(coalesce(jsonb_agg(s ORDER BY s.relation_id COLLATE "C",s.record_id),'[]')) FROM ontology.release_relation s
   JOIN ontology.input_record i USING(release_id,record_id) JOIN ontology.release_source_run r USING(release_id,run_id) WHERE s.release_id=id AND r.role='HISTORICAL'))
$$;

CREATE OR REPLACE FUNCTION ontology.verify_observation_membership_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE manifest jsonb; chosen ontology.observation_membership; frozen ontology.observation_freeze;
BEGIN
 SELECT * INTO chosen FROM ontology.observation_membership WHERE release_id=id;
 IF NOT FOUND THEN
  IF EXISTS(SELECT 1 FROM ontology.observation_freeze WHERE release_id=id) OR
   EXISTS(SELECT 1 FROM ontology.release_source_run WHERE release_id=id AND role='HISTORICAL')
  THEN RAISE EXCEPTION 'BIND_OBSERVATION_MEMBERSHIP_FIRST'; END IF;
  RETURN; -- Older source/review fixtures remain readable; publication is gated separately.
 END IF;
 SELECT * INTO STRICT frozen FROM ontology.observation_freeze WHERE release_id=id;
 IF frozen.evaluated_at IS DISTINCT FROM (SELECT created_at FROM ontology.corpus_release WHERE release_id=id)
 THEN RAISE EXCEPTION 'CANONICAL_OBSERVATION_REQUIRES_RELEASE_CREATION_TIME'; END IF;
 IF frozen.manifest_hash IS DISTINCT FROM ontology.hash(frozen.manifest) OR frozen.manifest->>'observation_hash' IS DISTINCT FROM
  (SELECT ontology.hash(coalesce(jsonb_agg(o ORDER BY entity_id COLLATE "C"),'[]')) FROM ontology.posting_observation o WHERE release_id=id)
 THEN RAISE EXCEPTION 'FROZEN_OBSERVATION_CONTENT_CHANGED'; END IF;
 IF frozen.manifest->'runs' IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_object('run_id',o.run_id,'watermark_at',o.watermark_at,
   'source_fingerprint',o.source_fingerprint,'posting_count',o.posting_count,'census_hash',o.census_hash) ORDER BY m.ordinal)
   FROM ontology.observation_history_member m JOIN ontology.observation_run o USING(run_id) WHERE m.release_id=id)
 THEN RAISE EXCEPTION 'FROZEN_OBSERVATION_HISTORY_CHANGED'; END IF;
 IF EXISTS((SELECT * FROM ontology.bound_observation_candidates_v1(id) EXCEPT SELECT * FROM ontology.entity_observation_state WHERE release_id=id)
  UNION ALL (SELECT * FROM ontology.entity_observation_state WHERE release_id=id EXCEPT SELECT * FROM ontology.bound_observation_candidates_v1(id)))
 THEN RAISE EXCEPTION 'OBSERVATION_REVISION_BINDING_CHANGED'; END IF;
 IF (SELECT count(*) FROM ontology.entity_observation_state WHERE release_id=id)<>(SELECT count(*) FROM ontology.posting_observation WHERE release_id=id)
  OR (SELECT count(*) FROM ontology.entity_observation_state WHERE release_id=id)<>
   (SELECT count(*) FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id=id AND v.kind='jobPosting')
 THEN RAISE EXCEPTION 'ONE_OBSERVATION_PER_RELEASE_POSTING_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.posting_observation o JOIN ontology.release_revision m USING(release_id,entity_id)
  JOIN ontology.revision v USING(revision_id) JOIN ontology.posting_seen s ON s.run_id=o.content_run_id AND s.posting_id=o.posting_id
  WHERE o.release_id=id AND (v.kind<>'jobPosting' OR v.payload IS DISTINCT FROM ontology.historical_posting_payload_v1(s.normalized)))
 THEN RAISE EXCEPTION 'OBSERVATION_SELECTED_CONTENT_MISMATCH'; END IF;
 -- No extra old record may enter through the generalized membership FK.
 IF EXISTS(SELECT 1 FROM ontology.input_record i JOIN ontology.release_source_run r USING(release_id,run_id)
  WHERE i.release_id=id AND r.role='HISTORICAL' AND NOT EXISTS(
   SELECT 1 FROM ontology.posting_observation o JOIN ontology.posting_seen s ON s.run_id=o.content_run_id AND s.posting_id=o.posting_id
   WHERE o.release_id=id AND NOT o.present_in_selected_run AND i.run_id=s.run_id AND i.record_id IN (s.list_record_id,s.detail_record_id)))
  OR (SELECT count(*) FROM ontology.input_record i JOIN ontology.release_source_run r USING(release_id,run_id) WHERE i.release_id=id AND r.role='HISTORICAL')<>
   2*(SELECT count(*) FROM ontology.posting_observation WHERE release_id=id AND NOT present_in_selected_run)
 THEN RAISE EXCEPTION 'HISTORICAL_INPUT_MEMBERSHIP_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.input_record i JOIN ontology.release_source_run s USING(release_id,run_id)
  JOIN ingestion.record r ON r.record_id=i.record_id JOIN ingestion.document d ON d.run_id=r.run_id AND d.document_id=r.document_id
  WHERE i.release_id=id AND s.role='HISTORICAL' AND (i.source_id<>s.source_id OR i.run_id<>r.run_id OR i.document_id<>r.document_id
   OR i.locator<>r.locator OR i.source_record_id<>r.source_record_id OR i.normalized IS DISTINCT FROM r.normalized
   OR i.normalized_hash<>ontology.hash(r.normalized) OR i.field_lineage IS DISTINCT FROM r.field_lineage OR i.raw_sha256<>d.raw_sha256))
 THEN RAISE EXCEPTION 'HISTORICAL_SOURCE_COPY_CHANGED'; END IF;
 manifest:=ontology.observation_membership_manifest_v1(id);
 IF chosen.manifest IS DISTINCT FROM manifest OR chosen.manifest_hash IS DISTINCT FROM ontology.hash(manifest)
 THEN RAISE EXCEPTION 'OBSERVATION_MEMBERSHIP_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.bind_observations_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE created timestamptz; frozen ontology.observation_freeze; manifest jsonb;
BEGIN
 PERFORM ontology.require_preparing(id);PERFORM ontology.check_frozen_sources(id);
 IF EXISTS(SELECT 1 FROM ontology.observation_membership WHERE release_id=id) THEN
  PERFORM ontology.verify_observation_membership_v1(id);RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) OR EXISTS(SELECT 1 FROM ontology.document_input_set WHERE release_id=id)
 THEN RAISE EXCEPTION 'BIND_OBSERVATIONS_BEFORE_INPUTS_OR_REVIEWS'; END IF;
 SELECT created_at INTO STRICT created FROM ontology.corpus_release WHERE release_id=id;
 -- Freeze at release creation, per the canonical observation contract. Existing
 -- manual previews with another cutoff remain unchanged and require a new release.
 PERFORM ontology.freeze_observations_v1(id,created);
 SELECT * INTO STRICT frozen FROM ontology.observation_freeze WHERE release_id=id;
 CREATE TEMP TABLE historical_posting ON COMMIT DROP AS
 SELECT s.*,ontology.historical_posting_payload_v1(s.normalized) AS payload
 FROM ontology.posting_observation o JOIN ontology.posting_seen s ON s.run_id=o.content_run_id AND s.posting_id=o.posting_id
 WHERE o.release_id=id AND NOT o.present_in_selected_run;
 INSERT INTO ontology.release_source_run
 SELECT DISTINCT id,r.run_id,r.source_id,'HISTORICAL',r.watermark_at,r.source_fingerprint FROM historical_posting s JOIN ontology.observation_run r USING(run_id)
 ON CONFLICT DO NOTHING;
 INSERT INTO ontology.input_record
 SELECT id,r.record_id,'job_alio',r.run_id,r.document_id,r.locator,r.source_record_id,r.normalized,ontology.hash(r.normalized),r.field_lineage,d.raw_sha256
 FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
 WHERE r.record_id IN (SELECT list_record_id FROM historical_posting UNION SELECT detail_record_id FROM historical_posting) ON CONFLICT DO NOTHING;
 -- Current institution revisions win. If the institution itself vanished, retain
 -- a deterministic source-derived fallback with all observed historical names.
 CREATE TEMP TABLE historical_object ON COMMIT DROP AS
 WITH organization_names AS (
  SELECT ontology.iri('organization','alio:'||(normalized->>'organization_code')) entity_id,
   'alio:'||(normalized->>'organization_code') code,normalized->>'organization_name' name,count(*) frequency
  FROM ontology.input_record i JOIN ontology.release_source_run r USING(release_id,run_id)
  WHERE i.release_id=id AND r.role='HISTORICAL' GROUP BY 1,2,3
 ), chosen AS (SELECT *,row_number() OVER(PARTITION BY entity_id ORDER BY frequency DESC,name COLLATE "C") rn FROM organization_names),
 aliases AS (SELECT entity_id,jsonb_agg(name ORDER BY name COLLATE "C") names FROM organization_names GROUP BY entity_id)
 SELECT s.entity_id,'jobPosting'::text kind,'job_alio:'||s.posting_id code,s.normalized->>'title' name,s.payload FROM historical_posting s
 UNION ALL
 SELECT c.entity_id,'organization',c.code,c.name,jsonb_build_object('code',substring(c.code FROM 6),'name',c.name,'employer_type','UNKNOWN',
  'aliases',a.names,'preferred_label_policy','source-priority-observed-frequency-v1')
 FROM chosen c JOIN aliases a USING(entity_id) WHERE rn=1 AND NOT EXISTS(SELECT 1 FROM ontology.release_revision m WHERE m.release_id=id AND m.entity_id=c.entity_id);
 IF EXISTS(SELECT 1 FROM historical_object WHERE entity_id IS NULL OR name IS NULL OR btrim(name)='') THEN RAISE EXCEPTION 'INVALID_HISTORICAL_SOURCE_IDENTITY'; END IF;
 IF EXISTS(SELECT 1 FROM historical_object h JOIN ontology.entity e USING(entity_id) WHERE h.kind<>e.kind OR h.code<>e.code) THEN RAISE EXCEPTION 'ONTOLOGY_IDENTITY_CONFLICT'; END IF;
 INSERT INTO ontology.entity(entity_id,kind,code) SELECT entity_id,kind,code FROM historical_object ON CONFLICT DO NOTHING;
 INSERT INTO ontology.revision(revision_id,entity_id,kind,name,payload,payload_hash)
 SELECT ontology.hash(jsonb_build_array(entity_id,'hop-ontology-v1',payload)),entity_id,kind,name,payload,ontology.hash(payload)
 FROM historical_object ON CONFLICT DO NOTHING;
 IF EXISTS(SELECT 1 FROM historical_object h JOIN ontology.revision v ON v.revision_id=ontology.hash(jsonb_build_array(h.entity_id,'hop-ontology-v1',h.payload))
  WHERE v.entity_id<>h.entity_id OR v.kind<>h.kind OR v.name<>h.name OR v.payload<>h.payload OR v.payload_hash<>ontology.hash(h.payload))
 THEN RAISE EXCEPTION 'ONTOLOGY_REVISION_CONTENT_CONFLICT'; END IF;
 INSERT INTO ontology.release_revision SELECT id,entity_id,ontology.hash(jsonb_build_array(entity_id,'hop-ontology-v1',payload)) FROM historical_object ON CONFLICT DO NOTHING;
 INSERT INTO ontology.revision_support
 SELECT id,s.entity_id,r.record_id,ARRAY(SELECT jsonb_object_keys(s.normalized) ORDER BY 1)
 FROM historical_posting s JOIN ontology.input_record r ON r.release_id=id AND r.record_id IN (s.list_record_id,s.detail_record_id) ON CONFLICT DO NOTHING;
 INSERT INTO ontology.revision_support
 SELECT id,ontology.iri('organization','alio:'||(i.normalized->>'organization_code')),i.record_id,ARRAY['organization_code','organization_name']
 FROM ontology.input_record i JOIN ontology.release_source_run r USING(release_id,run_id) WHERE i.release_id=id AND r.role='HISTORICAL' ON CONFLICT DO NOTHING;
 CREATE TEMP TABLE historical_relation ON COMMIT DROP AS
 SELECT i.record_id,s.entity_id,'POSTED_BY'::text predicate,s.payload->>'organization_id' organization_id,ARRAY['posting_id','organization_code'] fields,
  ontology.hash(jsonb_build_array(s.entity_id,'POSTED_BY',s.payload->>'organization_id','{}'::jsonb,'source-reference-v1')) relation_id
 FROM historical_posting s JOIN ontology.input_record i ON i.release_id=id AND i.record_id IN (s.list_record_id,s.detail_record_id)
 WHERE i.normalized->>'organization_code'=s.normalized->>'organization_code';
 INSERT INTO ontology.source_relation(relation_id,subject_id,predicate,object_id)
 SELECT DISTINCT relation_id,entity_id,predicate,organization_id FROM historical_relation ON CONFLICT DO NOTHING;
 IF EXISTS(SELECT 1 FROM historical_relation h JOIN ontology.source_relation r USING(relation_id) WHERE r.subject_id<>h.entity_id OR r.predicate<>h.predicate OR r.object_id<>h.organization_id OR r.qualifiers<>'{}')
 THEN RAISE EXCEPTION 'ONTOLOGY_RELATION_CONTENT_CONFLICT'; END IF;
 INSERT INTO ontology.release_relation SELECT id,relation_id,record_id,fields FROM historical_relation ON CONFLICT DO NOTHING;
 -- Insert the parent before its states, then freeze the exact manifest without
 -- updating either table: the expected hash is derived from the same candidates.
 SELECT ontology.observation_membership_manifest_v1(id)||jsonb_build_object(
  'state_count',count(*),'state_hash',ontology.hash(coalesce(jsonb_agg(s ORDER BY entity_id COLLATE "C"),'[]')))
 INTO manifest FROM ontology.bound_observation_candidates_v1(id) s;
 INSERT INTO ontology.observation_membership(release_id,manifest,manifest_hash) VALUES(id,manifest,ontology.hash(manifest));
 INSERT INTO ontology.entity_observation_state SELECT * FROM ontology.bound_observation_candidates_v1(id);
 PERFORM ontology.check_frozen_sources(id);PERFORM ontology.verify_observation_membership_v1(id);
END $$;

CREATE OR REPLACE FUNCTION ontology.query_posting_states_v1(choice text,preview boolean DEFAULT false) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; BEGIN
 id:=ontology.read_release_v1(choice,preview);
 IF NOT EXISTS(SELECT 1 FROM ontology.observation_membership WHERE release_id=id) THEN RAISE EXCEPTION 'BIND_OBSERVATION_MEMBERSHIP_FIRST'; END IF;
 PERFORM ontology.verify_observation_membership_v1(id);
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('observation_contract','posting-observation-membership-v1',
  'membership',(SELECT to_jsonb(m) FROM ontology.observation_membership m WHERE release_id=id),
  'states',coalesce((SELECT jsonb_agg(to_jsonb(s)||jsonb_build_object('posting_name',v.name) ORDER BY s.entity_id COLLATE "C")
   FROM ontology.entity_observation_state s JOIN ontology.revision v ON v.revision_id=s.selected_revision_id WHERE s.release_id=id),'[]'));
END $$;
COMMIT;
