BEGIN;

-- Source-run rows are input pins, not evidence coverage. Legacy publications
-- without pins use their verified job_run_id lineage.
CREATE OR REPLACE FUNCTION catalog._live_link_item_source(
 publication text,payload jsonb,posting_identity text)
RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
  WITH lineage AS (
   SELECT s.source_id FROM enrichment.link_publication_source_run s
   JOIN ingestion.run r ON r.run_id=s.run_id AND r.source_id=s.source_id
   WHERE s.publication_id=$1 AND s.source_id IN ('job_alio','nara_job')
   UNION ALL
   SELECT r.source_id FROM enrichment.link_publication p
   JOIN ingestion.run r ON r.run_id=p.job_run_id
   WHERE p.publication_id=$1 AND r.source_id IN ('job_alio','nara_job')
    AND NOT EXISTS (SELECT 1 FROM enrichment.link_publication_source_run s
     WHERE s.publication_id=p.publication_id)
 )
 SELECT CASE
  WHEN strpos($3,'job-alio:posting:')=1 AND $2->>'source_id' IS NOT NULL
   AND $2->>'source_id'<>'job_alio' THEN NULL
  WHEN strpos($3,'source:posting:nara_job:')=1 AND $2->>'source_id' IS NOT NULL
   AND $2->>'source_id'<>'nara_job' THEN NULL
  WHEN $2->>'source_id' IS NOT NULL THEN
   (SELECT source_id FROM lineage WHERE source_id=$2->>'source_id')
  WHEN strpos($3,'job-alio:posting:')=1 THEN
   (SELECT source_id FROM lineage WHERE source_id='job_alio')
  WHEN strpos($3,'source:posting:nara_job:')=1 THEN
   (SELECT source_id FROM lineage WHERE source_id='nara_job')
  END
$$;

