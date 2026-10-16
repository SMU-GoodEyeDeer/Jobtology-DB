-- Bind a composed local snapshot to the archived original-file occurrence map.
-- Raw exports and the potentially large map stay in the protected archive.
BEGIN;
SELECT retention.gate();

CREATE TABLE IF NOT EXISTS ingestion.jobkorea_dataset_provenance (
 run_id text PRIMARY KEY REFERENCES ingestion.run ON DELETE CASCADE,
 provenance jsonb NOT NULL CHECK(jsonb_typeof(provenance)='object'),
 registered_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION ingestion.jobkorea_dataset_provenance_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE owner text; BEGIN
 PERFORM retention.gate();
 IF TG_OP='INSERT' THEN
  PERFORM ingestion.validate_jobkorea_dataset_provenance(NEW.run_id,NEW.provenance);
  RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN
  SELECT p.owner_id INTO owner FROM retention.plan p JOIN retention.plan_run r USING(plan_id)
   WHERE p.state='ACTIVE' AND r.run_id=OLD.run_id AND r.selected;
  IF owner IS NOT NULL AND owner=current_setting('jobtology.retention_owner',true) THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'IMMUTABLE_JOBKOREA_DATASET_PROVENANCE';
END $$;
CREATE OR REPLACE TRIGGER immutable_dataset_provenance BEFORE INSERT OR UPDATE OR DELETE
 ON ingestion.jobkorea_dataset_provenance FOR EACH ROW
 EXECUTE FUNCTION ingestion.jobkorea_dataset_provenance_guard();
CREATE OR REPLACE TRIGGER immutable_dataset_provenance_truncate BEFORE TRUNCATE
 ON ingestion.jobkorea_dataset_provenance FOR EACH STATEMENT
 EXECUTE FUNCTION ingestion.jobkorea_dataset_provenance_guard();
CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE
 ON ingestion.jobkorea_dataset_provenance FOR EACH STATEMENT
 EXECUTE FUNCTION retention.freeze_writes();

CREATE OR REPLACE FUNCTION ingestion.validate_jobkorea_dataset_provenance(jobs text,p jsonb) RETURNS void
LANGUAGE plpgsql AS $$ DECLARE receipt ingestion.jobkorea_import; prepared boolean;
BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('jobkorea-input-provenance:'||jobs,0));
 IF jobs IS NULL OR jobs='LATEST' OR jsonb_typeof(p) IS DISTINCT FROM 'object'
  OR p->>'contract' IS DISTINCT FROM 'jobkorea-dataset-provenance-v1'
  OR p->>'row_key' IS DISTINCT FROM 'composed_line'
  OR NOT p ?& ARRAY['snapshot_sha256','snapshot_byte_length','selected_count',
   'occurrences_sha256','occurrences_byte_length','descriptor_sha256','descriptor_byte_length','archive_relative_root']
  OR EXISTS(SELECT 1 FROM jsonb_object_keys(p) k WHERE k NOT IN ('contract','row_key','snapshot_sha256',
   'snapshot_byte_length','selected_count','occurrences_sha256','occurrences_byte_length',
   'descriptor_sha256','descriptor_byte_length','archive_relative_root'))
  OR EXISTS(SELECT 1 FROM unnest(ARRAY['snapshot_sha256','occurrences_sha256','descriptor_sha256']) k
   WHERE jsonb_typeof(p->k) IS DISTINCT FROM 'string' OR p->>k !~ '^[0-9a-f]{64}$')
  OR EXISTS(SELECT 1 FROM unnest(ARRAY['snapshot_byte_length','selected_count','occurrences_byte_length','descriptor_byte_length']) k
   WHERE jsonb_typeof(p->k) IS DISTINCT FROM 'number' OR p->>k !~ '^[1-9][0-9]{0,11}$')
  OR p->>'archive_relative_root' IS DISTINCT FROM 'jobkorea/datasets/'||(p->>'descriptor_sha256')
 THEN RAISE EXCEPTION 'INVALID_JOBKOREA_DATASET_PROVENANCE'; END IF;
 SELECT i.* INTO STRICT receipt FROM ingestion.jobkorea_import i JOIN ingestion.run u USING(run_id)
  WHERE i.run_id=jobs AND u.source_id='jobkorea' AND u.state='READY' AND u.mode='REPLAY';
 IF NOT receipt.loaded OR receipt.error_code IS NOT NULL OR receipt.file_format<>'NDJSON'
  OR receipt.file_sha256 IS DISTINCT FROM p->>'snapshot_sha256'
  OR receipt.byte_length IS DISTINCT FROM (p->>'snapshot_byte_length')::bigint
  OR receipt.next_line_number-1 IS DISTINCT FROM (p->>'selected_count')::bigint
 THEN RAISE EXCEPTION 'JOBKOREA_DATASET_SNAPSHOT_BINDING_INVALID'; END IF;
 IF to_regclass('enrichment.input_bundle') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM enrichment.input_bundle WHERE job_run_id=$1)' INTO prepared USING jobs;
  IF prepared THEN RAISE EXCEPTION 'JOBKOREA_DATASET_PROVENANCE_MUST_PRECEDE_INPUTS'; END IF;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION ingestion.register_jobkorea_dataset_provenance(jobs text,p jsonb) RETURNS void
LANGUAGE plpgsql AS $$ DECLARE existing jsonb; BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('jobkorea-input-provenance:'||jobs,0));
 SELECT provenance INTO existing FROM ingestion.jobkorea_dataset_provenance WHERE run_id=jobs;
 IF FOUND THEN
  IF existing IS DISTINCT FROM p THEN RAISE EXCEPTION 'IMMUTABLE_JOBKOREA_DATASET_PROVENANCE'; END IF;
  RETURN;
 END IF;
 -- The INSERT trigger applies the same validation to function and direct writes.
 INSERT INTO ingestion.jobkorea_dataset_provenance(run_id,provenance) VALUES(jobs,p);
END $$;

COMMENT ON TABLE ingestion.jobkorea_dataset_provenance IS
 'Immutable archive digest binding for original local exports, selected unchanged lines, duplicate observations and selection policy. Each bundle physical_line resolves into occurrences.ndjson. No model-facing data is added.';
COMMIT;
