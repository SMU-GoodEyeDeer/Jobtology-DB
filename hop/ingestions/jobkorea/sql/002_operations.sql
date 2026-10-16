-- Deterministic normalization and local import; no source requests or paid APIs.
BEGIN;

CREATE OR REPLACE FUNCTION ingestion.jobkorea_date(value jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE raw text; day date; instant timestamptz;
BEGIN
 IF value IS NULL OR value='null'::jsonb THEN RETURN '{"present":false}'; END IF;
 IF jsonb_typeof(value)<>'string' THEN RETURN '{"present":true,"error":"INVALID_DATE_TYPE"}'; END IF;
 raw:=value#>>'{}';
 -- The supplied scraper encodes day values at midnight UTC. Retain the
 -- calendar date; the encoding does not establish source instant/timezone.
 IF raw ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}(T00:00:00(\.0+)?Z)?$' THEN
  BEGIN day:=left(raw,10)::date;
  EXCEPTION WHEN others THEN RETURN '{"present":true,"error":"INVALID_DATE"}'; END;
  IF to_char(day,'YYYY-MM-DD')<>left(raw,10) THEN RETURN '{"present":true,"error":"INVALID_DATE"}'; END IF;
  RETURN jsonb_build_object('present',true,'date',day,'precision','DAY','timezone',NULL,
   'encoding',CASE WHEN length(raw)>10 THEN 'MIDNIGHT_UTC_DATE_ENCODING' ELSE 'ISO_DATE' END);
 ELSIF raw ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
  BEGIN
   day:=left(raw,10)::date;
   IF substring(raw FROM 12 FOR 2)::integer>23 OR substring(raw FROM 15 FOR 2)::integer>59
    OR substring(raw FROM 18 FOR 2)::integer>59 THEN RETURN '{"present":true,"error":"INVALID_DATE"}'; END IF;
   instant:=raw::timestamptz;
  EXCEPTION WHEN others THEN RETURN '{"present":true,"error":"INVALID_DATE"}'; END;
  RETURN jsonb_build_object('present',true,'at',to_char(instant AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'precision','INSTANT','timezone',substring(raw FROM '(Z|[+-][0-9]{2}:[0-9]{2})$'),'encoding','EXPLICIT_OFFSET_TIMESTAMP');
 END IF;
 RETURN '{"present":true,"error":"INVALID_DATE"}';
END $$;

CREATE OR REPLACE FUNCTION ingestion.normalize_jobkorea_row(rec jsonb,loc text)
RETURNS TABLE(normalized jsonb,field_lineage jsonb,quality_flags jsonb,errors jsonb)
LANGUAGE plpgsql IMMUTABLE ROWS 1 AS $$
DECLARE native text; title text; company text; employer_kind text; role text;
 start_info jsonb; end_info jsonb; end_raw text; deadline_kind text; deadline_basis text;
 deadline_label text; status text; content text; content_status text; count_value integer;
 name text; value jsonb; mapped text; source_key text; err text;
BEGIN
 normalized:='{}'; field_lineage:='{}'; quality_flags:='[]'; errors:='[]';
 IF jsonb_typeof(rec) IS DISTINCT FROM 'object' THEN
  errors:=jsonb_build_array(jsonb_build_object('code','ROW_NOT_OBJECT','field','')); RETURN NEXT; RETURN;
 END IF;
 IF jsonb_typeof(rec->'product_page_url')='string' THEN
  native:=substring(rec->>'product_page_url' FROM
   '(?i)^https?://(?:www\.)?jobkorea\.co\.kr/Recruit/GI_Read/([0-9]+)(?:[/?#].*)?$');
 END IF;
 IF native IS NULL THEN errors:=errors||jsonb_build_array(jsonb_build_object('code','INVALID_POSTING_REFERENCE','field','product_page_url')); END IF;
 IF jsonb_typeof(rec->'job_title')='string' THEN title:=nullif(btrim(rec->>'job_title'),''); END IF;
 IF title IS NULL THEN errors:=errors||jsonb_build_array(jsonb_build_object('code','MISSING_OR_INVALID_TITLE','field','job_title')); END IF;
 IF rec ? 'company_name' AND rec->'company_name'<>'null'::jsonb AND jsonb_typeof(rec->'company_name')<>'string' THEN
  errors:=errors||jsonb_build_array(jsonb_build_object('code','INVALID_TEXT_TYPE','field','company_name'));
 END IF;
 company:=CASE WHEN jsonb_typeof(rec->'company_name')='string' THEN nullif(btrim(rec->>'company_name'),'') END;
 employer_kind:=CASE WHEN company IS NULL OR company IN('비공개','기업명 비공개','회사명 비공개','미공개','-','(주)','㈜') THEN 'UNKNOWN'
  WHEN company ~ '^(중소기업|중견기업|대기업|벤처기업|대기업 계열사.?자회사|외국계 기업|외국계기업|공기업|공공기관|비영리단체|협회|재단)([[:space:]]*\([^)]*\))?$'
   THEN 'CATEGORY_ONLY' ELSE 'NAME_UNVERIFIED' END;
 IF employer_kind='CATEGORY_ONLY' THEN quality_flags:=quality_flags||'"EMPLOYER_CATEGORY_ONLY"'::jsonb;
 ELSIF employer_kind='UNKNOWN' THEN quality_flags:=quality_flags||'"EMPLOYER_UNKNOWN"'::jsonb; END IF;

 status:=CASE WHEN rec->'is_closed'='true'::jsonb OR rec->'closed'='true'::jsonb OR
  upper(coalesce(rec->>'source_status',rec->>'status','')) IN('CLOSED','마감','채용마감','접수마감') THEN 'CLOSED' ELSE 'UNKNOWN' END;
 start_info:=ingestion.jobkorea_date(rec->'application_start_date');
 IF start_info ? 'error' THEN errors:=errors||jsonb_build_array(jsonb_build_object('code',start_info->>'error','field','application_start_date')); END IF;
 IF NOT coalesce((start_info->>'present')::boolean,false) THEN quality_flags:=quality_flags||'"APPLICATION_START_MISSING"'::jsonb; END IF;
 end_raw:=CASE WHEN jsonb_typeof(rec->'application_end_date')='string' THEN rec->>'application_end_date' END;
 IF rec->'application_end_date' IS NULL OR rec->'application_end_date'='null'::jsonb THEN
  end_info:='{}';
  IF status='CLOSED' THEN deadline_kind:='UNKNOWN'; deadline_basis:='SOURCE_STATUS';
  ELSE deadline_kind:='ROLLING'; deadline_basis:='USER_POLICY'; deadline_label:='상시채용';
   quality_flags:=quality_flags||'"DEADLINE_ASSUMED_ROLLING"'::jsonb; END IF;
 ELSIF end_raw IN('상시채용','상시','수시채용') THEN
  end_info:='{}'; deadline_kind:='ROLLING'; deadline_basis:='SOURCE_FIELD'; deadline_label:=end_raw;
 ELSIF end_raw IN('채용시까지','채용 시까지','채용시 마감','채용 시 마감') THEN
  end_info:='{}'; deadline_kind:='UNTIL_FILLED'; deadline_basis:='SOURCE_FIELD'; deadline_label:=end_raw;
 ELSE
  end_info:=ingestion.jobkorea_date(rec->'application_end_date');
  IF end_info ? 'error' THEN
   errors:=errors||jsonb_build_array(jsonb_build_object('code',end_info->>'error','field','application_end_date'));
   deadline_kind:='UNKNOWN'; deadline_basis:='INVALID_SOURCE_FIELD';
  ELSE deadline_kind:=CASE WHEN end_info ? 'date' THEN 'FIXED_DATE' ELSE 'FIXED_INSTANT' END; deadline_basis:='SOURCE_FIELD'; END IF;
 END IF;
 IF start_info ? 'date' AND end_info ? 'date' AND (end_info->>'date')::date<(start_info->>'date')::date THEN
  errors:=errors||jsonb_build_array(jsonb_build_object('code','END_BEFORE_START','field','application_end_date'));
 ELSIF start_info ? 'at' AND end_info ? 'at' AND (end_info->>'at')::timestamptz<(start_info->>'at')::timestamptz THEN
  errors:=errors||jsonb_build_array(jsonb_build_object('code','END_BEFORE_START','field','application_end_date'));
 END IF;
 role:=CASE WHEN jsonb_typeof(rec->'job_position')='string' THEN nullif(btrim(rec->>'job_position'),'') END;
 IF rec ? 'job_position' AND rec->'job_position'<>'null'::jsonb AND jsonb_typeof(rec->'job_position')<>'string' THEN
  errors:=errors||jsonb_build_array(jsonb_build_object('code','INVALID_TEXT_TYPE','field','job_position'));
 END IF;
 IF role IN('홈페이지 지원','홈페이지지원','온라인 지원','온라인지원','이메일 지원','이메일지원','방문 지원','방문지원') THEN
  quality_flags:=quality_flags||'"ROLE_IS_APPLICATION_METHOD"'::jsonb; role:=NULL;
 END IF;
 content:=CASE WHEN jsonb_typeof(rec->'description_text')='string' THEN nullif(btrim(rec->>'description_text'),'')
  WHEN jsonb_typeof(rec->'job_description_text')='string' THEN nullif(btrim(rec->>'job_description_text'),'') END;
 FOREACH name IN ARRAY ARRAY['description_text','job_description_text'] LOOP
  IF rec ? name AND rec->name<>'null'::jsonb AND jsonb_typeof(rec->name)<>'string' THEN
   errors:=errors||jsonb_build_array(jsonb_build_object('code','INVALID_TEXT_TYPE','field',name));
  END IF;
 END LOOP;
 content_status:=CASE WHEN content IS NULL THEN 'MISSING' ELSE 'TEXT_AVAILABLE' END;
 IF content IS NULL THEN quality_flags:=quality_flags||'"DESCRIPTION_MISSING"'::jsonb; END IF;
 IF rec ? 'recruitment_count' AND rec->'recruitment_count'<>'null'::jsonb THEN
  IF jsonb_typeof(rec->'recruitment_count')='number' AND rec->>'recruitment_count' ~ '^[0-9]+$' THEN
   BEGIN count_value:=(rec->>'recruitment_count')::integer;
   EXCEPTION WHEN others THEN err:='INVALID_RECRUITMENT_COUNT'; END;
  ELSE err:='INVALID_RECRUITMENT_COUNT'; END IF;
  IF err IS NOT NULL THEN errors:=errors||jsonb_build_array(jsonb_build_object('code',err,'field','recruitment_count')); END IF;
 END IF;
 normalized:=jsonb_build_object(
  'kind','JobPosting','posting_id',native,'native_posting_id',native,'representation','local_listing',
  'title',title,'company_name_raw',company,'employer_identity_kind',employer_kind,
  'organization_name',CASE WHEN employer_kind='NAME_UNVERIFIED' THEN company END,
  'source_url',CASE WHEN native IS NOT NULL THEN 'https://www.jobkorea.co.kr/Recruit/GI_Read/'||native END,
  'source_status',status,'application_start_date',start_info->'date','application_start_at',start_info->'at',
  'application_start_precision',start_info->'precision','application_start_timezone',start_info->'timezone',
  'deadline_kind',deadline_kind,'deadline_basis',deadline_basis,'deadline_raw',end_raw,'deadline_display_label',deadline_label,
  'deadline_date',end_info->'date','deadline_at',end_info->'at','deadline_precision',end_info->'precision',
  'deadline_timezone',end_info->'timezone','closing_date',end_info->'date',
  'content_status',content_status,'description_text',content,'extraction_eligible',content IS NOT NULL,'role',role,
  'job_position_raw',CASE WHEN jsonb_typeof(rec->'job_position')='string' THEN rec->>'job_position' END,
  'headcount',count_value,'scope','FILE_ONLY','provider_complete',false,
  'metadata_accepted',jsonb_array_length(errors)=0);
 -- Copy only supported scalar evidence; references/input remain raw evidence.
 FOR source_key,mapped IN SELECT * FROM (VALUES
  ('salary','salary_raw'),('experience_level','experience_raw'),('education_level','education'),
  ('employment_type','employment_type'),('work_location','regions'),('work_hours','work_hours'),
  ('company_size','company_size'),('company_type','company_type'),('industry','industry'),
  ('job_functions','job_functions'),('application_method','application_method'),('benefits','benefits_text')) x LOOP
  value:=rec->source_key;
  IF value IS NOT NULL AND value<>'null'::jsonb THEN
   IF jsonb_typeof(value)<>'string' THEN errors:=errors||jsonb_build_array(jsonb_build_object('code','INVALID_TEXT_TYPE','field',source_key));
   ELSE normalized:=normalized||jsonb_build_object(mapped,value);
    field_lineage:=field_lineage||jsonb_build_object(mapped,jsonb_build_object('locator',loc||'/'||source_key,'basis','SOURCE_FIELD')); END IF;
  END IF;
 END LOOP;
 IF rec ? 'company_benefits_tags' THEN
  value:=rec->'company_benefits_tags';
  IF jsonb_typeof(value)<>'array' OR EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(value)='array' THEN value ELSE '[]' END) x WHERE jsonb_typeof(x)<>'string')
  THEN errors:=errors||jsonb_build_array(jsonb_build_object('code','INVALID_BENEFITS_TAGS','field','company_benefits_tags'));
  ELSE normalized:=normalized||jsonb_build_object('benefits_tags',value); END IF;
 END IF;
 normalized:=normalized||jsonb_build_object('metadata_accepted',jsonb_array_length(errors)=0);
 field_lineage:=field_lineage||jsonb_build_object(
  'posting_id',jsonb_build_object('locator',loc||'/product_page_url','basis','LOCAL_REFERENCE_PARSE'),
  'title',jsonb_build_object('locator',loc||'/job_title','basis','SOURCE_FIELD'),
  'employer_identity_kind',jsonb_build_object('locator',loc||'/company_name','basis','LOCAL_CLASSIFICATION','verified',false),
  'deadline',jsonb_build_object('locator',loc||'/application_end_date','present',rec ? 'application_end_date',
    'basis',deadline_basis,'policy_revision',CASE WHEN deadline_basis='USER_POLICY' THEN '2026-10-07.1' END,
    'encoding',end_info->'encoding'),
  'application_start',jsonb_build_object('locator',loc||'/application_start_date','present',rec ? 'application_start_date','encoding',start_info->'encoding'),
  'content_status',jsonb_build_object('basis',CASE WHEN content IS NULL THEN 'LOCAL_CONTENT_ABSENT' ELSE 'SUPPLIED_TEXT' END));
 RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION ingestion.jobkorea_json_array_row_manifest(p_run_id text) RETURNS text
