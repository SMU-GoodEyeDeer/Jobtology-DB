-- Explicit operator-approved JobKorea replacement; historical evidence stays immutable.
BEGIN;
-- Optional policy hooks remain private and bypass unrelated historical cohorts.
CREATE OR REPLACE FUNCTION catalog._replacement_policy_ready() RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ok boolean; BEGIN
 IF to_regprocedure('replacement_matching.ready()') IS NULL THEN RETURN false; END IF;
 EXECUTE 'SELECT replacement_matching.ready()' INTO ok; RETURN coalesce(ok,false);
END $$;
CREATE OR REPLACE FUNCTION catalog._replacement_policy_allowed(scheme text,aid text,scope_hint text)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ok boolean; BEGIN
 IF scope_hint NOT IN('jkr-20261103-onet','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f')
 THEN RETURN true; END IF;
 IF to_regprocedure('replacement_matching.allowed_core(text,text,text)') IS NULL THEN RETURN false; END IF;
 EXECUTE 'SELECT replacement_matching.allowed_core($1,$2,$3)' INTO ok USING scheme,aid,scope_hint;
 RETURN coalesce(ok,false);
END $$;
REVOKE ALL ON FUNCTION catalog._replacement_policy_ready(),catalog._replacement_policy_allowed(text,text,text) FROM PUBLIC;
CREATE TABLE IF NOT EXISTS ingestion.jobkorea_replacement (
 replacement_id text PRIMARY KEY CHECK(length(replacement_id) BETWEEN 1 AND 200),
 job_run_id text NOT NULL UNIQUE CHECK(length(job_run_id) BETWEEN 1 AND 200),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[0-9a-f]{64}$'),
 expected_count bigint NOT NULL CHECK(expected_count>0),
 ncs_run_id text NOT NULL, onet_task_id text NOT NULL UNIQUE,
 baseline_at timestamptz NOT NULL DEFAULT clock_timestamp(), previous_serving jsonb
);
CREATE TABLE IF NOT EXISTS ingestion.jobkorea_replacement_event (
 event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 replacement_id text NOT NULL REFERENCES ingestion.jobkorea_replacement,
 phase text NOT NULL CHECK(phase IN('PREPARED','BLOCKED','SERVING')),
 ncs_writer_token text, onet_publication_id text, graph_receipt jsonb,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(phase<>'SERVING' OR (ncs_writer_token IS NOT NULL AND onet_publication_id IS NOT NULL
  AND jsonb_typeof(graph_receipt)='object' AND graph_receipt->>'status'='VERIFIED'))
);
CREATE OR REPLACE FUNCTION ingestion._immutable_jobkorea_replacement() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_JOBKOREA_REPLACEMENT_HISTORY'; END $$;
CREATE OR REPLACE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON ingestion.jobkorea_replacement
 FOR EACH ROW EXECUTE FUNCTION ingestion._immutable_jobkorea_replacement();
CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON ingestion.jobkorea_replacement
 FOR EACH STATEMENT EXECUTE FUNCTION ingestion._immutable_jobkorea_replacement();
CREATE OR REPLACE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON ingestion.jobkorea_replacement_event
 FOR EACH ROW EXECUTE FUNCTION ingestion._immutable_jobkorea_replacement();
CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON ingestion.jobkorea_replacement_event
 FOR EACH STATEMENT EXECUTE FUNCTION ingestion._immutable_jobkorea_replacement();
CREATE OR REPLACE FUNCTION ingestion.jobkorea_replacement_current() RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT to_jsonb(p)||to_jsonb(e) FROM ingestion.jobkorea_replacement_event e
 JOIN ingestion.jobkorea_replacement p USING(replacement_id) ORDER BY e.event_id DESC LIMIT 1
