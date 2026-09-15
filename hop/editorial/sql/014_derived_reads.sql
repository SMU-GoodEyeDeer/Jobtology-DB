-- V3 reads expose frozen derived claims separately from immutable source payloads.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.read_release_v3(choice text,preview boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE id text; requirement_frozen boolean; occupation_frozen boolean; sealed jsonb; BEGIN
 id:=ontology.read_release_v2(choice,preview);
 requirement_frozen:=EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=id);
 occupation_frozen:=EXISTS(SELECT 1 FROM ontology.occupation_freeze WHERE release_id=id);
 IF NOT requirement_frozen AND (EXISTS(SELECT 1 FROM ontology.requirement_membership WHERE release_id=id)
  OR EXISTS(SELECT 1 FROM ontology.requirement_selection WHERE release_id=id))
 THEN RAISE EXCEPTION 'REQUIREMENT_READ_MEMBERSHIP_REQUIRED'; END IF;
 IF NOT occupation_frozen AND (EXISTS(SELECT 1 FROM ontology.occupation_membership WHERE release_id=id)
  OR EXISTS(SELECT 1 FROM ontology.occupation_selection WHERE release_id=id))
 THEN RAISE EXCEPTION 'OCCUPATION_READ_MEMBERSHIP_REQUIRED'; END IF;
 IF requirement_frozen OR occupation_frozen THEN PERFORM ontology.verify_claims(id); END IF;
 PERFORM ontology.verify_requirements_v1(id);
 PERFORM ontology.verify_occupation_graph_v1(id);
 SELECT manifest INTO sealed FROM ontology.corpus_release WHERE release_id=id;
 IF sealed IS NOT NULL AND requirement_frozen AND (
  sealed->'requirement_membership' IS DISTINCT FROM (SELECT to_jsonb(m) FROM ontology.requirement_membership m WHERE release_id=id)
  OR sealed->'requirement_projection' IS DISTINCT FROM ontology.requirement_graph_manifest_v1(id))
 THEN RAISE EXCEPTION 'REQUIREMENT_READ_MANIFEST_MISMATCH'; END IF;
 RETURN id;
END $$;

CREATE OR REPLACE VIEW ontology.derived_claim_v1 AS
SELECT t.release_id,m.entity_id,t.posting_revision_id,t.claim_id,'NORMALIZED_REQUIREMENT'::text AS claim_kind,
 jsonb_build_object('claim_id',t.claim_id,'claim_kind','NORMALIZED_REQUIREMENT',
  'graph_node_id','typed-requirement/'||t.claim_id,'entity_id',m.entity_id,'posting_revision_id',t.posting_revision_id,
  'assertion_kind','NORMALIZED','normalization_id',t.normalization_id,'decision_id',t.decision_id,
  'source_claim_id',t.source_claim_id,'source_node_index',t.node_index,'name',t.source_text,
  'condition',t.condition,'requirement_kind',t.requirement_kind,'requirement_scope',t.requirement_scope,
  'necessity',t.necessity,'polarity',t.polarity,'applicability',t.applicability,
  'requirement_key',t.requirement_key,'key_algorithm',t.key_algorithm,
  'review_status',t.review_status,'reviewed_at',t.reviewed_at,'confidence',NULL,'confidence_state','UNASSESSED') AS summary
