-- Flat O*NET projection and an isolated graph lifecycle; no batch/revision nodes.
BEGIN;
SELECT retention.gate();

CREATE OR REPLACE FUNCTION classification.graph_nodes(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb,content_hash text)
LANGUAGE sql STABLE SET jit=off SET timezone='UTC' AS $$
 WITH r AS MATERIALIZED (SELECT * FROM classification.catalog_release WHERE release_id=id AND state='READY'),
 facts AS (
  SELECT 'urn:jobtology:onet:scheme' AS node_id,ARRAY['entity','onetCatalogObject','conceptScheme'] AS labels,
   jsonb_build_object('id','urn:jobtology:onet:scheme','managed_by','jobtology-onet-catalog-v1',
    'scheme_id','ONET','kind','conceptScheme','code','ONET','name','O*NET',
    'source_version',r.source_version,'taxonomy_version',r.taxonomy_version,
    'release_id',r.release_id,'current',true,'term_kind','SCHEME',
    'source_uri',(SELECT source_uri FROM classification.source_file WHERE release_id=id ORDER BY file_id LIMIT 1)) AS props,
   (r.normalized_input-ARRAY['terms','hierarchy'])||jsonb_build_object('manifest_hash',r.manifest_hash) AS source_facts
  FROM r
  UNION ALL
  SELECT t.term_id,ARRAY['entity','onetCatalogObject',CASE WHEN t.term_kind='GROUP' THEN 'occupationGroup' ELSE 'occupation' END],
   jsonb_strip_nulls(jsonb_build_object('id',t.term_id,'managed_by','jobtology-onet-catalog-v1','scheme_id','ONET',
    'kind',CASE WHEN t.term_kind='GROUP' THEN 'occupationGroup' ELSE 'occupation' END,
    'code',t.code,'name',t.preferred_label,'description',t.description,'source_version',r.source_version,
    'taxonomy_version',r.taxonomy_version,'release_id',r.release_id,'current',true,'term_kind',t.term_kind,
    'source_uri',t.source_uri,'language',t.source_attributes->>'language',
    'hierarchy_level',t.source_attributes->'hierarchy_level')),
   jsonb_build_object('term',to_jsonb(t)-'release_id','source_file',to_jsonb(f)-'release_id')
  FROM r JOIN classification.term t USING(release_id) JOIN classification.source_file f USING(release_id,file_id)
 ), projected AS (
  SELECT node_id,labels,classification.with_content_hash(props||jsonb_build_object(
   'source_facts_json',source_facts::text,'source_facts_sha256',classification.hash(source_facts))) AS properties FROM facts
 ) SELECT node_id,labels,properties,properties->>'content_hash' FROM projected ORDER BY node_id
$$;
CREATE OR REPLACE FUNCTION classification.graph_edges(id text)
RETURNS TABLE(edge_id text,start_id text,end_id text,edge_type text,properties jsonb,content_hash text)
LANGUAGE sql STABLE SET jit=off SET timezone='UTC' AS $$
 WITH r AS MATERIALIZED (SELECT * FROM classification.catalog_release WHERE release_id=id AND state='READY'),
 facts AS (
  SELECT t.term_id AS start_id,'urn:jobtology:onet:scheme' AS end_id,'IN_SCHEME' AS edge_type,
   jsonb_build_object('term_id',t.term_id,'file_id',t.file_id,'source_locator',t.source_locator,
    'source_file_sha256',f.sha256) AS source_facts
  FROM r JOIN classification.term t USING(release_id) JOIN classification.source_file f USING(release_id,file_id)
  UNION ALL
  SELECT h.child_id,h.parent_id,'BROADER',
   jsonb_build_object('hierarchy',to_jsonb(h)-'release_id','source_file',to_jsonb(f)-'release_id')
  FROM r JOIN classification.hierarchy h USING(release_id) JOIN classification.source_file f USING(release_id,file_id)
 ), identified AS (
  SELECT 'urn:jobtology:onet:relationship:'||classification.hash(jsonb_build_array(edge_type,start_id,end_id)) AS edge_id,
   start_id,end_id,edge_type,source_facts FROM facts
 ), projected AS (
  SELECT e.edge_id,e.start_id,e.end_id,e.edge_type,classification.with_content_hash(jsonb_build_object(
   'id',e.edge_id,'managed_by','jobtology-onet-catalog-v1','scheme_id','ONET','release_id',r.release_id,
   'source_version',r.source_version,'taxonomy_version',r.taxonomy_version,'current',true,
   'source_facts_json',e.source_facts::text,'source_facts_sha256',classification.hash(e.source_facts))) AS properties
  FROM identified e CROSS JOIN r
 ) SELECT edge_id,start_id,end_id,edge_type,properties,properties->>'content_hash' FROM projected ORDER BY edge_id
