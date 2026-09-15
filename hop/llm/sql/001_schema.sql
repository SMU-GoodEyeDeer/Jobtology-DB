-- Additive bootstrap. PostgreSQL 17+. No source records are changed.
BEGIN;
CREATE SCHEMA IF NOT EXISTS enrichment;
CREATE OR REPLACE FUNCTION enrichment.hash(v text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT encode(sha256(convert_to(v,'UTF8')),'hex') $$;

-- A completed provider response settles a reservation at its reported cost.
-- Unknown/unfinished requests keep their reservation; audit rows are never erased.
CREATE OR REPLACE FUNCTION enrichment.accounted_cost(state text, reported numeric, reservation numeric)
RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE WHEN state IN ('VALIDATED','REJECTED','ERROR') AND reported>=0
  THEN reported ELSE greatest(reservation,coalesce(reported,0)) END
$$;

CREATE TABLE IF NOT EXISTS enrichment.prompt (
  version text NOT NULL, stage text NOT NULL CHECK(stage IN ('extract','categorize')),
  system_prompt text NOT NULL, output_schema jsonb NOT NULL,
  content_hash text NOT NULL, PRIMARY KEY(version,stage)
);
CREATE TABLE IF NOT EXISTS enrichment.dataset (
  dataset_id text PRIMARY KEY, job_run_id text NOT NULL REFERENCES ingestion.run,
  ncs_run_id text NOT NULL REFERENCES ingestion.run, seed text NOT NULL,
  requested_size integer NOT NULL CHECK(requested_size BETWEEN 1 AND 1000),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.test_case (
  dataset_id text NOT NULL REFERENCES enrichment.dataset,
  posting_id text NOT NULL, source_data jsonb NOT NULL, source_hash text NOT NULL,
  stratum text NOT NULL, ordinal integer NOT NULL,
  PRIMARY KEY(dataset_id,posting_id), UNIQUE(dataset_id,ordinal)
);
CREATE TABLE IF NOT EXISTS enrichment.gold (
  gold_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset_id text NOT NULL, posting_id text NOT NULL,
  labels jsonb NOT NULL, reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(dataset_id,posting_id) REFERENCES enrichment.test_case
);
CREATE TABLE IF NOT EXISTS enrichment.batch (
  batch_id text PRIMARY KEY, mode text NOT NULL CHECK(mode IN ('EVAL','ENRICH')),
  dataset_id text REFERENCES enrichment.dataset,
  job_run_id text NOT NULL REFERENCES ingestion.run,
  ncs_run_id text NOT NULL REFERENCES ingestion.run,
  ncs_hash text NOT NULL, settings jsonb NOT NULL,
  state text NOT NULL CHECK(state IN ('PLANNED','RUNNING','COMPLETE','PARTIAL','FAILED')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz,
  CHECK((mode='EVAL')=(dataset_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS enrichment.ncs_catalog (
  run_id text NOT NULL REFERENCES ingestion.run, code text NOT NULL,
  name text NOT NULL, definition text, occupation_code text, occupation_name text,
  PRIMARY KEY(run_id,code)
);
CREATE TABLE IF NOT EXISTS enrichment.item (
  item_id text PRIMARY KEY, batch_id text NOT NULL REFERENCES enrichment.batch,
  posting_id text NOT NULL, source_data jsonb NOT NULL, source_hash text NOT NULL,
  ordinal integer NOT NULL, gold_id bigint REFERENCES enrichment.gold,
  extraction_id text, categorization_id text,
  state text NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','VALIDATED','REJECTED')),
  issue text, UNIQUE(batch_id,posting_id)
);
CREATE TABLE IF NOT EXISTS enrichment.input_bundle (
 bundle_id text PRIMARY KEY, job_run_id text NOT NULL REFERENCES ingestion.run,
 posting_id text NOT NULL, source_data jsonb NOT NULL, source_hash text NOT NULL,
 manifest jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(source_hash=encode(sha256(convert_to(source_data::text,'UTF8')),'hex'))
);
CREATE TABLE IF NOT EXISTS enrichment.item_input (
 item_id text PRIMARY KEY REFERENCES enrichment.item,
 bundle_id text NOT NULL REFERENCES enrichment.input_bundle
);
CREATE TABLE IF NOT EXISTS enrichment.test_case_input (
 dataset_id text NOT NULL, posting_id text NOT NULL,
 bundle_id text NOT NULL REFERENCES enrichment.input_bundle,
 PRIMARY KEY(dataset_id,posting_id),
 FOREIGN KEY(dataset_id,posting_id) REFERENCES enrichment.test_case
);
CREATE TABLE IF NOT EXISTS enrichment.attempt (
  attempt_id text PRIMARY KEY, batch_id text NOT NULL REFERENCES enrichment.batch,
  item_id text NOT NULL REFERENCES enrichment.item,
  stage text NOT NULL CHECK(stage IN ('extract','categorize')),
  cache_key text NOT NULL, request_body jsonb NOT NULL, candidates jsonb NOT NULL DEFAULT '[]',
  state text NOT NULL CHECK(state IN ('PLANNED','RESERVED','VALIDATED','REJECTED','ERROR','SKIPPED','BUDGET_BLOCKED')),
  reserved_usd numeric NOT NULL DEFAULT 0 CHECK(reserved_usd>=0),
  http_status integer, response_body text, response_id text, actual_model text, provider text,
  parsed_output jsonb, issues jsonb NOT NULL DEFAULT '[]',
  prompt_tokens bigint, completion_tokens bigint, cost_usd numeric,
  latency_ms bigint, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  reserved_at timestamptz, completed_at timestamptz, UNIQUE(item_id,stage)
);
CREATE INDEX IF NOT EXISTS attempt_cache ON enrichment.attempt(cache_key) WHERE state='VALIDATED';
-- ko-v2 stores the provider object separately from its deterministic evidence hydration.
-- Old response bodies/parsed outputs and prompt versions remain untouched.
ALTER TABLE enrichment.attempt ADD COLUMN IF NOT EXISTS raw_output jsonb;
CREATE INDEX IF NOT EXISTS attempt_budget ON enrichment.attempt(reserved_at) WHERE reserved_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS item_batch ON enrichment.item(batch_id);
CREATE TABLE IF NOT EXISTS enrichment.repair_item (
 item_id text PRIMARY KEY REFERENCES enrichment.item,
 prior_item_id text NOT NULL REFERENCES enrichment.item,
 prior_attempt_id text NOT NULL REFERENCES enrichment.attempt,
 trigger_issues jsonb NOT NULL,
 previous_output jsonb,
 audit_version text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.extraction_audit (
 attempt_id text NOT NULL REFERENCES enrichment.attempt,
 validator_version text NOT NULL,
 raw_output_hash text NOT NULL,
 source_hash text NOT NULL,
 issues jsonb NOT NULL,
 checked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(attempt_id,validator_version)
);
CREATE TABLE IF NOT EXISTS enrichment.review (
  review_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_id text NOT NULL REFERENCES enrichment.item,
  decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
  reviewer text NOT NULL CHECK(length(btrim(reviewer))>0), notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.graph_export (
  item_id text PRIMARY KEY REFERENCES enrichment.item,
  review_id bigint NOT NULL REFERENCES enrichment.review, exported_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION enrichment.source_fields(n jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_object_agg(key,value),'{}') FROM jsonb_each(n)
 WHERE key IN ('title','organization_name','education','recruitment_type','employment_type',
 'regions','ncs_category_codes','ncs_category_names','eligibility_text','preference_text',
 'selection_text','disqualification_text','duties_text','description_text')
 AND jsonb_typeof(value)='string' AND length(btrim(value#>>'{}'))>0
$$;
-- New document fields are admitted only through the explicit input contract.
-- source_fields remains the original inline whitelist for old hashes/reviews.
CREATE OR REPLACE FUNCTION enrichment.is_attachment_field(n jsonb,f text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(n#>>'{_input,contract}' IN ('attachment-input-v1','attachment-input-v2') AND f ~ '^attachment_[0-9]+_[0-9]+$'
  AND n#>'{_input,fields}' ? f AND jsonb_typeof(n->f)='string',false)
$$;
CREATE OR REPLACE FUNCTION enrichment.input_fields(n jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT enrichment.source_fields(n)||coalesce(jsonb_object_agg(key,value),'{}') FROM jsonb_each(n)
 WHERE enrichment.is_attachment_field(n,key)
$$;
CREATE OR REPLACE FUNCTION enrichment.narrative_field(n jsonb,f text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT f IN ('eligibility_text','preference_text','disqualification_text','selection_text','duties_text','description_text')
  OR enrichment.is_attachment_field(n,f)
$$;
CREATE OR REPLACE FUNCTION enrichment.assert_snapshot(id text, source text) RETURNS void
LANGUAGE plpgsql STABLE AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM ingestion.run u WHERE u.run_id=id AND u.source_id=source
   AND u.state='READY' AND u.mode<>'SMOKE') OR
   EXISTS(SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id=id) THEN
   RAISE EXCEPTION 'LLM_REQUIRES_VALID_READY_SNAPSHOT: %',source;
 END IF;
END $$;
CREATE OR REPLACE FUNCTION enrichment.resolve_snapshot(choice text, source text) RETURNS text
LANGUAGE plpgsql STABLE AS $$ DECLARE id text; BEGIN
 SELECT u.run_id INTO id FROM ingestion.run u WHERE u.source_id=source AND u.state='READY'
 AND u.mode<>'SMOKE' AND (choice='LATEST' OR choice=u.run_id)
 ORDER BY u.created_at DESC,u.run_id DESC LIMIT 1;
 PERFORM enrichment.assert_snapshot(id,source); RETURN id;
END $$;
COMMIT;
