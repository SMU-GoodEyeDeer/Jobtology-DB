-- Generated base-compatible typed requirement graph projection.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.graph_node_candidates_base_v1(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
WITH rev AS MATERIALIZED (SELECT v.* FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id=id),
 included_claim AS MATERIALIZED (SELECT c.* FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id) WHERE m.release_id=id),
included_position AS MATERIALIZED (SELECT p.* FROM ontology.release_position m JOIN ontology.position_claim p USING(position_id) WHERE m.release_id=id),
 included_rule AS MATERIALIZED (SELECT * FROM ontology.guarded_rule WHERE release_id=id),
 evidence AS MATERIALIZED (
  SELECT e.* FROM ontology.evidence_span e WHERE e.evidence_id IN (
   SELECT ce.evidence_id FROM ontology.claim_evidence ce JOIN included_claim c USING(claim_id)
   UNION SELECT ce.evidence_id FROM ontology.condition_evidence ce JOIN included_claim c USING(claim_id)
   UNION SELECT pe.evidence_id FROM ontology.position_evidence pe JOIN included_position p USING(position_id)
   UNION SELECT evidence_id FROM ontology.rule_evidence WHERE release_id=id)
), nodes AS (
 SELECT 'entity/'||e.entity_id AS node_id,ARRAY['ontologyEntity',e.kind] AS labels,
  jsonb_build_object('entity_id',e.entity_id,'kind',e.kind,'code',e.code,'scheme_id',e.scheme_id) AS properties
 FROM ontology.entity e JOIN rev v USING(entity_id)
 UNION ALL
 SELECT 'observation/'||s.observation_state_id,ARRAY['entityObservationState'],
  ontology.flat_properties(to_jsonb(s)||jsonb_build_object('name',v.name||' — '||s.serving_state))
 FROM ontology.entity_observation_state s JOIN ontology.revision v ON v.revision_id=s.selected_revision_id WHERE s.release_id=id
 UNION ALL
 SELECT 'revision/'||v.revision_id,ARRAY['entityRevision',v.kind||'Revision'],
  ontology.flat_properties((v.payload-ARRAY['eligibility_text','preference_text','selection_text','disqualification_text','duties_text','description_text'])||
   jsonb_build_object('revision_id',v.revision_id,'entity_id',v.entity_id,'kind',v.kind,'payload_hash',v.payload_hash,'schema_version',v.schema_version)) FROM rev v
 UNION ALL
 SELECT 'source/'||p.source_id,ARRAY['ontologySource'],jsonb_build_object('source_id',p.source_id,'name',p.source_id)
 FROM ontology.source_pin p WHERE release_id=id
 UNION ALL
 SELECT 'posting-input/'||d.bundle_id,ARRAY['postingInput'],jsonb_build_object('bundle_id',d.bundle_id,
  'posting_id',b.posting_id,'job_run_id',b.job_run_id,'source_hash',b.source_hash,'contract',b.manifest->>'contract',
  'name','Documents for '||b.posting_id,'document_count',jsonb_array_length(b.manifest->'documents'))
 FROM ontology.document_input d JOIN enrichment.input_bundle b USING(bundle_id) WHERE d.release_id=id
 UNION ALL
 SELECT ontology.graph_attachment_id(d),ARRAY['sourceAttachment'],jsonb_strip_nulls(jsonb_build_object(
  'bundle_id',d.bundle_id,'artifact_id',d.artifact_id,'file_id',d.descriptor->>'file_id','file_ordinal',d.file_ordinal,
  'name',d.descriptor->>'name','role',d.descriptor->>'role','source_url',a.source_url,
  'raw_sha256',d.binding->>'raw_hash','parsed_hash',d.binding->>'parsed_hash','text_hash',d.descriptor->>'text_hash',
  'parser_version',d.descriptor->>'parser_version','structure_layout_hash',d.binding->>'structure_layout_hash',
  'structure_issue_count',jsonb_array_length(coalesce(d.descriptor->'structure_issues','[]'))))
 FROM ontology.artifact_document d JOIN attachment.attempt t USING(attempt_id)
 JOIN attachment.document a ON a.document_id=t.document_id WHERE d.release_id=id
 UNION ALL
 SELECT ontology.graph_attachment_id(d)||'/observation/'||x.ordinality,ARRAY['documentObservation'],
  ontology.flat_properties(x.value||jsonb_build_object('ordinal',x.ordinality,'name',x.value->>'kind'))
 FROM ontology.artifact_document d CROSS JOIN LATERAL jsonb_array_elements(d.descriptor->'structure_issues') WITH ORDINALITY x
 WHERE d.release_id=id
 UNION ALL
 SELECT ontology.graph_attachment_id(d)||'/section/'||s.section_index,ARRAY['documentSection'],
  ontology.flat_properties((s.source_locator-'content_hash')||jsonb_build_object('section_index',s.section_index,
   'source_content_hash',s.source_locator->>'content_hash',
   'original_start',s.original_start,'original_end',s.original_end,'normalized_start',s.normalized_start,
   'normalized_end',s.normalized_end,'offset_unit','unicode-codepoint-zero-half-open',
   'name',coalesce(s.source_locator->>'locator','Section '||s.section_index)))
 FROM ontology.document_section s JOIN ontology.artifact_document d USING(release_id,artifact_id) WHERE s.release_id=id
 UNION ALL
 SELECT ontology.graph_document_part_id(d,'table',x),ARRAY['documentTable'],
  x||jsonb_build_object('name','Table '||(x->>'table_no')||' in '||(x->>'entry_name'))
 FROM ontology.artifact_document d CROSS JOIN LATERAL jsonb_array_elements(d.descriptor->'tables') x WHERE d.release_id=id
 UNION ALL
 SELECT ontology.graph_document_part_id(d,'cell',x),ARRAY['documentCell'],
  x||jsonb_build_object('name','Row '||(x->>'row_no')||', column '||(x->>'col_no'))
 FROM ontology.artifact_document d CROSS JOIN LATERAL jsonb_array_elements(d.descriptor->'cells') x WHERE d.release_id=id
 UNION ALL
 SELECT DISTINCT 'snapshot/'||p.source_id||'/'||d.raw_sha256,ARRAY['sourceSnapshot'],
  jsonb_build_object('source_id',p.source_id,'sha256',d.raw_sha256,'byte_length',d.byte_length,'encoding',d.encoding,
   'name',p.source_id||' '||left(d.raw_sha256,12))
 FROM ontology.release_source_run p JOIN ingestion.document d ON d.run_id=p.run_id AND d.selected WHERE p.release_id=id
 UNION ALL
 SELECT ontology.graph_record_id(i),ARRAY['sourceRecordEvidence'],ontology.flat_properties(jsonb_build_object(
  'source_id',i.source_id,'source_record_id',i.source_record_id,'locator',i.locator,'raw_sha256',i.raw_sha256,
  'normalized_hash',i.normalized_hash,'name',i.source_id||' '||i.source_record_id,'field_lineage',i.field_lineage))
 FROM ontology.input_record i WHERE release_id=id
 UNION ALL
 SELECT 'source-assertion/'||r.relation_id,ARRAY['assertion','sourceAssertion'],ontology.flat_properties(jsonb_build_object(
  'assertion_id',r.relation_id,'predicate',r.predicate,'subject_id',r.subject_id,'object_id',r.object_id,
  'assertion_kind',r.assertion_kind,'acceptance_policy',r.acceptance_policy,'qualifiers',r.qualifiers,'name',r.predicate))
 FROM ontology.source_relation r WHERE EXISTS(SELECT 1 FROM ontology.release_relation m WHERE m.release_id=id AND m.relation_id=r.relation_id)
 UNION ALL
 SELECT 'position/'||p.position_id,ARRAY['assertion','positionClaim'],jsonb_build_object('position_id',p.position_id,
  'posting_revision_id',p.posting_revision_id,'local_id',p.local_id,'name',p.name,'assertion_kind','REVIEWED_EXTRACTION') FROM included_position p
 UNION ALL
 SELECT 'claim/'||c.claim_id,ARRAY['assertion',CASE c.kind WHEN 'DUTY' THEN 'dutyClaim' ELSE 'requirementClaim' END],
  jsonb_build_object('claim_id',c.claim_id,'posting_revision_id',c.posting_revision_id,'kind',c.kind,'ordinal',c.ordinal,
   'text',c.text,'name',c.text,'category',c.category,'condition_kind',c.condition_kind,'logic',c.logic,'applicability',c.applicability,
   'interpretation_state',c.interpretation_state,'assertion_kind',c.assertion_kind,'text_parts',c.payload->'text_parts') FROM included_claim c
 UNION ALL
 SELECT 'condition/'||n.claim_id||'/'||n.node_index,ARRAY['conditionExpression'],jsonb_build_object('claim_id',n.claim_id,
  'node_index',n.node_index,'operator',n.operator,'text',n.text,'parts',n.parts,'name',coalesce(nullif(n.text,''),n.operator))
 FROM ontology.condition_node n JOIN included_claim c USING(claim_id)
 UNION ALL
 SELECT 'rule/'||r.rule_id,ARRAY['assertion','guardedRule'],jsonb_build_object('rule_id',r.rule_id,
  'claim_id',r.claim_id,'interpretation_id',r.interpretation_id,'local_id',r.local_id,'ordinal',r.ordinal,
  'action',r.action,'statement_parts',r.statement_parts,'schema_version',r.schema_version,
  'guard_kind',CASE WHEN r.guard='null' THEN 'UNCONDITIONAL' ELSE 'PREDICATE' END,
  'applicability',r.applicability,'position_ids',r.position_ids,'assertion_kind','REVIEWED_INTERPRETATION',
  'name',(SELECT string_agg(x,' ') FROM jsonb_array_elements_text(r.statement_parts) x)) FROM included_rule r
 UNION ALL
 SELECT 'rule-predicate/'||n.rule_id||n.node_path,ARRAY['rulePredicate'],jsonb_build_object('rule_id',n.rule_id,
  'node_path',n.node_path,'operator',n.operator,'parts',n.parts,'ordinal',n.ordinal,
  'name',coalesce(nullif((SELECT string_agg(x,' ') FROM jsonb_array_elements_text(n.parts) x),''),n.operator))
 FROM ontology.rule_predicate n WHERE n.release_id=id
 UNION ALL
 SELECT DISTINCT 'rule-contract/'||c.schema_version,ARRAY['ruleContract'],jsonb_build_object('schema_version',c.schema_version,
  'schema_hash',c.content_hash,'description',c.output_schema->>'description','name',c.schema_version)
 FROM enrichment.rule_contract c JOIN included_rule r USING(schema_version)
 UNION ALL
 SELECT 'rule-review/'||id||'/'||s.interpretation_id,ARRAY['ruleReviewSelection'],ontology.flat_properties(jsonb_build_object(
  'release_id',id,'interpretation_id',s.interpretation_id,'entity_id',s.entity_id,'requirement_index',s.requirement_index,
  'decision_id',s.decision_id,'outcome',s.outcome,'review',s.review,'name',s.outcome,
  'actor',s.interpretation->>'actor','reason',s.interpretation->>'reason','source_hash',s.interpretation->>'source_hash',
  'extraction_hash',s.interpretation->>'extraction_hash','extraction_revision_id',s.interpretation->>'revision_id'))
 FROM ontology.rule_selection s WHERE s.release_id=id
 UNION ALL
 SELECT 'evidence/'||e.evidence_id,ARRAY['evidenceSpan'],jsonb_build_object('evidence_id',e.evidence_id,'artifact_id',e.artifact_id,
  'start_offset',e.start_offset,'end_offset',e.end_offset,'excerpt',e.excerpt,'excerpt_sha256',e.excerpt_sha256,
  'offset_unit',e.offset_unit,'locator_version',e.locator_version,'name',e.excerpt) FROM evidence e
 UNION ALL
 SELECT 'artifact/'||a.artifact_id,ARRAY['textArtifact'],jsonb_build_object('artifact_id',a.artifact_id,'posting_id',a.posting_id,
  'source_field',a.source_field,'input_sha256',a.input_sha256,'text_sha256',a.text_sha256,'normalization_version',a.normalization_version,
  'name',a.source_field) FROM ontology.text_artifact a WHERE EXISTS(SELECT 1 FROM evidence e WHERE e.artifact_id=a.artifact_id)
 UNION ALL
 SELECT 'mapping/'||c.mapping_id,ARRAY['assertion','competencyMappingClaim'],jsonb_build_object('mapping_id',c.mapping_id,
  'predicate',c.predicate,'assertion_kind',c.assertion_kind,'reason',c.reason,'name',c.reason,'duty_claim_id',c.duty_claim_id,
  'target_revision_id',c.target_revision_id) FROM ontology.release_mapping m JOIN ontology.mapping_claim c USING(mapping_id) WHERE m.release_id=id
 UNION ALL
 SELECT 'selection/'||id||'/'||p.entity_id,ARRAY['postingReviewSelection'],ontology.flat_properties(jsonb_build_object(
  'release_id',id,'entity_id',p.entity_id,'outcome',p.outcome,'duties_status',p.extraction->>'duties_status',
  'source_hash',p.source_hash,'extraction_revision_id',p.extraction_revision_id,'decision_id',p.decision_id,
  'review',p.provenance->'review','name',p.outcome)) FROM ontology.posting_selection p WHERE p.release_id=id
 UNION ALL
 SELECT 'link-review/'||id||'/'||s.candidate_id,ARRAY['linkReviewSelection'],ontology.flat_properties(jsonb_build_object(
  'release_id',id,'candidate_id',s.candidate_id,'decision_id',s.decision_id,'outcome',s.outcome,'review',s.review,'name',s.outcome))
 FROM ontology.link_selection s WHERE s.release_id=id
)
SELECT DISTINCT node_id,labels,jsonb_strip_nulls(properties) FROM nodes
$$;

