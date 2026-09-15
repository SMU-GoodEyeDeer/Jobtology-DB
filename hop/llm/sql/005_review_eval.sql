BEGIN;
CREATE OR REPLACE VIEW enrichment.latest_review AS
SELECT DISTINCT ON(item_id) * FROM enrichment.review ORDER BY item_id,review_id DESC;

CREATE OR REPLACE VIEW enrichment.result AS
SELECT i.*,b.mode,b.job_run_id,b.ncs_run_id,b.dataset_id,b.settings,b.created_at,
 CASE WHEN e.state='VALIDATED' THEN e.parsed_output END AS extraction,
 CASE WHEN c.state IN ('VALIDATED','SKIPPED') THEN c.parsed_output END AS categorization,c.candidates,
 e.state AS extraction_state,c.state AS categorization_state,
 e.issues AS extraction_issues,c.issues AS categorization_issues,
 e.actual_model AS extraction_model,c.actual_model AS categorization_model,
 r.decision,r.reviewer,r.review_id
FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
LEFT JOIN enrichment.attempt e ON e.attempt_id=i.extraction_id
LEFT JOIN enrichment.attempt c ON c.attempt_id=i.categorization_id
LEFT JOIN enrichment.latest_review r ON r.item_id=i.item_id;

CREATE OR REPLACE FUNCTION enrichment.review_item(id text, decision text, reviewer text, notes text DEFAULT '')
RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF decision NOT IN ('ACCEPT','REJECT') OR nullif(btrim(reviewer),'') IS NULL THEN RAISE EXCEPTION 'INVALID_REVIEW'; END IF;
 PERFORM 1 FROM enrichment.item WHERE item_id=id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_ITEM'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.revision_input WHERE item_id=id)
 THEN RAISE EXCEPTION 'REVISION_BATCH_REQUIRES_PER_LINK_REVIEW'; END IF;
 IF decision='ACCEPT' AND NOT EXISTS(SELECT 1 FROM enrichment.result WHERE item_id=id AND state='VALIDATED' AND mode='ENRICH')
 THEN RAISE EXCEPTION 'ONLY_VALIDATED_ENRICH_ITEMS_CAN_BE_ACCEPTED'; END IF;
 INSERT INTO enrichment.review(item_id,decision,reviewer,notes) VALUES(id,decision,reviewer,coalesce(notes,''));
END $$;

