-- Explicit reviewer proposals for current ALIO roles against the current NCS catalog.
-- This transport does not use a model and does not publish to Neo4j. A case
-- freezes the exact source, accepted extraction, position-bound duty and full
-- NCS definition. Only decision, reason and notes may be edited.
BEGIN;

CREATE TABLE IF NOT EXISTS cs.manual_ncs_link_import (
 import_id text PRIMARY KEY,
 reviewer text NOT NULL,
 reviewer_kind text NOT NULL,
 packet jsonb NOT NULL,
 counts jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION cs.reject_manual_ncs_link_change() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'MANUAL_NCS_LINK_RECEIPT_IS_IMMUTABLE';
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger
   WHERE tgrelid='cs.manual_ncs_link_import'::regclass
     AND tgname='immutable_manual_ncs_link_import') THEN
  CREATE TRIGGER immutable_manual_ncs_link_import
  BEFORE UPDATE OR DELETE ON cs.manual_ncs_link_import
  FOR EACH ROW EXECUTE FUNCTION cs.reject_manual_ncs_link_change();
 END IF;
END $$;

CREATE OR REPLACE FUNCTION cs.manual_ncs_link_case_v1(
 identity text, role text, chosen_duty integer, chosen_code text)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object(
  'posting_identity',s.posting_identity,
  'role_id',s.role_id,
  'duty_index',chosen_duty,
  'competency_code',n.code,
  'context',jsonb_build_object(
    'policy_id',s.policy_id,
    'scope_binding_hash',s.binding_hash,
    'source_id',s.source_id,
    'source_posting_id',s.source_posting_id,
    'snapshot_run_id',s.snapshot_run_id,
    'source_hash',s.content_hash,
    'source_data',i.source_data,
    'title',s.title,
    'employer',s.employer,
    'role_name',s.role_name,
    'role_evidence_ids',s.role_evidence_ids,
    'item_id',i.item_id,
    'revision_id',r.revision_id,
    'extraction_hash',enrichment.hash(r.extraction::text),
    'duty',r.extraction->'duties'->chosen_duty,
    'ncs_run_id',n.run_id,
    'ncs_name',n.name,
    'ncs_definition',n.definition,
    'ncs_occupation_code',n.occupation_code,
    'ncs_occupation_name',n.occupation_name,
    'ncs_catalog_row_hash',enrichment.hash(to_jsonb(n)::text),
    'expected_candidate_id',enrichment.hash(
      jsonb_build_array(r.revision_id,n.code,chosen_duty)::text),
    'existing_candidate_origin',c.origin,
    'existing_candidate_reason',c.reason,
    'expected_link_decision_id',ld.decision_id),
  'decision',NULL,
  'reason','',
  'notes','')
 FROM cs.current_scope s
 JOIN enrichment.extraction_revision r ON r.revision_id=s.revision_id
 JOIN enrichment.item i ON i.item_id=r.item_id
 JOIN enrichment.batch b ON b.batch_id=i.batch_id
 JOIN enrichment.latest_extraction_decision ed ON ed.revision_id=r.revision_id
  AND ed.decision='ACCEPT'
 JOIN ingestion.latest_ready_run ready_ncs ON ready_ncs.source_id='ncs_competency'
 JOIN enrichment.ncs_catalog n ON n.run_id=ready_ncs.run_id AND n.code=chosen_code
 LEFT JOIN enrichment.link_candidate c ON c.candidate_id=enrichment.hash(
      jsonb_build_array(r.revision_id,n.code,chosen_duty)::text)
 LEFT JOIN enrichment.latest_link_decision ld ON ld.candidate_id=c.candidate_id
 WHERE s.posting_identity=identity AND s.role_id=role
   AND s.source_id='job_alio' AND s.scope_status='IN_SCOPE'
   AND s.content_hash=i.source_hash AND b.mode='ENRICH'
   AND b.ncs_run_id=ready_ncs.run_id
   AND nullif(btrim(coalesce(n.definition,'')),'') IS NOT NULL
   AND chosen_duty>=0
   AND coalesce(r.extraction->'duties'->chosen_duty->'position_ids','[]'::jsonb) ? role
$$;