CREATE OR REPLACE FUNCTION ontology.graph_edge_candidates_base_v1(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
WITH rev AS MATERIALIZED (SELECT * FROM ontology.release_revision WHERE release_id=id),
 claims AS MATERIALIZED (SELECT c.* FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id) WHERE m.release_id=id),
 positions AS MATERIALIZED (SELECT p.* FROM ontology.release_position m JOIN ontology.position_claim p USING(position_id) WHERE m.release_id=id)
SELECT 'entity/'||m.entity_id,'HAS_REVISION','revision/'||m.revision_id,'{}'::jsonb FROM rev m
UNION ALL
SELECT 'observation/'||s.observation_state_id,'FOR_ENTITY','entity/'||s.entity_id,'{}'::jsonb FROM ontology.entity_observation_state s WHERE release_id=id
UNION ALL
SELECT 'observation/'||s.observation_state_id,'SELECTS_REVISION','revision/'||s.selected_revision_id,'{}'::jsonb FROM ontology.entity_observation_state s WHERE release_id=id
UNION ALL
SELECT 'revision/'||v.revision_id,'DERIVED_FROM',ontology.graph_record_id(i),jsonb_build_object('fields',s.fields)
FROM ontology.revision_support s JOIN rev v USING(entity_id) JOIN ontology.input_record i ON i.release_id=s.release_id AND i.record_id=s.record_id WHERE s.release_id=id
UNION ALL
SELECT ontology.graph_record_id(i),'IN_SNAPSHOT','snapshot/'||i.source_id||'/'||i.raw_sha256,'{}'::jsonb FROM ontology.input_record i WHERE i.release_id=id
UNION ALL
SELECT DISTINCT 'snapshot/'||p.source_id||'/'||d.raw_sha256,'FROM_SOURCE','source/'||p.source_id,'{}'::jsonb
FROM ontology.release_source_run p JOIN ingestion.document d ON d.run_id=p.run_id AND d.selected WHERE p.release_id=id
UNION ALL
SELECT 'source-assertion/'||m.relation_id,'EVIDENCED_BY',ontology.graph_record_id(i),jsonb_build_object('fields',m.source_fields)
FROM ontology.release_relation m JOIN ontology.input_record i ON i.release_id=m.release_id AND i.record_id=m.record_id WHERE m.release_id=id
UNION ALL
SELECT DISTINCT 'source-assertion/'||r.relation_id,'SUBJECT','entity/'||r.subject_id,'{}'::jsonb FROM ontology.release_relation m JOIN ontology.source_relation r USING(relation_id) WHERE m.release_id=id
UNION ALL
SELECT DISTINCT 'source-assertion/'||r.relation_id,'OBJECT','entity/'||r.object_id,'{}'::jsonb FROM ontology.release_relation m JOIN ontology.source_relation r USING(relation_id) WHERE m.release_id=id
UNION ALL
SELECT DISTINCT 'revision/'||v.revision_id,r.predicate,'entity/'||r.object_id,
 jsonb_build_object('assertion_id',r.relation_id)||ontology.flat_properties(r.qualifiers)
