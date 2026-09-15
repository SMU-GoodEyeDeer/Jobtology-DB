BEGIN;
CREATE OR REPLACE FUNCTION ontology.cohort_profile_origin_v1(id text,entity text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object('record_id',i.record_id,'source_id',i.source_id,'run_id',i.run_id,
  'document_id',i.document_id,'locator',i.locator,'source_record_id',i.source_record_id,'raw_sha256',i.raw_sha256,
  'normalized_hash',i.normalized_hash,'source_fields',s.fields,'field_lineage',i.field_lineage) ORDER BY i.record_id),'[]')
 FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id) WHERE s.release_id=id AND s.entity_id=entity
$$;

CREATE OR REPLACE FUNCTION ontology.query_cohort_profile_input_v1(choice text,entity text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text;source jsonb;current ontology.cohort_profile_proposal%ROWTYPE;tracks jsonb;resolved boolean; BEGIN
 id:=ontology.read_release_v1(choice,preview);PERFORM ontology.verify_claims(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'FREEZE_REQUIREMENTS_BEFORE_COHORT_PROFILE'; END IF;
 PERFORM ontology.verify_requirements_v1(id);source:=ontology.cohort_profile_source_v1(id,entity);
 IF source IS NULL THEN RAISE EXCEPTION 'COHORT_PROFILE_POSTING_NOT_IN_RELEASE'; END IF;
 SELECT * INTO current FROM ontology.cohort_profile_proposal WHERE posting_entity_id=entity ORDER BY proposal_no DESC LIMIT 1;
 resolved:=source->>'extraction_outcome'='ACCEPTED' AND jsonb_array_length(source->'positions')>0;
 SELECT coalesce(jsonb_agg(jsonb_build_object('position_id',p->>'position_id','country_scope','UNKNOWN','country_evidence','[]'::jsonb,
  'experience_policy','UNKNOWN','policy_basis','UNKNOWN','minimum_months',NULL,'maximum_months',NULL,'experience_evidence','[]'::jsonb,
  'experience_requirement_ids','[]'::jsonb,'cohort_scope','UNRESOLVED','scope_notes','Awaiting source and position-scope review.',
  'scope_evidence','[]'::jsonb,'entry_track_scoped',false,'domestic_track_scoped',false,
  'considered_atom_ids',coalesce((SELECT jsonb_agg(atom->>'atom_id' ORDER BY atom->>'atom_id' COLLATE "C")
   FROM ontology.cohort_profile_atoms_v1(source,p->>'position_id')),'[]'),
  'included_requirement_ids','[]'::jsonb) ORDER BY p->>'position_id' COLLATE "C"),'[]') INTO tracks
 FROM jsonb_array_elements(source->'positions') p;
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('contract','reviewed-cohort-profiles-v1',
  'source_binding',source,'source_binding_hash',ontology.hash(source),'source_support',ontology.cohort_profile_origin_v1(id,entity),
  'current_proposal',CASE WHEN current.proposal_id IS NULL THEN NULL ELSE to_jsonb(current) END,
  'current_decision',(SELECT to_jsonb(d) FROM ontology.cohort_profile_decision d WHERE d.proposal_id=current.proposal_id ORDER BY decision_id DESC LIMIT 1),
  'proposal_template',jsonb_build_object('schema_version','hop-cohort-profile-proposal-v1','release_id',id,'posting_entity_id',entity,
   'parent_id',current.proposal_id,'source_binding_hash',ontology.hash(source),'actor','','actor_kind','human','method','MANUAL',
   'model_id',NULL,'prompt_version',NULL,'resolver_version','','reason','',
   'disposition',CASE WHEN resolved THEN 'PROFILE' ELSE 'UNRESOLVED' END,
   'unresolved_reason',CASE WHEN resolved THEN NULL WHEN source->>'extraction_outcome'<>'ACCEPTED' THEN 'EXTRACTION_NOT_ACCEPTED' ELSE 'NO_REVIEWED_POSITIONS' END,
   'posting_experience_label','UNKNOWN','posting_label_evidence','[]'::jsonb,'tracks',CASE WHEN resolved THEN tracks ELSE '[]'::jsonb END),
  'notice','Current proposal and review are editing context. Evidence uses zero-based, half-open Unicode code-point offsets in the normalized fields shown here.');
END $$;

CREATE OR REPLACE FUNCTION ontology.query_cohort_profiles_v1(choice text,preview boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE id text; BEGIN
 id:=ontology.read_release_v1(choice,preview);PERFORM ontology.verify_cohort_profiles_v1(id);
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('contract','reviewed-cohort-profiles-v1',
  'selection_status',CASE WHEN EXISTS(SELECT 1 FROM ontology.cohort_profile_freeze WHERE release_id=id) THEN 'FROZEN' ELSE 'NOT_FROZEN' END,
  'membership',(SELECT to_jsonb(m) FROM ontology.cohort_profile_membership m WHERE release_id=id),
  'selections',coalesce((SELECT jsonb_agg(jsonb_build_object('selection',to_jsonb(s),'proposal',to_jsonb(p),'review',to_jsonb(d),
   'origin_source_support',CASE WHEN p.proposal_id IS NOT NULL THEN ontology.cohort_profile_origin_v1(p.created_in_release,p.posting_entity_id) ELSE NULL END)
   ORDER BY s.entity_id COLLATE "C") FROM ontology.cohort_profile_selection s LEFT JOIN ontology.cohort_profile_proposal p USING(proposal_id)
   LEFT JOIN ontology.cohort_profile_decision d USING(decision_id) WHERE s.release_id=id),'[]'),
  'tracks',coalesce((SELECT jsonb_agg(to_jsonb(t)||jsonb_build_object('country_experience_scope_eligible',t.exclusion_reasons='[]'::jsonb)
   ORDER BY t.entity_id COLLATE "C",t.position_id COLLATE "C") FROM ontology.cohort_profile_track t WHERE t.release_id=id),'[]'),
  'notice','Country/experience/scope eligibility is not cohort membership. Occupation, source, language, date window, duplicate representative, calibration and publication checks remain separate.');
END $$;
COMMIT;
