-- Explicit rule effects preserve the original extraction and have their own review.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.rule_freeze (
 release_id text PRIMARY KEY REFERENCES ontology.review_freeze,
 interpretation_cutoff bigint NOT NULL,
 decision_cutoff bigint NOT NULL,
 policy_version text NOT NULL DEFAULT 'guarded-rules-v1'
);
CREATE TABLE IF NOT EXISTS ontology.rule_selection (
 release_id text NOT NULL,
 entity_id text NOT NULL,
 interpretation_id text NOT NULL REFERENCES enrichment.rule_interpretation,
 requirement_index integer NOT NULL,
 decision_id bigint REFERENCES enrichment.rule_interpretation_decision,
 outcome text NOT NULL CHECK(outcome IN ('ACCEPTED','REJECTED','REVIEW_REQUIRED','EXTRACTION_NOT_ACCEPTED','SOURCE_MISMATCH')),
 interpretation jsonb NOT NULL,
 review jsonb,
 PRIMARY KEY(release_id,interpretation_id),
 UNIQUE(release_id,entity_id,requirement_index),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.posting_selection,
 FOREIGN KEY(release_id) REFERENCES ontology.rule_freeze
);
CREATE TABLE IF NOT EXISTS ontology.rule_evidence (
 release_id text NOT NULL,
 interpretation_id text NOT NULL,
 local_id text NOT NULL,
 node_path text NOT NULL,
 part_index integer NOT NULL CHECK(part_index>=0),
 evidence_id text NOT NULL REFERENCES ontology.evidence_span,
 PRIMARY KEY(release_id,interpretation_id,local_id,node_path,part_index),
 FOREIGN KEY(release_id,interpretation_id) REFERENCES ontology.rule_selection
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['rule_freeze','rule_selection','rule_evidence'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||name AND tgrelid=('ontology.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

-- These views derive typed rules exclusively from an immutable accepted selection.
-- Scope remains on the reviewed requirement; a permission does not waive it.
CREATE OR REPLACE VIEW ontology.guarded_rule AS
SELECT s.release_id,s.entity_id,s.interpretation_id,s.decision_id,c.claim_id,
 s.interpretation->>'schema_version' AS schema_version,
 ontology.hash(jsonb_build_array(c.claim_id,s.interpretation_id,r.data->>'id')) AS rule_id,
 (r.ordinal-1)::integer AS ordinal,r.data->>'id' AS local_id,r.data->>'action' AS action,
 r.data->'statement_parts' AS statement_parts,r.data->'guard' AS guard,
 CASE WHEN r.data->>'target_rule_id' IS NOT NULL THEN
  ontology.hash(jsonb_build_array(c.claim_id,s.interpretation_id,r.data->>'target_rule_id')) END AS target_rule_id,
 r.data AS rule_data,c.applicability,c.payload->'position_ids' AS position_ids
FROM ontology.rule_selection s
JOIN ontology.release_claim m ON m.release_id=s.release_id AND m.entity_id=s.entity_id
JOIN ontology.claim c ON c.claim_id=m.claim_id AND c.kind='REQUIREMENT' AND c.ordinal=s.requirement_index
CROSS JOIN LATERAL jsonb_array_elements(s.interpretation#>'{document,rules}') WITH ORDINALITY r(data,ordinal)
WHERE s.outcome='ACCEPTED';

CREATE OR REPLACE VIEW ontology.rule_predicate AS
WITH RECURSIVE tree AS (
 SELECT r.release_id,r.rule_id,''::text AS node_path,NULL::text AS parent_path,NULL::integer AS ordinal,r.guard AS node,0 AS depth
 FROM ontology.guarded_rule r WHERE r.guard IS NOT NULL AND r.guard<>'null'
 UNION ALL
 SELECT t.release_id,t.rule_id,t.node_path||'/'||(c.ordinal-1),t.node_path,(c.ordinal-1)::integer,c.node,t.depth+1
 FROM tree t CROSS JOIN LATERAL jsonb_array_elements(t.node->'children') WITH ORDINALITY c(node,ordinal)
 WHERE t.depth<12
)
SELECT release_id,rule_id,node_path,parent_path,ordinal,node->>'op' AS operator,node->'parts' AS parts,node,depth FROM tree;

CREATE OR REPLACE VIEW ontology.rule_part AS
SELECT r.release_id,r.entity_id,r.interpretation_id,r.local_id,r.rule_id,'$statement'::text AS node_path,
 (p.ordinal-1)::integer AS part_index,p.fragment,r.rule_data
FROM ontology.guarded_rule r CROSS JOIN LATERAL jsonb_array_elements_text(r.statement_parts) WITH ORDINALITY p(fragment,ordinal)
UNION ALL
SELECT r.release_id,r.entity_id,r.interpretation_id,r.local_id,r.rule_id,n.node_path,
 (p.ordinal-1)::integer,p.fragment,r.rule_data
FROM ontology.guarded_rule r JOIN ontology.rule_predicate n USING(release_id,rule_id)
CROSS JOIN LATERAL jsonb_array_elements_text(n.parts) WITH ORDINALITY p(fragment,ordinal);

CREATE OR REPLACE FUNCTION ontology.assemble_rules(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s record; part record; eid text; cited jsonb;
BEGIN
 PERFORM ontology.require_preparing(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'FREEZE_REVIEWS_FIRST'; END IF;
 FOR s IN SELECT r.*,p.extraction,p.source_data FROM ontology.rule_selection r
  JOIN ontology.posting_selection p USING(release_id,entity_id) WHERE r.release_id=id AND r.outcome='ACCEPTED' LOOP
  IF enrichment.rule_interpretation_issues(s.interpretation->'document',s.extraction->'requirements'->s.requirement_index,s.source_data)<>'[]'
  THEN RAISE EXCEPTION 'INVALID_FROZEN_RULE_INTERPRETATION'; END IF;
 END LOOP;
 FOR part IN SELECT * FROM ontology.rule_part WHERE release_id=id LOOP
  SELECT r.evidence_ids INTO STRICT cited FROM ontology.posting_selection p
   CROSS JOIN LATERAL enrichment.rule_evidence_ranges(part.rule_data->'evidence_ids',p.source_data) r
   WHERE p.release_id=id AND p.entity_id=part.entity_id AND enrichment.parts_supported_v3(jsonb_build_array(part.fragment),r.quote)
   ORDER BY r.evidence_ids::text LIMIT 1;
  eid:=ontology.store_fragment(id,part.entity_id,jsonb_set(part.rule_data,'{evidence_ids}',cited),part.fragment);
  INSERT INTO ontology.rule_evidence VALUES(id,part.interpretation_id,part.local_id,part.node_path,part.part_index,eid) ON CONFLICT DO NOTHING;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.verify_rules(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM ontology.guarded_rule WHERE release_id=id) IS DISTINCT FROM
  (SELECT coalesce(sum(jsonb_array_length(interpretation#>'{document,rules}')),0) FROM ontology.rule_selection WHERE release_id=id AND outcome='ACCEPTED')
 THEN RAISE EXCEPTION 'ONTOLOGY_RULE_MEMBERSHIP_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.rule_selection s JOIN ontology.posting_selection p USING(release_id,entity_id)
  WHERE s.release_id=id AND s.outcome='ACCEPTED' AND
   (p.outcome<>'ACCEPTED' OR s.interpretation->>'revision_id'<>p.extraction_revision_id OR
    s.interpretation->>'source_hash'<>p.source_hash OR s.interpretation->>'extraction_hash'<>enrichment.hash(p.extraction::text) OR
    s.review->>'decision' IS DISTINCT FROM 'ACCEPT' OR (s.review->>'decision_id')::bigint IS DISTINCT FROM s.decision_id OR
    enrichment.rule_interpretation_issues(s.interpretation->'document',p.extraction->'requirements'->s.requirement_index,p.source_data)<>'[]'))
 THEN RAISE EXCEPTION 'ONTOLOGY_RULE_SOURCE_OR_REVIEW_MISMATCH'; END IF;
 IF (SELECT count(*) FROM ontology.rule_evidence WHERE release_id=id)<>(SELECT count(*) FROM ontology.rule_part WHERE release_id=id) OR
  EXISTS(SELECT 1 FROM ontology.rule_part p LEFT JOIN ontology.rule_evidence e USING(release_id,interpretation_id,local_id,node_path,part_index)
   LEFT JOIN ontology.evidence_span v USING(evidence_id) LEFT JOIN ontology.text_artifact a USING(artifact_id)
   WHERE p.release_id=id AND (e.evidence_id IS NULL OR a.posting_id<>p.entity_id OR
    enrichment.fold_space_v2(v.excerpt) IS DISTINCT FROM enrichment.fold_space_v2(ontology.normalize_text(p.fragment)) OR
    NOT EXISTS(SELECT 1 FROM ontology.posting_selection s
     CROSS JOIN LATERAL enrichment.rule_evidence_ranges(p.rule_data->'evidence_ids',s.source_data) cited
     CROSS JOIN LATERAL (SELECT min((x->>'start')::integer) AS first_char,max((x->>'end')::integer) AS last_char
      FROM jsonb_array_elements(enrichment.source_passages_v2(s.source_data)) x WHERE cited.evidence_ids @> jsonb_build_array(x->>'id')) bounds
     WHERE s.release_id=id AND s.entity_id=p.entity_id AND cited.source_field=a.source_field
      AND v.start_offset>=length(ontology.normalize_text(left(s.source_data->>a.source_field,bounds.first_char-1)))
      AND v.end_offset<=length(ontology.normalize_text(left(s.source_data->>a.source_field,bounds.last_char)))
      AND enrichment.parts_supported_v3(jsonb_build_array(p.fragment),cited.quote))))
 THEN RAISE EXCEPTION 'ONTOLOGY_RULE_EVIDENCE_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.guarded_rule r WHERE r.release_id=id AND r.target_rule_id IS NOT NULL AND
  NOT EXISTS(SELECT 1 FROM ontology.guarded_rule target WHERE target.release_id=id AND target.rule_id=r.target_rule_id AND target.interpretation_id=r.interpretation_id))
 THEN RAISE EXCEPTION 'ONTOLOGY_RULE_TARGET_MISMATCH'; END IF;
END $$;
COMMENT ON VIEW ontology.guarded_rule IS 'Independently reviewed rule effects; guard activation alone does not determine overall applicant eligibility or resolve predicate concepts.';
COMMIT;