FROM ontology.release_relation m JOIN ontology.source_relation r USING(relation_id) JOIN rev v ON v.entity_id=r.subject_id WHERE m.release_id=id
UNION ALL
SELECT 'revision/'||p.posting_revision_id,'HAS_POSITION','position/'||p.position_id,'{}'::jsonb FROM positions p
UNION ALL
SELECT 'revision/'||c.posting_revision_id,CASE c.kind WHEN 'DUTY' THEN 'HAS_DUTY' ELSE 'HAS_REQUIREMENT' END,'claim/'||c.claim_id,'{}'::jsonb FROM claims c
UNION ALL
SELECT 'claim/'||cp.claim_id,'APPLIES_TO','position/'||cp.position_id,'{}'::jsonb FROM ontology.claim_position cp JOIN claims c USING(claim_id)
UNION ALL
SELECT 'claim/'||c.claim_id,'EVIDENCED_BY','evidence/'||ce.evidence_id,jsonb_build_object('part_index',ce.part_index) FROM ontology.claim_evidence ce JOIN claims c USING(claim_id)
UNION ALL
SELECT 'position/'||p.position_id,'EVIDENCED_BY','evidence/'||pe.evidence_id,'{}'::jsonb FROM ontology.position_evidence pe JOIN positions p USING(position_id)
UNION ALL
SELECT 'claim/'||c.claim_id,'HAS_EXPRESSION','condition/'||c.claim_id||'/0','{}'::jsonb FROM claims c WHERE EXISTS(SELECT 1 FROM ontology.condition_node n WHERE n.claim_id=c.claim_id AND n.node_index=0)
UNION ALL
SELECT 'condition/'||cc.claim_id||'/'||cc.parent_index,'HAS_CHILD','condition/'||cc.claim_id||'/'||cc.child_index,jsonb_build_object('ordinal',cc.ordinal)
FROM ontology.condition_child cc JOIN claims c USING(claim_id)
UNION ALL
SELECT 'condition/'||ce.claim_id||'/'||ce.node_index,'EVIDENCED_BY','evidence/'||ce.evidence_id,jsonb_build_object('part_index',ce.part_index)
FROM ontology.condition_evidence ce JOIN claims c USING(claim_id)
UNION ALL
SELECT 'claim/'||r.claim_id,'HAS_RULE','rule/'||r.rule_id,jsonb_build_object('ordinal',r.ordinal)
FROM ontology.guarded_rule r WHERE r.release_id=id
UNION ALL
SELECT 'rule/'||r.rule_id,'USES_CONTRACT','rule-contract/'||r.schema_version,'{}'::jsonb FROM ontology.guarded_rule r WHERE r.release_id=id
UNION ALL
SELECT 'rule/'||r.rule_id,'REVIEWED_BY','rule-review/'||id||'/'||r.interpretation_id,'{}'::jsonb FROM ontology.guarded_rule r WHERE r.release_id=id
UNION ALL
SELECT 'rule/'||r.rule_id,CASE r.action WHEN 'DISABLE' THEN 'DISABLES' ELSE 'LIMITS' END,'rule/'||r.target_rule_id,'{}'::jsonb
FROM ontology.guarded_rule r WHERE r.release_id=id AND r.target_rule_id IS NOT NULL
UNION ALL
SELECT 'rule/'||r.rule_id,'GUARDED_BY','rule-predicate/'||r.rule_id,'{}'::jsonb
FROM ontology.guarded_rule r WHERE r.release_id=id AND r.guard<>'null'
UNION ALL
SELECT 'rule-predicate/'||n.rule_id||n.parent_path,'HAS_CHILD','rule-predicate/'||n.rule_id||n.node_path,jsonb_build_object('ordinal',n.ordinal)
FROM ontology.rule_predicate n WHERE n.release_id=id AND n.parent_path IS NOT NULL
UNION ALL
SELECT CASE WHEN e.node_path='$statement' THEN 'rule/'||r.rule_id ELSE 'rule-predicate/'||r.rule_id||e.node_path END,
 'EVIDENCED_BY','evidence/'||e.evidence_id,jsonb_build_object('part_index',e.part_index)
