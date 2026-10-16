-- Additive local-file source ledger. Install after ingestion + operations + retention.
BEGIN;
SELECT retention.gate();

ALTER TABLE ingestion.run DROP CONSTRAINT IF EXISTS run_source_id_check;
ALTER TABLE ingestion.run ADD CONSTRAINT run_source_id_check CHECK (source_id IN (
 'alio_organization','job_alio','nara_job','jobkorea','ncs_career_path',
 'ncs_competency','ncs_qualification','qnet_schedule'));
ALTER TABLE ingestion.document ADD COLUMN IF NOT EXISTS transport text NOT NULL DEFAULT 'HTTP';
ALTER TABLE ingestion.document ALTER COLUMN http_status DROP NOT NULL;
ALTER TABLE ingestion.document DROP CONSTRAINT IF EXISTS document_transport_check;
ALTER TABLE ingestion.document ADD CONSTRAINT document_transport_check CHECK (transport IN('HTTP','LOCAL_FILE'));
ALTER TABLE ingestion.document DROP CONSTRAINT IF EXISTS document_transport_metadata_check;
ALTER TABLE ingestion.document ADD CONSTRAINT document_transport_metadata_check CHECK (
 (transport='HTTP' AND http_status IS NOT NULL) OR
 (transport='LOCAL_FILE' AND http_status IS NULL AND provider_result IS NULL));

CREATE TABLE IF NOT EXISTS ingestion.jobkorea_import (
 run_id text PRIMARY KEY REFERENCES ingestion.run ON DELETE CASCADE,
 document_id text NOT NULL DEFAULT 'local-json' CHECK(document_id='local-json'),
 file_sha256 text NOT NULL CHECK(file_sha256 ~ '^[0-9a-f]{64}$'),
 byte_length bigint NOT NULL,
 raw_path text NOT NULL,
 file_format text NOT NULL DEFAULT 'JSON_ARRAY' CHECK(file_format IN('JSON_ARRAY','NDJSON')),
 next_byte_offset bigint NOT NULL DEFAULT 0 CHECK(next_byte_offset>=0),
 next_line_number bigint NOT NULL DEFAULT 1 CHECK(next_line_number>=1),
 batch_count bigint NOT NULL DEFAULT 0 CHECK(batch_count>=0),
 parser_version text NOT NULL,
 policy_revision text NOT NULL,
 received_at timestamptz NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 processed_at timestamptz,
 scraped_at timestamptz,
 scope text NOT NULL DEFAULT 'FILE_ONLY' CHECK(scope='FILE_ONLY'),
 -- The file is complete evidence of supplied rows, never a provider census.
 provider_complete boolean NOT NULL DEFAULT false CHECK(NOT provider_complete),
 collection_scope jsonb NOT NULL DEFAULT '{"completeness":"UNKNOWN","absence_is_closure":false}',
 payload_sha256 text CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'),
 row_manifest_sha256 text CHECK(row_manifest_sha256 ~ '^[0-9a-f]{64}$'),
 loaded boolean NOT NULL DEFAULT false,
 error_code text,
 UNIQUE(file_sha256,parser_version,policy_revision),
 CHECK(jsonb_typeof(collection_scope)='object'),
 CHECK((loaded AND payload_sha256=file_sha256 AND row_manifest_sha256 IS NOT NULL AND processed_at IS NOT NULL AND error_code IS NULL)
    OR NOT loaded)
);
-- Replay-compatible additive format migration. Array limits and identities stay
-- unchanged; the streaming parser owns the larger NDJSON archive contract.
ALTER TABLE ingestion.jobkorea_import ADD COLUMN IF NOT EXISTS file_format text NOT NULL DEFAULT 'JSON_ARRAY';
ALTER TABLE ingestion.jobkorea_import ADD COLUMN IF NOT EXISTS next_byte_offset bigint NOT NULL DEFAULT 0;
ALTER TABLE ingestion.jobkorea_import ADD COLUMN IF NOT EXISTS next_line_number bigint NOT NULL DEFAULT 1;
ALTER TABLE ingestion.jobkorea_import ADD COLUMN IF NOT EXISTS batch_count bigint NOT NULL DEFAULT 0;
ALTER TABLE ingestion.jobkorea_import DROP CONSTRAINT IF EXISTS jobkorea_import_byte_length_check;
ALTER TABLE ingestion.jobkorea_import DROP CONSTRAINT IF EXISTS jobkorea_import_raw_path_check;
ALTER TABLE ingestion.jobkorea_import DROP CONSTRAINT IF EXISTS jobkorea_import_format_contract;
ALTER TABLE ingestion.jobkorea_import ADD CONSTRAINT jobkorea_import_format_contract CHECK (
 (file_format='JSON_ARRAY' AND byte_length>0 AND byte_length<=67108864
  AND raw_path ~ '^jobkorea/[0-9a-f]{64}/source\.json$') OR
 (file_format='NDJSON' AND byte_length>0 AND byte_length<=17179869184
  AND raw_path ~ '^jobkorea/[0-9a-f]{64}/source\.ndjson$'
  AND next_byte_offset>=0 AND next_byte_offset<=byte_length AND next_line_number>=1 AND batch_count>=0));
