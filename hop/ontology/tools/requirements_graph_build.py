"""Layer typed requirements onto the exact base graph functions. Development only."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sql=(ROOT/'hop/ontology/sql/004_graph_inventory.sql').read_text()
def function(name,end):
    return sql[sql.index('CREATE OR REPLACE FUNCTION ontology.'+name):sql.index(end,sql.index('CREATE OR REPLACE FUNCTION ontology.'+name))].strip()
base=[]
for name,next_name in [('graph_node_candidates','graph_edge_candidates'),('graph_edge_candidates','graph_inventory_manifest'),('graph_inventory_manifest','verify_graph_numbers')]:
    body=function(name,'CREATE OR REPLACE FUNCTION ontology.'+next_name)
    base.append(body.replace('FUNCTION ontology.'+name+'(', 'FUNCTION ontology.'+name+'_base_v1(',1))
seal=function('seal_graph','-- Native Hop sends')
seal=seal.replace(" IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest_hash IS NOT NULL)",
    " PERFORM ontology.verify_requirements_v1(id);\n IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest_hash IS NOT NULL)",1)
extra='''
CREATE OR REPLACE FUNCTION ontology.graph_node_candidates(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
 SELECT * FROM ontology.graph_node_candidates_base_v1(id)
 UNION ALL SELECT * FROM ontology.requirement_graph_nodes_v1(id)
$$;
CREATE OR REPLACE FUNCTION ontology.graph_edge_candidates(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
 SELECT * FROM ontology.graph_edge_candidates_base_v1(id)
 UNION ALL SELECT * FROM ontology.requirement_graph_edges_v1(id)
$$;
CREATE OR REPLACE FUNCTION ontology.graph_inventory_manifest(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT ontology.graph_inventory_manifest_base_v1(id)||CASE WHEN EXISTS(SELECT 1 FROM ontology.requirement_membership WHERE release_id=id)
 THEN jsonb_build_object('requirement_membership',(SELECT to_jsonb(m) FROM ontology.requirement_membership m WHERE release_id=id),
  'requirement_projection',ontology.requirement_graph_manifest_v1(id)) ELSE '{}'::jsonb END
$$;
CREATE OR REPLACE VIEW ontology.publication_issue AS
 SELECT r.release_id,'SERVING_CONTRACT_INTEGRATION_PENDING'::text AS issue FROM ontology.corpus_release r
 UNION ALL SELECT p.release_id,'UNRESOLVED_POSTING_OUTCOME' FROM ontology.posting_selection p WHERE outcome<>'ACCEPTED'
 UNION ALL SELECT release_id,issue FROM ontology.typed_requirement_issue;
'''
property_view=sql[sql.index('CREATE OR REPLACE VIEW ontology.graph_property'):sql.index('CREATE OR REPLACE FUNCTION ontology.begin_graph_load')]
property_view=property_view.replace("('date_posted','closing_date','established_date')", "('date_posted','closing_date','established_date','earliest_start')")
(ROOT/'hop/ontology/sql/016_requirement_graph.sql').write_text('-- Generated base-compatible typed requirement graph projection.\nBEGIN;\n'+'\n\n'.join(base)+'\n'+extra+'\n'+seal+'\n'+property_view+'\nCOMMIT;\n')