CREATE OR REPLACE FUNCTION catalog._live_link_publications_with_provenance()
RETURNS TABLE(posting_source text,publication_id text,created_at timestamptz,
 run_id text,is_latest_publication boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
  SELECT source.posting_source,p.publication_id,p.created_at,p.run_id,
   p.publication_id=(SELECT newest.publication_id FROM enrichment.link_publication newest
    LEFT JOIN enrichment.link_publication_source_run pin
     ON pin.publication_id=newest.publication_id AND pin.source_id=source.posting_source
    LEFT JOIN ingestion.run pinned ON pinned.run_id=pin.run_id
     AND pinned.source_id=pin.source_id
    JOIN ingestion.run legacy ON legacy.run_id=newest.job_run_id
    WHERE newest.state='READY' AND (pinned.run_id IS NOT NULL OR
     (legacy.source_id=source.posting_source AND NOT EXISTS
      (SELECT 1 FROM enrichment.link_publication_source_run s
       WHERE s.publication_id=newest.publication_id)))
    ORDER BY newest.created_at DESC,newest.publication_id COLLATE "C" DESC LIMIT 1)
  FROM (VALUES ('job_alio'),('nara_job')) AS source(posting_source)
  CROSS JOIN LATERAL (
   SELECT p.publication_id,p.created_at,coalesce(pinned.run_id,legacy.run_id) AS run_id
   FROM enrichment.link_publication p
   LEFT JOIN enrichment.link_publication_source_run pin
    ON pin.publication_id=p.publication_id AND pin.source_id=source.posting_source
   LEFT JOIN ingestion.run pinned ON pinned.run_id=pin.run_id
    AND pinned.source_id=pin.source_id
   JOIN ingestion.run legacy ON legacy.run_id=p.job_run_id
   WHERE p.state='READY' AND (pinned.run_id IS NOT NULL OR
    (legacy.source_id=source.posting_source AND NOT EXISTS
     (SELECT 1 FROM enrichment.link_publication_source_run s
      WHERE s.publication_id=p.publication_id)))
    AND EXISTS (SELECT 1 FROM enrichment.link_publication_item i
     WHERE i.publication_id=p.publication_id
      AND catalog._live_link_item_source(i.publication_id,i.payload,i.posting_identity)
       =source.posting_source)
   ORDER BY p.created_at DESC,p.publication_id COLLATE "C" DESC LIMIT 1
 ) p
$$;

CREATE OR REPLACE FUNCTION catalog.live_ncs_demand_v1(
 ncs_prefix text DEFAULT NULL,page_size integer DEFAULT 20,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE prefix text:=nullif(btrim(ncs_prefix),''); ncs_run text; qual_run text;
 source_items jsonb; review_counts jsonb; result_items jsonb; total_count bigint;
BEGIN
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_LIVE_PAGE'; END IF;
 IF prefix IS NOT NULL AND prefix !~ '^[0-9]{2,8}$'
 THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 SELECT run_id INTO ncs_run FROM ingestion.latest_ready_run WHERE source_id='ncs_competency';
 SELECT run_id INTO qual_run FROM ingestion.latest_ready_run WHERE source_id='ncs_qualification';
 SELECT coalesce(jsonb_agg(jsonb_build_object('source_id','link_publication',
   'publication_id',p.publication_id,'created_at',p.created_at,
   'posting_source',p.posting_source,'run_id',p.run_id,
   'is_latest_publication',p.is_latest_publication)
   ORDER BY p.posting_source COLLATE "C"),'[]'::jsonb)
  INTO source_items FROM catalog._live_link_publications_with_provenance() p;

 WITH links AS MATERIALIZED (
   SELECT p.posting_source,p.publication_id,p.created_at,i.posting_id,i.name,i.payload,
   coalesce(i.payload->>'source_posting_id',
    CASE WHEN strpos(i.posting_identity,'job-alio:posting:')=1
     THEN substr(i.posting_identity,length('job-alio:posting:')+1) END) AS source_posting_id,
   l.value AS link,l.ordinal,
   l.value->>'competency_code' AS competency_code
   FROM catalog._live_link_publications_with_provenance() p
  JOIN enrichment.link_publication_item i ON i.publication_id=p.publication_id
   AND catalog._live_link_item_source(i.publication_id,i.payload,i.posting_identity)
    =p.posting_source
  CROSS JOIN LATERAL jsonb_array_elements(coalesce(i.payload->'links','[]'::jsonb))
   WITH ORDINALITY AS l(value,ordinal)
 ), counts AS (
  SELECT competency_code,count(DISTINCT (posting_source,posting_id)) AS postings,count(*) AS links
  FROM links WHERE competency_code IS NOT NULL GROUP BY competency_code
 ), filtered AS (
  SELECT * FROM counts WHERE prefix IS NULL OR left(competency_code,length(prefix))=prefix
 ), page AS (
  SELECT * FROM filtered ORDER BY postings DESC,links DESC,competency_code COLLATE "C" ASC
  LIMIT page_size OFFSET page_offset
  ), kinds AS (
  SELECT coalesce(nullif(link->>'reviewer_kind',''),'unknown') AS kind,count(*) AS n
  FROM links GROUP BY 1
 ), names AS MATERIALIZED (
  -- ingestion.competency/qualification_mapping are views; read each once per page.
  SELECT c.code,min(c.name) AS name,min(c.occupation_name) AS occupation_name
  FROM ingestion.competency c
  WHERE c.run_id=ncs_run AND c.code IN (SELECT competency_code FROM page)
  GROUP BY c.code
 ), quals AS MATERIALIZED (
  SELECT DISTINCT q.competency_code,q.qualification_code,q.qualification_name
  FROM ingestion.qualification_mapping q
  WHERE q.run_id=qual_run AND q.competency_code IN (SELECT competency_code FROM page)
 )
 SELECT (SELECT count(*) FROM filtered),
  (SELECT coalesce(jsonb_object_agg(kind,n),'{}'::jsonb) FROM kinds),
  (SELECT coalesce(jsonb_agg(jsonb_build_object(
   'competency_code',pg.competency_code,
   'competency_name',(SELECT n.name FROM names n WHERE n.code=pg.competency_code),
   'ncs_occupation_code',left(pg.competency_code,8),
   'ncs_occupation_name',(SELECT n.occupation_name FROM names n
    WHERE n.code=pg.competency_code),
   'postings',pg.postings,'links',pg.links,
    'evidence',(SELECT coalesce(jsonb_agg(jsonb_build_object('source_id',ev.posting_source,
     'publication_id',ev.publication_id,'created_at',ev.created_at,
    'source_posting_id',ev.source_posting_id,'title',ev.name,
    'position',ev.link->'duty'->>'position','duty',ev.link->'duty'->>'text')
    ORDER BY ev.source_posting_id COLLATE "C",ev.posting_source COLLATE "C",
     ev.posting_id COLLATE "C",ev.ordinal),'[]'::jsonb)
     FROM (SELECT posting_source,publication_id,created_at,source_posting_id,
      posting_id,name,link,ordinal
     FROM links WHERE competency_code=pg.competency_code
     ORDER BY source_posting_id COLLATE "C",posting_source COLLATE "C",
      posting_id COLLATE "C",ordinal LIMIT 3) ev),
   'related_qualifications',(SELECT coalesce(jsonb_agg(jsonb_build_object(
    'qualification_code',q.qualification_code,'qualification_name',q.qualification_name)
    ORDER BY q.qualification_code COLLATE "C",q.qualification_name COLLATE "C"),'[]'::jsonb)
    FROM quals q WHERE q.competency_code=pg.competency_code))
   ORDER BY pg.postings DESC,pg.links DESC,pg.competency_code COLLATE "C"),'[]'::jsonb)
   FROM page pg)
 INTO total_count,review_counts,result_items;
 RETURN jsonb_build_object('contract_version','hop-live-ncs-demand-v1',
  'sources',source_items,'review',jsonb_build_object('link_reviewer_kinds',review_counts),
  'filters',jsonb_build_object('ncs_prefix',prefix),
  'limit',page_size,'offset',page_offset,'total',total_count,'items',result_items);
END $$;

REVOKE ALL ON FUNCTION catalog._live_link_item_source(text,jsonb,text),
  catalog._live_link_publications_with_provenance(),
 catalog.live_ncs_demand_v1(text,integer,integer) FROM PUBLIC;
COMMIT;
