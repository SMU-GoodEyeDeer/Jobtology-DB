-- Complete-snapshot observation history and frozen posting-state candidates.
-- These records do not accept claims or add historical revisions to a graph.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.observation_run (
 run_id text PRIMARY KEY REFERENCES ingestion.run,
 source_id text NOT NULL CHECK(source_id='job_alio'),
 source_created_at timestamptz NOT NULL,
 source_completed_at timestamptz NOT NULL,
 watermark_at timestamptz NOT NULL,
 source_fingerprint text NOT NULL,
 posting_count bigint NOT NULL CHECK(posting_count>=0),
 census_hash text NOT NULL,
 captured_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.posting_seen (
 run_id text NOT NULL REFERENCES ontology.observation_run,
 posting_id text NOT NULL CHECK(length(posting_id)>0),
 entity_id text NOT NULL,
 normalized jsonb NOT NULL CHECK(jsonb_typeof(normalized)='object'),
 source_hash text NOT NULL,
 first_observed_at timestamptz NOT NULL,
 last_observed_at timestamptz NOT NULL,
 list_record_id bigint NOT NULL REFERENCES ingestion.record(record_id),
 detail_record_id bigint NOT NULL REFERENCES ingestion.record(record_id),
 PRIMARY KEY(run_id,posting_id), UNIQUE(run_id,entity_id),
 CHECK(first_observed_at<=last_observed_at),
 CHECK(source_hash=ontology.hash(normalized))
);
CREATE INDEX IF NOT EXISTS ontology_posting_seen_identity ON ontology.posting_seen(entity_id,run_id);
CREATE TABLE IF NOT EXISTS ontology.observation_freeze (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 through_run_id text NOT NULL REFERENCES ontology.observation_run,
 evaluated_at timestamptz NOT NULL,
 methodology_version text NOT NULL CHECK(methodology_version='posting-observation-v1'),
 manifest jsonb NOT NULL,
 manifest_hash text NOT NULL CHECK(manifest_hash=ontology.hash(manifest)),
 frozen_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.observation_history_member (
 release_id text NOT NULL REFERENCES ontology.observation_freeze,
 run_id text NOT NULL REFERENCES ontology.observation_run,
 ordinal integer NOT NULL CHECK(ordinal>=0),
 PRIMARY KEY(release_id,run_id),UNIQUE(release_id,ordinal)
);
CREATE TABLE IF NOT EXISTS ontology.posting_observation (
 release_id text NOT NULL REFERENCES ontology.observation_freeze,
 entity_id text NOT NULL,
 posting_id text NOT NULL,
 selected_revision_id text REFERENCES ontology.revision,
 content_run_id text NOT NULL,
 first_seen_at timestamptz NOT NULL,
 last_seen_at timestamptz NOT NULL,
 consecutive_absence_count integer NOT NULL CHECK(consecutive_absence_count>=0),
 present_in_selected_run boolean NOT NULL,
 serving_state text NOT NULL CHECK(serving_state IN ('ACTIVE','EXPIRED','CLOSED','NOT_SEEN')),
 state_reason text NOT NULL,
 deadline_at timestamptz,
 source_status text NOT NULL CHECK(source_status IN ('OPEN','CLOSED','UNKNOWN')),
 membership_state text NOT NULL CHECK(membership_state IN ('CURRENT_RELEASE','HISTORICAL_NOT_ASSEMBLED')),
 PRIMARY KEY(release_id,entity_id),UNIQUE(release_id,posting_id),
 FOREIGN KEY(content_run_id,posting_id) REFERENCES ontology.posting_seen(run_id,posting_id),
 CHECK(first_seen_at<=last_seen_at),
 CHECK(present_in_selected_run=(consecutive_absence_count=0)),
 CHECK((membership_state='CURRENT_RELEASE')=(selected_revision_id IS NOT NULL))
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['observation_run','posting_seen','observation_freeze','observation_history_member','posting_observation'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||t AND tgrelid=('ontology.'||t)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||t,t);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.posting_census_v1(id text)
RETURNS TABLE(run_id text,posting_id text,entity_id text,normalized jsonb,source_hash text,
 first_observed_at timestamptz,last_observed_at timestamptz,list_record_id bigint,detail_record_id bigint)
LANGUAGE sql STABLE AS $$
 SELECT p.run_id,p.posting_id,ontology.iri('jobPosting','job_alio:'||p.posting_id),p.normalized,ontology.hash(p.normalized),
  least(ld.retrieved_at,dd.retrieved_at),greatest(ld.retrieved_at,dd.retrieved_at),l.record_id,d.record_id
 FROM ingestion.job_posting p
 JOIN ingestion.record l ON l.run_id=p.run_id AND l.document_id=p.list_document_id AND l.locator=p.list_locator
 JOIN ingestion.record d ON d.run_id=p.run_id AND d.document_id=p.detail_document_id AND d.locator=p.detail_locator
 JOIN ingestion.document ld ON ld.run_id=l.run_id AND ld.document_id=l.document_id
 JOIN ingestion.document dd ON dd.run_id=d.run_id AND dd.document_id=d.document_id
 WHERE p.run_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.capture_posting_census_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r ingestion.run; watermark timestamptz; fingerprint text; census_hash text; n bigint; old ontology.observation_run;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 -- Keep the source rows coherent while the immutable census is copied. This is
 -- a short database transaction, never a lock held across downloads/model calls.
 LOCK TABLE ingestion.run,ingestion.document,ingestion.record IN SHARE MODE;
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-posting-census:'||id,0));
 PERFORM enrichment.assert_snapshot(id,'job_alio');
 SELECT * INTO STRICT r FROM ingestion.run WHERE run_id=id;
 IF r.mode<>'FULL' OR r.completed_at IS NULL THEN RAISE EXCEPTION 'OBSERVATION_REQUIRES_COMPLETED_FULL_RUN'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.document WHERE run_id=id AND selected AND verified_at IS NULL)
 THEN RAISE EXCEPTION 'OBSERVATION_REQUIRES_VERIFIED_DOCUMENTS'; END IF;
 SELECT max(retrieved_at) INTO watermark FROM ingestion.document WHERE run_id=id AND selected;
 IF watermark IS NULL OR watermark>r.completed_at THEN RAISE EXCEPTION 'INVALID_OBSERVATION_WATERMARK'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.ready_record WHERE run_id=id GROUP BY normalized->>'posting_id'
  HAVING normalized->>'posting_id' IS NULL OR count(*)<>2 OR
   count(*) FILTER(WHERE normalized->>'representation'='list')<>1 OR
   count(*) FILTER(WHERE normalized->>'representation'='detail')<>1)
 THEN RAISE EXCEPTION 'OBSERVATION_REQUIRES_COMPLETE_POSTING_PAIRS'; END IF;
 fingerprint:=ontology.source_fingerprint(id);
 SELECT count(*),ontology.hash(coalesce(jsonb_agg(c ORDER BY posting_id COLLATE "C"),'[]'))
 INTO n,census_hash FROM ontology.posting_census_v1(id) c;
 IF 2*n<>(SELECT count(*) FROM ingestion.ready_record WHERE run_id=id)
 THEN RAISE EXCEPTION 'OBSERVATION_POSTING_CENSUS_COUNT_MISMATCH'; END IF;
 SELECT * INTO old FROM ontology.observation_run WHERE run_id=id;
 IF FOUND THEN
  IF old.source_fingerprint<>fingerprint OR old.census_hash<>census_hash OR old.posting_count<>n OR old.watermark_at<>watermark OR old.census_hash IS DISTINCT FROM
   (SELECT ontology.hash(coalesce(jsonb_agg(c ORDER BY posting_id COLLATE "C"),'[]')) FROM ontology.posting_seen c WHERE run_id=id)
  THEN RAISE EXCEPTION 'OBSERVATION_SOURCE_CHANGED'; END IF;
  RETURN;
 END IF;
 INSERT INTO ontology.observation_run(run_id,source_id,source_created_at,source_completed_at,watermark_at,source_fingerprint,posting_count,census_hash)
 VALUES(id,'job_alio',r.created_at,r.completed_at,watermark,fingerprint,n,census_hash);
 INSERT INTO ontology.posting_seen SELECT * FROM ontology.posting_census_v1(id);
END $$;

CREATE OR REPLACE FUNCTION ontology.posting_deadline_v1(n jsonb) RETURNS timestamptz
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE value text:=nullif(n->>'closing_date','');day date;
BEGIN
 IF value IS NULL THEN RETURN NULL; END IF;
 IF value !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN RAISE EXCEPTION 'INVALID_OBSERVED_POSTING_DEADLINE'; END IF;
 BEGIN day:=value::date; EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'INVALID_OBSERVED_POSTING_DEADLINE'; END;
 -- A day-precision deadline includes the entire stated Korean calendar date.
 RETURN (day+1)::timestamp AT TIME ZONE 'Asia/Seoul';
END $$;

CREATE OR REPLACE FUNCTION ontology.observation_candidates_v1(id text,chosen text,cutoff timestamptz,history_manifest jsonb)
RETURNS SETOF ontology.posting_observation LANGUAGE sql STABLE AS $$
 WITH history AS MATERIALIZED (
  SELECT (m.ord-1)::integer AS ordinal,s.* FROM jsonb_array_elements(history_manifest->'runs') WITH ORDINALITY m(x,ord) JOIN ontology.posting_seen s ON s.run_id=m.x->>'run_id'
 ), latest AS (
  SELECT DISTINCT ON(entity_id) * FROM history ORDER BY entity_id,ordinal DESC
 ), states AS (
  SELECT s.*,f.first_seen_at,(jsonb_array_length(history_manifest->'runs')-1)-s.ordinal AS absence,
   ontology.posting_deadline_v1(s.normalized) deadline,
   CASE s.normalized->>'ongoing' WHEN 'false' THEN 'CLOSED' WHEN 'true' THEN 'OPEN' ELSE 'UNKNOWN' END source_status,
   m.revision_id
  FROM latest s JOIN (SELECT entity_id,min(first_observed_at) first_seen_at FROM history GROUP BY entity_id) f USING(entity_id)
  LEFT JOIN ontology.release_revision m ON m.release_id=id AND m.entity_id=s.entity_id
 )
 SELECT id,entity_id,posting_id,revision_id,run_id,first_seen_at,last_observed_at,absence,run_id=chosen,
  CASE WHEN source_status='CLOSED' THEN 'CLOSED' WHEN deadline<=cutoff THEN 'EXPIRED' WHEN absence>=2 THEN 'NOT_SEEN' ELSE 'ACTIVE' END,
  CASE WHEN source_status='CLOSED' THEN 'SOURCE_CLOSED' WHEN deadline<=cutoff THEN 'DEADLINE_ELAPSED'
   WHEN absence>=2 THEN 'ABSENT_FROM_TWO_FULL_RUNS' WHEN absence=1 THEN 'ONE_FULL_RUN_ABSENCE' ELSE 'OBSERVED_IN_FULL_RUN' END,
  deadline,source_status,CASE WHEN revision_id IS NOT NULL THEN 'CURRENT_RELEASE' ELSE 'HISTORICAL_NOT_ASSEMBLED' END FROM states;
$$;

CREATE OR REPLACE FUNCTION ontology.freeze_observations_v1(id text,as_at timestamptz DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE chosen text; cutoff timestamptz; selected_run ingestion.run; watermark timestamptz; item record; manifest jsonb;
 old ontology.observation_freeze;
BEGIN
 PERFORM ontology.require_preparing(id);PERFORM ontology.check_frozen_sources(id);
 SELECT run_id INTO STRICT chosen FROM ontology.source_pin WHERE release_id=id AND source_id='job_alio';
 SELECT * INTO STRICT selected_run FROM ingestion.run WHERE run_id=chosen;
 SELECT * INTO old FROM ontology.observation_freeze WHERE release_id=id;
 IF FOUND THEN
  IF as_at IS NOT NULL AND old.evaluated_at<>as_at THEN RAISE EXCEPTION 'OBSERVATION_EVALUATION_IS_FROZEN'; END IF;
  IF old.manifest_hash<>ontology.hash(old.manifest) OR old.manifest->>'observation_hash' IS DISTINCT FROM
   (SELECT ontology.hash(coalesce(jsonb_agg(o ORDER BY entity_id COLLATE "C"),'[]')) FROM ontology.posting_observation o WHERE release_id=id)
  THEN RAISE EXCEPTION 'FROZEN_OBSERVATION_CONTENT_CHANGED'; END IF;
  IF old.manifest->'runs' IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_object('run_id',o.run_id,'watermark_at',o.watermark_at,
    'source_fingerprint',o.source_fingerprint,'posting_count',o.posting_count,'census_hash',o.census_hash) ORDER BY m.ordinal)
   FROM ontology.observation_history_member m JOIN ontology.observation_run o USING(run_id) WHERE m.release_id=id)
  THEN RAISE EXCEPTION 'FROZEN_OBSERVATION_HISTORY_CHANGED'; END IF;
  FOR item IN SELECT run_id FROM ontology.observation_history_member WHERE release_id=id LOOP
   PERFORM ontology.capture_posting_census_v1(item.run_id);
  END LOOP;
  RETURN;
 END IF;
 cutoff:=coalesce(as_at,clock_timestamp());
 IF NOT isfinite(cutoff) OR cutoff<selected_run.completed_at THEN RAISE EXCEPTION 'OBSERVATION_EVALUATION_BEFORE_SOURCE_COMPLETED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id=id AND v.kind='jobPosting')
  AND EXISTS(SELECT 1 FROM ingestion.ready_record WHERE run_id=chosen)
 THEN RAISE EXCEPTION 'ASSEMBLE_SOURCES_FIRST'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.source_coverage WHERE release_id=id AND unaccounted_records>0)
 THEN RAISE EXCEPTION 'ASSEMBLE_SOURCES_FIRST'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-posting-observation',0));
 LOCK TABLE ingestion.run,ingestion.document,ingestion.record IN SHARE MODE;
 SELECT max(retrieved_at) INTO watermark FROM ingestion.document WHERE run_id=chosen AND selected;
 -- The available successful FULL run set is frozen, not recomputed on replay.
 -- REPLAY, SMOKE, LOADING, REVIEW_REQUIRED and FAILED never advance absence.
 FOR item IN
  SELECT u.run_id FROM ingestion.run u
  JOIN LATERAL (SELECT max(retrieved_at) w FROM ingestion.document d WHERE d.run_id=u.run_id AND d.selected) d ON true
  WHERE u.source_id='job_alio' AND u.mode='FULL' AND u.state='READY' AND u.completed_at<=cutoff
   AND (u.created_at,u.run_id COLLATE "C")<=(selected_run.created_at,chosen COLLATE "C") AND d.w<=watermark
  ORDER BY d.w,u.created_at,u.run_id COLLATE "C"
 LOOP PERFORM ontology.capture_posting_census_v1(item.run_id); END LOOP;
 IF NOT EXISTS(SELECT 1 FROM ontology.observation_run WHERE run_id=chosen) THEN RAISE EXCEPTION 'SELECTED_CENSUS_NOT_CAPTURED'; END IF;
 SELECT jsonb_build_object('contract','posting-observation-v1','through_run_id',chosen,'evaluated_at',cutoff,
  'history_scope','AVAILABLE_ACCEPTED_FULL_SNAPSHOTS','absence_rule','two-consecutive-successful-full-runs',
  'timezone','Asia/Seoul','runs',jsonb_agg(jsonb_build_object('run_id',o.run_id,'watermark_at',o.watermark_at,
    'source_fingerprint',o.source_fingerprint,'posting_count',o.posting_count,'census_hash',o.census_hash)
   ORDER BY o.watermark_at,o.source_created_at,o.run_id COLLATE "C")) INTO manifest
 FROM ontology.observation_run o JOIN ingestion.run u USING(run_id)
 WHERE u.source_id='job_alio' AND u.mode='FULL' AND u.state='READY' AND u.completed_at<=cutoff
  AND (u.created_at,u.run_id COLLATE "C")<=(selected_run.created_at,chosen COLLATE "C") AND o.watermark_at<=watermark;
 SELECT manifest||jsonb_build_object('observation_hash',ontology.hash(coalesce(jsonb_agg(c ORDER BY entity_id COLLATE "C"),'[]')),'observation_count',count(*))
 INTO manifest FROM ontology.observation_candidates_v1(id,chosen,cutoff,manifest) c;
 INSERT INTO ontology.observation_freeze(release_id,through_run_id,evaluated_at,methodology_version,manifest,manifest_hash)
 VALUES(id,chosen,cutoff,'posting-observation-v1',manifest,ontology.hash(manifest));
 INSERT INTO ontology.observation_history_member
 SELECT id,x->>'run_id',ord-1 FROM jsonb_array_elements(manifest->'runs') WITH ORDINALITY a(x,ord);
 INSERT INTO ontology.posting_observation
 SELECT * FROM ontology.observation_candidates_v1(id,chosen,cutoff,manifest);
 IF EXISTS(SELECT 1 FROM ontology.posting_observation o JOIN ontology.release_revision m USING(release_id,entity_id)
   JOIN ontology.revision v ON v.revision_id=m.revision_id JOIN ontology.posting_seen s ON s.run_id=o.content_run_id AND s.posting_id=o.posting_id
   WHERE o.release_id=id AND (NOT o.present_in_selected_run OR enrichment.source_fields(v.payload) IS DISTINCT FROM enrichment.source_fields(s.normalized)))
 THEN RAISE EXCEPTION 'OBSERVATION_RELEASE_CONTENT_MISMATCH'; END IF;
 IF (SELECT count(*) FROM ontology.posting_observation WHERE release_id=id AND present_in_selected_run)<>
  (SELECT posting_count FROM ontology.observation_run WHERE run_id=chosen)
 THEN RAISE EXCEPTION 'OBSERVATION_SELECTED_CENSUS_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.posting_observation WHERE release_id=id AND present_in_selected_run AND selected_revision_id IS NULL)
 THEN RAISE EXCEPTION 'OBSERVATION_CURRENT_REVISION_NOT_ASSEMBLED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.query_observations_v1(choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text;
