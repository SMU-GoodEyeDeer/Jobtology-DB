-- Explicitly inferred listing metadata -> NCS occupation classification.
-- This is separate from DUTIES_ONLY extraction and competency-unit alignment.
-- Model transport uses the existing batch/item/attempt spend ledger.
BEGIN;

CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_catalog (
 ncs_run_id text NOT NULL REFERENCES ingestion.run,
 occupation_code text NOT NULL CHECK(occupation_code ~ '^[0-9]{8}$'),
 occupation_name text NOT NULL,
 classification_names jsonb NOT NULL,
 unit_names jsonb NOT NULL,
 search_text text NOT NULL,
 catalog_hash text NOT NULL,
 PRIMARY KEY(ncs_run_id,occupation_code)
);
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_binding (
 item_id text PRIMARY KEY REFERENCES enrichment.item,
 bundle_id text NOT NULL REFERENCES enrichment.input_bundle,
 job_run_id text NOT NULL REFERENCES ingestion.run,
 ncs_run_id text NOT NULL REFERENCES ingestion.run,
 source_hash text NOT NULL,
 metadata_hash text NOT NULL,
 candidates jsonb NOT NULL CHECK(jsonb_typeof(candidates)='array'),
 candidates_hash text NOT NULL,
 binding_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_result (
 result_id text PRIMARY KEY,
 result_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 item_id text NOT NULL UNIQUE REFERENCES enrichment.metadata_occupation_binding,
 attempt_id text NOT NULL REFERENCES enrichment.attempt,
 output jsonb NOT NULL,
 actor text NOT NULL CHECK(length(btrim(actor))>0),
 basis text NOT NULL DEFAULT 'METADATA_INFERRED' CHECK(basis='METADATA_INFERRED'),
 assertion_kind text NOT NULL DEFAULT 'MODEL_INFERRED' CHECK(assertion_kind='MODEL_INFERRED'),
 confidence numeric CHECK(confidence IS NULL),
 confidence_state text NOT NULL DEFAULT 'UNASSESSED' CHECK(confidence_state='UNASSESSED'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_candidate (
 candidate_id text PRIMARY KEY,
 result_id text NOT NULL REFERENCES enrichment.metadata_occupation_result,
 ncs_run_id text NOT NULL,
 occupation_code text NOT NULL,
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='array'),
 UNIQUE(result_id,occupation_code),
 FOREIGN KEY(ncs_run_id,occupation_code) REFERENCES enrichment.metadata_occupation_catalog
);
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 result_id text NOT NULL REFERENCES enrichment.metadata_occupation_result,
 decision text NOT NULL CHECK(decision IN('ACCEPT','REJECT')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN('human','assistant')),
 notes text NOT NULL CHECK(length(btrim(notes))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS metadata_occupation_binding_source
 ON enrichment.metadata_occupation_binding(job_run_id,ncs_run_id,source_hash);
CREATE INDEX IF NOT EXISTS metadata_occupation_decision_latest
 ON enrichment.metadata_occupation_decision(result_id,decision_id DESC);

CREATE OR REPLACE FUNCTION enrichment.reject_metadata_occupation_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'IMMUTABLE_METADATA_OCCUPATION_HISTORY';
END $$;
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['metadata_occupation_catalog','metadata_occupation_binding',
  'metadata_occupation_result','metadata_occupation_candidate','metadata_occupation_decision'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='immutable_'||name
   AND tgrelid=('enrichment.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON enrichment.%I FOR EACH ROW EXECUTE FUNCTION enrichment.reject_metadata_occupation_change()',
    'immutable_'||name,name);
   EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON enrichment.%I FOR EACH STATEMENT EXECUTE FUNCTION enrichment.reject_metadata_occupation_change()',
    'immutable_truncate_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_fields(source jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) FROM jsonb_each(source)
 WHERE key IN('title','role','job_functions') AND jsonb_typeof(value)='string'
  AND nullif(btrim(value#>>'{}'),'') IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION enrichment.prepare_metadata_occupation_catalog(ncs text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE expected integer; found integer; BEGIN
 PERFORM retention.gate();
 IF ncs IS NULL OR ncs='LATEST' OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run
  WHERE source_id='ncs_competency' AND run_id=ncs)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REQUIRES_CURRENT_EXACT_NCS_RUN'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('metadata-occupation-catalog:'||ncs,0));
 SELECT count(DISTINCT normalized->>'occupation_code') INTO expected
 FROM ingestion.ready_record WHERE run_id=ncs AND source_id='ncs_competency';
 IF expected=0 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CATALOG_EMPTY'; END IF;
 WITH units AS MATERIALIZED (
  SELECT normalized AS data,normalized->>'occupation_code' AS code,
   normalized->>'occupation_name' AS name FROM ingestion.ready_record
  WHERE run_id=ncs AND source_id='ncs_competency'
 ), grouped AS (
  SELECT code,min(name) AS name,
   jsonb_build_array(min(data->>'classification_1'),min(data->>'classification_2'),min(data->>'classification_3')) AS classes,
   lower(string_agg(concat_ws(' ',name,data->>'name',data->>'definition'),' ' ORDER BY data->>'code')) AS search_text,
   enrichment.hash(jsonb_agg(data ORDER BY data->>'code')::text) AS catalog_hash
  FROM units GROUP BY code
 ), labels AS (
  SELECT code,jsonb_agg(name ORDER BY obsolete,name) AS names FROM (
   SELECT code,name,obsolete FROM (
    SELECT DISTINCT code,left(data->>'name',100) AS name,
     CASE WHEN data->>'name' ~ '(구버전|폐지)' THEN 1 ELSE 0 END AS obsolete FROM units
   ) all_names ORDER BY code,obsolete,name
  ) unique_names GROUP BY code
 ) INSERT INTO enrichment.metadata_occupation_catalog
 SELECT ncs,g.code,g.name,g.classes,
  (SELECT coalesce(jsonb_agg(value ORDER BY ordinal),'[]') FROM jsonb_array_elements(l.names) WITH ORDINALITY x(value,ordinal) WHERE ordinal<=8),
  g.search_text,g.catalog_hash FROM grouped g JOIN labels l USING(code)
 ON CONFLICT DO NOTHING;
 SELECT count(*) INTO found FROM enrichment.metadata_occupation_catalog WHERE ncs_run_id=ncs;
 IF found<>expected THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CATALOG_INCOMPLETE'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.metadata_occupation_catalog c JOIN (
  SELECT normalized->>'occupation_code' AS code,enrichment.hash(jsonb_agg(normalized ORDER BY normalized->>'code')::text) AS hash
  FROM ingestion.ready_record WHERE run_id=ncs AND source_id='ncs_competency'
  GROUP BY normalized->>'occupation_code') current ON current.code=c.occupation_code
  WHERE c.ncs_run_id=ncs AND c.catalog_hash<>current.hash)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CATALOG_SOURCE_CHANGED'; END IF;
 RETURN jsonb_build_object('ncs_run_id',ncs,'occupation_count',found,
  'catalog_hash',(SELECT enrichment.hash(jsonb_agg(jsonb_build_array(occupation_code,catalog_hash) ORDER BY occupation_code)::text)
    FROM enrichment.metadata_occupation_catalog WHERE ncs_run_id=ncs));
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_candidates(ncs text,source jsonb,cap integer DEFAULT 12)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE answer jsonb; BEGIN
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 30 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CANDIDATE_CAP_1_TO_30'; END IF;
 IF NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_catalog WHERE ncs_run_id=ncs)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CATALOG_NOT_PREPARED'; END IF;
 WITH input AS (SELECT lower(string_agg(value,' ' ORDER BY key)) AS text
  FROM jsonb_each_text(enrichment.metadata_occupation_fields(source))),
 words AS MATERIALIZED (
  SELECT DISTINCT word FROM input CROSS JOIN LATERAL regexp_split_to_table(input.text,'[^가-힣a-z0-9]+') word
  WHERE length(word) BETWEEN 2 AND 40
   AND word NOT IN('채용','모집','신입','경력','주니어','시니어','담당','관련','업무','회사','무관','개발자','엔지니어','developer','engineer','junior','senior')
 ), aliases AS (
  -- Retrieval hints translate common listing role vocabulary to official labels.
  -- They are not evidence and do not create an accepted classification.
  SELECT term,2.5::numeric AS weight FROM input CROSS JOIN LATERAL (VALUES
   ('(백.?엔드|프론트.?엔드|프런트|풀스택|backend|frontend|full.?stack|웹|앱|프로그래머|programmer|바이브|소프트웨어|software|java|python|typescript|javascript|csharp|c#|c\+\+|\.net|react|spring)','응용sw'),
   ('(데이터.?분석|data.?analyst|data.?scientist|데이터.?사이언티스트|빅데이터.?분석)','빅데이터분석'),
   ('(데이터.?엔지니어|data.?engineer|데이터.?플랫폼)','빅데이터플랫폼'),
   ('(데이터베이스|database|dba|sql)','데이터베이스'),
   ('(클라우드|cloud|aws|devops)','it시스템'),
   ('(클라우드|cloud|aws)','클라우드'),
   ('(인공지능|머신러닝|딥러닝|(^|[^a-z])ai([^a-z]|$))','인공지능'),
   ('(머신.?비전|machine.?vision|컴퓨터.?비전|computer.?vision)','영상정보'),
   ('(머신.?비전|machine.?vision|컴퓨터.?비전|computer.?vision)','인공지능'),
   ('(머신.?비전|machine.?vision|컴퓨터.?비전|computer.?vision|설비.?연동)','응용sw'),
   ('(임베디드|embedded|펌웨어|firmware|설비.?연동)','임베디드'),
   ('(iot|사물.?인터넷|설비.?연동|시스템.?통합)','iot'),
   ('(강사|교수|교육|훈련|instructor|lecturer|trainer|teacher)','기술교육'),
   ('(강사|교수|교육|훈련|instructor|lecturer|trainer|teacher)','교수'),
   ('(기계|mechanical|자동화.?장비|자동화.?설비|클린.?자동화)','기계설계'),
   ('(기계|mechanical|자동화.?장비|자동화.?설비|클린.?자동화)','기계요소'),
   ('(정보.?보안|정보.?보호|security|cyber|threat|보안)','정보보호'),
   ('(cyber|threat|보안.?사고|침해.?사고)','보안사고'),
   ('(네트워크|network)','네트워크')) x(pattern,term) WHERE input.text ~ x.pattern
 ), terms AS MATERIALIZED (
  SELECT term,max(weight) AS weight FROM (
   SELECT word AS term,1.0::numeric AS weight FROM words
   UNION ALL SELECT substring(word FROM pos FOR len),CASE WHEN len=3 THEN 0.4 ELSE 0.15 END
   FROM words CROSS JOIN generate_series(2,3) len CROSS JOIN LATERAL generate_series(1,length(word)-len+1) pos
   WHERE word ~ '^[가-힣]+$' AND length(word)>len
   UNION ALL SELECT term,weight FROM aliases
  ) fragments WHERE term NOT IN('채용','모집','신입','경력','담당','업무','관련','회사','개발','관리','운영','지원')
  GROUP BY term ORDER BY max(weight) DESC,length(term) DESC,term LIMIT 60
 ), hits AS MATERIALIZED (
  SELECT c.occupation_code,t.term,t.weight,
   CASE WHEN position(t.term in lower(c.occupation_name))>0 THEN 8.0 ELSE 1.0 END AS location_weight
  FROM enrichment.metadata_occupation_catalog c JOIN terms t ON position(t.term in c.search_text)>0
  WHERE c.ncs_run_id=ncs
 ), frequency AS (SELECT term,count(*) AS count FROM hits GROUP BY term),
 ranked AS (
  SELECT h.occupation_code,sum(h.weight*h.location_weight*ln(1.0+
   (SELECT count(*) FROM enrichment.metadata_occupation_catalog WHERE ncs_run_id=ncs)::numeric/f.count)) AS score
  FROM hits h JOIN frequency f USING(term) GROUP BY h.occupation_code
  ORDER BY score DESC,h.occupation_code LIMIT cap
 ) SELECT coalesce(jsonb_agg(jsonb_build_object('occupation_code',c.occupation_code,
  'occupation_name',c.occupation_name,'classification_names',c.classification_names,
  'unit_names',c.unit_names,'catalog_hash',c.catalog_hash,'retrieval_score',round(r.score,3)) ORDER BY r.score DESC,c.occupation_code),'[]')
 INTO answer FROM ranked r JOIN enrichment.metadata_occupation_catalog c USING(occupation_code) WHERE c.ncs_run_id=ncs;
 RETURN answer;
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_output_issues(
 output jsonb,source jsonb,candidates jsonb,max_matches integer DEFAULT 2)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE issues jsonb:='[]'; match jsonb; citation jsonb; fields jsonb:=enrichment.metadata_occupation_fields(source);
BEGIN
 IF jsonb_typeof(output) IS DISTINCT FROM 'object'
  OR NOT output ?& ARRAY['outcome','matches','abstain_reason']
  OR output-ARRAY['outcome','matches','abstain_reason']<>'{}'::jsonb
  OR jsonb_typeof(output->'outcome') IS DISTINCT FROM 'string'
  OR output->>'outcome' NOT IN('matched','abstained')
  OR jsonb_typeof(output->'matches') IS DISTINCT FROM 'array'
  OR jsonb_typeof(output->'abstain_reason') IS DISTINCT FROM 'string'
 THEN RETURN '["METADATA_OCCUPATION_OUTPUT_SHAPE"]'::jsonb; END IF;
 IF max_matches IS NULL OR max_matches NOT BETWEEN 1 AND 2
  OR jsonb_array_length(output->'matches')>max_matches
 THEN issues:=issues||'["METADATA_OCCUPATION_MATCH_CAP"]'::jsonb; END IF;
 IF (output->>'outcome'='matched')<>(jsonb_array_length(output->'matches')>0)
  OR (output->>'outcome'='abstained')<>(length(btrim(output->>'abstain_reason'))>0)
 THEN issues:=issues||'["METADATA_OCCUPATION_OUTCOME"]'::jsonb; END IF;
 IF (SELECT count(DISTINCT m->>'occupation_code') FROM jsonb_array_elements(output->'matches') m)
  <>jsonb_array_length(output->'matches') THEN issues:=issues||'["METADATA_OCCUPATION_DUPLICATE"]'::jsonb; END IF;
 FOR match IN SELECT value FROM jsonb_array_elements(output->'matches') LOOP
  IF jsonb_typeof(match) IS DISTINCT FROM 'object'
   OR NOT match ?& ARRAY['occupation_code','reason','evidence']
   OR match-ARRAY['occupation_code','reason','evidence']<>'{}'::jsonb
   OR jsonb_typeof(match->'occupation_code') IS DISTINCT FROM 'string'
   OR jsonb_typeof(match->'reason') IS DISTINCT FROM 'string'
   OR nullif(btrim(match->>'reason'),'') IS NULL OR length(match->>'reason')>1500
   OR jsonb_typeof(match->'evidence') IS DISTINCT FROM 'array'
  THEN issues:=issues||'["METADATA_OCCUPATION_MATCH_SHAPE"]'::jsonb; CONTINUE; END IF;
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(candidates) c WHERE c->>'occupation_code'=match->>'occupation_code')
  THEN issues:=issues||'["METADATA_OCCUPATION_OUTSIDE_SHORTLIST"]'::jsonb; END IF;
  IF jsonb_array_length(match->'evidence') NOT BETWEEN 1 AND 6
  THEN issues:=issues||'["METADATA_OCCUPATION_EVIDENCE_REQUIRED"]'::jsonb; END IF;
  FOR citation IN SELECT value FROM jsonb_array_elements(match->'evidence') LOOP
   IF jsonb_typeof(citation) IS DISTINCT FROM 'object' OR NOT citation ?& ARRAY['field','quote']
    OR citation-ARRAY['field','quote']<>'{}'::jsonb
    OR jsonb_typeof(citation->'field') IS DISTINCT FROM 'string'
    OR jsonb_typeof(citation->'quote') IS DISTINCT FROM 'string'
    OR nullif(btrim(citation->>'quote'),'') IS NULL OR length(citation->>'quote')>1000
    OR NOT fields ? (citation->>'field')
    OR coalesce(position(citation->>'quote' in fields->>(citation->>'field')),0)=0
   THEN issues:=issues||'["METADATA_OCCUPATION_UNSUPPORTED_CITATION"]'::jsonb; END IF;
  END LOOP;
 END LOOP;
 RETURN issues;
END $$;

CREATE OR REPLACE FUNCTION enrichment.bind_metadata_occupation_item(id text,bundle text,candidates jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE i enrichment.item%ROWTYPE; b enrichment.batch%ROWTYPE; ib enrichment.input_bundle%ROWTYPE;
 old enrichment.metadata_occupation_binding%ROWTYPE; metadata text; ch text; bh text; candidate jsonb; expected jsonb;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=id FOR UPDATE;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=i.batch_id;
 SELECT * INTO STRICT ib FROM enrichment.input_bundle WHERE bundle_id=bundle;
 PERFORM enrichment.verify_item_input(id);
 IF b.mode<>'ENRICH' OR b.settings->>'metadata_scope' IS DISTINCT FROM 'NCS_OCCUPATION_INFERENCE_V1'
  OR b.settings->>'acceptance_policy' IS DISTINCT FROM 'REVIEW'
  OR b.settings->>'prompt_version' IS DISTINCT FROM 'ko-metadata-occupation-v1'
  OR ib.job_run_id<>b.job_run_id OR ib.posting_id<>i.posting_id OR ib.source_hash<>i.source_hash
  OR ib.source_data<>i.source_data OR ib.source_data#>>'{_input,contract}' IS DISTINCT FROM 'jobkorea-input-v1'
  OR NOT EXISTS(SELECT 1 FROM enrichment.item_input WHERE item_id=id AND bundle_id=bundle)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=b.job_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=b.ncs_run_id)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_INPUT_BINDING_INVALID'; END IF;
 IF jsonb_typeof(candidates) IS DISTINCT FROM 'array' OR jsonb_array_length(candidates)>30
  OR jsonb_array_length(candidates)<>(SELECT count(DISTINCT x->>'occupation_code') FROM jsonb_array_elements(candidates) x)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CANDIDATES_INVALID'; END IF;
 FOR candidate IN SELECT value FROM jsonb_array_elements(candidates) LOOP
  SELECT jsonb_build_object('occupation_code',c.occupation_code,'occupation_name',c.occupation_name,
   'classification_names',c.classification_names,'unit_names',c.unit_names,'catalog_hash',c.catalog_hash)
  INTO expected FROM enrichment.metadata_occupation_catalog c
  WHERE c.ncs_run_id=b.ncs_run_id AND c.occupation_code=candidate->>'occupation_code';
  IF expected IS NULL OR candidate-'retrieval_score'<>expected
  THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CANDIDATE_CHANGED'; END IF;
 END LOOP;
 metadata:=enrichment.hash(enrichment.metadata_occupation_fields(i.source_data)::text);
 ch:=enrichment.hash(candidates::text);
 bh:=enrichment.hash(jsonb_build_array('metadata-occupation-binding-v1',b.job_run_id,b.ncs_run_id,bundle,i.source_hash,metadata,ch)::text);
 SELECT * INTO old FROM enrichment.metadata_occupation_binding WHERE item_id=id;
 IF FOUND AND (old.bundle_id<>bundle OR old.binding_hash<>bh)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_BINDING_CHANGED'; END IF;
 INSERT INTO enrichment.metadata_occupation_binding(item_id,bundle_id,job_run_id,ncs_run_id,source_hash,metadata_hash,candidates,candidates_hash,binding_hash)
 VALUES(id,bundle,b.job_run_id,b.ncs_run_id,i.source_hash,metadata,candidates,ch,bh) ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('item_id',id,'bundle_id',bundle,'source_hash',i.source_hash,
  'metadata_hash',metadata,'candidates_hash',ch,'binding_hash',bh);
END $$;

CREATE OR REPLACE FUNCTION enrichment.capture_metadata_occupation_result(id text,actor text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE i enrichment.item%ROWTYPE; binding enrichment.metadata_occupation_binding%ROWTYPE;
 a enrichment.attempt%ROWTYPE; result text; errors jsonb; match jsonb; spans jsonb;
BEGIN
 PERFORM retention.gate();
 IF nullif(btrim(actor),'') IS NULL THEN RAISE EXCEPTION 'METADATA_OCCUPATION_ACTOR_REQUIRED'; END IF;
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=id FOR UPDATE;
 SELECT * INTO STRICT binding FROM enrichment.metadata_occupation_binding WHERE item_id=id;
 SELECT * INTO STRICT a FROM enrichment.attempt WHERE attempt_id=i.categorization_id;
 PERFORM enrichment.verify_item_input(id);
 IF a.state NOT IN('VALIDATED','SKIPPED') OR a.stage<>'categorize'
  OR a.candidates<>binding.candidates
  OR NOT EXISTS(SELECT 1 FROM enrichment.item original JOIN enrichment.batch batch USING(batch_id)
   WHERE original.item_id=a.item_id
    AND enrichment.metadata_occupation_fields(original.source_data)=enrichment.metadata_occupation_fields(i.source_data)
    AND batch.ncs_run_id=binding.ncs_run_id
    AND batch.settings->>'metadata_scope'='NCS_OCCUPATION_INFERENCE_V1')
  OR (a.state='SKIPPED' AND (binding.candidates<>'[]'::jsonb OR a.parsed_output->>'outcome'<>'abstained'))
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_RESULT_NOT_VALIDATED'; END IF;
 errors:=enrichment.metadata_occupation_output_issues(a.parsed_output,i.source_data,binding.candidates,2);
 IF errors<>'[]'::jsonb THEN RAISE EXCEPTION 'METADATA_OCCUPATION_INVALID_OUTPUT: %',errors; END IF;
 result:=enrichment.hash(jsonb_build_array('metadata-occupation-result-v1',id,binding.binding_hash,a.attempt_id,a.parsed_output)::text);
 IF EXISTS(SELECT 1 FROM enrichment.metadata_occupation_result WHERE item_id=id AND result_id<>result)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_RESULT_CHANGED'; END IF;
 INSERT INTO enrichment.metadata_occupation_result(result_id,item_id,attempt_id,output,actor)
 VALUES(result,id,a.attempt_id,a.parsed_output,actor) ON CONFLICT DO NOTHING;
 FOR match IN SELECT value FROM jsonb_array_elements(a.parsed_output->'matches') LOOP
  SELECT jsonb_agg(e||jsonb_build_object('start',position(e->>'quote' in i.source_data->>(e->>'field')),
   'end',position(e->>'quote' in i.source_data->>(e->>'field'))+length(e->>'quote')-1,
   'offset_unit','unicode-codepoint-one-inclusive','source_hash',i.source_hash,'bundle_id',binding.bundle_id,
   'evidence_role','LISTING_METADATA','occurrence_policy','FIRST_EXACT_OCCURRENCE') ORDER BY ordinal)
  INTO spans FROM jsonb_array_elements(match->'evidence') WITH ORDINALITY x(e,ordinal);
  INSERT INTO enrichment.metadata_occupation_candidate(candidate_id,result_id,ncs_run_id,occupation_code,reason,evidence)
  VALUES(enrichment.hash(jsonb_build_array(result,match->>'occupation_code')::text),result,binding.ncs_run_id,
   match->>'occupation_code',match->>'reason',spans) ON CONFLICT DO NOTHING;
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION enrichment.decide_metadata_occupation(
 result text,decision text,reviewer text,kind text,notes text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE r enrichment.metadata_occupation_result%ROWTYPE; id bigint; old enrichment.metadata_occupation_decision%ROWTYPE;
 binding enrichment.metadata_occupation_binding%ROWTYPE;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT r FROM enrichment.metadata_occupation_result WHERE result_id=result FOR UPDATE;
 SELECT * INTO STRICT binding FROM enrichment.metadata_occupation_binding WHERE item_id=r.item_id;
 PERFORM enrichment.verify_item_input(r.item_id);
 IF decision NOT IN('ACCEPT','REJECT') OR kind NOT IN('human','assistant')
  OR nullif(btrim(reviewer),'') IS NULL OR nullif(btrim(notes),'') IS NULL
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REVIEW_PROVENANCE_REQUIRED'; END IF;
 IF reviewer=r.actor THEN RAISE EXCEPTION 'METADATA_OCCUPATION_INDEPENDENT_REVIEW_REQUIRED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=binding.job_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=binding.ncs_run_id)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REVIEW_SNAPSHOT_STALE'; END IF;
 SELECT * INTO old FROM enrichment.metadata_occupation_decision WHERE result_id=result ORDER BY decision_id DESC LIMIT 1;
 IF FOUND AND old.decision=decision AND old.reviewer=reviewer AND old.reviewer_kind=kind AND old.notes=notes
 THEN RETURN old.decision_id; END IF;
 INSERT INTO enrichment.metadata_occupation_decision(result_id,decision,reviewer,reviewer_kind,notes)
 VALUES(result,decision,reviewer,kind,notes) RETURNING decision_id INTO id;
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_status(jobs text,ncs text)
RETURNS TABLE(posting_id text,item_id text,result_id text,outcome text,decision text,matches jsonb)
LANGUAGE sql STABLE AS $$
 SELECT b.posting_id,b.item_id,r.result_id,
  CASE WHEN r.result_id IS NULL THEN 'PENDING'
   WHEN d.decision='REJECT' THEN 'REJECTED'
   WHEN d.decision IS NULL THEN 'REVIEW_PENDING'
   WHEN r.output->>'outcome'='abstained' THEN 'ABSTAINED' ELSE 'ACCEPTED_INFERRED_OCCUPATION' END,
  d.decision,coalesce(r.output->'matches','[]'::jsonb)
 FROM (SELECT DISTINCT ON(i.posting_id) i.posting_id,x.item_id FROM enrichment.metadata_occupation_binding x
  JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
  WHERE x.job_run_id=jobs AND x.ncs_run_id=ncs ORDER BY i.posting_id,b.created_at DESC,i.item_id DESC) b
 LEFT JOIN enrichment.metadata_occupation_result r USING(item_id)
 LEFT JOIN LATERAL (SELECT d.* FROM enrichment.metadata_occupation_decision d WHERE d.result_id=r.result_id
  ORDER BY decision_id DESC LIMIT 1) d ON true
$$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_graph_rows(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql STABLE AS $$
 SELECT s.posting_id,'source:posting:jobkorea:'||enrichment.hash(ib.manifest#>>'{document,source_record_id}'),
  'ncs:occupation:'||c.occupation_code,c.candidate_id,
  jsonb_build_object('result_id',r.result_id,'candidate_id',c.candidate_id,'occupation_code',c.occupation_code,
   'occupation_name',cat.occupation_name,'job_run_id',jobs,'ncs_run_id',ncs,
   'bundle_id',binding.bundle_id,'source_hash',binding.source_hash,'binding_hash',binding.binding_hash,
   'catalog_hash',cat.catalog_hash,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
   'item_id',i.item_id,'batch_id',i.batch_id,'attempt_id',r.attempt_id,
   'model',coalesce(a.actual_model,b.settings->>'categorize_model'),
   'prompt_version',b.settings->>'prompt_version','actor',r.actor,
   'confidence',NULL,'confidence_state','UNASSESSED','reason',c.reason,'evidence',c.evidence,
   'validation_status','VALIDATED','stage','STAGING','accepted',coalesce(d.decision='ACCEPT',false),
   'review_status',CASE WHEN d.decision='ACCEPT' AND d.reviewer_kind='human' THEN 'HUMAN_REVIEWED'
     WHEN d.decision='ACCEPT' THEN 'ASSISTANT_REVIEWED' ELSE 'UNREVIEWED' END,
   'decision_id',d.decision_id,'reviewer',d.reviewer,'reviewer_kind',d.reviewer_kind,'review_notes',d.notes)
 FROM enrichment.metadata_occupation_status(jobs,ncs) s
 JOIN enrichment.metadata_occupation_result r ON r.result_id=s.result_id
 JOIN enrichment.metadata_occupation_binding binding ON binding.item_id=s.item_id
 JOIN enrichment.item i ON i.item_id=binding.item_id
 JOIN enrichment.batch b ON b.batch_id=i.batch_id
 JOIN enrichment.attempt a ON a.attempt_id=r.attempt_id
 JOIN enrichment.input_bundle ib ON ib.bundle_id=binding.bundle_id
 JOIN enrichment.metadata_occupation_candidate c ON c.result_id=r.result_id
 JOIN enrichment.metadata_occupation_catalog cat ON cat.ncs_run_id=c.ncs_run_id AND cat.occupation_code=c.occupation_code
 LEFT JOIN LATERAL (SELECT d.* FROM enrichment.metadata_occupation_decision d WHERE d.result_id=r.result_id ORDER BY decision_id DESC LIMIT 1) d ON true
 WHERE r.output->>'outcome'='matched' AND d.decision IS DISTINCT FROM 'REJECT'
  AND (d.decision='ACCEPT' OR include_unreviewed)
  AND EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=jobs)
  AND EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=ncs)
$$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_review_packet(batch text)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','metadata-occupation-review-v1','batch_id',batch,'reviewer','','reviewer_kind','assistant',
  'rows',coalesce(jsonb_agg(jsonb_build_object('item_id',i.item_id,'posting_id',i.posting_id,'result_id',r.result_id,
   'source_fields',enrichment.metadata_occupation_fields(i.source_data),'bundle_id',binding.bundle_id,
   'job_run_id',binding.job_run_id,'ncs_run_id',binding.ncs_run_id,'binding_hash',binding.binding_hash,
   'candidates',binding.candidates,'output',r.output,'actor',r.actor,'decision',NULL,'notes','') ORDER BY i.ordinal),'[]'::jsonb))
 FROM enrichment.item i JOIN enrichment.metadata_occupation_binding binding USING(item_id)
 JOIN enrichment.metadata_occupation_result r USING(item_id) WHERE i.batch_id=batch
$$;

CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_graph_guard (
 writer_token text PRIMARY KEY,
 job_run_id text NOT NULL REFERENCES ingestion.run,
 ncs_run_id text NOT NULL REFERENCES ingestion.run,
 include_unreviewed boolean NOT NULL,
 rows_hash text NOT NULL,
 state text NOT NULL CHECK(state IN('PREPARED','READY','FAILED')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 completed_at timestamptz
);

CREATE OR REPLACE FUNCTION enrichment.guard_metadata_occupation_graph_history()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP<>'UPDATE' THEN RAISE EXCEPTION 'IMMUTABLE_METADATA_OCCUPATION_GRAPH_HISTORY'; END IF;
 IF NEW.writer_token IS DISTINCT FROM OLD.writer_token OR NEW.job_run_id IS DISTINCT FROM OLD.job_run_id
  OR NEW.ncs_run_id IS DISTINCT FROM OLD.ncs_run_id OR NEW.include_unreviewed IS DISTINCT FROM OLD.include_unreviewed
  OR NEW.rows_hash IS DISTINCT FROM OLD.rows_hash OR NEW.created_at IS DISTINCT FROM OLD.created_at
  OR OLD.state<>'PREPARED' OR NEW.state NOT IN('READY','FAILED') OR NEW.completed_at IS NULL
 THEN RAISE EXCEPTION 'IMMUTABLE_METADATA_OCCUPATION_GRAPH_SCOPE'; END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE name text; BEGIN
 IF to_regprocedure('retention.freeze_writes()') IS NOT NULL THEN
  FOREACH name IN ARRAY ARRAY['metadata_occupation_catalog','metadata_occupation_binding',
   'metadata_occupation_result','metadata_occupation_candidate','metadata_occupation_decision','metadata_occupation_graph_guard'] LOOP
   EXECUTE format('CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE ON enrichment.%I FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',name);
  END LOOP;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='immutable_metadata_occupation_graph_scope'
  AND tgrelid='enrichment.metadata_occupation_graph_guard'::regclass) THEN
  CREATE TRIGGER immutable_metadata_occupation_graph_scope BEFORE UPDATE OR DELETE
   ON enrichment.metadata_occupation_graph_guard FOR EACH ROW EXECUTE FUNCTION enrichment.guard_metadata_occupation_graph_history();
  CREATE TRIGGER immutable_metadata_occupation_graph_truncate BEFORE TRUNCATE
   ON enrichment.metadata_occupation_graph_guard FOR EACH STATEMENT EXECUTE FUNCTION enrichment.guard_metadata_occupation_graph_history();
 END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_graph_hash(jobs text,ncs text,include_unreviewed boolean)
RETURNS text LANGUAGE sql STABLE AS $$
 SELECT enrichment.hash(coalesce(jsonb_agg(jsonb_build_array(g.posting_id,g.posting_identity,
  g.occupation_identity,g.candidate_id,g.payload) ORDER BY g.candidate_id),'[]'::jsonb)::text)
 FROM enrichment.metadata_occupation_graph_rows(jobs,ncs,include_unreviewed) g
$$;

CREATE OR REPLACE FUNCTION enrichment.begin_metadata_occupation_graph(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE token text:=gen_random_uuid()::text; BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM retention.writer WHERE writer_id='metadata-occupation-graph')
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_ALREADY_ACTIVE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=jobs)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=ncs)
  OR NOT EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=jobs)
  OR NOT EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=ncs)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_REQUIRES_CURRENT_EXACT_SOURCE_GRAPHS'; END IF;
 PERFORM retention.enter_writer('metadata-occupation-graph','METADATA_OCCUPATION_GRAPH',token);
 INSERT INTO enrichment.metadata_occupation_graph_guard(writer_token,job_run_id,ncs_run_id,include_unreviewed,rows_hash,state)
 VALUES(token,jobs,ncs,include_unreviewed,enrichment.metadata_occupation_graph_hash(jobs,ncs,include_unreviewed),'PREPARED');
 RETURN token;
