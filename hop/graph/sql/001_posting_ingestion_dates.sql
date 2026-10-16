-- Additive identity dates. Source rows, READY receipts and model inputs stay frozen.
-- Install after shared ingestion and retention; JobKorea itself is optional.
BEGIN;
SELECT retention.gate();

-- Fresh or skewed per-run cardinalities otherwise let the planner rescan an
-- entire supplied file for every wanted posting. This index also bounds direct
-- identity lookup independently of whether autovacuum has analyzed a new run.
CREATE INDEX IF NOT EXISTS record_posting_date_lookup
 ON ingestion.record(run_id,(normalized->>'posting_id'))
 WHERE normalized->>'posting_id' IS NOT NULL;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_index i
  WHERE i.indexrelid='ingestion.record_posting_date_lookup'::regclass
   AND i.indrelid='ingestion.record'::regclass AND i.indisvalid AND NOT i.indisunique
   AND i.indnkeyatts=2 AND pg_get_indexdef(i.indexrelid,1,true)='run_id'
   AND pg_get_indexdef(i.indexrelid,2,true)=$expr$(normalized ->> 'posting_id'::text)$expr$
   AND pg_get_expr(i.indpred,i.indrelid)=$expr$((normalized ->> 'posting_id'::text) IS NOT NULL)$expr$)
 THEN RAISE EXCEPTION 'POSTING_DATE_LOOKUP_INDEX_CONFLICT'; END IF;
END $$;

CREATE TABLE IF NOT EXISTS ingestion.posting_ingestion_observation (
 identity_id text NOT NULL,
 source_id text NOT NULL CHECK(source_id IN('job_alio','nara_job','jobkorea')),
 source_posting_id text NOT NULL CHECK(source_posting_id<>''),
 run_id text NOT NULL CHECK(run_id<>'' AND run_id<>'LATEST'),
 evidence_record_id bigint NOT NULL,
 ingested_at timestamptz NOT NULL CHECK(isfinite(ingested_at)),
 ingestion_time_basis text NOT NULL CHECK(ingestion_time_basis IN('RUN_CREATED_AT','JOBKOREA_IMPORTED_AT')),
 receipt_scraped_at timestamptz CHECK(isfinite(receipt_scraped_at)),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(identity_id,run_id),
 CHECK(receipt_scraped_at IS NULL OR receipt_scraped_at<=ingested_at)
);
CREATE INDEX IF NOT EXISTS posting_ingestion_observation_run
 ON ingestion.posting_ingestion_observation(run_id,identity_id);