BEGIN
 id:=ontology.read_release_v1(choice,preview);
 IF NOT EXISTS(SELECT 1 FROM ontology.observation_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'FREEZE_OBSERVATIONS_FIRST'; END IF;
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object(
  'observation_contract','posting-observation-v1',
  'freeze',(SELECT to_jsonb(f) FROM ontology.observation_freeze f WHERE release_id=id),
  'counts',(SELECT jsonb_object_agg(serving_state,n) FROM (SELECT serving_state,count(*) n FROM ontology.posting_observation WHERE release_id=id GROUP BY serving_state) c),
  'historical_not_assembled',(SELECT count(*) FROM ontology.posting_observation WHERE release_id=id AND membership_state='HISTORICAL_NOT_ASSEMBLED'),
  'postings',coalesce((SELECT jsonb_agg(o ORDER BY entity_id COLLATE "C") FROM ontology.posting_observation o WHERE release_id=id),'[]'),
  'meaning','Frozen lifecycle candidates. Historical revision/claim carry-forward and graph/publication integration remain required.');
END $$;

CREATE OR REPLACE FUNCTION ontology.source_freshness_seconds_v1(source text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE source WHEN 'job_alio' THEN 108000 WHEN 'qnet_schedule' THEN 172800
 WHEN 'ncs_competency' THEN 691200 WHEN 'ncs_qualification' THEN 691200
 WHEN 'alio_organization' THEN 3024000 WHEN 'ncs_career_path' THEN 3024000 END
$$;
CREATE OR REPLACE FUNCTION ontology.query_source_health_v1(choice text,preview boolean DEFAULT false,
 as_at timestamptz DEFAULT statement_timestamp()) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text;rows jsonb;
BEGIN
 id:=ontology.read_release_v1(choice,preview);
 IF as_at IS NULL OR NOT isfinite(as_at) THEN RAISE EXCEPTION 'INVALID_SOURCE_HEALTH_TIME'; END IF;
 SELECT jsonb_agg(jsonb_build_object('source_id',p.source_id,'selected_run_id',p.run_id,
  'selected_watermark_at',p.source_watermark_at,'freshness_seconds',ontology.source_freshness_seconds_v1(p.source_id),
  'selected_is_fresh',p.source_watermark_at<=as_at AND as_at-p.source_watermark_at<=make_interval(secs=>ontology.source_freshness_seconds_v1(p.source_id)),
  'latest_full_run_id',latest.run_id,'latest_full_run_state',latest.state,
  'latest_success_run_id',success.run_id,'latest_success_watermark_at',success.watermark,
  'source_health',CASE WHEN latest.state='REVIEW_REQUIRED' THEN 'REVIEW_REQUIRED'
   WHEN latest.state='FAILED' OR (latest.state='READY' AND (latest.completed_at IS NULL OR
    EXISTS(SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id=latest.run_id) OR
    NOT EXISTS(SELECT 1 FROM ingestion.document d WHERE d.run_id=latest.run_id AND d.selected) OR
    EXISTS(SELECT 1 FROM ingestion.document d WHERE d.run_id=latest.run_id AND d.selected AND d.verified_at IS NULL))) THEN 'ERROR'
   WHEN success.watermark IS NULL OR as_at-success.watermark>make_interval(secs=>ontology.source_freshness_seconds_v1(p.source_id)) THEN 'STALE' ELSE 'HEALTHY' END,
  'refresh_in_progress',EXISTS(SELECT 1 FROM ingestion.run u WHERE u.source_id=p.source_id AND u.mode='FULL' AND u.state='LOADING' AND u.created_at<=as_at))
  ORDER BY p.source_id) INTO rows
 FROM ontology.source_pin p
 LEFT JOIN LATERAL (SELECT * FROM ingestion.run u WHERE u.source_id=p.source_id AND u.mode='FULL' AND u.state<>'LOADING'
  AND u.created_at<=as_at AND (u.completed_at IS NULL OR u.completed_at<=as_at) ORDER BY u.created_at DESC,u.run_id COLLATE "C" DESC LIMIT 1) latest ON true
 LEFT JOIN LATERAL (
  SELECT u.run_id,d.watermark FROM ingestion.run u
  JOIN LATERAL (SELECT max(retrieved_at) watermark FROM ingestion.document d WHERE d.run_id=u.run_id AND d.selected) d ON true
  WHERE u.source_id=p.source_id AND u.mode='FULL' AND u.state='READY' AND u.completed_at<=as_at AND d.watermark<=as_at
   AND NOT EXISTS(SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id=u.run_id)
   AND NOT EXISTS(SELECT 1 FROM ingestion.document x WHERE x.run_id=u.run_id AND x.selected AND x.verified_at IS NULL)
  ORDER BY d.watermark DESC,u.created_at DESC,u.run_id COLLATE "C" DESC LIMIT 1
 ) success ON true WHERE p.release_id=id;
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('health_contract','source-health-v1','checked_at',as_at,
  'sources',coalesce(rows,'[]'),'all_selected_sources_fresh',coalesce((SELECT bool_and((x->>'selected_is_fresh')::boolean) FROM jsonb_array_elements(rows) x),false),
  'meaning','Operational health is separate from frozen posting state. Failed runs never extend the successful watermark.');
END $$;
COMMIT;
