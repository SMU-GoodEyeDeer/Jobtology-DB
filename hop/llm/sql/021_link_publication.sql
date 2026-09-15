-- Practical ingestion/linking projection. No product-ontology release prerequisite.
BEGIN;
-- The generic job_posting view materializes all snapshots for broad graph
-- queries. A single posting lookup can use the exact accepted list/detail IDs.
CREATE OR REPLACE FUNCTION enrichment.inline_posting_source(jobs text,posting text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$ DECLARE value jsonb; BEGIN
 SELECT enrichment.source_fields((l.normalized||jsonb_strip_nulls(d.normalized))-'representation') INTO STRICT value
 FROM ingestion.ready_record l JOIN ingestion.ready_record d ON d.run_id=l.run_id
 WHERE l.run_id=jobs AND l.source_id='job_alio' AND d.source_id='job_alio'
 AND l.source_record_id=posting||':list' AND d.source_record_id=posting||':detail'
 AND l.normalized->>'posting_id'=posting AND d.normalized->>'posting_id'=posting;
 RETURN value;
END $$;
CREATE OR REPLACE FUNCTION enrichment.linking_input_hash(jobs text,posting text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE inline_hash text; current_files jsonb; chosen text; BEGIN
 inline_hash:=enrichment.hash(enrichment.inline_posting_source(jobs,posting)::text);
 SELECT source_payload->'files' INTO current_files FROM ingestion.ready_record
 WHERE run_id=jobs AND source_record_id=posting||':detail';
 -- Identical content can reuse a reviewed parse across daily source snapshots.
 -- A new prepared document input supersedes inline-only or older parser inputs.
 IF to_regclass('attachment.posting') IS NOT NULL THEN
  SELECT b.source_hash INTO chosen FROM enrichment.input_bundle b
  WHERE b.posting_id=posting AND b.manifest->>'inline_hash'=inline_hash
  AND EXISTS(SELECT 1 FROM attachment.posting a WHERE a.posting_id=posting
    AND a.batch_id IN (SELECT jsonb_array_elements_text(b.manifest->'attachment_batch_ids')) AND a.files=current_files)
  ORDER BY b.created_at DESC,b.bundle_id DESC LIMIT 1;
 END IF;
 RETURN coalesce(chosen,inline_hash);
END $$;

CREATE OR REPLACE VIEW enrichment.linking_status AS
SELECT p.run_id AS job_run_id,p.posting_id,p.normalized->>'title' AS title,
 n.run_id AS ncs_run_id,h.source_hash,r.revision_id,r.item_id,r.decision,r.decision_id,
 CASE WHEN r.decision='ACCEPT' THEN r.extraction END AS extraction,
 coalesce(links.matches,'[]'::jsonb) AS ncs_links,
 CASE WHEN r.revision_id IS NULL THEN
   CASE WHEN a.state IN ('REJECTED','ERROR','BUDGET_BLOCKED') THEN 'EXTRACTION_FAILED'
        WHEN a.state='VALIDATED' THEN 'EXTRACTION_REVIEW' ELSE 'PENDING_EXTRACTION' END
  WHEN r.decision IS DISTINCT FROM 'ACCEPT' THEN 'EXTRACTION_REVIEW'
  WHEN r.extraction->>'duties_status'='attachment_required' THEN 'ATTACHMENT_TEXT_MISSING'
  WHEN jsonb_array_length(coalesce(r.extraction->'duties','[]'))=0 THEN 'NO_EXPLICIT_DUTIES'
  WHEN jsonb_array_length(coalesce(links.matches,'[]'))>0 THEN 'ACCEPTED_LINKS'
  WHEN EXISTS(SELECT 1 FROM enrichment.link_candidate c LEFT JOIN enrichment.latest_link_decision d USING(candidate_id)
    WHERE c.revision_id=r.revision_id AND c.ncs_run_id=n.run_id AND d.decision IS NULL)
    THEN 'LINK_REVIEW'
  WHEN EXISTS(SELECT 1 FROM enrichment.link_candidate c WHERE c.revision_id=r.revision_id AND c.ncs_run_id=n.run_id)
    THEN 'NO_ACCEPTED_LINKS'
  WHEN EXISTS(SELECT 1 FROM enrichment.revision_link_result lr JOIN enrichment.revision_input ri USING(item_id)
    JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
    WHERE ri.revision_id=r.revision_id AND b.ncs_run_id=n.run_id AND lr.outcome IN ('no_supported_match','NO_RETRIEVAL_CANDIDATES'))
    THEN 'NO_SUPPORTED_MATCH'
  WHEN EXISTS(SELECT 1 FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
    JOIN enrichment.attempt x ON x.attempt_id=i.extraction_id
    JOIN enrichment.attempt c ON c.attempt_id=i.categorization_id
    WHERE i.item_id=r.item_id AND b.ncs_run_id=n.run_id AND c.state IN ('VALIDATED','SKIPPED')
    AND x.parsed_output->'duties'=r.extraction->'duties'
    AND (c.parsed_output->>'outcome'='no_supported_match' OR c.issues->>0='NO_RETRIEVAL_CANDIDATES'))
    THEN 'NO_SUPPORTED_MATCH'
  ELSE 'PENDING_CATEGORIZATION' END AS outcome
FROM ingestion.job_posting p JOIN ingestion.latest_ready_run j ON j.run_id=p.run_id AND j.source_id='job_alio'
CROSS JOIN (SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency') n
CROSS JOIN LATERAL (SELECT enrichment.linking_input_hash(p.run_id,p.posting_id) AS source_hash) h
LEFT JOIN LATERAL (
 SELECT s.* FROM enrichment.extraction_review_state s JOIN enrichment.item i USING(item_id)
 JOIN enrichment.batch b USING(batch_id) WHERE i.posting_id=p.posting_id AND i.source_hash=h.source_hash AND b.mode='ENRICH'
 ORDER BY s.revision_no DESC LIMIT 1
) r ON true
LEFT JOIN LATERAL (
 SELECT a.state FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
 JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id
 WHERE i.posting_id=p.posting_id AND i.source_hash=h.source_hash AND b.mode='ENRICH'
 ORDER BY b.created_at DESC,i.item_id DESC LIMIT 1
) a ON true
LEFT JOIN LATERAL (
 SELECT jsonb_agg(jsonb_build_object('candidate_id',c.candidate_id,'competency_code',c.competency_code,
  'ncs_run_id',c.ncs_run_id,'duty_index',c.duty_index,'reason',c.reason,
  'duty',r.extraction->'duties'->c.duty_index,'decision_id',d.decision_id,
  'reviewer_kind',d.reviewer_kind,'reviewer',d.reviewer,'review_notes',d.notes) ORDER BY c.candidate_id) AS matches
 FROM enrichment.link_candidate c JOIN enrichment.latest_link_decision d USING(candidate_id)
 WHERE c.revision_id=r.revision_id AND r.decision='ACCEPT' AND d.decision='ACCEPT' AND c.ncs_run_id=n.run_id
) links ON true;

CREATE OR REPLACE VIEW enrichment.link_publication_source AS
SELECT s.posting_id,'reviewed:'||s.revision_id AS enrichment_id,'job-alio:posting:'||s.posting_id AS posting_identity,
 s.title AS name,s.revision_id,s.item_id,s.ncs_links,
 jsonb_build_object('posting_id',s.posting_id,'name',s.title,'revision_id',s.revision_id,'item_id',s.item_id,
  'job_run_id',s.job_run_id,'ncs_run_id',s.ncs_run_id,'source_hash',s.source_hash,
  'extraction',s.extraction,'extraction_decision_id',s.decision_id,'extraction_reviewer',d.reviewer,
  'extraction_reviewer_kind',d.reviewer_kind,'prompt_version',b.settings->>'prompt_version',
  'extraction_model',coalesce(a.actual_model,b.settings->>'extract_model'),'links',s.ncs_links) AS payload
FROM enrichment.linking_status s JOIN enrichment.latest_extraction_decision d ON d.decision_id=s.decision_id
JOIN enrichment.item i ON i.item_id=s.item_id JOIN enrichment.batch b USING(batch_id)
LEFT JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id
WHERE s.decision='ACCEPT';

CREATE TABLE IF NOT EXISTS enrichment.link_publication (
 publication_id text PRIMARY KEY, source_hash text NOT NULL, job_run_id text NOT NULL REFERENCES ingestion.run,
 ncs_run_id text NOT NULL REFERENCES ingestion.run, state text NOT NULL CHECK(state IN ('PREPARED','READY','FAILED')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),completed_at timestamptz
);
CREATE TABLE IF NOT EXISTS enrichment.link_publication_item (
 publication_id text NOT NULL REFERENCES enrichment.link_publication,
 posting_id text NOT NULL,enrichment_id text NOT NULL,posting_identity text NOT NULL,
 name text,payload jsonb NOT NULL,payload_hash text NOT NULL,
 PRIMARY KEY(publication_id,posting_id)
);
-- Upgrade the installed retention function without replacing other modules'
-- optional pin checks. The base retention installer contains the same check.
DO $upgrade$
DECLARE definition text; marker text:=' IF NOT EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=id)';
BEGIN
 IF to_regprocedure('retention.protection(text,integer)') IS NULL THEN RETURN; END IF;
 SELECT pg_get_functiondef('retention.protection(text,integer)'::regprocedure) INTO definition;
 IF position('REVIEWED_LINK_PUBLICATION' IN definition)=0 THEN
  IF position(marker IN definition)=0 THEN RAISE EXCEPTION 'RETENTION_PROTECTION_UPGRADE_REQUIRES_REVIEW'; END IF;
  definition:=replace(definition,marker,$branch$
 IF to_regclass('enrichment.link_publication') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM enrichment.link_publication WHERE job_run_id=$1 OR ncs_run_id=$1)' INTO ontology_pinned USING id;
  IF ontology_pinned THEN RETURN 'REVIEWED_LINK_PUBLICATION'; END IF;
 END IF;
$branch$||marker);
  EXECUTE definition;
 END IF;
END $upgrade$;
CREATE OR REPLACE FUNCTION enrichment.link_source_hash() RETURNS text LANGUAGE sql STABLE AS $$
 SELECT enrichment.hash(jsonb_build_object(
  'jobs',(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='job_alio'),
  'ncs',(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency'),
  'rows',(SELECT coalesce(jsonb_agg(payload ORDER BY posting_id),'[]') FROM enrichment.link_publication_source))::text)
$$;
CREATE OR REPLACE FUNCTION enrichment.prepare_link_publication(id text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE h text:=enrichment.link_source_hash();existing text; BEGIN
 PERFORM retention.gate();
 IF nullif(id,'') IS NULL THEN id:=gen_random_uuid()::text; END IF;
 IF id !~ '^[A-Za-z0-9_-]{1,100}$' THEN RAISE EXCEPTION 'INVALID_PUBLICATION_ID'; END IF;
 SELECT source_hash INTO existing FROM enrichment.link_publication WHERE publication_id=id;
 IF FOUND THEN
  IF existing<>h THEN RAISE EXCEPTION 'PUBLICATION_INPUT_CHANGED_USE_NEW_ID'; END IF;
 ELSE
  INSERT INTO enrichment.link_publication(publication_id,source_hash,job_run_id,ncs_run_id,state)
  SELECT id,h,j.run_id,n.run_id,'PREPARED' FROM ingestion.latest_ready_run j CROSS JOIN ingestion.latest_ready_run n
  WHERE j.source_id='job_alio' AND n.source_id='ncs_competency';
  IF NOT FOUND THEN RAISE EXCEPTION 'CURRENT_SOURCE_SNAPSHOTS_REQUIRED'; END IF;
  INSERT INTO enrichment.link_publication_item
  SELECT id,posting_id,enrichment_id,posting_identity,name,payload,enrichment.hash(payload::text) FROM enrichment.link_publication_source;
 END IF;
 -- Single writer across all independent-link publications, also fenced by retention.
 PERFORM retention.enter_writer('reviewed-ncs-publication','LLM_GRAPH',id);
 UPDATE enrichment.link_publication SET state='PREPARED',completed_at=NULL WHERE publication_id=id;
 RETURN id;
END $$;
CREATE OR REPLACE FUNCTION enrichment.check_link_publication(id text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM enrichment.link_publication WHERE publication_id=id AND source_hash=enrichment.link_source_hash())
 THEN RAISE EXCEPTION 'SOURCE_OR_REVIEW_CHANGED_DURING_PUBLICATION'; END IF;
 IF NOT EXISTS(SELECT 1 FROM enrichment.link_publication p WHERE publication_id=id AND source_hash=
 enrichment.hash(jsonb_build_object('jobs',p.job_run_id,'ncs',p.ncs_run_id,'rows',
 (SELECT coalesce(jsonb_agg(payload ORDER BY posting_id),'[]') FROM enrichment.link_publication_item WHERE publication_id=id))::text))
 THEN RAISE EXCEPTION 'PUBLICATION_MEMBERSHIP_CHANGED'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.link_publication_item WHERE publication_id=id AND payload_hash<>enrichment.hash(payload::text))
 THEN RAISE EXCEPTION 'PUBLICATION_PAYLOAD_CHANGED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION enrichment.finish_link_publication(id text,success boolean) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF success THEN PERFORM enrichment.check_link_publication(id); END IF;
 UPDATE enrichment.link_publication SET state=CASE WHEN success THEN 'READY' ELSE 'FAILED' END,
 completed_at=clock_timestamp() WHERE publication_id=id;
 DELETE FROM retention.writer WHERE writer_id='reviewed-ncs-publication' AND target_id=id;
END $$;
COMMIT;