$$;

CREATE OR REPLACE FUNCTION classification.assert_graph_plan(token text) RETURNS void
LANGUAGE plpgsql STABLE SET jit=off AS $$
DECLARE l classification.graph_load;
BEGIN
 SELECT * INTO STRICT l FROM classification.graph_load WHERE load_id=token;
 PERFORM classification.assert_catalog(l.release_id);
 IF l.manifest_hash IS DISTINCT FROM (SELECT manifest_hash FROM classification.catalog_release WHERE release_id=l.release_id)
  OR (SELECT count(*) FROM classification.graph_load_node WHERE load_id=token)<>l.expected_nodes
  OR (SELECT count(*) FROM classification.graph_load_edge WHERE load_id=token)<>l.expected_edges
  OR (SELECT count(*) FROM classification.graph_load_node WHERE load_id=token AND properties->'current'='true'::jsonb)<>l.current_nodes
  OR (SELECT count(*) FROM classification.graph_load_edge WHERE load_id=token AND properties->'current'='true'::jsonb)<>l.current_edges
  OR EXISTS(SELECT 1 FROM classification.graph_load_node n WHERE n.load_id=token AND
    (n.node_id<>n.properties->>'id' OR n.content_hash IS DISTINCT FROM classification.hash(n.properties-'content_hash')
     OR n.properties->>'content_hash' IS DISTINCT FROM n.content_hash
     OR n.properties->>'managed_by' IS DISTINCT FROM 'jobtology-onet-catalog-v1'
     OR n.properties->>'scheme_id' IS DISTINCT FROM 'ONET'))
  OR EXISTS(SELECT 1 FROM classification.graph_load_edge e WHERE e.load_id=token AND
    (e.edge_id<>e.properties->>'id' OR e.content_hash IS DISTINCT FROM classification.hash(e.properties-'content_hash')
     OR e.properties->>'content_hash' IS DISTINCT FROM e.content_hash
     OR e.properties->>'managed_by' IS DISTINCT FROM 'jobtology-onet-catalog-v1'
     OR e.properties->>'scheme_id' IS DISTINCT FROM 'ONET'))
 THEN RAISE EXCEPTION 'ONET_GRAPH_PLAN_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM classification.graph_load_node n
   CROSS JOIN LATERAL jsonb_each(n.properties) p WHERE n.load_id=token AND jsonb_typeof(p.value) NOT IN('string','number','boolean')) OR
  EXISTS(SELECT 1 FROM classification.graph_load_edge e
   CROSS JOIN LATERAL jsonb_each(e.properties) p WHERE e.load_id=token AND jsonb_typeof(p.value) NOT IN('string','number','boolean'))
 THEN RAISE EXCEPTION 'ONET_GRAPH_PROPERTY_NOT_SCALAR'; END IF;
END $$;

