BEGIN;

-- Crosswalk-only workset. Qualified occupation adapters/projectors and the
-- immutable replacement policy are unchanged. Source facts are read only after
-- visible edge selection; publication gates run once per distinct source pin.
CREATE OR REPLACE FUNCTION catalog._crosswalk_pair_rows(node_id text)
RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,
 occupation_scheme text,occupation_code text,occupation_name text,association_id text,
 review_status text,stage text,confidence_state text,source_hash text,
 normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,
 catalog_freshness text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE selected_code text; selected_scheme text;
BEGIN
 IF node_id LIKE 'ncs:occupation:%' THEN
  selected_code:=substr(node_id,length('ncs:occupation:')+1); selected_scheme:='NCS';
 ELSIF node_id LIKE 'urn:jobtology:onet:occupation:%' THEN
  selected_code:=substr(node_id,length('urn:jobtology:onet:occupation:')+1); selected_scheme:='ONET';
 ELSE RETURN; END IF;
 IF selected_scheme<>'ONET' OR to_regclass('enrichment.metadata_occupation_catalog') IS NULL
  OR to_regclass('onet_matching.input') IS NULL
  OR to_regclass('onet_matching.graph_guard') IS NULL
  OR to_regclass('onet_matching.graph_edge') IS NULL
  OR to_regprocedure('ingestion.jobkorea_onet_publication_allowed(text,text,text,text)') IS NULL
  OR to_regprocedure('catalog._replacement_policy_ready()') IS NULL
  OR to_regprocedure('catalog._replacement_policy_allowed(text,text,text)') IS NULL THEN
  -- Preserve older/partial installations and their existing optional adapters.
  RETURN QUERY
   WITH anchor AS MATERIALIZED (
    SELECT * FROM catalog._inferred_occupation_rows(ARRAY[selected_code],NULL)
   ), counterparts AS MATERIALIZED (
    SELECT * FROM catalog._inferred_occupation_rows(NULL,
     coalesce((SELECT array_agg(DISTINCT a.posting_key) FROM anchor a),ARRAY[]::text[]))
   ) SELECT * FROM anchor UNION SELECT * FROM counterparts;
  RETURN;
 END IF;
 RETURN QUERY EXECUTE $bounded$
  WITH candidate_ids AS MATERIALIZED (
   -- Metadata-only source pruning is safe; cross-scheme identities need not
   -- match. Retain every version of these IDs until the original DISTINCT.
   SELECT DISTINCT e.edge_id FROM onet_matching.graph_edge e
   JOIN onet_matching.input i ON i.task_id=coalesce(e.properties->>'task_id',e.payload_json::jsonb->>'task_id')
    AND i.posting_identity=e.posting_identity
   WHERE i.source_id='jobkorea' AND e.properties->>'occupation_code'=$1
  ), edge_pins AS MATERIALIZED (
   SELECT DISTINCT e.publication_id,e.edge_id,g.task_id,pin.source_id,pin.source_run_id
   FROM candidate_ids c JOIN onet_matching.graph_edge e USING(edge_id)
   JOIN onet_matching.graph_guard g USING(publication_id)
   JOIN onet_matching.input pin ON pin.task_id=g.task_id AND pin.posting_identity=e.posting_identity
   WHERE g.state='VERIFIED' AND e.properties->>'occupation_code'=$1
  ), pin_gates AS MATERIALIZED (
   SELECT p.*,ingestion.jobkorea_onet_publication_allowed(
    p.publication_id,p.task_id,p.source_id,p.source_run_id) AS allowed
   FROM (SELECT DISTINCT publication_id,task_id,source_id,source_run_id FROM edge_pins) p
  ), edges AS MATERIALIZED (
   -- Keep ALL versions of each candidate ID through the original selection,
   -- including a newer version whose task/input/identity will not join below.
   -- Filtering that join before DISTINCT could revive an older publication.
   SELECT DISTINCT ON(e.edge_id) e.edge_id,e.posting_identity,e.occupation_identity,g.database_id,
    e.properties->>'occupation_code' AS occupation_code,e.properties->>'review_status' AS review_status,
    e.properties->>'stage' AS stage,e.properties->>'confidence_state' AS confidence_state,
    e.properties->>'source_facts_sha256' AS source_facts_sha256,e.properties->>'release_id' AS release_id,
    e.properties->>'catalog_hash' AS catalog_hash,e.properties->>'occupation_content_hash' AS occupation_content_hash,
    coalesce(e.properties->>'task_id',e.payload_json::jsonb->>'task_id') AS task_id,
    coalesce(e.properties->>'occupation_name',e.payload_json::jsonb->>'occupation_name') AS occupation_name
   FROM candidate_ids c JOIN onet_matching.graph_edge e USING(edge_id)
   JOIN onet_matching.graph_guard g USING(publication_id)
   WHERE g.state='VERIFIED'
    AND (g.task_id<>'jkr-20261103-onet' OR ((SELECT catalog._replacement_policy_ready())
     AND catalog._replacement_policy_allowed('ONET',
      coalesce(e.properties->>'attempt_id',e.payload_json::jsonb->>'attempt_id'),g.task_id)))
    AND EXISTS(SELECT 1 FROM edge_pins p JOIN pin_gates v
     USING(publication_id,task_id,source_id,source_run_id)
     WHERE p.publication_id=e.publication_id AND p.edge_id=e.edge_id AND v.allowed)
    AND e.properties->>'occupation_code'=$1
   ORDER BY e.edge_id,g.finished_at DESC,e.publication_id DESC
  ), input_keys AS MATERIALIZED (
   SELECT DISTINCT e.task_id,e.posting_identity FROM edges e
  ), inputs AS MATERIALIZED (
   SELECT i.task_id,i.posting_identity,i.source_id,i.source_run_id,
    CASE WHEN i.source_id='job_alio' THEN i.source_facts->>'posting_id'
     ELSE i.source_id||':'||(i.source_facts->>'posting_id') END AS posting_key
   FROM input_keys e JOIN onet_matching.input i
    ON i.task_id=e.task_id AND i.posting_identity=e.posting_identity
   WHERE i.source_id='jobkorea'
  ), onet AS MATERIALIZED (
   SELECT i.posting_key,e.posting_identity,i.source_id,i.source_run_id,'ONET'::text AS occupation_scheme,
    e.occupation_code,e.occupation_name,e.edge_id AS association_id,e.review_status,e.stage,e.confidence_state,
    NULL::text AS source_hash,NULL::text AS normalized_hash,e.source_facts_sha256,
    e.release_id AS catalog_pin,e.catalog_hash,
    CASE WHEN current.release_id IS NULL THEN 'STALE'
     WHEN node.content_hash=e.occupation_content_hash THEN 'CURRENT' ELSE 'STALE' END AS catalog_freshness
   FROM edges e JOIN inputs i ON i.task_id=e.task_id AND i.posting_identity=e.posting_identity
   LEFT JOIN classification.catalog_current current ON current.database_id=e.database_id AND current.release_id=e.release_id
   LEFT JOIN classification.graph_load_node node ON node.load_id=current.load_id AND node.node_id=e.occupation_identity
  ), ncs AS MATERIALIZED (
   -- ALL historical codes, and the canonical adapter's exact posting-key
   -- filter. This neither assumes equal identities nor discards stale pins.
   SELECT a.* FROM catalog._inferred_occupation_rows(
    (SELECT coalesce(array_agg(DISTINCT c.occupation_code),ARRAY[]::text[])
     FROM enrichment.metadata_occupation_catalog c),
    coalesce((SELECT array_agg(DISTINCT o.posting_key) FROM onet o),ARRAY[]::text[])) a
  )
  SELECT * FROM onet UNION SELECT * FROM ncs
 $bounded$ USING selected_code,selected_scheme;
END $$;

CREATE OR REPLACE FUNCTION catalog._ncs_onet_shared_posting_proposals(node_id text)
RETURNS SETOF jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH inferred AS MATERIALIZED (
  SELECT * FROM catalog._crosswalk_pair_rows(node_id)
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

REVOKE ALL ON FUNCTION catalog._crosswalk_pair_rows(text),
 catalog._ncs_onet_shared_posting_proposals(text) FROM PUBLIC;
COMMIT;
