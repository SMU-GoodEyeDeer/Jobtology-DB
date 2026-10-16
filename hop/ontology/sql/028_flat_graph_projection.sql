-- A versioned current Neo4j projection; original release/export inventory stays immutable.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.flat_graph_projection (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 contract_version text NOT NULL CHECK(contract_version='hop-ontology-flat-v1'),
 source_manifest_hash text NOT NULL, manifest_hash text NOT NULL, manifest jsonb NOT NULL,
 node_count bigint NOT NULL,edge_count bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS ontology.flat_graph_revision_binding (
 release_id text NOT NULL REFERENCES ontology.corpus_release,revision_node_id text NOT NULL,
 entity_node_id text NOT NULL,revision_id text NOT NULL,payload_hash text NOT NULL,
 PRIMARY KEY(release_id,revision_node_id),UNIQUE(release_id,entity_node_id)
);
CREATE TABLE IF NOT EXISTS ontology.flat_graph_node (
 release_id text NOT NULL REFERENCES ontology.corpus_release,node_id text NOT NULL,labels text[] NOT NULL,
 properties jsonb NOT NULL,identity_properties jsonb NOT NULL,owned_properties jsonb NOT NULL,
 content_hash text NOT NULL,flat_content_hash text NOT NULL,
 PRIMARY KEY(release_id,node_id)
);
CREATE TABLE IF NOT EXISTS ontology.flat_graph_edge (
 release_id text NOT NULL REFERENCES ontology.corpus_release,edge_id text NOT NULL,origin_edge_id text NOT NULL,
 subject_id text NOT NULL,predicate text NOT NULL,object_id text NOT NULL,properties jsonb NOT NULL,
 content_hash text NOT NULL,original_subject_id text NOT NULL,original_predicate text NOT NULL,
 original_object_id text NOT NULL,original_properties jsonb NOT NULL,original_content_hash text NOT NULL,
 PRIMARY KEY(release_id,edge_id),UNIQUE(release_id,origin_edge_id)
);
CREATE TABLE IF NOT EXISTS ontology.flat_graph_load (
 load_id text PRIMARY KEY,release_id text NOT NULL REFERENCES ontology.flat_graph_projection,
 database_id text NOT NULL,source_manifest_hash text NOT NULL,manifest_hash text NOT NULL,
 state text NOT NULL CHECK(state IN ('RUNNING','STAGED','VERIFIED','FAILED')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),staged_at timestamptz,finished_at timestamptz,
 node_count bigint,edge_count bigint,error text
);
CREATE UNIQUE INDEX IF NOT EXISTS flat_graph_one_writer ON ontology.flat_graph_load(database_id)
 WHERE state IN ('RUNNING','STAGED');
CREATE TABLE IF NOT EXISTS ontology.flat_graph_current (
 database_id text PRIMARY KEY,release_id text NOT NULL REFERENCES ontology.flat_graph_projection,
 load_id text NOT NULL REFERENCES ontology.flat_graph_load
);
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['flat_graph_projection','flat_graph_revision_binding','flat_graph_node','flat_graph_edge'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER flat_graph_immutable BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',tab);
  EXECUTE format('CREATE OR REPLACE TRIGGER flat_graph_immutable_truncate BEFORE TRUNCATE ON ontology.%I FOR EACH STATEMENT EXECUTE FUNCTION ontology.immutable()',tab);
 END LOOP;
 FOREACH tab IN ARRAY ARRAY['flat_graph_projection','flat_graph_revision_binding','flat_graph_node','flat_graph_edge','flat_graph_load','flat_graph_current'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER flat_graph_retention_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON ontology.%I FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',tab);
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION ontology.flat_graph_sealed_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 PERFORM pg_advisory_xact_lock(71243,28001);
 IF EXISTS(SELECT 1 FROM flat_inserted i JOIN ontology.flat_graph_projection p USING(release_id))
 THEN RAISE EXCEPTION 'FLAT_GRAPH_ALREADY_SEALED'; END IF;
 RETURN NULL;
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['flat_graph_revision_binding','flat_graph_node','flat_graph_edge'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER flat_graph_sealed_insert AFTER INSERT ON ontology.%I REFERENCING NEW TABLE AS flat_inserted FOR EACH STATEMENT EXECUTE FUNCTION ontology.flat_graph_sealed_insert_guard()',tab);
 END LOOP;
END $$;

-- Preserve shell identity fields. A differing source code gets a deterministic alias.
CREATE OR REPLACE FUNCTION ontology.flat_graph_owned_properties(base jsonb,revision jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE p record; result jsonb:='{}'; target text;
BEGIN
 FOR p IN SELECT * FROM jsonb_each(revision) LOOP
  IF p.key IN ('entity_id','kind','scheme_id') THEN
   IF base ? p.key AND base->p.key IS DISTINCT FROM p.value THEN RAISE EXCEPTION 'FLAT_IDENTITY_PROPERTY_CONFLICT: %',p.key; END IF;
   CONTINUE;
  END IF;
  target:=CASE p.key WHEN 'code' THEN 'revision_code' WHEN 'revision_id' THEN 'selected_revision_id'
   WHEN 'payload_hash' THEN 'selected_revision_payload_hash' WHEN 'schema_version' THEN 'selected_revision_schema_version' ELSE p.key END;
  IF target LIKE '%|%' OR target IN ('id','content_hash','flat_content_hash','flat_owned_keys') OR base ? target
   OR result ? target THEN RAISE EXCEPTION 'FLAT_PROPERTY_COLLISION: %',target; END IF;
  IF p.value<>'null'::jsonb THEN result:=result||jsonb_build_object(target,p.value); END IF;
 END LOOP;
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION ontology.flat_graph_inventory_manifest(id text) RETURNS jsonb
LANGUAGE sql STABLE SET jit=off AS $$
 SELECT jsonb_build_object('contract','hop-ontology-flat-v1','release_id',id,
  'source_manifest_hash',(SELECT manifest_hash FROM ontology.corpus_release WHERE release_id=id),
  'nodes',(SELECT count(*) FROM ontology.flat_graph_node WHERE release_id=id),
  'node_hash',(SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(node_id,flat_content_hash) ORDER BY node_id),'[]')) FROM ontology.flat_graph_node WHERE release_id=id),
  'edges',(SELECT count(*) FROM ontology.flat_graph_edge WHERE release_id=id),
  'edge_hash',(SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(edge_id,content_hash) ORDER BY edge_id),'[]')) FROM ontology.flat_graph_edge WHERE release_id=id),
  'bindings',(SELECT count(*) FROM ontology.flat_graph_revision_binding WHERE release_id=id),
  'legacy_edges',(SELECT count(*) FROM ontology.graph_edge e WHERE e.release_id=id AND EXISTS(
   SELECT 1 FROM ontology.flat_graph_revision_binding b WHERE b.release_id=id AND b.revision_node_id IN(e.subject_id,e.object_id))),
  'binding_hash',(SELECT ontology.hash(coalesce(jsonb_agg(b ORDER BY revision_node_id),'[]')) FROM ontology.flat_graph_revision_binding b WHERE release_id=id))
