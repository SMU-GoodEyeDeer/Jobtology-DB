-- Versioned HWPX structure reconstructed by native VFS reads and PostgreSQL XML.
-- Original download attempts, parser output and input bundles are never replaced.
BEGIN;
SELECT retention.gate();
CREATE TABLE IF NOT EXISTS attachment.hwpx_batch (
 batch_id text PRIMARY KEY,job_run_id text NOT NULL REFERENCES ingestion.run,
 attachment_batch_ids text[] NOT NULL,posting_ids text[] NOT NULL,max_documents integer NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS attachment.hwpx_structure (
 structure_id text PRIMARY KEY,batch_id text NOT NULL REFERENCES attachment.hwpx_batch,
 attempt_id text NOT NULL REFERENCES attachment.attempt,raw_hash text NOT NULL,
 parser_version text NOT NULL DEFAULT 'hwpx-xml-structure-v1',
 state text NOT NULL DEFAULT 'PLANNED' CHECK(state IN ('PLANNED','READING','BUILT','VERIFIED','REVIEW_REQUIRED','FAILED')),
 body_text text,body_hash text,issues jsonb NOT NULL DEFAULT '[]',
 started_at timestamptz,finished_at timestamptz,UNIQUE(batch_id,attempt_id)
);
CREATE TABLE IF NOT EXISTS attachment.hwpx_entry (
 structure_id text NOT NULL REFERENCES attachment.hwpx_structure,entry_name text NOT NULL,
 raw_bytes bytea NOT NULL,raw_hash text NOT NULL,byte_length bigint NOT NULL,
 PRIMARY KEY(structure_id,entry_name),CHECK(byte_length=octet_length(raw_bytes)),
 CHECK(raw_hash=encode(sha256(raw_bytes),'hex'))
);
CREATE TABLE IF NOT EXISTS attachment.hwpx_table (
 structure_id text NOT NULL,entry_name text NOT NULL,table_no integer NOT NULL,
 parent_table_no integer,parent_cell_no integer,rows integer,cols integer,
 PRIMARY KEY(structure_id,entry_name,table_no),
 FOREIGN KEY(structure_id,entry_name) REFERENCES attachment.hwpx_entry
);
CREATE TABLE IF NOT EXISTS attachment.hwpx_cell (
 structure_id text NOT NULL,entry_name text NOT NULL,cell_no integer NOT NULL,table_no integer NOT NULL,
 row_no integer,col_no integer,row_span integer,col_span integer,is_header boolean,
 PRIMARY KEY(structure_id,entry_name,cell_no),
 FOREIGN KEY(structure_id,entry_name,table_no) REFERENCES attachment.hwpx_table
);
CREATE TABLE IF NOT EXISTS attachment.hwpx_atom (
 structure_id text NOT NULL,entry_name text NOT NULL,event_no integer NOT NULL,
 paragraph_no integer,table_no integer,cell_no integer,context_role text NOT NULL,
 kind text NOT NULL,content text NOT NULL,
 PRIMARY KEY(structure_id,entry_name,event_no),
 FOREIGN KEY(structure_id,entry_name) REFERENCES attachment.hwpx_entry
);
CREATE TABLE IF NOT EXISTS attachment.hwpx_block (
 structure_id text NOT NULL,entry_name text NOT NULL,block_no integer NOT NULL,
 paragraph_no integer,table_no integer,cell_no integer,context_role text NOT NULL,
 first_event integer NOT NULL,last_event integer NOT NULL,content text NOT NULL,content_hash text NOT NULL,
 PRIMARY KEY(structure_id,entry_name,block_no),
 FOREIGN KEY(structure_id,entry_name) REFERENCES attachment.hwpx_entry
);
CREATE OR REPLACE FUNCTION attachment.hwpx_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'HWPX_STRUCTURE_IS_IMMUTABLE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM attachment.hwpx_structure WHERE structure_id=NEW.structure_id AND state='READING')
 THEN RAISE EXCEPTION 'HWPX_STRUCTURE_NOT_READING'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION attachment.hwpx_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' OR OLD.state NOT IN ('PLANNED','READING','BUILT') THEN RAISE EXCEPTION 'HWPX_STRUCTURE_IS_IMMUTABLE'; END IF;
 IF (NEW.structure_id,NEW.batch_id,NEW.attempt_id,NEW.raw_hash,NEW.parser_version) IS DISTINCT FROM
  (OLD.structure_id,OLD.batch_id,OLD.attempt_id,OLD.raw_hash,OLD.parser_version) THEN RAISE EXCEPTION 'HWPX_STRUCTURE_INPUT_CHANGED'; END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['hwpx_entry','hwpx_table','hwpx_cell','hwpx_atom','hwpx_block'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=('attachment.'||t)::regclass AND tgname='hwpx_immutable') THEN
   EXECUTE format('CREATE TRIGGER hwpx_immutable BEFORE INSERT OR UPDATE OR DELETE ON attachment.%I FOR EACH ROW EXECUTE FUNCTION attachment.hwpx_child_guard()',t);
  END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='attachment.hwpx_batch'::regclass AND tgname='immutable') THEN
  CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON attachment.hwpx_batch FOR EACH ROW EXECUTE FUNCTION attachment.immutable(); END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='attachment.hwpx_structure'::regclass AND tgname='immutable') THEN
  CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON attachment.hwpx_structure FOR EACH ROW EXECUTE FUNCTION attachment.hwpx_state_guard(); END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.uri_path(value text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT string_agg(CASE WHEN byte BETWEEN 48 AND 57 OR byte BETWEEN 65 AND 90 OR byte BETWEEN 97 AND 122 OR byte IN (45,46,47,95,126)
  THEN chr(byte) ELSE '%'||upper(lpad(to_hex(byte),2,'0')) END,'' ORDER BY n)
 FROM (SELECT n,get_byte(convert_to(value,'UTF8'),n) byte FROM generate_series(0,octet_length(value)-1) n) s
$$;
CREATE OR REPLACE FUNCTION attachment.prepare_hwpx(id text,jobs text,parents text,postings text,cap integer) RETURNS text LANGUAGE plpgsql AS $$
DECLARE batches text[]:=string_to_array(parents,'|');ids text[];b text;old attachment.hwpx_batch; BEGIN
 PERFORM retention.gate();
 IF coalesce(id,'')='' THEN id:=gen_random_uuid()::text; END IF;
 IF id !~ '^[A-Za-z0-9_-]{1,100}$' OR cap IS NULL OR cap NOT BETWEEN 1 AND 1000 OR cardinality(batches) IS NULL
  OR cardinality(batches) NOT BETWEEN 1 AND 100 OR cardinality(batches)<>(SELECT count(DISTINCT v) FROM unnest(batches) v)
 THEN RAISE EXCEPTION 'INVALID_HWPX_SELECTION'; END IF;
 SELECT coalesce(array_agg(DISTINCT v ORDER BY v),'{}') INTO ids FROM unnest(string_to_array(coalesce(postings,''),'|')) v WHERE v<>'';
 IF EXISTS(SELECT 1 FROM unnest(ids) v WHERE v !~ '^[0-9]+$') THEN RAISE EXCEPTION 'INVALID_POSTING_IDS'; END IF;
 FOREACH b IN ARRAY batches LOOP
  IF NOT EXISTS(SELECT 1 FROM attachment.batch WHERE batch_id=b AND job_run_id=jobs) THEN RAISE EXCEPTION 'HWPX_SNAPSHOT_MISMATCH'; END IF;
  PERFORM attachment.verify_batch(b);
 END LOOP;
 IF EXISTS(SELECT 1 FROM unnest(ids) v WHERE NOT EXISTS(SELECT 1 FROM attachment.posting WHERE batch_id=ANY(batches) AND posting_id=v))
 THEN RAISE EXCEPTION 'POSTING_NOT_IN_ATTACHMENT_PLAN'; END IF;
 SELECT * INTO old FROM attachment.hwpx_batch WHERE batch_id=id;
 IF FOUND THEN
  IF (old.job_run_id,old.attachment_batch_ids,old.posting_ids,old.max_documents) IS DISTINCT FROM (jobs,batches,ids,cap)
  THEN RAISE EXCEPTION 'HWPX_BATCH_IS_IMMUTABLE'; END IF;RETURN id;
 END IF;
 INSERT INTO attachment.hwpx_batch(batch_id,job_run_id,attachment_batch_ids,posting_ids,max_documents) VALUES(id,jobs,batches,ids,cap);
 INSERT INTO attachment.hwpx_structure(structure_id,batch_id,attempt_id,raw_hash)
 SELECT attachment.hash(jsonb_build_array(id,a.attempt_id,'hwpx-xml-structure-v1')::text),id,a.attempt_id,a.raw_hash
 FROM (SELECT DISTINCT ON(d.posting_id,d.file_ordinal) d.* FROM attachment.document d
  JOIN unnest(batches) WITH ORDINALITY b(batch_id,priority) USING(batch_id)
  WHERE cardinality(ids)=0 OR d.posting_id=ANY(ids) ORDER BY d.posting_id,d.file_ordinal,b.priority DESC) d
 JOIN attachment.attempt a USING(document_id) WHERE d.extension='hwpx' AND d.disposition='PLANNED' AND a.http_status=200
  AND a.state IN ('PARSED','NO_TEXT','NEEDS_REVIEW','PARSE_ERROR') AND a.raw_hash IS NOT NULL;
 IF (SELECT count(*) FROM attachment.hwpx_structure WHERE batch_id=id)>cap THEN RAISE EXCEPTION 'HWPX_CAP_EXCEEDED'; END IF;
 RETURN id;
END $$;
CREATE OR REPLACE FUNCTION attachment.reserve_hwpx(id text) RETURNS text LANGUAGE plpgsql AS $$ BEGIN
 PERFORM retention.gate();
 UPDATE attachment.hwpx_structure s SET state='READING',started_at=clock_timestamp() FROM attachment.attempt a
 WHERE s.structure_id=id AND s.state='PLANNED' AND a.attempt_id=s.attempt_id AND a.raw_hash=s.raw_hash;
 IF NOT FOUND THEN RAISE EXCEPTION 'HWPX_PLAN_REQUIRED'; END IF;
 PERFORM retention.enter_writer(id,'ATTACHMENT_STRUCTURE',id);RETURN id;
END $$;
CREATE OR REPLACE FUNCTION attachment.hwpx_check_hash(id text,actual text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM attachment.hwpx_structure WHERE structure_id=id AND state='READING' AND raw_hash=lower(actual))
 THEN RAISE EXCEPTION 'HWPX_ARCHIVE_CHANGED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.hwpx_entry_limit(id text,name text,size bigint) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF name !~ '^Contents/(content[.]hpf|header[.]xml|section[0-9]+[.]xml)$' OR size IS NULL OR size NOT BETWEEN 1 AND 16777216
  OR size+coalesce((SELECT sum(byte_length) FROM attachment.hwpx_entry WHERE structure_id=id),0)>67108864
 THEN RAISE EXCEPTION 'HWPX_ENTRY_OUTSIDE_LIMIT'; END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.save_hwpx_entry(id text,name text,bytes bytea,expected_size bigint) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 PERFORM attachment.hwpx_entry_limit(id,name,expected_size);
 IF octet_length(bytes) IS DISTINCT FROM expected_size THEN RAISE EXCEPTION 'HWPX_ENTRY_SIZE_CHANGED'; END IF;
 INSERT INTO attachment.hwpx_entry VALUES(id,name,bytes,encode(sha256(bytes),'hex'),expected_size);
END $$;
CREATE OR REPLACE FUNCTION attachment.hwpx_xml(id text,name text) RETURNS xml LANGUAGE plpgsql STABLE AS $$
DECLARE raw text; BEGIN
 SELECT convert_from(raw_bytes,'UTF8') INTO STRICT raw FROM attachment.hwpx_entry WHERE structure_id=id AND entry_name=name;
 IF raw ~* '<!DOCTYPE|<!ENTITY' THEN RAISE EXCEPTION 'HWPX_XML_DECLARATION_NOT_ALLOWED'; END IF;
 RETURN xmlparse(document raw);
END $$;
CREATE OR REPLACE FUNCTION attachment.hwpx_entries(id text) RETURNS TABLE(entry_name text,section_no integer)
LANGUAGE plpgsql STABLE AS $$
DECLARE x xml:=attachment.hwpx_xml(id,'Contents/content.hpf');items jsonb;spine jsonb; BEGIN
 IF cardinality(xpath('/*[local-name()="package" and namespace-uri()="http://www.idpf.org/2007/opf/"]',x))<>1
  OR cardinality(xpath('/*/*[local-name()="manifest"]',x))<>1
  OR cardinality(xpath('/*/*[local-name()="spine"]',x))<>1
 THEN RAISE EXCEPTION 'HWPX_PACKAGE_REQUIRED'; END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(a)),'[]') INTO items FROM XMLTABLE(
  XMLNAMESPACES('http://www.idpf.org/2007/opf/' AS opf),'/opf:package/opf:manifest/opf:item' PASSING x
  COLUMNS item_id text PATH '@id',href text PATH '@href') a;
 SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY a.n),'[]') INTO spine FROM XMLTABLE(
  XMLNAMESPACES('http://www.idpf.org/2007/opf/' AS opf),'/opf:package/opf:spine/opf:itemref' PASSING x
  COLUMNS n FOR ORDINALITY,item_id text PATH '@idref') a;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(items) a WHERE coalesce(a->>'item_id','')='' OR coalesce(a->>'href','')='')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(items) a GROUP BY a->>'item_id' HAVING count(*)<>1)
 THEN RAISE EXCEPTION 'INVALID_OR_DUPLICATE_HWPX_MANIFEST_ID'; END IF;
 IF jsonb_array_length(spine) NOT BETWEEN 1 AND 129
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(spine) a GROUP BY a->>'item_id' HAVING count(*)<>1)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(spine) s LEFT JOIN jsonb_array_elements(items) i ON i->>'item_id'=s->>'item_id'
   WHERE i IS NULL OR (i->>'href') !~ '^Contents/(header[.]xml|section[0-9]+[.]xml)$')
 THEN RAISE EXCEPTION 'INVALID_HWPX_SPINE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(items) a WHERE a->>'href' ~ '^Contents/section[0-9]+[.]xml$')
 THEN RAISE EXCEPTION 'HWPX_SECTIONS_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(items) i WHERE i->>'href' ~ '^Contents/(header[.]xml|section[0-9]+[.]xml)$'
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(spine) s WHERE s->>'item_id'=i->>'item_id'))
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(spine) s JOIN jsonb_array_elements(items) i ON i->>'item_id'=s->>'item_id'
   GROUP BY i->>'href' HAVING count(*)<>1)
 THEN RAISE EXCEPTION 'HWPX_SPINE_COVERAGE_MISMATCH'; END IF;
 RETURN QUERY SELECT i->>'href',CASE WHEN i->>'href'='Contents/header.xml' THEN 0
  ELSE (sum(CASE WHEN i->>'href'<>'Contents/header.xml' THEN 1 ELSE 0 END) OVER(ORDER BY (s->>'n')::integer))::integer END
 FROM jsonb_array_elements(spine) s JOIN jsonb_array_elements(items) i ON i->>'item_id'=s->>'item_id'
 ORDER BY (s->>'n')::integer;