CREATE OR REPLACE FUNCTION classification.begin_graph_load(id text,database text,token text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
DECLARE old classification.graph_target; r classification.catalog_release; active classification.catalog_current;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT r FROM classification.catalog_release WHERE release_id=id AND state='READY';
 PERFORM classification.assert_catalog(id);
 IF length(btrim(coalesce(database,''))) NOT BETWEEN 1 AND 200 OR
   length(btrim(coalesce(token,''))) NOT BETWEEN 1 AND 200
 THEN RAISE EXCEPTION 'ONET_GRAPH_IDENTITY_REQUIRED'; END IF;
 SELECT * INTO old FROM classification.graph_target WHERE database_id=database FOR UPDATE;
 SELECT * INTO active FROM classification.catalog_current WHERE scheme_id='ONET';
 IF old.release_id IS NOT NULL AND old.release_id<>id AND
    r.imported_at<=(SELECT imported_at FROM classification.catalog_release WHERE release_id=old.release_id)
 THEN RAISE EXCEPTION 'ONET_STALE_RELEASE_REPLAY'; END IF;
 IF active.release_id IS NOT NULL AND active.database_id<>database THEN
  RAISE EXCEPTION 'ONET_CURRENT_DATABASE_MISMATCH'; END IF;
 INSERT INTO classification.graph_load(load_id,release_id,database_id,previous_load_id,manifest_hash,state)
 VALUES(token,id,database,old.load_id,r.manifest_hash,'RUNNING');
 PERFORM retention.enter_writer(token,'ONET_CATALOG_GRAPH',id);
 INSERT INTO classification.graph_load_node
 SELECT token,n.node_id,n.labels,n.properties,n.content_hash,p.labels,p.properties,p.content_hash
 FROM classification.graph_nodes(id) n LEFT JOIN classification.graph_load_node p
  ON p.load_id=old.load_id AND p.node_id=n.node_id;
 INSERT INTO classification.graph_load_node
 SELECT token,p.node_id,p.labels,v.properties,v.properties->>'content_hash',p.labels,p.properties,p.content_hash
 FROM classification.graph_load_node p CROSS JOIN LATERAL
  (SELECT classification.with_content_hash(p.properties||jsonb_build_object('current',false)) AS properties) v
 WHERE p.load_id=old.load_id AND NOT EXISTS(SELECT 1 FROM classification.graph_load_node n
  WHERE n.load_id=token AND n.node_id=p.node_id);
 INSERT INTO classification.graph_load_edge
 SELECT token,e.edge_id,e.start_id,e.end_id,e.edge_type,e.properties,e.content_hash,p.properties,p.content_hash
 FROM classification.graph_edges(id) e LEFT JOIN classification.graph_load_edge p
  ON p.load_id=old.load_id AND p.edge_id=e.edge_id;
 INSERT INTO classification.graph_load_edge
 SELECT token,p.edge_id,p.start_id,p.end_id,p.edge_type,v.properties,v.properties->>'content_hash',p.properties,p.content_hash
 FROM classification.graph_load_edge p CROSS JOIN LATERAL
  (SELECT classification.with_content_hash(p.properties||jsonb_build_object('current',false)) AS properties) v
 WHERE p.load_id=old.load_id AND NOT EXISTS(SELECT 1 FROM classification.graph_load_edge e
  WHERE e.load_id=token AND e.edge_id=p.edge_id);
 UPDATE classification.graph_load SET
  expected_nodes=(SELECT count(*) FROM classification.graph_load_node WHERE load_id=token),
  expected_edges=(SELECT count(*) FROM classification.graph_load_edge WHERE load_id=token),
  current_nodes=(SELECT count(*) FROM classification.graph_load_node WHERE load_id=token AND properties->'current'='true'::jsonb),
  current_edges=(SELECT count(*) FROM classification.graph_load_edge WHERE load_id=token AND properties->'current'='true'::jsonb)
 WHERE load_id=token;
 PERFORM classification.assert_graph_plan(token);
END $$;

CREATE OR REPLACE FUNCTION classification.assert_readable_graph_load(token text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM classification.graph_load WHERE load_id=token AND state IN('RUNNING','VERIFIED'))
 THEN RAISE EXCEPTION 'ONET_GRAPH_LOAD_NOT_READABLE'; END IF;
 RETURN token;
END $$;
CREATE OR REPLACE FUNCTION classification.graph_load_context(token text)
RETURNS TABLE(load_id text,release_id text,database_id text,previous_release_id text,manifest_hash text,
 expected_nodes bigint,expected_edges bigint,current_nodes bigint,current_edges bigint)
LANGUAGE plpgsql STABLE AS $$
BEGIN
 PERFORM classification.assert_readable_graph_load(token);
 RETURN QUERY
 SELECT l.load_id,l.release_id,l.database_id,p.release_id,l.manifest_hash,l.expected_nodes,l.expected_edges,l.current_nodes,l.current_edges
 FROM classification.graph_load l LEFT JOIN classification.graph_load p ON p.load_id=l.previous_load_id
 WHERE l.load_id=token AND l.state IN('RUNNING','VERIFIED')
 ;
END
$$;
CREATE OR REPLACE FUNCTION classification.graph_load_nodes(token text)
RETURNS TABLE(node_id text,labels text[],properties jsonb,content_hash text,previous_labels text[],
 previous_properties jsonb,previous_content_hash text)
LANGUAGE plpgsql STABLE AS $$
BEGIN
 PERFORM classification.assert_readable_graph_load(token);
 RETURN QUERY
 SELECT n.node_id,n.labels,n.properties,n.content_hash,n.previous_labels,n.previous_properties,n.previous_content_hash
 FROM classification.graph_load_node n JOIN classification.graph_load l USING(load_id)
 WHERE n.load_id=token AND l.state IN('RUNNING','VERIFIED') ORDER BY n.node_id
 ;
END
$$;
CREATE OR REPLACE FUNCTION classification.graph_load_edges(token text)
RETURNS TABLE(edge_id text,start_id text,end_id text,edge_type text,properties jsonb,content_hash text,
 previous_properties jsonb,previous_content_hash text)
LANGUAGE plpgsql STABLE AS $$
BEGIN
 PERFORM classification.assert_readable_graph_load(token);
 RETURN QUERY
 SELECT e.edge_id,e.start_id,e.end_id,e.edge_type,e.properties,e.content_hash,e.previous_properties,e.previous_content_hash
 FROM classification.graph_load_edge e JOIN classification.graph_load l USING(load_id)
 WHERE e.load_id=token AND l.state IN('RUNNING','VERIFIED') ORDER BY e.edge_id
 ;
END
$$;

CREATE OR REPLACE FUNCTION classification.assert_running_graph_load(token text) RETURNS text
LANGUAGE plpgsql STABLE SET jit=off AS $$
DECLARE l classification.graph_load;
BEGIN
 SELECT * INTO l FROM classification.graph_load WHERE load_id=token;
 IF l.state IS DISTINCT FROM 'RUNNING' OR NOT EXISTS(SELECT 1 FROM retention.writer
   WHERE writer_id=token AND kind='ONET_CATALOG_GRAPH' AND target_id=l.release_id)
 THEN RAISE EXCEPTION 'ONET_GRAPH_LOAD_NOT_RUNNING'; END IF;
 PERFORM classification.assert_graph_plan(token);
 RETURN token;
END $$;
CREATE OR REPLACE FUNCTION classification.assert_verified_graph_load(token text) RETURNS text
LANGUAGE plpgsql STABLE SET jit=off AS $$
DECLARE l classification.graph_load;
BEGIN
 SELECT * INTO l FROM classification.graph_load WHERE load_id=token;
 IF l.state IS DISTINCT FROM 'VERIFIED' OR NOT EXISTS(SELECT 1 FROM classification.graph_target
   WHERE database_id=l.database_id AND release_id=l.release_id AND load_id=token)
 THEN RAISE EXCEPTION 'ONET_VERIFIED_CURRENT_GRAPH_REQUIRED'; END IF;
 PERFORM classification.assert_graph_plan(token);
 RETURN token;
END $$;

CREATE OR REPLACE FUNCTION classification.finish_graph_load(token text,nodes bigint,edges bigint,verified boolean) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
DECLARE l classification.graph_load; previous text;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT l FROM classification.graph_load WHERE load_id=token FOR UPDATE;
 PERFORM classification.assert_graph_plan(token);
 SELECT load_id INTO previous FROM classification.graph_target WHERE database_id=l.database_id;
 IF l.state<>'RUNNING' OR verified IS DISTINCT FROM true OR nodes IS DISTINCT FROM l.expected_nodes OR
   edges IS DISTINCT FROM l.expected_edges OR previous IS DISTINCT FROM l.previous_load_id OR
   NOT EXISTS(SELECT 1 FROM retention.writer WHERE writer_id=token AND kind='ONET_CATALOG_GRAPH' AND target_id=l.release_id)
 THEN RAISE EXCEPTION 'ONET_GRAPH_VERIFICATION_FAILED'; END IF;
 UPDATE classification.graph_load SET state='VERIFIED',finished_at=clock_timestamp(),node_count=nodes,edge_count=edges
 WHERE load_id=token;
 INSERT INTO classification.graph_target(database_id,release_id,load_id) VALUES(l.database_id,l.release_id,token)
 ON CONFLICT(database_id) DO UPDATE SET release_id=excluded.release_id,load_id=excluded.load_id;
 PERFORM retention.leave_writer(token);
END $$;
CREATE OR REPLACE FUNCTION classification.fail_graph_load(token text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 UPDATE classification.graph_load SET state='FAILED',finished_at=clock_timestamp(),
  error='Native O*NET catalogue load failed; retain evidence and retry the same release before rollover.'
 WHERE load_id=token AND state='RUNNING';
 IF FOUND THEN PERFORM retention.leave_writer(token); END IF;
END $$;
CREATE OR REPLACE FUNCTION classification.activate_catalog(id text,database text,token text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
DECLARE l classification.graph_load; old classification.catalog_current; moment timestamptz;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT l FROM classification.graph_load WHERE load_id=token;
 IF l.state<>'VERIFIED' OR l.release_id<>id OR l.database_id<>database OR
   NOT EXISTS(SELECT 1 FROM classification.graph_target WHERE database_id=database AND release_id=id AND load_id=token)
 THEN RAISE EXCEPTION 'ONET_VERIFIED_CURRENT_GRAPH_REQUIRED'; END IF;
 PERFORM classification.assert_graph_plan(token);
 SELECT * INTO old FROM classification.catalog_current WHERE scheme_id='ONET' FOR UPDATE;
 IF old.release_id=id AND old.database_id=database AND old.load_id=token THEN RETURN; END IF;
 moment:=clock_timestamp();
 INSERT INTO classification.activation_event(activation_id,scheme_id,release_id,previous_release_id,database_id,load_id,activated_at)
 VALUES(gen_random_uuid()::text,'ONET',id,old.release_id,database,token,moment);
 INSERT INTO classification.catalog_current(scheme_id,release_id,database_id,load_id,activated_at)
 VALUES('ONET',id,database,token,moment)
 ON CONFLICT(scheme_id) DO UPDATE SET release_id=excluded.release_id,database_id=excluded.database_id,
  load_id=excluded.load_id,activated_at=excluded.activated_at;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA classification FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION classification.import_onet_catalog(jsonb),
 classification.begin_graph_load(text,text,text),classification.finish_graph_load(text,bigint,bigint,boolean),
 classification.fail_graph_load(text),classification.activate_catalog(text,text,text) FROM PUBLIC;
COMMIT;
