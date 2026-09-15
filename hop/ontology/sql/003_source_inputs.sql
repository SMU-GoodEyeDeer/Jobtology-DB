-- Release-scoped attachment input selection and document evidence. No acceptance.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.document_input_set (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 manifest_hash text NOT NULL, manifest jsonb NOT NULL,
 selected_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.document_input (
 release_id text NOT NULL REFERENCES ontology.document_input_set,
 entity_id text NOT NULL,bundle_id text NOT NULL REFERENCES enrichment.input_bundle,
 PRIMARY KEY(release_id,entity_id),UNIQUE(release_id,bundle_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.release_revision
);
CREATE TABLE IF NOT EXISTS ontology.artifact_document (
 release_id text NOT NULL,artifact_id text NOT NULL REFERENCES ontology.text_artifact,
 entity_id text NOT NULL,bundle_id text NOT NULL REFERENCES enrichment.input_bundle,
 file_ordinal integer NOT NULL,attempt_id text NOT NULL REFERENCES attachment.attempt,
 record_id bigint NOT NULL,descriptor jsonb NOT NULL,binding jsonb NOT NULL,
 PRIMARY KEY(release_id,artifact_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.document_input,
 FOREIGN KEY(release_id,record_id) REFERENCES ontology.input_record
);
CREATE TABLE IF NOT EXISTS ontology.document_section (
 release_id text NOT NULL,artifact_id text NOT NULL,section_index integer NOT NULL,
 source_locator jsonb NOT NULL,original_start integer NOT NULL,original_end integer NOT NULL,
 normalized_start integer NOT NULL,normalized_end integer NOT NULL,
 PRIMARY KEY(release_id,artifact_id,section_index),CHECK(section_index>=0),
 FOREIGN KEY(release_id,artifact_id) REFERENCES ontology.artifact_document,
 CHECK(original_start>=0 AND original_end>=original_start AND normalized_start>=0 AND normalized_end>=normalized_start)
);
CREATE OR REPLACE FUNCTION ontology.document_input_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'IMMUTABLE_ONTOLOGY_DOCUMENT_INPUT'; END IF;
 PERFORM ontology.require_preparing(NEW.release_id);
 IF TG_TABLE_NAME IN ('document_input_set','document_input') AND EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=NEW.release_id)
 THEN RAISE EXCEPTION 'REVIEW_SELECTION_ALREADY_FROZEN'; END IF;
 RETURN NEW;
END $$;
-- Only evidence used by this release's selected assertions belongs in its graph.
CREATE OR REPLACE VIEW ontology.release_evidence AS
 SELECT m.release_id,e.evidence_id FROM ontology.release_claim m JOIN ontology.claim_evidence e USING(claim_id)
 UNION SELECT m.release_id,e.evidence_id FROM ontology.release_claim m JOIN ontology.condition_evidence e USING(claim_id)
 UNION SELECT m.release_id,e.evidence_id FROM ontology.release_position m JOIN ontology.position_evidence e USING(position_id)
 UNION SELECT release_id,evidence_id FROM ontology.rule_evidence;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['document_input_set','document_input','artifact_document','document_section'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=('ontology.'||t)::regclass AND tgname='document_input_guard') THEN
   EXECUTE format('CREATE TRIGGER document_input_guard BEFORE INSERT OR UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.document_input_guard()',t);
  END IF;
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION ontology.verify_document_inputs(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE selected ontology.document_input_set;row_data record;actual jsonb; BEGIN
 SELECT * INTO selected FROM ontology.document_input_set WHERE release_id=id;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT coalesce(jsonb_object_agg(entity_id,bundle_id),'{}') INTO actual FROM ontology.document_input WHERE release_id=id;
 IF selected.manifest IS DISTINCT FROM actual OR selected.manifest_hash IS DISTINCT FROM ontology.hash(actual)
 THEN RAISE EXCEPTION 'ONTOLOGY_DOCUMENT_SELECTION_CHANGED'; END IF;
 IF (SELECT count(*) FROM ontology.document_input WHERE release_id=id)<>
  (SELECT count(*) FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id=id AND v.kind='jobPosting')
 THEN RAISE EXCEPTION 'COMPLETE_POSTING_INPUT_SET_REQUIRED'; END IF;
 FOR row_data IN SELECT d.*,b.job_run_id,b.posting_id,b.source_data,v.kind,v.payload,p.run_id
  FROM ontology.document_input d JOIN enrichment.input_bundle b USING(bundle_id)
  JOIN ontology.release_revision m USING(release_id,entity_id) JOIN ontology.revision v USING(revision_id)
  JOIN ontology.source_pin p ON p.release_id=d.release_id AND p.source_id='job_alio' WHERE d.release_id=id LOOP
  IF row_data.kind<>'jobPosting' OR row_data.job_run_id IS DISTINCT FROM row_data.run_id OR row_data.posting_id IS DISTINCT FROM row_data.payload->>'posting_id'
   OR enrichment.source_fields(row_data.source_data) IS DISTINCT FROM enrichment.source_fields(row_data.payload)
  THEN RAISE EXCEPTION 'ONTOLOGY_DOCUMENT_INPUT_SOURCE_MISMATCH'; END IF;
  PERFORM attachment.verify_input_bundle(row_data.bundle_id);
 END LOOP;
 IF EXISTS(SELECT 1 FROM ontology.posting_selection p JOIN ontology.document_input d USING(release_id,entity_id)
  JOIN enrichment.input_bundle b USING(bundle_id) WHERE p.release_id=id AND
   (p.source_data IS DISTINCT FROM b.source_data OR p.source_hash IS DISTINCT FROM b.source_hash
    OR p.provenance->>'input_bundle_id' IS DISTINCT FROM d.bundle_id))
 THEN RAISE EXCEPTION 'ONTOLOGY_REVIEW_INPUT_MISMATCH'; END IF;
END $$;
CREATE OR REPLACE FUNCTION ontology.bind_document_inputs(id text,bundles text[]) RETURNS void LANGUAGE plpgsql AS $$
DECLARE jobs text;expected jsonb;previous ontology.document_input_set; BEGIN
 PERFORM ontology.require_preparing(id);PERFORM ontology.check_frozen_sources(id);
 IF cardinality(bundles) IS NULL OR cardinality(bundles) NOT BETWEEN 1 AND 10000 OR
  cardinality(bundles)<>(SELECT count(DISTINCT x) FROM unnest(bundles) x)
 THEN RAISE EXCEPTION 'EXACT_ONTOLOGY_INPUT_BUNDLES_REQUIRED'; END IF;
 SELECT run_id INTO STRICT jobs FROM ontology.source_pin WHERE release_id=id AND source_id='job_alio';
 IF (SELECT count(*) FROM enrichment.input_bundle WHERE bundle_id=ANY(bundles) AND job_run_id=jobs)<>cardinality(bundles) OR
  (SELECT count(DISTINCT posting_id) FROM enrichment.input_bundle WHERE bundle_id=ANY(bundles))<>cardinality(bundles)
 THEN RAISE EXCEPTION 'ONTOLOGY_INPUT_SNAPSHOT_OR_POSTING_MISMATCH'; END IF;
 SELECT jsonb_object_agg(m.entity_id,b.bundle_id) INTO expected
 FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id)
 JOIN enrichment.input_bundle b ON b.posting_id=v.payload->>'posting_id' AND b.bundle_id=ANY(bundles)
 WHERE m.release_id=id AND v.kind='jobPosting';
 IF expected IS NULL OR (SELECT count(*) FROM jsonb_object_keys(expected))<>cardinality(bundles)
 THEN RAISE EXCEPTION 'ONTOLOGY_INPUT_POSTING_NOT_IN_RELEASE'; END IF;
 SELECT * INTO previous FROM ontology.document_input_set WHERE release_id=id;
 IF FOUND THEN
  IF previous.manifest IS DISTINCT FROM expected THEN RAISE EXCEPTION 'ONTOLOGY_DOCUMENT_INPUTS_ARE_FROZEN'; END IF;
  PERFORM ontology.verify_document_inputs(id);RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'BIND_INPUTS_BEFORE_REVIEW_FREEZE'; END IF;
 INSERT INTO ontology.document_input_set(release_id,manifest_hash,manifest) VALUES(id,ontology.hash(expected),expected);
 INSERT INTO ontology.document_input SELECT id,key,value FROM jsonb_each_text(expected);
 PERFORM ontology.verify_document_inputs(id);
END $$;
CREATE OR REPLACE FUNCTION ontology.posting_input(id text,entity text,payload jsonb) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE value jsonb; BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.document_input_set WHERE release_id=id) THEN RETURN enrichment.source_fields(payload); END IF;
 SELECT b.source_data INTO STRICT value FROM ontology.document_input d JOIN enrichment.input_bundle b USING(bundle_id)
 WHERE d.release_id=id AND d.entity_id=entity;
 RETURN value;
END $$;
CREATE OR REPLACE FUNCTION ontology.store_document_artifact(id text,entity text,artifact text,field text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b enrichment.input_bundle;descriptor jsonb;binding jsonb;source_record bigint;original text;normalized text;part jsonb;n integer:=0;
 first_pos integer;last_pos integer;prefix text;body text;suffix text; BEGIN
 PERFORM ontology.require_preparing(id);
 SELECT x.* INTO STRICT b FROM ontology.document_input d JOIN enrichment.input_bundle x USING(bundle_id) WHERE d.release_id=id AND d.entity_id=entity;
 IF NOT enrichment.is_attachment_field(b.source_data,field) THEN RAISE EXCEPTION 'ONTOLOGY_ATTACHMENT_FIELD_REQUIRED'; END IF;
 descriptor:=b.source_data#>ARRAY['_input','fields',field];original:=b.source_data->>field;normalized:=ontology.normalize_text(original);
 SELECT value INTO STRICT binding FROM jsonb_array_elements(b.manifest->'documents') WHERE value->>'field'=field;
 SELECT i.record_id INTO STRICT source_record FROM ontology.input_record i
 WHERE i.release_id=id AND i.source_id='job_alio' AND i.run_id=b.job_run_id AND i.document_id=b.manifest->>'source_document_id' AND i.locator=b.manifest->>'source_locator';
 IF NOT EXISTS(SELECT 1 FROM ontology.text_artifact WHERE artifact_id=artifact AND posting_id=entity AND source_field=field
  AND input_sha256=enrichment.hash(original) AND normalized_text=normalized)
 THEN RAISE EXCEPTION 'ONTOLOGY_ATTACHMENT_ARTIFACT_MISMATCH'; END IF;
 INSERT INTO ontology.artifact_document VALUES(id,artifact,entity,b.bundle_id,(binding->>'file_ordinal')::integer,
  binding->>'attempt_id',source_record,descriptor,binding) ON CONFLICT DO NOTHING;
 FOR part IN SELECT value FROM jsonb_array_elements(binding->'sections') LOOP
  first_pos:=(part->>'start')::integer;last_pos:=(part->>'end')::integer;
  prefix:=ontology.normalize_text(left(original,first_pos));body:=ontology.normalize_text(substring(original FROM first_pos+1 FOR last_pos-first_pos));
  suffix:=ontology.normalize_text(substring(original FROM last_pos+1));
  IF prefix||body||suffix<>normalized THEN RAISE EXCEPTION 'DOCUMENT_SECTION_NORMALIZATION_BOUNDARY'; END IF;
  INSERT INTO ontology.document_section VALUES(id,artifact,n,part,first_pos,last_pos,length(prefix),length(prefix)+length(body)) ON CONFLICT DO NOTHING;
  n:=n+1;
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION ontology.verify_document_evidence(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE d record;b enrichment.input_bundle;s record;original text; BEGIN
 PERFORM ontology.verify_document_inputs(id);
 FOR d IN SELECT x.*,a.posting_id,a.source_field,a.input_sha256,a.normalized_text,a.text_sha256 FROM ontology.artifact_document x JOIN ontology.text_artifact a USING(artifact_id) WHERE x.release_id=id LOOP
  SELECT * INTO STRICT b FROM enrichment.input_bundle WHERE bundle_id=d.bundle_id;
  original:=b.source_data->>d.source_field;
  IF NOT enrichment.is_attachment_field(b.source_data,d.source_field) OR d.descriptor IS DISTINCT FROM b.source_data#>ARRAY['_input','fields',d.source_field]
   OR d.binding IS DISTINCT FROM (SELECT value FROM jsonb_array_elements(b.manifest->'documents') WHERE value->>'field'=d.source_field)
   OR d.input_sha256 IS DISTINCT FROM enrichment.hash(original) OR d.normalized_text IS DISTINCT FROM ontology.normalize_text(original)
   OR d.text_sha256 IS DISTINCT FROM enrichment.hash(d.normalized_text)
   OR d.entity_id IS DISTINCT FROM d.posting_id
   OR d.attempt_id IS DISTINCT FROM d.binding->>'attempt_id'
   OR d.file_ordinal IS DISTINCT FROM (d.binding->>'file_ordinal')::integer
   OR NOT EXISTS(SELECT 1 FROM ontology.posting_selection p WHERE p.release_id=id AND p.entity_id=d.entity_id AND p.outcome='ACCEPTED')
   OR NOT EXISTS(SELECT 1 FROM ontology.release_evidence r JOIN ontology.evidence_span e USING(evidence_id)
    WHERE r.release_id=id AND e.artifact_id=d.artifact_id)
   OR NOT EXISTS(SELECT 1 FROM ontology.document_input WHERE release_id=id AND entity_id=d.entity_id AND bundle_id=d.bundle_id)
   OR NOT EXISTS(SELECT 1 FROM ontology.input_record WHERE release_id=id AND record_id=d.record_id AND source_id='job_alio' AND run_id=b.job_run_id
    AND document_id=b.manifest->>'source_document_id' AND locator=b.manifest->>'source_locator')
  THEN RAISE EXCEPTION 'ONTOLOGY_DOCUMENT_EVIDENCE_MISMATCH'; END IF;
  IF (SELECT count(*) FROM ontology.document_section WHERE release_id=id AND artifact_id=d.artifact_id)<>jsonb_array_length(d.binding->'sections')
  THEN RAISE EXCEPTION 'ONTOLOGY_DOCUMENT_SECTION_COVERAGE'; END IF;
  FOR s IN SELECT * FROM ontology.document_section WHERE release_id=id AND artifact_id=d.artifact_id LOOP
   IF s.section_index<0 OR s.source_locator IS DISTINCT FROM d.binding->'sections'->s.section_index OR s.original_start IS DISTINCT FROM (s.source_locator->>'start')::integer OR s.original_end IS DISTINCT FROM (s.source_locator->>'end')::integer
    OR s.normalized_start<>length(ontology.normalize_text(left(original,s.original_start))) OR s.normalized_end<>length(ontology.normalize_text(left(original,s.original_end)))
    OR enrichment.hash(substring(original FROM s.original_start+1 FOR s.original_end-s.original_start))<>s.source_locator->>'content_hash'
   THEN RAISE EXCEPTION 'ONTOLOGY_DOCUMENT_SECTION_MISMATCH'; END IF;
  END LOOP;
 END LOOP;
 IF EXISTS(SELECT 1 FROM ontology.release_evidence r JOIN ontology.evidence_span e USING(evidence_id)
  JOIN ontology.text_artifact a USING(artifact_id) WHERE r.release_id=id AND
  NOT EXISTS(SELECT 1 FROM ontology.artifact_source src WHERE src.release_id=id AND src.artifact_id=a.artifact_id) AND
  NOT EXISTS(SELECT 1 FROM ontology.artifact_document doc WHERE doc.release_id=id AND doc.artifact_id=a.artifact_id))
 THEN RAISE EXCEPTION 'ONTOLOGY_EVIDENCE_HAS_NO_SOURCE'; END IF;
END $$;
COMMIT;
