-- Generated adapter; requires the typed requirement v3 graph stage first.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.graph_node_candidates(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
 SELECT * FROM ontology.graph_node_candidates_base_v1(id)
 UNION ALL SELECT * FROM ontology.requirement_graph_nodes_v1(id)
 UNION ALL SELECT * FROM editorial.graph_nodes_v1(id)
$$;
CREATE OR REPLACE FUNCTION ontology.graph_edge_candidates(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
 SELECT * FROM ontology.graph_edge_candidates_base_v1(id)
 UNION ALL SELECT * FROM ontology.requirement_graph_edges_v1(id)
 UNION ALL SELECT * FROM editorial.graph_edges_v1(id)
$$;
CREATE OR REPLACE FUNCTION ontology.graph_inventory_manifest(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT ontology.graph_inventory_manifest_base_v1(id)||CASE WHEN EXISTS(SELECT 1 FROM ontology.requirement_membership WHERE release_id=id)
 THEN jsonb_build_object('requirement_membership',(SELECT to_jsonb(m) FROM ontology.requirement_membership m WHERE release_id=id),
  'requirement_projection',ontology.requirement_graph_manifest_v1(id)) ELSE '{}'::jsonb END
 ||coalesce(editorial.graph_manifest_v1(id),'{}'::jsonb)
$$;
CREATE OR REPLACE VIEW ontology.publication_issue AS
 SELECT r.release_id,'SERVING_CONTRACT_INTEGRATION_PENDING'::text AS issue FROM ontology.corpus_release r
 UNION ALL SELECT p.release_id,'UNRESOLVED_POSTING_OUTCOME' FROM ontology.posting_selection p WHERE outcome<>'ACCEPTED'
 UNION ALL SELECT release_id,issue FROM ontology.typed_requirement_issue
 UNION ALL SELECT r.release_id,'EDITORIAL_SOURCE_MISSING' FROM ontology.corpus_release r
  WHERE NOT EXISTS(SELECT 1 FROM editorial.release_pin p WHERE p.release_id=r.release_id)
 UNION ALL SELECT r.release_id,'EDITORIAL_CURRENT_REVIEW_CHANGED' FROM ontology.corpus_release r
  JOIN editorial.release_pin p USING(release_id) JOIN editorial.catalogue_status s USING(snapshot_id)
  WHERE r.state IN ('PREPARING','READY') AND (NOT s.latest_version OR s.review_state<>'HUMAN_ACCEPTED' OR s.review_id<>p.review_id);

CREATE OR REPLACE FUNCTION ontology.seal_graph(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE sealed_manifest jsonb;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM 1 FROM ontology.corpus_release WHERE release_id=id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_ONTOLOGY_RELEASE'; END IF;
 PERFORM ontology.verify_requirements_v1(id);
 PERFORM editorial.verify_graph_v1(id);
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest_hash IS NOT NULL) THEN
  IF (SELECT r.manifest FROM ontology.corpus_release r WHERE release_id=id) IS DISTINCT FROM ontology.graph_inventory_manifest(id)
  THEN RAISE EXCEPTION 'SEALED_GRAPH_INVENTORY_CHANGED'; END IF;
  IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND state IN ('REVOKED','FAILED')) THEN RAISE EXCEPTION 'RELEASE_NOT_LOADABLE'; END IF;
  RETURN;
 END IF;
 PERFORM ontology.require_preparing(id); PERFORM ontology.check_frozen_sources(id); PERFORM ontology.verify_claims(id);
 PERFORM ontology.verify_observation_membership_v1(id);
 IF EXISTS(SELECT 1 FROM ontology.source_pin p WHERE release_id=id AND p.record_count<>(SELECT count(*) FROM ontology.input_record i WHERE i.release_id=id AND i.run_id=p.run_id))
 THEN RAISE EXCEPTION 'SOURCE_COPY_COUNT_MISMATCH'; END IF;
 CREATE TEMP TABLE graph_node_candidate ON COMMIT DROP AS SELECT * FROM ontology.graph_node_candidates(id);
 IF EXISTS(SELECT 1 FROM graph_node_candidate GROUP BY node_id HAVING count(*)>1) THEN RAISE EXCEPTION 'CONFLICTING_GRAPH_NODE_CONTENT'; END IF;
 IF EXISTS(SELECT 1 FROM graph_node_candidate WHERE properties ?| ARRAY['id','content_hash']) THEN RAISE EXCEPTION 'GRAPH_RESERVED_NODE_PROPERTY'; END IF;
 INSERT INTO ontology.graph_node SELECT id,node_id,labels,properties,ontology.hash(jsonb_build_array(node_id,labels,properties)) FROM graph_node_candidate ON CONFLICT DO NOTHING;
 CREATE TEMP TABLE graph_edge_candidate ON COMMIT DROP AS SELECT DISTINCT subject_id,predicate,object_id,jsonb_strip_nulls(properties) AS properties FROM ontology.graph_edge_candidates(id);
 IF EXISTS(SELECT 1 FROM graph_edge_candidate WHERE properties ?| ARRAY['id','content_hash','release_id']) THEN RAISE EXCEPTION 'GRAPH_RESERVED_EDGE_PROPERTY'; END IF;
 IF EXISTS(SELECT 1 FROM graph_edge_candidate e WHERE (e.subject_id<>'release/'||id AND NOT EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id=e.subject_id))
  OR NOT EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id=e.object_id)) THEN RAISE EXCEPTION 'GRAPH_ENDPOINT_OUTSIDE_RELEASE'; END IF;
 INSERT INTO ontology.graph_edge
 SELECT id,ontology.hash(jsonb_build_array(id,subject_id,predicate,object_id,properties)),subject_id,predicate,object_id,properties,
 ontology.hash(jsonb_build_array(subject_id,predicate,object_id,properties)) FROM graph_edge_candidate ON CONFLICT DO NOTHING;
 PERFORM ontology.verify_graph_numbers(id);
 sealed_manifest:=ontology.graph_inventory_manifest(id);
 UPDATE ontology.corpus_release r SET manifest=sealed_manifest,manifest_hash=ontology.hash(sealed_manifest) WHERE release_id=id;
END $$;

COMMIT;
