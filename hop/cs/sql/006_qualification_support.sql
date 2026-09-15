-- Install after reference-support.sql. New qualification runs pin the active
-- occupation codes in settings. Earlier runs retain the original 11-name scope.
-- Eleven category-20 occupations beyond the legacy scope are enabled by the
-- reviewed in-scope CS role-link audit of 2026-09-15. Unlinked candidates stay
-- disabled. Installation makes no reference HTTP or model request.
BEGIN;
CREATE TABLE IF NOT EXISTS ingestion.qualification_occupation_policy (
    policy_version text NOT NULL,
    occupation_code text NOT NULL CHECK (occupation_code ~ '^[0-9]{8}$'),
    occupation_name text NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    reason text NOT NULL,
    PRIMARY KEY (policy_version, occupation_code)
);

INSERT INTO ingestion.qualification_occupation_policy
    (policy_version, occupation_code, occupation_name, enabled, reason)
VALUES
 ('cs-it-ai-data-v1','20010105','빅데이터분석',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010107','빅데이터기획',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010202','응용SW엔지니어링',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010204','DB엔지니어링',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010207','UI/UX엔지니어링',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010208','시스템SW엔지니어링',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010701','인공지능플랫폼구축',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010703','인공지능모델링',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010705','인공지능서비스구현',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010706','인공지능학습데이터구축',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','20010707','생성형AI엔지니어링',true,'Existing qualification scope'),
 ('cs-it-ai-data-v1','19010401','지능형전력망설비',false,'Excluded after position-level CS scope review'),
 ('cs-it-ai-data-v1','20011101','개인정보보호관리운영',true,'Reviewed CS links: technical privacy operations'),
 ('cs-it-ai-data-v1','20020303','초고속망서비스',false,'Excluded after position-level CS scope review'),
 ('cs-it-ai-data-v1','20010201','SW아키텍처',false,'Candidate: software architecture'),
 ('cs-it-ai-data-v1','20010203','임베디드SW엔지니어링',false,'Candidate: embedded software'),
 ('cs-it-ai-data-v1','20010206','보안엔지니어링',false,'Candidate: security engineering'),
 ('cs-it-ai-data-v1','20010209','빅데이터플랫폼구축',true,'Reviewed CS link: data platform architecture'),
 ('cs-it-ai-data-v1','20010211','데이터아키텍처',false,'Candidate: data architecture'),
 ('cs-it-ai-data-v1','20010213','인프라스트럭쳐아키텍처구축',true,'Reviewed CS links: HPC server and network infrastructure'),
 ('cs-it-ai-data-v1','20010214','클라우드솔루션아키텍처',false,'Candidate: cloud architecture'),
 ('cs-it-ai-data-v1','20010215','클라우드인프라스트럭쳐엔지니어링',false,'Candidate: cloud infrastructure'),
 ('cs-it-ai-data-v1','20010301','IT시스템관리',true,'Reviewed CS links: technical IT operations'),
 ('cs-it-ai-data-v1','20010303','IT기술지원',true,'Reviewed CS links: technical IT support'),
 ('cs-it-ai-data-v1','20010304','빅데이터운영·관리',false,'Candidate: data operations'),
 ('cs-it-ai-data-v1','20010401','IT프로젝트관리',true,'Reviewed CS links: IT project planning and delivery'),
 ('cs-it-ai-data-v1','20010402','IT품질보증',false,'Candidate: software quality'),
 ('cs-it-ai-data-v1','20010403','IT테스트',false,'Candidate: software testing'),
 ('cs-it-ai-data-v1','20010601','정보보호관리·운영',true,'Reviewed CS link: security risk management'),
 ('cs-it-ai-data-v1','20010602','정보보호진단·분석',true,'Reviewed CS link: penetration testing'),
 ('cs-it-ai-data-v1','20010603','보안사고분석대응',true,'Reviewed CS links: incident response'),
 ('cs-it-ai-data-v1','20010604','정보보호암호·인증',false,'Candidate: cryptography/authentication'),
 ('cs-it-ai-data-v1','20010608','디지털포렌식',false,'Candidate: digital forensics'),
 ('cs-it-ai-data-v1','20010611','OT보안',false,'Candidate: operational technology security'),
 ('cs-it-ai-data-v1','20010612','클라우드 보안 관리·운영',false,'Candidate: cloud security'),
 ('cs-it-ai-data-v1','20010614','정보보호제품 시험·평가',false,'Candidate: security product testing'),
 ('cs-it-ai-data-v1','20010615','SW공급망보안',false,'Candidate: software supply chain security'),
 ('cs-it-ai-data-v1','20010704','인공지능서비스운영관리',false,'Candidate: AI service operations'),
 ('cs-it-ai-data-v1','20020103','네트워크구축',true,'Reviewed CS links: network engineering'),
 ('cs-it-ai-data-v1','20020110','클라우드플랫폼구축',false,'Candidate: cloud platform'),
 ('cs-it-ai-data-v1','20030303','정보시스템운영',true,'Reviewed CS links: information system operations')