-- Source fields remain authoritative. Derived data is a separate column and must match
-- BOTH current posting content and the pinned, current NCS snapshot.
CREATE OR REPLACE VIEW enrichment.current_posting AS
SELECT p.*,e.item_id AS enrichment_id,e.extraction,e.categorization,e.settings AS enrichment_settings
FROM ingestion.job_posting p JOIN ingestion.latest_ready_run j ON j.run_id=p.run_id AND j.source_id='job_alio'
LEFT JOIN LATERAL (
 SELECT r.* FROM enrichment.result r WHERE r.posting_id=p.posting_id AND r.mode='ENRICH'
 AND r.state='VALIDATED' AND r.decision='ACCEPT'
 AND r.source_hash=enrichment.hash(enrichment.source_fields(p.normalized)::text)
 AND r.ncs_run_id=(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency')
 ORDER BY r.review_id DESC LIMIT 1
) e ON true;

CREATE OR REPLACE FUNCTION enrichment.set_gold(dataset text, posting text, labels jsonb, reviewer text)
RETURNS void LANGUAGE plpgsql AS $$ DECLARE src jsonb; ncs text; x jsonb; k text; BEGIN
 SELECT c.source_data,d.ncs_run_id INTO STRICT src,ncs FROM enrichment.test_case c JOIN enrichment.dataset d USING(dataset_id)
 WHERE c.dataset_id=dataset AND c.posting_id=posting;
 IF nullif(btrim(reviewer),'') IS NULL OR jsonb_typeof(labels)<>'object' OR
 NOT labels ?& ARRAY['requirements','duties','ncs_codes','requirements_complete','duties_complete','ncs_complete'] OR
 EXISTS(SELECT 1 FROM jsonb_object_keys(labels) keys(key) WHERE keys.key NOT IN
 ('requirements','duties','ncs_codes','requirements_complete','duties_complete','ncs_complete'))
 THEN RAISE EXCEPTION 'INVALID_GOLD_LABELS'; END IF;
 FOREACH k IN ARRAY ARRAY['requirements_complete','duties_complete','ncs_complete'] LOOP
  IF jsonb_typeof(labels->k)<>'boolean' THEN RAISE EXCEPTION 'GOLD_COMPLETENESS_MUST_BE_BOOLEAN'; END IF;
 END LOOP;
 FOREACH k IN ARRAY ARRAY['requirements','duties','ncs_codes'] LOOP
  IF jsonb_typeof(labels->k)<>'array' THEN RAISE EXCEPTION 'GOLD_LABELS_MUST_BE_ARRAYS'; END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(labels->k)) <>
     (SELECT count(DISTINCT value) FROM jsonb_array_elements(labels->k))
  THEN RAISE EXCEPTION 'DUPLICATE_GOLD_LABEL'; END IF;
 END LOOP;
 IF labels->>'requirements_complete'='false' AND labels->>'duties_complete'='false' AND labels->>'ncs_complete'='false'
 AND jsonb_array_length(labels->'requirements')+jsonb_array_length(labels->'duties')+jsonb_array_length(labels->'ncs_codes')=0
 THEN RAISE EXCEPTION 'GOLD_LABELS_HAVE_NO_ASSERTIONS'; END IF;
 FOR x IN SELECT v FROM jsonb_array_elements(labels->'requirements') v UNION ALL SELECT v FROM jsonb_array_elements(labels->'duties') v LOOP
  IF jsonb_typeof(x)<>'object' OR nullif(x->>'field','') IS NULL OR length(btrim(coalesce(x->>'quote','')))<2 OR
    coalesce(position(x->>'quote' in src->>(x->>'field')),0)=0
  THEN RAISE EXCEPTION 'GOLD_EVIDENCE_NOT_IN_SOURCE'; END IF;
 END LOOP;
 FOR x IN SELECT jsonb_array_elements(labels->'requirements') LOOP
  IF NOT x ?& ARRAY['field','quote','category','importance','logic'] OR
   x->>'category' NOT IN ('education','experience','qualification','skill','other') OR
   x->>'importance' NOT IN ('required','preferred','unspecified','excluded','unrestricted') OR
   x->>'logic' NOT IN ('single','all_of','any_of','unspecified','conditional') OR
   (x ? 'kind' AND x->>'kind' NOT IN ('eligibility','preference','exclusion','unrestricted')) OR
   (x ? 'check_logic' AND jsonb_typeof(x->'check_logic')<>'boolean')
  THEN RAISE EXCEPTION 'INVALID_GOLD_REQUIREMENT'; END IF;
 END LOOP;
 FOR x IN SELECT jsonb_array_elements(labels->'ncs_codes') LOOP
  IF jsonb_typeof(x)<>'string' OR NOT EXISTS(SELECT 1 FROM ingestion.competency WHERE run_id=ncs AND code=x#>>'{}')
  THEN RAISE EXCEPTION 'GOLD_NCS_CODE_NOT_IN_PINNED_CATALOG'; END IF;
 END LOOP;
 INSERT INTO enrichment.gold(dataset_id,posting_id,labels,reviewer) VALUES(dataset,posting,labels,reviewer);
END $$;

-- A gold quote may be contained in a longer evidence quote. Labels check meaningful
-- conditions (including AND/OR and required/preferred), not identical model wording.
CREATE OR REPLACE FUNCTION enrichment.label_matches(pred jsonb, gold jsonb, section text)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(pred#>>'{evidence,field}'=gold->>'field'
 AND position(gold->>'quote' in pred#>>'{evidence,quote}')>0
 AND (section='duties' OR (pred->>'category'=gold->>'category' AND pred->>'importance'=gold->>'importance'
  AND (gold->>'check_logic'='false' OR pred->>'logic'=gold->>'logic')))
 AND (NOT gold ? 'position' OR pred->'position'=gold->'position')
 AND (NOT gold ? 'kind' OR pred->'kind'=gold->'kind')
 AND (NOT gold ? 'position_names' OR ((pred->'position_names') @> (gold->'position_names') AND (gold->'position_names') @> (pred->'position_names')))
 -- For v2, quoting a broad passage alone cannot claim a label the extracted text omits.
 AND (NOT pred ? 'evidence_ids' OR position(
  btrim(regexp_replace(gold->>'quote','[[:space:]]+',' ','g')) in
  btrim(regexp_replace(pred->>'text','[[:space:]]+',' ','g')))>0),false)
$$;
CREATE OR REPLACE VIEW enrichment.case_score AS
SELECT r.batch_id,r.item_id,r.posting_id,r.gold_id,r.state,r.extraction_state,r.categorization_state,
 (r.gold_id IS NOT NULL) AS has_gold,
 (g.labels->>'requirements_complete')::boolean AS requirements_complete,
 (g.labels->>'duties_complete')::boolean AS duties_complete,
 (g.labels->>'ncs_complete')::boolean AS ncs_complete,
 (SELECT count(*) FROM jsonb_array_elements(g.labels->'requirements') x) AS required_labels,
 (SELECT count(*) FROM jsonb_array_elements(g.labels->'requirements') x WHERE EXISTS(
   SELECT 1 FROM jsonb_array_elements(r.extraction->'requirements') p WHERE enrichment.label_matches(p,x,'requirements'))) AS requirements_found,
 (SELECT count(*) FROM jsonb_array_elements(r.extraction->'requirements') p) AS requirements_proposed,
 (SELECT count(*) FROM jsonb_array_elements(r.extraction->'requirements') p WHERE EXISTS(
   SELECT 1 FROM jsonb_array_elements(g.labels->'requirements') x WHERE enrichment.label_matches(p,x,'requirements'))) AS requirements_supported,
 (SELECT count(*) FROM jsonb_array_elements(g.labels->'duties') x) AS duty_labels,
 (SELECT count(*) FROM jsonb_array_elements(g.labels->'duties') x WHERE EXISTS(
   SELECT 1 FROM jsonb_array_elements(r.extraction->'duties') p WHERE enrichment.label_matches(p,x,'duties'))) AS duties_found,
 (SELECT count(*) FROM jsonb_array_elements(r.extraction->'duties')) AS duties_proposed,
 (SELECT count(*) FROM jsonb_array_elements(r.extraction->'duties') p WHERE EXISTS(
   SELECT 1 FROM jsonb_array_elements(g.labels->'duties') x WHERE enrichment.label_matches(p,x,'duties'))) AS duties_supported,
 (SELECT count(DISTINCT x) FROM jsonb_array_elements_text(g.labels->'ncs_codes') x) AS ncs_labels,
 (SELECT count(DISTINCT x) FROM jsonb_array_elements_text(g.labels->'ncs_codes') x WHERE EXISTS(
   SELECT 1 FROM jsonb_array_elements(r.categorization->'matches') p WHERE p->>'competency_code'=x)) AS ncs_found,
 (SELECT count(DISTINCT p->>'competency_code') FROM jsonb_array_elements(r.categorization->'matches') p) AS ncs_proposed,
 (SELECT count(DISTINCT x) FROM jsonb_array_elements_text(g.labels->'ncs_codes') x WHERE EXISTS(
   SELECT 1 FROM jsonb_array_elements(r.candidates) c WHERE c->>'code'=x)) AS ncs_retrieved
FROM enrichment.result r LEFT JOIN enrichment.gold g USING(gold_id) WHERE r.mode='EVAL';

CREATE OR REPLACE VIEW enrichment.batch_report AS
WITH items AS (
 SELECT batch_id,count(*) AS postings,count(*) FILTER(WHERE state='VALIDATED') AS validated,
  count(*) FILTER(WHERE issue IS NOT NULL) AS rejected,
  count(*) FILTER(WHERE extraction_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM enrichment.attempt a WHERE a.attempt_id=i.extraction_id AND a.batch_id=i.batch_id)) AS extraction_cache_hits,
  count(*) FILTER(WHERE categorization_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM enrichment.attempt a WHERE a.attempt_id=i.categorization_id AND a.batch_id=i.batch_id)) AS categorization_cache_hits
 FROM enrichment.item i GROUP BY batch_id
), costs AS (
 SELECT batch_id,count(*) FILTER(WHERE reserved_at IS NOT NULL) AS requests,
  count(*) FILTER(WHERE reserved_at IS NOT NULL AND cost_usd IS NULL) AS unknown_cost_requests,
  sum(cost_usd) AS reported_cost_usd,sum(enrichment.accounted_cost(state,cost_usd,reserved_usd)) AS budget_accounted_usd,
  sum(prompt_tokens) AS prompt_tokens,sum(completion_tokens) AS completion_tokens
 FROM enrichment.attempt GROUP BY batch_id
), scores AS (
 SELECT batch_id,count(*) FILTER(WHERE has_gold) AS labeled_postings,
  sum(requirements_found)::numeric/nullif(sum(required_labels),0) AS requirement_recall,
  sum(requirements_supported) FILTER(WHERE requirements_complete)::numeric/nullif(sum(requirements_proposed) FILTER(WHERE requirements_complete),0) AS requirement_precision,
  sum(duties_found)::numeric/nullif(sum(duty_labels),0) AS duty_recall,
  sum(duties_supported) FILTER(WHERE duties_complete)::numeric/nullif(sum(duties_proposed) FILTER(WHERE duties_complete),0) AS duty_precision,
  sum(ncs_found)::numeric/nullif(sum(ncs_labels),0) AS ncs_recall,
  sum(ncs_found) FILTER(WHERE ncs_complete)::numeric/nullif(sum(ncs_proposed) FILTER(WHERE ncs_complete),0) AS ncs_precision,
  sum(ncs_retrieved)::numeric/nullif(sum(ncs_labels),0) AS retrieval_recall,
  count(*) FILTER(WHERE ncs_complete AND ncs_labels=0) AS no_match_cases,
  count(*) FILTER(WHERE ncs_complete AND ncs_labels=0 AND ncs_proposed=0 AND state='VALIDATED') AS correct_abstentions
 FROM enrichment.case_score GROUP BY batch_id
)
SELECT b.*,i.postings,i.validated,i.rejected,i.extraction_cache_hits,i.categorization_cache_hits,
 coalesce(c.requests,0) AS requests,c.unknown_cost_requests,c.reported_cost_usd,c.budget_accounted_usd,c.prompt_tokens,c.completion_tokens,
 s.labeled_postings,s.requirement_recall,s.requirement_precision,s.duty_recall,s.duty_precision,
 s.ncs_recall,s.ncs_precision,s.retrieval_recall,s.no_match_cases,s.correct_abstentions
FROM enrichment.batch b JOIN items i USING(batch_id) LEFT JOIN costs c USING(batch_id) LEFT JOIN scores s USING(batch_id);
COMMIT;
