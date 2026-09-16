-- Append-only corrections and separate extraction/link decisions.
-- Existing whole-item reviews and their historical graph exports are untouched.
BEGIN;
CREATE TABLE IF NOT EXISTS enrichment.extraction_revision (
 revision_id text PRIMARY KEY,
 revision_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 item_id text NOT NULL REFERENCES enrichment.item,
 parent_revision_id text REFERENCES enrichment.extraction_revision,
 raw_output jsonb NOT NULL,
 extraction jsonb NOT NULL,
 actor text NOT NULL CHECK(length(btrim(actor))>0),
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.extraction_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 revision_id text NOT NULL REFERENCES enrichment.extraction_revision,
 decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant','policy')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
 notes text NOT NULL CHECK(length(btrim(notes))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.link_candidate (
 candidate_id text PRIMARY KEY,
 revision_id text NOT NULL REFERENCES enrichment.extraction_revision,
 ncs_run_id text NOT NULL,
 competency_code text NOT NULL,
 duty_index integer NOT NULL CHECK(duty_index>=0),
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 origin text NOT NULL CHECK(origin IN ('model','reviewer')),
 actor text NOT NULL CHECK(length(btrim(actor))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(revision_id,competency_code,duty_index),
 FOREIGN KEY(ncs_run_id,competency_code) REFERENCES enrichment.ncs_catalog(run_id,code)
);
CREATE TABLE IF NOT EXISTS enrichment.link_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 candidate_id text NOT NULL REFERENCES enrichment.link_candidate,
 decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant','policy')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
 notes text NOT NULL CHECK(length(btrim(notes))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION enrichment.append_only_review() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'APPEND_ONLY_REVIEW_HISTORY'; END $$;
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['extraction_revision','extraction_decision','link_candidate','link_decision','repair_item','extraction_audit','input_bundle','item_input','test_case_input'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='immutable_'||name
   AND tgrelid=('enrichment.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON enrichment.%I FOR EACH ROW EXECUTE FUNCTION enrichment.append_only_review()',
    'immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION enrichment.capture_extraction(id text, actor text, reason text,
 corrected jsonb DEFAULT NULL, parent text DEFAULT NULL) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE item enrichment.item%ROWTYPE; b enrichment.batch%ROWTYPE; output jsonb; hydrated jsonb;
 errors jsonb; contract_version text; rid text; previous text;
BEGIN
 SELECT * INTO STRICT item FROM enrichment.item WHERE item_id=id FOR UPDATE;
 PERFORM enrichment.verify_item_input(id);
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=item.batch_id;
 IF b.mode<>'ENRICH' THEN RAISE EXCEPTION 'EVAL_CANNOT_ENTER_PRODUCTION_REVIEW'; END IF;
 IF nullif(btrim(actor),'') IS NULL OR nullif(btrim(reason),'') IS NULL THEN RAISE EXCEPTION 'REVIEW_PROVENANCE_REQUIRED'; END IF;
 IF parent IS NOT NULL AND corrected IS NULL THEN RAISE EXCEPTION 'CORRECTION_OUTPUT_REQUIRED'; END IF;
 SELECT coalesce(corrected,a.raw_output,a.parsed_output) INTO output FROM enrichment.attempt a WHERE a.attempt_id=item.extraction_id;
 IF output IS NULL THEN RAISE EXCEPTION 'EXTRACTION_OUTPUT_REQUIRED'; END IF;
 contract_version:=b.settings->>'prompt_version';
 SELECT CASE WHEN contract_version IN ('ko-v6','ko-v7') THEN enrichment.schema_issues_v6(output,p.output_schema) ELSE enrichment.schema_issues(output,p.output_schema) END INTO errors FROM enrichment.prompt p WHERE p.version=contract_version AND p.stage='extract';
 IF errors IS DISTINCT FROM '[]'::jsonb THEN RAISE EXCEPTION 'INVALID_CORRECTION_SCHEMA: %',errors; END IF;
 CASE contract_version
  WHEN 'ko-v7' THEN
   errors:=enrichment.output_issues_v7(output,item.source_data);
   IF errors<>'[]'::jsonb THEN RAISE EXCEPTION 'CORRECTION_NOT_VALIDATED: %',errors; END IF;
   hydrated:=enrichment.hydrate_v7(output,item.source_data);
  WHEN 'ko-v6' THEN errors:=enrichment.output_issues_v6(output,item.source_data); hydrated:=enrichment.hydrate_v6(output,item.source_data);
  WHEN 'ko-v5' THEN errors:=enrichment.output_issues_v5(output,item.source_data); hydrated:=enrichment.hydrate_v5(output,item.source_data);
  WHEN 'ko-v4' THEN errors:=enrichment.output_issues_v4(output,item.source_data); hydrated:=enrichment.hydrate_v4(output,item.source_data);
  WHEN 'ko-link-v1' THEN errors:=enrichment.output_issues_link_v1(output,item.source_data); hydrated:=enrichment.hydrate_link_v1(output,item.source_data);
  WHEN 'ko-v3' THEN errors:=enrichment.output_issues_v3(output,item.source_data); hydrated:=enrichment.hydrate_v3(output,item.source_data);
  WHEN 'ko-v2' THEN errors:=enrichment.output_issues_v2(output,item.source_data); hydrated:=enrichment.hydrate_v2(output,item.source_data);
  WHEN 'ko-v1' THEN errors:=enrichment.output_issues('extract',output,item.source_data,NULL,'[]',8); hydrated:=output;
  ELSE RAISE EXCEPTION 'UNKNOWN_REVIEW_CONTRACT';
 END CASE;
 IF errors<>'[]'::jsonb THEN RAISE EXCEPTION 'CORRECTION_NOT_VALIDATED: %',errors; END IF;
 rid:=enrichment.hash(jsonb_build_array(id,parent,contract_version,output)::text);
 IF EXISTS(SELECT 1 FROM enrichment.extraction_revision WHERE revision_id=rid) THEN RETURN rid; END IF;
 SELECT revision_id INTO previous FROM enrichment.extraction_revision WHERE item_id=id ORDER BY revision_no DESC LIMIT 1;
 IF parent IS DISTINCT FROM previous THEN RAISE EXCEPTION 'STALE_REVISION_PARENT'; END IF;
 INSERT INTO enrichment.extraction_revision(revision_id,item_id,parent_revision_id,raw_output,extraction,actor,reason)
 VALUES(rid,id,parent,output,hydrated,actor,reason);
 RETURN rid;
END $$;

CREATE OR REPLACE FUNCTION enrichment.propose_link(revision text, code text, duty integer, explanation text,
 who text, provenance text DEFAULT 'reviewer') RETURNS text LANGUAGE plpgsql AS $$
DECLARE r enrichment.extraction_revision%ROWTYPE; ncs text; id text; existing enrichment.link_candidate%ROWTYPE;
BEGIN
 SELECT * INTO STRICT r FROM enrichment.extraction_revision WHERE revision_id=revision;
 IF duty IS NULL OR duty<0 OR duty>=jsonb_array_length(r.extraction->'duties') THEN RAISE EXCEPTION 'LINK_REQUIRES_EXPLICIT_DUTY'; END IF;
 SELECT b.ncs_run_id INTO ncs FROM enrichment.item i JOIN enrichment.batch b USING(batch_id) WHERE i.item_id=r.item_id;
 id:=enrichment.hash(jsonb_build_array(revision,code,duty)::text);
 SELECT * INTO existing FROM enrichment.link_candidate WHERE candidate_id=id;
 IF FOUND THEN
  IF existing.reason IS DISTINCT FROM explanation OR existing.origin IS DISTINCT FROM provenance
  THEN RAISE EXCEPTION 'LINK_CANDIDATE_IS_IMMUTABLE'; END IF;
  RETURN id;
 END IF;
 INSERT INTO enrichment.link_candidate(candidate_id,revision_id,ncs_run_id,competency_code,duty_index,reason,origin,actor)
 VALUES(id,revision,ncs,code,duty,explanation,provenance,who);
 RETURN id;
END $$;

-- Import a model shortlist only if it was validated against the exact same duties.
-- Correcting duty order/text invalidates its indices; it needs fresh categorization.
CREATE OR REPLACE FUNCTION enrichment.import_model_links(revision text, who text) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE r enrichment.extraction_revision%ROWTYPE; e jsonb; c jsonb; link jsonb; n integer:=0;
BEGIN
 SELECT * INTO STRICT r FROM enrichment.extraction_revision WHERE revision_id=revision;
 SELECT x.parsed_output,y.parsed_output INTO e,c FROM enrichment.item i
 JOIN enrichment.attempt x ON x.attempt_id=i.extraction_id
 JOIN enrichment.attempt y ON y.attempt_id=i.categorization_id AND y.state IN ('VALIDATED','SKIPPED')
 WHERE i.item_id=r.item_id;
 IF c IS NULL THEN RAISE EXCEPTION 'NO_VALIDATED_CATEGORIZATION'; END IF;
 IF e->'duties' IS DISTINCT FROM r.extraction->'duties' THEN RAISE EXCEPTION 'DUTIES_CHANGED_RECATEGORIZE'; END IF;
 FOR link IN SELECT jsonb_array_elements(c->'matches') LOOP
  PERFORM enrichment.propose_link(revision,link->>'competency_code',(link->>'duty_index')::integer,link->>'reason',who,'model');
  n:=n+1;
 END LOOP;
 RETURN n;
END $$;

CREATE OR REPLACE FUNCTION enrichment.decide_extraction(revision text, choice text, who text, kind text, explanation text)
RETURNS void LANGUAGE sql AS $$
 INSERT INTO enrichment.extraction_decision(revision_id,decision,reviewer,reviewer_kind,notes)
 VALUES(revision,choice,who,kind,explanation)
$$;
CREATE OR REPLACE FUNCTION enrichment.decide_link(candidate text, choice text, who text, kind text, explanation text)
RETURNS void LANGUAGE sql AS $$
 INSERT INTO enrichment.link_decision(candidate_id,decision,reviewer,reviewer_kind,notes)
 VALUES(candidate,choice,who,kind,explanation)
$$;

CREATE OR REPLACE VIEW enrichment.latest_extraction_decision AS
SELECT DISTINCT ON(revision_id) * FROM enrichment.extraction_decision ORDER BY revision_id,decision_id DESC;
CREATE OR REPLACE VIEW enrichment.latest_link_decision AS
SELECT DISTINCT ON(candidate_id) * FROM enrichment.link_decision ORDER BY candidate_id,decision_id DESC;
CREATE OR REPLACE VIEW enrichment.extraction_review_state AS
SELECT r.*,d.decision_id,d.decision,d.reviewer_kind,d.reviewer,d.notes,d.created_at AS reviewed_at
FROM enrichment.extraction_revision r LEFT JOIN enrichment.latest_extraction_decision d USING(revision_id);

-- A new correction supersedes its predecessor immediately for current serving.
-- It must acquire its own review; rejection never falls back to an earlier revision.
CREATE OR REPLACE VIEW enrichment.current_reviewed_posting AS
WITH source_posting AS (
 SELECT 'job_alio'::text AS source_id,p.run_id,p.posting_id,p.list_document_id,p.list_locator,
  p.detail_document_id,p.detail_locator,p.normalized,p.field_origin
 FROM ingestion.job_posting p
 JOIN ingestion.latest_ready_run j ON j.run_id=p.run_id AND j.source_id='job_alio'
 UNION ALL
 SELECT p.source_id,p.run_id,p.posting_id,NULL::text,NULL::text,NULL::text,NULL::text,
  p.normalized,'{}'::jsonb
 FROM ingestion.llm_posting p
 JOIN ingestion.latest_ready_run j ON j.run_id=p.run_id AND j.source_id=p.source_id
 WHERE p.source_id<>'job_alio'
)
SELECT p.run_id,p.posting_id,p.list_document_id,p.list_locator,p.detail_document_id,p.detail_locator,
 p.normalized,p.field_origin,r.revision_id,CASE WHEN r.decision='ACCEPT' THEN r.extraction END AS extraction,
 r.decision,r.reviewer_kind,r.reviewer,r.reviewed_at,
 coalesce(links.matches,'[]'::jsonb) AS reviewed_ncs_links
FROM source_posting p
LEFT JOIN LATERAL (
 SELECT s.* FROM enrichment.extraction_review_state s
 JOIN enrichment.item i USING(item_id)
 JOIN enrichment.batch b USING(batch_id)
 WHERE i.posting_id=p.posting_id AND i.source_hash=enrichment.hash(enrichment.source_fields(p.normalized)::text)
   AND b.job_run_id=p.run_id
 ORDER BY s.revision_no DESC LIMIT 1
) r ON true
LEFT JOIN LATERAL (
 SELECT jsonb_agg(jsonb_build_object('candidate_id',c.candidate_id,'competency_code',c.competency_code,
  'duty_index',c.duty_index,'reason',c.reason,'reviewer_kind',d.reviewer_kind,'reviewer',d.reviewer,
  'reviewed_at',d.created_at,'decision_id',d.decision_id,'ncs_run_id',c.ncs_run_id)
  ORDER BY c.duty_index,c.competency_code) AS matches
 FROM enrichment.link_candidate c JOIN enrichment.latest_link_decision d USING(candidate_id)
 WHERE c.revision_id=r.revision_id AND r.decision='ACCEPT' AND d.decision='ACCEPT'
 AND c.ncs_run_id=(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency')
) links ON true;

COMMENT ON VIEW enrichment.current_reviewed_posting IS
 'Current source-qualified posting extractions. Check decision=ACCEPT for extraction serving. NCS links require independent acceptance and the current NCS catalog; extraction survives NCS refresh. Reviewer kind is explicit, never inferred as human.';
COMMIT;
