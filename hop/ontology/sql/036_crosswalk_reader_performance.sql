BEGIN;

-- SQL034 allowed the planner to push endpoint-existence predicates below the
-- pair aggregate, resolving the same catalogue once per posting. Materialize
-- grouped pairs and distinct pinned endpoints before applying those predicates.
-- Push the wanted native IDs before latest-observation selection/aggregation,
-- skipping unrelated sources. The established no-argument projection is unchanged.
-- No catalogue pins, audit/review states, source facts or persisted rows change.
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

CREATE OR REPLACE FUNCTION catalog._ncs_onet_shared_posting_proposals(node_id text)
RETURNS SETOF jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH scope AS (
  SELECT CASE WHEN node_id LIKE 'ncs:occupation:%' THEN substr(node_id,length('ncs:occupation:')+1)
   WHEN node_id LIKE 'urn:jobtology:onet:occupation:%' THEN substr(node_id,length('urn:jobtology:onet:occupation:')+1) END AS code
 ), anchor AS MATERIALIZED (
  SELECT a.* FROM scope CROSS JOIN LATERAL catalog._inferred_occupation_rows(ARRAY[scope.code],NULL) a
  WHERE scope.code IS NOT NULL
 ), counterparts AS MATERIALIZED (
  SELECT a.* FROM catalog._inferred_occupation_rows(NULL,
   coalesce((SELECT array_agg(DISTINCT posting_key) FROM anchor),ARRAY[]::text[])) a
 ), inferred AS MATERIALIZED (
  SELECT * FROM anchor UNION SELECT * FROM counterparts
 ), wanted AS MATERIALIZED (
  SELECT r.source_id,r.posting_key,bool_or(r.occupation_scheme='NCS') AS needs_ncs,
   bool_or(r.occupation_scheme='ONET') AS needs_onet FROM inferred r GROUP BY r.source_id,r.posting_key
  -- Only a source/posting observed in both schemes can contribute a pair.
  -- Unpaired anchors need no current observation or freshness hash.
  HAVING bool_or(r.occupation_scheme='NCS') AND bool_or(r.occupation_scheme='ONET')
 ), observations AS MATERIALIZED (
  -- Source selection and each needed content hash run once for the combined
  -- bounded workset, rather than once for each side of the crosswalk.
  SELECT p.posting_id,p.source_id,
   CASE WHEN w.needs_ncs THEN encode(sha256(convert_to(p.normalized::text,'UTF8')),'hex') END AS normalized_hash,
   CASE WHEN w.needs_onet THEN catalog._live_source_fact_hash(p.source_id,p.normalized) END AS source_facts_sha256
  FROM catalog._live_source_observations(
   coalesce((SELECT array_agg(DISTINCT posting_key) FROM wanted),ARRAY[]::text[])) p JOIN wanted w
   ON w.source_id=p.source_id AND w.posting_key=p.posting_id
 ), associations AS MATERIALIZED (
  SELECT r.*,CASE WHEN p.posting_id IS NULL THEN 'STALE'
   WHEN r.occupation_scheme='NCS' AND r.normalized_hash IS NOT NULL THEN
    CASE WHEN r.normalized_hash=p.normalized_hash THEN 'CURRENT' ELSE 'STALE' END
   WHEN r.occupation_scheme='ONET' AND p.source_facts_sha256 IS NOT NULL THEN
    CASE WHEN r.source_facts_sha256=p.source_facts_sha256 THEN 'CURRENT' ELSE 'STALE' END
   ELSE 'UNKNOWN' END AS source_freshness,
   jsonb_build_object('association_id',r.association_id,'occupation_name',r.occupation_name,
    'review_status',r.review_status,'source_pins',jsonb_build_object('run_id',r.source_run_id,
     'source_hash',r.source_hash,'normalized_hash',r.normalized_hash,'source_facts_sha256',r.source_facts_sha256),
    'catalog_pins',jsonb_build_object('pin',r.catalog_pin,'catalog_hash',r.catalog_hash)) AS association
  FROM inferred r LEFT JOIN observations p ON p.source_id=r.source_id AND p.posting_id=r.posting_key
 ), pairs AS MATERIALIZED (
  SELECT n.occupation_code AS ncs_code,o.occupation_code AS onet_code,
   min(n.association->>'occupation_name') AS ncs_name,min(o.association->>'occupation_name') AS onet_name,
   n.association#>>'{catalog_pins,pin}' AS ncs_pin,o.association#>>'{catalog_pins,pin}' AS onet_pin,
   count(DISTINCT n.posting_key) AS shared_postings,
   bool_and(n.source_freshness='CURRENT' AND o.source_freshness='CURRENT') AS source_current,
   bool_or(n.source_freshness='STALE' OR o.source_freshness='STALE') AS source_stale,
   bool_and(n.catalog_freshness='CURRENT' AND o.catalog_freshness='CURRENT') AS catalog_current,
   array_agg(DISTINCT n.posting_key ORDER BY n.posting_key) AS posting_keys,
   jsonb_agg(DISTINCT jsonb_build_object('ncs_association_id',n.association->>'association_id',
    'onet_association_id',o.association->>'association_id','source_id',n.source_id,
    'ncs_source_pins',n.association->'source_pins','onet_source_pins',o.association->'source_pins',
    'ncs_catalog_pins',n.association->'catalog_pins','onet_catalog_pins',o.association->'catalog_pins',
    'ncs_review_status',n.association->>'review_status','onet_review_status',o.association->>'review_status')) AS associations
  FROM associations n JOIN associations o USING(posting_key,source_id)
  WHERE n.occupation_scheme='NCS' AND o.occupation_scheme='ONET'
   AND (node_id='ncs:occupation:'||n.occupation_code OR node_id='urn:jobtology:onet:occupation:'||o.occupation_code)
  GROUP BY n.occupation_code,o.occupation_code,n.association#>>'{catalog_pins,pin}',o.association#>>'{catalog_pins,pin}'
 ), endpoint_keys AS (
  SELECT 'ncs:occupation:'||ncs_code AS endpoint_id,ncs_pin AS endpoint_pin FROM pairs UNION
  SELECT 'urn:jobtology:onet:occupation:'||onet_code,onet_pin FROM pairs
 ), ncs_keys AS MATERIALIZED (
  SELECT endpoint_id,endpoint_pin,
   coalesce(endpoint_pin,(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency')) AS selected_pin
  FROM endpoint_keys WHERE endpoint_id LIKE 'ncs:occupation:%'
 ), ncs_records AS MATERIALIZED (
  -- Read each requested READY catalogue once, not once per occupation. Keep
  -- selected-document and non-SMOKE checks from ready_record and the resolver.
  SELECT r.run_id,r.normalized FROM ingestion.ready_record r
  JOIN (SELECT DISTINCT selected_pin FROM ncs_keys) pins ON pins.selected_pin=r.run_id
  JOIN ingestion.run u ON u.run_id=r.run_id
  WHERE r.source_id='ncs_competency' AND u.source_id='ncs_competency'
   AND u.state='READY' AND u.mode<>'SMOKE'
 ), ncs_nodes AS MATERIALIZED (
  -- These are exactly _crosswalk_node's NCS occupation fields and aggregate
  -- ordering. Original NULL/old pins stay distinct keys; NULL selects current.
  SELECT k.endpoint_id,k.endpoint_pin,
   jsonb_build_object('id',k.endpoint_id,'scheme','NCS','kind','ncs_occupation',
    'code',substr(k.endpoint_id,length('ncs:occupation:')+1),
    'name',min(r.normalized->>'occupation_name'),'catalog_pin',k.selected_pin,
    'description',string_agg(r.normalized->>'name',' · ' ORDER BY r.normalized->>'code'),
    'content_hash',encode(sha256(convert_to(jsonb_agg(r.normalized ORDER BY r.normalized->>'code')::text,'UTF8')),'hex')) AS node
  FROM ncs_keys k JOIN ncs_records r ON r.run_id=k.selected_pin
   AND r.normalized->>'occupation_code'=substr(k.endpoint_id,length('ncs:occupation:')+1)
  GROUP BY k.endpoint_id,k.endpoint_pin,k.selected_pin
 ), endpoints AS MATERIALIZED (
  SELECT k.endpoint_id,k.endpoint_pin,
   CASE WHEN k.endpoint_id LIKE 'ncs:occupation:%' THEN n.node
    ELSE catalog._crosswalk_node(k.endpoint_id,k.endpoint_pin) END AS node
  FROM endpoint_keys k LEFT JOIN ncs_nodes n ON n.endpoint_id=k.endpoint_id
   AND n.endpoint_pin IS NOT DISTINCT FROM k.endpoint_pin
 ), nodes AS MATERIALIZED (
  SELECT p.*,s.node AS source,t.node AS target FROM pairs p
  JOIN endpoints s ON s.endpoint_id='ncs:occupation:'||p.ncs_code AND s.endpoint_pin IS NOT DISTINCT FROM p.ncs_pin
  JOIN endpoints t ON t.endpoint_id='urn:jobtology:onet:occupation:'||p.onet_code AND t.endpoint_pin IS NOT DISTINCT FROM p.onet_pin
 )
 SELECT jsonb_build_object('mapping_id','shared-postings:'||encode(sha256(convert_to(
  jsonb_build_array(ncs_code,onet_code,ncs_pin,onet_pin)::text,'UTF8')),'hex'),
  'version','shared-postings-v1','source',source,'target',target,'relation','RELATED','status','PROPOSED',
  'basis','SHARED_POSTINGS','evidence',jsonb_build_object('shared_postings',shared_postings,
   'posting_keys',to_jsonb(posting_keys[1:5]),'associations',(SELECT jsonb_agg(value) FROM
    (SELECT value FROM jsonb_array_elements(associations) ORDER BY value::text LIMIT 5) sample),
   'summary','같은 공고의 직무 추론이 함께 연결된 탐색 제안이며 역량 동등성을 뜻하지 않아요.'),
  'review',NULL,'source_freshness',CASE WHEN source_current THEN 'CURRENT' WHEN source_stale THEN 'STALE' ELSE 'UNKNOWN' END,
  'catalog_freshness',CASE WHEN catalog_current THEN 'CURRENT' ELSE 'STALE' END,
  'created_at',NULL,'competency_evidence',false)
 FROM nodes WHERE source IS NOT NULL AND target IS NOT NULL
$$;

REVOKE ALL ON FUNCTION catalog._live_source_observations(text[]),
 catalog._ncs_onet_shared_posting_proposals(text) FROM PUBLIC;
COMMIT;