FROM ontology.rule_evidence e JOIN ontology.guarded_rule r USING(release_id,interpretation_id,local_id) WHERE e.release_id=id
UNION ALL
SELECT 'rule-review/'||id||'/'||s.interpretation_id,'FOR_EXTRACTION','selection/'||id||'/'||s.entity_id,'{}'::jsonb
FROM ontology.rule_selection s WHERE s.release_id=id
UNION ALL
SELECT DISTINCT 'evidence/'||e.evidence_id,'IN_ARTIFACT','artifact/'||e.artifact_id,'{}'::jsonb FROM ontology.evidence_span e
WHERE EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id='evidence/'||e.evidence_id)
UNION ALL
SELECT 'artifact/'||s.artifact_id,'DERIVED_FROM',ontology.graph_record_id(i),jsonb_build_object('field',s.source_field)
FROM ontology.artifact_source s JOIN ontology.input_record i ON i.release_id=s.release_id AND i.record_id=s.record_id WHERE s.release_id=id
AND EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.node_id='artifact/'||s.artifact_id)
UNION ALL
SELECT 'selection/'||id||'/'||d.entity_id,'USES_INPUT','posting-input/'||d.bundle_id,'{}'::jsonb
FROM ontology.document_input d WHERE d.release_id=id
UNION ALL
SELECT 'posting-input/'||d.bundle_id,'FOR_POSTING','revision/'||m.revision_id,'{}'::jsonb
FROM ontology.document_input d JOIN rev m USING(entity_id) WHERE d.release_id=id
UNION ALL
SELECT 'artifact/'||d.artifact_id,'DERIVED_FROM',ontology.graph_attachment_id(d),'{}'::jsonb
FROM ontology.artifact_document d WHERE d.release_id=id
UNION ALL
SELECT ontology.graph_attachment_id(d),'IN_INPUT','posting-input/'||d.bundle_id,'{}'::jsonb
FROM ontology.artifact_document d WHERE d.release_id=id
UNION ALL
SELECT ontology.graph_attachment_id(d),'DECLARED_IN',ontology.graph_record_id(i),'{}'::jsonb
FROM ontology.artifact_document d JOIN ontology.input_record i USING(release_id,record_id) WHERE d.release_id=id
UNION ALL
SELECT ontology.graph_attachment_id(d),'HAS_OBSERVATION',ontology.graph_attachment_id(d)||'/observation/'||x.ordinality,'{}'::jsonb
FROM ontology.artifact_document d CROSS JOIN LATERAL jsonb_array_elements(d.descriptor->'structure_issues') WITH ORDINALITY x
WHERE d.release_id=id
UNION ALL
SELECT ontology.graph_attachment_id(d)||'/section/'||s.section_index,'IN_ARTIFACT','artifact/'||d.artifact_id,'{}'::jsonb
FROM ontology.document_section s JOIN ontology.artifact_document d USING(release_id,artifact_id) WHERE s.release_id=id
UNION ALL
SELECT 'evidence/'||e.evidence_id,'OVERLAPS_SECTION',ontology.graph_attachment_id(d)||'/section/'||s.section_index,
 jsonb_build_object('start_offset',greatest(e.start_offset,s.normalized_start),'end_offset',least(e.end_offset,s.normalized_end),
  'offset_unit','unicode-codepoint-zero-half-open')