ON CONFLICT (policy_version, occupation_code) DO NOTHING;

CREATE OR REPLACE VIEW ingestion.active_qualification_scope AS
SELECT occupation_code, occupation_name, policy_version
FROM ingestion.qualification_occupation_policy
WHERE policy_version='cs-it-ai-data-v1' AND enabled;

-- The legacy fallback prevents a policy change from altering the expected
-- partitions of qualification runs already recorded in PostgreSQL.
CREATE OR REPLACE VIEW ingestion.expected_reference_partition AS
SELECT u.run_id, 'ncs-'||c.code AS partition_id,
       jsonb_build_object('ncsClCd',c.code,'dataFormat','json') AS request_context
FROM ingestion.run u JOIN ingestion.dependency d USING(run_id)
JOIN ingestion.competency c ON c.run_id=d.input_run_id
WHERE u.source_id='ncs_qualification' AND d.input_source_id='ncs_competency'
AND ((u.settings ? 'qualification_scope_codes' AND c.occupation_code IN
       (SELECT jsonb_array_elements_text(u.settings->'qualification_scope_codes')))
  OR (NOT (u.settings ? 'qualification_scope_codes') AND EXISTS
       (SELECT 1 FROM ingestion.qualification_scope s
        WHERE s.occupation_name=c.occupation_name)))
UNION ALL
SELECT DISTINCT u.run_id,'year-'||y.year||'-item-'||upper(q.qualification_code),
       jsonb_build_object('implYy',y.year::text,'jmCd',upper(q.qualification_code),'dataFormat','json')
FROM ingestion.run u JOIN ingestion.dependency d USING(run_id)
JOIN ingestion.qualification_mapping q ON q.run_id=d.input_run_id
CROSS JOIN LATERAL generate_series((u.settings->>'year_from')::integer,
                                  (u.settings->>'year_to')::integer) y(year)
WHERE u.source_id='qnet_schedule' AND d.input_source_id='ncs_qualification'
AND upper(q.qualification_code) ~ '^[A-Z0-9]{4}$';

CREATE OR REPLACE VIEW ingestion.reference_scope_issue AS
SELECT coalesce(e.run_id,p.run_id) AS run_id,
       'REFERENCE_PARTITION_SCOPE_MISMATCH'::text AS issue,
       coalesce(e.partition_id,p.partition_id) AS location
FROM ingestion.expected_reference_partition e
FULL JOIN (SELECT p.* FROM ingestion.partition p JOIN ingestion.run u USING(run_id)
 WHERE u.source_id IN ('ncs_qualification','qnet_schedule')) p USING(run_id,partition_id)
WHERE e.run_id IS NULL OR p.run_id IS NULL OR p.request_context<>e.request_context
   OR p.page_size<>50 OR p.kind<>'PAGED'
UNION ALL
SELECT u.run_id,'MISSING_QUALIFICATION_OCCUPATION',s.occupation_name
FROM ingestion.run u JOIN ingestion.dependency d USING(run_id)
CROSS JOIN ingestion.qualification_scope s
WHERE u.source_id='ncs_qualification' AND d.input_source_id='ncs_competency'
  AND NOT (u.settings ? 'qualification_scope_codes')
  AND NOT EXISTS(SELECT 1 FROM ingestion.competency c
                 WHERE c.run_id=d.input_run_id AND c.occupation_name=s.occupation_name)
UNION ALL
SELECT u.run_id,'MISSING_QUALIFICATION_OCCUPATION',code.occupation_code
FROM ingestion.run u JOIN ingestion.dependency d USING(run_id)
CROSS JOIN LATERAL jsonb_array_elements_text(u.settings->'qualification_scope_codes')
    AS code(occupation_code)
WHERE u.source_id='ncs_qualification' AND d.input_source_id='ncs_competency'
  AND u.settings ? 'qualification_scope_codes'
  AND NOT EXISTS(SELECT 1 FROM ingestion.competency c
                 WHERE c.run_id=d.input_run_id
                   AND c.occupation_code=code.occupation_code);

-- The caller supplies reviewed selected links from any posting source. This
-- reports related credentials via NCS; it never asserts employer requirements.
CREATE OR REPLACE FUNCTION ingestion.related_qualification_report(
    links jsonb, qualification_run_id text, qnet_run_id text)
