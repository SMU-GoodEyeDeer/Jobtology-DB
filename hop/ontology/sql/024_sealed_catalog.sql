BEGIN;
CREATE TABLE IF NOT EXISTS catalog.integrity_attestation (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 generation integer NOT NULL CHECK (generation=1),
 contract_version text NOT NULL CHECK (contract_version='hop-catalog-source-v1'),
 mode text NOT NULL CHECK (mode='SOURCE_ONLY'),
 manifest_hash text NOT NULL,
 observation_hash text NOT NULL,
 source_inventory_hash text NOT NULL,
 membership_hash text NOT NULL,
 node_count bigint NOT NULL,
 edge_count bigint NOT NULL,
 node_hash text NOT NULL,
 edge_hash text NOT NULL,
 attested_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON catalog.integrity_attestation FROM PUBLIC;
CREATE OR REPLACE TRIGGER catalog_attestation_immutable BEFORE UPDATE OR DELETE ON catalog.integrity_attestation
 FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
CREATE INDEX IF NOT EXISTS catalog_latest_graph_load ON ontology.graph_load(database_id,started_at DESC,load_id DESC);

CREATE OR REPLACE FUNCTION catalog._lock_release(id text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(71243,19002);
 PERFORM pg_advisory_xact_lock(hashtextextended('catalog-seal:'||id,0));
END $$;

CREATE OR REPLACE FUNCTION catalog._write_boundary() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed'
 THEN RAISE EXCEPTION 'CATALOG_WRITES_REQUIRE_READ_COMMITTED'; END IF;
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(71243,19002);
 RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION catalog._fence_graph_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE rid text; sealed_hash text;
BEGIN
  FOR rid IN SELECT DISTINCT release_id FROM catalog_inserted ORDER BY release_id LOOP
  SELECT manifest_hash INTO sealed_hash FROM ontology.corpus_release WHERE release_id=rid FOR SHARE;
  IF sealed_hash IS NOT NULL THEN RAISE EXCEPTION 'SEALED_CATALOG_WRITE_FENCE: % %',TG_TABLE_NAME,rid; END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION catalog._protect_audit_truncate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'CATALOG_AUDIT_TRUNCATE_FORBIDDEN: %',TG_TABLE_NAME;
END $$;
CREATE OR REPLACE TRIGGER catalog_attestation_no_truncate BEFORE TRUNCATE ON catalog.integrity_attestation
 FOR EACH STATEMENT EXECUTE FUNCTION catalog._protect_audit_truncate();
CREATE OR REPLACE TRIGGER catalog_approval_no_truncate BEFORE TRUNCATE ON catalog.catalog_approval
 FOR EACH STATEMENT EXECUTE FUNCTION catalog._protect_audit_truncate();

-- A shared identity/source run may be used by more than one release. Acquire
-- locks in lexical release order so two writers cannot invert their order.
CREATE OR REPLACE FUNCTION catalog._fence_row() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE old_row jsonb; new_row jsonb; rid text; sealed_hash text;
 table_name text:=TG_TABLE_SCHEMA||'.'||TG_TABLE_NAME;
BEGIN
 IF TG_OP='DELETE' THEN old_row:=to_jsonb(OLD); ELSE new_row:=to_jsonb(NEW); END IF;
 IF TG_OP='UPDATE' THEN old_row:=to_jsonb(OLD); END IF;
 IF TG_OP='INSERT' AND table_name IN ('ontology.entity','ontology.revision','ontology.source_relation') THEN
  CASE TG_TABLE_NAME
   WHEN 'entity' THEN
    IF EXISTS(SELECT 1 FROM ontology.entity t WHERE t.entity_id=NEW.entity_id
     AND to_jsonb(t)-'created_at'=new_row-'created_at') THEN RETURN NEW; END IF;
   WHEN 'revision' THEN
    IF EXISTS(SELECT 1 FROM ontology.revision t WHERE t.revision_id=NEW.revision_id
     AND to_jsonb(t)-'created_at'=new_row-'created_at') THEN RETURN NEW; END IF;
   WHEN 'source_relation' THEN
    IF EXISTS(SELECT 1 FROM ontology.source_relation t WHERE t.relation_id=NEW.relation_id
     AND to_jsonb(t)-'created_at'=new_row-'created_at') THEN RETURN NEW; END IF;
  END CASE;
 END IF;
 IF TG_TABLE_SCHEMA='ontology' AND TG_TABLE_NAME NOT IN
  ('entity','revision','source_relation','observation_run','posting_seen') THEN
   FOR rid IN SELECT DISTINCT release_id FROM (VALUES (new_row->>'release_id'),(old_row->>'release_id')) refs(release_id)
    WHERE release_id IS NOT NULL ORDER BY release_id LOOP
    SELECT manifest_hash INTO sealed_hash FROM ontology.corpus_release WHERE release_id=rid FOR SHARE;
    IF sealed_hash IS NOT NULL THEN RAISE EXCEPTION 'SEALED_CATALOG_WRITE_FENCE: % %',table_name,rid; END IF;
   END LOOP;
  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
 END IF;
 FOR rid IN
  SELECT DISTINCT release_id FROM (
    SELECT p.release_id FROM ontology.source_pin p
     WHERE TG_TABLE_SCHEMA='ingestion' AND (p.run_id=old_row->>'run_id' OR p.run_id=new_row->>'run_id')
   UNION ALL
    SELECT m.release_id FROM ontology.observation_history_member m
     WHERE (TG_TABLE_SCHEMA='ingestion' OR TG_TABLE_NAME IN ('observation_run','posting_seen'))
      AND (m.run_id=old_row->>'run_id' OR m.run_id=new_row->>'run_id')
    UNION ALL
    SELECT p.release_id FROM ingestion.dependency d JOIN ontology.source_pin p ON p.run_id=d.run_id
     WHERE TG_TABLE_SCHEMA='ingestion' AND (d.input_run_id=old_row->>'run_id' OR d.input_run_id=new_row->>'run_id')
    UNION ALL
    SELECT m.release_id FROM ingestion.dependency d JOIN ontology.observation_history_member m ON m.run_id=d.run_id
     WHERE TG_TABLE_SCHEMA='ingestion' AND (d.input_run_id=old_row->>'run_id' OR d.input_run_id=new_row->>'run_id')
   UNION ALL
   SELECT p.release_id FROM ingestion.dependency d JOIN ontology.source_pin p ON p.run_id=d.run_id
    WHERE table_name='ingestion.run' AND (d.input_run_id=old_row->>'run_id' OR d.input_run_id=new_row->>'run_id')
   UNION ALL
   SELECT m.release_id FROM ingestion.dependency d JOIN ontology.observation_history_member m ON m.run_id=d.run_id
    WHERE table_name='ingestion.run' AND (d.input_run_id=old_row->>'run_id' OR d.input_run_id=new_row->>'run_id')
   UNION ALL
   SELECT m.release_id FROM ontology.release_revision m
    WHERE TG_TABLE_NAME='entity' AND (m.entity_id=old_row->>'entity_id' OR m.entity_id=new_row->>'entity_id')
   UNION ALL
   SELECT m.release_id FROM ontology.release_revision m
    WHERE TG_TABLE_NAME='revision' AND (m.revision_id=old_row->>'revision_id' OR m.revision_id=new_row->>'revision_id')
   UNION ALL
   SELECT m.release_id FROM ontology.release_relation m
    WHERE TG_TABLE_NAME='source_relation' AND (m.relation_id=old_row->>'relation_id' OR m.relation_id=new_row->>'relation_id')
   UNION ALL
   SELECT m.release_id FROM ontology.observation_history_member m
    JOIN ontology.posting_seen s USING(run_id)
    WHERE TG_TABLE_NAME='posting_seen' AND (s.run_id=old_row->>'run_id' OR s.run_id=new_row->>'run_id')
 ) affected WHERE release_id IS NOT NULL ORDER BY release_id
 LOOP
  SELECT manifest_hash INTO sealed_hash FROM ontology.corpus_release WHERE release_id=rid FOR SHARE;
  IF sealed_hash IS NOT NULL
  THEN RAISE EXCEPTION 'SEALED_CATALOG_WRITE_FENCE: % %',table_name,rid; END IF;
 END LOOP;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE OR REPLACE FUNCTION catalog._fence_truncate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'SEALED_CATALOG_TRUNCATE_FENCE: %',TG_TABLE_NAME;
END $$;

CREATE OR REPLACE FUNCTION catalog._serialize_metadata() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE rid text:=coalesce(NEW.release_id,OLD.release_id);
BEGIN
 PERFORM catalog._lock_release(rid);
 IF TG_TABLE_NAME='corpus_release' AND TG_OP='UPDATE' THEN
  IF OLD.manifest_hash IS NOT NULL AND
   (NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash OR NEW.manifest IS DISTINCT FROM OLD.manifest OR
     NEW.pipeline_version IS DISTINCT FROM OLD.pipeline_version OR
     NEW.methodology_version IS DISTINCT FROM OLD.methodology_version OR
     NEW.created_at IS DISTINCT FROM OLD.created_at OR
     NEW.data_as_of IS DISTINCT FROM OLD.data_as_of)
  THEN RAISE EXCEPTION 'SEALED_CATALOG_RELEASE_IMMUTABLE'; END IF;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE OR REPLACE TRIGGER catalog_serialize_release BEFORE UPDATE OR DELETE ON ontology.corpus_release
 FOR EACH ROW EXECUTE FUNCTION catalog._serialize_metadata();
CREATE OR REPLACE TRIGGER catalog_serialize_load BEFORE INSERT OR UPDATE OR DELETE ON ontology.graph_load
 FOR EACH ROW EXECUTE FUNCTION catalog._serialize_metadata();

DO $$ DECLARE item text; schema_name text; table_name text;
BEGIN
 FOREACH item IN ARRAY ARRAY[
  'ingestion.run','ingestion.partition','ingestion.document','ingestion.record','ingestion.dependency','ingestion.rejected_row',
  'ontology.source_pin','ontology.release_source_run','ontology.input_record','ontology.entity','ontology.revision',
  'ontology.release_revision','ontology.revision_support','ontology.source_relation','ontology.release_relation',
  'ontology.quality_observation','ontology.observation_run','ontology.posting_seen','ontology.observation_freeze',
  'ontology.observation_history_member','ontology.posting_observation','ontology.observation_membership',
  'ontology.entity_observation_state','ontology.catalog_source_mode',
  'ontology.review_freeze','ontology.posting_selection','ontology.link_selection','ontology.rule_freeze',
  'ontology.rule_selection','ontology.rule_evidence','ontology.release_claim','ontology.release_position',
  'ontology.release_mapping','ontology.requirement_freeze','ontology.requirement_selection',
  'ontology.requirement_membership','ontology.document_input_set','ontology.document_input',
  'ontology.artifact_document','ontology.document_section'] LOOP
  schema_name:=split_part(item,'.',1); table_name:=split_part(item,'.',2);
   EXECUTE format('CREATE OR REPLACE TRIGGER catalog_write_boundary BEFORE INSERT OR UPDATE OR DELETE ON %I.%I FOR EACH STATEMENT EXECUTE FUNCTION catalog._write_boundary()',schema_name,table_name);
   EXECUTE format('CREATE OR REPLACE TRIGGER catalog_sealed_row BEFORE INSERT OR UPDATE OR DELETE ON %I.%I FOR EACH ROW EXECUTE FUNCTION catalog._fence_row()',schema_name,table_name);
   EXECUTE format('CREATE OR REPLACE TRIGGER catalog_sealed_truncate BEFORE TRUNCATE ON %I.%I FOR EACH STATEMENT EXECUTE FUNCTION catalog._fence_truncate()',schema_name,table_name);
 END LOOP;
END $$;
DO $$ DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['graph_node','graph_edge'] LOOP
   EXECUTE format('CREATE OR REPLACE TRIGGER catalog_write_boundary BEFORE INSERT OR UPDATE OR DELETE ON ontology.%I FOR EACH STATEMENT EXECUTE FUNCTION catalog._write_boundary()',name);
   EXECUTE format('CREATE OR REPLACE TRIGGER catalog_sealed_row BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION catalog._fence_row()',name);
   EXECUTE format('CREATE OR REPLACE TRIGGER catalog_sealed_insert AFTER INSERT ON ontology.%I REFERENCING NEW TABLE AS catalog_inserted FOR EACH STATEMENT EXECUTE FUNCTION catalog._fence_graph_insert()',name);
   EXECUTE format('CREATE OR REPLACE TRIGGER catalog_sealed_truncate BEFORE TRUNCATE ON ontology.%I FOR EACH STATEMENT EXECUTE FUNCTION catalog._fence_truncate()',name);
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.seal_catalog_source_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE sealed_manifest jsonb;
BEGIN
  PERFORM retention.gate();
  PERFORM pg_advisory_xact_lock(71243,19002);
  PERFORM catalog._lock_release(id);
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM 1 FROM ontology.corpus_release WHERE release_id=id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_ONTOLOGY_RELEASE'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND state IN ('REVOKED','FAILED'))
 THEN RAISE EXCEPTION 'RELEASE_NOT_LOADABLE'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest IS NOT NULL) THEN
  IF NOT EXISTS(SELECT 1 FROM catalog.integrity_attestation a JOIN ontology.corpus_release r USING(release_id)
   WHERE r.release_id=id AND a.manifest_hash=r.manifest_hash) THEN
   PERFORM ontology.verify_catalog_source_v1(id);
   IF (SELECT manifest FROM ontology.corpus_release WHERE release_id=id) IS DISTINCT FROM ontology.graph_inventory_manifest(id)
   THEN RAISE EXCEPTION 'SEALED_GRAPH_INVENTORY_CHANGED'; END IF;
  END IF;
  RETURN;
 END IF;
 PERFORM ontology.require_preparing(id);
 PERFORM ontology.verify_catalog_source_v1(id);
 CREATE TEMP TABLE catalog_node_candidate ON COMMIT DROP AS SELECT * FROM ontology.catalog_source_nodes_v1(id);
 IF EXISTS(SELECT 1 FROM catalog_node_candidate GROUP BY node_id HAVING count(*)>1)
 THEN RAISE EXCEPTION 'CONFLICTING_GRAPH_NODE_CONTENT'; END IF;
 IF EXISTS(SELECT 1 FROM catalog_node_candidate WHERE properties ?| ARRAY['id','content_hash'])
 THEN RAISE EXCEPTION 'GRAPH_RESERVED_NODE_PROPERTY'; END IF;
 INSERT INTO ontology.graph_node SELECT id,node_id,labels,properties,
  ontology.hash(jsonb_build_array(node_id,labels,properties)) FROM catalog_node_candidate;
 CREATE TEMP TABLE catalog_edge_candidate ON COMMIT DROP AS SELECT * FROM ontology.catalog_source_edges_v1(id);
 IF EXISTS(SELECT 1 FROM catalog_edge_candidate WHERE properties ?| ARRAY['id','content_hash','release_id'])
 THEN RAISE EXCEPTION 'GRAPH_RESERVED_EDGE_PROPERTY'; END IF;
 IF EXISTS(SELECT 1 FROM catalog_edge_candidate e WHERE
  (e.subject_id<>'release/'||id AND NOT EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id=e.subject_id))
  OR NOT EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id=e.object_id))
 THEN RAISE EXCEPTION 'GRAPH_ENDPOINT_OUTSIDE_RELEASE'; END IF;
 INSERT INTO ontology.graph_edge SELECT id,
  ontology.hash(jsonb_build_array(id,subject_id,predicate,object_id,properties)),
  subject_id,predicate,object_id,properties,
  ontology.hash(jsonb_build_array(subject_id,predicate,object_id,properties)) FROM catalog_edge_candidate;
 PERFORM ontology.verify_graph_numbers(id);
 sealed_manifest:=ontology.graph_inventory_manifest(id);
 UPDATE ontology.corpus_release SET manifest=sealed_manifest,manifest_hash=ontology.hash(sealed_manifest) WHERE release_id=id;
 PERFORM ontology.verify_catalog_source_v1(id);
