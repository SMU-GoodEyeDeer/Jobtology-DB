-- Versioned, source-bound selection of advertised IT/AI/data positions.
-- Requires cs/sql/001_common_postings.sql and the existing enrichment reviews.
BEGIN;
CREATE SCHEMA IF NOT EXISTS cs;

CREATE TABLE IF NOT EXISTS cs.scope_policy (
 policy_id text PRIMARY KEY, description text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO cs.scope_policy(policy_id,description) VALUES
 ('cs-it-ai-data-v1','Technical software, IT systems, security, data and AI advertised work; candidate screening requires position-level review.')
ON CONFLICT DO NOTHING;

-- Regexes are deliberately screening signals, never semantic acceptance.
CREATE OR REPLACE FUNCTION cs.scope_families_v1(value text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(array_agg(family ORDER BY family),ARRAY[]::text[]) FROM (
  SELECT 'SOFTWARE'::text family WHERE coalesce(value,'') ~* '(소프트웨어|프로그래밍|프로그램 개발|응용SW|시스템SW|SW개발|백엔드|프론트엔드|풀스택|웹.?개발|앱.?개발|API.?개발|software engineer|software develop|backend|frontend|full.?stack|programmer)'
  UNION ALL SELECT 'IT_SYSTEMS' WHERE coalesce(value,'') ~* '(클라우드|DevOps|데브옵스|인프라|네트워크|통신망.?구축|통신망.?유지보수|시스템.?운영|서버.?운영|전산.?운영|IT.?운영|정보시스템.?운영|cloud engineer|infrastructure|network engineer|site reliability|SRE)'
  UNION ALL SELECT 'SECURITY' WHERE coalesce(value,'') ~* '(정보보안|사이버.?보안|보안.?관제|침해.?대응|보안.?엔지니어|cybersecurity|security engineer|security operations)'
  UNION ALL SELECT 'DATA' WHERE coalesce(value,'') ~* '(데이터.?엔지니어|데이터.?분석|데이터.?사이언|빅데이터|데이터베이스|DB.?엔지니어|data engineer|data analyst|data scientist|database engineer|analytics engineer)'
  UNION ALL SELECT 'AI' WHERE coalesce(value,'') ~* '(인공지능|머신러닝|기계학습|딥러닝|생성형.?AI|AI.?엔지니어|AI.?개발|LLM|machine learning|artificial intelligence|ML engineer)'
 ) families
$$;

-- Narrow, position-level triage cues. These never produce acceptance. Do not
-- apply them to posting-wide NCS categories in mixed-position notices.
CREATE OR REPLACE FUNCTION cs.scope_title_families_v1(value text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(array_agg(DISTINCT family ORDER BY family),ARRAY[]::text[]) FROM (
  SELECT unnest(cs.scope_families_v1(regexp_replace(coalesce(value,''),'<[^>]+>',' ','g'))) AS family
  UNION ALL SELECT 'IT_SYSTEMS' WHERE coalesce(value,'') ~* '(^|[^[:alpha:]])(IT|ICT)([^[:alpha:]]|$)'
  UNION ALL SELECT 'SOFTWARE' WHERE regexp_replace(coalesce(value,''),'<[^>]+>',' ','g') ~* '전산.{0,12}개발'
 ) candidates
$$;

CREATE OR REPLACE FUNCTION cs.scope_duty_families_v1(value text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(array_agg(DISTINCT family ORDER BY family),ARRAY[]::text[]) FROM (
  SELECT unnest(cs.scope_families_v1(value)) AS family
  UNION ALL SELECT 'SOFTWARE' WHERE coalesce(value,'') ~* '(쿠버네티스|Kubernetes|CI.?/?CD|정보시스템.{0,80}개발|지능형.?검색.?플랫폼.{0,30}(구축|개발))'
  UNION ALL SELECT 'IT_SYSTEMS' WHERE coalesce(value,'') ~* '(플랫폼.?아키텍처|컨테이너.?플랫폼.{0,30}(설계|운영))'
  UNION ALL SELECT 'SECURITY' WHERE coalesce(value,'') ~* '(사이버.?위협정보|랜섬웨어|스미싱)'
  UNION ALL SELECT 'DATA' WHERE coalesce(value,'') ~* '(데이터.?구조.?검토|데이터.?정제|데이터.?품질.{0,8}(점검|검증)|메타데이터|지식.?데이터.?구조화)'
  UNION ALL SELECT 'DATA' WHERE coalesce(value,'') ~* '퀀트' AND coalesce(value,'') ~* '시스템.{0,20}(개발|운영)'
  UNION ALL SELECT 'AI' WHERE coalesce(value,'') ~* 'AI.?기반.{0,200}평가체계' AND coalesce(value,'') ~* '프로토타입.{0,20}구현'
 ) candidates
$$;

CREATE OR REPLACE FUNCTION cs.scope_duty_text_v1(extraction jsonb, role_id text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(string_agg(coalesce(duty->>'text',array_to_string(ARRAY(
  SELECT jsonb_array_elements_text(coalesce(duty->'text_parts','[]'::jsonb))),' ')),E'\n' ORDER BY ordinal),'')
 FROM jsonb_array_elements(coalesce(extraction->'duties','[]'::jsonb)) WITH ORDINALITY d(duty,ordinal)
 WHERE coalesce(duty->'position_ids','[]'::jsonb) ? role_id
$$;

CREATE OR REPLACE VIEW cs.scope_role_input AS
SELECT p.source_id,p.source_posting_id,p.posting_id,p.posting_identity,p.snapshot_run_id,
 p.title,p.categories,p.content_hash,p.employer,
 coalesce(x.revision_id,'') AS revision_id,x.review_decision,x.extraction_state,
 role->>'id' AS role_id,role->>'name' AS role_name,
 cs.scope_duty_text_v1(x.extraction,role->>'id') AS duty_text,
 coalesce(role->'evidence_ids','[]'::jsonb) AS role_evidence_ids,
 CASE WHEN x.extraction IS NULL OR jsonb_array_length(coalesce(x.extraction->'positions','[]'::jsonb))=0
   THEN 'SOURCE_TITLE' ELSE 'MODEL_EXTRACTION' END AS role_origin
FROM cs.common_posting p
JOIN (
 SELECT 'job_alio'::text AS source_id,run_id AS snapshot_run_id
 FROM ingestion.latest_ready_run WHERE source_id='job_alio'
 UNION ALL
 SELECT selected.source_id,selected.snapshot_run_id FROM (
  SELECT DISTINCT ON (source_id) source_id,snapshot_run_id
  FROM cs.source_snapshot WHERE state='READY'
  ORDER BY source_id,completed_at DESC,snapshot_run_id DESC
 ) selected
) current_snapshot USING(source_id,snapshot_run_id)
LEFT JOIN LATERAL (
 SELECT r.revision_id,r.decision AS review_decision,r.extraction,
   'REVIEWED'::text AS extraction_state
 FROM enrichment.extraction_review_state r
 JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
 WHERE p.source_id='job_alio' AND b.mode='ENRICH' AND i.posting_id=p.posting_id
   AND i.source_hash=p.content_hash AND r.decision='ACCEPT'
 ORDER BY r.revision_no DESC LIMIT 1
) reviewed ON true
LEFT JOIN LATERAL (
 SELECT a.parsed_output AS extraction
 FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
 JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id
 WHERE p.source_id='job_alio' AND b.mode='ENRICH' AND i.posting_id=p.posting_id
   AND i.source_hash=p.content_hash AND a.state='VALIDATED'
 ORDER BY b.created_at DESC,i.item_id DESC LIMIT 1
) attempt ON reviewed.revision_id IS NULL
CROSS JOIN LATERAL (
 SELECT reviewed.revision_id,reviewed.review_decision,
   CASE WHEN reviewed.revision_id IS NOT NULL THEN reviewed.extraction_state
        WHEN attempt.extraction IS NOT NULL THEN 'VALIDATED_UNREVIEWED' ELSE 'SOURCE_ONLY' END AS extraction_state,
   coalesce(reviewed.extraction,attempt.extraction) AS extraction
) x
CROSS JOIN LATERAL jsonb_array_elements(CASE
 WHEN jsonb_array_length(coalesce(x.extraction->'positions','[]'::jsonb))>0
 THEN x.extraction->'positions'
 ELSE jsonb_build_array(jsonb_build_object('id','posting','name',p.title,'evidence_ids','[]'::jsonb)) END) role;

CREATE TABLE IF NOT EXISTS cs.scope_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 policy_id text NOT NULL REFERENCES cs.scope_policy,
 posting_identity text NOT NULL, role_id text NOT NULL,
 binding_hash text NOT NULL,
 decision text NOT NULL CHECK(decision IN ('IN_SCOPE','OUT_OF_SCOPE','NEEDS_REVIEW')),
 family text CHECK(family IN ('SOFTWARE','IT_SYSTEMS','SECURITY','DATA','AI')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant','policy')),
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS scope_decision_lookup ON cs.scope_decision(policy_id,posting_identity,role_id,binding_hash,decision_id DESC);

CREATE OR REPLACE VIEW cs.scope_screen AS
SELECT r.*, 'cs-it-ai-data-v1'::text AS policy_id,
 cs.scope_title_families_v1(r.role_name) AS title_families,
 cs.scope_duty_families_v1(r.duty_text) AS duty_families,
 cs.scope_families_v1(r.categories::text) AS category_families,
 enrichment.hash(jsonb_build_array('cs-it-ai-data-v1',r.posting_identity,r.content_hash,
  r.revision_id,r.role_id,r.role_name,r.role_origin,r.role_evidence_ids,
  r.duty_text,r.categories,r.review_decision,r.extraction_state)::text) AS binding_hash,
 CASE
  WHEN cardinality(cs.scope_title_families_v1(r.role_name))>0 THEN 'IN_SCOPE_CANDIDATE'
  WHEN cardinality(cs.scope_duty_families_v1(r.duty_text))>0 OR cardinality(cs.scope_families_v1(r.categories::text))>0
   THEN 'NEEDS_REVIEW'
  ELSE 'OUT_OF_SCOPE_CANDIDATE' END AS screen_status
FROM cs.scope_role_input r;

CREATE OR REPLACE VIEW cs.current_scope AS
SELECT s.*,d.decision_id,d.decision AS scope_decision,d.family AS selected_family,
 d.reviewer,d.reviewer_kind,d.reason AS review_reason,d.created_at AS reviewed_at,
 CASE WHEN d.decision IS NOT NULL THEN d.decision
  WHEN s.screen_status='OUT_OF_SCOPE_CANDIDATE' THEN 'OUT_OF_SCOPE_CANDIDATE'
  ELSE 'NEEDS_REVIEW' END AS scope_status
FROM cs.scope_screen s LEFT JOIN LATERAL (
 SELECT d.* FROM cs.scope_decision d
 WHERE d.policy_id=s.policy_id AND d.posting_identity=s.posting_identity
  AND d.role_id=s.role_id AND d.binding_hash=s.binding_hash
 ORDER BY d.decision_id DESC LIMIT 1
) d ON true;

CREATE OR REPLACE FUNCTION cs.decide_scope_v1(identity text,role text,binding text,choice text,
 family_name text,who text,kind text,why text) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE current_row cs.scope_screen%ROWTYPE; latest_decision cs.scope_decision%ROWTYPE;
 decision_key bigint; BEGIN
 IF choice IS NULL OR choice NOT IN ('IN_SCOPE','OUT_OF_SCOPE','NEEDS_REVIEW') OR
  kind IS NULL OR kind NOT IN ('human','assistant','policy') OR length(btrim(coalesce(who,'')))=0 OR
  length(btrim(coalesce(why,'')))=0 OR
  (choice='IN_SCOPE' AND (family_name IS NULL OR family_name NOT IN ('SOFTWARE','IT_SYSTEMS','SECURITY','DATA','AI'))) OR
  (choice<>'IN_SCOPE' AND family_name IS NOT NULL)
 THEN RAISE EXCEPTION 'INVALID_SCOPE_DECISION'; END IF;
 SELECT * INTO STRICT current_row FROM cs.scope_screen s
 WHERE s.posting_identity=identity AND s.role_id=role;
 IF current_row.binding_hash<>binding THEN RAISE EXCEPTION 'STALE_SCOPE_BINDING'; END IF;
 SELECT * INTO latest_decision FROM cs.scope_decision d
 WHERE d.policy_id=current_row.policy_id AND d.posting_identity=identity
  AND d.role_id=role AND d.binding_hash=binding
 ORDER BY d.decision_id DESC LIMIT 1;
 IF latest_decision.decision_id IS NOT NULL AND latest_decision.decision=choice
  AND latest_decision.family IS NOT DISTINCT FROM family_name
  AND latest_decision.reviewer=who AND latest_decision.reviewer_kind=kind
  AND latest_decision.reason=why THEN RETURN latest_decision.decision_id; END IF;
 INSERT INTO cs.scope_decision(policy_id,posting_identity,role_id,binding_hash,decision,family,reviewer,reviewer_kind,reason)
 VALUES(current_row.policy_id,identity,role,binding,choice,family_name,who,kind,why)
 RETURNING decision_id INTO decision_key;
 RETURN decision_key;
END $$;

CREATE OR REPLACE VIEW cs.scope_summary AS
SELECT policy_id,source_id,scope_status,count(*) AS positions,
 count(DISTINCT posting_identity) AS postings
FROM cs.current_scope GROUP BY policy_id,source_id,scope_status;
COMMIT;