$$;
CREATE OR REPLACE FUNCTION ontology.assert_flat_graph_inventory(id text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$ DECLARE p ontology.flat_graph_projection; r ontology.corpus_release; BEGIN
 SELECT * INTO STRICT p FROM ontology.flat_graph_projection WHERE release_id=id;
 SELECT * INTO STRICT r FROM ontology.corpus_release WHERE release_id=id;
 IF r.state IN ('FAILED','REVOKED') OR r.manifest_hash IS DISTINCT FROM p.source_manifest_hash
  OR r.manifest_hash IS DISTINCT FROM ontology.hash(r.manifest)
  OR r.manifest IS DISTINCT FROM ontology.graph_inventory_manifest(id)
  OR p.manifest_hash IS DISTINCT FROM ontology.hash(p.manifest)
  OR p.manifest IS DISTINCT FROM ontology.flat_graph_inventory_manifest(id)
  OR EXISTS(SELECT 1 FROM ontology.flat_graph_node n WHERE release_id=id AND
   n.flat_content_hash<>ontology.hash(jsonb_build_array(n.node_id,n.labels,n.properties)))
  OR EXISTS(SELECT 1 FROM ontology.flat_graph_edge e WHERE release_id=id AND
   e.content_hash<>ontology.hash(jsonb_build_array(e.subject_id,e.predicate,e.object_id,e.properties)))
 THEN RAISE EXCEPTION 'FLAT_GRAPH_INVENTORY_CHANGED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION ontology.seal_flat_graph_projection(id text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$ DECLARE r ontology.corpus_release; m jsonb; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(71243,28001);
 SELECT * INTO STRICT r FROM ontology.corpus_release WHERE release_id=id FOR UPDATE;
 IF r.state IN ('FAILED','REVOKED') OR r.manifest IS NULL OR r.manifest_hash<>ontology.hash(r.manifest)
  OR r.manifest IS DISTINCT FROM ontology.graph_inventory_manifest(id) THEN RAISE EXCEPTION 'FLAT_REQUIRES_SEALED_RELEASE'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.flat_graph_projection WHERE release_id=id) THEN
  PERFORM ontology.assert_flat_graph_inventory(id); RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ontology.flat_graph_node WHERE release_id=id)
  OR EXISTS(SELECT 1 FROM ontology.flat_graph_edge WHERE release_id=id)
  OR EXISTS(SELECT 1 FROM ontology.flat_graph_revision_binding WHERE release_id=id)
 THEN RAISE EXCEPTION 'FLAT_UNSEALED_PROOF_ROWS'; END IF;
 -- This mapping is grounded in both the selected PG revision and sealed graph rows.
 INSERT INTO ontology.flat_graph_revision_binding
 WITH selected AS MATERIALIZED(
  SELECT v.entity_id,v.revision_id,v.payload_hash FROM ontology.release_revision s
  JOIN ontology.revision v USING(revision_id) WHERE s.release_id=id)
 SELECT id,n.node_id,'entity/'||v.entity_id,v.revision_id,v.payload_hash
 FROM selected v
 JOIN ontology.graph_node n ON n.release_id=id AND n.node_id='revision/'||v.revision_id
 JOIN ontology.graph_node e ON e.release_id=id AND e.node_id='entity/'||v.entity_id
 WHERE 'entityRevision'=ANY(n.labels) AND 'ontologyEntity'=ANY(e.labels)
  AND n.properties->>'entity_id'=v.entity_id AND n.properties->>'payload_hash'=v.payload_hash;
 IF (SELECT count(*) FROM ontology.flat_graph_revision_binding WHERE release_id=id)<>
  (SELECT count(*) FROM ontology.release_revision WHERE release_id=id)
  OR EXISTS(SELECT 1 FROM ontology.graph_node n WHERE release_id=id
   AND ('entityRevision'=ANY(labels) OR EXISTS(SELECT 1 FROM unnest(labels) x WHERE x LIKE '%Revision'))
   AND NOT EXISTS(SELECT 1 FROM ontology.flat_graph_revision_binding b WHERE b.release_id=id AND b.revision_node_id=n.node_id))
 THEN RAISE EXCEPTION 'FLAT_REVISION_BINDING_INCOMPLETE'; END IF;
 IF (WITH memberships AS MATERIALIZED(
  SELECT object_id FROM ontology.graph_edge WHERE release_id=id
   AND subject_id='release/'||id AND predicate='INCLUDES'),
  mapped AS MATERIALIZED(
   SELECT e.predicate,e.subject_id,b.revision_id,b.entity_node_id
   FROM ontology.graph_edge e LEFT JOIN ontology.flat_graph_revision_binding b
   ON b.release_id=id AND b.revision_node_id=e.object_id
   WHERE e.release_id=id AND e.predicate IN('HAS_REVISION','INCLUDES'))
  SELECT coalesce(bool_or(
   (e.predicate='HAS_REVISION' AND (e.revision_id IS NULL OR e.subject_id<>e.entity_node_id))
   OR (e.predicate='INCLUDES' AND e.revision_id IS NOT NULL
    AND (e.subject_id<>'release/'||id OR k.object_id IS NULL))),false)
  FROM mapped e LEFT JOIN memberships k ON k.object_id=e.entity_node_id)
 THEN RAISE EXCEPTION 'FLAT_STRUCTURAL_EDGE_NOT_ACCOUNTED'; END IF;
 INSERT INTO ontology.flat_graph_node
 SELECT id,n.node_id,n.labels,n.properties||coalesce(o.owned,'{}'),n.properties,coalesce(o.owned,'{}'),
  n.content_hash,ontology.hash(jsonb_build_array(n.node_id,n.labels,n.properties||coalesce(o.owned,'{}')))
 FROM ontology.graph_node n LEFT JOIN ontology.flat_graph_revision_binding b ON b.release_id=id AND b.entity_node_id=n.node_id
 LEFT JOIN ontology.graph_node v ON v.release_id=id AND v.node_id=b.revision_node_id
 LEFT JOIN LATERAL (SELECT ontology.flat_graph_owned_properties(n.properties,v.properties) AS owned WHERE b.revision_id IS NOT NULL) o ON true
 WHERE n.release_id=id AND NOT EXISTS(SELECT 1 FROM ontology.flat_graph_revision_binding x WHERE x.release_id=id AND x.revision_node_id=n.node_id);
 IF EXISTS(SELECT 1 FROM ontology.graph_edge e WHERE e.release_id=id
  AND e.properties ?| ARRAY['origin_edge_id','original_subject_id','original_object_id','subject_revision_id','object_revision_id']
  AND EXISTS(SELECT 1 FROM ontology.flat_graph_revision_binding b WHERE b.release_id=id
   AND b.revision_node_id IN(e.subject_id,e.object_id)))
 THEN RAISE EXCEPTION 'FLAT_EDGE_PROVENANCE_COLLISION'; END IF;
 INSERT INTO ontology.flat_graph_edge
 WITH bindings AS MATERIALIZED(SELECT * FROM ontology.flat_graph_revision_binding WHERE release_id=id),
 mapped AS MATERIALIZED(
  SELECT e.*,coalesce(a.entity_node_id,e.subject_id) AS new_subject,coalesce(b.entity_node_id,e.object_id) AS new_object,
   CASE WHEN e.predicate='SELECTS_REVISION' THEN 'SELECTS_ENTITY' ELSE e.predicate END AS new_predicate,
   e.properties||CASE WHEN a.revision_id IS NOT NULL OR b.revision_id IS NOT NULL THEN
    jsonb_strip_nulls(jsonb_build_object('origin_edge_id',e.edge_id,'original_subject_id',e.subject_id,
     'original_object_id',e.object_id,'subject_revision_id',a.revision_id,'object_revision_id',b.revision_id)) ELSE '{}'::jsonb END AS new_properties,
   a.revision_id AS from_revision,b.revision_id AS to_revision
  FROM ontology.graph_edge e LEFT JOIN bindings a ON a.revision_node_id=e.subject_id
  LEFT JOIN bindings b ON b.revision_node_id=e.object_id
  WHERE e.release_id=id AND e.predicate<>'HAS_REVISION'
   AND NOT(e.predicate='INCLUDES' AND b.revision_id IS NOT NULL))
 SELECT id,CASE WHEN from_revision IS NULL AND to_revision IS NULL THEN edge_id ELSE
  ontology.hash(jsonb_build_array('hop-ontology-flat-v1',edge_id,new_subject,new_predicate,new_object,new_properties)) END,
  edge_id,new_subject,new_predicate,new_object,new_properties,
  ontology.hash(jsonb_build_array(new_subject,new_predicate,new_object,new_properties)),
  subject_id,predicate,object_id,properties,content_hash FROM mapped;
 IF EXISTS(SELECT 1 FROM ontology.flat_graph_edge e WHERE release_id=id AND
  (e.subject_id<>'release/'||id AND NOT EXISTS(SELECT 1 FROM ontology.flat_graph_node n WHERE n.release_id=id AND n.node_id=e.subject_id))
  OR (e.release_id=id AND NOT EXISTS(SELECT 1 FROM ontology.flat_graph_node n WHERE n.release_id=id AND n.node_id=e.object_id)))
 THEN RAISE EXCEPTION 'FLAT_ENDPOINT_MISSING'; END IF;
 m:=ontology.flat_graph_inventory_manifest(id);
 INSERT INTO ontology.flat_graph_projection VALUES(id,'hop-ontology-flat-v1',r.manifest_hash,ontology.hash(m),m,
  (m->>'nodes')::bigint,(m->>'edges')::bigint,clock_timestamp());
 PERFORM ontology.assert_flat_graph_inventory(id);
