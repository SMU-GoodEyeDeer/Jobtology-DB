-- Additive derived-status correction only; inference inputs and history stay unchanged.
BEGIN;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_status(jobs text,ncs text)
RETURNS TABLE(posting_id text,item_id text,result_id text,outcome text,decision text,matches jsonb)
LANGUAGE sql STABLE AS $$
 SELECT b.posting_id,b.item_id,r.result_id,
  CASE WHEN r.result_id IS NULL THEN
    CASE WHEN a.completed_at IS NOT NULL AND a.state='REJECTED' THEN 'VALIDATION_FAILED'
     WHEN a.completed_at IS NOT NULL AND a.state='ERROR' THEN 'REQUEST_FAILED'
     ELSE 'PENDING' END
   WHEN d.decision='REJECT' THEN 'REJECTED'
   WHEN r.output->>'outcome'='abstained' THEN 'ABSTAINED'
   WHEN d.decision IS NULL THEN 'REVIEW_PENDING' ELSE 'ACCEPTED_INFERRED_OCCUPATION' END,
  d.decision,coalesce(r.output->'matches','[]'::jsonb)
 FROM (SELECT DISTINCT ON(i.posting_id) i.posting_id,x.item_id,i.categorization_id FROM enrichment.metadata_occupation_binding x
  JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
  WHERE x.job_run_id=jobs AND x.ncs_run_id=ncs ORDER BY i.posting_id,b.created_at DESC,i.item_id DESC) b
 LEFT JOIN enrichment.metadata_occupation_result r USING(item_id)
 -- Follow the selected item's current pointer, including reused attempts. Older
 -- failures cannot override a newer item's unsent or running categorization.
 LEFT JOIN enrichment.attempt a ON a.attempt_id=b.categorization_id AND a.stage='categorize'
 LEFT JOIN LATERAL (SELECT d.* FROM enrichment.metadata_occupation_decision d WHERE d.result_id=r.result_id
  ORDER BY decision_id DESC LIMIT 1) d ON true
$$;
COMMIT;
