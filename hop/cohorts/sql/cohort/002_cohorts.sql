BEGIN;
CREATE TABLE IF NOT EXISTS ontology.posting_cohort (
 cohort_id text PRIMARY KEY,release_id text NOT NULL REFERENCES ontology.corpus_release,
 occupation_id text NOT NULL REFERENCES ontology.entity,occupation_revision_id text NOT NULL REFERENCES ontology.revision,
 as_of date NOT NULL,window_start date NOT NULL,window_end date NOT NULL,
 methodology_version text NOT NULL CHECK(methodology_version='posting-cohort-job-alio-v1'),
 filter jsonb NOT NULL,filter_hash text NOT NULL CHECK(filter_hash=ontology.hash(filter)),
 dependency_binding jsonb NOT NULL,dependency_hash text NOT NULL CHECK(dependency_hash=ontology.hash(dependency_binding)),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(release_id,occupation_id,as_of,methodology_version),CHECK(window_start=as_of-179 AND window_end=as_of)
);
CREATE TABLE IF NOT EXISTS ontology.posting_cohort_posting (
 cohort_id text NOT NULL REFERENCES ontology.posting_cohort,entity_id text NOT NULL REFERENCES ontology.entity,
 posting_revision_id text NOT NULL REFERENCES ontology.revision,posting_id text NOT NULL,source_id text NOT NULL,
 group_id text NOT NULL,cluster_id uuid,representative_id text REFERENCES ontology.entity,
 outcome text NOT NULL CHECK(outcome IN ('INCLUDED','DUPLICATE','EXCLUDED')),exclusion_reasons jsonb NOT NULL,
 temporal_basis jsonb NOT NULL,language_metrics jsonb NOT NULL,selection_basis jsonb NOT NULL,
 PRIMARY KEY(cohort_id,entity_id)
);
CREATE TABLE IF NOT EXISTS ontology.posting_cohort_track (
 cohort_id text NOT NULL,entity_id text NOT NULL,position_id text NOT NULL REFERENCES ontology.position_claim,
 profile_proposal_id text NOT NULL REFERENCES ontology.cohort_profile_proposal,profile_decision_id bigint NOT NULL REFERENCES ontology.cohort_profile_decision,
 profile jsonb NOT NULL,exclusion_reasons jsonb NOT NULL,eligible boolean NOT NULL,included_in_cohort boolean NOT NULL,
 PRIMARY KEY(cohort_id,entity_id,position_id),FOREIGN KEY(cohort_id,entity_id) REFERENCES ontology.posting_cohort_posting
);
CREATE TABLE IF NOT EXISTS ontology.posting_cohort_claim (
 cohort_id text NOT NULL,entity_id text NOT NULL,position_id text NOT NULL,claim_id text NOT NULL,
 normalization_id text NOT NULL REFERENCES ontology.requirement_normalization,decision_id bigint NOT NULL REFERENCES ontology.requirement_decision,
 source_claim_id text NOT NULL REFERENCES ontology.claim,node_index integer NOT NULL,requirement_key text NOT NULL,
 requirement_scope text NOT NULL,requirement_kind text NOT NULL,necessity text NOT NULL,polarity text NOT NULL,
 PRIMARY KEY(cohort_id,entity_id,position_id,claim_id),FOREIGN KEY(cohort_id,entity_id,position_id) REFERENCES ontology.posting_cohort_track
);
CREATE TABLE IF NOT EXISTS ontology.posting_cohort_manifest (
 cohort_id text PRIMARY KEY REFERENCES ontology.posting_cohort,manifest jsonb NOT NULL,
 manifest_hash text NOT NULL CHECK(manifest_hash=ontology.hash(manifest))
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['posting_cohort','posting_cohort_posting','posting_cohort_track','posting_cohort_claim','posting_cohort_manifest'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=('ontology.'||name)::regclass AND tgname='ontology_immutable_'||name) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_posting_candidates_v1(id text,occupation text,as_of date)
RETURNS TABLE(entity_id text,posting_revision_id text,posting_id text,source_id text,group_id text,cluster_id uuid,
 representative_id text,outcome text,exclusion_reasons jsonb,temporal_basis jsonb,language_metrics jsonb,selection_basis jsonb)
LANGUAGE sql STABLE AS $$
 WITH raw AS MATERIALIZED (
  SELECT m.entity_id,m.revision_id,r.payload->>'posting_id' posting_id,st.source_id,d.group_id,d.cluster_id,
   ontology.cohort_temporal_v1(r.payload,o.last_seen_at) temporal,ontology.cohort_language_v1(r.payload) language,
   os.outcome occupation_outcome,po.occupation_id,ps.outcome profile_outcome,
   EXISTS(SELECT 1 FROM ontology.cohort_profile_track t WHERE t.release_id=id AND t.entity_id=m.entity_id AND t.exclusion_reasons='[]') eligible_track,
   jsonb_build_object('occupation_selection',to_jsonb(os),'profile_selection',to_jsonb(ps),'duplicate_membership',to_jsonb(d),
    'observation',to_jsonb(o),'observation_state_id',st.observation_state_id,'payload_hash',r.payload_hash) basis
  FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
  JOIN ontology.entity_observation_state st ON st.release_id=m.release_id AND st.entity_id=m.entity_id
  JOIN ontology.posting_observation o ON o.release_id=m.release_id AND o.entity_id=m.entity_id
  JOIN ontology.duplicate_member d ON d.release_id=m.release_id AND d.entity_id=m.entity_id
  JOIN ontology.occupation_selection os ON os.release_id=m.release_id AND os.entity_id=m.entity_id
  LEFT JOIN ontology.primary_product_occupation po ON po.release_id=m.release_id AND po.entity_id=m.entity_id
  JOIN ontology.cohort_profile_selection ps ON ps.release_id=m.release_id AND ps.entity_id=m.entity_id
  WHERE m.release_id=id AND r.kind='jobPosting'
 ), evaluated AS MATERIALIZED (
  SELECT x.*,coalesce((SELECT jsonb_agg(reason ORDER BY reason COLLATE "C") FROM (
   SELECT DISTINCT reason FROM (
    SELECT 'SOURCE_OUTSIDE_SCOPE' reason WHERE x.source_id<>'job_alio'
    UNION ALL SELECT 'OCCUPATION_'||x.occupation_outcome WHERE x.occupation_outcome<>'MATCHED'
    UNION ALL SELECT 'OTHER_OCCUPATION' WHERE x.occupation_id IS NOT NULL AND x.occupation_id<>occupation
    UNION ALL SELECT x.temporal->>'date_issue' WHERE x.temporal->>'date_issue' IS NOT NULL
    UNION ALL SELECT 'BEFORE_WINDOW' WHERE (x.temporal->>'published_on')::date<as_of-179
    UNION ALL SELECT 'AFTER_AS_OF' WHERE (x.temporal->>'published_on')::date>as_of
    UNION ALL SELECT x.temporal->>'ordering_issue' WHERE x.temporal->>'ordering_issue' IS NOT NULL
    UNION ALL SELECT 'KOREAN_CONTENT_NOT_ESTABLISHED' WHERE NOT (x.language->>'eligible')::boolean
    UNION ALL SELECT 'PROFILE_'||x.profile_outcome WHERE x.profile_outcome<>'REVIEWED'
    UNION ALL SELECT 'NO_QUALIFYING_TRACK' WHERE x.profile_outcome='REVIEWED' AND NOT x.eligible_track
    UNION ALL SELECT jsonb_array_elements_text(t.exclusion_reasons) FROM ontology.cohort_profile_track t
     WHERE t.release_id=id AND t.entity_id=x.entity_id AND x.profile_outcome='REVIEWED' AND NOT x.eligible_track
   ) flags
  ) distinct_flags),'[]') reasons FROM raw x
 ), reps AS (
  SELECT DISTINCT ON(group_id) group_id,entity_id FROM evaluated WHERE reasons='[]'
  ORDER BY group_id,(temporal->>'ordering_at')::timestamptz DESC,
   CASE source_id WHEN 'job_alio' THEN 0 WHEN 'saramin' THEN 1 ELSE 2 END,posting_id COLLATE "C",entity_id COLLATE "C"
 )
 SELECT e.entity_id,e.revision_id,e.posting_id,e.source_id,e.group_id,e.cluster_id,r.entity_id,
  CASE WHEN e.reasons<>'[]' THEN 'EXCLUDED' WHEN e.entity_id=r.entity_id THEN 'INCLUDED' ELSE 'DUPLICATE' END,
  CASE WHEN e.reasons='[]' AND e.entity_id<>r.entity_id THEN jsonb_build_array('DUPLICATE_NON_REPRESENTATIVE') ELSE e.reasons END,
  e.temporal,e.language,e.basis FROM evaluated e LEFT JOIN reps r USING(group_id)
$$;

CREATE OR REPLACE FUNCTION ontology.cohort_track_candidates_v1(key text) RETURNS SETOF ontology.posting_cohort_track LANGUAGE sql STABLE AS $$
 SELECT key,m.entity_id,t.position_id,t.proposal_id,t.decision_id,t.profile,t.exclusion_reasons,t.exclusion_reasons='[]',
  m.outcome='INCLUDED' AND t.exclusion_reasons='[]'
 FROM ontology.posting_cohort c JOIN ontology.posting_cohort_posting m USING(cohort_id)
 JOIN ontology.cohort_profile_track t ON t.release_id=c.release_id AND t.entity_id=m.entity_id WHERE c.cohort_id=key
$$;
CREATE OR REPLACE FUNCTION ontology.cohort_claim_candidates_v1(key text) RETURNS SETOF ontology.posting_cohort_claim LANGUAGE sql STABLE AS $$
 SELECT key,t.entity_id,t.position_id,r.claim_id,r.normalization_id,r.decision_id,r.source_claim_id,r.node_index,
  r.requirement_key,r.requirement_scope,r.requirement_kind,r.necessity,r.polarity
 FROM ontology.posting_cohort c JOIN ontology.posting_cohort_track t USING(cohort_id)
 CROSS JOIN LATERAL jsonb_array_elements_text(t.profile->'included_requirement_ids') included(claim_id)
 JOIN ontology.typed_requirement r ON r.release_id=c.release_id AND r.claim_id=included.claim_id
 WHERE c.cohort_id=key AND t.included_in_cohort
$$;

CREATE OR REPLACE FUNCTION ontology.cohort_manifest_v1(key text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','posting-cohort-job-alio-v1','cohort',(SELECT to_jsonb(c) FROM ontology.posting_cohort c WHERE cohort_id=key),
  'counts',jsonb_build_object('source_postings',(SELECT count(*) FROM ontology.posting_cohort_posting WHERE cohort_id=key),
   'included',(SELECT count(*) FROM ontology.posting_cohort_posting WHERE cohort_id=key AND outcome='INCLUDED'),
   'duplicate_non_representatives',(SELECT count(*) FROM ontology.posting_cohort_posting WHERE cohort_id=key AND outcome='DUPLICATE'),
   'excluded',(SELECT count(*) FROM ontology.posting_cohort_posting WHERE cohort_id=key AND outcome='EXCLUDED'),
   'included_tracks',(SELECT count(*) FROM ontology.posting_cohort_track WHERE cohort_id=key AND included_in_cohort),
   'claim_support_rows',(SELECT count(*) FROM ontology.posting_cohort_claim WHERE cohort_id=key)),
  'posting_hash',(SELECT ontology.hash(coalesce(jsonb_agg(p ORDER BY entity_id COLLATE "C"),'[]')) FROM ontology.posting_cohort_posting p WHERE cohort_id=key),
  'track_hash',(SELECT ontology.hash(coalesce(jsonb_agg(t ORDER BY entity_id COLLATE "C",position_id COLLATE "C"),'[]')) FROM ontology.posting_cohort_track t WHERE cohort_id=key),
  'claim_hash',(SELECT ontology.hash(coalesce(jsonb_agg(s ORDER BY entity_id COLLATE "C",position_id COLLATE "C",claim_id COLLATE "C"),'[]')) FROM ontology.posting_cohort_claim s WHERE cohort_id=key))
$$;

CREATE OR REPLACE FUNCTION ontology.verify_posting_cohort_v1(key text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE head ontology.posting_cohort%ROWTYPE;dependencies jsonb; BEGIN
 SELECT * INTO head FROM ontology.posting_cohort WHERE cohort_id=key;IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_POSTING_COHORT'; END IF;
 dependencies:=ontology.cohort_dependencies_v1(head.release_id);
 IF head.dependency_binding<>dependencies OR head.dependency_hash<>ontology.hash(dependencies)
  OR head.filter<>ontology.cohort_filter_v1(head.occupation_id,head.as_of) OR head.filter_hash<>ontology.hash(head.filter)
  OR head.cohort_id<>ontology.hash(jsonb_build_array('posting-cohort-job-alio-v1',head.release_id,head.filter_hash,head.dependency_hash))
  OR head.occupation_revision_id IS DISTINCT FROM (SELECT revision_id FROM ontology.release_revision WHERE release_id=head.release_id AND entity_id=head.occupation_id)
 THEN RAISE EXCEPTION 'POSTING_COHORT_INPUTS_CHANGED'; END IF;
 IF EXISTS((SELECT to_jsonb(p)-'cohort_id' FROM ontology.posting_cohort_posting p WHERE cohort_id=key
   EXCEPT SELECT to_jsonb(c) FROM ontology.cohort_posting_candidates_v1(head.release_id,head.occupation_id,head.as_of) c)
  UNION ALL (SELECT to_jsonb(c) FROM ontology.cohort_posting_candidates_v1(head.release_id,head.occupation_id,head.as_of) c
   EXCEPT SELECT to_jsonb(p)-'cohort_id' FROM ontology.posting_cohort_posting p WHERE cohort_id=key))
 THEN RAISE EXCEPTION 'POSTING_COHORT_MEMBERS_CHANGED'; END IF;
 IF EXISTS((SELECT * FROM ontology.posting_cohort_track WHERE cohort_id=key EXCEPT SELECT * FROM ontology.cohort_track_candidates_v1(key))
  UNION ALL (SELECT * FROM ontology.cohort_track_candidates_v1(key) EXCEPT SELECT * FROM ontology.posting_cohort_track WHERE cohort_id=key))
 THEN RAISE EXCEPTION 'POSTING_COHORT_TRACKS_CHANGED'; END IF;
 IF EXISTS((SELECT * FROM ontology.posting_cohort_claim WHERE cohort_id=key EXCEPT SELECT * FROM ontology.cohort_claim_candidates_v1(key))
  UNION ALL (SELECT * FROM ontology.cohort_claim_candidates_v1(key) EXCEPT SELECT * FROM ontology.posting_cohort_claim WHERE cohort_id=key))
 THEN RAISE EXCEPTION 'POSTING_COHORT_SUPPORT_CHANGED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ontology.posting_cohort_manifest WHERE cohort_id=key AND manifest=ontology.cohort_manifest_v1(key) AND manifest_hash=ontology.hash(manifest))
 THEN RAISE EXCEPTION 'POSTING_COHORT_MANIFEST_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.build_posting_cohort_v1(id text,occupation text,as_of date) RETURNS text LANGUAGE plpgsql AS $$
DECLARE dependencies jsonb;filters jsonb;key text;revision text;manifest jsonb; BEGIN
 PERFORM ontology.require_preparing(id);
 IF as_of IS NULL OR NOT isfinite(as_of) OR as_of>(SELECT (created_at AT TIME ZONE 'Asia/Seoul')::date FROM ontology.corpus_release WHERE release_id=id)
 THEN RAISE EXCEPTION 'INVALID_COHORT_AS_OF_DATE'; END IF;
 IF occupation IS NULL OR occupation NOT IN ('urn:jobtology:occupation:product:AI_ENGINEER','urn:jobtology:occupation:product:BACKEND_DEVELOPER',
  'urn:jobtology:occupation:product:FRONTEND_DEVELOPER','urn:jobtology:occupation:product:DATA_ANALYST')
 THEN RAISE EXCEPTION 'COHORT_ONE_PRODUCT_OCCUPATION_REQUIRED'; END IF;
 dependencies:=ontology.cohort_dependencies_v1(id);
 SELECT r.revision_id INTO revision FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
 WHERE m.release_id=id AND m.entity_id=occupation AND r.kind='occupation'
  AND r.payload->>'scheme_id'='urn:jobtology:conceptScheme:product-occupations';
 IF revision IS NULL THEN RAISE EXCEPTION 'COHORT_OCCUPATION_NOT_IN_RELEASE'; END IF;
 filters:=ontology.cohort_filter_v1(occupation,as_of);
 key:=ontology.hash(jsonb_build_array('posting-cohort-job-alio-v1',id,ontology.hash(filters),ontology.hash(dependencies)));
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-posting-cohort:'||key,0));
 IF EXISTS(SELECT 1 FROM ontology.posting_cohort WHERE cohort_id=key) THEN PERFORM ontology.verify_posting_cohort_v1(key);RETURN key;END IF;
 INSERT INTO ontology.posting_cohort(cohort_id,release_id,occupation_id,occupation_revision_id,as_of,window_start,window_end,methodology_version,filter,filter_hash,dependency_binding,dependency_hash)
 VALUES(key,id,occupation,revision,as_of,as_of-179,as_of,'posting-cohort-job-alio-v1',filters,ontology.hash(filters),dependencies,ontology.hash(dependencies));
 INSERT INTO ontology.posting_cohort_posting SELECT key,p.* FROM ontology.cohort_posting_candidates_v1(id,occupation,as_of) p;
 INSERT INTO ontology.posting_cohort_track SELECT * FROM ontology.cohort_track_candidates_v1(key);
 INSERT INTO ontology.posting_cohort_claim SELECT * FROM ontology.cohort_claim_candidates_v1(key);
 manifest:=ontology.cohort_manifest_v1(key);INSERT INTO ontology.posting_cohort_manifest VALUES(key,manifest,ontology.hash(manifest));
 PERFORM ontology.verify_posting_cohort_v1(key);RETURN key;
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_release_membership_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.cohort_id COLLATE "C"),'[]') FROM ontology.posting_cohort c
 JOIN ontology.posting_cohort_manifest m USING(cohort_id) WHERE c.release_id=id
$$;
CREATE OR REPLACE FUNCTION ontology.cohort_release_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key text; BEGIN
 IF NEW.manifest IS NOT NULL AND EXISTS(SELECT 1 FROM ontology.posting_cohort WHERE release_id=NEW.release_id) THEN
  FOR key IN SELECT cohort_id FROM ontology.posting_cohort WHERE release_id=NEW.release_id LOOP PERFORM ontology.verify_posting_cohort_v1(key);END LOOP;
  IF NEW.manifest->'posting_cohorts_v1' IS DISTINCT FROM ontology.cohort_release_membership_v1(NEW.release_id)
  THEN RAISE EXCEPTION 'POSTING_COHORT_GRAPH_INTEGRATION_REQUIRED'; END IF;
 END IF;RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='ontology.corpus_release'::regclass AND tgname='ontology_cohort_release_guard') THEN
  CREATE TRIGGER ontology_cohort_release_guard BEFORE INSERT OR UPDATE OF manifest ON ontology.corpus_release
  FOR EACH ROW EXECUTE FUNCTION ontology.cohort_release_guard_v1();
 END IF;
END $$;
COMMIT;
