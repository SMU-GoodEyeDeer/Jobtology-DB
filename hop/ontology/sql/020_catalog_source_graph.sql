-- Explicit catalog projection. Full reviewed sealing and serving activation stay separate.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.catalog_source_mode (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 mode text NOT NULL DEFAULT 'SOURCE_ONLY' CHECK(mode='SOURCE_ONLY'),
 contract_version text NOT NULL DEFAULT 'hop-ontology-graph-source-v1' CHECK(contract_version='hop-ontology-graph-source-v1'),
 prepared_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='ontology.catalog_source_mode'::regclass AND tgname='ontology_immutable_catalog_source_mode') THEN
  CREATE TRIGGER ontology_immutable_catalog_source_mode BEFORE UPDATE OR DELETE ON ontology.catalog_source_mode
   FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.verify_catalog_source_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM ontology.check_frozen_sources(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.catalog_source_mode WHERE release_id=id AND mode='SOURCE_ONLY'
  AND contract_version='hop-ontology-graph-source-v1') THEN RAISE EXCEPTION 'CATALOG_SOURCE_MODE_REQUIRED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ontology.observation_membership WHERE release_id=id)
 THEN RAISE EXCEPTION 'BIND_OBSERVATION_MEMBERSHIP_FIRST'; END IF;
 PERFORM ontology.verify_observation_membership_v1(id);
 IF EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.posting_selection WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.link_selection WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.rule_freeze WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.rule_selection WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.guarded_rule WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.release_claim WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.release_position WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.release_mapping WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.requirement_membership WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.document_input_set WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.document_input WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.artifact_document WHERE release_id=id)
 THEN RAISE EXCEPTION 'CATALOG_DERIVED_MEMBERSHIP_FORBIDDEN'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ontology.release_revision WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.source_coverage WHERE release_id=id AND
   (unaccounted_records<>0 OR supported_records<>record_count)) OR
  EXISTS(SELECT 1 FROM ontology.source_pin p WHERE p.release_id=id AND
   p.record_count<>(SELECT count(*) FROM ontology.input_record i WHERE i.release_id=id AND i.run_id=p.run_id))
 THEN RAISE EXCEPTION 'CATALOG_SOURCE_COVERAGE_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest IS NOT NULL) THEN
  IF EXISTS((SELECT n.node_id,n.labels,n.properties,n.content_hash FROM ontology.graph_node n WHERE release_id=id
    EXCEPT SELECT c.node_id,c.labels,c.properties,ontology.hash(jsonb_build_array(c.node_id,c.labels,c.properties))
     FROM ontology.catalog_source_nodes_v1(id) c)
   UNION ALL
   (SELECT c.node_id,c.labels,c.properties,ontology.hash(jsonb_build_array(c.node_id,c.labels,c.properties))
    FROM ontology.catalog_source_nodes_v1(id) c
    EXCEPT SELECT n.node_id,n.labels,n.properties,n.content_hash FROM ontology.graph_node n WHERE release_id=id))
  THEN RAISE EXCEPTION 'CATALOG_SOURCE_NODE_INVENTORY_CHANGED'; END IF;
  IF EXISTS((SELECT e.edge_id,e.subject_id,e.predicate,e.object_id,e.properties,e.content_hash FROM ontology.graph_edge e WHERE release_id=id
    EXCEPT SELECT ontology.hash(jsonb_build_array(id,c.subject_id,c.predicate,c.object_id,c.properties)),
     c.subject_id,c.predicate,c.object_id,c.properties,ontology.hash(jsonb_build_array(c.subject_id,c.predicate,c.object_id,c.properties))
     FROM ontology.catalog_source_edges_v1(id) c)
   UNION ALL
   (SELECT ontology.hash(jsonb_build_array(id,c.subject_id,c.predicate,c.object_id,c.properties)),
     c.subject_id,c.predicate,c.object_id,c.properties,ontology.hash(jsonb_build_array(c.subject_id,c.predicate,c.object_id,c.properties))
    FROM ontology.catalog_source_edges_v1(id) c
    EXCEPT SELECT e.edge_id,e.subject_id,e.predicate,e.object_id,e.properties,e.content_hash FROM ontology.graph_edge e WHERE release_id=id))
  THEN RAISE EXCEPTION 'CATALOG_SOURCE_EDGE_INVENTORY_CHANGED'; END IF;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.prepare_catalog_source_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM ontology.require_preparing(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.catalog_source_mode WHERE release_id=id) THEN
  IF EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) OR
   EXISTS(SELECT 1 FROM ontology.document_input_set WHERE release_id=id)
  THEN RAISE EXCEPTION 'CATALOG_SOURCE_REQUIRES_UNREVIEWED_RELEASE'; END IF;
  INSERT INTO ontology.catalog_source_mode(release_id) VALUES(id);
 END IF;
 PERFORM ontology.verify_catalog_source_v1(id);
END $$;