CREATE TABLE IF NOT EXISTS ingestion.jobkorea_issue (
 run_id text NOT NULL REFERENCES ingestion.run ON DELETE CASCADE,
 locator text NOT NULL,
 code text NOT NULL,
 field text NOT NULL DEFAULT '',
 severity text NOT NULL CHECK(severity IN ('ERROR','WARNING')),
 -- Only code/field/locator diagnostics belong here; original source values
 -- (including signed references) remain in the protected raw evidence.
 PRIMARY KEY(run_id,locator,code,field)
);

CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE
 ON ingestion.jobkorea_import FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();
CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE
 ON ingestion.jobkorea_issue FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();

CREATE OR REPLACE FUNCTION ingestion.jobkorea_evidence_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_id text; new_id text; id text; accepted boolean; owner text; sealed boolean; invalid boolean;
BEGIN
 PERFORM retention.gate();
 IF TG_OP<>'INSERT' THEN old_id:=OLD.run_id; END IF;
 IF TG_OP<>'DELETE' THEN new_id:=NEW.run_id; END IF;
 IF TG_TABLE_NAME='run' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.source_id='jobkorea' AND NEW.state='READY' THEN
    RAISE EXCEPTION 'JOBKOREA_READY_INSERT_FORBIDDEN';
   END IF;
  ELSIF TG_OP='UPDATE' THEN
   IF NEW.source_id='jobkorea' AND NEW.state='READY' AND OLD.state IS DISTINCT FROM 'READY' THEN
    IF to_regclass('ingestion.jobkorea_validation_issue') IS NULL THEN
     RAISE EXCEPTION 'JOBKOREA_SOURCE_VALIDATOR_NOT_INSTALLED';
    END IF;
    EXECUTE 'SELECT EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=$1)
     OR EXISTS(SELECT 1 FROM ingestion.jobkorea_validation_issue WHERE run_id=$1)' INTO invalid USING new_id;
    IF invalid THEN RAISE EXCEPTION 'JOBKOREA_READY_VALIDATION_FAILED'; END IF;
   END IF;
  END IF;
 END IF;
 FOR id IN SELECT DISTINCT x FROM unnest(ARRAY[old_id,new_id]) x WHERE x IS NOT NULL LOOP
  SELECT state='READY' INTO accepted FROM ingestion.run WHERE run_id=id AND source_id='jobkorea' FOR UPDATE;
  SELECT loaded INTO sealed FROM ingestion.jobkorea_import WHERE run_id=id;
  IF coalesce(accepted,false) THEN
   -- Match the existing retention deletion fence; updates and insertion into
   -- accepted evidence always remain prohibited.
   SELECT p.owner_id INTO owner FROM retention.plan p JOIN retention.plan_run r USING(plan_id)
    WHERE p.state='ACTIVE' AND r.run_id=id AND r.selected;
   IF TG_OP='DELETE' AND owner IS NOT NULL AND
    owner=current_setting('jobtology.retention_owner',true) THEN CONTINUE; END IF;
   RAISE EXCEPTION 'JOBKOREA_READY_EVIDENCE_IMMUTABLE';
  END IF;
  IF coalesce(sealed,false) AND TG_TABLE_NAME IN('record','rejected_row','partition','jobkorea_import')
  THEN
   SELECT p.owner_id INTO owner FROM retention.plan p JOIN retention.plan_run r USING(plan_id)
    WHERE p.state='ACTIVE' AND r.run_id=id AND r.selected;
   IF TG_OP='DELETE' AND owner IS NOT NULL AND
    owner=current_setting('jobtology.retention_owner',true) THEN CONTINUE; END IF;
   RAISE EXCEPTION 'JOBKOREA_LOADED_EVIDENCE_IMMUTABLE';
  END IF;
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;

CREATE OR REPLACE FUNCTION ingestion.jobkorea_no_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM ingestion.run WHERE source_id='jobkorea' AND state='READY')
 THEN RAISE EXCEPTION 'JOBKOREA_READY_EVIDENCE_IMMUTABLE'; END IF;
 RETURN NULL;
END $$;
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['run','dependency','partition','document','record','rejected_row',
  'jobkorea_import','jobkorea_issue'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER jobkorea_ready_evidence BEFORE INSERT OR UPDATE OR DELETE ON ingestion.%I
   FOR EACH ROW EXECUTE FUNCTION ingestion.jobkorea_evidence_guard()',name);
  EXECUTE format('CREATE OR REPLACE TRIGGER jobkorea_ready_no_truncate BEFORE TRUNCATE ON ingestion.%I
   FOR EACH STATEMENT EXECUTE FUNCTION ingestion.jobkorea_no_truncate()',name);
 END LOOP;
END $$;
COMMENT ON TABLE ingestion.jobkorea_import IS
 'Local supplied-file receipt/import/processing events; scraped_at is unknown unless supplied collection evidence supports it. READY covers FILE_ONLY, never provider completeness.';
COMMIT;
