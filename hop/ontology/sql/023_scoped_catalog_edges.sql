BEGIN;
CREATE OR REPLACE FUNCTION ontology.catalog_source_edges_v1(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
 WITH nodes AS MATERIALIZED (
  SELECT DISTINCT node_id FROM ontology.catalog_source_nodes_v1(id)
 )
 SELECT DISTINCT e.subject_id,e.predicate,e.object_id,jsonb_strip_nulls(e.properties)
 FROM ontology.graph_edge_candidates_base_v1(id) e
 LEFT JOIN nodes source ON source.node_id=e.subject_id
 JOIN nodes target ON target.node_id=e.object_id
 WHERE e.predicate IN ('HAS_REVISION','FOR_ENTITY','SELECTS_REVISION','DERIVED_FROM','IN_SNAPSHOT',
  'FROM_SOURCE','EVIDENCED_BY','SUBJECT','OBJECT','POSTED_BY','BELONGS_TO_OCCUPATION',
  'VERSION_OF','CLASSIFIED_AS','BROADER_THAN','HAS_MEMBER','CURRICULUM_REFERENCES',
  'HAS_EXAM_SESSION','HAS_CAREER_RANK','REFERENCES_UNIT_FAMILY','INCLUDES')
 AND (e.subject_id='release/'||id OR source.node_id IS NOT NULL)
$$;
COMMIT;
