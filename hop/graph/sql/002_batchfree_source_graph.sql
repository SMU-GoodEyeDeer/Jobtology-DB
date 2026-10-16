-- Permanent batch-free source graph. PostgreSQL owns snapshot membership and
-- immutable content proof; Neo4j contains only stable business identities and
-- their selected current source facts/direct relationships. Install after 001.
BEGIN;
CREATE TABLE IF NOT EXISTS ingestion.source_graph_projection (
 run_id text PRIMARY KEY, source_id text NOT NULL,
 state text NOT NULL CHECK(state IN('LOADING','READY','FAILED')),
 loader_version text NOT NULL CHECK(loader_version='hop-graph-batchfree-v1'),
 record_count bigint NOT NULL CHECK(record_count>=0),
 reference_count bigint NOT NULL CHECK(reference_count>=0),
 content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[0-9a-f]{64}$'),
 started_at timestamptz NOT NULL, verified_at timestamptz, error_code text,
 CHECK((state='READY')=(verified_at IS NOT NULL))
);
-- Deliberately no run/record FK: accepted proofs survive independent source-run
-- retention, like the posting ingestion observation ledger. No raw URLs copied.
CREATE TABLE IF NOT EXISTS ingestion.source_graph_record_evidence (
 run_id text NOT NULL, record_id text NOT NULL, source_record_id text NOT NULL,
 normalized_sha256 text NOT NULL, facts_sha256 text NOT NULL,
 document_sha256 text NOT NULL, content_sha256 text NOT NULL,
 PRIMARY KEY(run_id,record_id),
 CHECK(normalized_sha256 ~ '^[0-9a-f]{64}$' AND facts_sha256 ~ '^[0-9a-f]{64}$'
 AND document_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS ingestion.source_graph_membership (
 run_id text NOT NULL, record_id text NOT NULL, identity_id text NOT NULL,
 field text NOT NULL, kind text NOT NULL, code text NOT NULL,
 PRIMARY KEY(run_id,record_id,identity_id,field)
);
CREATE INDEX IF NOT EXISTS source_graph_membership_identity
 ON ingestion.source_graph_membership(run_id,identity_id,kind,code);

-- Existing source-qualified identities are unchanged. Q-Net sessions previously
-- existed only as records; give each real session a stable business identity.
CREATE OR REPLACE VIEW ingestion.source_graph_reference AS
SELECT * FROM ingestion.graph_reference
UNION ALL
SELECT g.id,r.run_id,'qnet:exam-session:'||encode(sha256(convert_to(r.source_record_id,'UTF8')),'hex'),
 'ExamSession',r.source_record_id,'source_record_id'
FROM ingestion.ready_record r JOIN ingestion.graph_record g USING(run_id,record_id)
WHERE r.source_id='qnet_schedule';

CREATE OR REPLACE VIEW ingestion.source_graph_live_record_evidence AS
SELECT g.run_id,g.id AS record_id,g.source_record_id,
 encode(sha256(convert_to(r.normalized::text,'UTF8')),'hex') AS normalized_sha256,
 encode(sha256(convert_to(g.facts_json,'UTF8')),'hex') AS facts_sha256,
 d.raw_sha256 AS document_sha256,
 encode(sha256(convert_to(jsonb_build_object('source_payload',r.source_payload,
 'normalized',r.normalized,'field_lineage',r.field_lineage,'quality_flags',r.quality_flags,
 'document_id',r.document_id,'locator',r.locator,'source_record_id',r.source_record_id,
 'document_sha256',d.raw_sha256,'facts_json',g.facts_json)::text,'UTF8')),'hex') AS content_sha256
FROM ingestion.graph_record g JOIN ingestion.ready_record r USING(run_id,record_id)
JOIN ingestion.document d USING(run_id,document_id);

CREATE OR REPLACE FUNCTION ingestion.source_graph_digest(records jsonb,members jsonb)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT encode(sha256(convert_to(jsonb_build_object('records',records,'members',members)::text,'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION ingestion.source_graph_manifest(jobs text,live boolean DEFAULT false)
RETURNS TABLE(record_count bigint,reference_count bigint,content_sha256 text)
LANGUAGE sql STABLE SET jit=off AS $$
 WITH records AS MATERIALIZED (
 SELECT * FROM ingestion.source_graph_live_record_evidence WHERE live AND run_id=jobs
 UNION ALL SELECT * FROM ingestion.source_graph_record_evidence WHERE NOT live AND run_id=jobs
 ), members AS MATERIALIZED (
 SELECT run_id,record_id,identity_id,field,kind,code FROM ingestion.source_graph_reference WHERE live AND run_id=jobs
 UNION ALL SELECT * FROM ingestion.source_graph_membership WHERE NOT live AND run_id=jobs
 )
 SELECT (SELECT count(*) FROM records),(SELECT count(*) FROM members),
 ingestion.source_graph_digest(
 (SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY record_id),'[]') FROM records r),
 (SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY record_id,identity_id,field),'[]') FROM members m)
 )
$$;

CREATE OR REPLACE FUNCTION ingestion.source_graph_evidence_guard() RETURNS trigger
LANGUAGE plpgsql SET jit=off AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_SOURCE_GRAPH_EVIDENCE'; END $$;
CREATE OR REPLACE FUNCTION ingestion.source_graph_insert_guard() RETURNS trigger
LANGUAGE plpgsql SET jit=off AS $$
DECLARE invalid boolean; jobs text;
BEGIN
 -- Transition tables can span runs. Fence each exact run before constructing
 -- live proof, rather than rebuilding whole history for every inserted slice.
 -- Compare the complete batch: EXISTS startup plans repeatedly scan genuine
 -- rows. bool_or preserves rejection when any exact row differs or is absent.
 FOR jobs IN SELECT DISTINCT run_id FROM new_evidence LOOP
  IF TG_TABLE_NAME='source_graph_record_evidence' THEN
   WITH live AS MATERIALIZED(SELECT * FROM ingestion.source_graph_live_record_evidence WHERE run_id=jobs)
   SELECT coalesce(bool_or(to_jsonb(e) IS DISTINCT FROM to_jsonb(l)),false) INTO invalid
   FROM new_evidence e LEFT JOIN live l USING(run_id,record_id) WHERE e.run_id=jobs;
  ELSE
   WITH live AS MATERIALIZED(SELECT * FROM ingestion.source_graph_reference WHERE run_id=jobs)
   SELECT coalesce(bool_or(to_jsonb(e) IS DISTINCT FROM to_jsonb(l)),false) INTO invalid
   FROM new_evidence e LEFT JOIN live l USING(run_id,record_id,identity_id,field) WHERE e.run_id=jobs;
  END IF;
  IF invalid OR NOT ingestion.source_graph_run_is_valid(jobs)
  THEN RAISE EXCEPTION 'INVALID_SOURCE_GRAPH_EVIDENCE'; END IF;
 END LOOP;
 RETURN NULL;
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['source_graph_record_evidence','source_graph_membership'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER immutable_source_graph_evidence BEFORE UPDATE OR DELETE ON ingestion.%I FOR EACH ROW EXECUTE FUNCTION ingestion.source_graph_evidence_guard()',tab);
  EXECUTE format('CREATE OR REPLACE TRIGGER immutable_source_graph_evidence_truncate BEFORE TRUNCATE ON ingestion.%I FOR EACH STATEMENT EXECUTE FUNCTION ingestion.source_graph_evidence_guard()',tab);
  EXECUTE format('CREATE OR REPLACE TRIGGER validate_source_graph_evidence AFTER INSERT ON ingestion.%I REFERENCING NEW TABLE AS new_evidence FOR EACH STATEMENT EXECUTE FUNCTION ingestion.source_graph_insert_guard()',tab);
 END LOOP;
 IF to_regprocedure('retention.freeze_writes()') IS NOT NULL THEN
  FOREACH tab IN ARRAY ARRAY['source_graph_projection','source_graph_record_evidence','source_graph_membership'] LOOP
   EXECUTE format('CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON ingestion.%I FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',tab);
  END LOOP;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION ingestion.source_graph_projection_guard() RETURNS trigger
LANGUAGE plpgsql SET jit=off AS $$
DECLARE m record;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF (NEW.run_id,NEW.source_id,NEW.loader_version,NEW.record_count,NEW.reference_count,NEW.content_sha256)
   IS DISTINCT FROM (OLD.run_id,OLD.source_id,OLD.loader_version,OLD.record_count,OLD.reference_count,OLD.content_sha256)
  THEN RAISE EXCEPTION 'IMMUTABLE_SOURCE_GRAPH_SNAPSHOT_PROOF'; END IF;
 ELSE
  IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=NEW.run_id AND source_id=NEW.source_id AND state='READY' AND mode<>'SMOKE')
   OR EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=NEW.run_id)
  THEN RAISE EXCEPTION 'SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN'; END IF;
  SELECT * INTO m FROM ingestion.source_graph_manifest(NEW.run_id,true);
  IF (NEW.record_count,NEW.reference_count,NEW.content_sha256) IS DISTINCT FROM (m.record_count,m.reference_count,m.content_sha256)
  THEN RAISE EXCEPTION 'SOURCE_GRAPH_LIVE_CONTENT_MISMATCH'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER immutable_source_graph_snapshot_proof BEFORE INSERT OR UPDATE ON ingestion.source_graph_projection
 FOR EACH ROW EXECUTE FUNCTION ingestion.source_graph_projection_guard();