END $$;

CREATE OR REPLACE FUNCTION enrichment.check_metadata_occupation_graph(token text)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE guard enrichment.metadata_occupation_graph_guard%ROWTYPE; BEGIN
 SELECT * INTO STRICT guard FROM enrichment.metadata_occupation_graph_guard WHERE writer_token=token;
 IF guard.state<>'PREPARED' OR NOT EXISTS(SELECT 1 FROM retention.writer
   WHERE writer_id='metadata-occupation-graph' AND kind='METADATA_OCCUPATION_GRAPH' AND target_id=token)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_LEASE_MISMATCH'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=guard.job_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=guard.ncs_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=guard.job_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=guard.ncs_run_id)
  OR guard.rows_hash<>enrichment.metadata_occupation_graph_hash(guard.job_run_id,guard.ncs_run_id,guard.include_unreviewed)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_SOURCE_OR_REVIEW_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.finish_metadata_occupation_graph(token text,failed boolean DEFAULT false)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE guard enrichment.metadata_occupation_graph_guard%ROWTYPE; BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT guard FROM enrichment.metadata_occupation_graph_guard WHERE writer_token=token FOR UPDATE;
 IF guard.state IN('READY','FAILED') THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM retention.writer WHERE writer_id='metadata-occupation-graph'
  AND kind='METADATA_OCCUPATION_GRAPH' AND target_id=token)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_LEASE_MISMATCH'; END IF;
 IF NOT failed THEN PERFORM enrichment.check_metadata_occupation_graph(token); END IF;
 UPDATE enrichment.metadata_occupation_graph_guard SET state=CASE WHEN failed THEN 'FAILED' ELSE 'READY' END,
  completed_at=clock_timestamp() WHERE writer_token=token;
 DELETE FROM retention.writer WHERE writer_id='metadata-occupation-graph' AND kind='METADATA_OCCUPATION_GRAPH' AND target_id=token;
END $$;

COMMENT ON TABLE enrichment.metadata_occupation_candidate IS
 'Inferred listing-metadata classifications to NCS occupations. Never duty/competency coverage, applicant proficiency, source-explicit work, or calibrated confidence.';
COMMENT ON FUNCTION enrichment.metadata_occupation_fields(jsonb) IS
 'Exact local listing title/role/job_functions only; excludes employer labels, URLs, deadlines, eligibility and narrative. None becomes a work duty.';
COMMIT;
