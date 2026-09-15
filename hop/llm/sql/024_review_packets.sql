-- Native bulk review transport; it never decides acceptance itself.
BEGIN;
CREATE TABLE IF NOT EXISTS enrichment.link_review_import (
 import_id text PRIMARY KEY, reviewer text NOT NULL, reviewer_kind text NOT NULL,
 packet jsonb NOT NULL, counts jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='enrichment.link_review_import'::regclass AND tgname='immutable_link_review_import') THEN
  CREATE TRIGGER immutable_link_review_import BEFORE UPDATE OR DELETE ON enrichment.link_review_import
  FOR EACH ROW EXECUTE FUNCTION enrichment.append_only_review();
 END IF;
END $$;
CREATE OR REPLACE FUNCTION enrichment.link_review_candidate(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('candidate_id',c.candidate_id,'revision_id',c.revision_id,
 'ncs_run_id',c.ncs_run_id,'competency_code',c.competency_code,'duty_index',c.duty_index,
 'model_reason',c.reason,'origin',c.origin,'name',n.name,'definition',n.definition,
 'occupation_name',n.occupation_name,'expected_decision_id',d.decision_id,'decision',NULL,'notes','')
 FROM enrichment.link_candidate c JOIN enrichment.ncs_catalog n ON n.run_id=c.ncs_run_id AND n.code=c.competency_code
 LEFT JOIN enrichment.latest_link_decision d USING(candidate_id) WHERE c.candidate_id=id
$$;
CREATE OR REPLACE FUNCTION enrichment.link_review_case(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('item_id',i.item_id,'posting_id',i.posting_id,'source_hash',i.source_hash,
 'revision_id',r.revision_id,'extraction_hash',enrichment.hash(r.extraction::text),
 'source_data',i.source_data,'extraction',r.extraction,'expected_extraction_decision_id',d.decision_id,
 'extraction_decision',NULL,'extraction_notes','',
 'links',coalesce((SELECT jsonb_agg(enrichment.link_review_candidate(c.candidate_id) ORDER BY c.duty_index,c.competency_code)
 FROM enrichment.link_candidate c WHERE c.revision_id=r.revision_id),'[]'))
 FROM enrichment.item i CROSS JOIN LATERAL (SELECT * FROM enrichment.extraction_revision r
 WHERE r.item_id=i.item_id ORDER BY revision_no DESC LIMIT 1) r
 LEFT JOIN enrichment.latest_extraction_decision d USING(revision_id) WHERE i.item_id=id
$$;
CREATE OR REPLACE FUNCTION enrichment.prepare_link_review(id text,postings text,cap integer,actor text) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE b enrichment.batch;item enrichment.item;rid text;ids text[];total integer;rows jsonb:='[]';omitted jsonb:='[]'; BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=id;
 IF b.mode<>'ENRICH' OR b.state NOT IN ('COMPLETE','PARTIAL','FAILED') OR nullif(btrim(actor),'') IS NULL
 OR cap IS NULL OR cap NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'TERMINAL_PRODUCTION_BATCH_AND_REVIEW_ACTOR_REQUIRED'; END IF;
 ids:=CASE WHEN coalesce(postings,'')='' THEN '{}'::text[] ELSE string_to_array(postings,'|') END;
 IF EXISTS(SELECT 1 FROM unnest(ids) p WHERE p !~ '^[0-9]+$' OR NOT EXISTS(SELECT 1 FROM enrichment.item i WHERE i.batch_id=id AND i.posting_id=p))
 THEN RAISE EXCEPTION 'UNKNOWN_REVIEW_POSTING'; END IF;
 SELECT count(*) INTO total FROM enrichment.item i WHERE i.batch_id=id AND (cardinality(ids)=0 OR i.posting_id=ANY(ids));
 IF total NOT BETWEEN 1 AND cap THEN RAISE EXCEPTION 'REVIEW_SELECTION_EXCEEDS_CAP_OR_EMPTY'; END IF;
 FOR item IN SELECT * FROM enrichment.item i WHERE i.batch_id=id AND (cardinality(ids)=0 OR i.posting_id=ANY(ids)) ORDER BY ordinal LOOP
  -- A checked correction can supersede a rejected raw model response. Capture
  -- validates revisions independently, so that revision remains reviewable.
  SELECT revision_id INTO rid FROM enrichment.extraction_revision WHERE item_id=item.item_id ORDER BY revision_no DESC LIMIT 1;
  IF rid IS NULL AND NOT EXISTS(SELECT 1 FROM enrichment.attempt WHERE attempt_id=item.extraction_id AND state='VALIDATED') THEN
   omitted:=omitted||jsonb_build_array(jsonb_build_object('posting_id',item.posting_id,'item_id',item.item_id,
    'state',(SELECT state FROM enrichment.attempt WHERE attempt_id=item.extraction_id),
    'issues',(SELECT issues FROM enrichment.attempt WHERE attempt_id=item.extraction_id)));
   CONTINUE;
  END IF;
  IF rid IS NULL THEN rid:=enrichment.capture_extraction(item.item_id,actor,'Prepare source-grounded batch review; no acceptance'); END IF;
  IF EXISTS(SELECT 1 FROM enrichment.attempt c JOIN enrichment.attempt x ON x.attempt_id=item.extraction_id
    WHERE c.attempt_id=item.categorization_id AND c.state IN ('VALIDATED','SKIPPED')
    AND x.parsed_output->'duties'=(SELECT extraction->'duties' FROM enrichment.extraction_revision WHERE revision_id=rid))
  THEN PERFORM enrichment.import_model_links(rid,actor); END IF;
  rows:=rows||jsonb_build_array(enrichment.link_review_case(item.item_id));
 END LOOP;
 RETURN jsonb_build_object('contract','ncs-link-review-v1','batch_id',id,'reviewer','',
 'reviewer_kind','human','cases',rows,'omitted',omitted);
END $$;
CREATE OR REPLACE FUNCTION enrichment.apply_link_review(packet jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE import_key text:=enrichment.hash(packet::text);who text:=packet->>'reviewer';kind text:=packet->>'reviewer_kind';
 v jsonb;l jsonb;expected jsonb;item enrichment.item;revision text;choice text;link_choice text;
 ex_count integer:=0;link_count integer:=0;answer jsonb;jobs text;ncs text; BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('link-review-import:'||import_key,0));
 IF packet->>'contract' IS DISTINCT FROM 'ncs-link-review-v1' OR nullif(btrim(who),'') IS NULL
 OR kind IS NULL OR kind NOT IN ('human','assistant','policy') OR jsonb_typeof(packet->'cases') IS DISTINCT FROM 'array'
 OR jsonb_array_length(packet->'cases') NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'INVALID_NAMED_REVIEW_PACKET'; END IF;
 SELECT counts INTO answer FROM enrichment.link_review_import WHERE import_id=import_key;
 IF FOUND THEN RETURN answer||jsonb_build_object('replayed',true,'import_id',import_key); END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(packet->'cases') c GROUP BY c->>'item_id' HAVING count(*)<>1)
 THEN RAISE EXCEPTION 'DUPLICATE_REVIEW_CASE'; END IF;
 SELECT run_id INTO jobs FROM ingestion.latest_ready_run WHERE source_id='job_alio';
 SELECT run_id INTO ncs FROM ingestion.latest_ready_run WHERE source_id='ncs_competency';
 FOR v IN SELECT jsonb_array_elements(packet->'cases') LOOP
  choice:=v->>'extraction_decision';
  IF choice IS NULL AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v->'links') c WHERE c->>'decision' IS NOT NULL) THEN CONTINUE; END IF;
  SELECT * INTO STRICT item FROM enrichment.item WHERE item_id=v->>'item_id' FOR UPDATE;
  IF NOT EXISTS(SELECT 1 FROM enrichment.batch WHERE batch_id=item.batch_id AND batch_id=packet->>'batch_id' AND mode='ENRICH')
   OR item.source_hash IS DISTINCT FROM enrichment.linking_input_hash(jobs,item.posting_id)
  THEN RAISE EXCEPTION 'REVIEW_SOURCE_IS_NOT_CURRENT'; END IF;
  PERFORM enrichment.verify_item_input(item.item_id);
  SELECT r.revision_id INTO revision FROM enrichment.extraction_revision r JOIN enrichment.item i USING(item_id)
   JOIN enrichment.batch b USING(batch_id) WHERE i.posting_id=item.posting_id AND i.source_hash=item.source_hash AND b.mode='ENRICH'
   ORDER BY r.revision_no DESC LIMIT 1;
  IF revision IS DISTINCT FROM v->>'revision_id' THEN RAISE EXCEPTION 'REVIEW_REVISION_SUPERSEDED'; END IF;
  PERFORM 1 FROM enrichment.extraction_revision WHERE revision_id=revision FOR UPDATE;
  expected:=enrichment.link_review_case(item.item_id);
  IF (v-ARRAY['extraction_decision','extraction_notes','links']) IS DISTINCT FROM
     (expected-ARRAY['extraction_decision','extraction_notes','links']) THEN RAISE EXCEPTION 'REVIEW_CONTEXT_OR_DECISION_CHANGED'; END IF;
  IF choice IS NOT NULL THEN
   IF choice NOT IN ('ACCEPT','REJECT') OR nullif(btrim(v->>'extraction_notes'),'') IS NULL THEN RAISE EXCEPTION 'EXTRACTION_DECISION_NOTES_REQUIRED'; END IF;
   PERFORM enrichment.decide_extraction(revision,choice,who,kind,v->>'extraction_notes');ex_count:=ex_count+1;
  END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(v->'links') c GROUP BY c->>'candidate_id' HAVING count(*)<>1)
  THEN RAISE EXCEPTION 'DUPLICATE_LINK_DECISION'; END IF;
  FOR l IN SELECT jsonb_array_elements(v->'links') LOOP
   link_choice:=l->>'decision';IF link_choice IS NULL THEN CONTINUE; END IF;
   IF link_choice NOT IN ('ACCEPT','REJECT') OR nullif(btrim(l->>'notes'),'') IS NULL THEN RAISE EXCEPTION 'LINK_DECISION_NOTES_REQUIRED'; END IF;
   PERFORM 1 FROM enrichment.link_candidate WHERE candidate_id=l->>'candidate_id' AND revision_id=revision AND ncs_run_id=ncs FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'CURRENT_REVISION_AND_NCS_CANDIDATE_REQUIRED'; END IF;
   IF (l-ARRAY['decision','notes']) IS DISTINCT FROM (enrichment.link_review_candidate(l->>'candidate_id')-ARRAY['decision','notes'])
   THEN RAISE EXCEPTION 'LINK_REVIEW_CONTEXT_OR_DECISION_CHANGED'; END IF;
   IF link_choice='ACCEPT' AND NOT EXISTS(SELECT 1 FROM enrichment.latest_extraction_decision WHERE revision_id=revision AND decision='ACCEPT')
   THEN RAISE EXCEPTION 'LINK_ACCEPTANCE_REQUIRES_ACCEPTED_EXTRACTION'; END IF;
   PERFORM enrichment.decide_link(l->>'candidate_id',link_choice,who,kind,l->>'notes');link_count:=link_count+1;
  END LOOP;
 END LOOP;
 IF ex_count+link_count=0 THEN RAISE EXCEPTION 'NO_EXPLICIT_REVIEW_DECISIONS'; END IF;
 answer:=jsonb_build_object('extraction_decisions',ex_count,'link_decisions',link_count);
 INSERT INTO enrichment.link_review_import VALUES(import_key,who,kind,packet,answer,clock_timestamp());
 RETURN answer||jsonb_build_object('replayed',false,'import_id',import_key);
END $$;
COMMIT;
