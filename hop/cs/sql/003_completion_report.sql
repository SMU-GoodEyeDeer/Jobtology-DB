-- Current, source-bound position and paid-work inventory. No provider calls.
BEGIN;
-- The position check starts with a pinned extraction revision/NCS snapshot;
-- keep it an indexed lookup rather than a candidate-table scan per role.
CREATE INDEX IF NOT EXISTS cs_link_candidate_revision_run_duty
 ON enrichment.link_candidate(revision_id,ncs_run_id,duty_index);
CREATE INDEX IF NOT EXISTS cs_link_decision_candidate_latest
 ON enrichment.link_decision(candidate_id,decision_id DESC);
CREATE OR REPLACE VIEW cs.accepted_role_link AS
SELECT scope.posting_identity,scope.role_id,scope.binding_hash,
 l->>'candidate_id' AS candidate_id,l->>'competency_code' AS competency_code,
 (l->>'duty_index')::integer AS duty_index,
 l->>'reason' AS reason,l->'duty' AS duty,
 l->>'reviewer_kind' AS reviewer_kind
FROM cs.current_scope scope
JOIN enrichment.linking_status state ON scope.source_id='job_alio'
 AND state.posting_id=scope.posting_id AND state.source_hash=scope.content_hash
CROSS JOIN LATERAL jsonb_array_elements(state.ncs_links) l
WHERE scope.scope_status='IN_SCOPE' AND (
 coalesce(l#>'{duty,position_ids}','[]'::jsonb) ? scope.role_id
 OR (scope.role_origin='SOURCE_TITLE' AND
     jsonb_array_length(coalesce(state.extraction->'positions','[]'::jsonb))=0)
);

CREATE OR REPLACE VIEW cs.role_completion AS
WITH scope AS MATERIALIZED (
 SELECT * FROM cs.current_scope
), current_state AS MATERIALIZED (
 SELECT posting_id,source_hash,outcome,revision_id,ncs_run_id,ncs_links,extraction
 FROM enrichment.linking_status
)
SELECT scope.policy_id,scope.source_id,scope.source_posting_id,scope.posting_id,
 scope.posting_identity,scope.snapshot_run_id,scope.title,scope.employer,
 scope.role_id,scope.role_name,scope.role_origin,scope.binding_hash,
 scope.scope_status,scope.selected_family,scope.screen_status,
 scope.extraction_state,scope.review_decision,
 coalesce(links.accepted_links,0) AS accepted_role_links,
 coalesce(links.distinct_units,0) AS distinct_role_units,
 CASE
  WHEN scope.scope_status<>'IN_SCOPE' THEN 'SCOPE_REVIEW_OR_EXCLUSION'
  WHEN scope.source_id<>'job_alio' THEN 'SOURCE_ADAPTER_ENRICHMENT_PENDING'
  WHEN coalesce(links.accepted_links,0)>0 AND coalesce(links.category_20_links,0)=0
   AND coalesce(links.other_category_links,0)>0 THEN 'PUBLISHED_DOMAIN_NCS_LINK'
  WHEN coalesce(links.accepted_links,0)>0 THEN 'PUBLISHED_NCS_LINK'
  WHEN state.outcome='EXTRACTION_REVIEW' THEN 'REVIEW_OR_CORRECT_SAVED_EXTRACTION'
  WHEN state.outcome='LINK_REVIEW' AND coalesce(pending.role_candidates,0)>0
   THEN 'REVIEW_SAVED_LINKS'
  WHEN state.outcome='LINK_REVIEW' THEN 'INVESTIGATE_ROLE_LINK_GAP'
  WHEN state.outcome='PENDING_EXTRACTION' THEN 'PREPARE_CURRENT_INPUT_AND_REUSE_CHECK'
  WHEN state.outcome='EXTRACTION_FAILED' THEN 'INSPECT_SAVED_FAILURE'
  WHEN state.outcome IN ('NO_ACCEPTED_LINKS','NO_SUPPORTED_MATCH')
   THEN 'INVESTIGATE_NCS_GAP'
  WHEN state.outcome='ACCEPTED_LINKS' THEN 'INVESTIGATE_ROLE_LINK_GAP'
  ELSE 'INSPECT_CURRENT_RESULT' END AS next_action,
 state.outcome AS linking_outcome,
 state.revision_id,
 state.source_hash,
 coalesce(pending.role_candidates,0) AS pending_role_candidates,
 coalesce(links.category_20_links,0) AS technical_role_links,
 coalesce(links.other_category_links,0) AS domain_role_links,
 coalesce(links.unclassified_links,0) AS unclassified_role_links
FROM scope
LEFT JOIN current_state state ON scope.source_id='job_alio'
 AND state.posting_id=scope.posting_id AND state.source_hash=scope.content_hash
LEFT JOIN LATERAL (
 SELECT count(*)::integer AS accepted_links,
  count(DISTINCT l->>'competency_code')::integer AS distinct_units,
  -- Category 20 is the NCS information/communication family, read from the
  -- pinned catalog rather than inferred from any posting source or title.
  count(*) FILTER (WHERE left(n.occupation_code,2)='20')::integer AS category_20_links,
  count(*) FILTER (WHERE n.occupation_code IS NOT NULL AND left(n.occupation_code,2)<>'20')::integer AS other_category_links,
  count(*) FILTER (WHERE n.occupation_code IS NULL)::integer AS unclassified_links
 FROM jsonb_array_elements(coalesce(state.ncs_links,'[]'::jsonb)) l
 LEFT JOIN enrichment.ncs_catalog n ON n.run_id=coalesce(l->>'ncs_run_id',state.ncs_run_id)
  AND n.code=l->>'competency_code'
 WHERE scope.scope_status='IN_SCOPE' AND (
   coalesce(l#>'{duty,position_ids}','[]'::jsonb) ? scope.role_id
   OR (scope.role_origin='SOURCE_TITLE' AND
       jsonb_array_length(coalesce(state.extraction->'positions','[]'::jsonb))=0)
 )
) links ON true
LEFT JOIN LATERAL (
 SELECT count(*)::integer AS role_candidates
 FROM enrichment.link_candidate c
 LEFT JOIN LATERAL (
  SELECT d.decision FROM enrichment.link_decision d
  WHERE d.candidate_id=c.candidate_id ORDER BY d.decision_id DESC LIMIT 1
 ) latest ON true
 WHERE scope.scope_status='IN_SCOPE' AND state.outcome='LINK_REVIEW'
  AND c.revision_id=state.revision_id AND c.ncs_run_id=state.ncs_run_id
  AND latest.decision IS NULL AND (
   coalesce(state.extraction->'duties'->c.duty_index->'position_ids','[]'::jsonb) ? scope.role_id
   OR (scope.role_origin='SOURCE_TITLE' AND
       jsonb_array_length(coalesce(state.extraction->'positions','[]'::jsonb))=0)
  )
) pending ON true;

CREATE OR REPLACE VIEW cs.completion_summary AS
SELECT policy_id,source_id,scope_status,next_action,count(*) AS positions,
 count(DISTINCT posting_identity) AS postings,
 sum(accepted_role_links) AS role_links,
 sum(technical_role_links) AS technical_role_links,
 sum(domain_role_links) AS domain_role_links,
 sum(pending_role_candidates) AS pending_role_candidates
FROM cs.role_completion
GROUP BY policy_id,source_id,scope_status,next_action;

-- A read-only per-position inventory for selecting exact review/repair cohorts.
CREATE OR REPLACE FUNCTION cs.assess_v1(limit_rows integer DEFAULT 1000)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE result jsonb; BEGIN
 IF limit_rows IS NULL OR limit_rows NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_ASSESS_LIMIT'; END IF;
 SELECT jsonb_build_object('policy_id','cs-it-ai-data-v1',
  'summary',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.source_id,x.scope_status,x.next_action),'[]'::jsonb)
   FROM cs.completion_summary x),
  'positions',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.source_id,x.posting_identity,x.role_id),'[]'::jsonb)
   FROM (SELECT source_id,source_posting_id,posting_identity,role_id,role_name,binding_hash,
    scope_status,screen_status,selected_family,linking_outcome,accepted_role_links,
    technical_role_links,domain_role_links,unclassified_role_links,pending_role_candidates,next_action
    FROM cs.role_completion ORDER BY source_id,posting_identity,role_id LIMIT limit_rows) x))
 INTO result;
 RETURN result;
END $$;
COMMIT;
