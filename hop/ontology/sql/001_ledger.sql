-- Native Hop ontology ledger. PostgreSQL is authoritative; Neo4j is rebuildable.
BEGIN;
CREATE SCHEMA IF NOT EXISTS ontology;
CREATE OR REPLACE FUNCTION ontology.hash(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to('hop-ontology-jsonb-v1:'||v::text,'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION ontology.iri(kind text, code text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT 'urn:jobtology:'||kind||':'||code
$$;
CREATE TABLE IF NOT EXISTS ontology.corpus_release (
 release_id text PRIMARY KEY,
 state text NOT NULL DEFAULT 'PREPARING' CHECK(state IN ('PREPARING','READY','ACTIVE','SUPERSEDED','REVOKED','FAILED')),
 pipeline_version text NOT NULL DEFAULT 'hop-ontology-v1',
 methodology_version text NOT NULL DEFAULT 'public-sector-v1',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 data_as_of timestamptz,
 manifest_hash text,
 manifest jsonb,
 graph_verified_at timestamptz,
 activated_at timestamptz,
 revoked_at timestamptz,
 revocation_reason text,
 CHECK((manifest IS NULL)=(manifest_hash IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_ontology_release ON ontology.corpus_release((true)) WHERE state='ACTIVE';
CREATE TABLE IF NOT EXISTS ontology.source_pin (
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 source_id text NOT NULL,
 run_id text NOT NULL REFERENCES ingestion.run,
 source_watermark_at timestamptz NOT NULL,
 source_fingerprint text NOT NULL,
 record_count bigint NOT NULL CHECK(record_count>=0),
 document_count bigint NOT NULL CHECK(document_count>=0),
 PRIMARY KEY(release_id,source_id), UNIQUE(release_id,run_id)
);
CREATE TABLE IF NOT EXISTS ontology.input_record (
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 record_id bigint NOT NULL,
 source_id text NOT NULL,
 run_id text NOT NULL,
 document_id text NOT NULL,
 locator text NOT NULL,
 source_record_id text NOT NULL,
 normalized jsonb NOT NULL,
 normalized_hash text NOT NULL,
 field_lineage jsonb NOT NULL,
 raw_sha256 text NOT NULL,
 PRIMARY KEY(release_id,record_id),
 FOREIGN KEY(release_id,run_id) REFERENCES ontology.source_pin(release_id,run_id)
);
CREATE INDEX IF NOT EXISTS ontology_input_identity ON ontology.input_record(release_id,source_id,source_record_id);
CREATE TABLE IF NOT EXISTS ontology.entity (
 entity_id text PRIMARY KEY,
 kind text NOT NULL CHECK(kind IN ('organization','jobPosting','occupation','ncsClass','ncsCompetency',
  'ncsUnitFamily','qualification','examSession','careerRank','conceptScheme','skill','majorConcept','course','courseInstance','actionTemplate','place')),
 code text NOT NULL,
 scheme_id text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.revision (
 revision_id text PRIMARY KEY,
 entity_id text NOT NULL REFERENCES ontology.entity,
 kind text NOT NULL,
 name text NOT NULL CHECK(length(btrim(name))>0),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 payload_hash text NOT NULL,
 schema_version text NOT NULL DEFAULT 'hop-ontology-v1',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(entity_id,revision_id)
);
CREATE TABLE IF NOT EXISTS ontology.release_revision (
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 entity_id text NOT NULL,
 revision_id text NOT NULL,
 PRIMARY KEY(release_id,entity_id),
 FOREIGN KEY(entity_id,revision_id) REFERENCES ontology.revision(entity_id,revision_id)
);
CREATE TABLE IF NOT EXISTS ontology.revision_support (
 release_id text NOT NULL,
 entity_id text NOT NULL,
 record_id bigint NOT NULL,
 fields text[] NOT NULL,
 PRIMARY KEY(release_id,entity_id,record_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.release_revision,
 FOREIGN KEY(release_id,record_id) REFERENCES ontology.input_record
);
CREATE INDEX IF NOT EXISTS ontology_support_by_record ON ontology.revision_support(release_id,record_id);
CREATE TABLE IF NOT EXISTS ontology.source_relation (
 relation_id text PRIMARY KEY,
 subject_id text NOT NULL REFERENCES ontology.entity,
 predicate text NOT NULL,
 object_id text NOT NULL REFERENCES ontology.entity,
 qualifiers jsonb NOT NULL DEFAULT '{}',
 assertion_kind text NOT NULL DEFAULT 'SOURCE_FACT' CHECK(assertion_kind='SOURCE_FACT'),
 acceptance_policy text NOT NULL DEFAULT 'source-reference-v1',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.release_relation (
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 relation_id text NOT NULL REFERENCES ontology.source_relation,
 record_id bigint NOT NULL,
 source_fields text[] NOT NULL,
 PRIMARY KEY(release_id,relation_id,record_id),
 FOREIGN KEY(release_id,record_id) REFERENCES ontology.input_record
);
CREATE TABLE IF NOT EXISTS ontology.quality_observation (
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 object_id text NOT NULL,
 code text NOT NULL,
 detail jsonb NOT NULL,
 PRIMARY KEY(release_id,object_id,code)
);

CREATE OR REPLACE FUNCTION ontology.immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_ONTOLOGY_RECORD: %',TG_TABLE_NAME; END $$;
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['source_pin','input_record','entity','revision','release_revision','revision_support',
  'source_relation','release_relation','quality_observation'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||name AND tgrelid=('ontology.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.require_preparing(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM 1 FROM ontology.corpus_release WHERE release_id=id AND state='PREPARING' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'ONTOLOGY_RELEASE_NOT_PREPARING'; END IF;
END $$;
CREATE OR REPLACE FUNCTION ontology.source_fingerprint(id text) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT ontology.hash(jsonb_build_object(
  'run',(SELECT to_jsonb(r) FROM ingestion.run r WHERE run_id=id),
  'documents',(SELECT jsonb_agg(to_jsonb(d)-'verified_at' ORDER BY document_id) FROM ingestion.document d WHERE run_id=id),
  'records',(SELECT jsonb_agg(jsonb_build_array(record_id,document_id,locator,ontology.hash(to_jsonb(r))) ORDER BY record_id)
   FROM ingestion.record r WHERE run_id=id),
  'dependencies',(SELECT jsonb_agg(to_jsonb(d) ORDER BY input_source_id) FROM ingestion.dependency d WHERE run_id=id)))
$$;
CREATE OR REPLACE FUNCTION ontology.check_frozen_sources(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p ontology.source_pin%ROWTYPE; historical record; BEGIN
 IF (SELECT count(*) FROM ontology.source_pin WHERE release_id=id)<>6 THEN RAISE EXCEPTION 'SIX_SOURCE_PINS_REQUIRED'; END IF;
 FOR p IN SELECT * FROM ontology.source_pin WHERE release_id=id LOOP
  PERFORM enrichment.assert_snapshot(p.run_id,p.source_id);
  IF EXISTS(SELECT 1 FROM ingestion.document d WHERE d.run_id=p.run_id AND d.selected AND d.verified_at IS NULL)
  THEN RAISE EXCEPTION 'UNVERIFIED_SOURCE_FILES: %',p.source_id; END IF;
  IF ontology.source_fingerprint(p.run_id)<>p.source_fingerprint THEN RAISE EXCEPTION 'PINNED_SOURCE_CHANGED: %',p.source_id; END IF;
 END LOOP;
 -- Frozen absence evidence includes intervening successful runs even when no
 -- posting's selected content comes from that particular run.
 FOR historical IN SELECT r.* FROM ontology.observation_history_member m JOIN ontology.observation_run r USING(run_id)
  WHERE m.release_id=id AND NOT EXISTS(SELECT 1 FROM ontology.source_pin s WHERE s.release_id=id AND s.run_id=r.run_id) LOOP
  PERFORM enrichment.assert_snapshot(historical.run_id,'job_alio');
  IF ontology.source_fingerprint(historical.run_id)<>historical.source_fingerprint OR
   EXISTS(SELECT 1 FROM ingestion.document d WHERE d.run_id=historical.run_id AND d.selected AND d.verified_at IS NULL)
  THEN RAISE EXCEPTION 'HISTORICAL_OBSERVATION_SOURCE_CHANGED'; END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.prepare_release(id text, source_choices jsonb DEFAULT '{}') RETURNS void
LANGUAGE plpgsql AS $$
DECLARE source text; chosen_run text; fingerprint text; watermark timestamptz; rc bigint; dc bigint;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF nullif(btrim(id),'') IS NULL OR jsonb_typeof(source_choices) IS DISTINCT FROM 'object' OR
  EXISTS(SELECT 1 FROM jsonb_object_keys(source_choices) k WHERE k NOT IN
   ('alio_organization','job_alio','ncs_competency','ncs_qualification','qnet_schedule','ncs_career_path'))
 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_RELEASE_PARAMETERS'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id) THEN
  PERFORM ontology.require_preparing(id);
  IF EXISTS(SELECT 1 FROM jsonb_each_text(source_choices) c JOIN ontology.source_pin p
   ON p.release_id=id AND p.source_id=c.key WHERE c.value<>'LATEST' AND c.value<>p.run_id)
  THEN RAISE EXCEPTION 'RELEASE_SOURCE_SELECTION_IS_IMMUTABLE'; END IF;
  PERFORM ontology.check_frozen_sources(id); RETURN;
 END IF;
 INSERT INTO ontology.corpus_release(release_id) VALUES(id);
 FOREACH source IN ARRAY ARRAY['alio_organization','job_alio','ncs_competency','ncs_qualification','qnet_schedule','ncs_career_path'] LOOP
  chosen_run:=enrichment.resolve_snapshot(coalesce(source_choices->>source,'LATEST'),source);
  IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=chosen_run AND mode='FULL') THEN RAISE EXCEPTION 'FULL_SOURCE_REQUIRED: %',source; END IF;
  IF EXISTS(SELECT 1 FROM ingestion.document d WHERE d.run_id=chosen_run AND d.selected AND d.verified_at IS NULL)
  THEN RAISE EXCEPTION 'UNVERIFIED_SOURCE_FILES: %',source; END IF;
  SELECT count(*),max(retrieved_at) INTO dc,watermark FROM ingestion.document d WHERE d.run_id=chosen_run AND d.selected;
  SELECT count(*) INTO rc FROM ingestion.ready_record WHERE run_id=chosen_run;
  IF dc=0 OR watermark IS NULL THEN RAISE EXCEPTION 'MISSING_SELECTED_SOURCE_OBSERVATIONS: %',source; END IF;
  fingerprint:=ontology.source_fingerprint(chosen_run);
  INSERT INTO ontology.source_pin VALUES(id,source,chosen_run,watermark,fingerprint,rc,dc);
  INSERT INTO ontology.input_record(release_id,record_id,source_id,run_id,document_id,locator,source_record_id,normalized,normalized_hash,field_lineage,raw_sha256)
  SELECT id,r.record_id,source,r.run_id,r.document_id,r.locator,r.source_record_id,r.normalized,
   ontology.hash(r.normalized),r.field_lineage,d.raw_sha256 FROM ingestion.ready_record r
  JOIN ingestion.document d USING(run_id,document_id) WHERE r.run_id=chosen_run;
 END LOOP;
 UPDATE ontology.corpus_release SET data_as_of=(SELECT min(source_watermark_at) FROM ontology.source_pin WHERE release_id=id) WHERE release_id=id;
 PERFORM ontology.check_frozen_sources(id);
END $$;
COMMENT ON FUNCTION ontology.hash(jsonb) IS 'Versioned PostgreSQL JSONB serialization, not RFC 8785 JCS. IDs are opaque; interchange does not recalculate IDs.';
COMMIT;
