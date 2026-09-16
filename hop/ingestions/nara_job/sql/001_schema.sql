-- Additive migration for the 나라일터 (PblJobService) Hop ingestion.
-- Install after docs/hop-migration/schema.sql and checks.sql.
BEGIN;

ALTER TABLE ingestion.run DROP CONSTRAINT IF EXISTS run_source_id_check;
ALTER TABLE ingestion.run ADD CONSTRAINT run_source_id_check CHECK (source_id IN (
  'alio_organization','job_alio','nara_job','ncs_career_path',
  'ncs_competency','ncs_qualification','qnet_schedule'));

CREATE OR REPLACE FUNCTION ingestion.nara_date(value text) RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE digits text:=regexp_replace(coalesce(value,''),'[^0-9]','','g');
BEGIN
 IF length(digits)<>8 THEN RETURN NULL; END IF;
 RETURN to_date(digits,'YYYYMMDD');
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION ingestion.nara_array(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE jsonb_typeof(value)
   WHEN 'array' THEN value WHEN 'object' THEN jsonb_build_array(value)
   ELSE '[]'::jsonb END
$$;

-- Validate an archived JSON response and atomically select it into the ledger.
-- Detail/position/file responses become one representation row even when their
-- nested item array is empty, preserving the fact that the endpoint was checked.
CREATE OR REPLACE FUNCTION ingestion.load_nara_document(
 p_run_id text,p_document_id text,p_body jsonb,p_max_pages integer,p_max_requests integer,p_mode text)
RETURNS TABLE(document_selected boolean,item_count integer,provider_result text,error_code text)
LANGUAGE plpgsql AS $$
DECLARE d ingestion.document%ROWTYPE; part ingestion.partition%ROWTYPE;
 header jsonb; body jsonb; items jsonb; resource text; as_of date; total integer; page integer; size integer;
 expected integer; rec jsonb; pos integer; posting text; normalized jsonb; err text;
BEGIN
 SELECT * INTO STRICT d FROM ingestion.document WHERE run_id=p_run_id AND document_id=p_document_id FOR UPDATE;
 SELECT * INTO STRICT part FROM ingestion.partition WHERE run_id=p_run_id AND partition_id=d.partition_id;
 IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=p_run_id AND source_id='nara_job' AND state='LOADING')
 THEN RAISE EXCEPTION 'NARA_RUN_NOT_LOADING'; END IF;
 header:=p_body#>'{response,header}'; body:=p_body#>'{response,body}';
 resource:=coalesce(part.request_context->>'resource','list');
 as_of:=coalesce(ingestion.nara_date(part.request_context->>'as_of'),current_date);
 provider_result:=header->>'resultCode';
 IF d.http_status<>200 THEN err:='HTTP_STATUS';
 ELSIF jsonb_typeof(p_body)<>'object' OR jsonb_typeof(header)<>'object' OR provider_result IS DISTINCT FROM '00' THEN err:='INVALID_PROVIDER_RESULT';
 ELSIF d.byte_length<=0 OR d.byte_length>67108864 THEN err:='INVALID_RESPONSE_SIZE';
 ELSIF jsonb_typeof(body)<>'object' THEN err:='INVALID_ENVELOPE'; END IF;

 IF err IS NULL AND resource='list' THEN
   BEGIN total:=(body->>'totalCount')::integer; page:=(body->>'pageNo')::integer; size:=(body->>'numOfRows')::integer;
   EXCEPTION WHEN others THEN err:='INVALID_PAGING_METADATA'; END;
   items:=ingestion.nara_array(body#>'{items,item}');
   IF err IS NULL AND (total<0 OR page<>d.page_no OR size<>part.page_size) THEN err:='PAGING_METADATA_MISMATCH'; END IF;
   expected:=greatest(0,least(part.page_size,total-(d.page_no-1)*part.page_size));
   IF err IS NULL AND jsonb_array_length(items)<>expected THEN err:='PAGE_ROW_COUNT_MISMATCH'; END IF;
   IF err IS NULL AND (ceil(total::numeric/part.page_size)>p_max_pages OR
       (ceil(total::numeric/part.page_size)+3*jsonb_array_length(items))>p_max_requests) THEN err:='REQUEST_BUDGET_EXCEEDED'; END IF;
 ELSE
   total:=1; page:=1; size:=1; items:=CASE resource
     WHEN 'detail' THEN ingestion.nara_array(body->'item')
     ELSE ingestion.nara_array(body#>'{items,item}') END;
 END IF;
 item_count:=CASE WHEN resource='list' THEN coalesce(jsonb_array_length(items),0) ELSE 1 END;

 UPDATE ingestion.document SET declared_total=total,effective_page=d.page_no,
   effective_page_size=part.page_size,item_count=load_nara_document.item_count,
   provider_result=load_nara_document.provider_result,
   selected=(err IS NULL) WHERE run_id=p_run_id AND document_id=p_document_id;
 IF err IS NOT NULL THEN error_code:=err; RETURN NEXT; RETURN; END IF;
 IF resource='list' AND part.expected_total IS NULL THEN
   UPDATE ingestion.partition SET expected_total=total WHERE run_id=p_run_id AND partition_id=part.partition_id;
 END IF;

 IF resource='list' THEN
   FOR rec,pos IN SELECT value,ordinality::integer FROM jsonb_array_elements(items) WITH ORDINALITY LOOP
     posting:=nullif(btrim(rec->>'idx'),'');
     normalized:=jsonb_strip_nulls(jsonb_build_object(
       'kind','JobPosting','posting_id',posting,'representation','list','title',nullif(btrim(rec->>'title'),''),
       'organization_name',nullif(btrim(rec->>'insttname'),''),'date_posted',ingestion.nara_date(rec->>'regdate'),
       'modified_date',ingestion.nara_date(rec->>'moddate'),'closing_date',ingestion.nara_date(rec->>'enddate'),
       'ongoing',coalesce(ingestion.nara_date(rec->>'enddate')>=as_of,false),
       'regions',nullif(btrim(rec->>'areacode'),''),'posting_type_code',rec->>'type01',
       'institution_type_code',rec->>'type02','source_url','https://www.gojobs.go.kr/apmView.do?empmnsn='||posting));
     IF posting IS NULL OR normalized->>'title' IS NULL OR normalized->>'organization_name' IS NULL
       OR normalized->>'date_posted' IS NULL OR normalized->>'closing_date' IS NULL THEN
       INSERT INTO ingestion.rejected_row VALUES(p_run_id,p_document_id,'/response/body/items/item/'||(pos-1),'INVALID_NARA_LIST_ROW',rec)
       ON CONFLICT DO NOTHING;
     ELSE
       INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags)
       VALUES(p_run_id,p_document_id,'/response/body/items/item/'||(pos-1),posting||':list',rec,normalized,
         '{"provider_type_mapping":"live API values: type01=posting type, type02=institution type"}'::jsonb,'[]')
       ON CONFLICT(run_id,document_id,locator) DO UPDATE SET source_payload=excluded.source_payload,normalized=excluded.normalized;
     END IF;
   END LOOP;
 ELSE
   posting:=part.request_context->>'idx';
   IF resource='detail' THEN
     rec:=coalesce(items->0,'{}'::jsonb);
     normalized:=jsonb_strip_nulls(jsonb_build_object(
       'kind','JobPosting','posting_id',posting,'representation','detail','title',nullif(btrim(rec->>'title'),''),
       'description_text',nullif(btrim(regexp_replace(coalesce(rec->>'contents',''),'<[^>]*>',' ','g')),''),
       'source_links',jsonb_strip_nulls(jsonb_build_array(rec->>'link01',rec->>'link02',rec->>'link03')),
       'source_url','https://www.gojobs.go.kr/apmView.do?empmnsn='||posting));
   ELSIF resource='positions' THEN
     normalized:=jsonb_build_object('kind','JobPosting','posting_id',posting,'representation','positions','positions',items,
       'duties_text',(SELECT nullif(string_agg(x->>'name',E'\n'),'') FROM jsonb_array_elements(items) x));
     rec:=jsonb_build_object('items',items);
   ELSE
     normalized:=jsonb_build_object('kind','JobPosting','posting_id',posting,'representation','files','attachment_refs',
       (SELECT coalesce(jsonb_agg(jsonb_strip_nulls(jsonb_build_object('name',x->>'filename','size',x->>'filesize',
         'sort',x->>'sort','url','https://www.gojobs.go.kr/'||ltrim(x->>'filepath','/'))) ORDER BY x->>'sort'),'[]') FROM jsonb_array_elements(items) x));
     rec:=jsonb_build_object('items',items);
   END IF;
   INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags)
   VALUES(p_run_id,p_document_id,'/response/body',posting||':'||resource,rec,normalized,'{}','[]')
   ON CONFLICT(run_id,document_id,locator) DO UPDATE SET source_payload=excluded.source_payload,normalized=excluded.normalized;
 END IF;
 document_selected:=true; error_code:=NULL; RETURN NEXT;
