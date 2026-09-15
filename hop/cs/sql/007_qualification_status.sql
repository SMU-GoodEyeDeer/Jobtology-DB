-- Read-only, source-qualified qualification coverage for current accepted CS
-- positions. Requires 003_completion_report.sql and 006_qualification_support.sql.
-- This installer makes no source, graph, or model request.
BEGIN;

CREATE OR REPLACE VIEW cs.current_role_qualification AS
WITH runs AS (
 SELECT q.run_id AS qualification_run_id,e.run_id AS qnet_run_id,
        qdep.input_run_id AS qualification_ncs_run_id,
        edep.input_run_id AS qnet_qualification_run_id
 FROM (SELECT 1) seed
 LEFT JOIN ingestion.latest_ready_run q ON q.source_id='ncs_qualification'
 LEFT JOIN ingestion.latest_ready_run e ON e.source_id='qnet_schedule'
 LEFT JOIN ingestion.dependency qdep ON qdep.run_id=q.run_id
  AND qdep.input_source_id='ncs_competency'
 LEFT JOIN ingestion.dependency edep ON edep.run_id=e.run_id
  AND edep.input_source_id='ncs_qualification'
)
SELECT s.policy_id,s.source_id,s.source_posting_id,s.posting_identity,
       s.snapshot_run_id,s.role_id,s.role_name,s.binding_hash,s.selected_family,
       l.candidate_id,l.duty_index,k.report_link_id,
       r.ncs_unit_code,r.ncs_unit_name,
       c.occupation_code,c.occupation_name,
       CASE WHEN c.occupation_code IS NULL THEN 'UNRESOLVED_NCS'
            WHEN left(c.occupation_code,2)='20' THEN 'TECHNICAL_CATEGORY_20'
            ELSE 'OTHER_NCS_CATEGORY' END AS ncs_category,
       r.qualification_code,r.qualification_name,r.standard_version,
       r.qualification_relation,r.qualification_status,r.exam_status,
       r.exam_sessions,
       u.qualification_run_id,u.qnet_run_id,u.qualification_ncs_run_id,
       u.qnet_qualification_run_id
FROM cs.accepted_role_link l JOIN cs.current_scope s
 ON s.posting_identity=l.posting_identity AND s.role_id=l.role_id
 AND s.binding_hash=l.binding_hash AND s.scope_status='IN_SCOPE'
CROSS JOIN runs u
CROSS JOIN LATERAL (
 SELECT md5(jsonb_build_array(s.posting_identity,s.role_id,s.binding_hash,
   l.candidate_id,l.duty_index,l.competency_code)::text) AS report_link_id
) k
CROSS JOIN LATERAL ingestion.related_qualification_report(
 jsonb_build_array(jsonb_build_object(
   'source_id',s.source_id,'source_posting_id',s.source_posting_id,
   'position_id',s.role_id,'link_id',k.report_link_id,
   'ncs_unit_code',l.competency_code)),
 u.qualification_run_id,u.qnet_run_id) r
LEFT JOIN ingestion.competency c ON c.run_id=u.qualification_ncs_run_id
 AND c.code=l.competency_code;

CREATE OR REPLACE VIEW cs.current_role_qualification_summary AS
SELECT policy_id,source_id,source_posting_id,posting_identity,snapshot_run_id,
       role_id,role_name,binding_hash,selected_family,
       qualification_run_id,qnet_run_id,
       count(DISTINCT report_link_id) AS accepted_ncs_links,
       count(DISTINCT report_link_id) FILTER
         (WHERE ncs_category='TECHNICAL_CATEGORY_20') AS technical_ncs_links,
       count(DISTINCT report_link_id) FILTER
         (WHERE ncs_category='OTHER_NCS_CATEGORY') AS other_ncs_links,
       count(DISTINCT qualification_code) FILTER
         (WHERE qualification_status='HAS_RELATED_QUALIFICATION') AS related_credentials,
       count(DISTINCT report_link_id) FILTER
         (WHERE qualification_status='UNFETCHED_QUALIFICATION_PARTITION') AS unfetched_links,
       count(DISTINCT report_link_id) FILTER
         (WHERE qualification_status='FETCHED_NO_MAPPING') AS fetched_without_mapping_links,
       count(DISTINCT report_link_id) FILTER
         (WHERE qualification_status='NO_READY_QUALIFICATION_SNAPSHOT') AS no_ready_qualification_links,
       count(DISTINCT qualification_code) FILTER
         (WHERE exam_status='HAS_EXAM_SESSION') AS credentials_with_exam_sessions,
       count(DISTINCT qualification_code) FILTER
         (WHERE exam_status IN ('FETCHED_NO_EXAM_SESSION','UNFETCHED_EXAM_PARTITION',
            'NO_READY_EXAM_SNAPSHOT','EXAM_SNAPSHOT_FOR_DIFFERENT_QUALIFICATION_RUN'))
         AS credentials_without_current_exam_sessions
FROM cs.current_role_qualification
GROUP BY policy_id,source_id,source_posting_id,posting_identity,snapshot_run_id,
         role_id,role_name,binding_hash,selected_family,
         qualification_run_id,qnet_run_id;

COMMIT;
