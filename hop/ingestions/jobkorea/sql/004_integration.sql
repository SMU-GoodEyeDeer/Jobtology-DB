-- Additive source-graph projection and optional common-posting bridge.
-- Install after 001-003. Never changes existing source facts or reviewed hashes.
BEGIN;
-- JobKorea graph facts are explicit metadata. Raw payloads, URL references and
-- narratives stay in PostgreSQL; existing source projections keep their facts.
CREATE OR REPLACE FUNCTION ingestion.jobkorea_graph_facts(n jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) FROM jsonb_each(n)
 WHERE key IN ('kind','posting_id','native_posting_id','representation','title',
 'organization_name','company_name_raw','employer_identity_kind','company_type',
 'company_size','industry','education','experience_raw','employment_type','salary_raw',
 'regions','work_hours','headcount','role','job_position_raw','job_functions',
 'benefits_text','benefits_tags','application_method','application_start_date',
 'application_start_at','application_start_precision','application_start_timezone',
 'closing_date','deadline_kind','deadline_basis','deadline_raw','deadline_date',
 'deadline_at','deadline_timezone','deadline_precision','deadline_display_label',
 'content_status','extraction_eligible','source_status','scope','provider_complete')
$$;

-- Rebuildable graph projection. Record identities are scoped to this experiment;
-- they are intentionally not the Python loader's content-addressed revision IDs.
CREATE OR REPLACE VIEW ingestion.graph_record AS
SELECT 'hop:' || r.run_id || ':' || r.record_id::text AS id,
       r.run_id, r.record_id, r.source_id, r.source_record_id,
       r.normalized->>'kind' AS kind,
       COALESCE(r.normalized->>'name', r.normalized->>'title',
                r.normalized->>'qualification_name', r.normalized->>'occupation_name') AS name,
       (CASE WHEN r.source_id='jobkorea' THEN ingestion.jobkorea_graph_facts(r.normalized)
        ELSE r.normalized - ARRAY['definition', 'eligibility_text', 'disqualification_text',
          'preference_text', 'selection_text', 'address', 'website', 'source_url'] END)::text AS facts_json
FROM ingestion.ready_record r;

CREATE OR REPLACE VIEW ingestion.graph_reference AS
SELECT 'hop:' || r.run_id || ':' || r.record_id::text AS record_id, r.run_id,
       ref.namespace || ':' || ref.code AS identity_id, ref.kind, ref.code, ref.field
FROM ingestion.ready_record r
CROSS JOIN LATERAL (
    SELECT 'ncs:occupation' AS namespace, 'Occupation' AS kind,
           r.normalized->>'occupation_code' AS code, 'occupation_code' AS field
    WHERE r.source_id IN ('ncs_career_path', 'ncs_competency')
    UNION ALL
    SELECT 'ncs:unversioned-unit', 'Competency', r.normalized->>'competency_code', 'competency_code'
    WHERE r.source_id = 'ncs_career_path'
    UNION ALL
    SELECT 'ncs:unit', 'Competency', r.normalized->>'code', 'code'
    WHERE r.source_id = 'ncs_competency'
    UNION ALL
    SELECT 'ncs:unit', 'Competency', r.normalized->>'competency_code', 'competency_code'
    WHERE r.source_id = 'ncs_qualification'
    UNION ALL
    SELECT 'qnet:qualification', 'Qualification', r.normalized->>'qualification_code', 'qualification_code'
    WHERE r.source_id IN ('ncs_qualification', 'qnet_schedule')
    UNION ALL
    SELECT 'alio:organization', 'Organization', r.normalized->>'code', 'code'
    WHERE r.source_id = 'alio_organization'
    UNION ALL
    SELECT 'alio:organization', 'Organization', r.normalized->>'organization_code', 'organization_code'
    WHERE r.source_id = 'job_alio'
    UNION ALL
    SELECT 'job-alio:posting', 'JobPosting', r.normalized->>'posting_id', 'posting_id'
    WHERE r.source_id = 'job_alio'
    UNION ALL
    SELECT 'source:posting:nara_job', 'JobPosting',
           encode(sha256(convert_to(r.normalized->>'posting_id','UTF8')),'hex'), 'posting_id'
    WHERE r.source_id = 'nara_job'
    UNION ALL
    SELECT 'source:posting:jobkorea', 'JobPosting',
           encode(sha256(convert_to(r.normalized->>'posting_id','UTF8')),'hex'), 'posting_id'
    WHERE r.source_id = 'jobkorea'
) ref
WHERE ref.code IS NOT NULL;

-- CS is optional for the source-graph import; reconcile its bridge when present.
DO $cs_bridge$ BEGIN
 IF to_regclass('cs.common_posting') IS NOT NULL THEN
  EXECUTE $source_contract$
-- This source contract is separate from enrichment.source_fields, so existing
-- JOB-ALIO/Nara reviewed hashes remain unchanged. References and source payloads
-- are evidence in PostgreSQL, never input text or a recovery instruction.
CREATE OR REPLACE FUNCTION cs.jobkorea_source_fields(n jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) FROM jsonb_each(n)
 WHERE key IN ('title','organization_name','company_name_raw','employer_identity_kind',
 'company_type','company_size','industry','education','experience_raw','employment_type',
 'salary_raw','regions','work_hours','headcount','role','job_position_raw','job_functions',
 'benefits_text','benefits_tags','application_method','application_start_date',
 'application_start_at','application_start_precision','application_start_timezone',
 'closing_date','deadline_kind','deadline_basis','deadline_raw','deadline_date',
 'deadline_at','deadline_timezone','deadline_precision','deadline_display_label',
 'content_status','extraction_eligible','source_status','scope','provider_complete',
 'description_text','duties_text','eligibility_text','preference_text','selection_text',
 'disqualification_text')