CREATE OR REPLACE FUNCTION ontology.catalog_source_nodes_v1(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
 SELECT n.* FROM ontology.graph_node_candidates_base_v1(id) n WHERE
  (n.labels[1]='ontologyEntity' AND cardinality(n.labels)=2) OR
  (n.labels[1]='entityRevision' AND cardinality(n.labels)=2) OR
  n.labels IN (ARRAY['entityObservationState'],ARRAY['ontologySource'],ARRAY['sourceSnapshot'],
   ARRAY['sourceRecordEvidence'],ARRAY['assertion','sourceAssertion'])
$$;
CREATE OR REPLACE FUNCTION ontology.catalog_source_edges_v1(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
 SELECT DISTINCT e.subject_id,e.predicate,e.object_id,jsonb_strip_nulls(e.properties)
 FROM ontology.graph_edge_candidates_base_v1(id) e
 WHERE e.predicate IN ('HAS_REVISION','FOR_ENTITY','SELECTS_REVISION','DERIVED_FROM','IN_SNAPSHOT',
  'FROM_SOURCE','EVIDENCED_BY','SUBJECT','OBJECT','POSTED_BY','BELONGS_TO_OCCUPATION',
  'VERSION_OF','CLASSIFIED_AS','BROADER_THAN','HAS_MEMBER','CURRICULUM_REFERENCES',
  'HAS_EXAM_SESSION','HAS_CAREER_RANK','REFERENCES_UNIT_FAMILY','INCLUDES')
 AND (e.subject_id='release/'||id OR EXISTS(SELECT 1 FROM ontology.catalog_source_nodes_v1(id) n WHERE n.node_id=e.subject_id))
 AND EXISTS(SELECT 1 FROM ontology.catalog_source_nodes_v1(id) n WHERE n.node_id=e.object_id)
$$;

-- Retain the exact reviewed manifest for every release without a catalog mode.
CREATE OR REPLACE FUNCTION ontology.graph_inventory_manifest_reviewed_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('format','hop-ontology-graph-v1','release_id',r.release_id,'pipeline_version',r.pipeline_version,
  'methodology_version',r.methodology_version,'data_as_of',r.data_as_of,'created_at',r.created_at,
  'source_pins',(SELECT jsonb_agg(p ORDER BY source_id) FROM ontology.source_pin p WHERE release_id=id),
  'review_freeze',(SELECT to_jsonb(f) FROM ontology.review_freeze f WHERE release_id=id),
  'selection_hash',(SELECT ontology.hash(coalesce(jsonb_agg(p ORDER BY entity_id),'[]')) FROM ontology.posting_selection p WHERE release_id=id),
  'link_selection_hash',(SELECT ontology.hash(coalesce(jsonb_agg(p ORDER BY candidate_id),'[]')) FROM ontology.link_selection p WHERE release_id=id),
  'nodes',(SELECT count(*) FROM ontology.graph_node WHERE release_id=id),
  'node_hash',(SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(node_id,content_hash) ORDER BY node_id),'[]')) FROM ontology.graph_node WHERE release_id=id),
  'edges',(SELECT count(*) FROM ontology.graph_edge WHERE release_id=id),
  'edge_hash',(SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(edge_id,content_hash) ORDER BY edge_id),'[]')) FROM ontology.graph_edge WHERE release_id=id))
  || CASE WHEN EXISTS(SELECT 1 FROM ontology.rule_freeze WHERE release_id=id) THEN jsonb_build_object(
  'rule_freeze',(SELECT to_jsonb(f) FROM ontology.rule_freeze f WHERE release_id=id),
  'rule_selection_hash',(SELECT ontology.hash(coalesce(jsonb_agg(s ORDER BY interpretation_id),'[]')) FROM ontology.rule_selection s WHERE release_id=id)) ELSE '{}'::jsonb END
  || CASE WHEN EXISTS(SELECT 1 FROM ontology.document_input_set WHERE release_id=id) THEN jsonb_build_object(
  'document_input_set',(SELECT to_jsonb(s) FROM ontology.document_input_set s WHERE release_id=id),
  'document_evidence_hash',(SELECT ontology.hash(coalesce(jsonb_agg(d ORDER BY artifact_id),'[]')) FROM ontology.artifact_document d WHERE release_id=id),
  'document_section_hash',(SELECT ontology.hash(coalesce(jsonb_agg(s ORDER BY artifact_id,section_index),'[]')) FROM ontology.document_section s WHERE release_id=id)) ELSE '{}'::jsonb END
  || CASE WHEN EXISTS(SELECT 1 FROM ontology.observation_membership WHERE release_id=id) THEN jsonb_build_object(
  'observation_membership',(SELECT to_jsonb(m) FROM ontology.observation_membership m WHERE release_id=id)) ELSE '{}'::jsonb END
 FROM ontology.corpus_release r WHERE release_id=id