CREATE OR REPLACE FUNCTION ingestion.assert_source_graph_content(jobs text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
DECLARE p ingestion.source_graph_projection; m record;
BEGIN
 SELECT * INTO p FROM ingestion.source_graph_projection WHERE run_id=jobs;
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_GRAPH_PROJECTION_MISSING'; END IF;
 SELECT * INTO m FROM ingestion.source_graph_manifest(jobs);
 IF (p.record_count,p.reference_count,p.content_sha256) IS DISTINCT FROM (m.record_count,m.reference_count,m.content_sha256)
 THEN RAISE EXCEPTION 'SOURCE_GRAPH_EVIDENCE_MISMATCH'; END IF;
 -- A retained live source must still be accepted and byte-for-byte equivalent.
 -- After explicitly archived source cleanup, the immutable captured proof stays.
 IF EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=jobs) THEN
  IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=jobs AND state='READY' AND mode<>'SMOKE')
   OR EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=jobs)
  THEN RAISE EXCEPTION 'SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN'; END IF;
  SELECT * INTO m FROM ingestion.source_graph_manifest(jobs,true);
  IF (p.record_count,p.reference_count,p.content_sha256) IS DISTINCT FROM (m.record_count,m.reference_count,m.content_sha256)
  THEN RAISE EXCEPTION 'SOURCE_GRAPH_LIVE_CONTENT_MISMATCH'; END IF;
 END IF;