$$;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_serving_run_allowed(jobs text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT CASE WHEN c IS NULL THEN true WHEN c->>'phase'='BLOCKED' THEN false
 WHEN c->>'phase'='SERVING' THEN jobs=c->>'job_run_id'
 WHEN jsonb_typeof(c->'previous_serving')='object' THEN jobs=c#>>'{previous_serving,job_run_id}'
 ELSE jobs<>c->>'job_run_id' AND EXISTS(SELECT 1 FROM ingestion.run r WHERE r.run_id=jobs
  AND r.created_at<=(c->>'baseline_at')::timestamptz) END
 FROM (SELECT ingestion.jobkorea_replacement_current() c) state
$$;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_ncs_publication_allowed(token text,jobs text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT CASE WHEN jobs='jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f' AND NOT catalog._replacement_policy_ready() THEN false
 WHEN c IS NULL THEN true WHEN c->>'phase'='BLOCKED' THEN false
 WHEN c->>'phase'='SERVING' THEN token=c->>'ncs_writer_token' AND jobs=c->>'job_run_id'
 WHEN jsonb_typeof(c->'previous_serving')='object' THEN token=c#>>'{previous_serving,ncs_writer_token}'
  AND jobs=c#>>'{previous_serving,job_run_id}'
 ELSE ingestion.jobkorea_serving_run_allowed(jobs) END
 FROM (SELECT ingestion.jobkorea_replacement_current() c) state
$$;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_onet_publication_allowed(publication text,task text,source text,jobs text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT source<>'jobkorea' OR CASE WHEN task='jkr-20261103-onet' AND NOT catalog._replacement_policy_ready() THEN false WHEN c IS NULL THEN true WHEN c->>'phase'='BLOCKED' THEN false
 WHEN c->>'phase'='SERVING' THEN publication=c->>'onet_publication_id' AND task=c->>'onet_task_id'
  AND jobs=c->>'job_run_id'
 WHEN jsonb_typeof(c->'previous_serving')='object' THEN publication=c#>>'{previous_serving,onet_publication_id}'
  AND task=c#>>'{previous_serving,onet_task_id}' AND jobs=c#>>'{previous_serving,job_run_id}'
 ELSE task<>c->>'onet_task_id' AND ingestion.jobkorea_serving_run_allowed(jobs) END
 FROM (SELECT ingestion.jobkorea_replacement_current() c) state
$$;
CREATE OR REPLACE FUNCTION ingestion.prepare_jobkorea_replacement(id text,jobs text,digest text,expected_rows bigint,ncs text,onet_task text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE c jsonb; busy boolean; BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('jobkorea-replacement',0));
 c:=ingestion.jobkorea_replacement_current();
 IF to_regclass('enrichment.metadata_occupation_graph_guard') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_graph_guard WHERE state=''PREPARED'')' INTO busy;
  IF busy THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_GRAPH_WRITER_BUSY'; END IF;
 END IF;
 IF to_regclass('onet_matching.graph_guard') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM onet_matching.graph_guard WHERE state=''PREPARED'')' INTO busy;
  IF busy THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_GRAPH_WRITER_BUSY'; END IF;
 END IF;
 IF to_regclass('retention.writer') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM retention.writer)' INTO busy;
  IF busy THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_GRAPH_WRITER_BUSY'; END IF;
 END IF;
 IF c IS NOT NULL AND c->>'phase'<>'SERVING' THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_ALREADY_PENDING'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=jobs AND state='READY')
 THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_PREPARE_BEFORE_READY'; END IF;
 INSERT INTO ingestion.jobkorea_replacement(replacement_id,job_run_id,input_sha256,expected_count,ncs_run_id,onet_task_id,previous_serving)
 VALUES(id,jobs,digest,expected_rows,ncs,onet_task,c);
 INSERT INTO ingestion.jobkorea_replacement_event(replacement_id,phase) VALUES(id,'PREPARED');
 RETURN ingestion.jobkorea_replacement_current();
END $$;
CREATE OR REPLACE FUNCTION ingestion.block_jobkorea_replacement(id text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE c jsonb; BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('jobkorea-replacement',0));
 c:=ingestion.jobkorea_replacement_current();
 IF c->>'replacement_id' IS DISTINCT FROM id OR c->>'phase' IS DISTINCT FROM 'PREPARED'
 THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_PHASE_MISMATCH'; END IF;
 INSERT INTO ingestion.jobkorea_replacement_event(replacement_id,phase) VALUES(id,'BLOCKED');
 RETURN ingestion.jobkorea_replacement_current();
END $$;
CREATE OR REPLACE FUNCTION ingestion.activate_jobkorea_replacement(id text,ncs_token text,onet_publication text,receipt jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE c jsonb; accepted bigint; ok boolean; BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('jobkorea-replacement',0));
 c:=ingestion.jobkorea_replacement_current();
 IF c->>'replacement_id' IS DISTINCT FROM id OR c->>'phase' IS DISTINCT FROM 'BLOCKED'
 THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_PHASE_MISMATCH'; END IF;
 SELECT count(*) INTO accepted FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
 JOIN ingestion.run u USING(run_id) WHERE r.run_id=c->>'job_run_id' AND u.source_id='jobkorea'
 AND u.state='READY' AND u.mode<>'SMOKE' AND d.selected AND r.normalized->>'kind'='JobPosting'
 AND r.normalized->>'representation'='local_listing' AND r.normalized->'metadata_accepted'='true'::jsonb;
 IF accepted<>(c->>'expected_count')::bigint THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_COUNT_MISMATCH'; END IF;
 EXECUTE 'SELECT EXISTS(SELECT 1 FROM ingestion.jobkorea_import WHERE run_id=$1 AND file_sha256=$2)'
 INTO ok USING c->>'job_run_id',c->>'input_sha256';
 IF NOT ok THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_INPUT_MISMATCH'; END IF;
 EXECUTE 'SELECT EXISTS(SELECT 1 FROM ingestion.source_graph_projection WHERE run_id=$1 AND state=''READY'')'
 INTO ok USING c->>'job_run_id';
 IF NOT ok THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_SOURCE_GRAPH_UNVERIFIED'; END IF;
 EXECUTE 'SELECT count(*)=$3 AND bool_and(outcome<>''PENDING'')
 FROM enrichment.metadata_occupation_status($1,$2)'
 INTO ok USING c->>'job_run_id',c->>'ncs_run_id',(c->>'expected_count')::bigint;
 IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_NCS_COHORT_UNSETTLED'; END IF;

 EXECUTE 'SELECT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_graph_guard WHERE writer_token=$1
 AND job_run_id=$2 AND ncs_run_id=$3 AND state=''READY'')'
 INTO ok USING ncs_token,c->>'job_run_id',c->>'ncs_run_id';
 IF NOT ok THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_NCS_PUBLICATION_MISMATCH'; END IF;
 EXECUTE 'SELECT EXISTS(SELECT 1 FROM onet_matching.graph_guard WHERE publication_id=$1 AND task_id=$2 AND state=''VERIFIED'')
 AND (SELECT count(*) FROM onet_matching.input WHERE task_id=$2)=$4
 AND NOT EXISTS(SELECT 1 FROM onet_matching.input WHERE task_id=$2 AND (source_id<>''jobkorea'' OR source_run_id<>$3))'
 INTO ok USING onet_publication,c->>'onet_task_id',c->>'job_run_id',(c->>'expected_count')::bigint;
 IF NOT ok THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_ONET_PUBLICATION_MISMATCH'; END IF;
 EXECUTE 'SELECT count(*)=$2 AND bool_and(state IN(''VALIDATED'',''SKIPPED'',''REJECTED'',''ERROR''))
 AND bool_and(reserved_at IS NULL OR cost_usd IS NOT NULL) FROM onet_matching.attempt WHERE task_id=$1'
 INTO ok USING c->>'onet_task_id',(c->>'expected_count')::bigint;
 IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_ONET_COHORT_UNSETTLED'; END IF;

 IF receipt->>'status' IS DISTINCT FROM 'VERIFIED' OR receipt->>'job_run_id' IS DISTINCT FROM c->>'job_run_id'
 OR receipt->>'replacement_id' IS DISTINCT FROM id
 THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_GRAPH_RECEIPT_MISMATCH'; END IF;
 INSERT INTO ingestion.jobkorea_replacement_event(replacement_id,phase,ncs_writer_token,onet_publication_id,graph_receipt)
 VALUES(id,'SERVING',ncs_token,onet_publication,receipt);
 RETURN ingestion.jobkorea_replacement_current();