$$;
CREATE OR REPLACE FUNCTION ontology.graph_inventory_manifest_base_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM ontology.catalog_source_mode WHERE release_id=id) THEN
  jsonb_build_object('format','hop-ontology-graph-source-v1','mode','SOURCE_ONLY','release_id',r.release_id,
   'pipeline_version',r.pipeline_version,'methodology_version',r.methodology_version,
   'data_as_of',r.data_as_of,'created_at',r.created_at,
   'source_pins',(SELECT jsonb_agg(p ORDER BY source_id) FROM ontology.source_pin p WHERE release_id=id),
   'observation_membership',(SELECT to_jsonb(m) FROM ontology.observation_membership m WHERE release_id=id),
   'nodes',(SELECT count(*) FROM ontology.graph_node WHERE release_id=id),
   'node_hash',(SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(node_id,content_hash) ORDER BY node_id),'[]')) FROM ontology.graph_node WHERE release_id=id),
   'edges',(SELECT count(*) FROM ontology.graph_edge WHERE release_id=id),
   'edge_hash',(SELECT ontology.hash(coalesce(jsonb_agg(jsonb_build_array(edge_id,content_hash) ORDER BY edge_id),'[]')) FROM ontology.graph_edge WHERE release_id=id))
  ELSE ontology.graph_inventory_manifest_reviewed_v1(id) END
 FROM ontology.corpus_release r WHERE release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.seal_catalog_source_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE sealed_manifest jsonb;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM 1 FROM ontology.corpus_release WHERE release_id=id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_ONTOLOGY_RELEASE'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND state IN ('REVOKED','FAILED')) THEN RAISE EXCEPTION 'RELEASE_NOT_LOADABLE'; END IF;
 PERFORM ontology.verify_catalog_source_v1(id);
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest IS NOT NULL) THEN
  IF (SELECT manifest FROM ontology.corpus_release WHERE release_id=id) IS DISTINCT FROM ontology.graph_inventory_manifest(id)
  THEN RAISE EXCEPTION 'SEALED_GRAPH_INVENTORY_CHANGED'; END IF;
  RETURN;
 END IF;
 PERFORM ontology.require_preparing(id);
 CREATE TEMP TABLE catalog_node_candidate ON COMMIT DROP AS SELECT * FROM ontology.catalog_source_nodes_v1(id);
 IF EXISTS(SELECT 1 FROM catalog_node_candidate GROUP BY node_id HAVING count(*)>1) THEN RAISE EXCEPTION 'CONFLICTING_GRAPH_NODE_CONTENT'; END IF;
 IF EXISTS(SELECT 1 FROM catalog_node_candidate WHERE properties ?| ARRAY['id','content_hash']) THEN RAISE EXCEPTION 'GRAPH_RESERVED_NODE_PROPERTY'; END IF;
 INSERT INTO ontology.graph_node SELECT id,node_id,labels,properties,ontology.hash(jsonb_build_array(node_id,labels,properties)) FROM catalog_node_candidate;
 CREATE TEMP TABLE catalog_edge_candidate ON COMMIT DROP AS SELECT * FROM ontology.catalog_source_edges_v1(id);
 IF EXISTS(SELECT 1 FROM catalog_edge_candidate WHERE properties ?| ARRAY['id','content_hash','release_id']) THEN RAISE EXCEPTION 'GRAPH_RESERVED_EDGE_PROPERTY'; END IF;
 IF EXISTS(SELECT 1 FROM catalog_edge_candidate e WHERE (e.subject_id<>'release/'||id AND NOT EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id=e.subject_id))
  OR NOT EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id=e.object_id)) THEN RAISE EXCEPTION 'GRAPH_ENDPOINT_OUTSIDE_RELEASE'; END IF;
 INSERT INTO ontology.graph_edge
 SELECT id,ontology.hash(jsonb_build_array(id,subject_id,predicate,object_id,properties)),subject_id,predicate,object_id,properties,
  ontology.hash(jsonb_build_array(subject_id,predicate,object_id,properties)) FROM catalog_edge_candidate;
 PERFORM ontology.verify_graph_numbers(id);
 sealed_manifest:=ontology.graph_inventory_manifest(id);
 UPDATE ontology.corpus_release SET manifest=sealed_manifest,manifest_hash=ontology.hash(sealed_manifest) WHERE release_id=id;
 PERFORM ontology.verify_catalog_source_v1(id);
END $$;

-- The loader selects a persisted release contract, never a caller-supplied skip flag.
CREATE OR REPLACE FUNCTION ontology.begin_graph_load(id text,database text,token text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF nullif(btrim(database),'') IS NULL OR nullif(btrim(token),'') IS NULL THEN RAISE EXCEPTION 'GRAPH_LOAD_IDENTITY_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.catalog_source_mode WHERE release_id=id)
 THEN PERFORM ontology.seal_catalog_source_v1(id);
 ELSE PERFORM ontology.seal_graph(id); END IF;
 IF EXISTS(SELECT 1 FROM ontology.graph_load WHERE database_id=database AND state='RUNNING') THEN RAISE EXCEPTION 'ONTOLOGY_GRAPH_WRITER_ALREADY_RUNNING'; END IF;
 INSERT INTO ontology.graph_load(load_id,release_id,database_id,manifest_hash,state)
 SELECT token,id,database,manifest_hash,'RUNNING' FROM ontology.corpus_release WHERE release_id=id;
 PERFORM retention.enter_writer(token,'ONTOLOGY_GRAPH',id);
 UPDATE ontology.corpus_release SET graph_verified_at=NULL WHERE release_id=id;
END $$;
COMMIT;