FROM ontology.typed_requirement t JOIN ontology.requirement_membership f USING(release_id)
JOIN ontology.release_revision m ON m.release_id=t.release_id AND m.revision_id=t.posting_revision_id
UNION ALL
SELECT p.release_id,p.entity_id,p.posting_revision_id,ontology.occupation_claim_id_v1(p.proposal_id,p.decision_id),'PRIMARY_OCCUPATION',
 jsonb_build_object('claim_id',ontology.occupation_claim_id_v1(p.proposal_id,p.decision_id),'claim_kind','PRIMARY_OCCUPATION',
  'graph_node_id','primary-occupation/'||ontology.occupation_claim_id_v1(p.proposal_id,p.decision_id),
  'entity_id',p.entity_id,'posting_revision_id',p.posting_revision_id,
  'assertion_kind',CASE p.method WHEN 'MODEL_INFERRED' THEN 'MODEL_INFERRED' ELSE 'NORMALIZED' END,
  'proposal_id',p.proposal_id,'decision_id',p.decision_id,'method',p.method,'resolver_version',p.resolver_version,
  'name',r.name,'occupation',jsonb_build_object('entity_id',r.entity_id,'revision_id',r.revision_id,
   'name',r.name,'payload_hash',r.payload_hash),
  'review_status',p.review_state,'reviewed_at',p.reviewed_at,'confidence',p.confidence,'confidence_state',p.confidence_state)
FROM ontology.primary_product_occupation p JOIN ontology.occupation_membership f USING(release_id)
JOIN ontology.release_revision m ON m.release_id=p.release_id AND m.revision_id=p.occupation_revision_id
JOIN ontology.revision r ON r.revision_id=m.revision_id;

CREATE OR REPLACE FUNCTION ontology.read_context_v3(id text,preview boolean) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT ontology.read_context_v2(id,preview)||jsonb_build_object('contract_version','hop-ontology-read-v3',
  'derived_memberships',jsonb_build_object(
   'requirements',jsonb_build_object('status',CASE WHEN EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=id) THEN 'FROZEN' ELSE 'NOT_FROZEN' END,
    'membership_hash',(SELECT manifest_hash FROM ontology.requirement_membership WHERE release_id=id),
    'freeze',(SELECT to_jsonb(f) FROM ontology.requirement_freeze f WHERE release_id=id)),
   'occupations',jsonb_build_object('status',CASE WHEN EXISTS(SELECT 1 FROM ontology.occupation_freeze WHERE release_id=id) THEN 'FROZEN' ELSE 'NOT_FROZEN' END,
    'membership_hash',(SELECT manifest_hash FROM ontology.occupation_membership WHERE release_id=id),
    'freeze',(SELECT to_jsonb(f) FROM ontology.occupation_freeze f WHERE release_id=id))))
$$;

