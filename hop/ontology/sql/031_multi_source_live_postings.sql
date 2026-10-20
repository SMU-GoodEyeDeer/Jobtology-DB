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


-- Preserve each accepted JobKorea delta observation until a later accepted row
-- for the same native ID replaces it. An omitted row is not source closure.
-- Other sources retain their latest READY complete-snapshot contract.
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

-- Validate calendar values before casts; malformed evidence stays unknown.
CREATE OR REPLACE FUNCTION catalog._live_date(value text) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF value !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN RETURN NULL; END IF;
 RETURN (value::date)::text;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION catalog._live_instant(value text) RETURNS timestamptz
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF value !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$' THEN RETURN NULL; END IF;
 RETURN value::timestamptz;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION catalog._live_posting_open(value jsonb,on_day date) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT coalesce(value->>'source_status','UNKNOWN')<>'CLOSED'
  AND (catalog._live_date(value->>'application_start_date') IS NULL
   OR catalog._live_date(value->>'application_start_date')::date<=on_day)
  AND (catalog._live_instant(value->>'application_start_at') IS NULL
   OR catalog._live_instant(value->>'application_start_at')<((on_day+1)::timestamp AT TIME ZONE 'Asia/Seoul'))
  AND (catalog._live_date(coalesce(value->>'deadline_date',value->>'closing_date')) IS NULL
   OR catalog._live_date(coalesce(value->>'deadline_date',value->>'closing_date'))::date>=on_day)
  AND (catalog._live_instant(value->>'deadline_at') IS NULL
   OR catalog._live_instant(value->>'deadline_at')>=(on_day::timestamp AT TIME ZONE 'Asia/Seoul'))
$$;

CREATE OR REPLACE FUNCTION catalog._live_source_posting_item(
 value jsonb,posting text,source text,observation_run text,observed_at timestamptz)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH cleaned AS (
  SELECT catalog._live_date(value->>'date_posted') AS posted,
   coalesce(catalog._live_date(coalesce(value->>'deadline_date',value->>'closing_date')),
    (catalog._live_instant(value->>'deadline_at') AT TIME ZONE 'Asia/Seoul')::date::text) AS closing,
   CASE WHEN source='jobkorea' THEN
    CASE WHEN value->>'source_status'='CLOSED' THEN false
     WHEN NOT catalog._live_posting_open(value,(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date) THEN false
     WHEN catalog._live_instant(value->>'application_start_at')>CURRENT_TIMESTAMP THEN false
     WHEN catalog._live_instant(value->>'deadline_at')<CURRENT_TIMESTAMP THEN false
     WHEN value->>'deadline_kind' IN ('ROLLING','UNTIL_FILLED','FIXED_DATE','FIXED_INSTANT') THEN true END
    ELSE (value->>'ongoing')::boolean END AS ongoing
 ) SELECT catalog._live_posting_item(value||jsonb_build_object('date_posted',posted,
   'closing_date',closing,'ongoing',ongoing),posting)||jsonb_build_object(
  'source_id',source,'source_status',value->>'source_status',
  'deadline_kind',value->>'deadline_kind','deadline_basis',value->>'deadline_basis',
  'deadline_raw',value->>'deadline_raw',
  'application_start_date',catalog._live_date(value->>'application_start_date'),
  'application_start_at',catalog._live_instant(value->>'application_start_at'),
  'deadline_at',catalog._live_instant(value->>'deadline_at'),
  'ongoing_basis',CASE WHEN source='jobkorea' AND ongoing IS NOT NULL
   THEN CASE WHEN value->>'source_status'='CLOSED' THEN 'SOURCE_STATUS'
    WHEN value->>'deadline_basis'='USER_POLICY' THEN 'USER_POLICY' ELSE 'SOURCE_DATE_POLICY' END
   WHEN value ? 'ongoing' THEN 'SOURCE_NORMALIZATION' END,
  'source_provenance',jsonb_build_object('source_id',source,'run_id',observation_run,'data_as_of',observed_at))
 FROM cleaned
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
 WITH observations AS MATERIALIZED (SELECT * FROM catalog._live_source_observations()),
 matching AS MATERIALIZED (
  SELECT p.*,coalesce(catalog._live_date(coalesce(p.normalized->>'deadline_date',p.normalized->>'closing_date')),
   (catalog._live_instant(p.normalized->>'deadline_at') AT TIME ZONE 'Asia/Seoul')::date::text) AS closing
  FROM observations p WHERE
   (q IS NULL OR strpos(lower(coalesce(p.normalized->>'title','')),lower(q))>0
    OR strpos(lower(coalesce(p.normalized->>'organization_name','')),lower(q))>0)
   AND (category IS NULL OR EXISTS (SELECT 1 FROM jsonb_array_elements(
    catalog._live_categories(p.normalized->>'ncs_category_codes',p.normalized->>'ncs_category_names')) cat
    WHERE lower(cat->>'code')=lower(category) OR cat->>'name'=category))
   AND (area IS NULL OR catalog._live_parts(p.normalized->>'regions') ? area)
   AND (open_on IS NULL OR catalog._live_posting_open(
    CASE WHEN p.source_id='jobkorea' THEN p.normalized ELSE
     p.normalized||jsonb_build_object('application_start_date',p.normalized->>'date_posted') END,open_on))
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
 RETURN jsonb_build_object('contract_version','hop-live-source-v1','sources',source_items,
  'filters',jsonb_build_object('q',q,'ncs_category',category,'region',area,'open_on',open_on),
  'limit',page_size,'offset',page_offset,'total',total_count,'items',result_items);
END $$;

CREATE OR REPLACE FUNCTION catalog.live_posting_v1(posting_choice text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE chosen text:=nullif(btrim(posting_choice),''); chosen_source text; item jsonb; source_items jsonb;
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
 RETURN jsonb_build_object('contract_version','hop-live-source-v1','sources',source_items,'item',item);
END $$;

REVOKE ALL ON FUNCTION catalog._live_source_postings(text,text),catalog._live_source_observations(),
 catalog._live_instant(text),catalog._live_posting_open(jsonb,date),
 catalog._live_source_posting_item(jsonb,text,text,text,timestamptz),
 catalog.live_postings_v1(text,text,text,date,integer,integer),catalog.live_posting_v1(text) FROM PUBLIC;
COMMIT;
