"""Add product occupation projection after the immutable editorial v4 stage."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/editorial'
sql=(OUT/'sql/004_graph_adapter.sql').read_text()
sql=sql.replace(' UNION ALL SELECT * FROM editorial.graph_nodes_v1(id)',' UNION ALL SELECT * FROM editorial.graph_nodes_v1(id)\n UNION ALL SELECT * FROM ontology.occupation_graph_nodes_v1(id)')
sql=sql.replace(' UNION ALL SELECT * FROM editorial.graph_edges_v1(id)',' UNION ALL SELECT * FROM editorial.graph_edges_v1(id)\n UNION ALL SELECT * FROM ontology.occupation_graph_edges_v1(id)')
sql=sql.replace(" ||coalesce(editorial.graph_manifest_v1(id),'{}'::jsonb)"," ||coalesce(editorial.graph_manifest_v1(id),'{}'::jsonb)\n ||coalesce(ontology.occupation_graph_manifest_v1(id),'{}'::jsonb)")
sql=sql.replace(' PERFORM editorial.verify_graph_v1(id);',' PERFORM editorial.verify_graph_v1(id);\n PERFORM ontology.verify_occupation_graph_v1(id);')
old="OR s.review_id<>p.review_id);"
assert old in sql
sql=sql.replace(old,"""OR s.review_id<>p.review_id)
 UNION ALL SELECT r.release_id,'OCCUPATION_SELECTION_NOT_FROZEN' FROM ontology.corpus_release r
  WHERE NOT EXISTS(SELECT 1 FROM ontology.occupation_freeze f WHERE f.release_id=r.release_id)
 UNION ALL SELECT release_id,'UNRESOLVED_PRODUCT_OCCUPATION' FROM ontology.occupation_selection WHERE outcome<>'MATCHED'
 UNION ALL SELECT release_id,'OCCUPATION_CONFIDENCE_UNASSESSED' FROM ontology.primary_product_occupation;""")
(OUT/'sql/011_occupation_graph_adapter.sql').write_text(sql.replace('-- Generated adapter;', '-- Generated product occupation adapter;',1))