RETURNS TABLE (
    source_id text, source_posting_id text, position_id text, link_id text,
    ncs_unit_code text, ncs_unit_name text,
    qualification_code text, qualification_name text, standard_version text,
    qualification_relation text, qualification_status text, exam_status text,
    exam_sessions jsonb)
LANGUAGE sql STABLE AS $$
WITH selected AS (
    SELECT * FROM jsonb_to_recordset(links) AS x(
        source_id text, source_posting_id text, position_id text,
        link_id text, ncs_unit_code text)
), runs AS (
    SELECT q.run_id AS qualification_run_id, q.state AS qualification_state,
           dep.input_run_id AS ncs_run_id,
           e.run_id AS exam_run_id, e.state AS exam_state,
           edep.input_run_id AS exam_qualification_run_id
    FROM (SELECT 1) seed
    LEFT JOIN ingestion.run q ON q.run_id=qualification_run_id
                                 AND q.source_id='ncs_qualification'
    LEFT JOIN ingestion.dependency dep ON dep.run_id=q.run_id
                                   AND dep.input_source_id='ncs_competency'
    LEFT JOIN ingestion.run e ON e.run_id=qnet_run_id
                                 AND e.source_id='qnet_schedule'
    LEFT JOIN ingestion.dependency edep ON edep.run_id=e.run_id
                                   AND edep.input_source_id='ncs_qualification'
)
SELECT s.source_id,s.source_posting_id,s.position_id,s.link_id,
       s.ncs_unit_code,c.name,
       m.qualification_code,m.qualification_name,m.standard_version,
       CASE WHEN m.qualification_code IS NULL THEN NULL
            ELSE 'RELATED_VIA_NCS' END,
       CASE WHEN r.qualification_state IS DISTINCT FROM 'READY' THEN 'NO_READY_QUALIFICATION_SNAPSHOT'
            WHEN c.code IS NULL THEN 'UNRESOLVED_NCS_IDENTIFIER'
            WHEN p.partition_id IS NULL THEN 'UNFETCHED_QUALIFICATION_PARTITION'
            WHEN p.expected_total IS NULL THEN 'QUALIFICATION_PARTITION_NOT_VERIFIED'
            WHEN m.qualification_code IS NULL AND p.expected_total=0 THEN 'FETCHED_NO_MAPPING'
            WHEN m.qualification_code IS NULL THEN 'MAPPING_ROWS_MISSING'
            ELSE 'HAS_RELATED_QUALIFICATION' END,
       CASE WHEN m.qualification_code IS NULL THEN 'NO_MAPPING_TO_CHECK'
            WHEN r.exam_state IS DISTINCT FROM 'READY' THEN 'NO_READY_EXAM_SNAPSHOT'
            WHEN r.exam_qualification_run_id IS DISTINCT FROM r.qualification_run_id
              THEN 'EXAM_SNAPSHOT_FOR_DIFFERENT_QUALIFICATION_RUN'
            WHEN qp.fetched_partitions=0 THEN 'UNFETCHED_EXAM_PARTITION'
            WHEN es.exam_count=0 THEN 'FETCHED_NO_EXAM_SESSION'
            ELSE 'HAS_EXAM_SESSION' END,
       CASE WHEN r.exam_state='READY'
              AND r.exam_qualification_run_id=r.qualification_run_id
            THEN coalesce(es.sessions,'[]'::jsonb)
            ELSE '[]'::jsonb END
FROM selected s CROSS JOIN runs r
LEFT JOIN ingestion.competency c ON c.run_id=r.ncs_run_id AND c.code=s.ncs_unit_code
LEFT JOIN ingestion.partition p ON p.run_id=r.qualification_run_id
                               AND p.partition_id='ncs-'||s.ncs_unit_code
LEFT JOIN ingestion.qualification_mapping m
       ON m.run_id=r.qualification_run_id AND m.competency_code=s.ncs_unit_code
LEFT JOIN LATERAL (
    SELECT count(*)::integer AS fetched_partitions FROM ingestion.partition x
    WHERE x.run_id=r.exam_run_id
      AND x.partition_id ~ '^year-[0-9]{4}-item-[A-Z0-9]{4}$'
      AND split_part(x.partition_id,'-item-',2)=upper(m.qualification_code)
) qp ON m.qualification_code IS NOT NULL
LEFT JOIN LATERAL (
    SELECT count(*)::integer AS exam_count,
           coalesce(jsonb_agg(jsonb_build_object(
               'year',e.year,'round',e.round,'name',e.name,'dates',e.dates)
               ORDER BY e.year,e.round),'[]'::jsonb) AS sessions
    FROM ingestion.exam_session e
    WHERE e.run_id=r.exam_run_id
      AND upper(e.qualification_code)=upper(m.qualification_code)
) es ON m.qualification_code IS NOT NULL;
$$;
COMMIT;
