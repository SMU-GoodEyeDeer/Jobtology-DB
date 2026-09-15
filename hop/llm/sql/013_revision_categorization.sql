-- Categorize an accepted extraction revision without another extraction request.
BEGIN;
CREATE TABLE IF NOT EXISTS enrichment.revision_input (
 item_id text PRIMARY KEY REFERENCES enrichment.item,
 revision_id text NOT NULL REFERENCES enrichment.extraction_revision,
 decision_id bigint NOT NULL REFERENCES enrichment.extraction_decision,
 extraction_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.revision_link_result (
 item_id text PRIMARY KEY REFERENCES enrichment.revision_input,
 attempt_id text NOT NULL REFERENCES enrichment.attempt,
 outcome text NOT NULL CHECK(outcome IN ('matched','no_supported_match','NO_EXPLICIT_DUTIES','NO_RETRIEVAL_CANDIDATES')),
 output_hash text NOT NULL,
 actor text NOT NULL CHECK(length(btrim(actor))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.link_support (
 item_id text NOT NULL REFERENCES enrichment.revision_link_result,
 candidate_id text NOT NULL REFERENCES enrichment.link_candidate,
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 PRIMARY KEY(item_id,candidate_id)
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['revision_input','revision_link_result','link_support'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='immutable_'||name AND tgrelid=('enrichment.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON enrichment.%I FOR EACH ROW EXECUTE FUNCTION enrichment.append_only_review()',
    'immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

-- Existing candidate IDs/decisions survive. A new NCS snapshot is a new target context.
ALTER TABLE enrichment.link_candidate DROP CONSTRAINT IF EXISTS link_candidate_revision_id_competency_code_duty_index_key;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='enrichment.link_candidate'::regclass AND conname='link_candidate_revision_run_duty_key') THEN
  ALTER TABLE enrichment.link_candidate ADD CONSTRAINT link_candidate_revision_run_duty_key
   UNIQUE(revision_id,ncs_run_id,competency_code,duty_index);
 END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.revision_input_issue(id text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE binding enrichment.revision_input%ROWTYPE; r enrichment.extraction_revision%ROWTYPE;
 i enrichment.item%ROWTYPE; original enrichment.item%ROWTYPE; latest text; d enrichment.latest_extraction_decision%ROWTYPE;
BEGIN
 SELECT * INTO binding FROM enrichment.revision_input WHERE item_id=id;
 IF NOT FOUND THEN RETURN 'REVISION_INPUT_REQUIRED'; END IF;
 SELECT * INTO STRICT r FROM enrichment.extraction_revision WHERE revision_id=binding.revision_id;
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=id;
 SELECT * INTO STRICT original FROM enrichment.item WHERE item_id=r.item_id;
 IF binding.extraction_hash IS DISTINCT FROM enrichment.hash(r.extraction::text) OR
  original.posting_id IS DISTINCT FROM i.posting_id OR original.source_hash IS DISTINCT FROM i.source_hash OR
  original.source_data IS DISTINCT FROM i.source_data OR i.source_hash IS DISTINCT FROM enrichment.hash(i.source_data::text)
 THEN RETURN 'REVISION_INPUT_CHANGED'; END IF;
 SELECT x.revision_id INTO latest FROM enrichment.extraction_revision x JOIN enrichment.item xi USING(item_id)
 JOIN enrichment.batch xb USING(batch_id) WHERE xi.posting_id=i.posting_id AND xi.source_hash=i.source_hash AND xb.mode='ENRICH'
 ORDER BY x.revision_no DESC LIMIT 1;
 IF latest IS DISTINCT FROM binding.revision_id THEN RETURN 'REVISION_SUPERSEDED'; END IF;
 SELECT * INTO d FROM enrichment.latest_extraction_decision WHERE revision_id=binding.revision_id;
 IF d.decision IS DISTINCT FROM 'ACCEPT' OR d.decision_id IS DISTINCT FROM binding.decision_id
 THEN RETURN 'REVISION_ACCEPTANCE_CHANGED'; END IF;
 RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION enrichment.plan_revision_batch(id text,jobs text,ncs text,opts jsonb,revisions text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE selected text[]:=string_to_array(revisions,'|'); postings text; rid text; r enrichment.extraction_revision%ROWTYPE;
 original enrichment.item%ROWTYPE; d enrichment.latest_extraction_decision%ROWTYPE; new_item text; problem text;
BEGIN
 IF revisions IS NULL OR cardinality(selected) NOT BETWEEN 1 AND 10000 OR
  EXISTS(SELECT 1 FROM unnest(selected) v WHERE v !~ '^[0-9a-f]{64}$') OR
  cardinality(selected)<>(SELECT count(DISTINCT v) FROM unnest(selected) v)
 THEN RAISE EXCEPTION 'INVALID_REVISION_SELECTION'; END IF;
 IF opts->>'acceptance_policy' IS DISTINCT FROM 'REVIEW' OR opts->>'prompt_version' IS NULL OR opts->>'prompt_version' NOT IN ('ko-v6','ko-v7','ko-link-v1')
  OR opts ? 'repair_batch_id' OR opts ? 'posting_ids'
 THEN RAISE EXCEPTION 'REVISION_CATEGORIZATION_REQUIRES_V6_REVIEW_AND_EXACT_REVISIONS_OR_V7_REVIEW'; END IF;
 IF nullif(btrim(opts->>'actor'),'') IS NULL THEN RAISE EXCEPTION 'LINK_IMPORT_ACTOR_REQUIRED'; END IF;
 IF cardinality(selected)>(opts->>'limit')::integer THEN RAISE EXCEPTION 'REVISION_SELECTION_EXCEEDS_LIMIT'; END IF;
 SELECT string_agg(i.posting_id,'|' ORDER BY i.posting_id) INTO postings
 FROM enrichment.extraction_revision src JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
 WHERE src.revision_id=ANY(selected) AND b.mode='ENRICH';
 IF (SELECT count(*) FROM enrichment.extraction_revision src JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
  WHERE src.revision_id=ANY(selected) AND b.mode='ENRICH')<>cardinality(selected)
 THEN RAISE EXCEPTION 'UNKNOWN_OR_NONPRODUCTION_REVISION'; END IF;
 PERFORM enrichment.plan_batch(id,'ENRICH',NULL,jobs,ncs,
  opts||jsonb_build_object('posting_ids',postings,'input_kind','accepted_revision','revision_ids',revisions));
 FOREACH rid IN ARRAY selected LOOP
  SELECT * INTO STRICT r FROM enrichment.extraction_revision WHERE revision_id=rid;
  SELECT * INTO STRICT original FROM enrichment.item WHERE item_id=r.item_id;
  SELECT * INTO d FROM enrichment.latest_extraction_decision WHERE revision_id=rid;
  IF d.decision IS DISTINCT FROM 'ACCEPT' THEN RAISE EXCEPTION 'REVISION_REQUIRES_ACCEPTANCE'; END IF;
  SELECT item_id INTO STRICT new_item FROM enrichment.item WHERE batch_id=id AND posting_id=original.posting_id;
  INSERT INTO enrichment.revision_input(item_id,revision_id,decision_id,extraction_hash)
  VALUES(new_item,rid,d.decision_id,enrichment.hash(r.extraction::text));
  problem:=enrichment.revision_input_issue(new_item);
  IF problem IS NOT NULL THEN RAISE EXCEPTION '%',problem; END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION enrichment.import_revision_links(id text,who text) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE i enrichment.item%ROWTYPE; b enrichment.batch%ROWTYPE; binding enrichment.revision_input%ROWTYPE;
 a enrichment.attempt%ROWTYPE; prior enrichment.revision_link_result%ROWTYPE; problem text; link jsonb;
 candidate text; original_ncs text; n integer:=0; outcome text; fingerprint text;
BEGIN
 IF nullif(btrim(who),'') IS NULL THEN RAISE EXCEPTION 'LINK_IMPORT_ACTOR_REQUIRED'; END IF;
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=id FOR UPDATE;
 SELECT * INTO STRICT binding FROM enrichment.revision_input WHERE item_id=id;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=i.batch_id;
 SELECT * INTO STRICT a FROM enrichment.attempt WHERE attempt_id=i.categorization_id;
 PERFORM pg_advisory_xact_lock(hashtextextended('revision-link-import:'||binding.revision_id,0));
 problem:=enrichment.revision_input_issue(id);
 IF problem IS NOT NULL THEN RAISE EXCEPTION '%',problem; END IF;
 IF b.mode<>'ENRICH' OR b.settings->>'input_kind' IS DISTINCT FROM 'accepted_revision' OR a.stage<>'categorize'
  OR a.state NOT IN ('VALIDATED','SKIPPED') THEN RAISE EXCEPTION 'NO_VALIDATED_REVISION_CATEGORIZATION'; END IF;
 fingerprint:=enrichment.hash(jsonb_build_array(a.parsed_output,a.candidates)::text);
 SELECT * INTO prior FROM enrichment.revision_link_result WHERE item_id=id;
 IF FOUND THEN
  IF prior.attempt_id IS DISTINCT FROM a.attempt_id OR prior.output_hash IS DISTINCT FROM fingerprint
  THEN RAISE EXCEPTION 'LINK_RESULT_CHANGED'; END IF;
  RETURN (SELECT count(*)::integer FROM enrichment.link_support WHERE item_id=id);
 END IF;
 -- Validate again against the pinned reviewed duties even when a cache supplied the attempt.
 IF a.state='VALIDATED' AND enrichment.output_issues('categorize',a.parsed_output,i.source_data,
  (SELECT extraction FROM enrichment.extraction_revision WHERE revision_id=binding.revision_id),a.candidates,
  (b.settings->>'max_matches')::integer)<>'[]' THEN RAISE EXCEPTION 'INVALID_REVISION_LINK_OUTPUT'; END IF;
 outcome:=CASE WHEN a.state='SKIPPED' THEN a.issues->>0 ELSE a.parsed_output->>'outcome' END;
 INSERT INTO enrichment.revision_link_result(item_id,attempt_id,outcome,output_hash,actor)
 VALUES(id,a.attempt_id,outcome,fingerprint,who);
 SELECT ob.ncs_run_id INTO STRICT original_ncs FROM enrichment.extraction_revision r
 JOIN enrichment.item oi USING(item_id) JOIN enrichment.batch ob USING(batch_id) WHERE r.revision_id=binding.revision_id;
 FOR link IN SELECT jsonb_array_elements(a.parsed_output->'matches') LOOP
  SELECT candidate_id INTO candidate FROM enrichment.link_candidate c WHERE c.revision_id=binding.revision_id
   AND c.ncs_run_id=b.ncs_run_id AND c.competency_code=link->>'competency_code' AND c.duty_index=(link->>'duty_index')::integer;
  IF NOT FOUND THEN
   candidate:=enrichment.hash(CASE WHEN original_ncs=b.ncs_run_id
    THEN jsonb_build_array(binding.revision_id,link->>'competency_code',(link->>'duty_index')::integer)
    ELSE jsonb_build_array(binding.revision_id,b.ncs_run_id,link->>'competency_code',(link->>'duty_index')::integer) END::text);
   INSERT INTO enrichment.link_candidate(candidate_id,revision_id,ncs_run_id,competency_code,duty_index,reason,origin,actor)
   VALUES(candidate,binding.revision_id,b.ncs_run_id,link->>'competency_code',(link->>'duty_index')::integer,link->>'reason','model',who);
  END IF;
  -- A fresh rationale is evidence; it never overwrites or clears an earlier rejection.
  INSERT INTO enrichment.link_support(item_id,candidate_id,reason) VALUES(id,candidate,link->>'reason');
  n:=n+1;
 END LOOP;
 RETURN n;
END $$;
COMMIT;