FROM ontology.release_evidence r JOIN ontology.evidence_span e USING(evidence_id)
JOIN ontology.artifact_document d ON d.release_id=r.release_id AND d.artifact_id=e.artifact_id
JOIN ontology.document_section s ON s.release_id=d.release_id AND s.artifact_id=d.artifact_id
WHERE r.release_id=id AND e.start_offset<s.normalized_end AND e.end_offset>s.normalized_start
UNION ALL
SELECT ontology.graph_document_part_id(d,'table',x),'IN_ATTACHMENT',ontology.graph_attachment_id(d),'{}'::jsonb
FROM ontology.artifact_document d CROSS JOIN LATERAL jsonb_array_elements(d.descriptor->'tables') x WHERE d.release_id=id
UNION ALL
SELECT ontology.graph_document_part_id(d,'table',x),'NESTED_IN_CELL',
 ontology.graph_document_part_id(d,'cell',x||jsonb_build_object('cell_no',x->'parent_cell_no')),'{}'::jsonb
FROM ontology.artifact_document d CROSS JOIN LATERAL jsonb_array_elements(d.descriptor->'tables') x
WHERE d.release_id=id AND x->>'parent_cell_no' IS NOT NULL
UNION ALL
SELECT ontology.graph_document_part_id(d,'table',x),'HAS_CELL',ontology.graph_document_part_id(d,'cell',x),'{}'::jsonb
FROM ontology.artifact_document d CROSS JOIN LATERAL jsonb_array_elements(d.descriptor->'cells') x WHERE d.release_id=id
UNION ALL
SELECT ontology.graph_attachment_id(d)||'/section/'||s.section_index,'IN_CELL',
 ontology.graph_document_part_id(d,'cell',s.source_locator),'{}'::jsonb