CREATE OR REPLACE FUNCTION ontology.query_derived_claim_v1(release_choice text,claim_choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; c ontology.derived_claim_v1%ROWTYPE; result jsonb; source jsonb; targets jsonb; evidence_ids jsonb; BEGIN
 id:=ontology.read_release_v3(release_choice,preview);
 SELECT * INTO c FROM ontology.derived_claim_v1 WHERE release_id=id AND claim_id=claim_choice;
 IF NOT FOUND THEN RAISE EXCEPTION 'ONTOLOGY_DERIVED_CLAIM_NOT_IN_RELEASE'; END IF;
 IF c.claim_kind='NORMALIZED_REQUIREMENT' THEN
  SELECT jsonb_build_object('proposal',n.document,'review',to_jsonb(d),
   'source_binding_hash',ontology.hash(n.source_binding),'target_bindings_hash',ontology.hash(n.target_bindings),
   'normalization_created_at',n.created_at),n.source_binding,n.target_bindings,
   coalesce((SELECT jsonb_agg(DISTINCT e->'span'->>'evidence_id' ORDER BY e->'span'->>'evidence_id')
    FROM jsonb_array_elements(n.source_binding->'evidence') e),'[]')
  INTO result,source,targets,evidence_ids
  FROM ontology.requirement_normalization n JOIN ontology.requirement_decision d ON d.decision_id=(c.summary->>'decision_id')::bigint
  WHERE n.normalization_id=c.summary->>'normalization_id';
 ELSE
  SELECT jsonb_build_object('proposal',p.document,'review',to_jsonb(d),
   'source_binding_hash',p.source_binding_hash,'catalogue_binding',p.catalogue_binding,
   'catalogue_binding_hash',ontology.hash(p.catalogue_binding),'proposal_created_at',p.created_at),p.source_binding,
   jsonb_build_array(jsonb_build_object('role','PRIMARY_OCCUPATION','entity_id',p.occupation_id,
    'revision_id',p.occupation_revision_id,'payload_hash',r.payload_hash)),p.document->'evidence_ids'
  INTO result,source,targets,evidence_ids
  FROM ontology.occupation_proposal p JOIN ontology.occupation_decision d ON d.decision_id=(c.summary->>'decision_id')::bigint
  JOIN ontology.revision r ON r.revision_id=p.occupation_revision_id WHERE p.proposal_id=c.summary->>'proposal_id';
 END IF;
 RETURN ontology.read_context_v3(id,preview)||jsonb_build_object('claim',c.summary||result||jsonb_build_object(
  'source_binding',source,
  'targets',coalesce((SELECT jsonb_agg(b||jsonb_build_object('revision',to_jsonb(r)-'created_at',
   'source_support',coalesce((SELECT jsonb_agg(reference ORDER BY support_id,reference::text COLLATE "C")
    FROM ontology.source_support_v2(id,r.entity_id)),'[]')) ORDER BY b->>'role',r.entity_id COLLATE "C")
   FROM jsonb_array_elements(targets) b JOIN ontology.release_revision m ON m.release_id=id AND m.revision_id=b->>'revision_id'
   JOIN ontology.revision r ON r.revision_id=m.revision_id),'[]'),
  'evidence',coalesce((SELECT jsonb_agg(ontology.query_evidence_v1(id,e,preview) ORDER BY e COLLATE "C")
   FROM jsonb_array_elements_text(evidence_ids) e),'[]')));
END $$;

CREATE OR REPLACE FUNCTION ontology.query_derived_claims_v1(release_choice text DEFAULT NULL,entity_choice text DEFAULT NULL,
 claim_kind_choice text DEFAULT NULL,page_size integer DEFAULT 100,cursor_value text DEFAULT NULL,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; entity_filter text; kind_filter text; scope jsonb; cursor_data jsonb; last_id text; rows jsonb; next_cursor text; total bigint; BEGIN
 id:=ontology.read_release_v3(release_choice,preview);
 entity_filter:=nullif(entity_choice,'');kind_filter:=nullif(claim_kind_choice,'');
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_PAGE_SIZE'; END IF;
 IF kind_filter IS NOT NULL AND kind_filter NOT IN ('NORMALIZED_REQUIREMENT','PRIMARY_OCCUPATION')
 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_DERIVED_CLAIM_KIND'; END IF;
 IF entity_filter IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ontology.release_revision WHERE release_id=id AND entity_id=entity_filter)
 THEN RAISE EXCEPTION 'ONTOLOGY_ENTITY_NOT_IN_RELEASE'; END IF;
 SELECT count(*),jsonb_build_object('contract','hop-ontology-derived-cursor-v1','release_id',id,
  'entity_id',entity_filter,'claim_kind',kind_filter,
  'derived_memberships',ontology.read_context_v3(id,preview)->'derived_memberships',
  'editorial_membership_hash',(SELECT manifest_hash FROM editorial.release_pin WHERE release_id=id),
  'selection_hash',ontology.hash(coalesce(jsonb_agg(summary ORDER BY claim_id COLLATE "C"),'[]')))
 INTO total,scope FROM ontology.derived_claim_v1
 WHERE release_id=id AND (entity_filter IS NULL OR entity_id=entity_filter) AND (kind_filter IS NULL OR claim_kind=kind_filter);
 IF nullif(cursor_value,'') IS NOT NULL THEN
  BEGIN
   IF length(cursor_value)>4096 THEN RAISE EXCEPTION 'CURSOR_TOO_LONG'; END IF;
   cursor_data:=convert_from(decode(cursor_value,'base64'),'UTF8')::jsonb;
   IF jsonb_typeof(cursor_data) IS DISTINCT FROM 'object' OR jsonb_typeof(cursor_data->'last_id') IS DISTINCT FROM 'string'
    OR nullif(cursor_data->>'last_id','') IS NULL OR cursor_data-'last_id' IS DISTINCT FROM scope
   THEN RAISE EXCEPTION 'CURSOR_SCOPE_MISMATCH'; END IF;
   last_id:=cursor_data->>'last_id';
  EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_CURSOR'; END;
 END IF;
 SELECT coalesce(jsonb_agg(summary ORDER BY claim_id COLLATE "C"),'[]') INTO rows FROM (
  SELECT claim_id,summary FROM ontology.derived_claim_v1
  WHERE release_id=id AND (entity_filter IS NULL OR entity_id=entity_filter) AND (kind_filter IS NULL OR claim_kind=kind_filter)
   AND (last_id IS NULL OR claim_id COLLATE "C">last_id COLLATE "C")
  ORDER BY claim_id COLLATE "C" LIMIT page_size+1) x;
 IF jsonb_array_length(rows)>page_size THEN
  rows:=rows-page_size;
  next_cursor:=replace(encode(convert_to((scope||jsonb_build_object('last_id',rows->-1->>'claim_id'))::text,'UTF8'),'base64'),E'\n','');
 END IF;
 RETURN ontology.read_context_v3(id,preview)||jsonb_build_object('entity_id',entity_filter,'claim_kind',kind_filter,
  'total',total,'items',rows,'next_cursor',next_cursor);
END $$;

CREATE OR REPLACE FUNCTION ontology.query_entity_v3(release_choice text,entity_choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; result jsonb; BEGIN
 id:=ontology.read_release_v3(release_choice,preview);
 result:=ontology.query_entity_v2(id,entity_choice,preview);
 RETURN result||ontology.read_context_v3(id,preview)||jsonb_build_object(
  'derived_claims',ontology.query_derived_claims_v1(id,entity_choice,NULL,100,NULL,preview),
  'primary_occupation',(SELECT summary FROM ontology.derived_claim_v1 WHERE release_id=id AND entity_id=entity_choice AND claim_kind='PRIMARY_OCCUPATION'),
  'occupation_selection',(SELECT to_jsonb(s) FROM ontology.occupation_selection s WHERE release_id=id AND s.entity_id=entity_choice),
  'requirement_outcomes',coalesce((SELECT jsonb_object_agg(outcome,n) FROM (
   SELECT s.outcome,count(*) n FROM ontology.requirement_selection s JOIN ontology.requirement_atom a USING(release_id,source_claim_id,node_index)
   WHERE s.release_id=id AND a.entity_id=entity_choice GROUP BY s.outcome) x),'{}'),
  'derived_claim_notice','Frozen reviewed interpretations are separate from source payloads. Confidence is unassessed; parent expression trees, positions and guards still govern applicability.');
END $$;

CREATE OR REPLACE FUNCTION ontology.query_summary_v3(release_choice text DEFAULT NULL,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; BEGIN
 id:=ontology.read_release_v3(release_choice,preview);
 RETURN ontology.query_summary_v2(id,preview)||ontology.read_context_v3(id,preview)||jsonb_build_object(
  'derived_claim_counts',coalesce((SELECT jsonb_object_agg(claim_kind,n) FROM (
   SELECT claim_kind,count(*) n FROM ontology.derived_claim_v1 WHERE release_id=id GROUP BY claim_kind) x),'{}'),
  'requirement_outcomes',coalesce((SELECT jsonb_object_agg(outcome,n) FROM (
   SELECT outcome,count(*) n FROM ontology.requirement_selection WHERE release_id=id GROUP BY outcome) x),'{}'),
  'occupation_outcomes',coalesce((SELECT jsonb_object_agg(outcome,n) FROM (
   SELECT outcome,count(*) n FROM ontology.occupation_selection WHERE release_id=id GROUP BY outcome) x),'{}'),
  'derived_claim_notice','Counts describe frozen reviewed interpretations, not extraction accuracy, calibrated confidence, cohort demand or publication readiness.');
END $$;
COMMIT;