END $$;
CREATE OR REPLACE FUNCTION ingestion.assert_source_graph_projection(jobs text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM ingestion.source_graph_projection WHERE run_id=jobs AND state='READY'
  AND loader_version='hop-graph-batchfree-v1' AND verified_at IS NOT NULL)
 THEN RAISE EXCEPTION 'SOURCE_GRAPH_PROJECTION_NOT_READY'; END IF;
 PERFORM ingestion.assert_source_graph_content(jobs);
END $$;
CREATE OR REPLACE FUNCTION ingestion.assert_source_graph_member(jobs text,identity text,entity_kind text,entity_code text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SET jit=off AS $$
BEGIN
 PERFORM ingestion.assert_source_graph_projection(jobs);
 IF NOT EXISTS(SELECT 1 FROM ingestion.source_graph_membership WHERE run_id=jobs AND identity_id=identity
  AND kind=entity_kind AND (entity_code IS NULL OR code=entity_code))
 THEN RAISE EXCEPTION 'SOURCE_GRAPH_MEMBER_MISSING'; END IF;
END $$;
CREATE OR REPLACE FUNCTION ingestion.graph_source_run_evidence(jobs text)
RETURNS SETOF ingestion.source_graph_projection LANGUAGE plpgsql SET jit=off AS $$
BEGIN
 PERFORM ingestion.assert_source_graph_projection(jobs);
 RETURN QUERY SELECT * FROM ingestion.source_graph_projection WHERE run_id=jobs;
END $$;
CREATE OR REPLACE FUNCTION ingestion.graph_source_identity_evidence(jobs text,identity text)
RETURNS SETOF ingestion.source_graph_membership LANGUAGE plpgsql SET jit=off AS $$
BEGIN
 PERFORM ingestion.assert_source_graph_projection(jobs);
 RETURN QUERY SELECT * FROM ingestion.source_graph_membership WHERE run_id=jobs AND identity_id=identity;
END $$;
CREATE OR REPLACE FUNCTION ingestion.begin_source_graph_projection(jobs text) RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$
DECLARE u ingestion.run; m record;
BEGIN
 SELECT * INTO u FROM ingestion.run WHERE run_id=jobs AND state='READY' AND mode<>'SMOKE';
 IF NOT FOUND OR EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=jobs)
 THEN RAISE EXCEPTION 'SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN'; END IF;
 INSERT INTO ingestion.source_graph_record_evidence SELECT * FROM ingestion.source_graph_live_record_evidence
 WHERE run_id=jobs ON CONFLICT DO NOTHING;
 INSERT INTO ingestion.source_graph_membership SELECT run_id,record_id,identity_id,field,kind,code FROM ingestion.source_graph_reference
 WHERE run_id=jobs ON CONFLICT DO NOTHING;
 SELECT * INTO m FROM ingestion.source_graph_manifest(jobs,true);
 INSERT INTO ingestion.source_graph_projection(run_id,source_id,state,loader_version,record_count,reference_count,content_sha256,started_at)
 VALUES(jobs,u.source_id,'LOADING','hop-graph-batchfree-v1',m.record_count,m.reference_count,m.content_sha256,clock_timestamp())
 ON CONFLICT(run_id) DO UPDATE SET state='LOADING',verified_at=NULL,error_code=NULL,started_at=clock_timestamp();
 PERFORM ingestion.assert_source_graph_content(jobs);
 RETURN true;