CREATE TABLE IF NOT EXISTS ingestion.jobkorea_collection_time_evidence (
 run_id text PRIMARY KEY CHECK(run_id<>'' AND run_id<>'LATEST'),
 file_sha256 text NOT NULL CHECK(file_sha256 ~ '^[0-9a-f]{64}$'),
 scraped_at timestamptz NOT NULL CHECK(isfinite(scraped_at)),
 evidence_source text NOT NULL CHECK(evidence_source='USER_REPORTED'),
 evidence_reference text NOT NULL CHECK(evidence_reference ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$'),
 reported_timezone text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION ingestion.posting_identity(source text,posting text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT CASE source WHEN 'job_alio' THEN 'job-alio:posting:'||posting
 WHEN 'nara_job' THEN 'source:posting:nara_job:'||encode(sha256(convert_to(posting,'UTF8')),'hex')
 WHEN 'jobkorea' THEN 'source:posting:jobkorea:'||encode(sha256(convert_to(posting,'UTF8')),'hex') END
$$;

-- An official source has a recorded ingestion-run creation event, not a row-level
-- import clock. JobKorea has its more precise immutable local import receipt.
CREATE OR REPLACE FUNCTION ingestion.posting_ingestion_run_event(jobs text)
RETURNS TABLE(ingested_at timestamptz,ingestion_time_basis text,receipt_scraped_at timestamptz)
LANGUAGE plpgsql STABLE ROWS 1 AS $$ DECLARE source text; created timestamptz; BEGIN
 SELECT u.source_id,u.created_at INTO source,created FROM ingestion.run u
 WHERE u.run_id=jobs AND u.state='READY' AND u.mode<>'SMOKE';
 IF NOT FOUND THEN RETURN; END IF;
 IF source='jobkorea' THEN
  IF to_regclass('ingestion.jobkorea_import') IS NULL THEN
   RAISE EXCEPTION 'JOBKOREA_IMPORT_RECEIPT_REQUIRED';
  END IF;
  RETURN QUERY EXECUTE 'SELECT i.imported_at,''JOBKOREA_IMPORTED_AT''::text,i.scraped_at
   FROM ingestion.jobkorea_import i WHERE i.run_id=$1 AND i.loaded AND i.error_code IS NULL' USING jobs;
 ELSE
  RETURN QUERY SELECT created,'RUN_CREATED_AT'::text,NULL::timestamptz;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION ingestion.posting_ingestion_observation_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE actual record; BEGIN
 PERFORM retention.gate();
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'IMMUTABLE_POSTING_INGESTION_OBSERVATION'; END IF;
 SELECT r.run_id,r.source_id,r.normalized->>'posting_id' AS posting,e.* INTO actual
 FROM ingestion.ready_record r
 CROSS JOIN LATERAL ingestion.posting_ingestion_run_event(r.run_id) e
 WHERE r.record_id=NEW.evidence_record_id;
 IF NOT FOUND OR actual.run_id IS DISTINCT FROM NEW.run_id
  OR actual.source_id IS DISTINCT FROM NEW.source_id OR actual.posting IS DISTINCT FROM NEW.source_posting_id
  OR ingestion.posting_identity(actual.source_id,actual.posting) IS DISTINCT FROM NEW.identity_id
  OR actual.ingested_at IS DISTINCT FROM NEW.ingested_at
  OR actual.ingestion_time_basis IS DISTINCT FROM NEW.ingestion_time_basis
  OR actual.receipt_scraped_at IS DISTINCT FROM NEW.receipt_scraped_at
 THEN RAISE EXCEPTION 'INVALID_POSTING_INGESTION_OBSERVATION'; END IF;
 NEW.recorded_at:=clock_timestamp();
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER immutable_posting_ingestion_observation
 BEFORE INSERT OR UPDATE OR DELETE ON ingestion.posting_ingestion_observation
 FOR EACH ROW EXECUTE FUNCTION ingestion.posting_ingestion_observation_guard();
CREATE OR REPLACE TRIGGER immutable_posting_ingestion_observation_truncate
 BEFORE TRUNCATE ON ingestion.posting_ingestion_observation
 FOR EACH STATEMENT EXECUTE FUNCTION ingestion.posting_ingestion_observation_guard();
CREATE OR REPLACE TRIGGER retention_write_guard
 BEFORE INSERT OR UPDATE OR DELETE ON ingestion.posting_ingestion_observation
 FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();

-- Validate distinct runs once per INSERT statement. The row guard uses the
-- indexed evidence_record_id lookup; it never reevaluates the whole validator.
CREATE OR REPLACE FUNCTION ingestion.posting_ingestion_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM inserted_observations) THEN RETURN NULL; END IF;
 -- The Boolean test preserves a run-correlated validator SubPlan even before
 -- source statistics exist, avoiding joins across unrelated source histories.
 IF EXISTS(SELECT 1 FROM (SELECT DISTINCT run_id FROM inserted_observations) n
  WHERE (EXISTS(SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id=n.run_id)) IS TRUE)
 THEN RAISE EXCEPTION 'POSTING_DATE_RUN_VALIDATION_FAILED'; END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER validate_posting_ingestion_insert
 AFTER INSERT ON ingestion.posting_ingestion_observation
 REFERENCING NEW TABLE AS inserted_observations
 FOR EACH STATEMENT EXECUTE FUNCTION ingestion.posting_ingestion_insert_guard();

CREATE OR REPLACE FUNCTION ingestion.jobkorea_collection_time_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE receipt record; BEGIN
 PERFORM retention.gate();
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'IMMUTABLE_JOBKOREA_COLLECTION_TIME_EVIDENCE'; END IF;
 IF to_regclass('ingestion.jobkorea_import') IS NULL THEN RAISE EXCEPTION 'JOBKOREA_IMPORT_RECEIPT_REQUIRED'; END IF;
 EXECUTE 'SELECT i.file_sha256,i.imported_at,i.scraped_at FROM ingestion.jobkorea_import i
  JOIN ingestion.run u USING(run_id) WHERE i.run_id=$1 AND u.source_id=''jobkorea''
  AND u.state=''READY'' AND u.mode=''REPLAY'' AND i.loaded AND i.error_code IS NULL
  AND NOT EXISTS(SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id=u.run_id)'
 INTO receipt USING NEW.run_id;
 IF receipt.file_sha256 IS NULL OR receipt.file_sha256 IS DISTINCT FROM NEW.file_sha256
  OR NEW.scraped_at>receipt.imported_at OR NEW.scraped_at>clock_timestamp()
  OR (receipt.scraped_at IS NOT NULL AND receipt.scraped_at IS DISTINCT FROM NEW.scraped_at)
  OR NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=NEW.reported_timezone)
 THEN RAISE EXCEPTION 'INVALID_JOBKOREA_COLLECTION_TIME_EVIDENCE'; END IF;
 NEW.recorded_at:=clock_timestamp();
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER immutable_jobkorea_collection_time_evidence
 BEFORE INSERT OR UPDATE OR DELETE ON ingestion.jobkorea_collection_time_evidence
 FOR EACH ROW EXECUTE FUNCTION ingestion.jobkorea_collection_time_guard();
CREATE OR REPLACE TRIGGER immutable_jobkorea_collection_time_evidence_truncate
 BEFORE TRUNCATE ON ingestion.jobkorea_collection_time_evidence
 FOR EACH STATEMENT EXECUTE FUNCTION ingestion.jobkorea_collection_time_guard();
CREATE OR REPLACE TRIGGER retention_write_guard
 BEFORE INSERT OR UPDATE OR DELETE ON ingestion.jobkorea_collection_time_evidence
 FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();

CREATE OR REPLACE FUNCTION ingestion.register_jobkorea_collection_time(
 jobs text,file_hash text,collection_time timestamptz,source text,reference text,timezone_name text)
RETURNS void LANGUAGE plpgsql AS $$ DECLARE prior ingestion.jobkorea_collection_time_evidence; BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('posting-collection-time:'||jobs,0));
 SELECT * INTO prior FROM ingestion.jobkorea_collection_time_evidence WHERE run_id=jobs;
 IF FOUND THEN
  IF ROW(prior.file_sha256,prior.scraped_at,prior.evidence_source,prior.evidence_reference,prior.reported_timezone)
   IS DISTINCT FROM ROW(file_hash,collection_time,source,reference,timezone_name)
  THEN RAISE EXCEPTION 'IMMUTABLE_JOBKOREA_COLLECTION_TIME_EVIDENCE'; END IF;
  RETURN;
 END IF;
 INSERT INTO ingestion.jobkorea_collection_time_evidence
 (run_id,file_sha256,scraped_at,evidence_source,evidence_reference,reported_timezone)
 VALUES(jobs,file_hash,collection_time,source,reference,timezone_name);
