-- A release keeps six current source pins and may retain exact historical JOB
-- records needed by its frozen observation history. Current pins stay immutable.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.release_source_run (
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 run_id text NOT NULL REFERENCES ingestion.run,
 source_id text NOT NULL,
 role text NOT NULL CHECK(role IN ('CURRENT','HISTORICAL')),
 source_watermark_at timestamptz NOT NULL,
 source_fingerprint text NOT NULL,
 PRIMARY KEY(release_id,run_id),
 CHECK(role='CURRENT' OR source_id='job_alio')
);
CREATE OR REPLACE FUNCTION ontology.source_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'IMMUTABLE_RELEASE_SOURCE_RUN'; END IF;
 IF NEW.role='CURRENT' THEN
  IF NOT EXISTS(SELECT 1 FROM ontology.source_pin p WHERE p.release_id=NEW.release_id AND p.run_id=NEW.run_id
   AND p.source_id=NEW.source_id AND p.source_watermark_at=NEW.source_watermark_at AND p.source_fingerprint=NEW.source_fingerprint)
  THEN RAISE EXCEPTION 'CURRENT_SOURCE_RUN_REQUIRES_EXACT_PIN'; END IF;
 ELSE
  PERFORM ontology.require_preparing(NEW.release_id);
  IF NOT EXISTS(SELECT 1 FROM ontology.observation_history_member m JOIN ontology.observation_run r USING(run_id)
   WHERE m.release_id=NEW.release_id AND m.run_id=NEW.run_id AND r.source_id=NEW.source_id
    AND r.watermark_at=NEW.source_watermark_at AND r.source_fingerprint=NEW.source_fingerprint)
   OR NOT EXISTS(SELECT 1 FROM ontology.posting_observation o WHERE o.release_id=NEW.release_id
    AND o.content_run_id=NEW.run_id AND NOT o.present_in_selected_run)
  THEN RAISE EXCEPTION 'HISTORICAL_SOURCE_RUN_REQUIRES_FROZEN_OBSERVATION'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION ontology.register_current_source_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO ontology.release_source_run VALUES(NEW.release_id,NEW.run_id,NEW.source_id,'CURRENT',NEW.source_watermark_at,NEW.source_fingerprint);
 RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='ontology.release_source_run'::regclass AND tgname='source_run_guard') THEN
  CREATE TRIGGER source_run_guard BEFORE INSERT OR UPDATE OR DELETE ON ontology.release_source_run FOR EACH ROW EXECUTE FUNCTION ontology.source_run_guard();
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='ontology.source_pin'::regclass AND tgname='register_current_source_run') THEN
  CREATE TRIGGER register_current_source_run AFTER INSERT ON ontology.source_pin FOR EACH ROW EXECUTE FUNCTION ontology.register_current_source_run();
 END IF;
END $$;
INSERT INTO ontology.release_source_run
 SELECT release_id,run_id,source_id,'CURRENT',source_watermark_at,source_fingerprint FROM ontology.source_pin ON CONFLICT DO NOTHING;
-- Replace only the old current-pin FK. Record/evidence/revision-support keys and
-- old rows are unchanged; historical membership is checked by the guarded table.
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='ontology.input_record'::regclass
  AND contype='f' AND confrelid='ontology.source_pin'::regclass LOOP
  EXECUTE format('ALTER TABLE ontology.input_record DROP CONSTRAINT %I',c.conname);
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='ontology.input_record'::regclass AND conname='input_record_release_source_run') THEN
  ALTER TABLE ontology.input_record ADD CONSTRAINT input_record_release_source_run
   FOREIGN KEY(release_id,run_id) REFERENCES ontology.release_source_run;
 END IF;
END $$;

CREATE TABLE IF NOT EXISTS ontology.observation_membership (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 manifest jsonb NOT NULL,
 manifest_hash text NOT NULL CHECK(manifest_hash=ontology.hash(manifest)),
 bound_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.entity_observation_state (
 observation_state_id text PRIMARY KEY,
 release_id text NOT NULL REFERENCES ontology.observation_membership,
 entity_id text NOT NULL,
 selected_revision_id text NOT NULL,
 entity_type text NOT NULL CHECK(entity_type='jobPosting'),
 source_id text NOT NULL CHECK(source_id='job_alio'),
 connector_run_id text NOT NULL REFERENCES ingestion.run,
 content_run_id text NOT NULL REFERENCES ingestion.run,
 first_seen_at timestamptz NOT NULL,
 last_seen_at timestamptz NOT NULL,
 consecutive_absence_count integer NOT NULL CHECK(consecutive_absence_count>=0),
 serving_state text NOT NULL CHECK(serving_state IN ('ACTIVE','EXPIRED','CLOSED','NOT_SEEN')),
 state_reason text NOT NULL,
 evaluated_at timestamptz NOT NULL,
 methodology_version text NOT NULL CHECK(methodology_version='posting-observation-membership-v1'),
 UNIQUE(release_id,entity_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.release_revision,
 FOREIGN KEY(entity_id,selected_revision_id) REFERENCES ontology.revision(entity_id,revision_id),
 FOREIGN KEY(release_id,content_run_id) REFERENCES ontology.release_source_run,
 CHECK(first_seen_at<=last_seen_at AND last_seen_at<=evaluated_at)
);
CREATE INDEX IF NOT EXISTS ontology_observation_state_by_release ON ontology.entity_observation_state(release_id,serving_state,last_seen_at);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['observation_membership','entity_observation_state'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=('ontology.'||t)::regclass AND tgname='ontology_immutable_'||t) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()', 'ontology_immutable_'||t,t);
  END IF;
 END LOOP;
END $$;
COMMIT;
