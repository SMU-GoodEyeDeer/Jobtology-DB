BEGIN;

-- Keep ALIO's paired-record reader unchanged for other catalog consumers.
-- JobKorea local listings are valid metadata even when source content is absent.
CREATE OR REPLACE FUNCTION catalog._live_source_postings(run text,source text)
RETURNS TABLE(posting_id text,normalized jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT p.posting_id,p.normalized FROM catalog._live_job_postings($1) p
 WHERE $2='job_alio'
 UNION ALL
 SELECT 'jobkorea:'||(r.normalized->>'posting_id'),r.normalized
 FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
 WHERE $2='jobkorea' AND r.run_id=$1 AND d.selected
  AND r.normalized->>'kind'='JobPosting'
  AND r.normalized->>'representation'='local_listing'
  AND r.normalized->'metadata_accepted'='true'::jsonb
  AND nullif(r.normalized->>'posting_id','') IS NOT NULL
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
 IF length(q)>100 THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 WITH source_runs AS MATERIALIZED (
  SELECT source_id,run_id,completed_at,CASE source_id WHEN 'jobkorea' THEN 0 ELSE 1 END priority
  FROM ingestion.latest_ready_run WHERE source_id IN ('jobkorea','job_alio')
 ), filtered AS (
  SELECT s.source_id,s.priority,p.posting_id,
   p.normalized||jsonb_build_object('closing_date',catalog._live_date(p.normalized->>'closing_date'),
    'date_posted',catalog._live_date(p.normalized->>'date_posted')) AS normalized,
   catalog._live_date(p.normalized->>'closing_date') AS closing,
   catalog._live_date(CASE WHEN s.source_id='jobkorea'
    THEN p.normalized->>'application_start_date' ELSE p.normalized->>'date_posted' END) AS opens,
   catalog._live_parts(p.normalized->>'regions') AS regions,
   catalog._live_categories(p.normalized->>'ncs_category_codes',p.normalized->>'ncs_category_names') AS categories
  FROM source_runs s CROSS JOIN LATERAL catalog._live_source_postings(s.run_id,s.source_id) p
 ), matching AS (
  SELECT * FROM filtered f WHERE
   (q IS NULL OR strpos(lower(coalesce(f.normalized->>'title','')),lower(q))>0
    OR strpos(lower(coalesce(f.normalized->>'organization_name','')),lower(q))>0)
   AND (category IS NULL OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.categories) cat
    WHERE lower(cat->>'code')=lower(category) OR cat->>'name'=category))
   AND (area IS NULL OR f.regions ? area)
   AND (open_on IS NULL OR ((f.closing IS NULL OR f.closing::date>=open_on)
    AND (f.opens IS NULL OR f.opens::date<=open_on)))
 ), page AS (
  SELECT * FROM matching ORDER BY priority,closing::date ASC NULLS LAST,posting_id COLLATE "C" ASC
  LIMIT page_size OFFSET page_offset
 )
 SELECT (SELECT jsonb_agg(jsonb_build_object('source_id',source_id,'run_id',run_id,
   'data_as_of',completed_at) ORDER BY priority) FROM source_runs),
  (SELECT count(*) FROM matching),
  (SELECT coalesce(jsonb_agg(catalog._live_posting_item(normalized,posting_id)||
   jsonb_build_object('source_id',source_id)
   ORDER BY priority,closing::date ASC NULLS LAST,posting_id COLLATE "C" ASC),'[]'::jsonb) FROM page)
 INTO source_items,total_count,result_items;
 IF source_items IS NULL THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 RETURN jsonb_build_object('contract_version','hop-live-source-v1','sources',source_items,
  'filters',jsonb_build_object('q',q,'ncs_category',category,'region',area,'open_on',open_on),
  'limit',page_size,'offset',page_offset,'total',total_count,'items',result_items);
END $$;

CREATE OR REPLACE FUNCTION catalog.live_posting_v1(posting_choice text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE source_run ingestion.run%ROWTYPE; chosen text:=nullif(btrim(posting_choice),'');
 chosen_source text; item jsonb;
BEGIN
 IF chosen IS NULL THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 chosen_source:=CASE WHEN starts_with(chosen,'jobkorea:') THEN 'jobkorea' ELSE 'job_alio' END;
 -- Reject unsupported namespaces independently of which supported sources are READY.
 IF strpos(chosen,':')>0 AND chosen_source='job_alio'
 THEN RAISE EXCEPTION 'LIVE_POSTING_NOT_FOUND'; END IF;
 SELECT * INTO source_run FROM ingestion.latest_ready_run WHERE source_id=chosen_source;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 SELECT catalog._live_posting_item(p.normalized||jsonb_build_object(
   'closing_date',catalog._live_date(p.normalized->>'closing_date'),
   'date_posted',catalog._live_date(p.normalized->>'date_posted')),p.posting_id)||
  jsonb_build_object('source_id',chosen_source) INTO item
 FROM catalog._live_source_postings(source_run.run_id,chosen_source) p WHERE p.posting_id=chosen;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_POSTING_NOT_FOUND'; END IF;
 RETURN jsonb_build_object('contract_version','hop-live-source-v1',
  'sources',jsonb_build_array(jsonb_build_object('source_id',chosen_source,'run_id',source_run.run_id,
   'data_as_of',source_run.completed_at)),'item',item);
END $$;

REVOKE ALL ON FUNCTION catalog._live_source_postings(text,text),
 catalog.live_postings_v1(text,text,text,date,integer,integer),catalog.live_posting_v1(text) FROM PUBLIC;
COMMIT;