END $$;

CREATE OR REPLACE VIEW ontology.flat_graph_legacy_node AS
 SELECT n.* FROM ontology.graph_node n JOIN ontology.flat_graph_revision_binding b
 ON b.release_id=n.release_id AND b.revision_node_id=n.node_id;
CREATE OR REPLACE VIEW ontology.flat_graph_legacy_edge AS
 SELECT e.* FROM ontology.graph_edge e WHERE EXISTS(SELECT 1 FROM ontology.flat_graph_revision_binding b
 WHERE b.release_id=e.release_id AND b.revision_node_id IN(e.subject_id,e.object_id));
CREATE OR REPLACE VIEW ontology.flat_graph_edge_disposition AS
 SELECT e.release_id,e.edge_id AS origin_edge_id,f.edge_id AS flat_edge_id,
 CASE WHEN f.edge_id=e.edge_id THEN 'UNCHANGED' WHEN f.edge_id IS NOT NULL THEN 'REROUTED'
 WHEN e.predicate='HAS_REVISION' THEN 'DROPPED_HAS_REVISION' ELSE 'DROPPED_REVISION_MEMBERSHIP' END AS disposition
 FROM ontology.graph_edge e JOIN ontology.flat_graph_projection p USING(release_id)
 LEFT JOIN ontology.flat_graph_edge f ON f.release_id=e.release_id AND f.origin_edge_id=e.edge_id;
