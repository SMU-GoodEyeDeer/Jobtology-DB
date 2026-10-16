-- Bounded flat projections. Nulls and nested source values remain in immutable PG evidence.
BEGIN;
SELECT retention.gate();
CREATE OR REPLACE FUNCTION onet_detail.scalar_properties(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT coalesce(jsonb_object_agg(key,CASE WHEN jsonb_typeof(v) IN('object','array') THEN to_jsonb(v::text) ELSE v END),'{}')
 FROM jsonb_each(value) p(key,v) WHERE jsonb_typeof(v)<>'null'
$$;
CREATE OR REPLACE FUNCTION onet_detail.graph_nodes(release_key text)
RETURNS TABLE(node_id text,labels text[],properties jsonb,content_hash text)
LANGUAGE sql STABLE SET jit=off AS $$
 SELECT n.id,ARRAY['entity','onetDetail',lower(n.type)],p.value,p.value->>'content_hash'
 FROM onet_detail.catalog_release r JOIN onet_detail.node n USING(release_id)
 CROSS JOIN LATERAL(SELECT onet_detail.with_content_hash(onet_detail.scalar_properties(n.properties)||jsonb_build_object(
 'id',n.id,'managed_by','jobtology-onet-details-v1','scheme_id','ONET','kind',n.type,'release_id',r.release_id,
 'source_version',r.source_version,'base_release_id',r.base_release_id,'current',true)) value) p
 WHERE r.release_id=release_key AND r.state='READY' ORDER BY n.id
$$;
CREATE OR REPLACE FUNCTION onet_detail.graph_edges(release_key text)
RETURNS TABLE(edge_id text,start_id text,end_id text,edge_type text,properties jsonb,content_hash text)
LANGUAGE sql STABLE SET jit=off AS $$
 SELECT e.id,e.source_id,e.target_id,e.type,p.value,p.value->>'content_hash'
 FROM onet_detail.catalog_release r JOIN onet_detail.edge e USING(release_id)
 CROSS JOIN LATERAL(SELECT onet_detail.with_content_hash(onet_detail.scalar_properties(e.properties)||jsonb_build_object(
 'id',e.id,'managed_by','jobtology-onet-details-v1','scheme_id','ONET','kind',e.type,'release_id',r.release_id,
 'source_version',r.source_version,'base_release_id',r.base_release_id,'current',true)) value) p
 WHERE r.release_id=release_key AND r.state='READY' ORDER BY e.id
$$;
CREATE OR REPLACE FUNCTION onet_detail.assert_graph_plan(token text) RETURNS void
LANGUAGE plpgsql STABLE SET jit=off AS $$
#variable_conflict use_variable
DECLARE l onet_detail.graph_load;
BEGIN
 SELECT * INTO STRICT l FROM onet_detail.graph_load WHERE load_id=token;
 PERFORM onet_detail.assert_catalog(l.release_id);
 IF l.manifest_hash IS DISTINCT FROM (SELECT manifest_hash FROM onet_detail.catalog_release WHERE release_id=l.release_id)
  OR (SELECT count(*) FROM onet_detail.graph_load_node WHERE load_id=token)<>l.expected_nodes
  OR (SELECT count(*) FROM onet_detail.graph_load_edge WHERE load_id=token)<>l.expected_edges
  OR (SELECT count(*) FROM onet_detail.graph_load_node WHERE load_id=token AND properties->'current'='true'::jsonb)<>l.current_nodes
  OR (SELECT count(*) FROM onet_detail.graph_load_edge WHERE load_id=token AND properties->'current'='true'::jsonb)<>l.current_edges
  OR EXISTS(SELECT 1 FROM onet_detail.graph_load_node n WHERE n.load_id=token AND
    (n.node_id<>n.properties->>'id' OR n.content_hash IS DISTINCT FROM onet_detail.hash(n.properties-'content_hash')
     OR n.properties->>'content_hash' IS DISTINCT FROM n.content_hash
     OR n.properties->>'managed_by' IS DISTINCT FROM 'jobtology-onet-details-v1'
     OR n.properties->>'scheme_id' IS DISTINCT FROM 'ONET'))
  OR EXISTS(SELECT 1 FROM onet_detail.graph_load_edge e WHERE e.load_id=token AND
    (e.edge_id<>e.properties->>'id' OR e.content_hash IS DISTINCT FROM onet_detail.hash(e.properties-'content_hash')
     OR e.properties->>'content_hash' IS DISTINCT FROM e.content_hash
     OR e.properties->>'managed_by' IS DISTINCT FROM 'jobtology-onet-details-v1'
     OR e.properties->>'scheme_id' IS DISTINCT FROM 'ONET'))
 THEN RAISE EXCEPTION 'ONET_DETAILS_GRAPH_PLAN_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM onet_detail.graph_load_node n
   CROSS JOIN LATERAL jsonb_each(n.properties) p WHERE n.load_id=token AND jsonb_typeof(p.value) NOT IN('string','number','boolean')) OR
  EXISTS(SELECT 1 FROM onet_detail.graph_load_edge e
   CROSS JOIN LATERAL jsonb_each(e.properties) p WHERE e.load_id=token AND jsonb_typeof(p.value) NOT IN('string','number','boolean'))
 THEN RAISE EXCEPTION 'ONET_DETAILS_GRAPH_PROPERTY_NOT_SCALAR'; END IF;
