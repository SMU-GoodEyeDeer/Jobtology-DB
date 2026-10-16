-- Additive O*NET reference catalogue. It is independent of the six-source corpus.
-- PostgreSQL preserves release evidence; Neo4j contains flat owned concepts only.
BEGIN;
SELECT retention.gate();
CREATE SCHEMA IF NOT EXISTS classification;

CREATE OR REPLACE FUNCTION classification.hash(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to('jobtology-onet-catalog-v1:'||value::text,'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION classification.with_content_hash(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT (value-'content_hash')||jsonb_build_object('content_hash',classification.hash(value-'content_hash'))
$$;

CREATE TABLE IF NOT EXISTS classification.catalog_release (
 release_id text PRIMARY KEY CHECK(length(release_id) BETWEEN 1 AND 200),
 scheme_id text NOT NULL CHECK(scheme_id='ONET'),
 source_version text NOT NULL CHECK(source_version ~ '^[0-9]+\.[0-9]+$'),
 taxonomy_version text NOT NULL CHECK(length(btrim(taxonomy_version)) BETWEEN 1 AND 120),
 contract_version text NOT NULL CHECK(contract_version='jobtology-onet-catalog-v1'),
 state text NOT NULL DEFAULT 'STAGING' CHECK(state IN('STAGING','READY')),
 normalized_input jsonb NOT NULL CHECK(jsonb_typeof(normalized_input)='object'),
 manifest_hash text NOT NULL CHECK(manifest_hash ~ '^[0-9a-f]{64}$'),
 imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 ready_at timestamptz,
 CHECK((state='READY')=(ready_at IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS classification.source_file (
 release_id text NOT NULL REFERENCES classification.catalog_release,
 file_id text NOT NULL,
 source_uri text NOT NULL,
 archive_path text NOT NULL,
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 byte_length bigint NOT NULL CHECK(byte_length>0),
 encoding text NOT NULL,
 downloaded_at timestamptz NOT NULL,
 PRIMARY KEY(release_id,file_id), UNIQUE(release_id,archive_path)
);
CREATE TABLE IF NOT EXISTS classification.term (
 release_id text NOT NULL REFERENCES classification.catalog_release,
 term_id text NOT NULL,
 code text NOT NULL,
 term_kind text NOT NULL CHECK(term_kind IN('GROUP','OCCUPATION')),
 preferred_label text NOT NULL CHECK(length(btrim(preferred_label))>0),
 description text,
 source_uri text NOT NULL,
 file_id text NOT NULL,
 source_locator text NOT NULL,
 source_attributes jsonb NOT NULL CHECK(jsonb_typeof(source_attributes)='object'),
 PRIMARY KEY(release_id,term_id), UNIQUE(release_id,term_kind,code),
 FOREIGN KEY(release_id,file_id) REFERENCES classification.source_file,
 CHECK((term_kind='GROUP' AND code ~ '^[0-9]{2}-[0-9]{4}$'
   AND term_id='urn:jobtology:onet:group:'||code)
  OR (term_kind='OCCUPATION' AND code ~ '^[0-9]{2}-[0-9]{4}\.[0-9]{2}$'
   AND term_id='urn:jobtology:onet:occupation:'||code))
);
CREATE TABLE IF NOT EXISTS classification.hierarchy (
 release_id text NOT NULL REFERENCES classification.catalog_release,
 child_id text NOT NULL,
 parent_id text NOT NULL,
 file_id text NOT NULL,
 source_locator text NOT NULL,
 source_uri text NOT NULL,
 source_attributes jsonb NOT NULL CHECK(jsonb_typeof(source_attributes)='object'),
 PRIMARY KEY(release_id,child_id,parent_id),
 FOREIGN KEY(release_id,child_id) REFERENCES classification.term(release_id,term_id),
 FOREIGN KEY(release_id,parent_id) REFERENCES classification.term(release_id,term_id),
 FOREIGN KEY(release_id,file_id) REFERENCES classification.source_file,
 CHECK(child_id<>parent_id)
);
CREATE TABLE IF NOT EXISTS classification.graph_load (
 load_id text PRIMARY KEY,
 release_id text NOT NULL REFERENCES classification.catalog_release,
 database_id text NOT NULL,
 previous_load_id text REFERENCES classification.graph_load,
 manifest_hash text NOT NULL CHECK(manifest_hash ~ '^[0-9a-f]{64}$'),
 state text NOT NULL CHECK(state IN('RUNNING','VERIFIED','FAILED')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 finished_at timestamptz,
 expected_nodes bigint NOT NULL DEFAULT 0,
 expected_edges bigint NOT NULL DEFAULT 0,
 current_nodes bigint NOT NULL DEFAULT 0,
 current_edges bigint NOT NULL DEFAULT 0,
 node_count bigint,
 edge_count bigint,
 error text
);
CREATE UNIQUE INDEX IF NOT EXISTS onet_one_graph_writer
 ON classification.graph_load(database_id) WHERE state='RUNNING';
CREATE TABLE IF NOT EXISTS classification.graph_load_node (
 load_id text NOT NULL REFERENCES classification.graph_load,
 node_id text NOT NULL,
 labels text[] NOT NULL,
 properties jsonb NOT NULL,
 content_hash text NOT NULL,
 previous_labels text[],
 previous_properties jsonb,
 previous_content_hash text,
 PRIMARY KEY(load_id,node_id)
);
CREATE TABLE IF NOT EXISTS classification.graph_load_edge (
 load_id text NOT NULL REFERENCES classification.graph_load,
 edge_id text NOT NULL,
 start_id text NOT NULL,
 end_id text NOT NULL,
 edge_type text NOT NULL CHECK(edge_type IN('IN_SCHEME','BROADER')),
 properties jsonb NOT NULL,
 content_hash text NOT NULL,
 previous_properties jsonb,
 previous_content_hash text,
 PRIMARY KEY(load_id,edge_id),
 FOREIGN KEY(load_id,start_id) REFERENCES classification.graph_load_node(load_id,node_id),
 FOREIGN KEY(load_id,end_id) REFERENCES classification.graph_load_node(load_id,node_id)
);
CREATE TABLE IF NOT EXISTS classification.graph_target (
 database_id text PRIMARY KEY,
 release_id text NOT NULL REFERENCES classification.catalog_release,
 load_id text NOT NULL REFERENCES classification.graph_load
);
CREATE TABLE IF NOT EXISTS classification.catalog_current (
 scheme_id text PRIMARY KEY CHECK(scheme_id='ONET'),
 release_id text NOT NULL REFERENCES classification.catalog_release,
 database_id text NOT NULL,
 load_id text NOT NULL REFERENCES classification.graph_load,
 activated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS classification.activation_event (
 activation_id text PRIMARY KEY,
 scheme_id text NOT NULL CHECK(scheme_id='ONET'),
 release_id text NOT NULL REFERENCES classification.catalog_release,
 previous_release_id text REFERENCES classification.catalog_release,
 database_id text NOT NULL,
 load_id text NOT NULL REFERENCES classification.graph_load,
 activated_at timestamptz NOT NULL
);

CREATE OR REPLACE FUNCTION classification.assert_catalog(id text) RETURNS void
LANGUAGE plpgsql STABLE SET jit=off SET timezone='UTC' AS $$
DECLARE r classification.catalog_release;
BEGIN
 SELECT * INTO STRICT r FROM classification.catalog_release WHERE release_id=id;
 IF classification.hash(r.normalized_input)<>r.manifest_hash OR
   (SELECT count(*) FROM classification.source_file WHERE release_id=id)<>jsonb_array_length(r.normalized_input->'sources') OR
   (SELECT count(*) FROM classification.term WHERE release_id=id)<>jsonb_array_length(r.normalized_input->'terms') OR
   (SELECT count(*) FROM classification.hierarchy WHERE release_id=id)<>jsonb_array_length(r.normalized_input->'hierarchy') OR
   (SELECT jsonb_agg(to_jsonb(f)-'release_id' ORDER BY file_id) FROM classification.source_file f WHERE f.release_id=id)
    IS DISTINCT FROM r.normalized_input->'sources' OR
   (SELECT jsonb_agg(to_jsonb(t)-'release_id' ORDER BY term_id) FROM classification.term t WHERE t.release_id=id)
    IS DISTINCT FROM r.normalized_input->'terms' OR
   (SELECT jsonb_agg(to_jsonb(h)-'release_id' ORDER BY child_id,parent_id) FROM classification.hierarchy h WHERE h.release_id=id)
    IS DISTINCT FROM r.normalized_input->'hierarchy'
 THEN RAISE EXCEPTION 'ONET_CATALOG_INVENTORY_MISMATCH'; END IF;
 IF NOT EXISTS(SELECT 1 FROM classification.term WHERE release_id=id AND term_kind='OCCUPATION') OR
   EXISTS(SELECT 1 FROM classification.term t WHERE t.release_id=id AND
    (coalesce(t.source_attributes->>'hierarchy_level','') !~ '^[1-5]$' OR
     (t.term_kind='GROUP' AND ((t.source_attributes->>'hierarchy_level')::integer NOT BETWEEN 1 AND 3 OR
       (t.source_attributes->>'hierarchy_level'='1' AND t.code !~ '^[0-9]{2}-0000$') OR
       (t.source_attributes->>'hierarchy_level'='2' AND t.code !~ '^[0-9]{2}-[0-9]{2}00$') OR
       (t.source_attributes->>'hierarchy_level'='3' AND t.code !~ '^[0-9]{2}-[0-9]{3}0$'))) OR
     (t.term_kind='OCCUPATION' AND NOT ((t.source_attributes->>'hierarchy_level'='4' AND t.code LIKE '%.00') OR
       (t.source_attributes->>'hierarchy_level'='5' AND t.code NOT LIKE '%.00'))))) OR
   EXISTS(SELECT 1 FROM classification.hierarchy h
     JOIN classification.term p ON p.release_id=h.release_id AND p.term_id=h.parent_id
     JOIN classification.term c ON c.release_id=h.release_id AND c.term_id=h.child_id
     WHERE h.release_id=id AND
       ((p.source_attributes->>'hierarchy_level')::integer<>(c.source_attributes->>'hierarchy_level')::integer-1 OR
        left(p.code,2)<>left(c.code,2) OR
        (c.source_attributes->>'hierarchy_level'='2' AND p.code<>left(c.code,2)||'-0000') OR
        (c.source_attributes->>'hierarchy_level'='5' AND p.code<>left(c.code,7)||'.00'))) OR
   EXISTS(SELECT 1 FROM classification.hierarchy WHERE release_id=id GROUP BY child_id HAVING count(*)<>1)
 THEN RAISE EXCEPTION 'ONET_INVALID_HIERARCHY_KIND'; END IF;
 IF EXISTS(WITH RECURSIVE walk(start_id,node_id,path,cycle) AS (
   SELECT child_id,parent_id,ARRAY[child_id,parent_id],false FROM classification.hierarchy WHERE release_id=id
   UNION ALL
   SELECT w.start_id,h.parent_id,w.path||h.parent_id,h.parent_id=ANY(w.path)
    FROM walk w JOIN classification.hierarchy h ON h.release_id=id AND h.child_id=w.node_id WHERE NOT w.cycle
  ) SELECT 1 FROM walk WHERE cycle)
 THEN RAISE EXCEPTION 'ONET_HIERARCHY_CYCLE'; END IF;
 IF EXISTS(SELECT 1 FROM classification.term t WHERE t.release_id=id AND
   ((t.source_attributes->>'hierarchy_level'<>'1' AND
     NOT EXISTS(SELECT 1 FROM classification.hierarchy h WHERE h.release_id=id AND h.child_id=t.term_id)) OR
    (t.source_attributes->>'hierarchy_level'='1' AND
     EXISTS(SELECT 1 FROM classification.hierarchy h WHERE h.release_id=id AND h.child_id=t.term_id))))
 THEN RAISE EXCEPTION 'ONET_OCCUPATION_PARENT_MISSING'; END IF;
END $$;

CREATE OR REPLACE FUNCTION classification.evidence_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE id text; s text;
BEGIN
 PERFORM retention.gate();
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'IMMUTABLE_ONET_CATALOG_RECORD: %',TG_TABLE_NAME; END IF;
 id:=NEW.release_id;
 SELECT state INTO s FROM classification.catalog_release WHERE release_id=id FOR UPDATE;
 IF s IS DISTINCT FROM 'STAGING' THEN RAISE EXCEPTION 'ONET_RELEASE_NOT_STAGING'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION classification.immutable_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_ONET_CATALOG_RECORD: %',TG_TABLE_NAME; END $$;
CREATE OR REPLACE FUNCTION classification.release_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'STAGING' THEN RAISE EXCEPTION 'ONET_READY_INSERT_FORBIDDEN'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP<>'UPDATE' OR OLD.state<>'STAGING' OR NEW.state<>'READY' OR
   (to_jsonb(OLD)-ARRAY['state','ready_at']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['state','ready_at'])
 THEN RAISE EXCEPTION 'IMMUTABLE_ONET_CATALOG_RECORD: catalog_release'; END IF;
 PERFORM classification.assert_catalog(OLD.release_id);
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER onet_release_guard BEFORE INSERT OR UPDATE OR DELETE
 ON classification.catalog_release FOR EACH ROW EXECUTE FUNCTION classification.release_guard();
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['source_file','term','hierarchy'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER onet_evidence_guard BEFORE INSERT OR UPDATE OR DELETE ON classification.%I
   FOR EACH ROW EXECUTE FUNCTION classification.evidence_guard()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['graph_load_node','graph_load_edge','activation_event'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER onet_immutable_guard BEFORE UPDATE OR DELETE ON classification.%I
   FOR EACH ROW EXECUTE FUNCTION classification.immutable_guard()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['catalog_release','source_file','term','hierarchy','graph_load_node','graph_load_edge','activation_event'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER onet_no_truncate BEFORE TRUNCATE ON classification.%I
   FOR EACH STATEMENT EXECUTE FUNCTION classification.immutable_guard()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['catalog_release','source_file','term','hierarchy','graph_load','graph_load_node',
   'graph_load_edge','graph_target','catalog_current','activation_event'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE ON classification.%I
   FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',name);
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION classification.import_onet_catalog(payload jsonb) RETURNS text
LANGUAGE plpgsql SET jit=off SET timezone='UTC' AS $$
DECLARE id text; r classification.catalog_release; normalized jsonb; value jsonb;
BEGIN
 PERFORM retention.gate();
 IF octet_length(payload::text)>16777216 OR jsonb_typeof(payload) IS DISTINCT FROM 'object' OR
   EXISTS(SELECT 1 FROM jsonb_object_keys(payload) k WHERE k NOT IN
    ('contract_version','release_id','scheme_id','source_version','taxonomy_version','sources','terms','hierarchy')) OR
   payload->>'contract_version' IS DISTINCT FROM 'jobtology-onet-catalog-v1' OR
   payload->>'scheme_id' IS DISTINCT FROM 'ONET' OR
   coalesce(payload->>'source_version','') !~ '^[0-9]+\.[0-9]+$' OR
   payload->>'taxonomy_version' IS DISTINCT FROM 'O*NET-SOC2019' OR
   length(btrim(coalesce(payload->>'release_id',''))) NOT BETWEEN 1 AND 200 OR
   jsonb_typeof(payload->'sources') IS DISTINCT FROM 'array' OR
   jsonb_typeof(payload->'terms') IS DISTINCT FROM 'array' OR
   jsonb_typeof(payload->'hierarchy') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'ONET_INVALID_PAYLOAD'; END IF;
 IF jsonb_array_length(payload->'sources')<>3 OR
   jsonb_array_length(payload->'terms') NOT BETWEEN 1 AND 20000 OR
   jsonb_array_length(payload->'hierarchy') NOT BETWEEN 1 AND 40000
 THEN RAISE EXCEPTION 'ONET_PAYLOAD_BOUNDS'; END IF;
 FOR value IN SELECT x FROM jsonb_array_elements(payload->'sources') x LOOP
  IF jsonb_typeof(value) IS DISTINCT FROM 'object' OR
    EXISTS(SELECT 1 FROM jsonb_object_keys(value) k WHERE k NOT IN
     ('file_id','source_uri','archive_path','sha256','byte_length','encoding','downloaded_at')) OR
    coalesce(value->>'file_id','') NOT IN('occupation_data','taxonomy','soc_structure') OR
    coalesce(value->>'source_uri','') !~ '^https://(www\.)?onetcenter\.org/' OR
    coalesce(value->>'archive_path','') !~ '^sources/(occupation_data\.json|taxonomy\.jsonld|soc_structure\.csv)$' OR
    value->>'archive_path' ~ '(^|/)\.\.?(/|$)' OR
    coalesce(value->>'sha256','') !~ '^[0-9a-f]{64}$' OR
    jsonb_typeof(value->'byte_length') IS DISTINCT FROM 'number' OR
    coalesce(value->>'byte_length','') !~ '^[0-9]+$' OR
    (value->>'byte_length')::bigint NOT BETWEEN 1 AND 1073741824 OR
    length(btrim(coalesce(value->>'encoding',''))) NOT BETWEEN 1 AND 40 OR
    jsonb_typeof(value->'downloaded_at') IS DISTINCT FROM 'string' OR
    coalesce(value->>'downloaded_at','') !~ '^\d{4}-\d{2}-\d{2}T.*(Z|[+-]\d{2}:\d{2})$'
  THEN RAISE EXCEPTION 'ONET_INVALID_SOURCE_FILE'; END IF;
  IF (value->>'file_id'='occupation_data' AND (value->>'archive_path'<>'sources/occupation_data.json' OR
      value->>'source_uri'<>'https://www.onetcenter.org/dl_files/database/db_'||replace(payload->>'source_version','.','_')||'_json/occupation_data.json')) OR
    (value->>'file_id'='taxonomy' AND (value->>'archive_path'<>'sources/taxonomy.jsonld' OR
      value->>'source_uri'<>'https://www.onetcenter.org/ctdl/graph/ce-8350d6ad-bc2a-11ef-8f5a-005056bdd76e')) OR
    (value->>'file_id'='soc_structure' AND (value->>'archive_path'<>'sources/soc_structure.csv' OR
      value->>'source_uri'<>'https://www.onetcenter.org/taxonomy/2019/structure/SOC_Structure.csv?fmt=csv'))
  THEN RAISE EXCEPTION 'ONET_SOURCE_VERSION_PIN_MISMATCH'; END IF;
 END LOOP;
 FOR value IN SELECT x FROM jsonb_array_elements(payload->'terms') x LOOP
  IF jsonb_typeof(value) IS DISTINCT FROM 'object' OR
    EXISTS(SELECT 1 FROM jsonb_object_keys(value) k WHERE k NOT IN
     ('term_id','code','term_kind','preferred_label','description','source_uri','file_id','source_locator','source_attributes')) OR
    coalesce(value->>'term_kind','') NOT IN('GROUP','OCCUPATION') OR
    (value->>'term_kind'='GROUP' AND (coalesce(value->>'code','') !~ '^[0-9]{2}-[0-9]{4}$' OR
      value->>'term_id' IS DISTINCT FROM 'urn:jobtology:onet:group:'||(value->>'code'))) OR
    (value->>'term_kind'='OCCUPATION' AND (coalesce(value->>'code','') !~ '^[0-9]{2}-[0-9]{4}\.[0-9]{2}$' OR
      value->>'term_id' IS DISTINCT FROM 'urn:jobtology:onet:occupation:'||(value->>'code'))) OR
    length(btrim(coalesce(value->>'preferred_label',''))) NOT BETWEEN 1 AND 1000 OR
    jsonb_typeof(value->'description') NOT IN('null','string') OR
    coalesce(value->>'source_uri','') !~ '^(https?://|urn:)' OR
    length(btrim(coalesce(value->>'file_id','')))=0 OR
    length(btrim(coalesce(value->>'source_locator','')))=0 OR
    jsonb_typeof(value->'source_attributes') IS DISTINCT FROM 'object' OR
    coalesce(value->'source_attributes'->>'hierarchy_level','') !~ '^[1-5]$' OR
    jsonb_typeof(value->'source_attributes'->'hierarchy_level') IS DISTINCT FROM 'number' OR
    (value->'source_attributes' ? 'language' AND value->'source_attributes'->>'language' NOT IN('en','en-US'))
  THEN RAISE EXCEPTION 'ONET_INVALID_TERM'; END IF;
 END LOOP;
 FOR value IN SELECT x FROM jsonb_array_elements(payload->'hierarchy') x LOOP
  IF jsonb_typeof(value) IS DISTINCT FROM 'object' OR
    EXISTS(SELECT 1 FROM jsonb_object_keys(value) k WHERE k NOT IN
     ('child_id','parent_id','file_id','source_locator','source_uri','source_attributes')) OR
    coalesce(value->>'child_id','') !~ '^urn:jobtology:onet:(occupation|group):' OR
    coalesce(value->>'parent_id','') !~ '^urn:jobtology:onet:(occupation|group):' OR
    length(btrim(coalesce(value->>'file_id','')))=0 OR
    length(btrim(coalesce(value->>'source_locator','')))=0 OR
    coalesce(value->>'source_uri','') !~ '^(https?://|urn:)' OR
    jsonb_typeof(value->'source_attributes') IS DISTINCT FROM 'object'
  THEN RAISE EXCEPTION 'ONET_INVALID_HIERARCHY'; END IF;
 END LOOP;
 -- Normalize only timestamp spelling. All source facts, URIs and locators remain.
 normalized:=jsonb_set(payload,'{sources}',(SELECT jsonb_agg(
   x||jsonb_build_object('downloaded_at',(x->>'downloaded_at')::timestamptz) ORDER BY x->>'file_id')
   FROM jsonb_array_elements(payload->'sources') x));
 normalized:=jsonb_set(normalized,'{terms}',(SELECT jsonb_agg(x ORDER BY x->>'term_id')
   FROM jsonb_array_elements(payload->'terms') x));
 normalized:=jsonb_set(normalized,'{hierarchy}',(SELECT jsonb_agg(x ORDER BY x->>'child_id',x->>'parent_id')
   FROM jsonb_array_elements(payload->'hierarchy') x));
 id:=payload->>'release_id';
 SELECT * INTO r FROM classification.catalog_release WHERE release_id=id FOR UPDATE;
 IF FOUND THEN
  IF r.normalized_input IS DISTINCT FROM normalized OR r.state<>'READY'
  THEN RAISE EXCEPTION 'ONET_RELEASE_REPLAY_CHANGED'; END IF;
  PERFORM classification.assert_catalog(id); RETURN id;
 END IF;
 INSERT INTO classification.catalog_release(release_id,scheme_id,source_version,taxonomy_version,
   contract_version,normalized_input,manifest_hash)
 VALUES(id,'ONET',payload->>'source_version',payload->>'taxonomy_version',payload->>'contract_version',
   normalized,classification.hash(normalized));
 INSERT INTO classification.source_file
 SELECT id,f.* FROM jsonb_to_recordset(normalized->'sources') AS f(file_id text,source_uri text,
   archive_path text,sha256 text,byte_length bigint,encoding text,downloaded_at timestamptz);
 INSERT INTO classification.term
 SELECT id,t.* FROM jsonb_to_recordset(normalized->'terms') AS t(term_id text,code text,term_kind text,
   preferred_label text,description text,source_uri text,file_id text,source_locator text,source_attributes jsonb);
 INSERT INTO classification.hierarchy
 SELECT id,h.* FROM jsonb_to_recordset(normalized->'hierarchy') AS h(child_id text,parent_id text,
   file_id text,source_locator text,source_uri text,source_attributes jsonb);
 UPDATE classification.catalog_release SET state='READY',ready_at=clock_timestamp() WHERE release_id=id;
 RETURN id;
END $$;

CREATE OR REPLACE VIEW classification.current_term AS
 SELECT t.* FROM classification.catalog_current c JOIN classification.term t USING(release_id);
CREATE OR REPLACE VIEW classification.current_hierarchy AS
 SELECT h.* FROM classification.catalog_current c JOIN classification.hierarchy h USING(release_id);
COMMENT ON SCHEMA classification IS
 'Independent source-stated O*NET reference catalogues. No posting classification or paid inference.';
COMMENT ON TABLE classification.catalog_release IS
 'Immutable imported reference release; imported_at is repository processing time, never collection or source publication time.';
COMMIT;