-- Match the existing native primitive rendering, including legacy JSON-null shells.
CREATE OR REPLACE VIEW ontology.flat_graph_property AS
WITH objects AS (
 SELECT release_id,'NODE'::text AS owner_type,node_id AS owner_id,content_hash,flat_content_hash,properties FROM ontology.flat_graph_node
 UNION ALL SELECT release_id,'EDGE',edge_id,content_hash,content_hash,properties FROM ontology.flat_graph_edge
), expanded AS (
 SELECT o.*,p.key,jsonb_typeof(p.value)='array' AS is_array,coalesce(a.ordinality-1,-1)::integer AS ordinal,
 CASE WHEN jsonb_typeof(p.value)='array' THEN a.value ELSE p.value END AS value,
 CASE WHEN jsonb_typeof(p.value)='array' THEN jsonb_array_length(p.value) ELSE -1 END AS array_size,
 CASE WHEN jsonb_typeof(p.value)='array' THEN EXISTS(SELECT 1 FROM jsonb_array_elements(p.value) x
 WHERE CASE WHEN jsonb_typeof(x)='number' THEN (x#>>'{}')::numeric<>trunc((x#>>'{}')::numeric) ELSE false END) ELSE false END AS float_array
 FROM objects o CROSS JOIN LATERAL jsonb_each(o.properties) p
 LEFT JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(p.value)='array' THEN p.value ELSE '[]' END) WITH ORDINALITY a ON true
)
SELECT release_id,owner_type,owner_id,content_hash,flat_content_hash,key,is_array,ordinal,value,array_size,value#>>'{}' AS text_value,
 CASE WHEN value IS NULL THEN 'empty_array' WHEN jsonb_typeof(value)='number' THEN
 CASE WHEN NOT float_array AND (value#>>'{}')::numeric=trunc((value#>>'{}')::numeric) THEN 'integer' ELSE 'number' END
 WHEN jsonb_typeof(value)='string' AND (key IN('date_posted','closing_date','established_date','earliest_start') OR key LIKE 'dates.%')
 AND (value#>>'{}')~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN 'date'
 WHEN jsonb_typeof(value)='string' AND key~'(^|[.])(created_at|reviewed_at|first_seen_at|last_seen_at|evaluated_at)$'
 AND (value#>>'{}')~'^[0-9]{4}-[0-9]{2}-[0-9]{2}T' THEN 'datetime' ELSE jsonb_typeof(value) END AS value_type FROM expanded;
CREATE OR REPLACE VIEW ontology.flat_graph_legacy_property AS
 SELECT p.* FROM ontology.graph_property p WHERE
 (p.owner_type='NODE' AND EXISTS(SELECT 1 FROM ontology.flat_graph_legacy_node n WHERE n.release_id=p.release_id AND n.node_id=p.owner_id))
 OR (p.owner_type='EDGE' AND EXISTS(SELECT 1 FROM ontology.flat_graph_legacy_edge e WHERE e.release_id=p.release_id AND e.edge_id=p.owner_id));

CREATE OR REPLACE FUNCTION ontology.begin_flat_graph_load(id text,database text,token text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$ DECLARE old ontology.flat_graph_current; approved text; p ontology.flat_graph_projection; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(71243,28001);
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF nullif(btrim(database),'') IS NULL OR nullif(btrim(token),'') IS NULL THEN RAISE EXCEPTION 'FLAT_LOAD_IDENTITY_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.catalog_source_mode WHERE release_id=id) THEN
  PERFORM ontology.seal_catalog_source_v1(id);
 ELSE
  PERFORM ontology.seal_graph(id);
 END IF;
 PERFORM ontology.seal_flat_graph_projection(id);
 SELECT * INTO old FROM ontology.flat_graph_current WHERE database_id=database FOR UPDATE;
 IF FOUND THEN
  IF old.release_id<>id AND (SELECT created_at FROM ontology.corpus_release WHERE release_id=id)<=
   (SELECT created_at FROM ontology.corpus_release WHERE release_id=old.release_id)
  THEN RAISE EXCEPTION 'FLAT_STALE_RELEASE_REPLAY'; END IF;
 ELSE
  SELECT a.release_id INTO approved FROM catalog.catalog_active_release c JOIN catalog.catalog_approval a USING(approval_id)
  WHERE c.singleton AND a.database_id=database;
  IF approved IS NOT NULL AND approved<>id THEN RAISE EXCEPTION 'FLAT_INITIAL_REQUIRES_APPROVED_CATALOG'; END IF;
 END IF;
 SELECT * INTO STRICT p FROM ontology.flat_graph_projection WHERE release_id=id;
 INSERT INTO ontology.flat_graph_load(load_id,release_id,database_id,source_manifest_hash,manifest_hash,state)
 VALUES(token,id,database,p.source_manifest_hash,p.manifest_hash,'RUNNING');
 INSERT INTO ontology.flat_graph_current VALUES(database,id,token)
 ON CONFLICT(database_id) DO UPDATE SET release_id=excluded.release_id,load_id=excluded.load_id;
 PERFORM retention.enter_writer(token,'ONTOLOGY_GRAPH',id);
END $$;
CREATE OR REPLACE FUNCTION ontology.resume_flat_graph_load(token text) RETURNS text
LANGUAGE plpgsql SET jit=off AS $$ DECLARE l ontology.flat_graph_load; BEGIN
 SELECT * INTO STRICT l FROM ontology.flat_graph_load WHERE load_id=token AND state='STAGED';
 IF NOT EXISTS(SELECT 1 FROM ontology.flat_graph_current c WHERE c.database_id=l.database_id
  AND c.release_id=l.release_id AND c.load_id=token) THEN RAISE EXCEPTION 'FLAT_STAGED_TOKEN_NOT_CURRENT'; END IF;
 PERFORM ontology.assert_flat_graph_inventory(l.release_id); RETURN token;
END $$;
CREATE OR REPLACE FUNCTION ontology.stage_flat_graph_load(token text,nodes bigint,edges bigint,verified boolean) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$ DECLARE l ontology.flat_graph_load; p ontology.flat_graph_projection; BEGIN
 PERFORM retention.gate(); SELECT * INTO STRICT l FROM ontology.flat_graph_load WHERE load_id=token FOR UPDATE;
 SELECT * INTO STRICT p FROM ontology.flat_graph_projection WHERE release_id=l.release_id;
 PERFORM ontology.assert_flat_graph_inventory(l.release_id);
 IF l.state<>'RUNNING' OR verified IS DISTINCT FROM true OR nodes IS DISTINCT FROM p.node_count OR edges IS DISTINCT FROM p.edge_count
  OR l.manifest_hash<>p.manifest_hash OR NOT EXISTS(SELECT 1 FROM ontology.flat_graph_current c
   WHERE c.database_id=l.database_id AND c.release_id=l.release_id AND c.load_id=token)
 THEN RAISE EXCEPTION 'FLAT_STAGE_VERIFICATION_FAILED'; END IF;
 UPDATE ontology.flat_graph_load SET state='STAGED',staged_at=clock_timestamp(),node_count=nodes,edge_count=edges WHERE load_id=token;
END $$;
CREATE OR REPLACE FUNCTION ontology.finish_flat_graph_load(token text,nodes bigint,edges bigint,verified boolean) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$ DECLARE l ontology.flat_graph_load; p ontology.flat_graph_projection; BEGIN
 PERFORM retention.gate(); SELECT * INTO STRICT l FROM ontology.flat_graph_load WHERE load_id=token FOR UPDATE;
 SELECT * INTO STRICT p FROM ontology.flat_graph_projection WHERE release_id=l.release_id;
 PERFORM ontology.assert_flat_graph_inventory(l.release_id);
 IF l.state NOT IN('RUNNING','STAGED') OR verified IS DISTINCT FROM true OR nodes IS DISTINCT FROM p.node_count OR edges IS DISTINCT FROM p.edge_count
  OR l.manifest_hash<>p.manifest_hash OR NOT EXISTS(SELECT 1 FROM ontology.flat_graph_current c
   WHERE c.database_id=l.database_id AND c.release_id=l.release_id AND c.load_id=token)
 THEN RAISE EXCEPTION 'FLAT_LOAD_VERIFICATION_FAILED'; END IF;
 UPDATE ontology.flat_graph_load SET state='VERIFIED',finished_at=clock_timestamp(),node_count=nodes,edge_count=edges WHERE load_id=token;
 PERFORM retention.leave_writer(token);
END $$;
CREATE OR REPLACE FUNCTION ontology.fail_flat_graph_load(token text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$ BEGIN
 PERFORM retention.gate();
 UPDATE ontology.flat_graph_load SET state='FAILED',finished_at=clock_timestamp(),error='Native flat projection failed; inspect protected log.'
 WHERE load_id=token AND state IN('RUNNING','STAGED');
 IF FOUND THEN PERFORM retention.leave_writer(token); END IF;
END $$;
CREATE OR REPLACE FUNCTION ontology.require_flat_graph_projection(id text,database text) RETURNS void
LANGUAGE plpgsql STABLE SET jit=off AS $$ DECLARE l ontology.flat_graph_load; p ontology.flat_graph_projection; BEGIN
 SELECT f.* INTO l FROM ontology.flat_graph_current c JOIN ontology.flat_graph_load f USING(load_id)
 WHERE c.database_id=database AND c.release_id=id AND f.release_id=id AND f.database_id=database;
 SELECT * INTO p FROM ontology.flat_graph_projection WHERE release_id=id;
 IF l.state IS DISTINCT FROM 'VERIFIED' OR l.finished_at IS NULL OR l.manifest_hash IS DISTINCT FROM p.manifest_hash
  OR l.source_manifest_hash IS DISTINCT FROM p.source_manifest_hash OR l.node_count IS DISTINCT FROM p.node_count
  OR l.edge_count IS DISTINCT FROM p.edge_count OR p.contract_version IS DISTINCT FROM 'hop-ontology-flat-v1'
  OR NOT EXISTS(SELECT 1 FROM ontology.corpus_release r WHERE r.release_id=id
   AND r.state NOT IN('FAILED','REVOKED') AND r.manifest_hash=p.source_manifest_hash)
 THEN RAISE EXCEPTION 'FLAT_GRAPH_PROJECTION_NOT_READY'; END IF;
END $$;
-- Old XML cannot acquire a token for the retired revision-node writer.
CREATE OR REPLACE FUNCTION ontology.begin_graph_load(id text,database text,token text) RETURNS void
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'REVISION_GRAPH_WRITER_RETIRED_USE_FLAT'; END $$;
REVOKE ALL ON ontology.flat_graph_projection,ontology.flat_graph_revision_binding,ontology.flat_graph_node,
 ontology.flat_graph_edge,ontology.flat_graph_load,ontology.flat_graph_current FROM PUBLIC;
DO $$ DECLARE sig text; BEGIN
 FOREACH sig IN ARRAY ARRAY['ontology.flat_graph_sealed_insert_guard()',
 'ontology.flat_graph_owned_properties(jsonb,jsonb)','ontology.flat_graph_inventory_manifest(text)',
 'ontology.assert_flat_graph_inventory(text)','ontology.seal_flat_graph_projection(text)',
 'ontology.begin_flat_graph_load(text,text,text)','ontology.stage_flat_graph_load(text,bigint,bigint,boolean)',
 'ontology.finish_flat_graph_load(text,bigint,bigint,boolean)','ontology.fail_flat_graph_load(text)',
 'ontology.resume_flat_graph_load(text)',
 'ontology.require_flat_graph_projection(text,text)','ontology.begin_graph_load(text,text,text)'] LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',sig);
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN
   EXECUTE format('REVOKE ALL ON FUNCTION %s FROM jobtology_catalog_reader',sig);
  END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN
  REVOKE ALL ON ontology.flat_graph_projection,ontology.flat_graph_revision_binding,ontology.flat_graph_node,
   ontology.flat_graph_edge,ontology.flat_graph_load,ontology.flat_graph_current FROM jobtology_catalog_reader;
 END IF;
END $$;
COMMIT;