END $$;

CREATE OR REPLACE FUNCTION onet_detail.begin_graph_load(id text,database text,token text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
#variable_conflict use_variable
DECLARE old onet_detail.graph_target; r onet_detail.catalog_release; active onet_detail.catalog_current;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT r FROM onet_detail.catalog_release WHERE release_id=id AND state='READY';
 PERFORM onet_detail.assert_catalog(id);
 IF NOT EXISTS(SELECT 1 FROM classification.catalog_current c JOIN classification.graph_target t USING(database_id)
  WHERE c.release_id=r.base_release_id AND c.database_id=database AND t.load_id=c.load_id)
 THEN RAISE EXCEPTION 'ONET_DETAILS_CURRENT_BASE_REQUIRED'; END IF;

 IF length(btrim(coalesce(database,''))) NOT BETWEEN 1 AND 200 OR
   length(btrim(coalesce(token,''))) NOT BETWEEN 1 AND 200
 THEN RAISE EXCEPTION 'ONET_DETAILS_GRAPH_IDENTITY_REQUIRED'; END IF;
 SELECT * INTO old FROM onet_detail.graph_target WHERE database_id=database FOR UPDATE;
 IF old.release_id IS NOT NULL AND old.release_id<>id THEN RAISE EXCEPTION 'ONET_DETAILS_ROLLOVER_REQUIRES_QUALIFICATION'; END IF;
 SELECT * INTO active FROM onet_detail.catalog_current WHERE scheme_id='ONET';
 IF old.release_id IS NOT NULL AND old.release_id<>id AND
    r.imported_at<=(SELECT imported_at FROM onet_detail.catalog_release WHERE release_id=old.release_id)
 THEN RAISE EXCEPTION 'ONET_DETAILS_STALE_RELEASE_REPLAY'; END IF;
 IF active.release_id IS NOT NULL AND active.database_id<>database THEN
  RAISE EXCEPTION 'ONET_DETAILS_CURRENT_DATABASE_MISMATCH'; END IF;
 INSERT INTO onet_detail.graph_load(load_id,release_id,database_id,previous_load_id,manifest_hash,state)
 VALUES(token,id,database,old.load_id,r.manifest_hash,'RUNNING');
 PERFORM retention.enter_writer(token,'ONET_DETAILS_GRAPH',id);
 INSERT INTO onet_detail.graph_load_occupation
 SELECT token,n.node_id,n.labels,n.properties,n.content_hash FROM classification.catalog_current c
 JOIN classification.graph_load_node n USING(load_id)
 WHERE c.release_id=r.base_release_id AND n.node_id IN
 (SELECT e.source_id FROM onet_detail.edge e WHERE e.release_id=id AND e.source_id LIKE 'urn:jobtology:onet:occupation:%');
 IF (SELECT count(*) FROM onet_detail.graph_load_occupation WHERE load_id=token)<>
 (SELECT count(DISTINCT source_id) FROM onet_detail.edge WHERE release_id=id AND source_id LIKE 'urn:jobtology:onet:occupation:%')
 THEN RAISE EXCEPTION 'ONET_DETAILS_OCCUPATION_INVENTORY_MISMATCH'; END IF;

 INSERT INTO onet_detail.graph_load_node
 SELECT token,n.node_id,n.labels,n.properties,n.content_hash,p.labels,p.properties,p.content_hash
 FROM onet_detail.graph_nodes(id) n LEFT JOIN onet_detail.graph_load_node p
  ON p.load_id=old.load_id AND p.node_id=n.node_id;
 INSERT INTO onet_detail.graph_load_node
 SELECT token,p.node_id,p.labels,v.properties,v.properties->>'content_hash',p.labels,p.properties,p.content_hash
 FROM onet_detail.graph_load_node p CROSS JOIN LATERAL
  (SELECT onet_detail.with_content_hash(p.properties||jsonb_build_object('current',false)) AS properties) v
 WHERE p.load_id=old.load_id AND NOT EXISTS(SELECT 1 FROM onet_detail.graph_load_node n
  WHERE n.load_id=token AND n.node_id=p.node_id);
 INSERT INTO onet_detail.graph_load_edge
 SELECT token,e.edge_id,e.start_id,e.end_id,e.edge_type,e.properties,e.content_hash,p.properties,p.content_hash
 FROM onet_detail.graph_edges(id) e LEFT JOIN onet_detail.graph_load_edge p
  ON p.load_id=old.load_id AND p.edge_id=e.edge_id;
 INSERT INTO onet_detail.graph_load_edge
 SELECT token,p.edge_id,p.start_id,p.end_id,p.edge_type,v.properties,v.properties->>'content_hash',p.properties,p.content_hash
 FROM onet_detail.graph_load_edge p CROSS JOIN LATERAL
  (SELECT onet_detail.with_content_hash(p.properties||jsonb_build_object('current',false)) AS properties) v
 WHERE p.load_id=old.load_id AND NOT EXISTS(SELECT 1 FROM onet_detail.graph_load_edge e
  WHERE e.load_id=token AND e.edge_id=p.edge_id);
 UPDATE onet_detail.graph_load SET
  expected_nodes=(SELECT count(*) FROM onet_detail.graph_load_node WHERE load_id=token),
  expected_edges=(SELECT count(*) FROM onet_detail.graph_load_edge WHERE load_id=token),
  current_nodes=(SELECT count(*) FROM onet_detail.graph_load_node WHERE load_id=token AND properties->'current'='true'::jsonb),
  current_edges=(SELECT count(*) FROM onet_detail.graph_load_edge WHERE load_id=token AND properties->'current'='true'::jsonb)
 WHERE load_id=token;
 PERFORM onet_detail.assert_graph_plan(token);
END $$;

CREATE OR REPLACE FUNCTION onet_detail.assert_readable_graph_load(token text) RETURNS text
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_variable
BEGIN
 IF NOT EXISTS(SELECT 1 FROM onet_detail.graph_load WHERE load_id=token AND state IN('RUNNING','VERIFIED'))
 THEN RAISE EXCEPTION 'ONET_DETAILS_GRAPH_LOAD_NOT_READABLE'; END IF;
 RETURN token;
END $$;
CREATE OR REPLACE FUNCTION onet_detail.graph_load_context(token text)
RETURNS TABLE(load_id text,release_id text,database_id text,previous_release_id text,manifest_hash text,
 expected_nodes bigint,expected_edges bigint,current_nodes bigint,current_edges bigint)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_variable
BEGIN
 PERFORM onet_detail.assert_readable_graph_load(token);
 RETURN QUERY
 SELECT l.load_id,l.release_id,l.database_id,p.release_id,l.manifest_hash,l.expected_nodes,l.expected_edges,l.current_nodes,l.current_edges
 FROM onet_detail.graph_load l LEFT JOIN onet_detail.graph_load p ON p.load_id=l.previous_load_id
 WHERE l.load_id=token AND l.state IN('RUNNING','VERIFIED')
 ;
END
$$;
CREATE OR REPLACE FUNCTION onet_detail.graph_load_nodes(token text)
RETURNS TABLE(node_id text,labels text[],properties jsonb,content_hash text,previous_labels text[],
 previous_properties jsonb,previous_content_hash text)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_variable
BEGIN
 PERFORM onet_detail.assert_readable_graph_load(token);
 RETURN QUERY
 SELECT n.node_id,n.labels,n.properties,n.content_hash,n.previous_labels,n.previous_properties,n.previous_content_hash
 FROM onet_detail.graph_load_node n JOIN onet_detail.graph_load l USING(load_id)
 WHERE n.load_id=token AND l.state IN('RUNNING','VERIFIED') ORDER BY n.node_id
 ;
END
$$;
CREATE OR REPLACE FUNCTION onet_detail.graph_load_edges(token text)
RETURNS TABLE(edge_id text,start_id text,end_id text,edge_type text,properties jsonb,content_hash text,
 previous_properties jsonb,previous_content_hash text)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_variable
BEGIN
 PERFORM onet_detail.assert_readable_graph_load(token);
 RETURN QUERY
 SELECT e.edge_id,e.start_id,e.end_id,e.edge_type,e.properties,e.content_hash,e.previous_properties,e.previous_content_hash
 FROM onet_detail.graph_load_edge e JOIN onet_detail.graph_load l USING(load_id)
 WHERE e.load_id=token AND l.state IN('RUNNING','VERIFIED') ORDER BY e.edge_id
 ;
END
$$;

CREATE OR REPLACE FUNCTION onet_detail.graph_load_occupations(token text)
RETURNS TABLE(node_id text,labels text[],properties jsonb,content_hash text,previous_labels text[],
 previous_properties jsonb,previous_content_hash text)
LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_variable
BEGIN
 PERFORM onet_detail.assert_readable_graph_load(token);
 RETURN QUERY SELECT n.node_id,n.labels,n.properties,n.content_hash,NULL::text[],NULL::jsonb,NULL::text
 FROM onet_detail.graph_load_occupation n WHERE n.load_id=token ORDER BY n.node_id;
END $$;
CREATE OR REPLACE FUNCTION onet_detail.assert_running_graph_load(token text) RETURNS text
LANGUAGE plpgsql STABLE SET jit=off AS $$
#variable_conflict use_variable
DECLARE l onet_detail.graph_load;
BEGIN
 SELECT * INTO l FROM onet_detail.graph_load WHERE load_id=token;
 IF l.state IS DISTINCT FROM 'RUNNING' OR NOT EXISTS(SELECT 1 FROM retention.writer
   WHERE writer_id=token AND kind='ONET_DETAILS_GRAPH' AND target_id=l.release_id)
 THEN RAISE EXCEPTION 'ONET_DETAILS_GRAPH_LOAD_NOT_RUNNING'; END IF;
 RETURN token;
END $$;
CREATE OR REPLACE FUNCTION onet_detail.assert_verified_graph_load(token text) RETURNS text
LANGUAGE plpgsql STABLE SET jit=off AS $$
#variable_conflict use_variable
DECLARE l onet_detail.graph_load;
BEGIN
 SELECT * INTO l FROM onet_detail.graph_load WHERE load_id=token;
 IF l.state IS DISTINCT FROM 'VERIFIED' OR NOT EXISTS(SELECT 1 FROM onet_detail.graph_target
   WHERE database_id=l.database_id AND release_id=l.release_id AND load_id=token)
 THEN RAISE EXCEPTION 'ONET_DETAILS_VERIFIED_CURRENT_GRAPH_REQUIRED'; END IF;
 RETURN token;
END $$;

CREATE OR REPLACE FUNCTION onet_detail.finish_graph_load(token text,nodes bigint,edges bigint,verified boolean) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
#variable_conflict use_variable
DECLARE l onet_detail.graph_load; previous text;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT l FROM onet_detail.graph_load WHERE load_id=token FOR UPDATE;
 PERFORM onet_detail.assert_graph_plan(token);
 SELECT load_id INTO previous FROM onet_detail.graph_target WHERE database_id=l.database_id;
 IF l.state<>'RUNNING' OR verified IS DISTINCT FROM true OR nodes IS DISTINCT FROM l.expected_nodes OR
   edges IS DISTINCT FROM l.expected_edges OR previous IS DISTINCT FROM l.previous_load_id OR
   NOT EXISTS(SELECT 1 FROM retention.writer WHERE writer_id=token AND kind='ONET_DETAILS_GRAPH' AND target_id=l.release_id)
 THEN RAISE EXCEPTION 'ONET_DETAILS_GRAPH_VERIFICATION_FAILED'; END IF;
 UPDATE onet_detail.graph_load SET state='VERIFIED',finished_at=clock_timestamp(),node_count=nodes,edge_count=edges
 WHERE load_id=token;
 INSERT INTO onet_detail.graph_target(database_id,release_id,load_id) VALUES(l.database_id,l.release_id,token)
 ON CONFLICT(database_id) DO UPDATE SET release_id=excluded.release_id,load_id=excluded.load_id;
 PERFORM retention.leave_writer(token);
END $$;
CREATE OR REPLACE FUNCTION onet_detail.fail_graph_load(token text) RETURNS void
LANGUAGE plpgsql AS $$
#variable_conflict use_variable
BEGIN
 PERFORM retention.gate();
 UPDATE onet_detail.graph_load SET state='FAILED',finished_at=clock_timestamp(),
  error='Native O*NET catalogue load failed; retain evidence and retry the same release before rollover.'
 WHERE load_id=token AND state='RUNNING';
 IF FOUND THEN PERFORM retention.leave_writer(token); END IF;
END $$;
CREATE OR REPLACE FUNCTION onet_detail.activate_catalog(id text,database text,token text) RETURNS void
LANGUAGE plpgsql SET jit=off AS $$
#variable_conflict use_variable
DECLARE l onet_detail.graph_load; old onet_detail.catalog_current; moment timestamptz;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT l FROM onet_detail.graph_load WHERE load_id=token;
 IF l.state<>'VERIFIED' OR l.release_id<>id OR l.database_id<>database OR
   NOT EXISTS(SELECT 1 FROM onet_detail.graph_target WHERE database_id=database AND release_id=id AND load_id=token)
 THEN RAISE EXCEPTION 'ONET_DETAILS_VERIFIED_CURRENT_GRAPH_REQUIRED'; END IF;
 PERFORM onet_detail.assert_graph_plan(token);
 SELECT * INTO old FROM onet_detail.catalog_current WHERE scheme_id='ONET' FOR UPDATE;
 IF old.release_id=id AND old.database_id=database AND old.load_id=token THEN RETURN; END IF;
 moment:=clock_timestamp();
 INSERT INTO onet_detail.activation_event(activation_id,scheme_id,release_id,previous_release_id,database_id,load_id,activated_at)
 VALUES(gen_random_uuid()::text,'ONET',id,old.release_id,database,token,moment);
 INSERT INTO onet_detail.catalog_current(scheme_id,release_id,database_id,load_id,activated_at)
 VALUES('ONET',id,database,token,moment)
 ON CONFLICT(scheme_id) DO UPDATE SET release_id=excluded.release_id,database_id=excluded.database_id,
  load_id=excluded.load_id,activated_at=excluded.activated_at;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA onet_detail FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION onet_detail.import_onet_catalog(jsonb,text),
 onet_detail.begin_graph_load(text,text,text),onet_detail.finish_graph_load(text,bigint,bigint,boolean),
 onet_detail.fail_graph_load(text),onet_detail.activate_catalog(text,text,text) FROM PUBLIC;
COMMIT;
