-- Apply after 027 and replayed canonical 003/005/013/017/021 on upgrades.
-- This adds bounded local preparation only: no HTTP, model calls or publication.
BEGIN;

CREATE OR REPLACE FUNCTION enrichment.jobkorea_pilot_scope(source jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 WITH hints AS (
  SELECT field FROM (VALUES
   ('title',source->>'title'),('role',source->>'role'),
   ('job_functions',source->>'job_functions'),('description_text',source->>'description_text')
  ) fields(field,value)
  WHERE lower(coalesce(value,'')) ~
   '(소프트웨어|프로그래밍|프로그래머|웹[[:space:]]*개발|앱[[:space:]]*개발|개발자|프론트.?엔드|백.?엔드|풀스택|데이터|정보[[:space:]]*보안|시스템[[:space:]]*엔지니어|클라우드|인공지능|머신러닝|딥러닝|정보[[:space:]]*통신|(^|[^a-z])(it|ict|ai|dba|sql|devops|software|python|java|backend|frontend|developer|programmer|database|data|cloud)([^a-z]|$))'
 ) SELECT jsonb_build_object('status',CASE WHEN EXISTS(SELECT 1 FROM hints) THEN 'CANDIDATE' ELSE 'UNKNOWN' END,
  'basis','LEXICAL_SCREEN_ONLY','verified_scope',false,
  'evidence_fields',coalesce((SELECT jsonb_agg(field ORDER BY field) FROM hints),'[]'::jsonb))
$$;

CREATE OR REPLACE FUNCTION enrichment.jobkorea_linking_preview(
 jobs text,ncs text,cap integer DEFAULT 5)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE j text; n text; answer jsonb; BEGIN
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 25 THEN RAISE EXCEPTION 'JOBKOREA_PILOT_CAP_MUST_BE_1_TO_25'; END IF;
 j:=enrichment.resolve_snapshot(jobs,'jobkorea');
 n:=enrichment.resolve_snapshot(ncs,'ncs_competency');
 IF NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=j)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=n)
 THEN RAISE EXCEPTION 'JOBKOREA_PILOT_REQUIRES_CURRENT_READY_SOURCES'; END IF;
 WITH scoped AS MATERIALIZED (
  SELECT p.posting_id,p.normalized,enrichment.jobkorea_pilot_scope(p.normalized) AS scope
  FROM ingestion.llm_posting p WHERE p.run_id=j AND p.source_id='jobkorea'
 ), pending AS MATERIALIZED (
  SELECT p.*,s.source_hash,s.outcome FROM scoped p JOIN enrichment.linking_status s
   ON s.job_run_id=j AND s.posting_id=p.posting_id AND s.ncs_run_id=n
  WHERE p.scope->>'status'='CANDIDATE' AND s.outcome IN('INPUT_NOT_PREPARED','PENDING_EXTRACTION')
   AND p.normalized->>'source_status' IS DISTINCT FROM 'CLOSED'
 ), selected AS MATERIALIZED (
  SELECT * FROM pending ORDER BY
   CASE WHEN normalized->>'content_status'='TEXT_AVAILABLE' THEN 0 ELSE 1 END,posting_id LIMIT cap
 ), rows AS MATERIALIZED (
  SELECT s.*,b.bundle_id FROM selected s LEFT JOIN LATERAL (
   SELECT b.bundle_id FROM enrichment.input_bundle b WHERE b.job_run_id=j AND b.posting_id=s.posting_id
    AND b.source_hash=s.source_hash AND b.source_data#>>'{_input,contract}'='jobkorea-input-v1'
   ORDER BY b.created_at DESC,b.bundle_id DESC LIMIT 1
  ) b ON true
 ) SELECT jsonb_build_object('job_run_id',j,'ncs_run_id',n,'input_contract','jobkorea-input-v1',
  'pilot_scope','IT_SOFTWARE_DATA','scope_basis','LEXICAL_SCREEN_ONLY','verified_scope',false,
  'source_count',(SELECT count(*) FROM scoped),
  'source_graph_ready',EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=j),
  'candidate_count',(SELECT count(*) FROM scoped WHERE scope->>'status'='CANDIDATE'),
  'unknown_count',(SELECT count(*) FROM scoped WHERE scope->>'status'='UNKNOWN'),
  'pending_candidate_count',(SELECT count(*) FROM pending),'selected_count',(SELECT count(*) FROM rows),
  'selected',(SELECT count(*) FROM rows),'pilot_cap',cap,
  'content_missing_count',(SELECT count(*) FROM scoped WHERE normalized->>'content_status'='MISSING'),
  'selected_content_missing_count',(SELECT count(*) FROM rows WHERE normalized->>'content_status'='MISSING'),
  'posting_ids',coalesce((SELECT string_agg(posting_id,'|' ORDER BY posting_id) FROM rows),''),
  'bundle_ids',coalesce((SELECT string_agg(bundle_id,'|' ORDER BY posting_id) FROM rows),''),
  'prepared_count',(SELECT count(*) FROM rows WHERE bundle_id IS NOT NULL),
  'run_needed',CASE WHEN EXISTS(SELECT 1 FROM rows) THEN 'Y' ELSE 'N' END,
  'readiness',CASE WHEN NOT EXISTS(SELECT 1 FROM rows) THEN 'NO_PENDING_PILOT_INPUTS'
   WHEN EXISTS(SELECT 1 FROM rows WHERE bundle_id IS NULL) THEN 'INPUT_PREPARATION_REQUIRED'
   ELSE 'READY_FOR_DRY_REQUEST_PLAN' END,
  'rows',coalesce((SELECT jsonb_agg(jsonb_build_object('posting_id',posting_id,'scope',scope,
   'content_status',normalized->>'content_status','linking_outcome',outcome,
   'input_prepared',bundle_id IS NOT NULL) ORDER BY posting_id) FROM rows),'[]'::jsonb)) INTO answer;
 RETURN answer;