FROM ontology.document_section s JOIN ontology.artifact_document d USING(release_id,artifact_id)
WHERE s.release_id=id AND s.source_locator->>'cell_no' IS NOT NULL
UNION ALL
SELECT 'mapping/'||c.mapping_id,'MAPS_DUTY','claim/'||c.duty_claim_id,'{}'::jsonb FROM ontology.release_mapping m JOIN ontology.mapping_claim c USING(mapping_id) WHERE m.release_id=id
UNION ALL
SELECT 'mapping/'||c.mapping_id,'MAPS_TARGET','revision/'||c.target_revision_id,'{}'::jsonb FROM ontology.release_mapping m JOIN ontology.mapping_claim c USING(mapping_id) WHERE m.release_id=id
UNION ALL
SELECT 'mapping/'||m.mapping_id,'REVIEWED_BY','link-review/'||id||'/'||m.candidate_id,'{}'::jsonb FROM ontology.release_mapping m WHERE m.release_id=id
UNION ALL
SELECT 'selection/'||id||'/'||p.entity_id,'SELECTS_REVISION','revision/'||p.posting_revision_id,'{}'::jsonb FROM ontology.posting_selection p WHERE p.release_id=id
UNION ALL
SELECT 'claim/'||m.claim_id,'REVIEWED_BY','selection/'||id||'/'||m.entity_id,'{}'::jsonb FROM ontology.release_claim m WHERE m.release_id=id
UNION ALL
SELECT 'position/'||m.position_id,'REVIEWED_BY','selection/'||id||'/'||m.entity_id,'{}'::jsonb FROM ontology.release_position m WHERE m.release_id=id
UNION ALL
SELECT 'release/'||id,'INCLUDES',node_id,'{}'::jsonb FROM ontology.graph_node WHERE release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.graph_inventory_manifest_base_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
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

