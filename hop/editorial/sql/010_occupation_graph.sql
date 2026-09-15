-- Product-role decisions retain exact historical bindings as typed value trees.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.occupation_claim_id_v1(p text,d bigint) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT ontology.hash(jsonb_build_array('primary-product-occupation-v1',p,d))
$$;
CREATE OR REPLACE FUNCTION ontology.occupation_binding_id_v1(kind text,value jsonb) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT ontology.hash(jsonb_build_array('occupation-binding-v1',kind,value))
$$;
CREATE OR REPLACE FUNCTION ontology.occupation_value_id_v1(binding text,pointer text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT 'occupation-value/'||ontology.hash(jsonb_build_array(binding,pointer))
$$;
CREATE OR REPLACE FUNCTION ontology.occupation_bindings_v1(id text)
RETURNS TABLE(binding_id text,binding_kind text,value jsonb) LANGUAGE sql STABLE AS $$
 WITH selected AS (SELECT p.* FROM ontology.occupation_proposal p WHERE p.proposal_id IN
  (SELECT proposal_id FROM ontology.occupation_selection WHERE release_id=id)),
 vals AS (SELECT 'SOURCE'::text kind,source_binding val FROM selected UNION SELECT 'CATALOGUE',catalogue_binding FROM selected)
 SELECT ontology.occupation_binding_id_v1(kind,val),kind,val FROM vals
$$;
CREATE OR REPLACE FUNCTION ontology.occupation_binding_values_v1(id text)
RETURNS TABLE(binding_id text,pointer text,parent_pointer text,member_key text,member_index integer,value jsonb)
LANGUAGE sql STABLE AS $$
 WITH RECURSIVE tree(binding_id,pointer,parent_pointer,member_key,member_index,value) AS (
  SELECT b.binding_id,''::text,NULL::text,NULL::text,NULL::integer,b.value FROM ontology.occupation_bindings_v1(id) b
  UNION ALL
  SELECT t.binding_id,t.pointer||'/'||replace(replace(c.key,'~','~0'),'/','~1'),t.pointer,c.member_key,c.member_index,c.value
  FROM tree t CROSS JOIN LATERAL (
   SELECT key,key AS member_key,NULL::integer member_index,value FROM jsonb_each(CASE WHEN jsonb_typeof(t.value)='object' THEN t.value ELSE '{}' END)
   UNION ALL
   SELECT (ordinality-1)::text,NULL,(ordinality-1)::integer,value
   FROM jsonb_array_elements(CASE WHEN jsonb_typeof(t.value)='array' THEN t.value ELSE '[]' END) WITH ORDINALITY
  ) c
 ) SELECT * FROM tree
$$;

CREATE OR REPLACE FUNCTION ontology.occupation_graph_nodes_v1(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
WITH selected AS MATERIALIZED (SELECT p.* FROM ontology.occupation_proposal p WHERE p.proposal_id IN
 (SELECT proposal_id FROM ontology.occupation_selection WHERE release_id=id)), nodes AS (
 SELECT 'occupation-freeze/'||id node_id,ARRAY['occupationFreeze'] labels,
  to_jsonb(f)||jsonb_build_object('manifest_hash',m.manifest_hash,'name','고정된 직무 분류 — '||id) properties
 FROM ontology.occupation_freeze f JOIN ontology.occupation_membership m USING(release_id) WHERE f.release_id=id
 UNION ALL
 SELECT 'occupation-selection/'||id||'/'||s.entity_id,ARRAY['occupationReviewSelection'],
  to_jsonb(s)||jsonb_build_object('name',r.name||' — '||s.outcome)
 FROM ontology.occupation_selection s JOIN ontology.revision r ON r.revision_id=s.posting_revision_id WHERE s.release_id=id
 UNION ALL
 SELECT 'occupation-proposal/'||p.proposal_id,ARRAY['occupationProposal'],
  (to_jsonb(p)-ARRAY['document','source_binding','catalogue_binding'])||ontology.flat_properties(p.document,'proposal.')||
  jsonb_build_object('source_binding_id',ontology.occupation_binding_id_v1('SOURCE',p.source_binding),
   'catalogue_binding_id',ontology.occupation_binding_id_v1('CATALOGUE',p.catalogue_binding),
   'catalogue_binding_hash',ontology.hash(p.catalogue_binding),
   'proposal_null_fields',(SELECT coalesce(jsonb_agg(k ORDER BY k),'[]') FROM jsonb_each(p.document) x(k,v) WHERE v='null'),
   'record_null_fields',(SELECT coalesce(jsonb_agg(k ORDER BY k),'[]') FROM jsonb_each(to_jsonb(p)) x(k,v) WHERE v='null'),
   'name',(p.source_binding->>'title')||' — '||p.disposition)
 FROM selected p
 UNION ALL
 SELECT 'occupation-review/'||d.decision_id,ARRAY['occupationReview'],to_jsonb(d)||jsonb_build_object('name','직무 분류 검토 — '||d.reviewer)
 FROM ontology.occupation_decision d WHERE d.decision_id IN (SELECT decision_id FROM ontology.occupation_selection WHERE release_id=id)
 UNION ALL
 SELECT 'occupation-binding/'||b.binding_id,ARRAY['occupationBinding'],jsonb_build_object('binding_id',b.binding_id,
  'binding_kind',b.binding_kind,'binding_hash',ontology.hash(b.value),'name',CASE b.binding_kind WHEN 'SOURCE' THEN '검토 당시 업무 근거' ELSE '검토 당시 직무 분류표' END)
 FROM ontology.occupation_bindings_v1(id) b
 UNION ALL
 SELECT ontology.occupation_value_id_v1(v.binding_id,v.pointer),ARRAY['occupationBindingValue'],
  jsonb_build_object('binding_id',v.binding_id,'pointer',v.pointer,'value_kind',jsonb_typeof(v.value),
   'member_count',CASE jsonb_typeof(v.value) WHEN 'object' THEN (SELECT count(*) FROM jsonb_object_keys(v.value))
    WHEN 'array' THEN jsonb_array_length(v.value) END,
   'value',CASE WHEN jsonb_typeof(v.value) IN ('string','number','boolean') THEN v.value END,
   'name',left(coalesce(v.member_key,v.member_index::text,'binding')||': '||CASE WHEN jsonb_typeof(v.value) IN ('string','number','boolean')
    THEN v.value#>>'{}' ELSE jsonb_typeof(v.value) END,180)) FROM ontology.occupation_binding_values_v1(id) v
 UNION ALL
 SELECT 'primary-occupation/'||ontology.occupation_claim_id_v1(p.proposal_id,d.decision_id),ARRAY['assertion','primaryOccupationClaim'],
  jsonb_build_object('claim_id',ontology.occupation_claim_id_v1(p.proposal_id,d.decision_id),'proposal_id',p.proposal_id,
   'decision_id',d.decision_id,'posting_revision_id',p.posting_revision_id,'occupation_id',p.occupation_id,
   'occupation_revision_id',p.occupation_revision_id,'method',p.document->>'method','resolver_version',p.document->>'resolver_version',
   'assertion_kind',CASE p.document->>'method' WHEN 'MODEL_INFERRED' THEN 'MODEL_INFERRED' ELSE 'NORMALIZED' END,
   'confidence_state','UNASSESSED','review_status',CASE d.reviewer_kind WHEN 'human' THEN 'HUMAN_ACCEPTED' ELSE 'ASSISTANT_REVIEWED' END,
   'reviewer',d.reviewer,'reviewer_kind',d.reviewer_kind,'notes',d.notes,'created_at',p.created_at,'reviewed_at',d.reviewed_at,
   'valid_time_basis','POSTING_REVISION','name',(p.source_binding->>'title')||' → '||r.name)
 FROM ontology.occupation_selection s JOIN selected p USING(proposal_id) JOIN ontology.occupation_decision d USING(decision_id)
 JOIN ontology.revision r ON r.revision_id=p.occupation_revision_id WHERE s.release_id=id AND s.outcome='MATCHED'
 UNION ALL
 SELECT 'occupation-contract/'||c.version,ARRAY['occupationContract'],jsonb_build_object('schema_version',c.version,
  'schema_hash',c.content_hash,'name','직무 분류 제안 형식 v1') FROM ontology.occupation_contract c
 WHERE EXISTS(SELECT 1 FROM ontology.occupation_freeze WHERE release_id=id) AND c.version='hop-product-occupation-proposal-v1'
)
SELECT DISTINCT node_id,labels,jsonb_strip_nulls(properties) FROM nodes
$$;

CREATE OR REPLACE FUNCTION ontology.occupation_graph_edges_v1(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
WITH selected AS MATERIALIZED (SELECT p.* FROM ontology.occupation_proposal p WHERE p.proposal_id IN
 (SELECT proposal_id FROM ontology.occupation_selection WHERE release_id=id)),
 matched AS MATERIALIZED (SELECT * FROM ontology.primary_product_occupation WHERE release_id=id)
SELECT 'occupation-freeze/'||id,'HAS_OCCUPATION_SELECTION','occupation-selection/'||id||'/'||s.entity_id,'{}'::jsonb
 FROM ontology.occupation_selection s WHERE release_id=id
UNION ALL
SELECT 'occupation-freeze/'||id,'USES_CONTRACT','occupation-contract/hop-product-occupation-proposal-v1','{}'::jsonb
 FROM ontology.occupation_freeze WHERE release_id=id
UNION ALL
SELECT 'occupation-selection/'||id||'/'||s.entity_id,'HAS_SUBJECT','revision/'||s.posting_revision_id,'{}'::jsonb
 FROM ontology.occupation_selection s WHERE release_id=id
UNION ALL
SELECT 'occupation-selection/'||id||'/'||s.entity_id,'SELECTS_PROPOSAL','occupation-proposal/'||s.proposal_id,'{}'::jsonb
 FROM ontology.occupation_selection s WHERE release_id=id AND proposal_id IS NOT NULL
UNION ALL
SELECT 'occupation-selection/'||id||'/'||s.entity_id,'REVIEWED_BY','occupation-review/'||s.decision_id,'{}'::jsonb
 FROM ontology.occupation_selection s WHERE release_id=id AND decision_id IS NOT NULL
UNION ALL
SELECT 'occupation-review/'||d.decision_id,'REVIEWS_PROPOSAL','occupation-proposal/'||d.proposal_id,'{}'::jsonb
 FROM ontology.occupation_decision d WHERE decision_id IN (SELECT decision_id FROM ontology.occupation_selection WHERE release_id=id)
UNION ALL
SELECT 'occupation-proposal/'||p.proposal_id,'USES_SOURCE_BINDING','occupation-binding/'||ontology.occupation_binding_id_v1('SOURCE',p.source_binding),'{}'::jsonb FROM selected p
UNION ALL
SELECT 'occupation-proposal/'||p.proposal_id,'USES_CATALOGUE_BINDING','occupation-binding/'||ontology.occupation_binding_id_v1('CATALOGUE',p.catalogue_binding),'{}'::jsonb FROM selected p
UNION ALL
SELECT 'occupation-proposal/'||p.proposal_id,'USES_CONTRACT','occupation-contract/'||(p.document->>'schema_version'),'{}'::jsonb FROM selected p
UNION ALL
SELECT 'occupation-binding/'||b.binding_id,'HAS_BINDING_VALUE',ontology.occupation_value_id_v1(b.binding_id,''),'{}'::jsonb FROM ontology.occupation_bindings_v1(id) b
UNION ALL
SELECT ontology.occupation_value_id_v1(v.binding_id,v.parent_pointer),'BINDING_MEMBER',ontology.occupation_value_id_v1(v.binding_id,v.pointer),
 jsonb_strip_nulls(jsonb_build_object('member_key',v.member_key,'member_index',v.member_index))
 FROM ontology.occupation_binding_values_v1(id) v WHERE parent_pointer IS NOT NULL
UNION ALL
SELECT 'primary-occupation/'||ontology.occupation_claim_id_v1(m.proposal_id,m.decision_id),'HAS_SUBJECT','revision/'||m.posting_revision_id,'{}'::jsonb FROM matched m
UNION ALL
SELECT 'primary-occupation/'||ontology.occupation_claim_id_v1(m.proposal_id,m.decision_id),'TARGETS','entity/'||m.occupation_id,'{}'::jsonb FROM matched m
UNION ALL
SELECT 'primary-occupation/'||ontology.occupation_claim_id_v1(m.proposal_id,m.decision_id),'SELECTS_REVISION','revision/'||m.occupation_revision_id,'{}'::jsonb FROM matched m
UNION ALL
SELECT 'primary-occupation/'||ontology.occupation_claim_id_v1(m.proposal_id,m.decision_id),'DERIVED_FROM','occupation-proposal/'||m.proposal_id,'{}'::jsonb FROM matched m
UNION ALL
SELECT 'primary-occupation/'||ontology.occupation_claim_id_v1(m.proposal_id,m.decision_id),'REVIEWED_BY','occupation-review/'||m.decision_id,'{}'::jsonb FROM matched m
UNION ALL
SELECT 'primary-occupation/'||ontology.occupation_claim_id_v1(m.proposal_id,m.decision_id),'EVIDENCED_BY','evidence/'||e,'{}'::jsonb
 FROM matched m CROSS JOIN LATERAL jsonb_array_elements_text(m.evidence_ids) e
UNION ALL
SELECT 'revision/'||m.posting_revision_id,'FOR_OCCUPATION','entity/'||m.occupation_id,
 jsonb_build_object('source_assertion_ids',jsonb_build_array(ontology.occupation_claim_id_v1(m.proposal_id,m.decision_id)),
  'methodology_version','product-occupation-graph-v1') FROM matched m
$$;

CREATE OR REPLACE FUNCTION ontology.occupation_graph_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('occupation_membership',m.manifest,'occupation_membership_hash',m.manifest_hash,
  'occupation_contract_hash',(SELECT content_hash FROM ontology.occupation_contract WHERE version='hop-product-occupation-proposal-v1'))
 FROM ontology.occupation_membership m WHERE release_id=id
$$;
CREATE OR REPLACE FUNCTION ontology.verify_occupation_graph_v1(id text) RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE occupation_labels text[]:=ARRAY['occupationFreeze','occupationReviewSelection','occupationProposal','occupationReview',
 'occupationBinding','occupationBindingValue','primaryOccupationClaim','occupationContract']; BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.occupation_freeze WHERE release_id=id) THEN
  IF EXISTS(SELECT 1 FROM ontology.graph_node n WHERE release_id=id AND n.labels && occupation_labels)
  THEN RAISE EXCEPTION 'OCCUPATION_GRAPH_WITHOUT_FREEZE'; END IF;
  RETURN;
 END IF;
 PERFORM ontology.verify_occupations_v1(id);
 IF (SELECT manifest FROM ontology.corpus_release WHERE release_id=id) IS NULL THEN RETURN; END IF;
 IF NOT ((SELECT manifest FROM ontology.corpus_release WHERE release_id=id) @> ontology.occupation_graph_manifest_v1(id))
 THEN RAISE EXCEPTION 'OCCUPATION_GRAPH_MANIFEST_MISMATCH'; END IF;
 IF EXISTS((SELECT node_id,n.labels,properties FROM ontology.graph_node n WHERE release_id=id AND n.labels && occupation_labels
   EXCEPT SELECT * FROM ontology.occupation_graph_nodes_v1(id)) UNION ALL
  (SELECT * FROM ontology.occupation_graph_nodes_v1(id) EXCEPT
   SELECT node_id,n.labels,properties FROM ontology.graph_node n WHERE release_id=id AND n.labels && occupation_labels))
 THEN RAISE EXCEPTION 'OCCUPATION_GRAPH_NODE_MISMATCH'; END IF;
 IF EXISTS((SELECT subject_id,predicate,object_id,properties FROM ontology.graph_edge WHERE release_id=id AND
   (subject_id LIKE 'occupation-%' OR subject_id LIKE 'primary-occupation/%' OR predicate='FOR_OCCUPATION')
   EXCEPT SELECT * FROM ontology.occupation_graph_edges_v1(id)) UNION ALL
  (SELECT * FROM ontology.occupation_graph_edges_v1(id) EXCEPT
   SELECT subject_id,predicate,object_id,properties FROM ontology.graph_edge WHERE release_id=id))
 THEN RAISE EXCEPTION 'OCCUPATION_GRAPH_EDGE_MISMATCH'; END IF;
END $$;
COMMIT;