-- selection.json is an array of exact, zero-based duty/code choices. Each
-- choice creates one frozen review case, rather than a keyword-generated match.
CREATE OR REPLACE FUNCTION cs.prepare_manual_ncs_link_review_v1(
 selections jsonb, actor text) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE selection jsonb; cases jsonb:='[]'::jsonb; frozen jsonb;
 index_no integer; BEGIN
 IF jsonb_typeof(selections) IS DISTINCT FROM 'array'
    OR jsonb_array_length(selections) NOT BETWEEN 1 AND 100
    OR nullif(btrim(coalesce(actor,'')),'') IS NULL
 THEN RAISE EXCEPTION 'INVALID_MANUAL_NCS_LINK_SELECTION'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(selections) x
   WHERE jsonb_typeof(x) IS DISTINCT FROM 'object'
      OR x-ARRAY['posting_identity','role_id','duty_index','competency_code']<>'{}'::jsonb
      OR nullif(x->>'posting_identity','') IS NULL
      OR nullif(x->>'role_id','') IS NULL
      OR nullif(x->>'competency_code','') IS NULL
      OR jsonb_typeof(x->'duty_index') IS DISTINCT FROM 'number'
      OR (x->>'duty_index') !~ '^[0-9]+$')
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(selections) x
       GROUP BY x->>'posting_identity',x->>'role_id',x->>'duty_index',x->>'competency_code'
       HAVING count(*)>1)
 THEN RAISE EXCEPTION 'INVALID_OR_DUPLICATE_MANUAL_NCS_LINK_SELECTION'; END IF;
 FOR selection IN SELECT x FROM jsonb_array_elements(selections) x LOOP
  index_no:=(selection->>'duty_index')::integer;
  frozen:=cs.manual_ncs_link_case_v1(selection->>'posting_identity',
      selection->>'role_id',index_no,selection->>'competency_code');
  IF frozen IS NULL THEN RAISE EXCEPTION 'MANUAL_NCS_LINK_CONTEXT_NOT_CURRENT_OR_DUTY_NOT_ROLE_BOUND: %',selection; END IF;
  cases:=cases||jsonb_build_array(frozen);
 END LOOP;
 RETURN jsonb_build_object('contract','cs-manual-ncs-link-v1',
   'prepared_by',actor,'reviewer','','reviewer_kind','human',
   'selections',selections,'cases',cases);
END $$;

