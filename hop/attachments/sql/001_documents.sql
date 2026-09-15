-- Native Hop attachment provenance. Install ingestion and manual retention first.
BEGIN;
SELECT retention.gate();
CREATE SCHEMA IF NOT EXISTS attachment;
CREATE TABLE IF NOT EXISTS attachment.policy (
 policy_id text PRIMARY KEY, contract jsonb NOT NULL, contract_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS attachment.batch (
 batch_id text PRIMARY KEY, job_run_id text NOT NULL REFERENCES ingestion.run,
 posting_ids text[] NOT NULL, source_hash text NOT NULL, raw_root text NOT NULL,
 policy_id text NOT NULL REFERENCES attachment.policy, max_files integer NOT NULL CHECK(max_files BETWEEN 1 AND 10000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS attachment.posting (
 batch_id text NOT NULL REFERENCES attachment.batch, posting_id text NOT NULL,
 source_document_id text NOT NULL, source_locator text NOT NULL, source_hash text NOT NULL,
 files jsonb NOT NULL CHECK(jsonb_typeof(files)='array'), PRIMARY KEY(batch_id,posting_id)
);
CREATE TABLE IF NOT EXISTS attachment.document (
 document_id text PRIMARY KEY, batch_id text NOT NULL, posting_id text NOT NULL,
 file_ordinal integer NOT NULL CHECK(file_ordinal>0), metadata jsonb NOT NULL,
 source_url text, request_url text, extension text,
 disposition text NOT NULL CHECK(disposition IN ('PLANNED','APPLICATION_FORM','ROLE_REVIEW','INVALID_URL','UNSUPPORTED_FORMAT')),
 FOREIGN KEY(batch_id,posting_id) REFERENCES attachment.posting,
 UNIQUE(batch_id,posting_id,file_ordinal)
);
CREATE TABLE IF NOT EXISTS attachment.attempt (
 attempt_id text PRIMARY KEY, document_id text NOT NULL UNIQUE REFERENCES attachment.document,
 raw_path text NOT NULL UNIQUE, state text NOT NULL DEFAULT 'RESERVED'
 CHECK(state IN ('RESERVED','ARCHIVED','PARSED','HTTP_ERROR','UNEXPECTED_CONTENT','EMPTY_DOCUMENT','TOO_LARGE','PARSE_ERROR','NEEDS_REVIEW','NO_TEXT','TRANSPORT_ERROR')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), finished_at timestamptz,
 http_status integer, response_headers text, raw_hash text, byte_length bigint,
 parser_version text, parsed_xml text, parser_metadata jsonb, parsed_hash text, issue text,
 CHECK(raw_hash IS NULL OR raw_hash ~ '^[0-9a-f]{64}$'),
 CHECK((state IN ('RESERVED','ARCHIVED'))=(finished_at IS NULL))
);
CREATE TABLE IF NOT EXISTS attachment.section (
 attempt_id text NOT NULL REFERENCES attachment.attempt, section_no integer NOT NULL,
 locator_kind text NOT NULL CHECK(locator_kind IN ('page','body','archive_section')), locator text NOT NULL,
 content text NOT NULL, content_hash text NOT NULL, PRIMARY KEY(attempt_id,section_no)
);
-- Additive storage revision: existing parse hashes and historical rows stay intact.
ALTER TABLE attachment.attempt ADD COLUMN IF NOT EXISTS parser_metadata_raw text;
ALTER TABLE attachment.attempt ADD COLUMN IF NOT EXISTS parser_metadata_hash text;
ALTER TABLE attachment.attempt ADD COLUMN IF NOT EXISTS metadata_normalization jsonb;
ALTER TABLE attachment.attempt ADD COLUMN IF NOT EXISTS parse_storage_version text NOT NULL DEFAULT 'xml-jsonb-v1';
CREATE OR REPLACE FUNCTION attachment.hash(v text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to(v,'UTF8')),'hex');
$$;
CREATE OR REPLACE FUNCTION attachment.immutable() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'ATTACHMENT_INPUT_IS_IMMUTABLE'; END $$;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['policy','batch','posting','document','section'] LOOP
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=('attachment.'||t)::regclass AND tgname='immutable') THEN
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON attachment.%I FOR EACH ROW EXECUTE FUNCTION attachment.immutable()',t);
 END IF; END LOOP; END $$;
CREATE OR REPLACE FUNCTION attachment.source_hash(run text,ids text[]) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT attachment.hash(coalesce(jsonb_agg(jsonb_build_array(r.source_record_id,r.document_id,r.locator,r.source_payload)
 ORDER BY r.source_record_id,r.document_id,r.locator)::text,'[]'))
 FROM ingestion.ready_record r WHERE r.run_id=run AND r.source_id='job_alio' AND r.source_record_id LIKE '%:detail'
 AND (cardinality(ids)=0 OR split_part(r.source_record_id,':',1)=ANY(ids));
$$;
CREATE OR REPLACE FUNCTION attachment.check_source(id text) RETURNS void LANGUAGE plpgsql AS $$
 DECLARE b attachment.batch; BEGIN SELECT * INTO STRICT b FROM attachment.batch WHERE batch_id=id;
 IF b.source_hash IS DISTINCT FROM attachment.source_hash(b.job_run_id,b.posting_ids) THEN RAISE EXCEPTION 'ATTACHMENT_SOURCE_CHANGED'; END IF;
 END $$;
CREATE OR REPLACE FUNCTION attachment.prepare(id text,run text,ids_text text,base text,cap integer) RETURNS text LANGUAGE plpgsql AS $$
DECLARE ids text[]; b attachment.batch; r record; f record; ext text; disposition text; file_id text; doc text; BEGIN
 PERFORM retention.gate();
 IF id IS NULL OR id='' THEN id:=gen_random_uuid()::text; END IF;
 IF id !~ '^[A-Za-z0-9_-]{1,100}$' THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_BATCH_ID'; END IF;
 IF base IS NULL OR base !~ '^/' OR base ~ '(^|/)[.][.]?(/|$)|//|[\\]' OR base ~ '[[:cntrl:]]' OR right(base,1)='/' THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_ROOT'; END IF;
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_CAP'; END IF;
 SELECT coalesce(array_agg(DISTINCT v ORDER BY v),'{}') INTO ids FROM unnest(string_to_array(coalesce(ids_text,''),'|')) v WHERE v<>'';
 IF EXISTS(SELECT 1 FROM unnest(ids) v WHERE v !~ '^[0-9]+$') THEN RAISE EXCEPTION 'INVALID_POSTING_IDS'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=prepare.run AND source_id='job_alio' AND state='READY' AND mode<>'SMOKE') THEN RAISE EXCEPTION 'READY_JOB_SNAPSHOT_REQUIRED'; END IF;
 SELECT * INTO b FROM attachment.batch WHERE batch_id=id;
 IF FOUND THEN
  IF (b.job_run_id,b.posting_ids,b.raw_root,b.max_files) IS DISTINCT FROM (run,ids,base,cap) THEN RAISE EXCEPTION 'ATTACHMENT_SELECTION_IS_IMMUTABLE'; END IF;
  PERFORM attachment.check_source(id); RETURN id;
 END IF;
 IF EXISTS(SELECT 1 FROM ingestion.ready_record WHERE run_id=prepare.run AND source_record_id LIKE '%:detail'
  AND (cardinality(ids)=0 OR split_part(source_record_id,':',1)=ANY(ids)) GROUP BY source_record_id HAVING count(*)<>1)
 THEN RAISE EXCEPTION 'AMBIGUOUS_SOURCE_POSTING'; END IF;
 IF cardinality(ids)>0 AND EXISTS(SELECT 1 FROM unnest(ids) v WHERE NOT EXISTS(SELECT 1 FROM ingestion.ready_record
  WHERE run_id=prepare.run AND source_record_id=v||':detail')) THEN RAISE EXCEPTION 'POSTING_NOT_IN_SNAPSHOT'; END IF;
 INSERT INTO attachment.batch VALUES(id,run,ids,attachment.source_hash(run,ids),base,'job-alio-attachments-v1',cap,clock_timestamp());
 FOR r IN SELECT * FROM ingestion.ready_record WHERE run_id=prepare.run AND source_record_id LIKE '%:detail'
 AND (cardinality(ids)=0 OR split_part(source_record_id,':',1)=ANY(ids)) ORDER BY source_record_id LOOP
  IF jsonb_typeof(r.source_payload->'files') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'ATTACHMENT_METADATA_ARRAY_REQUIRED'; END IF;
  INSERT INTO attachment.posting VALUES(id,split_part(r.source_record_id,':',1),r.document_id,r.locator,attachment.hash(r.source_payload::text),r.source_payload->'files');
  FOR f IN SELECT value,ordinality FROM jsonb_array_elements(r.source_payload->'files') WITH ORDINALITY LOOP
   file_id:=f.value->>'recrutAtchFileNo'; ext:=lower(substring(f.value->>'atchFileNm' FROM '[.]([^.]+)$'));
   disposition:=CASE WHEN f.value->>'atchFileType'='B' THEN 'APPLICATION_FORM'
    WHEN coalesce(f.value->>'atchFileType','') NOT IN ('A','C') THEN 'ROLE_REVIEW'
    WHEN file_id IS NULL OR file_id !~ '^[0-9]+$' OR (f.value->>'url') IS DISTINCT FROM
     ('https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='||file_id) THEN 'INVALID_URL'
    WHEN ext IS NULL OR ext NOT IN ('pdf','hwp','hwpx') THEN 'UNSUPPORTED_FORMAT' ELSE 'PLANNED' END;
   doc:=attachment.hash(jsonb_build_array(id,r.source_record_id,f.ordinality,f.value)::text);
   INSERT INTO attachment.document VALUES(doc,id,split_part(r.source_record_id,':',1),f.ordinality,f.value,f.value->>'url',
    CASE WHEN disposition='PLANNED' THEN 'https://www.alio.go.kr/download/download.json?fileNo='||file_id END,ext,disposition);
  END LOOP;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM attachment.posting WHERE batch_id=id) THEN RAISE EXCEPTION 'NO_ATTACHMENT_POSTINGS'; END IF;
 IF (SELECT count(*) FROM attachment.document dd WHERE dd.batch_id=id AND dd.disposition='PLANNED')>cap THEN RAISE EXCEPTION 'ATTACHMENT_CAP_EXCEEDED'; END IF;
 RETURN id;
