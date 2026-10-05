BEGIN;

-- The MATERIALIZED CTE in ingestion.job_posting parses all runs before run_id filtering;
-- assemble only the already-pinned READY run to keep live reads bounded.
CREATE OR REPLACE FUNCTION catalog._live_job_postings(run text)
RETURNS TABLE(posting_id text,normalized jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH grouped AS (
  SELECT r.normalized->>'posting_id' AS posting_id,
   (array_agg(r.normalized) FILTER (WHERE r.normalized->>'representation'='list'))[1] AS list_value,
   (array_agg(r.normalized) FILTER (WHERE r.normalized->>'representation'='detail'))[1] AS detail_value
  FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
  WHERE r.run_id=$1 AND d.selected GROUP BY 1
 )
 SELECT posting_id,(list_value||jsonb_strip_nulls(detail_value))-'representation' AS normalized
 FROM grouped WHERE list_value IS NOT NULL AND detail_value IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION catalog._live_parts(value text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT coalesce(jsonb_agg(part ORDER BY ordinal),'[]'::jsonb)
 FROM unnest(string_to_array(value,',')) WITH ORDINALITY AS words(word,ordinal)
 CROSS JOIN LATERAL (SELECT nullif(btrim(word),'') AS part) cleaned
 WHERE part IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION catalog._live_categories(codes text,names text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object('code',nullif(btrim(code_list[i]),''),
  'name',nullif(btrim(name_list[i]),'')) ORDER BY i),'[]'::jsonb)
 FROM (SELECT string_to_array(codes,',') code_list,string_to_array(names,',') name_list) parts
 CROSS JOIN LATERAL generate_series(1,greatest(coalesce(array_length(code_list,1),0),
  coalesce(array_length(name_list,1),0))) AS indices(i)
$$;

CREATE OR REPLACE FUNCTION catalog._live_posting_item(value jsonb,posting text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('posting_id',posting,'title',value->>'title',
  'organization_code',value->>'organization_code','organization_name',value->>'organization_name',
  'date_posted',value->>'date_posted','closing_date',value->>'closing_date',
  'ongoing',(value->>'ongoing')::boolean,'regions',catalog._live_parts(value->>'regions'),
  'employment_types',catalog._live_parts(value->>'employment_type'),
  'recruitment_type',value->>'recruitment_type','education',value->>'education',
  'ncs_categories',catalog._live_categories(value->>'ncs_category_codes',value->>'ncs_category_names'),
  'headcount',(value->>'headcount')::integer,
  'source_url',CASE WHEN value->>'source_url' ~ '^https?://' THEN value->>'source_url' END)
$$;

CREATE OR REPLACE FUNCTION catalog._live_date(value text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT CASE WHEN value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN value END
$$;

CREATE OR REPLACE FUNCTION catalog.live_postings_v1(
 search text DEFAULT NULL,ncs_category text DEFAULT NULL,region text DEFAULT NULL,
 open_on date DEFAULT NULL,page_size integer DEFAULT 20,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE source_run ingestion.run%ROWTYPE; q text:=nullif(btrim(search),'');
 category text:=nullif(btrim(ncs_category),''); area text:=nullif(btrim(region),'');
 total_count bigint; result_items jsonb;
BEGIN
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_LIVE_PAGE'; END IF;
 IF length(q)>100 THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 SELECT * INTO source_run FROM ingestion.latest_ready_run WHERE source_id='job_alio';
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 WITH filtered AS (
  SELECT p.posting_id,p.normalized,p.normalized->>'closing_date' AS closing,
   catalog._live_parts(p.normalized->>'regions') AS regions,
   catalog._live_categories(p.normalized->>'ncs_category_codes',p.normalized->>'ncs_category_names') AS categories
  FROM catalog._live_job_postings(source_run.run_id) p
 ), matching AS (
  SELECT * FROM filtered f WHERE
   (q IS NULL OR strpos(lower(coalesce(f.normalized->>'title','')),lower(q))>0
    OR strpos(lower(coalesce(f.normalized->>'organization_name','')),lower(q))>0)
   AND (category IS NULL OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.categories) cat
    WHERE lower(cat->>'code')=lower(category) OR cat->>'name'=category))
   AND (area IS NULL OR f.regions ? area)
   AND (open_on IS NULL OR ((f.closing IS NULL OR f.closing::date>=open_on)
    AND (f.normalized->>'date_posted' IS NULL OR (f.normalized->>'date_posted')::date<=open_on)))
 ), page AS (
  SELECT * FROM matching ORDER BY closing::date ASC NULLS LAST,posting_id COLLATE "C" ASC
  LIMIT page_size OFFSET page_offset
 )
 SELECT (SELECT count(*) FROM matching),
  (SELECT coalesce(jsonb_agg(catalog._live_posting_item(normalized,posting_id)
   ORDER BY closing::date ASC NULLS LAST,posting_id COLLATE "C" ASC),'[]'::jsonb) FROM page)
 INTO total_count,result_items;
 RETURN jsonb_build_object('contract_version','hop-live-source-v1',
  'sources',jsonb_build_array(jsonb_build_object('source_id','job_alio','run_id',source_run.run_id,
   'data_as_of',source_run.completed_at)),
  'filters',jsonb_build_object('q',q,'ncs_category',category,'region',area,'open_on',open_on),
  'limit',page_size,'offset',page_offset,'total',total_count,'items',result_items);
END $$;

CREATE OR REPLACE FUNCTION catalog.live_posting_v1(posting_choice text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE source_run ingestion.run%ROWTYPE; chosen text:=nullif(btrim(posting_choice),'');
 item jsonb;
BEGIN
 IF chosen IS NULL THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 SELECT * INTO source_run FROM ingestion.latest_ready_run WHERE source_id='job_alio';
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 SELECT catalog._live_posting_item(p.normalized,p.posting_id) INTO item
 FROM catalog._live_job_postings(source_run.run_id) p WHERE p.posting_id=chosen;
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_POSTING_NOT_FOUND'; END IF;
 RETURN jsonb_build_object('contract_version','hop-live-source-v1',
  'sources',jsonb_build_array(jsonb_build_object('source_id','job_alio','run_id',source_run.run_id,
   'data_as_of',source_run.completed_at)),'item',item);
END $$;

CREATE OR REPLACE FUNCTION catalog.live_exam_sessions_v1(
 qualification text DEFAULT NULL,from_date date DEFAULT NULL,to_date date DEFAULT NULL,
 page_size integer DEFAULT 20,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE exam_run ingestion.run%ROWTYPE; qual_run ingestion.run%ROWTYPE;
 term text:=nullif(btrim(qualification),''); source_items jsonb;
 total_count bigint; result_items jsonb;
BEGIN
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_LIVE_PAGE'; END IF;
 IF length(term)>100 OR from_date>to_date THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 SELECT * INTO exam_run FROM ingestion.latest_ready_run WHERE source_id='qnet_schedule';
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 SELECT * INTO qual_run FROM ingestion.latest_ready_run WHERE source_id='ncs_qualification';
 source_items:=jsonb_build_array(jsonb_build_object('source_id','qnet_schedule',
  'run_id',exam_run.run_id,'data_as_of',exam_run.completed_at));
 IF qual_run.run_id IS NOT NULL THEN
  source_items:=source_items||jsonb_build_array(jsonb_build_object('source_id','ncs_qualification',
   'run_id',qual_run.run_id,'data_as_of',qual_run.completed_at));
 END IF;
 WITH qualification_names AS (
  SELECT qualification_code,min(qualification_name) AS qualification_name
  FROM ingestion.qualification_mapping WHERE run_id=qual_run.run_id GROUP BY qualification_code
 ), sessions AS (
  SELECT s.qualification_code,n.qualification_name,s.year,s.round,s.category_code,s.name,
   jsonb_build_object('registration_start',catalog._live_date(s.dates->>'docRegStartDt'),
    'registration_end',catalog._live_date(s.dates->>'docRegEndDt'),
    'exam_start',catalog._live_date(s.dates->>'docExamStartDt'),
    'exam_end',catalog._live_date(s.dates->>'docExamEndDt'),
    'result_date',catalog._live_date(s.dates->>'docPassDt')) AS written,
   jsonb_build_object('registration_start',catalog._live_date(s.dates->>'pracRegStartDt'),
    'registration_end',catalog._live_date(s.dates->>'pracRegEndDt'),
    'exam_start',catalog._live_date(s.dates->>'pracExamStartDt'),
    'exam_end',catalog._live_date(s.dates->>'pracExamEndDt'),
    'result_date',catalog._live_date(s.dates->>'pracPassDt')) AS practical
  FROM ingestion.exam_session s LEFT JOIN qualification_names n USING(qualification_code)
  WHERE s.run_id=exam_run.run_id
 ), dated AS (
  SELECT s.*, (SELECT min(value #>> '{}') FROM (
    SELECT value FROM jsonb_each(s.written)
    UNION ALL SELECT value FROM jsonb_each(s.practical)) dates
   WHERE jsonb_typeof(value)='string') AS earliest
  FROM sessions s
 ), matching AS (
  SELECT * FROM dated d WHERE
   (term IS NULL OR d.qualification_code=term OR
    strpos(lower(coalesce(d.qualification_name,'')),lower(term))>0)
   AND ((from_date IS NULL AND to_date IS NULL) OR EXISTS (
    SELECT 1 FROM (SELECT value FROM jsonb_each(d.written)
     UNION ALL SELECT value FROM jsonb_each(d.practical)) all_dates
    WHERE jsonb_typeof(value)='string' AND
     (from_date IS NULL OR (value #>> '{}')>=from_date::text) AND
     (to_date IS NULL OR (value #>> '{}')<=to_date::text)))
 ), page AS (
  SELECT * FROM matching ORDER BY earliest ASC NULLS LAST,
   qualification_code COLLATE "C",year,round,category_code COLLATE "C"
  LIMIT page_size OFFSET page_offset
 )
 SELECT (SELECT count(*) FROM matching),
  (SELECT coalesce(jsonb_agg(jsonb_build_object('qualification_code',qualification_code,
   'qualification_name',qualification_name,'year',year,'round',round,
   'category_code',category_code,'name',name,'written',written,'practical',practical)
   ORDER BY earliest ASC NULLS LAST,qualification_code COLLATE "C",year,round,
    category_code COLLATE "C"),'[]'::jsonb) FROM page)
 INTO total_count,result_items;
 RETURN jsonb_build_object('contract_version','hop-live-source-v1','sources',source_items,
  'filters',jsonb_build_object('qualification',term,'from',from_date,'to',to_date),
  'limit',page_size,'offset',page_offset,'total',total_count,'items',result_items);
END $$;

REVOKE ALL ON FUNCTION catalog._live_job_postings(text),catalog._live_parts(text),catalog._live_categories(text,text),
 catalog._live_posting_item(jsonb,text),catalog._live_date(text),
 catalog.live_postings_v1(text,text,text,date,integer,integer),catalog.live_posting_v1(text),
 catalog.live_exam_sessions_v1(text,date,date,integer,integer) FROM PUBLIC;
COMMIT;