END $$;

CREATE OR REPLACE FUNCTION ingestion.record_posting_ingestion_observations(jobs text)
RETURNS bigint LANGUAGE plpgsql AS $$ DECLARE added bigint; source text; BEGIN
 PERFORM retention.gate();
 SELECT u.source_id INTO source FROM ingestion.run u
  WHERE u.run_id=jobs AND u.state='READY' AND u.mode<>'SMOKE';
 IF jobs IS NULL OR jobs='LATEST' OR source IS NULL
 THEN RAISE EXCEPTION 'POSTING_DATES_REQUIRE_EXACT_READY_RUN'; END IF;
 IF source NOT IN('job_alio','nara_job','jobkorea') THEN RETURN 0; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id=jobs)
 THEN RAISE EXCEPTION 'POSTING_DATES_REQUIRE_EXACT_READY_RUN'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('posting-ingestion-observations',0));
 WITH source_rows AS MATERIALIZED (
  SELECT r.source_id,r.run_id,r.normalized->>'posting_id' AS posting,
   min(r.record_id) AS evidence_record_id
  FROM ingestion.ready_record r WHERE r.source_id=source AND r.normalized->>'posting_id' IS NOT NULL
  GROUP BY r.source_id,r.run_id,r.normalized->>'posting_id'
 ), matched AS MATERIALIZED (
  -- Mark each posting's accepted historical occurrences in one ordered pass.
  -- Matching a freshly imported wanted set with a join can underestimate its
  -- cardinality and compare every posting against every source row.
  SELECT s.*,bool_or(s.run_id=jobs) OVER(PARTITION BY s.source_id,s.posting) AS in_target
  FROM source_rows s
 ), valid_runs AS MATERIALIZED (
  SELECT u.run_id FROM ingestion.run u WHERE u.state='READY' AND u.mode<>'SMOKE'
   AND u.source_id=source
   -- Keep validation correlated to each candidate run. An unfenced NOT EXISTS
   -- can pull up the expanded validator and compare unrelated source records
   -- quadratically when a fresh import has not yet been autoanalyzed.
   AND (NOT EXISTS(SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id=u.run_id)) IS TRUE
 ), selected AS MATERIALIZED (
  SELECT r.source_id,r.posting,r.run_id,r.evidence_record_id
  FROM matched r JOIN valid_runs u USING(run_id) WHERE r.in_target
 ), events AS MATERIALIZED (
  SELECT x.run_id,e.* FROM (SELECT DISTINCT run_id FROM selected) x
  CROSS JOIN LATERAL ingestion.posting_ingestion_run_event(x.run_id) e
 )
 INSERT INTO ingestion.posting_ingestion_observation
 (identity_id,source_id,source_posting_id,run_id,evidence_record_id,ingested_at,ingestion_time_basis,receipt_scraped_at)
 SELECT ingestion.posting_identity(s.source_id,s.posting),s.source_id,s.posting,s.run_id,s.evidence_record_id,
  e.ingested_at,e.ingestion_time_basis,e.receipt_scraped_at
 FROM selected s JOIN events e USING(run_id)
 WHERE NOT EXISTS(SELECT 1 FROM ingestion.posting_ingestion_observation prior
  WHERE prior.identity_id=ingestion.posting_identity(s.source_id,s.posting) AND prior.run_id=s.run_id)
 ON CONFLICT(identity_id,run_id) DO NOTHING;
 GET DIAGNOSTICS added=ROW_COUNT;
 IF EXISTS(SELECT 1 FROM ingestion.ready_record r WHERE r.run_id=jobs
  AND r.source_id IN('job_alio','nara_job','jobkorea') AND r.normalized->>'posting_id' IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM ingestion.posting_ingestion_observation o WHERE o.run_id=jobs
   AND o.identity_id=ingestion.posting_identity(r.source_id,r.normalized->>'posting_id')))
 THEN RAISE EXCEPTION 'POSTING_DATE_OBSERVATION_MISSING'; END IF;
 RETURN added;