END $$;
CREATE OR REPLACE FUNCTION ingestion.finish_source_graph_projection(jobs text) RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$
BEGIN
 PERFORM ingestion.assert_source_graph_content(jobs);
 UPDATE ingestion.source_graph_projection SET state='READY',verified_at=clock_timestamp(),error_code=NULL
 WHERE run_id=jobs AND state='LOADING';
 IF NOT FOUND THEN RAISE EXCEPTION 'SOURCE_GRAPH_PROJECTION_NOT_LOADING'; END IF;
 RETURN true;
END $$;
CREATE OR REPLACE FUNCTION ingestion.fail_source_graph_projection(jobs text) RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$
BEGIN
 UPDATE ingestion.source_graph_projection SET state='FAILED',verified_at=NULL,error_code='GRAPH_LOAD_FAILED'
 WHERE run_id=jobs AND state='LOADING';
 RETURN true;
END $$;

-- Fence the exact-run predicate inside the validator query. Expanding the global
-- validation view into every reference join repeats unrelated historical work.
-- This still evaluates every validator for each accepted run, once per scope.
CREATE OR REPLACE FUNCTION ingestion.source_graph_run_is_valid(jobs text)
RETURNS boolean LANGUAGE plpgsql STABLE SET jit=off AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=jobs AND state='READY' AND mode<>'SMOKE')
 THEN RETURN false; END IF;
 RETURN NOT EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=jobs);
END $$;

-- Candidate rows remain wholly in PostgreSQL. Current facts use a complete
-- selected representation; an explicit NULL/missing newer field never borrows
-- an older run's value. Names retain the prior richer/authoritative semantics.
CREATE OR REPLACE VIEW ingestion.source_graph_candidate AS
WITH eligible_runs AS MATERIALIZED(SELECT u.run_id,u.created_at FROM ingestion.run u
 WHERE u.state='READY' AND u.mode<>'SMOKE' AND ingestion.source_graph_run_is_valid(u.run_id)),
records AS MATERIALIZED(SELECT r.run_id,r.record_id,r.source_id,r.source_record_id,r.normalized,u.created_at
 FROM ingestion.ready_record r JOIN eligible_runs u USING(run_id)),
refs AS MATERIALIZED(SELECT q.*,substring(q.record_id from '[^:]+$')::bigint AS numeric_record_id
 FROM ingestion.source_graph_reference q JOIN eligible_runs u USING(run_id))
