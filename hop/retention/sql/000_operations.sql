-- Durable refresh state and conservative request accounting. Install after
-- schema.sql. Reservation happens before HTTP; an interrupted request continues
-- to consume quota because the provider may have received it.
BEGIN;
-- Retention replaces this optional hook when installed. Reinstalling operations
-- must not turn an active maintenance fence off.
DO $$ BEGIN
 IF to_regprocedure('ingestion.maintenance_active()') IS NULL THEN
  EXECUTE 'CREATE FUNCTION ingestion.maintenance_active() RETURNS boolean LANGUAGE sql STABLE AS ''SELECT false''';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS ingestion.refresh_policy (
 source_id text PRIMARY KEY,
 interval_seconds integer NOT NULL CHECK(interval_seconds>0),
 retry_seconds integer NOT NULL DEFAULT 3600 CHECK(retry_seconds>=60),
 requests_per_24h integer NOT NULL DEFAULT 1000 CHECK(requests_per_24h>0),
 enabled boolean NOT NULL DEFAULT true
);
INSERT INTO ingestion.refresh_policy(source_id,interval_seconds) VALUES
 ('alio_organization',2592000),('job_alio',86400),('ncs_competency',604800),
 ('ncs_qualification',604800),('qnet_schedule',86400),('ncs_career_path',2592000)
ON CONFLICT(source_id) DO NOTHING;
CREATE TABLE IF NOT EXISTS ingestion.request_attempt (
 run_id text NOT NULL REFERENCES ingestion.run,
 source_id text NOT NULL,
 partition_id text NOT NULL,
 page_no integer NOT NULL,
 confirmation_no integer NOT NULL,
 reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 completed_at timestamptz,
 outcome text NOT NULL DEFAULT 'RESERVED' CHECK(outcome IN ('RESERVED','RESPONSE_ARCHIVED','TRANSPORT_ERROR')),
 PRIMARY KEY(run_id,partition_id,page_no,confirmation_no),
 FOREIGN KEY(run_id,partition_id) REFERENCES ingestion.partition
);
CREATE INDEX IF NOT EXISTS request_attempt_quota ON ingestion.request_attempt(source_id,reserved_at);
-- Count pre-ledger responses too. This does not reconstruct transport failures
-- that occurred before accounting was installed.
INSERT INTO ingestion.request_attempt(run_id,source_id,partition_id,page_no,confirmation_no,
 reserved_at,completed_at,outcome)
SELECT DISTINCT ON(d.run_id,d.partition_id,d.page_no,d.confirmation_no)
 d.run_id,u.source_id,d.partition_id,d.page_no,d.confirmation_no,d.retrieved_at,d.retrieved_at,'RESPONSE_ARCHIVED'
FROM ingestion.document d JOIN ingestion.run u USING(run_id)
ORDER BY d.run_id,d.partition_id,d.page_no,d.confirmation_no,d.attempt_no
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS ingestion.graph_export (
 run_id text PRIMARY KEY REFERENCES ingestion.run,
 exported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 loader_version text NOT NULL
);
-- The ontology extension is optional for source-only installations. When it is
-- present, capture JOB-ALIO's accepted census in the same transaction as the
-- graph checkpoint. A capture failure leaves the graph recovery path pending.
CREATE OR REPLACE FUNCTION ingestion.record_graph_export_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r ingestion.run;
BEGIN
 SELECT * INTO r FROM ingestion.run WHERE run_id=id AND state='READY' AND mode<>'SMOKE';
 IF NOT FOUND THEN RAISE EXCEPTION 'GRAPH_EXPORT_REQUIRES_READY_SNAPSHOT'; END IF;
 IF r.source_id='job_alio' AND r.mode='FULL' AND to_regprocedure('ontology.capture_posting_census_v1(text)') IS NOT NULL THEN
  EXECUTE 'SELECT ontology.capture_posting_census_v1($1)' USING id;
 END IF;
 INSERT INTO ingestion.graph_export(run_id,loader_version) VALUES(id,'hop-graph-v2')
 ON CONFLICT(run_id) DO UPDATE SET exported_at=clock_timestamp(),loader_version=EXCLUDED.loader_version;