CREATE OR REPLACE FUNCTION ontology.seal_graph(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE sealed_manifest jsonb;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM 1 FROM ontology.corpus_release WHERE release_id=id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_ONTOLOGY_RELEASE'; END IF;
 PERFORM ontology.verify_requirements_v1(id);
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
CREATE OR REPLACE VIEW ontology.graph_property AS
WITH objects AS (
 SELECT release_id,'NODE'::text AS owner_type,node_id AS owner_id,content_hash,properties FROM ontology.graph_node
 UNION ALL SELECT release_id,'EDGE',edge_id,content_hash,properties FROM ontology.graph_edge
), expanded AS (
 SELECT o.release_id,o.owner_type,o.owner_id,o.content_hash,p.key,
  jsonb_typeof(p.value)='array' AS is_array,coalesce(a.ordinality-1,-1)::integer AS ordinal,
  CASE WHEN jsonb_typeof(p.value)='array' THEN a.value ELSE p.value END AS value,
  CASE WHEN jsonb_typeof(p.value)='array' THEN jsonb_array_length(p.value) ELSE -1 END AS array_size,
  CASE WHEN jsonb_typeof(p.value)='array' THEN EXISTS(SELECT 1 FROM jsonb_array_elements(p.value) x
   WHERE CASE WHEN jsonb_typeof(x)='number' THEN (x#>>'{}')::numeric<>trunc((x#>>'{}')::numeric) ELSE false END) ELSE false END AS float_array
 FROM objects o CROSS JOIN LATERAL jsonb_each(o.properties) p
 LEFT JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(p.value)='array' THEN p.value ELSE '[]' END) WITH ORDINALITY a ON true
)
SELECT release_id,owner_type,owner_id,content_hash,key,is_array,ordinal,value,array_size,
 value#>>'{}' AS text_value,CASE WHEN value IS NULL THEN 'empty_array'
 WHEN jsonb_typeof(value)='number' THEN CASE WHEN NOT float_array AND (value#>>'{}')::numeric=trunc((value#>>'{}')::numeric) THEN 'integer' ELSE 'number' END
 WHEN jsonb_typeof(value)='string' AND (key IN ('date_posted','closing_date','established_date','earliest_start') OR key LIKE 'dates.%')
  AND (value#>>'{}') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN 'date'
 WHEN jsonb_typeof(value)='string' AND key ~ '(^|[.])(created_at|reviewed_at|first_seen_at|last_seen_at|evaluated_at)$'
  AND (value#>>'{}') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T' THEN 'datetime'
 ELSE jsonb_typeof(value) END AS value_type FROM expanded;


COMMIT;