SELECT q.record_id,q.run_id,q.identity_id,q.kind,q.code,q.field,r.source_id,r.source_record_id,
 r.record_id AS numeric_record_id,r.normalized,
 NULL::text AS facts_json,u.created_at,
 CASE q.kind
 WHEN 'Organization' THEN CASE WHEN r.source_id='alio_organization' THEN r.normalized->>'name' ELSE r.normalized->>'organization_name' END
 WHEN 'JobPosting' THEN r.normalized->>'title'
 WHEN 'Occupation' THEN r.normalized->>'occupation_name'
 WHEN 'Competency' THEN CASE WHEN r.source_id='ncs_competency' THEN r.normalized->>'name' ELSE r.normalized->>'competency_name' END
 WHEN 'Qualification' THEN r.normalized->>'qualification_name'
 WHEN 'ExamSession' THEN r.normalized->>'name' END AS proposed_name,
 CASE WHEN (q.kind='Organization' AND r.source_id='alio_organization')
 OR (q.kind='Competency' AND r.source_id='ncs_competency')
 OR (q.kind='Qualification' AND r.source_id='ncs_qualification') THEN 0 ELSE 1 END AS owner_priority,
 CASE WHEN r.source_id IN('alio_organization','ncs_competency','ncs_qualification') THEN 0 ELSE 1 END AS name_priority
FROM refs q JOIN records r ON r.run_id=q.run_id AND r.record_id=q.numeric_record_id
JOIN eligible_runs u ON u.run_id=r.run_id;