END $$;
CREATE TABLE IF NOT EXISTS ingestion.refresh_execution (
 execution_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source_id text NOT NULL REFERENCES ingestion.refresh_policy,
 operation text NOT NULL CHECK(operation IN ('FETCH','GRAPH')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 finished_at timestamptz,
 exit_code integer
);
CREATE OR REPLACE FUNCTION ingestion.reserve_request(target_run text,target_partition text,
 target_page integer,target_confirmation integer,max_requests integer)
RETURNS TABLE(request_allowed boolean,reservation_reason text)
LANGUAGE plpgsql AS $$
DECLARE src text; budget integer;
BEGIN
 SELECT source_id INTO src FROM ingestion.run WHERE run_id=target_run AND state='LOADING';
 IF src IS NULL THEN RETURN QUERY SELECT false,'RUN_NOT_LOADING'::text;RETURN; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-request:'||src,0));
 SELECT requests_per_24h INTO budget FROM ingestion.refresh_policy WHERE source_id=src;
 IF max_requests NOT BETWEEN 1 AND 1000 OR budget IS NULL THEN
  RETURN QUERY SELECT false,'INVALID_REQUEST_BUDGET'::text;RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ingestion.request_attempt WHERE run_id=target_run AND partition_id=target_partition
  AND page_no=target_page AND confirmation_no=target_confirmation) THEN
  RETURN QUERY SELECT false,'REQUEST_ALREADY_RESERVED'::text;RETURN;
 END IF;
 IF (SELECT count(*) FROM ingestion.request_attempt WHERE source_id=src AND reserved_at>clock_timestamp()-interval '24 hours')>=budget THEN
  RETURN QUERY SELECT false,'PROVIDER_QUOTA_RESERVED'::text;RETURN;
 END IF;
 IF (SELECT count(*) FROM ingestion.request_attempt WHERE run_id=target_run)>=max_requests THEN
  RETURN QUERY SELECT false,'RUN_REQUEST_BUDGET_EXCEEDED'::text;RETURN;
 END IF;
 INSERT INTO ingestion.request_attempt(run_id,source_id,partition_id,page_no,confirmation_no)
 VALUES(target_run,src,target_partition,target_page,target_confirmation);
 RETURN QUERY SELECT true,NULL::text;
END $$;
CREATE OR REPLACE VIEW ingestion.latest_ready_run AS
SELECT DISTINCT ON(source_id) u.* FROM ingestion.run u WHERE state='READY' AND mode<>'SMOKE'
ORDER BY source_id,created_at DESC,run_id DESC;
CREATE OR REPLACE VIEW ingestion.current_record AS
SELECT r.* FROM ingestion.ready_record r JOIN ingestion.latest_ready_run u USING(run_id,source_id);
CREATE OR REPLACE VIEW ingestion.refresh_queue AS
SELECT p.source_id,
 CASE WHEN u.run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=u.run_id)
 THEN 'GRAPH' ELSE 'FETCH' END AS operation,u.run_id,
 CASE p.source_id WHEN 'alio_organization' THEN 1 WHEN 'job_alio' THEN 2
 WHEN 'ncs_competency' THEN 3 WHEN 'ncs_qualification' THEN 4 WHEN 'qnet_schedule' THEN 5 ELSE 6 END AS priority
FROM ingestion.refresh_policy p LEFT JOIN ingestion.latest_ready_run u USING(source_id)
WHERE p.enabled AND NOT ingestion.maintenance_active()
AND (u.run_id IS NULL OR u.created_at<clock_timestamp()-make_interval(secs=>p.interval_seconds)
 OR NOT EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=u.run_id)
 OR EXISTS(SELECT 1 FROM ingestion.dependency d
  JOIN ingestion.latest_ready_run dep ON dep.source_id=d.input_source_id
  WHERE d.run_id=u.run_id AND d.input_run_id<>dep.run_id))
AND NOT EXISTS(SELECT 1 FROM ingestion.refresh_execution x WHERE x.source_id=p.source_id
 AND x.exit_code IS DISTINCT FROM 0
 AND coalesce(x.finished_at,x.started_at)>clock_timestamp()-make_interval(secs=>p.retry_seconds))
AND (p.source_id NOT IN ('job_alio','ncs_qualification','qnet_schedule') OR EXISTS(
 SELECT 1 FROM ingestion.latest_ready_run dep WHERE dep.source_id=CASE p.source_id
 WHEN 'job_alio' THEN 'alio_organization' WHEN 'ncs_qualification' THEN 'ncs_competency' ELSE 'ncs_qualification' END));
COMMIT;
