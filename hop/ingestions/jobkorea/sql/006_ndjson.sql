-- Bounded, resumable local NDJSON ingestion. No source requests or full-file JSON.
-- Native archive verification supplies the complete-file SHA256 before begin and
-- again before seal. SQL binds exact bounded batches, physical lines and rows.
BEGIN;
SELECT retention.gate();

CREATE TABLE IF NOT EXISTS ingestion.jobkorea_ndjson_chunk (
 run_id text NOT NULL REFERENCES ingestion.jobkorea_import ON DELETE CASCADE,
 chunk_no bigint NOT NULL CHECK(chunk_no>0),
 start_byte_offset bigint NOT NULL CHECK(start_byte_offset>=0),
 start_line_number bigint NOT NULL CHECK(start_line_number>0),
 byte_length integer NOT NULL CHECK(byte_length BETWEEN 1 AND 33554432),
 line_count integer NOT NULL CHECK(line_count BETWEEN 1 AND 5000),
 accepted_count integer NOT NULL CHECK(accepted_count>=0),
 rejected_count integer NOT NULL CHECK(rejected_count>=0),
 batch_sha256 text NOT NULL CHECK(batch_sha256 ~ '^[0-9a-f]{64}$'),
 line_manifest_sha256 text NOT NULL CHECK(line_manifest_sha256 ~ '^[0-9a-f]{64}$'),
 chain_sha256 text NOT NULL CHECK(chain_sha256 ~ '^[0-9a-f]{64}$'),
 -- Raw serialization remains bounded and allows each persisted chunk hash to
 -- be rechecked without concatenating the file or rebuilding a giant JSONB.
 raw_text text NOT NULL,
 committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(run_id,chunk_no), UNIQUE(run_id,start_byte_offset),
 CHECK(accepted_count+rejected_count=line_count),
 CHECK(octet_length(raw_text)=byte_length AND right(raw_text,1)=chr(10))
);
CREATE TABLE IF NOT EXISTS ingestion.jobkorea_ndjson_line (
 run_id text NOT NULL,
 line_number bigint NOT NULL CHECK(line_number>0),
 byte_offset bigint NOT NULL CHECK(byte_offset>=0),
 byte_length integer NOT NULL CHECK(byte_length BETWEEN 2 AND 16777216),
 raw_sha256 text NOT NULL CHECK(raw_sha256 ~ '^[0-9a-f]{64}$'),
 row_sha256 text NOT NULL CHECK(row_sha256 ~ '^[0-9a-f]{64}$'),
 chunk_no bigint NOT NULL,
 source_record_id text,
 PRIMARY KEY(run_id,line_number), UNIQUE(run_id,byte_offset),
 FOREIGN KEY(run_id,chunk_no) REFERENCES ingestion.jobkorea_ndjson_chunk ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX IF NOT EXISTS jobkorea_ndjson_line_identity
 ON ingestion.jobkorea_ndjson_line(run_id,source_record_id) WHERE source_record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobkorea_ndjson_line_chunk ON ingestion.jobkorea_ndjson_line(run_id,chunk_no,line_number);

CREATE OR REPLACE FUNCTION ingestion.jobkorea_ndjson_evidence_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE id text; line bigint; owner text; committed boolean;
BEGIN
 PERFORM retention.gate();
 -- An UPDATE cannot evade the old run's fence by moving its evidence to a
 -- different source/run. New destinations are also checked for array rows.
 id:=CASE WHEN TG_OP='DELETE' THEN OLD.run_id
  WHEN TG_OP='UPDATE' AND EXISTS(SELECT 1 FROM ingestion.jobkorea_import i WHERE i.run_id=OLD.run_id AND i.file_format='NDJSON') THEN OLD.run_id
  ELSE NEW.run_id END;
 IF NOT EXISTS(SELECT 1 FROM ingestion.jobkorea_import i WHERE i.run_id=id AND i.file_format='NDJSON')
 THEN IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF; END IF;
 SELECT p.owner_id INTO owner FROM retention.plan p JOIN retention.plan_run r USING(plan_id)
  WHERE p.state='ACTIVE' AND r.run_id=id AND r.selected;
 IF TG_OP='DELETE' AND owner IS NOT NULL AND owner=current_setting('jobtology.retention_owner',true)
 THEN RETURN OLD; END IF;
 IF TG_TABLE_NAME IN('jobkorea_ndjson_chunk','jobkorea_ndjson_line') THEN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE'; END IF;
  IF NOT EXISTS(SELECT 1 FROM ingestion.run u WHERE u.run_id=id AND u.state='LOADING')
  THEN RAISE EXCEPTION 'JOBKOREA_RUN_NOT_LOADING'; END IF;
 ELSIF TG_TABLE_NAME IN('record','rejected_row','jobkorea_issue') THEN
  IF TG_OP='INSERT' THEN line:=CASE WHEN NEW.locator ~ '^line:[1-9][0-9]*$' THEN substring(NEW.locator FROM 6)::bigint END;
  ELSE line:=CASE WHEN OLD.locator ~ '^line:[1-9][0-9]*$' THEN substring(OLD.locator FROM 6)::bigint END; END IF;
  SELECT EXISTS(SELECT 1 FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=id AND l.line_number=line) INTO committed;
  IF committed THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE'; END IF;
  IF TG_OP='UPDATE' AND NEW.run_id IS DISTINCT FROM OLD.run_id THEN
   RAISE EXCEPTION 'JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE';
  END IF;
 ELSIF TG_TABLE_NAME='jobkorea_import' AND TG_OP='UPDATE' THEN
  IF ROW(NEW.file_sha256,NEW.byte_length,NEW.raw_path,NEW.file_format,NEW.parser_version,NEW.policy_revision,
    NEW.received_at,NEW.imported_at,NEW.scraped_at,NEW.document_id)
   IS DISTINCT FROM ROW(OLD.file_sha256,OLD.byte_length,OLD.raw_path,OLD.file_format,OLD.parser_version,OLD.policy_revision,
    OLD.received_at,OLD.imported_at,OLD.scraped_at,OLD.document_id)
  THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_RECEIPT_IMMUTABLE'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_ndjson_no_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM ingestion.jobkorea_ndjson_chunk)
 THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_COMMITTED_EVIDENCE_IMMUTABLE'; END IF;
 RETURN NULL;
END $$;
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['jobkorea_ndjson_chunk','jobkorea_ndjson_line','record','rejected_row','jobkorea_issue','jobkorea_import'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER jobkorea_ndjson_evidence BEFORE INSERT OR UPDATE OR DELETE ON ingestion.%I
   FOR EACH ROW EXECUTE FUNCTION ingestion.jobkorea_ndjson_evidence_guard()',name);
  EXECUTE format('CREATE OR REPLACE TRIGGER jobkorea_ndjson_no_truncate BEFORE TRUNCATE ON ingestion.%I
   FOR EACH STATEMENT EXECUTE FUNCTION ingestion.jobkorea_ndjson_no_truncate()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['jobkorea_ndjson_chunk','jobkorea_ndjson_line'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE ON ingestion.%I
   FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',name);
  EXECUTE format('CREATE OR REPLACE TRIGGER jobkorea_ready_evidence BEFORE INSERT OR UPDATE OR DELETE ON ingestion.%I
   FOR EACH ROW EXECUTE FUNCTION ingestion.jobkorea_evidence_guard()',name);
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ingestion.jobkorea_ndjson_row_hash(p_run_id text,p_line_number bigint) RETURNS text
LANGUAGE sql STABLE AS $$
 SELECT encode(sha256(convert_to(x.body::text,'UTF8')),'hex') FROM (
  SELECT jsonb_build_object('kind','ACCEPTED','locator',r.locator,'source_record_id',r.source_record_id,
   'source_payload',r.source_payload,'normalized',r.normalized,'field_lineage',r.field_lineage,'quality_flags',r.quality_flags) body
  FROM ingestion.record r WHERE r.run_id=p_run_id AND r.document_id='local-json' AND r.locator='line:'||p_line_number
  UNION ALL
  SELECT jsonb_build_object('kind','REJECTED','locator',r.locator,'error_code',r.error_code,'source_payload',r.source_payload)
  FROM ingestion.rejected_row r WHERE r.run_id=p_run_id AND r.document_id='local-json' AND r.locator='line:'||p_line_number
 ) x
$$;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_ndjson_chunk_manifest(p_run_id text,p_chunk_no bigint) RETURNS text
LANGUAGE sql STABLE AS $$
 -- Aggregation is restricted to one bounded chunk (at most 5000 digest rows).
 SELECT encode(sha256(convert_to(coalesce(jsonb_agg(jsonb_build_array(l.line_number,l.byte_offset,l.byte_length,
  l.raw_sha256,ingestion.jobkorea_ndjson_row_hash(l.run_id,l.line_number)) ORDER BY l.line_number),'[]')::text,'UTF8')),'hex')
 FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=p_run_id AND l.chunk_no=p_chunk_no
$$;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_ndjson_chain_step(p_prior text,p_chunk ingestion.jobkorea_ndjson_chunk) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
 SELECT encode(sha256(convert_to(p_prior||':'||jsonb_build_array(p_chunk.chunk_no,p_chunk.start_byte_offset,
  p_chunk.start_line_number,p_chunk.byte_length,p_chunk.line_count,p_chunk.accepted_count,p_chunk.rejected_count,
  p_chunk.batch_sha256,p_chunk.line_manifest_sha256)::text,'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_ndjson_row_manifest(p_run_id text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE meta ingestion.jobkorea_import; c ingestion.jobkorea_ndjson_chunk; chain text;
 expected_byte bigint:=0; expected_line bigint:=1; expected_chunk bigint:=1; n bigint; current_chunk_no bigint;
 raw_lines text[]; raw_line text; body text; physical ingestion.jobkorea_ndjson_line; source_payload jsonb;
 line_no bigint; byte_no bigint; line_bytes integer;
BEGIN
 SELECT * INTO STRICT meta FROM ingestion.jobkorea_import i WHERE i.run_id=p_run_id AND i.file_format='NDJSON';
 chain:=encode(sha256(convert_to('jobkorea-ndjson-row-manifest-v1','UTF8')),'hex');
 -- Cursor rows contain only a chunk number. Fetch one raw chunk at a time so
 -- PL/pgSQL cursor prefetch cannot retain dozens of large serialized batches.
 FOR current_chunk_no IN SELECT x.chunk_no FROM ingestion.jobkorea_ndjson_chunk x WHERE x.run_id=p_run_id ORDER BY x.chunk_no LOOP
  SELECT * INTO STRICT c FROM ingestion.jobkorea_ndjson_chunk x WHERE x.run_id=p_run_id AND x.chunk_no=current_chunk_no;
  IF c.chunk_no<>expected_chunk OR c.start_byte_offset<>expected_byte OR c.start_line_number<>expected_line
   OR c.batch_sha256 IS DISTINCT FROM encode(sha256(convert_to(c.raw_text,'UTF8')),'hex')
   OR c.line_manifest_sha256 IS DISTINCT FROM ingestion.jobkorea_ndjson_chunk_manifest(p_run_id,c.chunk_no)
  THEN RETURN NULL; END IF;
  raw_lines:=string_to_array(c.raw_text,chr(10));
  IF cardinality(raw_lines)-1<>c.line_count THEN RETURN NULL; END IF;
  line_no:=expected_line; byte_no:=expected_byte;
  FOREACH raw_line IN ARRAY raw_lines[1:c.line_count] LOOP
   raw_line:=raw_line||chr(10); line_bytes:=octet_length(raw_line);
   SELECT * INTO physical FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=p_run_id AND l.line_number=line_no;
   IF NOT FOUND OR physical.chunk_no<>c.chunk_no OR physical.byte_offset<>byte_no OR physical.byte_length<>line_bytes
    OR physical.raw_sha256 IS DISTINCT FROM encode(sha256(convert_to(raw_line,'UTF8')),'hex') THEN RETURN NULL; END IF;
   body:=left(raw_line,length(raw_line)-1);
   IF right(body,1)=chr(13) THEN body:=left(body,length(body)-1); END IF;
   IF NOT (body IS JSON OBJECT WITH UNIQUE KEYS) THEN RETURN NULL; END IF;
   SELECT r.source_payload INTO source_payload FROM (
    SELECT r.source_payload FROM ingestion.record r WHERE r.run_id=p_run_id AND r.document_id='local-json' AND r.locator='line:'||line_no
    UNION ALL
    SELECT r.source_payload FROM ingestion.rejected_row r WHERE r.run_id=p_run_id AND r.document_id='local-json' AND r.locator='line:'||line_no
   ) r;
   IF source_payload IS DISTINCT FROM body::jsonb THEN RETURN NULL; END IF;
   line_no:=line_no+1; byte_no:=byte_no+line_bytes;
  END LOOP;
  IF byte_no<>expected_byte+c.byte_length THEN RETURN NULL; END IF;
  SELECT count(*) INTO n FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=p_run_id AND l.chunk_no=c.chunk_no;
  IF n<>c.line_count OR EXISTS(SELECT 1 FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=p_run_id AND l.chunk_no=c.chunk_no
   AND (l.line_number NOT BETWEEN expected_line AND expected_line+c.line_count-1
    OR l.byte_offset<expected_byte OR l.byte_offset+l.byte_length>expected_byte+c.byte_length
    OR l.row_sha256 IS DISTINCT FROM ingestion.jobkorea_ndjson_row_hash(p_run_id,l.line_number)))
  THEN RETURN NULL; END IF;
  chain:=ingestion.jobkorea_ndjson_chain_step(chain,c);
  IF chain IS DISTINCT FROM c.chain_sha256 THEN RETURN NULL; END IF;
  expected_byte:=expected_byte+c.byte_length; expected_line:=expected_line+c.line_count; expected_chunk:=expected_chunk+1;
 END LOOP;
 IF expected_byte<>meta.next_byte_offset OR expected_line<>meta.next_line_number OR expected_chunk-1<>meta.batch_count
  OR (SELECT count(*) FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=p_run_id)<>expected_line-1
 THEN RETURN NULL; END IF;
 RETURN chain;
END $$;

CREATE OR REPLACE FUNCTION ingestion.begin_jobkorea_ndjson_import(
 p_sha256 text,p_byte_length bigint,p_raw_path text,p_received_at timestamptz,p_scraped_at timestamptz DEFAULT NULL)
RETURNS TABLE(run_id text,document_id text,reused boolean,state text,next_byte_offset bigint,next_line_number bigint)
LANGUAGE plpgsql AS $$
DECLARE chosen text; prior ingestion.jobkorea_import; prior_run ingestion.run;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF p_sha256 IS NULL OR p_sha256 !~ '^[0-9a-f]{64}$' OR p_byte_length IS NULL OR p_byte_length NOT BETWEEN 1 AND 17179869184
  OR p_raw_path IS DISTINCT FROM 'jobkorea/'||p_sha256||'/source.ndjson' OR p_received_at IS NULL
 THEN RAISE EXCEPTION 'INVALID_JOBKOREA_NDJSON_IMPORT_PARAMETERS'; END IF;
 chosen:='jobkorea-ndjson-'||encode(sha256(convert_to('hop-jobkorea-ndjson-v1:2026-10-07.1:'||p_sha256,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(chosen,0));
 SELECT * INTO prior FROM ingestion.jobkorea_import i WHERE i.run_id=chosen FOR UPDATE;
 IF FOUND THEN
  SELECT * INTO STRICT prior_run FROM ingestion.run u WHERE u.run_id=chosen FOR UPDATE;
  IF prior.file_format<>'NDJSON' OR prior.file_sha256 IS DISTINCT FROM p_sha256 OR prior.byte_length IS DISTINCT FROM p_byte_length
   OR prior.raw_path IS DISTINCT FROM p_raw_path OR prior.scraped_at IS DISTINCT FROM p_scraped_at
   OR prior_run.source_id<>'jobkorea' OR prior_run.mode<>'REPLAY' OR prior.parser_version<>'hop-jobkorea-ndjson-v1'
   OR prior_run.parser_version<>prior.parser_version OR prior_run.policy_revision<>prior.policy_revision
  THEN RAISE EXCEPTION 'JOBKOREA_IMPORT_CONFLICT'; END IF;
  run_id:=chosen; document_id:=prior.document_id; reused:=true; state:=prior_run.state;
  next_byte_offset:=prior.next_byte_offset; next_line_number:=prior.next_line_number; RETURN NEXT; RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ingestion.run u WHERE u.run_id=chosen) THEN RAISE EXCEPTION 'JOBKOREA_IMPORT_CONFLICT'; END IF;
 INSERT INTO ingestion.run(run_id,source_id,mode,parser_version,policy_revision)
 VALUES(chosen,'jobkorea','REPLAY','hop-jobkorea-ndjson-v1','2026-10-07.1');
 INSERT INTO ingestion.jobkorea_import(run_id,file_sha256,byte_length,raw_path,file_format,parser_version,policy_revision,received_at,scraped_at)
 VALUES(chosen,p_sha256,p_byte_length,p_raw_path,'NDJSON','hop-jobkorea-ndjson-v1','2026-10-07.1',p_received_at,p_scraped_at);
 INSERT INTO ingestion.partition(run_id,partition_id,kind,request_context,page_size)
 VALUES(chosen,'local-file','FILE','{"transport":"LOCAL_FILE","scope":"FILE_ONLY","provider_complete":false,"absence_is_closure":false}',1);
 INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,provider_result,retrieved_at,transport)
 VALUES(chosen,'local-json','local-file',1,p_raw_path,p_sha256,p_byte_length,'UTF-8',NULL,NULL,p_received_at,'LOCAL_FILE');
 run_id:=chosen; document_id:='local-json'; reused:=false; state:='LOADING'; next_byte_offset:=0; next_line_number:=1; RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION ingestion.append_jobkorea_ndjson_batch(
 p_run_id text,p_start_byte_offset bigint,p_start_line_number bigint,p_batch_text text,p_batch_sha256 text)
RETURNS TABLE(next_byte_offset bigint,next_line_number bigint,accepted_count integer,rejected_count integer,replayed boolean,state text)
LANGUAGE plpgsql AS $$
DECLARE meta ingestion.jobkorea_import; current_state text; prior ingestion.jobkorea_ndjson_chunk;
 c ingestion.jobkorea_ndjson_chunk; rawline text; body text; rec jsonb; parsed record; issue jsonb; flag jsonb;
 lines text[]; line_no bigint; byte_no bigint; line_bytes integer; total_bytes integer; n integer; loc text; identity text; chain text;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_run_id,0));
 SELECT u.state INTO STRICT current_state FROM ingestion.run u WHERE u.run_id=p_run_id AND u.source_id='jobkorea' FOR UPDATE;
 SELECT * INTO STRICT meta FROM ingestion.jobkorea_import i WHERE i.run_id=p_run_id FOR UPDATE;
 IF meta.file_format<>'NDJSON' OR meta.parser_version<>'hop-jobkorea-ndjson-v1' THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_FORMAT_CONFLICT'; END IF;
 total_bytes:=octet_length(p_batch_text);
 IF p_batch_text IS NULL OR total_bytes NOT BETWEEN 1 AND 33554432 OR p_batch_sha256 IS NULL
  OR p_batch_sha256 IS DISTINCT FROM encode(sha256(convert_to(p_batch_text,'UTF8')),'hex')
 THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_BATCH_HASH_OR_SIZE_CONFLICT'; END IF;
 IF right(p_batch_text,1)<>chr(10) THEN
  RAISE EXCEPTION USING MESSAGE='NDJSON_FINAL_NEWLINE_REQUIRED',ERRCODE='22000',
   DETAIL='line:'||p_start_line_number||'@byte:'||p_start_byte_offset;
 END IF;
 SELECT * INTO prior FROM ingestion.jobkorea_ndjson_chunk x WHERE x.run_id=p_run_id AND x.start_byte_offset=p_start_byte_offset;
 IF FOUND THEN
  IF prior.start_line_number IS DISTINCT FROM p_start_line_number OR prior.byte_length<>total_bytes
   OR prior.batch_sha256 IS DISTINCT FROM p_batch_sha256 OR prior.raw_text IS DISTINCT FROM p_batch_text
  THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_BATCH_REPLAY_CONFLICT'; END IF;
  next_byte_offset:=prior.start_byte_offset+prior.byte_length; next_line_number:=prior.start_line_number+prior.line_count;
  accepted_count:=prior.accepted_count; rejected_count:=prior.rejected_count; replayed:=true; state:=current_state; RETURN NEXT; RETURN;
 END IF;
 IF current_state<>'LOADING' OR meta.loaded OR meta.error_code IS NOT NULL THEN RAISE EXCEPTION 'JOBKOREA_RUN_NOT_LOADING'; END IF;
 IF p_start_byte_offset IS DISTINCT FROM meta.next_byte_offset OR p_start_line_number IS DISTINCT FROM meta.next_line_number
  OR p_start_byte_offset+total_bytes>meta.byte_length THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_CHECKPOINT_CONFLICT'; END IF;
 lines:=string_to_array(p_batch_text,chr(10)); n:=cardinality(lines)-1;
 IF n NOT BETWEEN 1 AND 5000 THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_BATCH_LINE_LIMIT'; END IF;
 line_no:=p_start_line_number; byte_no:=p_start_byte_offset; accepted_count:=0; rejected_count:=0;
 FOREACH rawline IN ARRAY lines[1:n] LOOP
  rawline:=rawline||chr(10); line_bytes:=octet_length(rawline);
  IF line_bytes>16777216 THEN RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_LINE_TOO_LARGE',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no; END IF;
  body:=left(rawline,length(rawline)-1);
  IF right(body,1)=chr(13) THEN body:=left(body,length(body)-1); END IF;
  IF btrim(body,E' \t\r')='' THEN RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_BLANK_LINE',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no; END IF;
  IF left(body,1)=chr(65279) THEN RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_BOM_FORBIDDEN',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no; END IF;
  IF NOT (body IS JSON OBJECT) THEN RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_JSON_INVALID',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no; END IF;
  IF NOT (body IS JSON OBJECT WITH UNIQUE KEYS) THEN RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_DUPLICATE_KEYS',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no; END IF;
  BEGIN rec:=body::jsonb; EXCEPTION WHEN data_exception THEN
   RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_JSON_INVALID',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no;
  END;
  loc:='line:'||line_no;
  SELECT * INTO STRICT parsed FROM ingestion.normalize_jobkorea_row(rec,loc);
  identity:=parsed.normalized->>'posting_id';
  IF identity IS NULL THEN RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_IDENTITY_INVALID',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no; END IF;
  IF EXISTS(SELECT 1 FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=p_run_id AND l.source_record_id=identity)
  THEN RAISE EXCEPTION USING MESSAGE='LOCAL_NDJSON_DUPLICATE_IDENTITY',ERRCODE='22000',DETAIL='line:'||line_no||'@byte:'||byte_no; END IF;
  FOR issue IN SELECT value FROM jsonb_array_elements(parsed.errors) LOOP
   INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,field,severity)
   VALUES(p_run_id,loc,issue->>'code',issue->>'field','ERROR') ON CONFLICT DO NOTHING;
  END LOOP;
  FOR flag IN SELECT value FROM jsonb_array_elements(parsed.quality_flags) LOOP
   INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,severity)
   VALUES(p_run_id,loc,flag#>>'{}','WARNING') ON CONFLICT DO NOTHING;
  END LOOP;
  IF jsonb_array_length(parsed.errors)>0 THEN
   INSERT INTO ingestion.rejected_row(run_id,document_id,locator,error_code,source_payload)
   VALUES(p_run_id,meta.document_id,loc,'INVALID_JOBKOREA_ROW',rec); rejected_count:=rejected_count+1;
  ELSE
   INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags)
   VALUES(p_run_id,meta.document_id,loc,identity,rec,parsed.normalized,parsed.field_lineage,parsed.quality_flags); accepted_count:=accepted_count+1;
  END IF;
  INSERT INTO ingestion.jobkorea_ndjson_line(run_id,line_number,byte_offset,byte_length,raw_sha256,row_sha256,chunk_no,source_record_id)
  VALUES(p_run_id,line_no,byte_no,line_bytes,encode(sha256(convert_to(rawline,'UTF8')),'hex'),
   ingestion.jobkorea_ndjson_row_hash(p_run_id,line_no),meta.batch_count+1,identity);
  line_no:=line_no+1; byte_no:=byte_no+line_bytes;
 END LOOP;
 c.run_id:=p_run_id; c.chunk_no:=meta.batch_count+1; c.start_byte_offset:=p_start_byte_offset; c.start_line_number:=p_start_line_number;
 c.byte_length:=total_bytes; c.line_count:=n; c.accepted_count:=accepted_count; c.rejected_count:=rejected_count;
 c.batch_sha256:=p_batch_sha256; c.line_manifest_sha256:=ingestion.jobkorea_ndjson_chunk_manifest(p_run_id,c.chunk_no); c.raw_text:=p_batch_text;
 IF meta.batch_count=0 THEN chain:=encode(sha256(convert_to('jobkorea-ndjson-row-manifest-v1','UTF8')),'hex');
 ELSE SELECT x.chain_sha256 INTO STRICT chain FROM ingestion.jobkorea_ndjson_chunk x WHERE x.run_id=p_run_id AND x.chunk_no=meta.batch_count; END IF;
 c.chain_sha256:=ingestion.jobkorea_ndjson_chain_step(chain,c);
 INSERT INTO ingestion.jobkorea_ndjson_chunk(run_id,chunk_no,start_byte_offset,start_line_number,byte_length,line_count,
  accepted_count,rejected_count,batch_sha256,line_manifest_sha256,chain_sha256,raw_text)
 VALUES(c.run_id,c.chunk_no,c.start_byte_offset,c.start_line_number,c.byte_length,c.line_count,c.accepted_count,c.rejected_count,
  c.batch_sha256,c.line_manifest_sha256,c.chain_sha256,c.raw_text);
 UPDATE ingestion.jobkorea_import i SET next_byte_offset=byte_no,next_line_number=line_no,batch_count=c.chunk_no WHERE i.run_id=p_run_id;
 next_byte_offset:=byte_no; next_line_number:=line_no; replayed:=false; state:=current_state; RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION ingestion.jobkorea_ndjson_validation_issue()
RETURNS TABLE(run_id text,issue text,location text) LANGUAGE sql STABLE AS $$
 SELECT i.run_id,'JOBKOREA_NDJSON_CHECKPOINT_INCOMPLETE','' FROM ingestion.jobkorea_import i
 WHERE i.file_format='NDJSON' AND (i.next_byte_offset<>i.byte_length OR i.next_line_number<=1 OR i.batch_count<=0)
 UNION ALL
 SELECT i.run_id,'JOBKOREA_NDJSON_LINE_ACCOUNTING_CONFLICT','' FROM ingestion.jobkorea_import i
 WHERE i.file_format='NDJSON' AND (
  (SELECT count(*) FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=i.run_id)<>i.next_line_number-1
  OR (SELECT count(*) FROM ingestion.record r WHERE r.run_id=i.run_id)
   +(SELECT count(*) FROM ingestion.rejected_row r WHERE r.run_id=i.run_id)<>i.next_line_number-1
  OR EXISTS(SELECT 1 FROM ingestion.record r WHERE r.run_id=i.run_id AND NOT EXISTS(
   SELECT 1 FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=r.run_id
    AND l.line_number=CASE WHEN r.locator ~ '^line:[1-9][0-9]{0,9}$' THEN substring(r.locator FROM 6)::bigint END
    AND l.source_record_id=r.source_record_id))
  OR EXISTS(SELECT 1 FROM ingestion.rejected_row r WHERE r.run_id=i.run_id AND NOT EXISTS(
   SELECT 1 FROM ingestion.jobkorea_ndjson_line l WHERE l.run_id=r.run_id
    AND l.line_number=CASE WHEN r.locator ~ '^line:[1-9][0-9]{0,9}$' THEN substring(r.locator FROM 6)::bigint END)))
 UNION ALL
 SELECT i.run_id,'JOBKOREA_NDJSON_CHAIN_CONFLICT','' FROM ingestion.jobkorea_import i
 WHERE i.file_format='NDJSON' AND ingestion.jobkorea_ndjson_row_manifest(i.run_id) IS NULL
$$;

CREATE OR REPLACE FUNCTION ingestion.seal_jobkorea_ndjson_import(p_run_id text,p_verified_sha256 text,p_verified_byte_length bigint)
RETURNS TABLE(state text,record_count bigint,issue_count bigint) LANGUAGE plpgsql AS $$
DECLARE meta ingestion.jobkorea_import; current_state text; manifest text; rows bigint;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_run_id,0));
 SELECT u.state INTO STRICT current_state FROM ingestion.run u WHERE u.run_id=p_run_id AND u.source_id='jobkorea' FOR UPDATE;
 SELECT * INTO STRICT meta FROM ingestion.jobkorea_import i WHERE i.run_id=p_run_id FOR UPDATE;
 IF meta.file_format<>'NDJSON' THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_FORMAT_CONFLICT'; END IF;
 IF p_verified_sha256 IS DISTINCT FROM meta.file_sha256 OR p_verified_byte_length IS DISTINCT FROM meta.byte_length
 THEN RAISE EXCEPTION 'JOBKOREA_ARCHIVE_VERIFICATION_FAILED'; END IF;
 IF current_state='READY' THEN RETURN QUERY SELECT * FROM ingestion.finalize_jobkorea_import(p_run_id); RETURN; END IF;
 IF current_state<>'LOADING' OR meta.error_code IS NOT NULL THEN RAISE EXCEPTION 'JOBKOREA_RUN_NOT_LOADING'; END IF;
 IF meta.next_byte_offset<>meta.byte_length OR meta.next_line_number<=1 OR meta.batch_count<=0
 THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_CHECKPOINT_INCOMPLETE'; END IF;
 manifest:=ingestion.jobkorea_ndjson_row_manifest(p_run_id);
 IF manifest IS NULL THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_CHAIN_CONFLICT'; END IF;
 rows:=meta.next_line_number-1;
 IF rows>2147483647 THEN RAISE EXCEPTION 'JOBKOREA_NDJSON_ROW_COUNT_LIMIT'; END IF;
 UPDATE ingestion.partition SET expected_total=rows::integer,page_size=rows::integer WHERE run_id=p_run_id AND partition_id='local-file';
 UPDATE ingestion.document SET selected=true,item_count=rows::integer,declared_total=rows::integer,effective_page=1,
  effective_page_size=rows::integer,verified_at=coalesce(verified_at,clock_timestamp()) WHERE run_id=p_run_id AND document_id=meta.document_id;
 UPDATE ingestion.jobkorea_import SET loaded=true,payload_sha256=meta.file_sha256,row_manifest_sha256=manifest,processed_at=clock_timestamp(),
  collection_scope=jsonb_build_object('completeness','UNKNOWN','provider_complete',false,'absence_is_closure',false,
   'supplied_row_count',rows,'file_format','NDJSON','physical_line_count',rows,'batch_count',meta.batch_count)
 WHERE run_id=p_run_id;
 RETURN QUERY SELECT * FROM ingestion.finalize_jobkorea_import(p_run_id);
END $$;

CREATE OR REPLACE FUNCTION ingestion.mark_failed_jobkorea_ndjson_import(
 p_run_id text,p_line_number bigint,p_byte_offset bigint,p_error_code text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_run_id,0));
 IF NOT EXISTS(SELECT 1 FROM ingestion.run u JOIN ingestion.jobkorea_import i USING(run_id)
  WHERE u.run_id=p_run_id AND u.state='LOADING' AND i.file_format='NDJSON') THEN RETURN; END IF;
 IF p_line_number IS NULL OR p_line_number<1 OR p_byte_offset IS NULL OR p_byte_offset<0
 THEN RAISE EXCEPTION 'INVALID_JOBKOREA_NDJSON_FAILURE_LOCATION'; END IF;
 IF p_error_code IS NULL OR p_error_code !~ '^[A-Z0-9_]{1,80}$' THEN p_error_code:='LOCAL_IMPORT_FAILED'; END IF;
 INSERT INTO ingestion.jobkorea_issue(run_id,locator,code,severity)
 VALUES(p_run_id,'line:'||p_line_number||'@byte:'||p_byte_offset,p_error_code,'ERROR') ON CONFLICT DO NOTHING;
 PERFORM ingestion.mark_failed_jobkorea_import(p_run_id,p_error_code);
END $$;
COMMENT ON TABLE ingestion.jobkorea_ndjson_line IS
 'Exact physical line and UTF8 byte provenance; byte_length includes terminal LF or CRLF. Locators line:n are not JSON array pointers.';
COMMENT ON TABLE ingestion.jobkorea_ndjson_chunk IS
 'Immutable bounded exact-serialization chunks, replay checkpoints and chained row manifests. Full archive SHA256 is independently reverified by the native reader at seal.';
COMMIT;