LANGUAGE sql STABLE AS $$
 SELECT encode(sha256(convert_to(jsonb_build_object(
  'records',(SELECT coalesce(jsonb_agg(jsonb_build_object('locator',r.locator,'source_record_id',r.source_record_id,
   'source_payload',r.source_payload,'normalized',r.normalized,'field_lineage',r.field_lineage,'quality_flags',r.quality_flags) ORDER BY r.locator),'[]')
   FROM ingestion.record r WHERE r.run_id=p_run_id),
  'rejected',(SELECT coalesce(jsonb_agg(to_jsonb(r)-'run_id'-'document_id' ORDER BY r.locator),'[]')
   FROM ingestion.rejected_row r WHERE r.run_id=p_run_id))::text,'UTF8')),'hex')
$$;

-- Dispatch dynamically so a canonical operations replay preserves the later
-- streaming implementation, while the original array digest stays byte-identical.
CREATE OR REPLACE FUNCTION ingestion.jobkorea_row_manifest(p_run_id text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE result text; format text;
BEGIN
 SELECT i.file_format INTO format FROM ingestion.jobkorea_import i WHERE i.run_id=p_run_id;
 IF format='NDJSON' THEN
  IF to_regprocedure('ingestion.jobkorea_ndjson_row_manifest(text)') IS NULL THEN
   RAISE EXCEPTION 'JOBKOREA_NDJSON_CONTRACT_NOT_INSTALLED';
  END IF;
  EXECUTE 'SELECT ingestion.jobkorea_ndjson_row_manifest($1)' INTO result USING p_run_id;
  RETURN result;
 END IF;
 RETURN ingestion.jobkorea_json_array_row_manifest(p_run_id);
END $$;

CREATE OR REPLACE FUNCTION ingestion.begin_jobkorea_import(
 p_sha256 text,p_byte_length bigint,p_raw_path text,p_received_at timestamptz,p_scraped_at timestamptz DEFAULT NULL)
RETURNS TABLE(run_id text,document_id text,reused boolean,state text)
LANGUAGE plpgsql AS $$
DECLARE chosen text; prior ingestion.jobkorea_import; prior_run ingestion.run;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF p_sha256 IS NULL OR p_sha256 !~ '^[0-9a-f]{64}$' OR p_byte_length IS NULL OR p_byte_length NOT BETWEEN 1 AND 67108864
  OR p_raw_path IS DISTINCT FROM 'jobkorea/'||p_sha256||'/source.json' OR p_received_at IS NULL
 THEN RAISE EXCEPTION 'INVALID_JOBKOREA_IMPORT_PARAMETERS'; END IF;
 chosen:='jobkorea-'||encode(sha256(convert_to('hop-jobkorea-v1:2026-10-07.1:'||p_sha256,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(chosen,0));
 SELECT * INTO prior FROM ingestion.jobkorea_import i WHERE i.run_id=chosen FOR UPDATE;
 IF FOUND THEN
  SELECT * INTO STRICT prior_run FROM ingestion.run u WHERE u.run_id=chosen FOR UPDATE;
  IF prior.file_sha256 IS DISTINCT FROM p_sha256 OR prior.byte_length IS DISTINCT FROM p_byte_length OR prior.raw_path IS DISTINCT FROM p_raw_path
   OR prior.scraped_at IS DISTINCT FROM p_scraped_at OR prior_run.source_id<>'jobkorea' OR prior_run.mode<>'REPLAY'
   OR prior_run.parser_version<>prior.parser_version OR prior_run.policy_revision<>prior.policy_revision
  THEN RAISE EXCEPTION 'JOBKOREA_IMPORT_CONFLICT'; END IF;
  run_id:=chosen; document_id:='local-json'; reused:=true; state:=prior_run.state; RETURN NEXT; RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ingestion.run u WHERE u.run_id=chosen) THEN RAISE EXCEPTION 'JOBKOREA_IMPORT_CONFLICT'; END IF;
 INSERT INTO ingestion.run(run_id,source_id,mode,parser_version,policy_revision)
 VALUES(chosen,'jobkorea','REPLAY','hop-jobkorea-v1','2026-10-07.1');
 INSERT INTO ingestion.jobkorea_import(run_id,file_sha256,byte_length,raw_path,parser_version,policy_revision,received_at,scraped_at)
 VALUES(chosen,p_sha256,p_byte_length,p_raw_path,'hop-jobkorea-v1','2026-10-07.1',p_received_at,p_scraped_at);
 INSERT INTO ingestion.partition(run_id,partition_id,kind,request_context,page_size)
 VALUES(chosen,'local-file','FILE','{"transport":"LOCAL_FILE","scope":"FILE_ONLY","provider_complete":false,"absence_is_closure":false}',1);
 INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,provider_result,retrieved_at,transport)
 VALUES(chosen,'local-json','local-file',1,p_raw_path,p_sha256,p_byte_length,'UTF-8',NULL,NULL,p_received_at,'LOCAL_FILE');
 run_id:=chosen; document_id:='local-json'; reused:=false; state:='LOADING'; RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION ingestion.load_jobkorea_document(p_run_id text,p_body text)
RETURNS TABLE(item_count integer,accepted_count integer,rejected_count integer,error_code text)
LANGUAGE plpgsql AS $$
DECLARE meta ingestion.jobkorea_import; run ingestion.run; body jsonb; rec jsonb; pos bigint;
 parsed record; issue jsonb; flag jsonb; rawhash text; scopes jsonb;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_run_id,0));
 SELECT * INTO STRICT run FROM ingestion.run WHERE run_id=p_run_id FOR UPDATE;
 SELECT * INTO STRICT meta FROM ingestion.jobkorea_import WHERE run_id=p_run_id FOR UPDATE;
 IF meta.file_format<>'JSON_ARRAY' THEN RAISE EXCEPTION 'JOBKOREA_ARRAY_LOADER_FORMAT_CONFLICT'; END IF;
 IF run.source_id<>'jobkorea' THEN RAISE EXCEPTION 'INVALID_JOBKOREA_RUN'; END IF;
 rawhash:=encode(sha256(convert_to(p_body,'UTF8')),'hex');
 IF p_body IS NULL OR rawhash IS DISTINCT FROM meta.file_sha256 OR octet_length(convert_to(p_body,'UTF8')) IS DISTINCT FROM meta.byte_length
 THEN RAISE EXCEPTION 'JOBKOREA_FILE_HASH_OR_SIZE_CONFLICT'; END IF;
 IF meta.loaded THEN
  SELECT d.item_count INTO item_count FROM ingestion.document d WHERE d.run_id=p_run_id AND d.document_id=meta.document_id;
  SELECT count(*)::integer INTO accepted_count FROM ingestion.record r WHERE r.run_id=p_run_id;
  SELECT count(*)::integer INTO rejected_count FROM ingestion.rejected_row r WHERE r.run_id=p_run_id;
  error_code:=NULL; RETURN NEXT; RETURN;
 END IF;
 IF run.state<>'LOADING' OR meta.error_code IS NOT NULL THEN RAISE EXCEPTION 'JOBKOREA_RUN_NOT_LOADING'; END IF;
 item_count:=0; accepted_count:=0; rejected_count:=0;
 IF NOT (p_body IS JSON ARRAY WITH UNIQUE KEYS) THEN
  error_code:='INVALID_JSON_ARRAY_OR_DUPLICATE_KEYS';
  INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,severity) VALUES(p_run_id,'',error_code,'ERROR');
  UPDATE ingestion.jobkorea_import SET error_code=load_jobkorea_document.error_code,processed_at=clock_timestamp() WHERE run_id=p_run_id;
  RETURN NEXT; RETURN;
 END IF;
 BEGIN body:=p_body::jsonb;
 EXCEPTION WHEN others THEN
  error_code:='INVALID_JSON_VALUE';
  INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,severity) VALUES(p_run_id,'',error_code,'ERROR');
  UPDATE ingestion.jobkorea_import SET error_code=load_jobkorea_document.error_code,processed_at=clock_timestamp() WHERE run_id=p_run_id;
  RETURN NEXT; RETURN;
 END;
 item_count:=jsonb_array_length(body);
 IF item_count=0 THEN
  error_code:='EMPTY_SUPPLIED_FILE';
  INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,severity) VALUES(p_run_id,'',error_code,'ERROR');
  UPDATE ingestion.jobkorea_import SET error_code=load_jobkorea_document.error_code,processed_at=clock_timestamp() WHERE run_id=p_run_id;
  RETURN NEXT; RETURN;
 END IF;
 FOR rec,pos IN SELECT value,ordinality-1 FROM jsonb_array_elements(body) WITH ORDINALITY LOOP
  SELECT * INTO STRICT parsed FROM ingestion.normalize_jobkorea_row(rec,'/'||pos);
  FOR issue IN SELECT value FROM jsonb_array_elements(parsed.errors) LOOP
   INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,field,severity)
   VALUES(p_run_id,'/'||pos,issue->>'code',issue->>'field','ERROR') ON CONFLICT DO NOTHING;
  END LOOP;
  FOR flag IN SELECT value FROM jsonb_array_elements(parsed.quality_flags) LOOP
   INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,severity)
   VALUES(p_run_id,'/'||pos,flag#>>'{}','WARNING') ON CONFLICT DO NOTHING;
  END LOOP;
  IF jsonb_array_length(parsed.errors)>0 THEN
   INSERT INTO ingestion.rejected_row(run_id,document_id,locator,error_code,source_payload)
   VALUES(p_run_id,meta.document_id,'/'||pos,'INVALID_JOBKOREA_ROW',rec);
   rejected_count:=rejected_count+1;
  ELSE
   INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags)
   VALUES(p_run_id,meta.document_id,'/'||pos,parsed.normalized->>'posting_id',rec,parsed.normalized,parsed.field_lineage,parsed.quality_flags);
   accepted_count:=accepted_count+1;
  END IF;
 END LOOP;
 SELECT jsonb_build_object('completeness','UNKNOWN','provider_complete',false,'absence_is_closure',false,
  'supplied_row_count',item_count,'max_pages',(SELECT jsonb_agg(DISTINCT x#>'{input,max_pages}') FROM jsonb_array_elements(body) x WHERE jsonb_typeof(x#>'{input,max_pages}')='number'),
  'job_category_codes',(SELECT jsonb_agg(DISTINCT x#>'{input,job_category_codes}') FROM jsonb_array_elements(body) x WHERE jsonb_typeof(x#>'{input,job_category_codes}')='string')) INTO scopes;
 UPDATE ingestion.partition SET expected_total=item_count,page_size=greatest(1,item_count)
 WHERE run_id=p_run_id AND partition_id='local-file';
 UPDATE ingestion.document SET selected=true,item_count=load_jobkorea_document.item_count,declared_total=load_jobkorea_document.item_count,
  effective_page=1,effective_page_size=greatest(1,load_jobkorea_document.item_count)
 WHERE run_id=p_run_id AND document_id=meta.document_id;
 UPDATE ingestion.jobkorea_import SET loaded=true,payload_sha256=rawhash,row_manifest_sha256=ingestion.jobkorea_row_manifest(p_run_id),
  processed_at=clock_timestamp(),collection_scope=scopes WHERE run_id=p_run_id;
 error_code:=NULL; RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION ingestion.verify_jobkorea_file(p_run_id text,p_sha256 text,p_byte_length bigint)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE meta ingestion.jobkorea_import; current_state text;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_run_id,0));
 SELECT state INTO STRICT current_state FROM ingestion.run WHERE run_id=p_run_id AND source_id='jobkorea' FOR UPDATE;
 SELECT * INTO STRICT meta FROM ingestion.jobkorea_import WHERE run_id=p_run_id;
 IF p_sha256 IS DISTINCT FROM meta.file_sha256 OR p_byte_length IS DISTINCT FROM meta.byte_length
 THEN RAISE EXCEPTION 'JOBKOREA_ARCHIVE_VERIFICATION_FAILED'; END IF;
 IF current_state='READY' THEN RETURN; END IF;
 IF current_state<>'LOADING' THEN RAISE EXCEPTION 'JOBKOREA_RUN_NOT_LOADING'; END IF;
 UPDATE ingestion.document SET verified_at=coalesce(verified_at,clock_timestamp()) WHERE run_id=p_run_id AND document_id=meta.document_id;
END $$;

CREATE OR REPLACE FUNCTION ingestion.mark_failed_jobkorea_import(p_run_id text,p_error_code text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_run_id,0));
 PERFORM 1 FROM ingestion.run WHERE run_id=p_run_id AND source_id='jobkorea' AND state='LOADING' FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 IF p_error_code IS NULL OR p_error_code !~ '^[A-Z0-9_]{1,80}$' THEN p_error_code:='LOCAL_IMPORT_FAILED'; END IF;
 INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,severity) VALUES(p_run_id,'',p_error_code,'ERROR') ON CONFLICT DO NOTHING;
 UPDATE ingestion.jobkorea_import SET error_code=p_error_code,processed_at=clock_timestamp() WHERE run_id=p_run_id AND NOT loaded;
 UPDATE ingestion.run SET state='FAILED',completed_at=clock_timestamp() WHERE run_id=p_run_id;
END $$;
COMMIT;