END $$;
CREATE OR REPLACE FUNCTION attachment.reserve(id text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE d attachment.document;b attachment.batch;a text:=gen_random_uuid()::text; BEGIN
 PERFORM retention.gate(); SELECT * INTO STRICT d FROM attachment.document WHERE document_id=id;
 SELECT * INTO STRICT b FROM attachment.batch WHERE batch_id=d.batch_id;
 PERFORM attachment.check_source(b.batch_id);
 IF d.disposition<>'PLANNED' THEN RAISE EXCEPTION 'ATTACHMENT_NOT_ELIGIBLE'; END IF;
 -- Unique document_id prevents concurrent or implicit repeat downloads.
 INSERT INTO attachment.attempt(attempt_id,document_id,raw_path) VALUES(a,id,b.raw_root||'/'||a||'.'||d.extension);
 PERFORM retention.enter_writer(a,'ATTACHMENT',b.batch_id); RETURN a;
END $$;
CREATE OR REPLACE FUNCTION attachment.body_issue(code integer,body bytea,ext text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE WHEN code IS DISTINCT FROM 200 THEN 'HTTP_ERROR'
 WHEN octet_length(body) IS NULL OR octet_length(body)=0 THEN 'EMPTY_DOCUMENT'
 WHEN octet_length(body)>67108864 THEN 'TOO_LARGE'
 WHEN ext='pdf' AND substring(body,1,5)<>decode('255044462d','hex') THEN 'UNEXPECTED_CONTENT'
 WHEN ext='hwp' AND substring(body,1,8)<>decode('d0cf11e0a1b11ae1','hex') THEN 'UNEXPECTED_CONTENT'
 WHEN ext='hwpx' AND substring(body,1,4)<>decode('504b0304','hex') THEN 'UNEXPECTED_CONTENT'
 ELSE NULL END;
$$;
CREATE OR REPLACE FUNCTION attachment.archive(id text,code integer,headers text,hash text,size bigint,problem text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF hash IS NULL OR hash !~ '^[0-9a-f]{64}$' OR size IS NULL OR size<0 THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_ARCHIVE'; END IF;
 IF problem IS NOT NULL AND problem NOT IN ('HTTP_ERROR','EMPTY_DOCUMENT','TOO_LARGE','UNEXPECTED_CONTENT') THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_BODY_OUTCOME'; END IF;
 UPDATE attachment.attempt SET http_status=code,response_headers=headers,raw_hash=hash,byte_length=size,state=coalesce(problem,'ARCHIVED'),
 issue=problem,finished_at=CASE WHEN problem IS NOT NULL THEN clock_timestamp() END WHERE attempt_id=id AND state='RESERVED';
 IF NOT FOUND THEN RAISE EXCEPTION 'ATTACHMENT_RESERVATION_REQUIRED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.assert_hash(id text,actual text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM attachment.attempt WHERE attempt_id=id AND raw_hash=lower(actual) AND state='ARCHIVED') THEN RAISE EXCEPTION 'ATTACHMENT_BYTES_CHANGED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.decode_metadata(raw text) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE m jsonb;marked jsonb;marker text;fields jsonb;n integer; BEGIN
 IF raw IS NULL THEN RAISE EXCEPTION 'PARSER_METADATA_REQUIRED'; END IF;
 -- PostgreSQL JSONB cannot represent NUL. Match a JSON escape only, preserving
 -- escaped backslashes (a literal \\u0000 must not become a replacement character).
 m:=regexp_replace(raw,$re$(?<!\\)((?:\\\\)*)\\u0000$re$,$rep$\1\\ufffd$rep$,'g')::jsonb;
 IF jsonb_typeof(m) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'PARSER_METADATA_OBJECT_REQUIRED'; END IF;
 SELECT count(*) INTO n FROM regexp_matches(raw,$re$(?<!\\)((?:\\\\)*)\\u0000$re$,'g');
 fields:='[]';
 IF n>0 THEN
  -- A collision-free marker identifies exactly which top-level metadata fields
  -- changed, even when the original contains U+FFFD or nested arrays/objects.
  marker:='__HOP_METADATA_NUL_'||attachment.hash(raw)||'__';
  WHILE strpos(m::text,marker)>0 LOOP marker:=marker||'_'; END LOOP;
  marked:=regexp_replace(raw,$re$(?<!\\)((?:\\\\)*)\\u0000$re$,$rep$\1$rep$||marker,'g')::jsonb;
  SELECT coalesce(jsonb_agg(key ORDER BY key),'[]') INTO fields FROM jsonb_each(marked)
   WHERE strpos(key,marker)>0 OR strpos(value::text,marker)>0;
 END IF;
 RETURN jsonb_build_object('metadata',m,'normalization',jsonb_build_object(
  'policy','json-nul-to-replacement-v1','nul_escape_count',n,'affected_fields',fields));
END $$;
CREATE OR REPLACE FUNCTION attachment.save_parse(id text,xml_text text,metadata_text text,actual_hash text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE x xml;m jsonb;decoded jsonb;kind text;problem text;cnt integer;expected_ext text; BEGIN
 PERFORM attachment.assert_hash(id,actual_hash);
 SELECT extension INTO STRICT expected_ext FROM attachment.document d JOIN attachment.attempt a USING(document_id) WHERE attempt_id=id;
 decoded:=attachment.decode_metadata(metadata_text);m:=decoded->'metadata';
 -- Only PDF title metadata has a verified compatibility case. Other changed
 -- metadata remains inspectable, but needs review before becoming model input.
 IF (decoded#>>'{normalization,nul_escape_count}')::integer>0 AND
  (expected_ext<>'pdf' OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(decoded#>'{normalization,affected_fields}') f
   WHERE f NOT IN ('dc:title','pdf:docinfo:title'))) THEN problem:='METADATA_NUL_REQUIRES_REVIEW'; END IF;
 IF xml_text IS NULL OR length(xml_text)>2000000 THEN problem:='PARSED_OUTPUT_TOO_LARGE';
 ELSIF xml_text ~* '<!DOCTYPE|<!ENTITY' THEN problem:='XML_DECLARATION_NOT_ALLOWED';
 ELSE
  x:=xmlparse(document xml_text);
  IF coalesce(m->>'Content-Type','') !~ (CASE expected_ext WHEN 'pdf' THEN '^application/pdf$'
    WHEN 'hwp' THEN '^application/x-hwp($|[;-])|^application/(vnd[.]hancom[.]hwp|haansofthwp)$'
    ELSE '^application/(vnd[.]hancom[.]hwpx|hwp[+]zip|haansofthwpx)$' END) THEN problem:='UNEXPECTED_PARSER_MEDIA_TYPE';
  ELSIF EXISTS(SELECT 1 FROM jsonb_object_keys(m) k WHERE k ~* 'exception|warning|truncat') THEN problem:='PARSER_WARNINGS';
  END IF;
  IF expected_ext='hwpx' THEN
   -- Tika's generic package parser also emits previews, font tables and settings.
   -- Only the document section entries belong in the evidence text.
   INSERT INTO attachment.section
   SELECT id,row_number() OVER(ORDER BY substring(entry FROM 'section([0-9]+)')::integer)::integer,
    'archive_section','zip:'||entry,content,attachment.hash(content)
   FROM XMLTABLE('//*[local-name()="div" and @class="package-entry"]' PASSING x
    COLUMNS entry text PATH '*[local-name()="h1"]',content text PATH 'string(*[local-name()="p"])') t
   WHERE entry ~ '^Contents/section[0-9]+[.]xml$';
   IF NOT FOUND THEN problem:=coalesce(problem,'NO_HWPX_DOCUMENT_SECTIONS'); END IF;
  ELSIF cardinality(xpath('//*[local-name()="div" and @class="page"]',x))>0 THEN
   INSERT INTO attachment.section SELECT id,n,'page','page:'||n,content,attachment.hash(content)
   FROM XMLTABLE('//*[local-name()="div" and @class="page"]' PASSING x COLUMNS n FOR ORDINALITY,content text PATH 'string(.)') t;
  ELSE
   INSERT INTO attachment.section SELECT id,1,'body','body:1',content,attachment.hash(content)
   FROM XMLTABLE('/*[local-name()="html"]/*[local-name()="body"]' PASSING x COLUMNS content text PATH 'string(.)') t;
  END IF;
  IF expected_ext='pdf' THEN
   IF (m->>'xmpTPg:NPages') ~ '^[0-9]+$' AND (m->>'xmpTPg:NPages')::bigint <>
     (SELECT count(*) FROM attachment.section WHERE attempt_id=id AND locator_kind='page') THEN
    problem:=coalesce(problem,'PDF_PAGE_COUNT_MISMATCH');
   ELSIF EXISTS(SELECT 1 FROM attachment.section WHERE attempt_id=id AND content !~ '[[:alnum:]가-힣]') THEN
    problem:=coalesce(problem,'BLANK_OR_SCANNED_PDF_PAGE');
   ELSIF coalesce(m->>'pdf:totalUnmappedUnicodeChars','0') <> '0' THEN
    problem:=coalesce(problem,'UNMAPPED_PDF_CHARACTERS');
   END IF;
  ELSIF expected_ext='hwpx' AND EXISTS(SELECT 1 FROM attachment.section WHERE attempt_id=id
    AND substring(locator FROM 'section([0-9]+)')::bigint<>section_no-1) THEN
   problem:=coalesce(problem,'NONCONTIGUOUS_HWPX_SECTIONS');
  END IF;
 END IF;
 SELECT count(*) INTO cnt FROM attachment.section WHERE attempt_id=id AND content ~ '[[:alnum:]가-힣]';
 UPDATE attachment.attempt SET parser_version='hop-2.19-tika-3.3.1-xml-v1',parsed_xml=xml_text,parser_metadata=m,
 parser_metadata_raw=metadata_text,parser_metadata_hash=attachment.hash(metadata_text),
 metadata_normalization=decoded->'normalization',parse_storage_version='xml-jsonb-v2',
 parsed_hash=attachment.hash(jsonb_build_object('storage_version','xml-jsonb-v2','xml',xml_text,'metadata_raw',metadata_text)::text),
 state=CASE WHEN cnt=0 AND (problem IS NULL OR problem='BLANK_OR_SCANNED_PDF_PAGE') THEN 'NO_TEXT'
  WHEN problem IS NOT NULL THEN 'NEEDS_REVIEW' ELSE 'PARSED' END,
 issue=coalesce(problem,CASE WHEN cnt=0 THEN 'NO_EXTRACTED_TEXT_OCR_OR_MANUAL_REVIEW_REQUIRED' END),finished_at=clock_timestamp() WHERE attempt_id=id;
END $$;
CREATE OR REPLACE FUNCTION attachment.finish_attempt(id text,child_ok boolean,errors bigint) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 UPDATE attachment.attempt SET state=CASE WHEN state='RESERVED' THEN 'TRANSPORT_ERROR' ELSE 'PARSE_ERROR' END,
 issue=CASE WHEN state='RESERVED' THEN 'CHILD_FAILED_BEFORE_ARCHIVE' ELSE 'CHILD_FAILED_DURING_PARSE' END,finished_at=clock_timestamp()
 WHERE attempt_id=id AND state IN ('RESERVED','ARCHIVED');
 IF child_ok IS DISTINCT FROM true OR errors IS DISTINCT FROM 0 THEN
  UPDATE attachment.attempt SET state='NEEDS_REVIEW',issue='CHILD_FAILED_AFTER_PARSE'
   WHERE attempt_id=id AND state='PARSED';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM attachment.attempt WHERE attempt_id=id AND finished_at IS NOT NULL) THEN RAISE EXCEPTION 'ATTACHMENT_ATTEMPT_NOT_TERMINAL'; END IF;
 PERFORM retention.leave_writer(id);
END $$;
CREATE OR REPLACE VIEW attachment.report AS
 SELECT p.batch_id,p.posting_id,count(d.document_id) AS attachment_count,
 count(*) FILTER(WHERE d.disposition='PLANNED' AND a.attempt_id IS NULL) AS pending,
 count(*) FILTER(WHERE a.state IN ('RESERVED','ARCHIVED')) AS running,
 count(*) FILTER(WHERE a.state='PARSED') AS parsed,
 count(*) FILTER(WHERE d.document_id IS NOT NULL AND (d.disposition<>'PLANNED' OR a.state NOT IN ('RESERVED','ARCHIVED','PARSED'))) AS other_outcomes
 FROM attachment.posting p LEFT JOIN attachment.document d USING(batch_id,posting_id) LEFT JOIN attachment.attempt a USING(document_id)
 GROUP BY p.batch_id,p.posting_id;
CREATE OR REPLACE FUNCTION attachment.verify_batch(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM attachment.check_source(id);
 IF EXISTS(SELECT 1 FROM attachment.report WHERE batch_id=id AND (pending>0 OR running>0)) THEN RAISE EXCEPTION 'ATTACHMENT_BATCH_INCOMPLETE'; END IF;
 IF EXISTS(SELECT 1 FROM attachment.document d JOIN attachment.attempt a USING(document_id) JOIN retention.writer w ON w.writer_id=a.attempt_id WHERE d.batch_id=id)
 THEN RAISE EXCEPTION 'ATTACHMENT_WRITER_NOT_RELEASED'; END IF;
END $$;
COMMIT;