END $$;

CREATE OR REPLACE FUNCTION catalog._source_inventory(id text) RETURNS text
LANGUAGE sql STABLE AS $$
 SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(x.run_id,x.source_fingerprint) ORDER BY x.run_id),'[]'::jsonb))
 FROM (SELECT run_id,source_fingerprint FROM ontology.release_source_run WHERE release_id=id) x
$$;

CREATE OR REPLACE FUNCTION catalog._membership_inventory(id text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE result jsonb:='{}'::jsonb; entry record; digest text;
BEGIN
 FOR entry IN SELECT table_name FROM (VALUES ('source_pin'),('release_source_run'),('input_record'),
  ('release_revision'),('revision_support'),('release_relation'),('quality_observation'),
  ('observation_freeze'),('observation_history_member'),('posting_observation'),
  ('observation_membership'),('entity_observation_state'),('catalog_source_mode')) names(table_name)
 LOOP
  EXECUTE format('SELECT ontology.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),''[]''::jsonb)) FROM ontology.%I t WHERE release_id=$1',entry.table_name)
   INTO digest USING id;
  result:=result||jsonb_build_object(entry.table_name,digest);
 END LOOP;
 RETURN ontology.hash(result);
END $$;

CREATE OR REPLACE FUNCTION catalog._attest(id text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r ontology.corpus_release%ROWTYPE; manifest jsonb; observation text;
BEGIN
 PERFORM catalog._lock_release(id);
 SELECT * INTO STRICT r FROM ontology.corpus_release WHERE release_id=id;
 IF r.state<>'PREPARING' OR r.manifest_hash IS NULL OR r.graph_verified_at IS NULL
 THEN RAISE EXCEPTION 'CATALOG_RELEASE_NOT_VERIFIED'; END IF;
 PERFORM ontology.check_frozen_sources(id);
 PERFORM ontology.verify_catalog_source_v1(id);
 manifest:=ontology.graph_inventory_manifest(id);
 IF manifest IS DISTINCT FROM r.manifest OR ontology.hash(manifest)<>r.manifest_hash
 THEN RAISE EXCEPTION 'CATALOG_INVENTORY_CHANGED'; END IF;
 SELECT manifest_hash INTO observation FROM ontology.observation_membership WHERE release_id=id;
 IF observation IS NULL THEN RAISE EXCEPTION 'CATALOG_OBSERVATION_MISSING'; END IF;
 INSERT INTO catalog.integrity_attestation(release_id,generation,contract_version,mode,manifest_hash,
  observation_hash,source_inventory_hash,membership_hash,node_count,edge_count,node_hash,edge_hash)
 VALUES(id,1,'hop-catalog-source-v1','SOURCE_ONLY',r.manifest_hash,observation,
  catalog._source_inventory(id),catalog._membership_inventory(id),
  (manifest->>'nodes')::bigint,(manifest->>'edges')::bigint,manifest->>'node_hash',manifest->>'edge_hash')
 ON CONFLICT(release_id) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM catalog.integrity_attestation a WHERE a.release_id=id
  AND a.manifest_hash=r.manifest_hash AND a.observation_hash=observation
  AND a.source_inventory_hash=catalog._source_inventory(id) AND a.membership_hash=catalog._membership_inventory(id))
 THEN RAISE EXCEPTION 'CATALOG_ATTESTATION_CONFLICT'; END IF;
END $$;

CREATE OR REPLACE FUNCTION catalog._approved_release(release_choice text DEFAULT NULL)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE selected catalog.catalog_approval%ROWTYPE; r ontology.corpus_release%ROWTYPE;
 latest ontology.graph_load%ROWTYPE; a catalog.integrity_attestation%ROWTYPE;
BEGIN
 SELECT v.* INTO selected FROM catalog.catalog_active_release p JOIN catalog.catalog_approval v USING(approval_id) WHERE p.singleton;
 IF NOT FOUND OR (nullif(btrim(release_choice),'') IS NOT NULL AND selected.release_id<>release_choice)
 THEN RAISE EXCEPTION 'CATALOG_RELEASE_NOT_APPROVED'; END IF;
 SELECT * INTO r FROM ontology.corpus_release WHERE release_id=selected.release_id;
 IF r.state IN ('REVOKED','FAILED') THEN RAISE EXCEPTION 'CATALOG_RELEASE_UNAVAILABLE'; END IF;
 IF current_setting('transaction_isolation')<>'read committed'
 THEN RAISE EXCEPTION 'CATALOG_REQUIRES_READ_COMMITTED'; END IF;
 SELECT * INTO a FROM catalog.integrity_attestation WHERE release_id=selected.release_id;
 SELECT * INTO latest FROM ontology.graph_load WHERE database_id=selected.database_id
  ORDER BY started_at DESC,load_id DESC LIMIT 1;
 IF r.state<>'PREPARING' OR a.generation IS DISTINCT FROM 1 OR
  a.contract_version IS DISTINCT FROM 'hop-catalog-source-v1' OR a.mode IS DISTINCT FROM 'SOURCE_ONLY' OR
  NOT EXISTS(SELECT 1 FROM ontology.catalog_source_mode m WHERE m.release_id=r.release_id AND m.mode=a.mode
   AND m.contract_version='hop-ontology-graph-source-v1') OR
  a.manifest_hash IS DISTINCT FROM r.manifest_hash OR a.manifest_hash IS DISTINCT FROM selected.manifest_hash OR
  a.observation_hash IS DISTINCT FROM (SELECT manifest_hash FROM ontology.observation_membership WHERE release_id=r.release_id) OR
  a.node_count IS DISTINCT FROM (r.manifest->>'nodes')::bigint OR a.edge_count IS DISTINCT FROM (r.manifest->>'edges')::bigint OR
  a.node_hash IS DISTINCT FROM r.manifest->>'node_hash' OR a.edge_hash IS DISTINCT FROM r.manifest->>'edge_hash' OR
  r.graph_verified_at IS NULL OR latest.load_id IS DISTINCT FROM selected.load_id OR
  latest.release_id IS DISTINCT FROM r.release_id OR latest.state IS DISTINCT FROM 'VERIFIED' OR
  latest.finished_at IS NULL OR latest.manifest_hash IS DISTINCT FROM a.manifest_hash OR
  latest.node_count IS DISTINCT FROM a.node_count OR latest.edge_count IS DISTINCT FROM a.edge_count
 THEN RAISE EXCEPTION 'CATALOG_APPROVAL_STALE'; END IF;
 RETURN r.release_id;
END $$;

CREATE OR REPLACE FUNCTION catalog.approve_catalog_release(release_id text,database_id text,actor text,reason text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r ontology.corpus_release%ROWTYPE; latest ontology.graph_load%ROWTYPE; approved bigint;
BEGIN
 IF nullif(btrim(release_id),'') IS NULL OR nullif(btrim(database_id),'') IS NULL OR
  nullif(btrim(actor),'') IS NULL OR nullif(btrim(reason),'') IS NULL
 THEN RAISE EXCEPTION 'CATALOG_APPROVAL_PROVENANCE_REQUIRED'; END IF;
  PERFORM retention.gate();
  PERFORM pg_advisory_xact_lock(71243,19002);
  PERFORM pg_advisory_xact_lock(71243,19001);
 PERFORM catalog._lock_release(release_id);
 SELECT * INTO r FROM ontology.corpus_release WHERE corpus_release.release_id=approve_catalog_release.release_id;
 IF NOT FOUND OR r.state<>'PREPARING' OR r.manifest IS NULL OR r.graph_verified_at IS NULL
 THEN RAISE EXCEPTION 'CATALOG_RELEASE_NOT_VERIFIED'; END IF;
 SELECT * INTO latest FROM ontology.graph_load WHERE graph_load.database_id=approve_catalog_release.database_id
  ORDER BY started_at DESC,load_id DESC LIMIT 1;
 IF latest.release_id IS DISTINCT FROM r.release_id OR latest.state IS DISTINCT FROM 'VERIFIED' OR
  latest.manifest_hash IS DISTINCT FROM r.manifest_hash OR latest.finished_at IS NULL OR
  latest.node_count IS DISTINCT FROM (r.manifest->>'nodes')::bigint OR
  latest.edge_count IS DISTINCT FROM (r.manifest->>'edges')::bigint
 THEN RAISE EXCEPTION 'CATALOG_GRAPH_LOAD_NOT_VERIFIED'; END IF;
 PERFORM catalog._attest(release_id);
 SELECT v.approval_id INTO approved FROM catalog.catalog_active_release p JOIN catalog.catalog_approval v USING(approval_id)
 WHERE p.singleton AND v.release_id=r.release_id AND v.load_id=latest.load_id;
 IF approved IS NULL THEN
  INSERT INTO catalog.catalog_approval(release_id,database_id,load_id,manifest_hash,actor,reason)
   VALUES(r.release_id,database_id,latest.load_id,r.manifest_hash,actor,reason) RETURNING approval_id INTO approved;
 END IF;
 INSERT INTO catalog.catalog_active_release(singleton,approval_id) VALUES(true,approved)
 ON CONFLICT(singleton) DO UPDATE SET approval_id=excluded.approval_id;
 RETURN approved;
END $$;

CREATE OR REPLACE FUNCTION catalog._context(id text) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('contract_version','hop-catalog-source-v1','release_id',r.release_id,
  'data_as_of',r.data_as_of,'manifest_hash',r.manifest_hash,
  'source_profile',jsonb_build_object('kind','SOURCE_ONLY','analysis_available',false,
   'capabilities',jsonb_build_array('entities','source_relations')))
 FROM ontology.corpus_release r WHERE r.release_id=id
$$;

CREATE OR REPLACE FUNCTION catalog.catalog_context_v1(release_choice text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 RETURN catalog._context(catalog._approved_release(release_choice));
END $$;

DO $$ DECLARE sig text; definition text;
BEGIN
 FOREACH sig IN ARRAY ARRAY[
  'catalog.catalog_entities_v1(text,text,integer,integer)',
  'catalog.catalog_entity_v1(text,text)',
  'catalog.catalog_relations_v1(text,text,integer,integer)',
  'catalog.catalog_summary_v1(text)'] LOOP
  SELECT pg_get_functiondef(sig::regprocedure) INTO definition;
  definition:=replace(definition,'catalog.catalog_context_v1(id)','catalog._context(id)');
  EXECUTE definition;
 END LOOP;
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA catalog FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN
  REVOKE ALL ON FUNCTION catalog._lock_release(text),catalog._fence_row(),catalog._fence_graph_insert(),catalog._fence_truncate(),catalog._serialize_metadata(),catalog._protect_audit_truncate(),
   catalog._source_inventory(text),catalog._membership_inventory(text),catalog._attest(text),catalog._context(text),
    catalog._approved_release(text),catalog._write_boundary(),catalog.approve_catalog_release(text,text,text,text) FROM jobtology_catalog_reader;
 END IF;
END $$;
COMMIT;