END $$;

CREATE OR REPLACE FUNCTION catalog._live_source_observations()
RETURNS TABLE(source_id text,priority integer,posting_id text,run_id text,
 data_as_of timestamptz,normalized jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH latest AS MATERIALIZED (
  SELECT source_id,run_id,completed_at FROM ingestion.latest_ready_run
  WHERE source_id IN ('jobkorea','job_alio','nara_job')
 ), jk AS (
  SELECT DISTINCT ON (r.normalized->>'posting_id')
   'jobkorea'::text AS source_id,0 AS priority,
   'jobkorea:'||(r.normalized->>'posting_id') AS posting_id,
   r.run_id,u.completed_at AS data_as_of,r.normalized
  FROM ingestion.run u JOIN ingestion.record r USING(run_id)
  JOIN ingestion.document d USING(run_id,document_id)
  WHERE u.source_id='jobkorea' AND u.state='READY' AND u.mode<>'SMOKE'
   AND ingestion.jobkorea_serving_run_allowed(u.run_id)
   AND d.selected AND r.normalized->>'kind'='JobPosting'
   AND r.normalized->>'representation'='local_listing'
   AND r.normalized->'metadata_accepted'='true'::jsonb
   AND nullif(r.normalized->>'posting_id','') IS NOT NULL
  ORDER BY r.normalized->>'posting_id',u.created_at DESC,u.run_id DESC,r.record_id DESC
 ), nara_rows AS MATERIALIZED (
  SELECT r.* FROM latest u JOIN ingestion.record r USING(run_id)
  JOIN ingestion.document d USING(run_id,document_id)
  WHERE u.source_id='nara_job' AND d.selected AND r.normalized->>'kind'='JobPosting'
 ), nara AS (
  SELECT r.run_id,r.normalized->>'posting_id' AS native,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='list'))->0 AS l,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='detail'))->0 AS d,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='positions'))->0 AS p,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='files'))->0 AS f
  FROM nara_rows r GROUP BY r.run_id,r.normalized->>'posting_id'
 )
 SELECT * FROM jk
 UNION ALL
 SELECT u.source_id,1,p.posting_id,u.run_id,u.completed_at,p.normalized
 FROM latest u CROSS JOIN LATERAL catalog._live_job_postings(u.run_id) p
 WHERE u.source_id='job_alio'
 UNION ALL
 SELECT u.source_id,2,'nara_job:'||p.native,u.run_id,u.completed_at,
  (p.l||jsonb_strip_nulls(p.d)||jsonb_strip_nulls(p.p)||jsonb_strip_nulls(p.f))-'representation'
 FROM latest u JOIN nara p USING(run_id)
 WHERE u.source_id='nara_job' AND p.l IS NOT NULL AND p.d IS NOT NULL
  AND p.p IS NOT NULL AND p.f IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION catalog._live_source_observations(posting_choices text[])
