-- Correct source classification_names without rewriting frozen pilot history.
-- Replay after 029/030 restores these wrappers; no function is renamed.
BEGIN;
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_catalog_context (
 ncs_run_id text NOT NULL,
 occupation_code text NOT NULL,
 classification_names jsonb NOT NULL CHECK(jsonb_typeof(classification_names)='array'),
 hierarchy_basis text NOT NULL CHECK(hierarchy_basis IN('SOURCE_CLASSIFICATION_NAMES','LEGACY_FLAT_SOURCE')),
 context_version text NOT NULL CHECK(context_version='ncs-occupation-context-v2'),
 source_catalog_hash text NOT NULL,
 context_hash text NOT NULL,
 catalog_context_hash text NOT NULL,
 PRIMARY KEY(ncs_run_id,occupation_code),
 FOREIGN KEY(ncs_run_id,occupation_code) REFERENCES enrichment.metadata_occupation_catalog,
 CHECK(jsonb_array_length(classification_names)=3)
);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='immutable_metadata_occupation_catalog_context'
  AND tgrelid='enrichment.metadata_occupation_catalog_context'::regclass) THEN
  CREATE TRIGGER immutable_metadata_occupation_catalog_context BEFORE UPDATE OR DELETE
   ON enrichment.metadata_occupation_catalog_context FOR EACH ROW
   EXECUTE FUNCTION enrichment.reject_metadata_occupation_change();
  CREATE TRIGGER immutable_truncate_metadata_occupation_catalog_context BEFORE TRUNCATE
   ON enrichment.metadata_occupation_catalog_context FOR EACH STATEMENT
   EXECUTE FUNCTION enrichment.reject_metadata_occupation_change();
 END IF;
 IF to_regprocedure('retention.freeze_writes()') IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM pg_trigger WHERE tgname='retention_write_guard'
   AND tgrelid='enrichment.metadata_occupation_catalog_context'::regclass) THEN
  CREATE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
   ON enrichment.metadata_occupation_catalog_context FOR EACH STATEMENT
   EXECUTE FUNCTION retention.freeze_writes();
 END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_source_classes(data jsonb,hierarchical boolean)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN
 IF NOT hierarchical THEN
  RETURN jsonb_build_array(data->>'classification_1',data->>'classification_2',data->>'classification_3');
 END IF;
 IF NOT data ? 'classification_names' OR jsonb_typeof(data->'classification_names') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_SOURCE_HIERARCHY_MISSING'; END IF;
 IF jsonb_array_length(data->'classification_names')<>3 OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(data->'classification_names') part
   WHERE jsonb_typeof(part) IS DISTINCT FROM 'string' OR nullif(btrim(part#>>'{}'),'') IS NULL)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_SOURCE_HIERARCHY_INVALID'; END IF;
 RETURN data->'classification_names';
END $$;

CREATE OR REPLACE FUNCTION enrichment.prepare_metadata_occupation_catalog_legacy(ncs text)
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

CREATE OR REPLACE FUNCTION enrichment.prepare_metadata_occupation_catalog(ncs text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE legacy jsonb; hierarchical boolean; count_context integer; context_manifest text; BEGIN
 -- The original source/unit/name ledger remains append-only and source-checked.
 legacy:=enrichment.prepare_metadata_occupation_catalog_legacy(ncs);
 SELECT coalesce(bool_or(normalized ? 'classification_names'),false) INTO hierarchical
 FROM ingestion.ready_record WHERE run_id=ncs AND source_id='ncs_competency';
 IF EXISTS(SELECT 1 FROM ingestion.ready_record WHERE run_id=ncs AND source_id='ncs_competency'
  GROUP BY normalized->>'occupation_code' HAVING count(DISTINCT
   enrichment.metadata_occupation_source_classes(normalized,hierarchical))<>1)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_SOURCE_HIERARCHY_INCONSISTENT'; END IF;
 WITH classes AS MATERIALIZED (
  SELECT normalized->>'occupation_code' AS occupation_code,
   min(enrichment.metadata_occupation_source_classes(normalized,hierarchical)::text)::jsonb AS names
  FROM ingestion.ready_record WHERE run_id=ncs AND source_id='ncs_competency'
  GROUP BY normalized->>'occupation_code'
 ), contexts AS MATERIALIZED (
  SELECT c.occupation_code,k.names,c.catalog_hash,
   enrichment.hash(jsonb_build_array('ncs-occupation-context-v2',c.catalog_hash,k.names)::text) AS hash
  FROM enrichment.metadata_occupation_catalog c JOIN classes k USING(occupation_code)
  WHERE c.ncs_run_id=ncs
 ), manifest AS (
  SELECT enrichment.hash(jsonb_agg(jsonb_build_array(occupation_code,hash) ORDER BY occupation_code)::text) AS hash
  FROM contexts
 ) INSERT INTO enrichment.metadata_occupation_catalog_context
 SELECT ncs,c.occupation_code,c.names,
  CASE WHEN hierarchical THEN 'SOURCE_CLASSIFICATION_NAMES' ELSE 'LEGACY_FLAT_SOURCE' END,
  'ncs-occupation-context-v2',c.catalog_hash,c.hash,m.hash FROM contexts c CROSS JOIN manifest m
 ON CONFLICT DO NOTHING;
 SELECT count(*),min(catalog_context_hash) INTO count_context,context_manifest
 FROM enrichment.metadata_occupation_catalog_context WHERE ncs_run_id=ncs;
 IF count_context<>(legacy->>'occupation_count')::integer OR EXISTS(
  WITH source_classes AS MATERIALIZED (
   SELECT normalized->>'occupation_code' AS occupation_code,
    min(enrichment.metadata_occupation_source_classes(normalized,hierarchical)::text)::jsonb AS names
   FROM ingestion.ready_record WHERE run_id=ncs AND source_id='ncs_competency'
   GROUP BY normalized->>'occupation_code'
  )
  SELECT 1 FROM enrichment.metadata_occupation_catalog_context k
  JOIN enrichment.metadata_occupation_catalog c USING(ncs_run_id,occupation_code)
  LEFT JOIN source_classes actual USING(occupation_code)
  WHERE k.ncs_run_id=ncs AND (k.source_catalog_hash<>c.catalog_hash OR k.context_hash<>
   enrichment.hash(jsonb_build_array('ncs-occupation-context-v2',c.catalog_hash,k.classification_names)::text)
   OR k.catalog_context_hash<>context_manifest
   OR k.classification_names IS DISTINCT FROM actual.names))
  OR context_manifest IS DISTINCT FROM (SELECT enrichment.hash(jsonb_agg(
   jsonb_build_array(occupation_code,context_hash) ORDER BY occupation_code)::text)
   FROM enrichment.metadata_occupation_catalog_context WHERE ncs_run_id=ncs)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CATALOG_CONTEXT_CHANGED'; END IF;
 RETURN legacy||jsonb_build_object('catalog_hash',context_manifest,'context_version','ncs-occupation-context-v2');
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_candidates(ncs text,source jsonb,cap integer DEFAULT 12)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE answer jsonb; BEGIN
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 30 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CANDIDATE_CAP_1_TO_30'; END IF;
 IF NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_catalog_context WHERE ncs_run_id=ncs)
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
  'occupation_name',c.occupation_name,'classification_names',k.classification_names,
  'unit_names',c.unit_names,'catalog_hash',k.context_hash,'retrieval_score',round(r.score,3)) ORDER BY r.score DESC,c.occupation_code),'[]')
 INTO answer FROM ranked r JOIN enrichment.metadata_occupation_catalog c USING(occupation_code)
 JOIN enrichment.metadata_occupation_catalog_context k ON k.ncs_run_id=c.ncs_run_id AND k.occupation_code=c.occupation_code
 WHERE c.ncs_run_id=ncs;
 RETURN answer;
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
 metadata:=enrichment.hash(enrichment.metadata_occupation_fields(i.source_data)::text);
 ch:=enrichment.hash(candidates::text);
 bh:=enrichment.hash(jsonb_build_array('metadata-occupation-binding-v1',b.job_run_id,b.ncs_run_id,bundle,i.source_hash,metadata,ch)::text);
 SELECT * INTO old FROM enrichment.metadata_occupation_binding WHERE item_id=id;
 IF FOUND THEN
  -- Existing items replay their original context exactly, including the five
  -- pre-correction paid results; never reinterpret them against the new view.
  IF old.candidates<>candidates THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CANDIDATE_CHANGED'; END IF;
  IF old.bundle_id<>bundle OR old.binding_hash<>bh OR old.source_hash<>i.source_hash
   OR old.metadata_hash<>metadata OR old.candidates_hash<>ch
  THEN RAISE EXCEPTION 'METADATA_OCCUPATION_BINDING_CHANGED'; END IF;
  RETURN jsonb_build_object('item_id',id,'bundle_id',bundle,'source_hash',i.source_hash,
   'metadata_hash',metadata,'candidates_hash',ch,'binding_hash',bh);
 END IF;
 IF NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_catalog_context
  WHERE ncs_run_id=b.ncs_run_id AND catalog_context_hash=b.ncs_hash)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_BATCH_CONTEXT_CHANGED'; END IF;
 FOR candidate IN SELECT value FROM jsonb_array_elements(candidates) LOOP
  SELECT jsonb_build_object('occupation_code',c.occupation_code,'occupation_name',c.occupation_name,
   'classification_names',k.classification_names,'unit_names',c.unit_names,'catalog_hash',k.context_hash)
  INTO expected FROM enrichment.metadata_occupation_catalog c
  JOIN enrichment.metadata_occupation_catalog_context k USING(ncs_run_id,occupation_code)
  WHERE c.ncs_run_id=b.ncs_run_id AND c.occupation_code=candidate->>'occupation_code';
  IF expected IS NULL OR candidate-'retrieval_score'<>expected
  THEN RAISE EXCEPTION 'METADATA_OCCUPATION_CANDIDATE_CHANGED'; END IF;
 END LOOP;
 INSERT INTO enrichment.metadata_occupation_binding(item_id,bundle_id,job_run_id,ncs_run_id,source_hash,metadata_hash,candidates,candidates_hash,binding_hash)
 VALUES(id,bundle,b.job_run_id,b.ncs_run_id,i.source_hash,metadata,candidates,ch,bh) ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('item_id',id,'bundle_id',bundle,'source_hash',i.source_hash,
  'metadata_hash',metadata,'candidates_hash',ch,'binding_hash',bh);
END $$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_graph_rows(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql STABLE AS $$
 SELECT s.posting_id,'source:posting:jobkorea:'||enrichment.hash(ib.manifest#>>'{document,source_record_id}'),
  'ncs:occupation:'||c.occupation_code,c.candidate_id,
  jsonb_build_object('result_id',r.result_id,'candidate_id',c.candidate_id,'occupation_code',c.occupation_code,
   'occupation_name',cat.occupation_name,'job_run_id',jobs,'ncs_run_id',ncs,
   'bundle_id',binding.bundle_id,'source_hash',binding.source_hash,'binding_hash',binding.binding_hash,
   'catalog_hash',(SELECT x->>'catalog_hash' FROM jsonb_array_elements(binding.candidates) x
    WHERE x->>'occupation_code'=c.occupation_code),'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
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

COMMIT;