END $$;
CREATE OR REPLACE FUNCTION attachment.render_hwpx_entry(id text,name text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE x xml:=attachment.hwpx_xml(id,name);n integer; BEGIN
 IF cardinality(xpath('/*[local-name()="sec" and namespace-uri()="http://www.hancom.co.kr/hwpml/2011/section"]',x))<>1
 THEN RAISE EXCEPTION 'HWPX_SECTION_REQUIRED'; END IF;
 INSERT INTO attachment.hwpx_table
 SELECT id,name,t.n,CASE WHEN has_parent THEN parent_no END,CASE WHEN has_cell THEN cell_no END,rows,cols
 FROM XMLTABLE(XMLNAMESPACES('http://www.hancom.co.kr/hwpml/2011/paragraph' AS hp),'//hp:tbl' PASSING x
 COLUMNS n FOR ORDINALITY,has_parent boolean PATH 'boolean(ancestor::hp:tbl)',has_cell boolean PATH 'boolean(ancestor::hp:tc)',
 parent_no integer PATH 'count(ancestor::hp:tbl[1]/preceding::hp:tbl | ancestor::hp:tbl[1]/ancestor::hp:tbl)+1',
 cell_no integer PATH 'count(ancestor::hp:tc[1]/preceding::hp:tc | ancestor::hp:tc[1]/ancestor::hp:tc)+1',
 rows integer PATH '@rowCnt',cols integer PATH '@colCnt') t;
 INSERT INTO attachment.hwpx_cell
 SELECT id,name,t.n,table_no,row_no,col_no,row_span,col_span,coalesce(is_header,false)
 FROM XMLTABLE(XMLNAMESPACES('http://www.hancom.co.kr/hwpml/2011/paragraph' AS hp),'//hp:tc' PASSING x
 COLUMNS n FOR ORDINALITY,table_no integer PATH 'count(ancestor::hp:tbl[1]/preceding::hp:tbl | ancestor::hp:tbl[1]/ancestor::hp:tbl)+1',
 row_no integer PATH 'hp:cellAddr/@rowAddr',col_no integer PATH 'hp:cellAddr/@colAddr',
 row_span integer PATH 'hp:cellSpan/@rowSpan',col_span integer PATH 'hp:cellSpan/@colSpan',is_header boolean PATH '@header') t;
 INSERT INTO attachment.hwpx_atom
 SELECT id,name,t.n,CASE WHEN has_paragraph THEN paragraph_no END,CASE WHEN has_table THEN table_no END,CASE WHEN has_cell THEN cell_no END,
 CASE WHEN in_header THEN 'header' WHEN in_footer THEN 'footer' WHEN in_footnote THEN 'footnote' WHEN in_endnote THEN 'endnote' ELSE 'body' END,
 CASE WHEN is_text THEN 'text' WHEN control_namespace='http://www.hancom.co.kr/hwpml/2011/paragraph' THEN kind ELSE '{'||coalesce(control_namespace,'')||'}'||coalesce(kind,'unknown') END,
 CASE WHEN is_text THEN coalesce(value,'') WHEN control_namespace<>'http://www.hancom.co.kr/hwpml/2011/paragraph' THEN '' WHEN kind='lineBreak' THEN E'\n' WHEN kind='tab' THEN E'\t'
  WHEN kind='fwSpace' THEN U&'\3000' WHEN kind='nbSpace' THEN U&'\00a0' ELSE '' END
 FROM XMLTABLE(XMLNAMESPACES('http://www.hancom.co.kr/hwpml/2011/paragraph' AS hp),'//hp:t/node()' PASSING x
 COLUMNS n FOR ORDINALITY,is_text boolean PATH 'boolean(self::text())',kind text PATH 'local-name(.)',control_namespace text PATH 'namespace-uri(.)',value text PATH 'string(.)',
 has_paragraph boolean PATH 'boolean(ancestor::hp:p)',paragraph_no integer PATH 'count(ancestor::hp:p[1]/preceding::hp:p | ancestor::hp:p[1]/ancestor::hp:p)+1',
 has_table boolean PATH 'boolean(ancestor::hp:tbl)',has_cell boolean PATH 'boolean(ancestor::hp:tc)',
 table_no integer PATH 'count(ancestor::hp:tbl[1]/preceding::hp:tbl | ancestor::hp:tbl[1]/ancestor::hp:tbl)+1',
 cell_no integer PATH 'count(ancestor::hp:tc[1]/preceding::hp:tc | ancestor::hp:tc[1]/ancestor::hp:tc)+1',
 in_header boolean PATH 'boolean(ancestor::hp:header)',in_footer boolean PATH 'boolean(ancestor::hp:footer)',
 in_footnote boolean PATH 'boolean(ancestor::hp:footNote)',in_endnote boolean PATH 'boolean(ancestor::hp:endNote)') t;
 -- Keep document order even when a paragraph contains an embedded table and
 -- resumes after it. Formatting runs concatenate without invented spaces.
 INSERT INTO attachment.hwpx_block
 WITH parts AS (SELECT *,jsonb_build_array(paragraph_no,table_no,cell_no,context_role) AS owner FROM attachment.hwpx_atom WHERE structure_id=id AND entry_name=name),
 boundaries AS (SELECT *,CASE WHEN lag(owner) OVER(ORDER BY event_no) IS DISTINCT FROM owner THEN 1 ELSE 0 END AS boundary FROM parts),
 grouped AS (SELECT *,sum(boundary) OVER(ORDER BY event_no) AS g FROM boundaries)
 SELECT id,name,g::integer,min(paragraph_no),min(table_no),min(cell_no),min(context_role),min(event_no),max(event_no),
 string_agg(content,'' ORDER BY event_no),attachment.hash(string_agg(content,'' ORDER BY event_no)) FROM grouped GROUP BY g;
 SELECT count(*) INTO n FROM attachment.hwpx_atom WHERE structure_id=id AND entry_name=name AND (paragraph_no IS NULL OR kind NOT IN ('text','lineBreak','tab','fwSpace','nbSpace'));
 IF n>0 THEN UPDATE attachment.hwpx_structure SET issues=issues||jsonb_build_array(jsonb_build_object('kind','unrendered_text_controls','entry',name,'count',n)) WHERE structure_id=id; END IF;
 SELECT count(*) INTO n FROM attachment.hwpx_cell c JOIN attachment.hwpx_table t USING(structure_id,entry_name,table_no)
 WHERE c.structure_id=id AND c.entry_name=name AND (c.row_no IS NULL OR c.col_no IS NULL OR c.row_span IS NULL OR c.col_span IS NULL
  OR t.rows IS NULL OR t.cols IS NULL OR c.row_no<0 OR c.col_no<0 OR c.row_span<1 OR c.col_span<1 OR c.row_no+c.row_span>t.rows OR c.col_no+c.col_span>t.cols);
 IF n>0 THEN UPDATE attachment.hwpx_structure SET issues=issues||jsonb_build_array(jsonb_build_object('kind','invalid_table_geometry','entry',name,'count',n)) WHERE structure_id=id; END IF;
 n:=cardinality(xpath('//*[local-name()="pic"]',x));
 IF n>0 THEN UPDATE attachment.hwpx_structure SET issues=issues||jsonb_build_array(jsonb_build_object('kind','embedded_images_unreviewed','entry',name,'count',n)) WHERE structure_id=id; END IF;
 n:=cardinality(xpath('//*[local-name()="autoNum" or local-name()="deleteBegin" or local-name()="insertBegin"]',x));
 IF n>0 THEN UPDATE attachment.hwpx_structure SET issues=issues||jsonb_build_array(jsonb_build_object('kind','numbering_or_tracked_changes_review','entry',name,'count',n)) WHERE structure_id=id; END IF;
END $$;
CREATE OR REPLACE FUNCTION attachment.build_hwpx_structure(id text,actual_hash text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE member record;text_value text; BEGIN
 PERFORM attachment.hwpx_check_hash(id,actual_hash);
 IF EXISTS(SELECT 1 FROM attachment.hwpx_entries(id) p LEFT JOIN attachment.hwpx_entry e ON e.structure_id=id AND e.entry_name=p.entry_name WHERE e.entry_name IS NULL)
 THEN RAISE EXCEPTION 'HWPX_PACKAGE_ENTRY_MISSING'; END IF;
 IF NOT EXISTS(SELECT 1 FROM attachment.hwpx_entries(id) WHERE entry_name ~ '^Contents/section[0-9]+[.]xml$') THEN RAISE EXCEPTION 'HWPX_BODY_REQUIRED'; END IF;
 FOR member IN SELECT * FROM attachment.hwpx_entries(id) WHERE entry_name ~ '^Contents/section[0-9]+[.]xml$' ORDER BY section_no LOOP
  PERFORM attachment.render_hwpx_entry(id,member.entry_name);
 END LOOP;
 SELECT coalesce(string_agg(b.content,E'\n' ORDER BY e.section_no,b.block_no),'') INTO text_value
 FROM attachment.hwpx_entries(id) e JOIN attachment.hwpx_block b ON b.structure_id=id AND b.entry_name=e.entry_name
 WHERE length(btrim(b.content,E' \t\r\n'||U&'\3000\00a0'))>0;
 UPDATE attachment.hwpx_structure SET body_text=text_value,body_hash=attachment.hash(text_value),state='BUILT',
  issues=issues||CASE WHEN text_value !~ '[[:alnum:]가-힣]' THEN '[{"kind":"no_text"}]'::jsonb ELSE '[]'::jsonb END
 WHERE structure_id=id;
END $$;
CREATE OR REPLACE FUNCTION attachment.finish_hwpx(id text,child_ok boolean,errors bigint) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 UPDATE attachment.hwpx_structure SET state=CASE WHEN state<>'BUILT' OR child_ok IS DISTINCT FROM true OR errors IS DISTINCT FROM 0 THEN 'FAILED'
  WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(issues) i WHERE i->>'kind'<>'embedded_images_unreviewed') THEN 'REVIEW_REQUIRED' ELSE 'VERIFIED' END,
  issues=issues||CASE WHEN state<>'BUILT' OR child_ok IS DISTINCT FROM true OR errors IS DISTINCT FROM 0 THEN '[{"kind":"native_child_failed"}]'::jsonb ELSE '[]'::jsonb END,
  finished_at=clock_timestamp() WHERE structure_id=id AND state IN ('READING','BUILT');
 IF NOT FOUND THEN RAISE EXCEPTION 'HWPX_ACTIVE_STRUCTURE_REQUIRED'; END IF;
 PERFORM retention.leave_writer(id);
END $$;
CREATE OR REPLACE FUNCTION attachment.verify_hwpx_batch(id text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM attachment.hwpx_batch WHERE batch_id=id) THEN RAISE EXCEPTION 'HWPX_BATCH_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM attachment.hwpx_structure s LEFT JOIN retention.writer w ON w.writer_id=s.structure_id
  WHERE s.batch_id=id AND (s.state IN ('PLANNED','READING','BUILT') OR w.writer_id IS NOT NULL)) THEN RAISE EXCEPTION 'HWPX_BATCH_INCOMPLETE'; END IF;
END $$;
COMMIT;
