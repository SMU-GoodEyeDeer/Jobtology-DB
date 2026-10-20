BEGIN;

-- This reader is deliberately separate from sealed release inputs and the
-- explicit-duty/competency evidence contract. No inference becomes a source fact.
-- Remove the earlier private no-argument overload when replaying this migration.
DROP FUNCTION IF EXISTS catalog._inferred_occupation_rows();
CREATE OR REPLACE FUNCTION catalog._inferred_occupation_rows(occupation_codes text[] DEFAULT NULL)
RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,
 occupation_scheme text,occupation_code text,occupation_name text,association_id text,
 review_status text,stage text,confidence_state text,source_hash text,
 normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,
 catalog_freshness text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF (occupation_codes IS NULL OR EXISTS(SELECT 1 FROM unnest(occupation_codes) code
  WHERE code ~ '^[0-9]{8}$'))
  AND to_regprocedure('enrichment.metadata_occupation_graph_rows(text,text,boolean)') IS NOT NULL THEN
  RETURN QUERY EXECUTE $ncs$
   WITH publications AS (
    SELECT DISTINCT ON(job_run_id,ncs_run_id) *
    FROM enrichment.metadata_occupation_graph_guard WHERE state='READY'
    ORDER BY job_run_id,ncs_run_id,completed_at DESC,writer_token DESC
   )
   SELECT DISTINCT ON(b.manifest#>>'{document,source_record_id}',r.payload->>'occupation_code')
    'jobkorea:'||(b.manifest#>>'{document,source_record_id}'),r.posting_identity,
    'jobkorea'::text,p.job_run_id,'NCS'::text,r.payload->>'occupation_code',
    r.payload->>'occupation_name',r.candidate_id,r.payload->>'review_status',
    r.payload->>'stage',r.payload->>'confidence_state',r.payload->>'source_hash',
    b.manifest#>>'{document,normalized_hash}',NULL::text,p.ncs_run_id,r.payload->>'catalog_hash',
    CASE WHEN n.run_id=p.ncs_run_id THEN 'CURRENT' ELSE 'STALE' END
   FROM publications p
   CROSS JOIN LATERAL enrichment.metadata_occupation_graph_rows(p.job_run_id,p.ncs_run_id,p.include_unreviewed) r
   JOIN enrichment.input_bundle b ON b.bundle_id=r.payload->>'bundle_id'
   LEFT JOIN ingestion.latest_ready_run n ON n.source_id='ncs_competency'
   WHERE $1 IS NULL OR r.payload->>'occupation_code'=ANY($1)
   ORDER BY b.manifest#>>'{document,source_record_id}',r.payload->>'occupation_code',
    p.completed_at DESC,r.candidate_id DESC
  $ncs$ USING occupation_codes;
 END IF;
 IF (occupation_codes IS NULL OR EXISTS(SELECT 1 FROM unnest(occupation_codes) code
  WHERE code ~ '^[0-9]{2}-[0-9]{4}\.[0-9]{2}$'))
  AND to_regclass('onet_matching.graph_edge') IS NOT NULL THEN
  RETURN QUERY EXECUTE $onet$
   WITH edges AS (
    SELECT DISTINCT ON(e.edge_id) e.*,g.database_id
    FROM onet_matching.graph_edge e JOIN onet_matching.graph_guard g USING(publication_id)
    WHERE g.state='VERIFIED' AND ($1 IS NULL OR e.properties->>'occupation_code'=ANY($1))
    ORDER BY e.edge_id,g.finished_at DESC,e.publication_id DESC
   )
   SELECT CASE WHEN i.source_id='job_alio' THEN i.source_facts->>'posting_id'
     ELSE i.source_id||':'||(i.source_facts->>'posting_id') END,
    e.posting_identity,i.source_id,i.source_run_id,'ONET'::text,
    e.properties->>'occupation_code',payload->>'occupation_name',e.edge_id,
    e.properties->>'review_status',e.properties->>'stage',e.properties->>'confidence_state',
    NULL::text,NULL::text,e.properties->>'source_facts_sha256',
    e.properties->>'release_id',e.properties->>'catalog_hash',
    CASE WHEN current.release_id IS NULL THEN 'STALE'
     WHEN node.content_hash=e.properties->>'occupation_content_hash' THEN 'CURRENT' ELSE 'STALE' END
   FROM edges e
   CROSS JOIN LATERAL (SELECT e.payload_json::jsonb AS payload) parsed
   JOIN onet_matching.input i ON i.task_id=payload->>'task_id' AND i.posting_identity=e.posting_identity
   LEFT JOIN classification.catalog_current current ON current.database_id=e.database_id
    AND current.release_id=e.properties->>'release_id'
   LEFT JOIN classification.graph_load_node node ON node.load_id=current.load_id AND node.node_id=e.occupation_identity
  $onet$ USING occupation_codes;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION catalog._live_source_fact_hash(source text,value jsonb)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE answer text;
BEGIN
 IF to_regprocedure('ingestion.source_graph_entity_facts(text,text,jsonb)') IS NULL THEN RETURN NULL; END IF;
 EXECUTE 'SELECT encode(sha256(convert_to(ingestion.source_graph_entity_facts(''JobPosting'',$1,$2)::text,''UTF8'')),''hex'')'
 INTO answer USING source,value;
 RETURN answer;
END $$;

CREATE OR REPLACE FUNCTION catalog.inferred_occupation_context_v1(
 occupation_codes text[] DEFAULT NULL,page_size integer DEFAULT 20,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE answer jsonb;
BEGIN
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_LIVE_PAGE'; END IF;
 IF occupation_codes IS NOT NULL AND (cardinality(occupation_codes)>100 OR EXISTS(
  SELECT 1 FROM unnest(occupation_codes) code
  WHERE code IS NULL OR code !~ '^([0-9]{8}|[0-9]{2}-[0-9]{4}\.[0-9]{2})$'))
 THEN RAISE EXCEPTION 'INVALID_OCCUPATION_CONTEXT_FILTER'; END IF;
 WITH inferred_rows AS MATERIALIZED (
  SELECT * FROM catalog._inferred_occupation_rows(occupation_codes)
  WHERE occupation_codes IS NULL OR occupation_code=ANY(occupation_codes)
 ), wanted_postings AS MATERIALIZED (
  SELECT source_id,posting_key,bool_or(occupation_scheme='NCS') AS needs_ncs,
   bool_or(occupation_scheme='ONET') AS needs_onet
  FROM inferred_rows GROUP BY source_id,posting_key
 ), current_observations AS MATERIALIZED (
  SELECT p.posting_id,p.source_id,p.run_id,p.data_as_of,p.normalized,
   CASE WHEN w.needs_ncs THEN encode(sha256(convert_to(p.normalized::text,'UTF8')),'hex') END AS normalized_hash,
   CASE WHEN w.needs_onet THEN catalog._live_source_fact_hash(p.source_id,p.normalized) END AS source_facts_sha256
  FROM catalog._live_source_observations() p
  JOIN wanted_postings w ON w.source_id=p.source_id AND w.posting_key=p.posting_id
 ), associations AS MATERIALIZED (
  SELECT r.*,p.normalized AS current_normalized,p.run_id AS current_run_id,
   p.data_as_of AS current_data_as_of,
   CASE WHEN p.posting_id IS NULL THEN 'STALE'
    WHEN r.occupation_scheme='NCS' AND r.normalized_hash IS NOT NULL THEN
     CASE WHEN r.normalized_hash=p.normalized_hash THEN 'CURRENT' ELSE 'STALE' END
    WHEN r.occupation_scheme='ONET' AND p.source_facts_sha256 IS NOT NULL THEN
     CASE WHEN r.source_facts_sha256=p.source_facts_sha256 THEN 'CURRENT' ELSE 'STALE' END
    ELSE 'UNKNOWN' END AS source_freshness
  FROM inferred_rows r LEFT JOIN current_observations p
   ON p.source_id=r.source_id AND p.posting_id=r.posting_key
 ), page AS (
  SELECT * FROM associations ORDER BY CASE source_id WHEN 'jobkorea' THEN 0 WHEN 'job_alio' THEN 1 ELSE 2 END,posting_key COLLATE "C",
   occupation_scheme COLLATE "C",occupation_code COLLATE "C",association_id COLLATE "C"
  LIMIT page_size OFFSET page_offset
 )
 SELECT jsonb_build_object('contract_version','jobtology-inferred-occupation-context-v1',
  'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
  'competency_evidence',false,'limit',page_size,'offset',page_offset,
  'filters',jsonb_build_object('occupation_codes',occupation_codes),
  'total',(SELECT count(*) FROM associations),
  'summary',jsonb_build_object('associations',(SELECT count(*) FROM associations),
   'postings',(SELECT count(DISTINCT (source_id,posting_key)) FROM associations),
   'source_current_associations',(SELECT count(*) FROM associations WHERE source_freshness='CURRENT'),
   'catalog_current_associations',(SELECT count(*) FROM associations WHERE catalog_freshness='CURRENT'),
   'stale_associations',(SELECT count(*) FROM associations WHERE source_freshness='STALE' OR catalog_freshness='STALE'),
   'unknown_associations',(SELECT count(*) FROM associations WHERE source_freshness='UNKNOWN'),
   'current_associations',(SELECT count(*) FROM associations WHERE source_freshness='CURRENT' AND catalog_freshness='CURRENT'),
   'by_source',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.source_id COLLATE "C"),'[]'::jsonb)
    FROM (SELECT source_id,count(*) AS associations,count(DISTINCT posting_key) AS postings,
     count(*) FILTER (WHERE source_freshness='CURRENT') AS source_current_associations,
     count(*) FILTER (WHERE catalog_freshness='CURRENT') AS catalog_current_associations,
     count(*) FILTER (WHERE source_freshness='CURRENT' AND catalog_freshness='CURRENT') AS current_associations
     FROM associations GROUP BY source_id) s),
   'by_occupation',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.occupation_scheme COLLATE "C",
     s.occupation_code COLLATE "C"),'[]'::jsonb)
    FROM (SELECT occupation_scheme,occupation_code,min(occupation_name) AS occupation_name,
     count(*) AS associations,count(DISTINCT (source_id,posting_key)) AS postings,
     count(*) FILTER (WHERE source_freshness='CURRENT') AS source_current_associations,
     count(*) FILTER (WHERE catalog_freshness='CURRENT') AS catalog_current_associations,
     count(*) FILTER (WHERE source_freshness='CURRENT' AND catalog_freshness='CURRENT') AS current_associations
     FROM associations GROUP BY occupation_scheme,occupation_code) s)),
  'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
   'posting_key',posting_key,'posting_identity',posting_identity,'source_id',source_id,
   'occupation_scheme',occupation_scheme,'occupation_code',occupation_code,'occupation_name',occupation_name,
   'association_id',association_id,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
   'review_status',review_status,'stage',stage,'confidence',NULL,'confidence_state',confidence_state,
   'source_freshness',source_freshness,'catalog_freshness',catalog_freshness,
   'posting',CASE WHEN current_normalized IS NOT NULL THEN catalog._live_source_posting_item(
    current_normalized,posting_key,source_id,current_run_id,current_data_as_of) END,
   'source_pins',jsonb_build_object('run_id',source_run_id,'source_hash',source_hash,
    'normalized_hash',normalized_hash,'source_facts_sha256',source_facts_sha256),
   'catalog_pins',jsonb_build_object('pin',catalog_pin,'catalog_hash',catalog_hash))
   ORDER BY CASE source_id WHEN 'jobkorea' THEN 0 WHEN 'job_alio' THEN 1 ELSE 2 END,posting_key COLLATE "C",occupation_scheme COLLATE "C",
    occupation_code COLLATE "C",association_id COLLATE "C"),'[]'::jsonb) FROM page)) INTO answer;
 RETURN answer;
END $$;

REVOKE ALL ON FUNCTION catalog._inferred_occupation_rows(text[]),catalog._live_source_fact_hash(text,jsonb),
 catalog.inferred_occupation_context_v1(text[],integer,integer) FROM PUBLIC;
-- A compatible catalog upgrade needs only 031/032. Preserve every existing
-- privilege; fresh installations still apply the standard restricted grants.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN
  GRANT EXECUTE ON FUNCTION catalog.inferred_occupation_context_v1(text[],integer,integer)
   TO jobtology_catalog_reader;
 END IF;
END $$;
COMMIT;
