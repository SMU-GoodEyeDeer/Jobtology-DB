-- Additive official O*NET detail reference evidence. Existing catalogue rows are read-only.
BEGIN;
SELECT retention.gate();
CREATE SCHEMA IF NOT EXISTS onet_detail;
CREATE OR REPLACE FUNCTION onet_detail.hash(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to('jobtology-onet-details-v1:'||value::text,'UTF8')),'hex')
$$;
CREATE OR REPLACE FUNCTION onet_detail.with_content_hash(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT (value-'content_hash')||jsonb_build_object('content_hash',onet_detail.hash(value-'content_hash'))
$$;
CREATE TABLE IF NOT EXISTS onet_detail.catalog_release (
 release_id text PRIMARY KEY CHECK(length(release_id) BETWEEN 1 AND 200),
 base_release_id text NOT NULL REFERENCES classification.catalog_release,
 base_catalogue_sha256 text NOT NULL CHECK(base_catalogue_sha256 ~ '^[0-9a-f]{64}$'),
 scheme_id text NOT NULL CHECK(scheme_id='ONET'), source_version text NOT NULL CHECK(source_version='31.0'),
 contract_version text NOT NULL CHECK(contract_version='jobtology-onet-details-v1'),
 state text NOT NULL DEFAULT 'STAGING' CHECK(state IN('STAGING','READY')),
 normalized_input jsonb NOT NULL, manifest_hash text NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),ready_at timestamptz,
 CHECK((state='READY')=(ready_at IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS onet_detail.source_file (
 release_id text NOT NULL REFERENCES onet_detail.catalog_release,file_id text NOT NULL,
 source_uri text NOT NULL,archive_path text NOT NULL,sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 byte_length bigint NOT NULL CHECK(byte_length>0),encoding text NOT NULL,downloaded_at timestamptz NOT NULL,
 PRIMARY KEY(release_id,file_id),UNIQUE(release_id,archive_path)
);
CREATE TABLE IF NOT EXISTS onet_detail.node (
 release_id text NOT NULL REFERENCES onet_detail.catalog_release,id text NOT NULL,
 type text NOT NULL,properties jsonb NOT NULL CHECK(jsonb_typeof(properties)='object'),
 PRIMARY KEY(release_id,id),CHECK(id LIKE 'urn:jobtology:onet-detail:%')
);
CREATE TABLE IF NOT EXISTS onet_detail.edge (
 release_id text NOT NULL REFERENCES onet_detail.catalog_release,id text NOT NULL,
 source_id text NOT NULL,target_id text NOT NULL,type text NOT NULL,
 properties jsonb NOT NULL CHECK(jsonb_typeof(properties)='object'),
 PRIMARY KEY(release_id,id),CHECK(id LIKE 'urn:jobtology:onet-detail:edge:%')
);
CREATE TABLE IF NOT EXISTS onet_detail.graph_load (
 load_id text PRIMARY KEY,
 release_id text NOT NULL REFERENCES onet_detail.catalog_release,
 database_id text NOT NULL,
 previous_load_id text REFERENCES onet_detail.graph_load,
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
 ON onet_detail.graph_load(database_id) WHERE state='RUNNING';
CREATE TABLE IF NOT EXISTS onet_detail.graph_load_node (
 load_id text NOT NULL REFERENCES onet_detail.graph_load,
 node_id text NOT NULL,
 labels text[] NOT NULL,
 properties jsonb NOT NULL,
 content_hash text NOT NULL,
 previous_labels text[],
 previous_properties jsonb,
 previous_content_hash text,
 PRIMARY KEY(load_id,node_id)
);
CREATE TABLE IF NOT EXISTS onet_detail.graph_load_edge (
 load_id text NOT NULL REFERENCES onet_detail.graph_load,
 edge_id text NOT NULL,
 start_id text NOT NULL,
 end_id text NOT NULL,
 edge_type text NOT NULL,
 properties jsonb NOT NULL,
 content_hash text NOT NULL,
 previous_properties jsonb,
 previous_content_hash text,
 PRIMARY KEY(load_id,edge_id)
);
CREATE TABLE IF NOT EXISTS onet_detail.graph_load_occupation (
 load_id text NOT NULL REFERENCES onet_detail.graph_load,node_id text NOT NULL,
 labels text[] NOT NULL,properties jsonb NOT NULL,content_hash text NOT NULL,
 PRIMARY KEY(load_id,node_id)
);
CREATE TABLE IF NOT EXISTS onet_detail.graph_target (
 database_id text PRIMARY KEY,
 release_id text NOT NULL REFERENCES onet_detail.catalog_release,
 load_id text NOT NULL REFERENCES onet_detail.graph_load
);
CREATE TABLE IF NOT EXISTS onet_detail.catalog_current (
 scheme_id text PRIMARY KEY CHECK(scheme_id='ONET'),
 release_id text NOT NULL REFERENCES onet_detail.catalog_release,
 database_id text NOT NULL,
 load_id text NOT NULL REFERENCES onet_detail.graph_load,
 activated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS onet_detail.activation_event (
 activation_id text PRIMARY KEY,
 scheme_id text NOT NULL CHECK(scheme_id='ONET'),
 release_id text NOT NULL REFERENCES onet_detail.catalog_release,
 previous_release_id text REFERENCES onet_detail.catalog_release,
 database_id text NOT NULL,
 load_id text NOT NULL REFERENCES onet_detail.graph_load,
 activated_at timestamptz NOT NULL
);

CREATE OR REPLACE FUNCTION onet_detail.assert_catalog(id text) RETURNS void
LANGUAGE plpgsql STABLE SET jit=off AS $$
#variable_conflict use_variable
DECLARE r onet_detail.catalog_release;
BEGIN
 SELECT * INTO STRICT r FROM onet_detail.catalog_release WHERE release_id=id;
 IF onet_detail.hash(r.normalized_input)<>r.manifest_hash OR
 (SELECT coalesce(jsonb_agg(to_jsonb(n)-'release_id' ORDER BY n.id),'[]') FROM onet_detail.node n WHERE release_id=id)
 IS DISTINCT FROM r.normalized_input->'nodes' OR
 (SELECT coalesce(jsonb_agg(to_jsonb(e)-'release_id' ORDER BY e.id),'[]') FROM onet_detail.edge e WHERE release_id=id)
 IS DISTINCT FROM r.normalized_input->'edges' OR
 (SELECT jsonb_agg(to_jsonb(f)-'release_id' ORDER BY file_id) FROM onet_detail.source_file f WHERE release_id=id)
 IS DISTINCT FROM r.normalized_input->'sources'
 THEN RAISE EXCEPTION 'ONET_DETAILS_INVENTORY_MISMATCH'; END IF;
 IF NOT EXISTS(SELECT 1 FROM classification.catalog_release b WHERE b.release_id=r.base_release_id AND b.state='READY'
 AND b.source_version=r.source_version)
 THEN RAISE EXCEPTION 'ONET_DETAILS_BASE_PIN_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM onet_detail.edge e WHERE e.release_id=id AND
  (NOT EXISTS(SELECT 1 FROM onet_detail.node n WHERE n.release_id=id AND n.id=e.target_id) OR
   NOT EXISTS(SELECT 1 FROM onet_detail.node n WHERE n.release_id=id AND n.id=e.source_id) AND
   NOT EXISTS(SELECT 1 FROM classification.term t WHERE t.release_id=r.base_release_id AND t.term_kind='OCCUPATION'
    AND t.term_id=e.source_id AND t.code IN(SELECT jsonb_array_elements_text(r.normalized_input->'scope_codes')))))
 THEN RAISE EXCEPTION 'ONET_DETAILS_INVALID_ENDPOINT'; END IF;
 IF EXISTS(SELECT 1 FROM onet_detail.edge e
 LEFT JOIN onet_detail.node a ON a.release_id=e.release_id AND a.id=e.source_id
 JOIN onet_detail.node b ON b.release_id=e.release_id AND b.id=e.target_id
 WHERE e.release_id=id AND CASE e.type
 WHEN 'ONET_DETAIL_PARENT' THEN a.type='ELEMENT' AND b.type='ELEMENT'
 WHEN 'ONET_SOFTWARE_TYPE' THEN a.type='SOFTWARE' AND b.type='ELEMENT'
 WHEN 'ONET_ANCHOR_ELEMENT' THEN a.type='LEVEL_ANCHOR' AND b.type='ELEMENT'
 WHEN 'ONET_ANCHOR_SCALE' THEN a.type='LEVEL_ANCHOR' AND b.type='SCALE'
 WHEN 'ONET_CATEGORY_SCALE' THEN a.type='TASK_CATEGORY' AND b.type='SCALE'
 WHEN 'ONET_SOFTWARE_EXAMPLE' THEN a.id IS NULL AND b.type='SOFTWARE'
 WHEN 'ONET_TASK' THEN a.id IS NULL AND b.type='TASK'
 WHEN 'ONET_TASK_RATING' THEN a.id IS NULL AND b.type='TASK'
 ELSE a.id IS NULL AND b.type='ELEMENT' END IS DISTINCT FROM true)
 THEN RAISE EXCEPTION 'ONET_DETAILS_ENDPOINT_KIND_MISMATCH'; END IF;

END $$;
CREATE OR REPLACE FUNCTION onet_detail.evidence_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
#variable_conflict use_variable
DECLARE id text; s text;
BEGIN
 PERFORM retention.gate();
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'IMMUTABLE_ONET_DETAILS_CATALOG_RECORD: %',TG_TABLE_NAME; END IF;
 id:=NEW.release_id;
 SELECT state INTO s FROM onet_detail.catalog_release WHERE release_id=id FOR UPDATE;
 IF s IS DISTINCT FROM 'STAGING' THEN RAISE EXCEPTION 'ONET_DETAILS_RELEASE_NOT_STAGING'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION onet_detail.immutable_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
#variable_conflict use_variable
BEGIN RAISE EXCEPTION 'IMMUTABLE_ONET_DETAILS_CATALOG_RECORD: %',TG_TABLE_NAME; END $$;
CREATE OR REPLACE FUNCTION onet_detail.release_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
#variable_conflict use_variable
BEGIN
 PERFORM retention.gate();
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'STAGING' THEN RAISE EXCEPTION 'ONET_DETAILS_READY_INSERT_FORBIDDEN'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP<>'UPDATE' OR OLD.state<>'STAGING' OR NEW.state<>'READY' OR
   (to_jsonb(OLD)-ARRAY['state','ready_at']) IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['state','ready_at'])
 THEN RAISE EXCEPTION 'IMMUTABLE_ONET_DETAILS_CATALOG_RECORD: catalog_release'; END IF;
 PERFORM onet_detail.assert_catalog(OLD.release_id);
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER onet_release_guard BEFORE INSERT OR UPDATE OR DELETE
 ON onet_detail.catalog_release FOR EACH ROW EXECUTE FUNCTION onet_detail.release_guard();
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['source_file','node','edge'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER onet_evidence_guard BEFORE INSERT OR UPDATE OR DELETE ON onet_detail.%I
   FOR EACH ROW EXECUTE FUNCTION onet_detail.evidence_guard()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['graph_load_node','graph_load_edge','graph_load_occupation','activation_event'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER onet_immutable_guard BEFORE UPDATE OR DELETE ON onet_detail.%I
   FOR EACH ROW EXECUTE FUNCTION onet_detail.immutable_guard()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['catalog_release','source_file','node','edge','graph_load_node','graph_load_edge','graph_load_occupation','activation_event'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER onet_no_truncate BEFORE TRUNCATE ON onet_detail.%I
   FOR EACH STATEMENT EXECUTE FUNCTION onet_detail.immutable_guard()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['catalog_release','source_file','node','edge','graph_load','graph_load_node',
   'graph_load_edge','graph_load_occupation','graph_target','catalog_current','activation_event'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE ON onet_detail.%I
   FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',name);
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION onet_detail.import_onet_catalog(payload jsonb,base_input text) RETURNS text
LANGUAGE plpgsql SET jit=off SET timezone='UTC' AS $$
#variable_conflict use_variable
DECLARE id text; r onet_detail.catalog_release; normalized jsonb; value jsonb; base jsonb;
BEGIN
 PERFORM retention.gate();
 IF octet_length(base_input)>16777216 OR encode(sha256(convert_to(base_input,'UTF8')),'hex')
 IS DISTINCT FROM payload->>'base_catalogue_sha256' THEN RAISE EXCEPTION 'ONET_DETAILS_BASE_BYTES_MISMATCH'; END IF;
 base:=base_input::jsonb;
 base:=jsonb_set(base,'{sources}',(SELECT jsonb_agg(x||jsonb_build_object('downloaded_at',
 (x->>'downloaded_at')::timestamptz) ORDER BY x->>'file_id') FROM jsonb_array_elements(base->'sources') x));
 base:=jsonb_set(base,'{terms}',(SELECT jsonb_agg(x ORDER BY x->>'term_id') FROM jsonb_array_elements(base->'terms') x));
 base:=jsonb_set(base,'{hierarchy}',(SELECT jsonb_agg(x ORDER BY x->>'child_id',x->>'parent_id') FROM jsonb_array_elements(base->'hierarchy') x));
 IF NOT EXISTS(SELECT 1 FROM classification.catalog_release b WHERE b.release_id=payload->>'base_release_id'
 AND b.state='READY' AND b.normalized_input=base) THEN RAISE EXCEPTION 'ONET_DETAILS_BASE_PIN_MISMATCH'; END IF;
 IF octet_length(payload::text)>67108864 OR jsonb_typeof(payload) IS DISTINCT FROM 'object' OR
 payload->>'contract_version' IS DISTINCT FROM 'jobtology-onet-details-v1' OR
 payload->>'scheme_id' IS DISTINCT FROM 'ONET' OR payload->>'source_version' IS DISTINCT FROM '31.0' OR
 coalesce(payload->>'release_id','') !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$' OR
 jsonb_typeof(payload->'nodes') IS DISTINCT FROM 'array' OR jsonb_typeof(payload->'edges') IS DISTINCT FROM 'array' OR
 jsonb_typeof(payload->'sources') IS DISTINCT FROM 'array' OR jsonb_typeof(payload->'scope_codes') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'ONET_DETAILS_INVALID_PAYLOAD'; END IF;
 IF jsonb_array_length(payload->'nodes') NOT BETWEEN 1 AND 30000 OR
 jsonb_array_length(payload->'edges') NOT BETWEEN 1 AND 100000 OR
 jsonb_array_length(payload->'sources') NOT BETWEEN 1 AND 20 OR
 jsonb_array_length(payload->'scope_codes') NOT BETWEEN 1 AND 100
 THEN RAISE EXCEPTION 'ONET_DETAILS_PAYLOAD_BOUNDS'; END IF;
 IF payload->'scope_codes' IS DISTINCT FROM (SELECT jsonb_agg(t.code ORDER BY t.code)
 FROM classification.term t WHERE t.release_id=payload->>'base_release_id' AND t.term_kind='OCCUPATION'
 AND (t.code LIKE '15-12%' OR t.code IN('15-2051.00','11-3021.00','17-2061.00')))
 THEN RAISE EXCEPTION 'ONET_DETAILS_SCOPE_PIN_MISMATCH'; END IF;
 FOR value IN SELECT x FROM jsonb_array_elements(payload->'sources') x LOOP
  IF coalesce(value->>'file_id','') !~ '^[a-z_]+$' OR
   value->>'source_uri' IS DISTINCT FROM 'https://www.onetcenter.org/dl_files/database/db_31_0_csv/'||(value->>'file_id')||'.csv' OR
   value->>'archive_path' IS DISTINCT FROM 'sources/'||(value->>'file_id')||'.csv' OR
   coalesce(value->>'file_id','') NOT IN('software_skills','essential_skills','transferable_skills','knowledge','task_statements',
    'task_ratings','content_model_reference','scales_reference','task_categories','level_scale_anchors') OR
   coalesce(value->>'archive_path','') !~ '^sources/[A-Za-z0-9_.-]+$' OR
   coalesce(value->>'sha256','') !~ '^[0-9a-f]{64}$' OR
   (value->>'byte_length')::bigint NOT BETWEEN 1 AND 67108864
  THEN RAISE EXCEPTION 'ONET_DETAILS_INVALID_SOURCE'; END IF;
 END LOOP;
 FOR value IN SELECT x FROM jsonb_array_elements(payload->'nodes') x LOOP
  IF coalesce(value->>'id','') !~ '^urn:jobtology:onet-detail:[A-Za-z0-9_.:%-]+$' OR
   coalesce(value->>'type','') NOT IN('ELEMENT','TASK','SOFTWARE','SCALE','TASK_CATEGORY','LEVEL_ANCHOR') OR
   jsonb_typeof(value->'properties') IS DISTINCT FROM 'object'
  THEN RAISE EXCEPTION 'ONET_DETAILS_INVALID_NODE'; END IF;
 END LOOP;
 FOR value IN SELECT x FROM jsonb_array_elements(payload->'edges') x LOOP
  IF coalesce(value->>'id','') !~ '^urn:jobtology:onet-detail:edge:[0-9a-f]{64}$' OR
   coalesce(value->>'type','') NOT IN('ONET_DETAIL_PARENT','ONET_SOFTWARE_EXAMPLE','ONET_SOFTWARE_TYPE','ONET_ESSENTIAL_SKILL','ONET_TRANSFERABLE_SKILL','ONET_KNOWLEDGE','ONET_TASK','ONET_TASK_RATING','ONET_ANCHOR_ELEMENT','ONET_ANCHOR_SCALE','ONET_CATEGORY_SCALE') OR
   jsonb_typeof(value->'properties') IS DISTINCT FROM 'object'
  THEN RAISE EXCEPTION 'ONET_DETAILS_INVALID_EDGE'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM (SELECT properties FROM jsonb_to_recordset(payload->'nodes') x(properties jsonb)
 UNION ALL SELECT properties FROM jsonb_to_recordset(payload->'edges') x(properties jsonb)) v,
 LATERAL jsonb_object_keys(v.properties) k WHERE k IN('id','managed_by','scheme_id','release_id','source_version',
 'base_release_id','current','content_hash','kind')) THEN RAISE EXCEPTION 'ONET_DETAILS_RESERVED_PROPERTY'; END IF;
 normalized:=jsonb_set(payload,'{sources}',(SELECT jsonb_agg(x||jsonb_build_object('downloaded_at',
  (x->>'downloaded_at')::timestamptz) ORDER BY x->>'file_id') FROM jsonb_array_elements(payload->'sources') x));
 normalized:=jsonb_set(normalized,'{nodes}',(SELECT jsonb_agg(x ORDER BY x->>'id') FROM jsonb_array_elements(payload->'nodes') x));
 normalized:=jsonb_set(normalized,'{edges}',(SELECT jsonb_agg(x ORDER BY x->>'id') FROM jsonb_array_elements(payload->'edges') x));
 id:=payload->>'release_id';
 SELECT * INTO r FROM onet_detail.catalog_release WHERE release_id=id FOR UPDATE;
 IF FOUND THEN
  IF r.normalized_input IS DISTINCT FROM normalized OR r.state<>'READY'
  THEN RAISE EXCEPTION 'ONET_DETAILS_RELEASE_REPLAY_CHANGED'; END IF;
  PERFORM onet_detail.assert_catalog(id); RETURN id;
 END IF;
 INSERT INTO onet_detail.catalog_release(release_id,base_release_id,base_catalogue_sha256,scheme_id,source_version,
 contract_version,normalized_input,manifest_hash) VALUES(id,payload->>'base_release_id',payload->>'base_catalogue_sha256',
 'ONET','31.0',payload->>'contract_version',normalized,onet_detail.hash(normalized));
 INSERT INTO onet_detail.source_file SELECT id,f.* FROM jsonb_to_recordset(normalized->'sources')
 f(file_id text,source_uri text,archive_path text,sha256 text,byte_length bigint,encoding text,downloaded_at timestamptz);
 INSERT INTO onet_detail.node SELECT id,n.* FROM jsonb_to_recordset(normalized->'nodes') n(id text,type text,properties jsonb);
 INSERT INTO onet_detail.edge SELECT id,e.* FROM jsonb_to_recordset(normalized->'edges')
 e(id text,source_id text,target_id text,type text,properties jsonb);
 UPDATE onet_detail.catalog_release SET state='READY',ready_at=clock_timestamp() WHERE release_id=id;
 RETURN id;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA onet_detail FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION onet_detail.import_onet_catalog(jsonb,text) FROM PUBLIC;
COMMIT;