RETURNS TABLE(source_id text,priority integer,posting_id text,run_id text,
 data_as_of timestamptz,normalized jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH choices AS MATERIALIZED (
  SELECT CASE WHEN starts_with(choice,'jobkorea:') THEN 'jobkorea'
   WHEN starts_with(choice,'nara_job:') THEN 'nara_job' ELSE 'job_alio' END AS source_id,
   CASE WHEN starts_with(choice,'jobkorea:') THEN substr(choice,length('jobkorea:')+1)
    WHEN starts_with(choice,'nara_job:') THEN substr(choice,length('nara_job:')+1) ELSE choice END AS native_id
  FROM unnest(posting_choices) choice
 ), latest AS MATERIALIZED (
  SELECT source_id,run_id,completed_at FROM ingestion.latest_ready_run
  WHERE source_id IN ('jobkorea','job_alio','nara_job')
   AND (posting_choices IS NULL OR source_id IN(SELECT source_id FROM choices))
 ), jk AS (
  SELECT DISTINCT ON (r.normalized->>'posting_id')
   'jobkorea'::text AS source_id,0 AS priority,
   'jobkorea:'||(r.normalized->>'posting_id') AS posting_id,
   r.run_id,u.completed_at AS data_as_of,r.normalized
  FROM ingestion.run u JOIN ingestion.record r USING(run_id)
  JOIN ingestion.document d USING(run_id,document_id)
  WHERE u.source_id='jobkorea' AND u.state='READY' AND u.mode<>'SMOKE'
   AND ingestion.jobkorea_serving_run_allowed(u.run_id)
   AND (posting_choices IS NULL OR EXISTS(SELECT 1 FROM choices WHERE source_id='jobkorea'))
   AND (posting_choices IS NULL OR r.normalized->>'posting_id' IN(SELECT native_id FROM choices WHERE source_id='jobkorea'))
   AND d.selected AND r.normalized->>'kind'='JobPosting'
   AND r.normalized->>'representation'='local_listing'
   AND r.normalized->'metadata_accepted'='true'::jsonb
   AND nullif(r.normalized->>'posting_id','') IS NOT NULL
  ORDER BY r.normalized->>'posting_id',u.created_at DESC,u.run_id DESC,r.record_id DESC
 ), nara_rows AS MATERIALIZED (
  SELECT r.* FROM latest u JOIN ingestion.record r USING(run_id)
  JOIN ingestion.document d USING(run_id,document_id)
  WHERE u.source_id='nara_job' AND d.selected AND r.normalized->>'kind'='JobPosting'
   AND (posting_choices IS NULL OR r.normalized->>'posting_id' IN(SELECT native_id FROM choices WHERE source_id='nara_job'))
 ), nara AS (
  SELECT r.run_id,r.normalized->>'posting_id' AS native,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='list'))->0 AS l,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='detail'))->0 AS d,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='positions'))->0 AS p,
   (jsonb_agg(r.normalized ORDER BY r.record_id) FILTER (WHERE r.normalized->>'representation'='files'))->0 AS f
  FROM nara_rows r GROUP BY r.run_id,r.normalized->>'posting_id'
 )
 SELECT * FROM jk
 UNION ALL
 SELECT u.source_id,1,p.posting_id,u.run_id,u.completed_at,p.normalized
 FROM latest u CROSS JOIN LATERAL catalog._live_job_postings(u.run_id) p
 WHERE u.source_id='job_alio'
  AND (posting_choices IS NULL OR p.posting_id IN(SELECT native_id FROM choices WHERE source_id='job_alio'))
 UNION ALL
 SELECT u.source_id,2,'nara_job:'||p.native,u.run_id,u.completed_at,
  (p.l||jsonb_strip_nulls(p.d)||jsonb_strip_nulls(p.p)||jsonb_strip_nulls(p.f))-'representation'
 FROM latest u JOIN nara p USING(run_id)
 WHERE u.source_id='nara_job' AND p.l IS NOT NULL AND p.d IS NOT NULL
  AND p.p IS NOT NULL AND p.f IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION catalog._inferred_occupation_rows(occupation_codes text[],posting_choices text[])
RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,
 occupation_scheme text,occupation_code text,occupation_name text,association_id text,
 review_status text,stage text,confidence_state text,source_hash text,
 normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,
 catalog_freshness text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF (occupation_codes IS NOT NULL AND cardinality(occupation_codes)=0)
  OR (posting_choices IS NOT NULL AND cardinality(posting_choices)=0) THEN RETURN; END IF;
 IF (occupation_codes IS NULL OR EXISTS(SELECT 1 FROM unnest(occupation_codes) code WHERE code ~ '^[0-9]{8}$'))
  AND to_regprocedure('enrichment.metadata_occupation_graph_rows(text,text,boolean)') IS NOT NULL THEN
  IF to_regclass('enrichment.metadata_occupation_candidate_decision') IS NOT NULL THEN
   RETURN QUERY EXECUTE $ncs_bounded$
    WITH publications AS MATERIALIZED (
     SELECT DISTINCT ON(g.job_run_id,g.ncs_run_id) g.*
     FROM enrichment.metadata_occupation_graph_guard g
     WHERE g.state='READY' AND ingestion.jobkorea_ncs_publication_allowed(g.writer_token,g.job_run_id)
      AND EXISTS(SELECT 1 FROM ingestion.run r WHERE r.run_id=g.job_run_id AND r.source_id='jobkorea' AND r.state='READY')
      AND EXISTS(SELECT 1 FROM ingestion.run r WHERE r.run_id=g.ncs_run_id AND r.source_id='ncs_competency' AND r.state='READY')
     ORDER BY g.job_run_id,g.ncs_run_id,g.completed_at DESC,g.writer_token DESC
    ), captured AS MATERIALIZED (
     SELECT DISTINCT ON(p.job_run_id,p.ncs_run_id,i.posting_id)
      p.job_run_id,p.ncs_run_id,p.completed_at,p.include_unreviewed,
      i.posting_id,x.bundle_id,x.source_hash,ib.manifest,r.result_id,r.output,r.attempt_id,
      b.settings->>'prompt_version' AS prompt_version
     FROM publications p JOIN enrichment.metadata_occupation_binding x
      ON x.job_run_id=p.job_run_id AND x.ncs_run_id=p.ncs_run_id
     JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
     JOIN enrichment.metadata_occupation_result r ON r.item_id=x.item_id
     JOIN enrichment.input_bundle ib ON ib.bundle_id=x.bundle_id
     WHERE $2 IS NULL OR 'jobkorea:'||(ib.manifest#>>'{document,source_record_id}')=ANY($2)
     ORDER BY p.job_run_id,p.ncs_run_id,i.posting_id,b.created_at DESC,i.item_id DESC
    ), selected AS (
     SELECT s.*,c.candidate_id,c.occupation_code,cat.occupation_name,cat.catalog_hash,
      CASE WHEN s.prompt_version='ko-metadata-occupation-v3' THEN d3.decision ELSE d1.decision END AS decision,
      CASE WHEN s.prompt_version='ko-metadata-occupation-v3' THEN d3.reviewer_kind ELSE d1.reviewer_kind END AS reviewer_kind
     FROM captured s JOIN enrichment.metadata_occupation_candidate c USING(result_id)
     JOIN enrichment.metadata_occupation_catalog cat ON cat.ncs_run_id=c.ncs_run_id AND cat.occupation_code=c.occupation_code
     LEFT JOIN LATERAL (SELECT d.* FROM enrichment.metadata_occupation_decision d
      WHERE d.result_id=s.result_id AND s.prompt_version<>'ko-metadata-occupation-v3' ORDER BY decision_id DESC LIMIT 1) d1 ON true
     LEFT JOIN LATERAL (SELECT d.* FROM enrichment.metadata_occupation_candidate_decision d
      WHERE d.candidate_id=c.candidate_id AND s.prompt_version='ko-metadata-occupation-v3' ORDER BY decision_id DESC LIMIT 1) d3 ON true
     WHERE (s.job_run_id<>'jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f' OR ((SELECT catalog._replacement_policy_ready()) AND catalog._replacement_policy_allowed('NCS',s.attempt_id,s.job_run_id))) AND s.output->>'outcome'='matched' AND ($1 IS NULL OR c.occupation_code=ANY($1))
      AND s.prompt_version IS NOT NULL
      AND (s.prompt_version<>'ko-metadata-occupation-v3' OR EXISTS(SELECT 1 FROM jsonb_array_elements(s.output->'matches') m
       WHERE m->>'occupation_code'=c.occupation_code))
    )
    SELECT DISTINCT ON(s.manifest#>>'{document,source_record_id}',s.occupation_code)
     'jobkorea:'||(s.manifest#>>'{document,source_record_id}'),
     'source:posting:jobkorea:'||enrichment.hash(s.manifest#>>'{document,source_record_id}'),
     'jobkorea'::text,s.job_run_id,'NCS'::text,s.occupation_code,s.occupation_name,s.candidate_id,
     CASE WHEN s.decision='ACCEPT' AND s.reviewer_kind='human' THEN 'HUMAN_REVIEWED'
      WHEN s.decision='ACCEPT' THEN 'ASSISTANT_REVIEWED' ELSE 'UNREVIEWED' END,
     'STAGING'::text,'UNASSESSED'::text,s.source_hash,s.manifest#>>'{document,normalized_hash}',NULL::text,
     s.ncs_run_id,s.catalog_hash,
     CASE WHEN current.run_id=s.ncs_run_id OR catalog._ncs_catalog_revalidation(s.ncs_run_id,s.occupation_code,s.catalog_hash) IS NOT NULL
      THEN 'CURRENT' ELSE 'STALE' END
    FROM selected s LEFT JOIN ingestion.latest_ready_run current ON current.source_id='ncs_competency'
    WHERE s.decision IS DISTINCT FROM 'REJECT' AND (s.decision='ACCEPT' OR s.include_unreviewed)
    ORDER BY s.manifest#>>'{document,source_record_id}',s.occupation_code,s.completed_at DESC,s.candidate_id DESC
   $ncs_bounded$ USING occupation_codes,posting_choices;
  ELSE
   -- Compatibility with installations predating explicit candidate review v3.
   RETURN QUERY EXECUTE $ncs_legacy$
    WITH publications AS (
     SELECT DISTINCT ON(job_run_id,ncs_run_id) * FROM enrichment.metadata_occupation_graph_guard
     WHERE state='READY' AND ingestion.jobkorea_ncs_publication_allowed(writer_token,job_run_id) ORDER BY job_run_id,ncs_run_id,completed_at DESC,writer_token DESC
    )
    SELECT DISTINCT ON(b.manifest#>>'{document,source_record_id}',r.payload->>'occupation_code')
     'jobkorea:'||(b.manifest#>>'{document,source_record_id}'),r.posting_identity,'jobkorea'::text,p.job_run_id,
     'NCS'::text,r.payload->>'occupation_code',r.payload->>'occupation_name',r.candidate_id,
     r.payload->>'review_status',r.payload->>'stage',r.payload->>'confidence_state',r.payload->>'source_hash',
     b.manifest#>>'{document,normalized_hash}',NULL::text,p.ncs_run_id,r.payload->>'catalog_hash',
     CASE WHEN n.run_id=p.ncs_run_id OR catalog._ncs_catalog_revalidation(p.ncs_run_id,r.payload->>'occupation_code',r.payload->>'catalog_hash') IS NOT NULL
      THEN 'CURRENT' ELSE 'STALE' END
    FROM publications p CROSS JOIN LATERAL enrichment.metadata_occupation_graph_rows(p.job_run_id,p.ncs_run_id,p.include_unreviewed) r
    JOIN enrichment.input_bundle b ON b.bundle_id=r.payload->>'bundle_id'
    LEFT JOIN ingestion.latest_ready_run n ON n.source_id='ncs_competency'
    WHERE ($1 IS NULL OR r.payload->>'occupation_code'=ANY($1))
     AND ($2 IS NULL OR 'jobkorea:'||(b.manifest#>>'{document,source_record_id}')=ANY($2))
    ORDER BY b.manifest#>>'{document,source_record_id}',r.payload->>'occupation_code',p.completed_at DESC,r.candidate_id DESC
   $ncs_legacy$ USING occupation_codes,posting_choices;
  END IF;
 END IF;
 IF (occupation_codes IS NULL OR EXISTS(SELECT 1 FROM unnest(occupation_codes) code
  WHERE code ~ '^[0-9]{2}-[0-9]{4}\.[0-9]{2}$')) AND to_regclass('onet_matching.graph_edge') IS NOT NULL THEN
  RETURN QUERY EXECUTE $onet_bounded$
   WITH inputs AS MATERIALIZED (
    SELECT i.task_id,i.posting_identity,i.source_id,i.source_run_id,
     CASE WHEN i.source_id='job_alio' THEN i.source_facts->>'posting_id'
      ELSE i.source_id||':'||(i.source_facts->>'posting_id') END AS posting_key
    FROM onet_matching.input i WHERE $2 IS NULL OR CASE WHEN i.source_id='job_alio' THEN i.source_facts->>'posting_id'
     ELSE i.source_id||':'||(i.source_facts->>'posting_id') END=ANY($2)
   ), edges AS MATERIALIZED (
    SELECT DISTINCT ON(e.edge_id) e.edge_id,e.posting_identity,e.occupation_identity,g.database_id,
     e.properties->>'occupation_code' AS occupation_code,e.properties->>'review_status' AS review_status,
     e.properties->>'stage' AS stage,e.properties->>'confidence_state' AS confidence_state,
     e.properties->>'source_facts_sha256' AS source_facts_sha256,e.properties->>'release_id' AS release_id,
     e.properties->>'catalog_hash' AS catalog_hash,e.properties->>'occupation_content_hash' AS occupation_content_hash,
     coalesce(e.properties->>'task_id',e.payload_json::jsonb->>'task_id') AS task_id,
     coalesce(e.properties->>'occupation_name',e.payload_json::jsonb->>'occupation_name') AS occupation_name
    FROM onet_matching.graph_edge e JOIN onet_matching.graph_guard g USING(publication_id)
    WHERE g.state='VERIFIED' AND (g.task_id<>'jkr-20261103-onet' OR ((SELECT catalog._replacement_policy_ready()) AND catalog._replacement_policy_allowed('ONET',coalesce(e.properties->>'attempt_id',e.payload_json::jsonb->>'attempt_id'),g.task_id))) AND EXISTS(SELECT 1 FROM onet_matching.input pin WHERE pin.task_id=g.task_id
      AND pin.posting_identity=e.posting_identity AND ingestion.jobkorea_onet_publication_allowed(g.publication_id,g.task_id,pin.source_id,pin.source_run_id)) AND ($1 IS NULL OR e.properties->>'occupation_code'=ANY($1))
     AND ($2 IS NULL OR EXISTS(SELECT 1 FROM inputs i WHERE i.posting_identity=e.posting_identity))
    ORDER BY e.edge_id,g.finished_at DESC,e.publication_id DESC
   )
   SELECT i.posting_key,e.posting_identity,i.source_id,i.source_run_id,'ONET'::text,
    e.occupation_code,e.occupation_name,e.edge_id,e.review_status,e.stage,e.confidence_state,NULL::text,NULL::text,
    e.source_facts_sha256,e.release_id,e.catalog_hash,
    CASE WHEN current.release_id IS NULL THEN 'STALE'
     WHEN node.content_hash=e.occupation_content_hash THEN 'CURRENT' ELSE 'STALE' END
   FROM edges e JOIN inputs i ON i.task_id=e.task_id AND i.posting_identity=e.posting_identity
   LEFT JOIN classification.catalog_current current ON current.database_id=e.database_id AND current.release_id=e.release_id
   LEFT JOIN classification.graph_load_node node ON node.load_id=current.load_id AND node.node_id=e.occupation_identity
  $onet_bounded$ USING occupation_codes,posting_choices;
 END IF;
END $$;

-- Public source metadata follows the same serving fence as its posting rows.
CREATE OR REPLACE FUNCTION catalog._jobkorea_fenced_source_runs()
RETURNS TABLE(source_id text,run_id text,completed_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT source_id,run_id,completed_at FROM ingestion.latest_ready_run WHERE source_id<>'jobkorea'
 UNION ALL
 SELECT source_id,run_id,completed_at FROM (
  SELECT source_id,run_id,completed_at FROM ingestion.run
  WHERE source_id='jobkorea' AND state='READY' AND mode<>'SMOKE'
   AND ingestion.jobkorea_serving_run_allowed(run_id)
  ORDER BY created_at DESC,run_id DESC LIMIT 1
 ) jobkorea
$$;

CREATE OR REPLACE FUNCTION catalog.live_postings_v1(
 search text DEFAULT NULL,ncs_category text DEFAULT NULL,region text DEFAULT NULL,
 open_on date DEFAULT NULL,page_size integer DEFAULT 20,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE q text:=nullif(btrim(search),'');
 category text:=nullif(btrim(ncs_category),''); area text:=nullif(btrim(region),'');
 source_items jsonb; total_count bigint; result_items jsonb;
BEGIN
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_LIVE_PAGE'; END IF;
 IF length(q)>100 OR length(category)>200 THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 WITH observations AS MATERIALIZED (SELECT * FROM catalog._live_source_observations()),
 source_filtered AS MATERIALIZED (
  SELECT p.*,coalesce(catalog._live_date(coalesce(p.normalized->>'deadline_date',p.normalized->>'closing_date')),
   (catalog._live_instant(p.normalized->>'deadline_at') AT TIME ZONE 'Asia/Seoul')::date::text) AS closing
  FROM observations p WHERE
   (q IS NULL OR strpos(lower(coalesce(p.normalized->>'title','')),lower(q))>0
    OR strpos(lower(coalesce(p.normalized->>'organization_name','')),lower(q))>0)
   AND (area IS NULL OR catalog._live_parts(p.normalized->>'regions') ? area)
   AND (open_on IS NULL OR catalog._live_posting_open(
    CASE WHEN p.source_id='jobkorea' THEN p.normalized ELSE
     p.normalized||jsonb_build_object('application_start_date',p.normalized->>'date_posted') END,open_on))
 ), current_inferred AS MATERIALIZED (
  SELECT a.posting_key,a.source_id FROM catalog._live_occupation_associations(
   ARRAY(SELECT p.posting_id FROM source_filtered p),catalog._live_ncs_filter_codes(category)) a
  WHERE a.occupation_scheme='NCS' AND starts_with(a.occupation_code,category)
   AND a.source_freshness='CURRENT' AND a.catalog_freshness='CURRENT'
 ), matching AS MATERIALIZED (
  SELECT p.* FROM source_filtered p WHERE category IS NULL
   OR EXISTS (SELECT 1 FROM jsonb_array_elements(
    catalog._live_categories(p.normalized->>'ncs_category_codes',p.normalized->>'ncs_category_names')) cat
    WHERE CASE WHEN category ~ '^[0-9]{1,8}$' THEN starts_with(cat->>'code',category)
     ELSE lower(cat->>'code')=lower(category) OR cat->>'name'=category END)
   OR EXISTS (SELECT 1 FROM current_inferred a WHERE a.source_id=p.source_id AND a.posting_key=p.posting_id)
 ), page AS (
  SELECT * FROM matching ORDER BY priority,closing::date ASC NULLS LAST,posting_id COLLATE "C" ASC
  LIMIT page_size OFFSET page_offset
 )
 SELECT (SELECT jsonb_agg(jsonb_build_object('source_id',source_id,'run_id',run_id,
   'data_as_of',completed_at) ORDER BY CASE source_id WHEN 'jobkorea' THEN 0 WHEN 'job_alio' THEN 1 ELSE 2 END)
   FROM catalog._jobkorea_fenced_source_runs() WHERE source_id IN ('jobkorea','job_alio','nara_job')),
  (SELECT count(*) FROM matching),
  (SELECT coalesce(jsonb_agg(catalog._live_source_posting_item(normalized,posting_id,source_id,run_id,data_as_of)
   ORDER BY priority,closing::date ASC NULLS LAST,posting_id COLLATE "C" ASC),'[]'::jsonb) FROM page)
 INTO source_items,total_count,result_items;
 IF source_items IS NULL THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 -- Enrichment is batched over the selected page, never one adapter scan per item.
 WITH associations AS MATERIALIZED (
  SELECT a.source_id,a.posting_key,jsonb_agg(a.association
   ORDER BY a.occupation_scheme COLLATE "C",a.occupation_code COLLATE "C",a.association->>'association_id') AS items
  FROM catalog._live_occupation_associations(
   ARRAY(SELECT value->>'posting_id' FROM jsonb_array_elements(result_items)),NULL) a
  GROUP BY a.source_id,a.posting_key
 ) SELECT coalesce(jsonb_agg(p.value||jsonb_build_object('occupation_associations',coalesce(a.items,'[]'::jsonb))
  ORDER BY p.ordinality),'[]'::jsonb) INTO result_items
 FROM jsonb_array_elements(result_items) WITH ORDINALITY p
 LEFT JOIN associations a ON a.source_id=p.value->>'source_id' AND a.posting_key=p.value->>'posting_id';
 RETURN jsonb_build_object('contract_version','hop-live-source-v1','sources',source_items,
  'filters',jsonb_build_object('q',q,'ncs_category',category,'region',area,'open_on',open_on,
   'ncs_match_scope','SOURCE_OR_CURRENT_INFERRED'),
  'limit',page_size,'offset',page_offset,'total',total_count,'items',result_items);
END $$;

CREATE OR REPLACE FUNCTION catalog.live_posting_v1(posting_choice text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE chosen text:=nullif(btrim(posting_choice),''); chosen_source text; item jsonb; source_items jsonb;
 associations jsonb;
BEGIN
 IF chosen IS NULL THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 chosen_source:=CASE WHEN starts_with(chosen,'jobkorea:') THEN 'jobkorea'
  WHEN starts_with(chosen,'nara_job:') THEN 'nara_job' ELSE 'job_alio' END;
 IF strpos(chosen,':')>0 AND chosen_source='job_alio' THEN RAISE EXCEPTION 'LIVE_POSTING_NOT_FOUND'; END IF;
 SELECT jsonb_build_array(jsonb_build_object('source_id',source_id,'run_id',run_id,'data_as_of',completed_at))
 INTO source_items FROM catalog._jobkorea_fenced_source_runs() WHERE source_id=chosen_source;
 IF source_items IS NULL THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 SELECT catalog._live_source_posting_item(p.normalized,p.posting_id,p.source_id,p.run_id,p.data_as_of),
  jsonb_build_array(jsonb_build_object('source_id',p.source_id,'run_id',p.run_id,'data_as_of',p.data_as_of))
 INTO item,source_items
 FROM catalog._live_source_observations() p WHERE p.source_id=chosen_source AND p.posting_id=chosen;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_POSTING_NOT_FOUND'; END IF;
 SELECT coalesce(jsonb_agg(a.association ORDER BY a.occupation_scheme COLLATE "C",
  a.occupation_code COLLATE "C",a.association->>'association_id'),'[]'::jsonb) INTO associations
 FROM catalog._live_occupation_associations(ARRAY[chosen],NULL) a WHERE a.source_id=chosen_source;
 RETURN jsonb_build_object('contract_version','hop-live-source-v1','sources',source_items,
  'item',item||jsonb_build_object('occupation_associations',associations));
END $$;

-- Reject replay of a retired JobKorea pin before any new graph writer is admitted.
CREATE OR REPLACE FUNCTION ingestion._jobkorea_ncs_graph_fence() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE c jsonb; BEGIN
 c:=ingestion.jobkorea_replacement_current();
 IF c IS NOT NULL AND NEW.state<>'FAILED' AND NEW.job_run_id IS DISTINCT FROM c->>'job_run_id'
 THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_RETIRED_GRAPH_PIN'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION ingestion._jobkorea_onet_graph_fence() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE c jsonb; bad boolean; BEGIN
 c:=ingestion.jobkorea_replacement_current();
 IF c IS NOT NULL AND NEW.state<>'FAILED' THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM onet_matching.input WHERE task_id=$1 AND source_id=''jobkorea''
   AND (source_run_id IS DISTINCT FROM $2 OR task_id IS DISTINCT FROM $3))'
   INTO bad USING NEW.task_id,c->>'job_run_id',c->>'onet_task_id';
  IF bad THEN RAISE EXCEPTION 'JOBKOREA_REPLACEMENT_RETIRED_GRAPH_PIN'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION ingestion.install_jobkorea_publication_fences() RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF to_regclass('enrichment.metadata_occupation_graph_guard') IS NOT NULL THEN
  EXECUTE 'CREATE OR REPLACE TRIGGER jobkorea_replacement_fence BEFORE INSERT OR UPDATE
   ON enrichment.metadata_occupation_graph_guard FOR EACH ROW EXECUTE FUNCTION ingestion._jobkorea_ncs_graph_fence()';
 END IF;
 IF to_regclass('onet_matching.graph_guard') IS NOT NULL THEN
  EXECUTE 'CREATE OR REPLACE TRIGGER jobkorea_replacement_fence BEFORE INSERT OR UPDATE
   ON onet_matching.graph_guard FOR EACH ROW EXECUTE FUNCTION ingestion._jobkorea_onet_graph_fence()';
 END IF;
END $$;
SELECT ingestion.install_jobkorea_publication_fences();
REVOKE ALL ON FUNCTION ingestion._jobkorea_ncs_graph_fence(),ingestion._jobkorea_onet_graph_fence(),
 ingestion.install_jobkorea_publication_fences() FROM PUBLIC;

REVOKE ALL ON ingestion.jobkorea_replacement,ingestion.jobkorea_replacement_event FROM PUBLIC;
REVOKE ALL ON FUNCTION ingestion._immutable_jobkorea_replacement(),ingestion.jobkorea_replacement_current(),
 ingestion.jobkorea_serving_run_allowed(text),ingestion.jobkorea_ncs_publication_allowed(text,text),
 ingestion.jobkorea_onet_publication_allowed(text,text,text,text),
 ingestion.prepare_jobkorea_replacement(text,text,text,bigint,text,text),
 ingestion.block_jobkorea_replacement(text),ingestion.activate_jobkorea_replacement(text,text,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION catalog._jobkorea_fenced_source_runs(),catalog._live_source_observations(),catalog._live_source_observations(text[]),
 catalog._inferred_occupation_rows(text[],text[]),
 catalog.live_postings_v1(text,text,text,date,integer,integer),catalog.live_posting_v1(text) FROM PUBLIC;
COMMIT;