$$;

$source_contract$;
  EXECUTE $content_hash$
-- Once the structured LLM contract exists, lineage must use its exact hash.
-- Source-only installs retain their original normalized metadata hash.
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
  EXECUTE $common_view$
CREATE OR REPLACE VIEW cs.common_posting AS
SELECT 'job_alio'::text AS source_id,
 p.posting_id AS source_posting_id,
 p.posting_id AS posting_id,
 'job-alio:posting:'||p.posting_id AS posting_identity,
 p.run_id AS snapshot_run_id,
 p.normalized->>'organization_name' AS employer,
 p.normalized->>'title' AS title,
 jsonb_build_object('ncs_category_codes',p.normalized->>'ncs_category_codes',
                    'ncs_category_names',p.normalized->>'ncs_category_names') AS categories,
 p.normalized,
 enrichment.source_fields(p.normalized) AS source_data,
 enrichment.hash(enrichment.source_fields(p.normalized)::text) AS inline_source_hash,
 enrichment.linking_input_hash(p.run_id,p.posting_id) AS content_hash,
 coalesce(d.source_payload->'files','[]'::jsonb) AS attachment_refs,
 jsonb_build_object('list_document_id',p.list_document_id,'list_locator',p.list_locator,
                    'detail_document_id',p.detail_document_id,'detail_locator',p.detail_locator,
                    'field_origin',p.field_origin) AS evidence
FROM ingestion.job_posting p
JOIN ingestion.run r ON r.run_id=p.run_id AND r.source_id='job_alio'
 AND r.state='READY' AND r.mode<>'SMOKE'
LEFT JOIN ingestion.ready_record d ON d.run_id=p.run_id
 AND d.source_record_id=p.posting_id||':detail' AND d.source_id='job_alio'
UNION ALL
SELECT 'nara_job'::text AS source_id,
 p.posting_id AS source_posting_id,
 cs.external_posting_key('nara_job',p.posting_id) AS posting_id,
 cs.external_posting_identity('nara_job',p.posting_id) AS posting_identity,
 p.run_id AS snapshot_run_id,
 p.normalized->>'organization_name' AS employer,
 p.normalized->>'title' AS title,
 jsonb_build_object('posting_type_code',p.normalized->>'posting_type_code',
                    'institution_type_code',p.normalized->>'institution_type_code') AS categories,
 p.normalized,
 enrichment.source_fields(p.normalized) AS source_data,
 enrichment.hash(enrichment.source_fields(p.normalized)::text) AS inline_source_hash,
 enrichment.hash(enrichment.source_fields(p.normalized)::text) AS content_hash,
 coalesce(p.normalized->'attachment_refs','[]'::jsonb) AS attachment_refs,
 p.field_origin AS evidence
FROM ingestion.nara_job_posting p
JOIN ingestion.run r ON r.run_id=p.run_id AND r.source_id='nara_job'
 AND r.state='READY' AND r.mode<>'SMOKE'
UNION ALL
SELECT 'jobkorea'::text AS source_id,
 r.normalized->>'posting_id' AS source_posting_id,
 cs.external_posting_key('jobkorea',r.normalized->>'posting_id') AS posting_id,
 cs.external_posting_identity('jobkorea',r.normalized->>'posting_id') AS posting_identity,
 r.run_id AS snapshot_run_id,
 r.normalized->>'organization_name' AS employer,
 r.normalized->>'title' AS title,
 jsonb_strip_nulls(jsonb_build_object('industry',r.normalized->'industry',
  'job_functions',r.normalized->'job_functions','employer_identity_kind',r.normalized->'employer_identity_kind')) AS categories,
 r.normalized,
 cs.jobkorea_source_fields(r.normalized) AS source_data,
 enrichment.hash(cs.jobkorea_source_fields(r.normalized)::text) AS inline_source_hash,
 cs.jobkorea_content_hash(r.run_id,r.normalized->>'posting_id',r.normalized) AS content_hash,
 '[]'::jsonb AS attachment_refs,
 jsonb_build_object('document_id',r.document_id,'locator',r.locator,
  'field_lineage',r.field_lineage,'quality_flags',r.quality_flags,'transport','LOCAL_FILE') AS evidence
FROM ingestion.ready_record r WHERE r.source_id='jobkorea'
UNION ALL
SELECT i.source_id,
 i.source_posting_id,
 cs.external_posting_key(i.source_id,i.source_posting_id) AS posting_id,
 cs.external_posting_identity(i.source_id,i.source_posting_id) AS posting_identity,
 i.snapshot_run_id,
 i.employer,
 i.title,
 i.categories,
 i.normalized,
 i.source_data,
 enrichment.hash(i.source_data::text) AS inline_source_hash,
 enrichment.hash(i.source_data::text) AS content_hash,
 i.attachment_refs,
 i.evidence
FROM cs.posting_input i JOIN cs.source_snapshot s
 USING (source_id,snapshot_run_id) WHERE s.state='READY';

$common_view$;
 END IF;
END $cs_bridge$;
COMMIT;
