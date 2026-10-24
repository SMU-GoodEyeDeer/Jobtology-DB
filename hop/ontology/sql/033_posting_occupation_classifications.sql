BEGIN;

-- Default hook is deliberately empty. SQL035 may install a guarded audit-backed
-- implementation; merely changing catalog pins never upgrades freshness.
DO $bootstrap_hook$ BEGIN
 IF to_regprocedure('catalog._ncs_catalog_revalidation(text,text,text)') IS NULL THEN
  EXECUTE $definition$CREATE FUNCTION catalog._ncs_catalog_revalidation(original text,code text,original_hash text)
   RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $hook$ SELECT NULL::jsonb $hook$$definition$;
 END IF;
END $bootstrap_hook$;

-- A bounded projection of the published occupation ledger. Select source rows
-- and the latest captured result BEFORE candidate/review expansion; do not call
-- the full JSON graph publisher once per posting/candidate.
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
     WHERE g.state='READY'
      AND EXISTS(SELECT 1 FROM ingestion.run r WHERE r.run_id=g.job_run_id AND r.source_id='jobkorea' AND r.state='READY')
      AND EXISTS(SELECT 1 FROM ingestion.run r WHERE r.run_id=g.ncs_run_id AND r.source_id='ncs_competency' AND r.state='READY')
     ORDER BY g.job_run_id,g.ncs_run_id,g.completed_at DESC,g.writer_token DESC
    ), captured AS MATERIALIZED (
     SELECT DISTINCT ON(p.job_run_id,p.ncs_run_id,i.posting_id)
      p.job_run_id,p.ncs_run_id,p.completed_at,p.include_unreviewed,
      i.posting_id,x.bundle_id,x.source_hash,ib.manifest,r.result_id,r.output,
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
     WHERE s.output->>'outcome'='matched' AND ($1 IS NULL OR c.occupation_code=ANY($1))
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
     WHERE state='READY' ORDER BY job_run_id,ncs_run_id,completed_at DESC,writer_token DESC
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
    WHERE g.state='VERIFIED' AND ($1 IS NULL OR e.properties->>'occupation_code'=ANY($1))
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

-- Retain the existing context reader signature with the same ordering/freshness
-- semantics. Its list/detail callers can now supply a bounded source selection.
CREATE OR REPLACE FUNCTION catalog._inferred_occupation_rows(occupation_codes text[] DEFAULT NULL)
RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,
 occupation_scheme text,occupation_code text,occupation_name text,association_id text,
 review_status text,stage text,confidence_state text,source_hash text,
 normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,
 catalog_freshness text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT * FROM catalog._inferred_occupation_rows(occupation_codes,NULL)
$$;
REVOKE ALL ON FUNCTION catalog._inferred_occupation_rows(text[],text[]),catalog._ncs_catalog_revalidation(text,text,text) FROM PUBLIC;


-- An inferred occupation is never a source category or competency assertion.
-- Read each adapter once and hash each relevant current observation once per
-- batch. Empty bounded selections do not enumerate publication history.
CREATE OR REPLACE FUNCTION catalog._live_occupation_associations(
 posting_choices text[] DEFAULT NULL,occupation_codes text[] DEFAULT NULL)
RETURNS TABLE(posting_key text,source_id text,occupation_scheme text,occupation_code text,
 source_freshness text,catalog_freshness text,association jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF (posting_choices IS NOT NULL AND cardinality(posting_choices)=0)
  OR (occupation_codes IS NOT NULL AND cardinality(occupation_codes)=0) THEN RETURN; END IF;
 RETURN QUERY
 WITH inferred_rows AS MATERIALIZED (
  SELECT r.* FROM catalog._inferred_occupation_rows(occupation_codes,posting_choices) r
  WHERE (posting_choices IS NULL OR r.posting_key=ANY(posting_choices))
   AND (occupation_codes IS NULL OR r.occupation_code=ANY(occupation_codes))
 ), wanted AS MATERIALIZED (
  SELECT r.source_id,r.posting_key,bool_or(r.occupation_scheme='NCS') AS needs_ncs,
   bool_or(r.occupation_scheme='ONET') AS needs_onet
  FROM inferred_rows r GROUP BY r.source_id,r.posting_key
 ), observations AS MATERIALIZED (
  SELECT p.posting_id,p.source_id,
   CASE WHEN w.needs_ncs THEN encode(sha256(convert_to(p.normalized::text,'UTF8')),'hex') END AS normalized_hash,
   CASE WHEN w.needs_onet THEN catalog._live_source_fact_hash(p.source_id,p.normalized) END AS source_facts_sha256
  FROM catalog._live_source_observations() p
  JOIN wanted w ON w.source_id=p.source_id AND w.posting_key=p.posting_id
 ), compared AS (
  SELECT r.*,CASE WHEN p.posting_id IS NULL THEN 'STALE'
   WHEN r.occupation_scheme='NCS' AND r.normalized_hash IS NOT NULL THEN
    CASE WHEN r.normalized_hash=p.normalized_hash THEN 'CURRENT' ELSE 'STALE' END
   WHEN r.occupation_scheme='ONET' AND p.source_facts_sha256 IS NOT NULL THEN
    CASE WHEN r.source_facts_sha256=p.source_facts_sha256 THEN 'CURRENT' ELSE 'STALE' END
   ELSE 'UNKNOWN' END AS source_freshness
  FROM inferred_rows r LEFT JOIN observations p ON p.source_id=r.source_id AND p.posting_id=r.posting_key
 ) SELECT r.posting_key,r.source_id,r.occupation_scheme,r.occupation_code,
  r.source_freshness,r.catalog_freshness,jsonb_build_object(
   'posting_key',r.posting_key,'posting_identity',r.posting_identity,'source_id',r.source_id,
   'occupation_scheme',r.occupation_scheme,'occupation_code',r.occupation_code,'occupation_name',r.occupation_name,
   'association_id',r.association_id,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
   'competency_evidence',false,'review_status',r.review_status,'stage',r.stage,
   'confidence',NULL,'confidence_state',r.confidence_state,
   'source_freshness',r.source_freshness,'catalog_freshness',r.catalog_freshness,
   'source_pins',jsonb_build_object('run_id',r.source_run_id,'source_hash',r.source_hash,
    'normalized_hash',r.normalized_hash,'source_facts_sha256',r.source_facts_sha256),
   'catalog_pins',jsonb_build_object('pin',r.catalog_pin,'catalog_hash',r.catalog_hash),
   'catalog_revalidation',CASE WHEN r.occupation_scheme='NCS' THEN catalog._ncs_catalog_revalidation(r.catalog_pin,r.occupation_code,r.catalog_hash) END)
 FROM compared r;
END $$;

-- This private lookup selects catalog codes before the metadata adapter runs.
-- It allows a numeric NCS prefix without enumerating the unrelated ONET branch.
CREATE OR REPLACE FUNCTION catalog._live_ncs_filter_codes(category text)
RETURNS text[] LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE codes text[];
BEGIN
 IF category IS NULL OR category !~ '^[0-9]{1,8}$'
  OR to_regclass('enrichment.metadata_occupation_catalog') IS NULL THEN RETURN ARRAY[]::text[]; END IF;
 EXECUTE 'SELECT coalesce(array_agg(DISTINCT occupation_code ORDER BY occupation_code),ARRAY[]::text[]) '
  'FROM enrichment.metadata_occupation_catalog WHERE starts_with(occupation_code,$1)'
 INTO codes USING category;
 RETURN codes;
END $$;

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
   FROM ingestion.latest_ready_run WHERE source_id IN ('jobkorea','job_alio','nara_job')),
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
 INTO source_items FROM ingestion.latest_ready_run WHERE source_id=chosen_source;
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

REVOKE ALL ON FUNCTION catalog._live_occupation_associations(text[],text[]),catalog._live_ncs_filter_codes(text),
 catalog.live_postings_v1(text,text,text,date,integer,integer),catalog.live_posting_v1(text) FROM PUBLIC;
COMMIT;