CREATE OR REPLACE FUNCTION cs.apply_manual_ncs_link_review_v1(packet jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE import_key text:=enrichment.hash(packet::text);
 who text:=packet->>'reviewer'; kind text:=packet->>'reviewer_kind';
 case_row jsonb; expected jsonb; selection jsonb; choice text; why text; notes text;
 existing enrichment.link_candidate%ROWTYPE;
 latest enrichment.link_decision%ROWTYPE;
 candidate text; new_count integer:=0; decision_count integer:=0;
 unchanged_count integer:=0; result jsonb; BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('cs-manual-ncs-link-import',0));
 IF packet->>'contract' IS DISTINCT FROM 'cs-manual-ncs-link-v1'
    OR nullif(btrim(coalesce(packet->>'prepared_by','')),'') IS NULL
    OR nullif(btrim(coalesce(who,'')),'') IS NULL
    OR kind IS NULL OR kind NOT IN ('human','assistant','policy')
    OR jsonb_typeof(packet->'selections') IS DISTINCT FROM 'array'
    OR jsonb_typeof(packet->'cases') IS DISTINCT FROM 'array'
    OR jsonb_array_length(packet->'cases') NOT BETWEEN 1 AND 100
    OR jsonb_array_length(packet->'selections')<>jsonb_array_length(packet->'cases')
 THEN RAISE EXCEPTION 'INVALID_NAMED_MANUAL_NCS_LINK_PACKET'; END IF;
 SELECT counts INTO result FROM cs.manual_ncs_link_import WHERE import_id=import_key;
 IF FOUND THEN RETURN result||jsonb_build_object('replayed',true,'import_id',import_key); END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(packet->'cases') x
   GROUP BY x->>'posting_identity',x->>'role_id',x->>'duty_index',x->>'competency_code'
   HAVING count(*)>1)
 THEN RAISE EXCEPTION 'DUPLICATE_MANUAL_NCS_LINK_CASE'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(packet->'selections') x
   WHERE jsonb_typeof(x) IS DISTINCT FROM 'object'
      OR x-ARRAY['posting_identity','role_id','duty_index','competency_code']<>'{}'::jsonb
      OR nullif(x->>'posting_identity','') IS NULL
      OR nullif(x->>'role_id','') IS NULL
      OR nullif(x->>'competency_code','') IS NULL
      OR jsonb_typeof(x->'duty_index') IS DISTINCT FROM 'number'
      OR (x->>'duty_index') !~ '^[0-9]+$')
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(packet->'selections') x
       GROUP BY x->>'posting_identity',x->>'role_id',x->>'duty_index',x->>'competency_code'
       HAVING count(*)>1)
 THEN RAISE EXCEPTION 'INVALID_OR_DUPLICATE_MANUAL_NCS_LINK_SELECTION'; END IF;
 -- Validate all frozen cases before making any proposal or decision.
 FOR case_row IN SELECT x FROM jsonb_array_elements(packet->'cases') x LOOP
  IF jsonb_typeof(case_row) IS DISTINCT FROM 'object'
     OR case_row-ARRAY['posting_identity','role_id','duty_index','competency_code',
                       'context','decision','reason','notes']<>'{}'::jsonb
     OR (case_row->>'duty_index') !~ '^[0-9]+$'
  THEN RAISE EXCEPTION 'INVALID_MANUAL_NCS_LINK_CASE'; END IF;
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(packet->'selections') x
    WHERE x->>'posting_identity'=case_row->>'posting_identity'
      AND x->>'role_id'=case_row->>'role_id'
      AND x->>'duty_index'=case_row->>'duty_index'
      AND x->>'competency_code'=case_row->>'competency_code')
  THEN RAISE EXCEPTION 'MANUAL_NCS_LINK_SELECTION_CHANGED'; END IF;
  expected:=cs.manual_ncs_link_case_v1(case_row->>'posting_identity',
     case_row->>'role_id',(case_row->>'duty_index')::integer,
     case_row->>'competency_code');
  IF expected IS NULL THEN RAISE EXCEPTION 'MANUAL_NCS_LINK_CONTEXT_NOT_CURRENT_OR_DUTY_NOT_ROLE_BOUND'; END IF;
  IF case_row-ARRAY['decision','reason','notes'] IS DISTINCT FROM
      expected-ARRAY['decision','reason','notes']
  THEN RAISE EXCEPTION 'MANUAL_NCS_LINK_CONTEXT_OR_DEFINITION_CHANGED'; END IF;
  choice:=case_row->>'decision';
  IF choice IS NULL THEN CONTINUE; END IF;
  why:=case_row->>'reason'; notes:=case_row->>'notes';
  IF choice NOT IN ('ACCEPT','REJECT')
     OR nullif(btrim(coalesce(why,'')),'') IS NULL
     OR nullif(btrim(coalesce(notes,'')),'') IS NULL
  THEN RAISE EXCEPTION 'EXPLICIT_MANUAL_NCS_LINK_REASON_AND_NOTES_REQUIRED'; END IF;
  IF case_row#>>'{context,existing_candidate_origin}' IS NOT NULL AND
     case_row#>>'{context,existing_candidate_origin}'<>'reviewer'
  THEN RAISE EXCEPTION 'EXISTING_MODEL_CANDIDATE_USES_LINK_REVIEW_PACKET'; END IF;
  IF case_row#>>'{context,existing_candidate_reason}' IS NOT NULL AND
     case_row#>>'{context,existing_candidate_reason}'<>why
  THEN RAISE EXCEPTION 'LINK_CANDIDATE_IS_IMMUTABLE'; END IF;
  PERFORM enrichment.verify_item_input(case_row#>>'{context,item_id}');
 END LOOP;
 FOR case_row IN SELECT x FROM jsonb_array_elements(packet->'cases') x LOOP
  choice:=case_row->>'decision'; IF choice IS NULL THEN CONTINUE; END IF;
  why:=case_row->>'reason'; notes:=case_row->>'notes';
  candidate:=case_row#>>'{context,expected_candidate_id}';
  SELECT * INTO existing FROM enrichment.link_candidate WHERE candidate_id=candidate;
  IF existing.candidate_id IS NULL THEN
   candidate:=enrichment.propose_link(case_row#>>'{context,revision_id}',
      case_row->>'competency_code',(case_row->>'duty_index')::integer,
      why,who,'reviewer');
   new_count:=new_count+1;
  END IF;
  SELECT d.* INTO latest FROM enrichment.latest_link_decision d
     WHERE d.candidate_id=candidate;
  IF latest.decision_id IS NOT NULL AND latest.decision=choice
     AND latest.reviewer=who AND latest.reviewer_kind=kind
     AND latest.notes=notes THEN
   unchanged_count:=unchanged_count+1;
  ELSE
   PERFORM enrichment.decide_link(candidate,choice,who,kind,notes);
   decision_count:=decision_count+1;
  END IF;
 END LOOP;
 IF decision_count+unchanged_count=0 THEN
  RAISE EXCEPTION 'NO_EXPLICIT_MANUAL_NCS_LINK_DECISIONS';
 END IF;
 result:=jsonb_build_object('new_candidates',new_count,
   'new_decisions',decision_count,'unchanged_decisions',unchanged_count,
   'reviewer',who,'reviewer_kind',kind);
 INSERT INTO cs.manual_ncs_link_import(import_id,reviewer,reviewer_kind,packet,counts)
 VALUES(import_key,who,kind,packet,result);
 RETURN result||jsonb_build_object('replayed',false,'import_id',import_key);
END $$;

COMMENT ON FUNCTION cs.apply_manual_ncs_link_review_v1(jsonb) IS
'Only an explicitly named review of a current accepted ALIO role/duty and complete current NCS definition can append a candidate and decision. Receipt replay is idempotent; publishing remains separate.';
COMMIT;