CREATE OR REPLACE FUNCTION ingestion.source_graph_entity_facts(entity_kind text,source text,n jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE
 WHEN entity_kind='Organization' AND source<>'alio_organization' THEN
  jsonb_build_object('kind','Organization','code',n->'organization_code','name',n->'organization_name')
 WHEN entity_kind='Occupation' THEN
  jsonb_build_object('kind','Occupation','code',n->'occupation_code','name',n->'occupation_name',
   'classification_names',n->'classification_names')
 WHEN entity_kind='Competency' AND source<>'ncs_competency' THEN
  jsonb_build_object('kind','Competency','code',n->'competency_code','name',n->'competency_name','level',n->'competency_level')
 WHEN entity_kind='Qualification' THEN
  jsonb_build_object('kind','Qualification','code',n->'qualification_code','name',n->'qualification_name')
 WHEN source='jobkorea' THEN ingestion.jobkorea_graph_facts(n)
 ELSE n-ARRAY['definition','eligibility_text','disqualification_text','preference_text','selection_text','address','website','source_url'] END
$$;

CREATE OR REPLACE FUNCTION ingestion.graph_source_entities(jobs text)
RETURNS TABLE(identity_id text,kind text,code text,entity_name text,entity_title text,
 name_source_run_id text,name_source_record_id text,source_id text,source_run_id text,
 source_record_id text,source_created_at text,source_facts_json text,source_facts_sha256 text)
LANGUAGE plpgsql SET jit=off AS $$
BEGIN
 IF jobs='ALL_CHECKPOINTED' THEN
  IF EXISTS(SELECT 1 FROM ingestion.graph_export g JOIN ingestion.run u USING(run_id)
   WHERE NOT ingestion.source_graph_run_is_valid(u.run_id))
  THEN RAISE EXCEPTION 'SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN'; END IF;
 ELSE
  IF NOT ingestion.source_graph_run_is_valid(jobs)
  THEN RAISE EXCEPTION 'SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN'; END IF;
 END IF;
 RETURN QUERY
 WITH current_edges AS MATERIALIZED(SELECT from_id,to_id FROM ingestion.graph_source_edges(jobs)),
 wanted AS MATERIALIZED(SELECT DISTINCT q.identity_id FROM ingestion.source_graph_reference q WHERE q.run_id=jobs OR (jobs='ALL_CHECKPOINTED' AND EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=q.run_id))
 UNION SELECT from_id FROM current_edges
 UNION SELECT to_id FROM current_edges),
 candidates AS MATERIALIZED(SELECT c.* FROM ingestion.source_graph_candidate c JOIN wanted w USING(identity_id)),
 facts AS MATERIALIZED(SELECT c.*,row_number() OVER(PARTITION BY c.identity_id ORDER BY owner_priority,
 created_at DESC,c.run_id DESC,CASE WHEN normalized->>'representation'='detail' THEN 0 ELSE 1 END,
 numeric_record_id DESC,c.record_id DESC) AS choice FROM candidates c),
 names AS(SELECT c.*,row_number() OVER(PARTITION BY c.identity_id ORDER BY
 (nullif(btrim(proposed_name),'') IS NULL),name_priority,created_at DESC,c.run_id DESC,
 CASE WHEN normalized->>'representation'='detail' THEN 0 ELSE 1 END,
 numeric_record_id DESC,c.record_id DESC) AS choice FROM candidates c),
 current_facts AS MATERIALIZED(SELECT * FROM facts WHERE choice=1),
 posting_records AS MATERIALIZED(SELECT r.run_id,r.source_id,r.normalized,
 r.normalized->>'posting_id' AS posting_id,r.normalized->>'representation' AS representation
 FROM ingestion.ready_record r JOIN current_facts f ON f.run_id=r.run_id AND f.source_id=r.source_id
 AND f.normalized->>'posting_id'=r.normalized->>'posting_id'
 WHERE f.kind='JobPosting' AND f.source_id IN('job_alio','nara_job')),
 posting_sets AS MATERIALIZED(SELECT p.run_id,p.source_id,p.posting_id,
 jsonb_object_agg(p.representation,p.normalized) AS forms FROM posting_records p
 GROUP BY p.run_id,p.source_id,p.posting_id),
 job_facts AS MATERIALIZED(SELECT p.run_id,p.posting_id,
 ((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail'))-'representation' AS normalized
 FROM posting_sets p WHERE p.source_id='job_alio' AND p.forms ?& ARRAY['list','detail']),
 nara_facts AS MATERIALIZED(SELECT p.run_id,p.posting_id,
 ((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail')||jsonb_strip_nulls(p.forms->'positions')||jsonb_strip_nulls(p.forms->'files'))-'representation' AS normalized
 FROM posting_sets p WHERE p.source_id='nara_job' AND p.forms ?& ARRAY['list','detail','positions','files']
 AND coalesce((p.forms->'list'->>'ongoing')::boolean,false))
 SELECT f.identity_id,f.kind,f.code,coalesce(nullif(btrim(n.proposed_name),''),f.kind||' '||f.code),
 CASE WHEN f.kind='JobPosting' THEN coalesce(nullif(btrim(n.proposed_name),''),f.kind||' '||f.code) END,
 n.run_id,n.record_id,f.source_id,f.run_id,f.source_record_id,
 to_char(f.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
 selected.facts_json,encode(sha256(convert_to(selected.facts_json,'UTF8')),'hex')
 FROM current_facts f JOIN names n USING(identity_id)
 LEFT JOIN job_facts j ON j.run_id=f.run_id AND j.posting_id=f.normalized->>'posting_id'
 LEFT JOIN nara_facts k ON k.run_id=f.run_id AND k.posting_id=f.normalized->>'posting_id'
 CROSS JOIN LATERAL(SELECT ingestion.source_graph_entity_facts(f.kind,f.source_id,
 CASE WHEN f.kind='JobPosting' AND f.source_id='job_alio' THEN
  coalesce(j.normalized,f.normalized)
 WHEN f.kind='JobPosting' AND f.source_id='nara_job' THEN
  coalesce(k.normalized,f.normalized)
 ELSE f.normalized END)::text AS facts_json) selected
 WHERE n.choice=1 ORDER BY f.identity_id;
END $$;

-- One direct fact relationship per grounded source row/pair, scoped to a stable
-- owner and source. Selecting the latest owner observation does not infer that
-- entities absent from a later file closed or disappeared.
CREATE OR REPLACE FUNCTION ingestion.graph_source_edges(jobs text)
RETURNS TABLE(owner_id text,source_id text,source_run_id text,source_record_id text,
 from_id text,to_id text,edge_kind text,edge_key text,edge_facts_json text)
LANGUAGE sql STABLE SET jit=off AS $$
 WITH eligible_runs AS MATERIALIZED(SELECT u.run_id,u.created_at FROM ingestion.run u
 WHERE u.state='READY' AND u.mode<>'SMOKE' AND ingestion.source_graph_run_is_valid(u.run_id)),
 records AS MATERIALIZED(SELECT r.run_id,r.record_id,r.source_id,r.source_record_id,r.normalized,u.created_at
 FROM ingestion.ready_record r JOIN eligible_runs u USING(run_id)),
 refs AS MATERIALIZED(SELECT q.*,substring(q.record_id from '[^:]+$')::bigint AS numeric_record_id
 FROM ingestion.source_graph_reference q JOIN eligible_runs u USING(run_id)),
 touched AS MATERIALIZED(SELECT DISTINCT identity_id FROM refs q WHERE run_id=jobs OR (jobs='ALL_CHECKPOINTED' AND EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=q.run_id))),
 owners AS MATERIALIZED(
 SELECT DISTINCT ON(q.identity_id,r.source_id) q.identity_id,r.source_id,r.run_id
 FROM refs q JOIN touched t USING(identity_id)
 JOIN records r ON q.run_id=r.run_id AND r.record_id=q.numeric_record_id
 WHERE ((r.source_id IN('job_alio','nara_job','jobkorea') AND q.kind='JobPosting')
 OR (r.source_id='ncs_competency' AND q.kind='Competency')
 OR (r.source_id='ncs_career_path' AND q.kind='Occupation')
 OR (r.source_id='ncs_qualification' AND q.kind='Competency')
 OR (r.source_id='qnet_schedule' AND q.kind='ExamSession'))
 ORDER BY q.identity_id,r.source_id,r.created_at DESC,r.run_id DESC
 ), pairs AS(
 SELECT o.identity_id AS owner_id,r.source_id,r.run_id,r.source_record_id,
 CASE WHEN r.source_id='qnet_schedule' THEN target.identity_id ELSE o.identity_id END AS from_id,
 CASE WHEN r.source_id='qnet_schedule' THEN o.identity_id ELSE target.identity_id END AS to_id,
 CASE r.source_id WHEN 'job_alio' THEN 'EMPLOYER' WHEN 'ncs_competency' THEN 'CLASSIFIED_AS'
 WHEN 'ncs_career_path' THEN 'HAS_CAREER_COMPETENCY' WHEN 'ncs_qualification' THEN 'QUALIFICATION_MAPPING'
 WHEN 'qnet_schedule' THEN 'HAS_EXAM_SESSION' END AS edge_kind,
 (CASE WHEN r.source_id='jobkorea' THEN ingestion.jobkorea_graph_facts(r.normalized)
 ELSE r.normalized-ARRAY['definition','eligibility_text','disqualification_text','preference_text','selection_text','address','website','source_url'] END)::text AS facts_json
 FROM owners o JOIN refs self ON self.run_id=o.run_id AND self.identity_id=o.identity_id
 JOIN records r ON r.run_id=self.run_id AND r.record_id=self.numeric_record_id
 JOIN refs target ON target.run_id=self.run_id AND target.numeric_record_id=self.numeric_record_id
 AND ((r.source_id='job_alio' AND target.kind='Organization')
 OR (r.source_id='ncs_competency' AND target.kind='Occupation')
 OR (r.source_id='ncs_career_path' AND target.kind='Competency')
 OR (r.source_id='ncs_qualification' AND target.kind='Qualification')
 OR (r.source_id='qnet_schedule' AND target.kind='Qualification'))
 ), dedup AS(
 SELECT DISTINCT ON(owner_id,source_id,from_id,to_id,edge_kind,
 CASE WHEN source_id IN('job_alio','ncs_competency') THEN '' ELSE source_record_id END) * FROM pairs
 ORDER BY owner_id,source_id,from_id,to_id,edge_kind,
 CASE WHEN source_id IN('job_alio','ncs_competency') THEN '' ELSE source_record_id END,source_record_id DESC
 )
 SELECT owner_id,source_id,run_id,source_record_id,from_id,to_id,edge_kind,
 encode(sha256(convert_to(jsonb_build_array(source_id,owner_id,from_id,to_id,edge_kind,
 CASE WHEN source_id IN('job_alio','ncs_competency') THEN '' ELSE source_record_id END)::text,'UTF8')),'hex'),facts_json
 FROM dedup ORDER BY owner_id,edge_kind,to_id
$$;
DROP FUNCTION IF EXISTS ingestion.graph_source_edge_owners(text);
CREATE FUNCTION ingestion.graph_source_edge_owners(jobs text)
RETURNS TABLE(owner_id text,source_id text,expected_edge_keys text) LANGUAGE sql STABLE SET jit=off AS $$
 WITH owners AS(SELECT DISTINCT q.identity_id,r.source_id
 FROM ingestion.source_graph_reference q JOIN ingestion.ready_record r ON q.run_id=r.run_id AND r.record_id=substring(q.record_id from '[^:]+$')::bigint
 WHERE (q.run_id=jobs OR (jobs='ALL_CHECKPOINTED' AND EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=q.run_id))) AND ((r.source_id IN('job_alio','nara_job','jobkorea') AND q.kind='JobPosting')
 OR (r.source_id='ncs_competency' AND q.kind='Competency')
 OR (r.source_id='ncs_career_path' AND q.kind='Occupation')
 OR (r.source_id='ncs_qualification' AND q.kind='Competency')
 OR (r.source_id='qnet_schedule' AND q.kind='ExamSession'))),
 edges AS MATERIALIZED(SELECT owner_id,source_id,string_agg(edge_key,',' ORDER BY edge_key) AS edge_keys
 FROM ingestion.graph_source_edges(jobs) GROUP BY owner_id,source_id)
 SELECT o.identity_id,o.source_id,coalesce(e.edge_keys,'') FROM owners o
 LEFT JOIN edges e ON e.owner_id=o.identity_id AND e.source_id=o.source_id
$$;
CREATE OR REPLACE FUNCTION ingestion.begin_source_graph_migration() RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$ DECLARE jobs text; BEGIN
 FOR jobs IN SELECT g.run_id FROM ingestion.graph_export g JOIN ingestion.run u USING(run_id) ORDER BY u.created_at,g.run_id LOOP
  PERFORM ingestion.begin_source_graph_projection(jobs);
 END LOOP;
 RETURN true;
END $$;
CREATE OR REPLACE FUNCTION ingestion.finish_source_graph_migration() RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$ DECLARE jobs text; BEGIN
 FOR jobs IN SELECT g.run_id FROM ingestion.graph_export g JOIN ingestion.run u USING(run_id) ORDER BY u.created_at,g.run_id LOOP
  PERFORM ingestion.finish_source_graph_projection(jobs);
 END LOOP;
 RETURN true;
END $$;
CREATE OR REPLACE FUNCTION ingestion.fail_source_graph_migration() RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$ BEGIN
 UPDATE ingestion.source_graph_projection SET state='FAILED',verified_at=NULL,error_code='GRAPH_LOAD_FAILED'
 WHERE state='LOADING' AND run_id IN(SELECT run_id FROM ingestion.graph_export);
 RETURN true;
END $$;
COMMENT ON FUNCTION ingestion.graph_source_entities(text) IS
 'Stable business entities with current complete source facts and separately selected readable names; historical membership stays in PostgreSQL.';
CREATE OR REPLACE FUNCTION ingestion.record_graph_export_v1(id text) RETURNS void LANGUAGE plpgsql SET jit=off AS $$
DECLARE r ingestion.run;
BEGIN
 SELECT * INTO r FROM ingestion.run WHERE run_id=id AND state='READY' AND mode<>'SMOKE';
 IF NOT FOUND THEN RAISE EXCEPTION 'GRAPH_EXPORT_REQUIRES_READY_SNAPSHOT'; END IF;
 IF to_regprocedure('ingestion.assert_source_graph_projection(text)') IS NULL
 THEN RAISE EXCEPTION 'BATCHFREE_SOURCE_GRAPH_CONTRACT_REQUIRED'; END IF;
 PERFORM ingestion.assert_source_graph_projection(id);
 IF r.source_id='job_alio' AND r.mode='FULL' AND to_regprocedure('ontology.capture_posting_census_v1(text)') IS NOT NULL THEN
  EXECUTE 'SELECT ontology.capture_posting_census_v1($1)' USING id;
 END IF;
 INSERT INTO ingestion.graph_export(run_id,loader_version) VALUES(id,'hop-graph-batchfree-v1')
 ON CONFLICT(run_id) DO UPDATE SET exported_at=clock_timestamp(),loader_version=EXCLUDED.loader_version;
END $$;
COMMIT;