END $$;

CREATE OR REPLACE FUNCTION enrichment.prepare_jobkorea_linking_pilot(
 jobs text,ncs text,cap integer DEFAULT 5)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE preview jsonb; id text; BEGIN
 PERFORM retention.gate();
 preview:=enrichment.jobkorea_linking_preview(jobs,ncs,cap);
 IF preview->>'run_needed'='N' THEN RETURN preview; END IF;
 FOREACH id IN ARRAY string_to_array(preview->>'posting_ids','|') LOOP
  PERFORM enrichment.prepare_jobkorea_input_bundle(preview->>'job_run_id',id);
 END LOOP;
 RETURN enrichment.jobkorea_linking_preview(preview->>'job_run_id',preview->>'ncs_run_id',cap);
END $$;

-- Keep the existing reviewed consumer's legacy inline hash behavior; JobKorea
-- revisions bind its verified local metadata/narrative bundle instead.
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
 WHERE i.posting_id=p.posting_id AND i.source_hash=CASE WHEN p.source_id='jobkorea'
  THEN enrichment.linking_input_hash(p.run_id,p.posting_id)
  ELSE enrichment.hash(enrichment.source_fields(p.normalized)::text) END
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

-- Upgrade an already installed optional CS bridge without touching legacy
-- source branches or normalized inline_source_hash values. Source/CS installer
-- replay carries the same dispatcher and cannot silently revert this hash.
DO $cs_link_hash$
DECLARE definition text; marker text:='enrichment.hash(cs.jobkorea_source_fields(r.normalized)::text) AS content_hash';
BEGIN
 IF to_regclass('cs.common_posting') IS NULL OR
  to_regprocedure('cs.jobkorea_source_fields(jsonb)') IS NULL THEN RETURN; END IF;
 EXECUTE $content_hash$
CREATE OR REPLACE FUNCTION cs.jobkorea_content_hash(jobs text,posting text,n jsonb)
RETURNS text LANGUAGE plpgsql STABLE AS $$ DECLARE expected text; actual text; BEGIN
 IF to_regprocedure('enrichment.build_jobkorea_input(text,text)') IS NULL THEN
  RETURN enrichment.hash(cs.jobkorea_source_fields(n)::text);
 END IF;
 expected:=enrichment.hash((enrichment.build_jobkorea_input(jobs,
  cs.external_posting_key('jobkorea',posting))->'source_data')::text);
 actual:=enrichment.linking_input_hash(jobs,cs.external_posting_key('jobkorea',posting));
 IF actual IS DISTINCT FROM expected THEN RAISE EXCEPTION 'JOBKOREA_LINKING_HASH_ADAPTER_NOT_INSTALLED'; END IF;
 RETURN actual;
END $$;
$content_hash$;
 SELECT pg_get_viewdef('cs.common_posting'::regclass,true) INTO definition;
 IF position('cs.jobkorea_content_hash(' IN definition)>0 THEN RETURN; END IF;
 IF position(marker IN definition)=0 OR
  (length(definition)-length(replace(definition,marker,'')))/length(marker)<>1
 THEN RAISE EXCEPTION 'JOBKOREA_COMMON_POSTING_UPGRADE_REQUIRES_REVIEW'; END IF;
 definition:=replace(definition,marker,
  'cs.jobkorea_content_hash(r.run_id, r.normalized ->> ''posting_id'', r.normalized) AS content_hash');
 EXECUTE 'CREATE OR REPLACE VIEW cs.common_posting AS '||definition;
END $cs_link_hash$;

COMMENT ON FUNCTION enrichment.jobkorea_pilot_scope(jsonb) IS
 'Lexical IT/software/data pilot hints only. UNKNOWN does not mean out of scope; no role/category/title metadata establishes work duties.';
COMMENT ON FUNCTION enrichment.prepare_jobkorea_linking_pilot(text,text,integer) IS
 'Bounded current local-file input preparation. Default 5, hard cap 25. Does not execute model requests, accept reviews or publish links.';
COMMIT;
