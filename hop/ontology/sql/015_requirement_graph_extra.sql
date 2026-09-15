-- Additive typed requirement graph helpers; install before the 016 wrappers.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.typed_claim_id_v1(n text,d bigint) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT ontology.hash(jsonb_build_array('typed-requirement-claim-v1',n,d))
$$;
CREATE OR REPLACE FUNCTION ontology.typed_condition_id_v1(c jsonb) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT ontology.hash(jsonb_build_array('typed-condition-v1',c))
$$;
CREATE OR REPLACE FUNCTION ontology.typed_condition_properties_v1(c jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT jsonb_strip_nulls(c)||jsonb_build_object('condition_id',ontology.typed_condition_id_v1(c),
  'condition_fields',(SELECT jsonb_agg(k ORDER BY k COLLATE "C") FROM jsonb_object_keys(c) k),
  'null_fields',coalesce((SELECT jsonb_agg(k ORDER BY k COLLATE "C") FROM jsonb_each(c) e(k,v) WHERE v='null'),'[]'),
  'name',CASE c->>'kind' WHEN 'SKILL' THEN '기술 조건' WHEN 'LANGUAGE' THEN '언어 조건' WHEN 'CREDENTIAL' THEN '자격 조건'
   WHEN 'EDUCATION' THEN '학력 조건' WHEN 'EXPERIENCE' THEN '경력 조건' WHEN 'PROJECT' THEN '프로젝트 조건'
   WHEN 'LOCATION' THEN '근무 지역 조건' WHEN 'ELIGIBILITY' THEN '지원 자격 조건' WHEN 'AVAILABILITY' THEN '근무 일정 조건' ELSE '미해결 조건' END)
$$;
CREATE OR REPLACE VIEW ontology.typed_requirement AS
SELECT s.release_id,s.source_claim_id,s.node_index,n.normalization_id,d.decision_id,
 ontology.typed_claim_id_v1(n.normalization_id,d.decision_id) AS claim_id,
 n.source_binding->>'posting_revision_id' AS posting_revision_id,n.condition,
 n.condition->>'kind' AS requirement_kind,
 CASE WHEN n.condition->>'kind' IN ('LOCATION','ELIGIBILITY','AVAILABILITY') THEN 'POSTING_FILTER' ELSE 'CAPABILITY' END AS requirement_scope,
 n.document->>'necessity' AS necessity,n.document->>'polarity' AS polarity,n.requirement_key,n.key_algorithm,
 CASE d.reviewer_kind WHEN 'human' THEN 'HUMAN_ACCEPTED' ELSE 'ASSISTANT_REVIEWED' END AS review_status,
 d.reviewer,d.reviewer_kind,d.notes,n.created_at,d.created_at AS reviewed_at,
 n.source_binding->>'source_text' AS source_text,n.source_binding->>'applicability' AS applicability
FROM ontology.requirement_selection s JOIN ontology.requirement_normalization n USING(normalization_id)
JOIN ontology.requirement_decision d ON d.decision_id=s.decision_id WHERE s.outcome='REVIEWED';

CREATE OR REPLACE FUNCTION ontology.requirement_graph_nodes_v1(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
WITH selected AS MATERIALIZED (SELECT n.* FROM ontology.requirement_selection s JOIN ontology.requirement_normalization n USING(normalization_id) WHERE s.release_id=id),
nodes AS (
 SELECT 'requirement-selection/'||id||'/'||s.source_claim_id||'/'||s.node_index AS node_id,ARRAY['requirementReviewSelection'] AS labels,
  jsonb_build_object('release_id',id,'source_claim_id',s.source_claim_id,'source_node_index',s.node_index,
   'normalization_id',s.normalization_id,'decision_id',s.decision_id,'outcome',s.outcome,
   'typed_claim_id',CASE WHEN s.outcome='REVIEWED' THEN ontology.typed_claim_id_v1(s.normalization_id,s.decision_id) END,
   'reviewer',d.reviewer,'reviewer_kind',d.reviewer_kind,'notes',d.notes,'decision',d.decision,'reviewed_at',d.created_at,
   'name',a.source_text||' — '||s.outcome) AS properties
 FROM ontology.requirement_selection s JOIN ontology.requirement_atom a USING(release_id,source_claim_id,node_index)
 LEFT JOIN ontology.requirement_decision d ON d.decision_id=s.decision_id WHERE s.release_id=id
 UNION ALL
 SELECT 'requirement-normalization/'||n.normalization_id,ARRAY['requirementNormalization'],
  jsonb_build_object('normalization_id',n.normalization_id,'source_claim_id',n.source_claim_id,'source_node_index',n.node_index,
   'parent_id',n.parent_id,'schema_version',n.document->>'schema_version','actor',n.document->>'actor',
   'reason',n.document->>'reason','resolver_version',n.document->>'resolver_version','created_at',n.created_at,
   'necessity',n.document->>'necessity','polarity',n.document->>'polarity','requirement_key',n.requirement_key,'key_algorithm',n.key_algorithm,
   'source_binding_hash',ontology.hash(n.source_binding),'target_bindings_hash',ontology.hash(n.target_bindings),
   'name',n.source_binding->>'source_text') FROM selected n
 UNION ALL
 SELECT 'typed-condition/'||ontology.typed_condition_id_v1(n.condition),
  ARRAY[CASE WHEN n.condition->>'kind'='UNRESOLVED' THEN 'unresolvedCondition' ELSE 'typedCondition' END],
  ontology.typed_condition_properties_v1(n.condition) FROM selected n
 UNION ALL
 SELECT 'typed-requirement/'||t.claim_id,ARRAY['assertion','normalizedRequirementClaim'],
  jsonb_build_object('claim_id',t.claim_id,'normalization_id',t.normalization_id,'source_claim_id',t.source_claim_id,'source_node_index',t.node_index,
   'posting_revision_id',t.posting_revision_id,'requirement_kind',t.requirement_kind,'requirement_scope',t.requirement_scope,
   'necessity',t.necessity,'polarity',t.polarity,'requirement_key',t.requirement_key,'key_algorithm',t.key_algorithm,
   'assertion_kind','NORMALIZED','confidence_state','UNASSESSED','review_status',t.review_status,
   'decision_id',t.decision_id,'reviewer',t.reviewer,'reviewer_kind',t.reviewer_kind,'notes',t.notes,
   'created_at',t.created_at,'reviewed_at',t.reviewed_at,'applicability',t.applicability,
   'valid_time_basis','POSTING_REVISION','name',t.source_text,'text',t.source_text)
 FROM ontology.typed_requirement t WHERE t.release_id=id
 UNION ALL
 SELECT 'requirement-binding/'||ontology.hash(jsonb_build_array(n.normalization_id,b)),ARRAY['requirementTargetBinding'],
  b||jsonb_build_object('normalization_id',n.normalization_id,'target_subkind',r.payload->>'kind','name',r.name||' — '||(b->>'role'))
 FROM selected n CROSS JOIN LATERAL jsonb_array_elements(n.target_bindings) b JOIN ontology.revision r ON r.revision_id=b->>'revision_id'
 UNION ALL
 SELECT 'requirement-contract/'||c.version,ARRAY['requirementContract'],
  jsonb_build_object('schema_version',c.version,'schema_hash',c.content_hash,'name',c.version)
 FROM ontology.requirement_contract c WHERE EXISTS(SELECT 1 FROM selected n WHERE n.document->>'schema_version'=c.version)
)
SELECT DISTINCT node_id,labels,jsonb_strip_nulls(properties) FROM nodes
$$;

CREATE OR REPLACE FUNCTION ontology.requirement_graph_edges_v1(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
WITH selected AS MATERIALIZED (SELECT n.* FROM ontology.requirement_selection s JOIN ontology.requirement_normalization n USING(normalization_id) WHERE s.release_id=id),
typed AS MATERIALIZED (SELECT * FROM ontology.typed_requirement WHERE release_id=id)
SELECT 'requirement-selection/'||id||'/'||s.source_claim_id||'/'||s.node_index,'FOR_SOURCE_ATOM',
 CASE WHEN s.node_index=-1 THEN 'claim/'||s.source_claim_id ELSE 'condition/'||s.source_claim_id||'/'||s.node_index END,'{}'::jsonb
 FROM ontology.requirement_selection s WHERE s.release_id=id
UNION ALL
SELECT 'requirement-selection/'||id||'/'||s.source_claim_id||'/'||s.node_index,'SELECTS_NORMALIZATION','requirement-normalization/'||s.normalization_id,'{}'::jsonb
 FROM ontology.requirement_selection s WHERE s.release_id=id AND s.normalization_id IS NOT NULL
UNION ALL
SELECT 'requirement-normalization/'||n.normalization_id,'FOR_SOURCE_ATOM',
 CASE WHEN n.node_index=-1 THEN 'claim/'||n.source_claim_id ELSE 'condition/'||n.source_claim_id||'/'||n.node_index END,'{}'::jsonb FROM selected n
UNION ALL
SELECT 'requirement-normalization/'||n.normalization_id,'HAS_PROPOSED_CONDITION','typed-condition/'||ontology.typed_condition_id_v1(n.condition),'{}'::jsonb FROM selected n
UNION ALL
SELECT 'requirement-normalization/'||n.normalization_id,'USES_CONTRACT','requirement-contract/'||(n.document->>'schema_version'),'{}'::jsonb FROM selected n
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'DERIVED_FROM','requirement-normalization/'||t.normalization_id,'{}'::jsonb FROM typed t
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'FOR_SOURCE_GROUP','claim/'||t.source_claim_id,'{}'::jsonb FROM typed t
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'FOR_SOURCE_ATOM',
 CASE WHEN t.node_index=-1 THEN 'claim/'||t.source_claim_id ELSE 'condition/'||t.source_claim_id||'/'||t.node_index END,'{}'::jsonb FROM typed t
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'HAS_SUBJECT','revision/'||t.posting_revision_id,'{}'::jsonb FROM typed t
UNION ALL
SELECT 'revision/'||t.posting_revision_id,'HAS_TYPED_REQUIREMENT','typed-requirement/'||t.claim_id,'{}'::jsonb FROM typed t
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'REVIEWED_BY','requirement-selection/'||id||'/'||t.source_claim_id||'/'||t.node_index,'{}'::jsonb FROM typed t
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'APPLIES_TO','position/'||p.position_id,'{}'::jsonb FROM typed t JOIN ontology.claim_position p ON p.claim_id=t.source_claim_id
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'NORMALIZED_CONDITION','typed-condition/'||ontology.typed_condition_id_v1(t.condition),'{}'::jsonb
 FROM typed t WHERE t.requirement_kind NOT IN ('SKILL','LANGUAGE','CREDENTIAL')
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'TARGETS','entity/'||(t.condition->>'target_id'),'{}'::jsonb
 FROM typed t WHERE t.requirement_kind IN ('SKILL','LANGUAGE','CREDENTIAL')
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'EVIDENCED_BY','evidence/'||(e->'span'->>'evidence_id'),jsonb_build_object('part_index',(e->>'part_index')::integer)
 FROM typed t JOIN selected n USING(normalization_id) CROSS JOIN LATERAL jsonb_array_elements(n.source_binding->'evidence') e
UNION ALL
SELECT 'requirement-normalization/'||n.normalization_id,'USES_TARGET_BINDING','requirement-binding/'||ontology.hash(jsonb_build_array(n.normalization_id,b)),'{}'::jsonb
 FROM selected n CROSS JOIN LATERAL jsonb_array_elements(n.target_bindings) b
UNION ALL
SELECT 'typed-requirement/'||t.claim_id,'USES_TARGET_BINDING','requirement-binding/'||ontology.hash(jsonb_build_array(n.normalization_id,b)),'{}'::jsonb
 FROM typed t JOIN selected n USING(normalization_id) CROSS JOIN LATERAL jsonb_array_elements(n.target_bindings) b
UNION ALL
SELECT 'requirement-binding/'||ontology.hash(jsonb_build_array(n.normalization_id,b)),'SELECTS_REVISION','revision/'||(b->>'revision_id'),'{}'::jsonb
 FROM selected n CROSS JOIN LATERAL jsonb_array_elements(n.target_bindings) b
 JOIN ontology.release_revision m ON m.release_id=id AND m.entity_id=b->>'entity_id' AND m.revision_id=b->>'revision_id'
$$;

CREATE OR REPLACE FUNCTION ontology.requirement_graph_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','typed-requirement-graph-v1',
  'atoms',(SELECT count(*) FROM ontology.requirement_selection WHERE release_id=id),
  'reviewed_claims',(SELECT count(*) FROM ontology.typed_requirement WHERE release_id=id),
  'atom_hash',ontology.hash(coalesce((SELECT jsonb_agg(jsonb_build_array(s.source_claim_id,s.node_index,s.normalization_id,s.decision_id,s.outcome,
   CASE WHEN s.outcome='REVIEWED' THEN ontology.typed_claim_id_v1(s.normalization_id,s.decision_id) END) ORDER BY s.source_claim_id,s.node_index)
   FROM ontology.requirement_selection s WHERE s.release_id=id),'[]')))
$$;
COMMIT;