END $$;

CREATE OR REPLACE VIEW ingestion.nara_posting_representation AS
SELECT r.run_id,r.document_id,r.locator,r.source_payload,r.normalized,n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
 posting_id text,representation text,title text,organization_name text,date_posted date,
 modified_date date,closing_date date,ongoing boolean,source_url text,regions text,
 recruitment_type text,description_text text,positions jsonb,attachment_refs jsonb,source_links jsonb)
WHERE r.source_id='nara_job';

CREATE OR REPLACE VIEW ingestion.nara_job_posting AS
WITH representations AS MATERIALIZED (SELECT * FROM ingestion.nara_posting_representation),
active_list AS (SELECT * FROM representations WHERE representation='list' AND ongoing)
SELECT l.run_id,l.posting_id,l.document_id AS list_document_id,l.locator AS list_locator,
 d.document_id AS detail_document_id,d.locator AS detail_locator,
 (l.normalized||jsonb_strip_nulls(d.normalized)||jsonb_strip_nulls(p.normalized)||jsonb_strip_nulls(f.normalized))-'representation' AS normalized,
 jsonb_build_object('list_document_id',l.document_id,'list_locator',l.locator,'detail_document_id',d.document_id,
  'detail_locator',d.locator,'positions_document_id',p.document_id,'files_document_id',f.document_id) AS field_origin
FROM active_list l JOIN representations d ON d.run_id=l.run_id AND d.posting_id=l.posting_id AND d.representation='detail'
JOIN representations p ON p.run_id=l.run_id AND p.posting_id=l.posting_id AND p.representation='positions'
JOIN representations f ON f.run_id=l.run_id AND f.posting_id=l.posting_id AND f.representation='files';

CREATE OR REPLACE VIEW ingestion.llm_posting AS
SELECT 'job_alio'::text AS source_id,p.run_id,p.posting_id,p.normalized
FROM ingestion.job_posting p
UNION ALL
SELECT 'nara_job',p.run_id,'ext-nara_job-'||encode(sha256(convert_to(p.posting_id,'UTF8')),'hex'),p.normalized
FROM ingestion.nara_job_posting p;

COMMIT;
