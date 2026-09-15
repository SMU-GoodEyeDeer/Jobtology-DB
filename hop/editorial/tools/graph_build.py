"""Generate an additive editorial adapter without rewriting ontology v1-v3 files."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
source=(ROOT/'hop/ontology/sql/016_requirement_graph.sql').read_text()
seal=source[source.index('CREATE OR REPLACE FUNCTION ontology.seal_graph'):source.index('CREATE OR REPLACE VIEW ontology.graph_property')]
seal=seal.replace(' PERFORM ontology.verify_requirements_v1(id);',
                  ' PERFORM ontology.verify_requirements_v1(id);\n PERFORM editorial.verify_graph_v1(id);',1)
sql='''-- Generated adapter; requires the typed requirement v3 graph stage first.
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
'''
(ROOT/'hop/editorial/sql/004_graph_adapter.sql').write_text(sql+'\n'+seal+'\nCOMMIT;\n')