END $$;

CREATE OR REPLACE FUNCTION ingestion.graph_posting_ingestion_dates(jobs text)
RETURNS TABLE(identity_id text,first_ingested_at text,last_ingested_at text,latest_ingestion_run_id text,
 ingestion_batch_date text,ingestion_time_basis text,scraped_at text,scraped_at_basis text,
 scraped_at_evidence_reference text)
LANGUAGE plpgsql STABLE AS $$ BEGIN
 IF jobs IS NULL OR jobs='LATEST' OR NOT EXISTS(SELECT 1 FROM ingestion.run u
  WHERE u.run_id=jobs AND u.state='READY' AND u.mode<>'SMOKE')
 THEN RAISE EXCEPTION 'POSTING_DATES_REQUIRE_EXACT_READY_RUN'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.ready_record r WHERE r.run_id=jobs
  AND r.source_id IN('job_alio','nara_job','jobkorea') AND r.normalized->>'posting_id' IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM ingestion.posting_ingestion_observation o WHERE o.run_id=jobs
   AND o.identity_id=ingestion.posting_identity(r.source_id,r.normalized->>'posting_id')))
 THEN RAISE EXCEPTION 'POSTING_DATE_OBSERVATION_MISSING'; END IF;
 RETURN QUERY WITH wanted AS MATERIALIZED (
  SELECT DISTINCT o.identity_id FROM ingestion.posting_ingestion_observation o WHERE o.run_id=jobs
 ), ranked AS (
  SELECT o.*,min(o.ingested_at) OVER(PARTITION BY o.identity_id) AS first_at,
   row_number() OVER(PARTITION BY o.identity_id ORDER BY o.ingested_at DESC,o.run_id DESC) AS choice
  FROM ingestion.posting_ingestion_observation o JOIN wanted w USING(identity_id)
 )
 SELECT o.identity_id,to_char(o.first_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  to_char(o.ingested_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),o.run_id,
  to_char(o.ingested_at AT TIME ZONE 'Asia/Seoul','YYYY-MM-DD'),o.ingestion_time_basis,
  to_char(coalesce(e.scraped_at,o.receipt_scraped_at) AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  CASE WHEN e.scraped_at IS NOT NULL THEN e.evidence_source
   WHEN o.receipt_scraped_at IS NOT NULL THEN 'IMPORT_RECEIPT' END,e.evidence_reference
 FROM ranked o LEFT JOIN ingestion.jobkorea_collection_time_evidence e ON e.run_id=o.run_id
 WHERE o.choice=1 ORDER BY o.identity_id;
END
$$;

COMMENT ON TABLE ingestion.posting_ingestion_observation IS
 'Append-only accepted posting membership/import events. No run FK: minimal validated date provenance survives source retention without preventing cleanup. evidence_record_id is the original native record locator; names, facts and LLM hashes are untouched.';
COMMENT ON TABLE ingestion.jobkorea_collection_time_evidence IS
 'Append-only supplemental collection evidence bound to a READY JobKorea file digest. USER_REPORTED is an assertion, not API verification; recorded_at is its actual registration time. Original import receipt scraped_at stays immutable.';
COMMENT ON FUNCTION ingestion.graph_posting_ingestion_dates(text) IS
 'Affected posting identities aggregate retained accepted occurrence events independently of display names. Scrape evidence comes exclusively from their latest containing run; a newer unknown collection clears older scrape fields. Batch date is Asia/Seoul.';
COMMIT;
