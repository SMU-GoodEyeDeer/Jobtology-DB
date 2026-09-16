-- Native JSON-file transport for explicit position-level scope reviews.
-- The exported source/role context is immutable; only decision, family and
-- notes may be edited. The import is one PostgreSQL transaction.
BEGIN;

CREATE TABLE IF NOT EXISTS cs.scope_review_import (
 import_id text PRIMARY KEY,
 reviewer text NOT NULL,
 reviewer_kind text NOT NULL,
 packet jsonb NOT NULL,
 counts jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION cs.reject_scope_review_change() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'SCOPE_REVIEW_RECEIPT_IS_IMMUTABLE';
END $$;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_trigger
   WHERE tgrelid='cs.scope_review_import'::regclass
     AND tgname='immutable_scope_review_import') THEN
  CREATE TRIGGER immutable_scope_review_import
  BEFORE UPDATE OR DELETE ON cs.scope_review_import
  FOR EACH ROW EXECUTE FUNCTION cs.reject_scope_review_change();
 END IF;
END $$;

-- Full source and role context is included, rather than just its digest. The
-- digest in scope_screen also binds the current policy, source hash and role.
CREATE OR REPLACE FUNCTION cs.scope_review_case_v1(identity text, role text)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object(
  'posting_identity',s.posting_identity,
  'role_id',s.role_id,
  'context',to_jsonb(s),
  'expected_decision_id',d.decision_id,
  'decision',NULL,
  'family',NULL,
  'notes','')
 FROM cs.scope_screen s
 LEFT JOIN LATERAL (
  SELECT decision_id FROM cs.scope_decision d
  WHERE d.policy_id=s.policy_id AND d.posting_identity=s.posting_identity
    AND d.role_id=s.role_id AND d.binding_hash=s.binding_hash
  ORDER BY decision_id DESC LIMIT 1
 ) d ON true
 WHERE s.posting_identity=identity AND s.role_id=role
$$;

CREATE OR REPLACE FUNCTION cs.prepare_scope_review_v1(
 source_filter text, status_filter text, posting_identities text,
 cap integer, actor text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE rows jsonb; n integer; identities text[]; BEGIN
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 1000
    OR nullif(btrim(coalesce(actor,'')),'') IS NULL
    OR coalesce(status_filter,'') NOT IN ('','NEEDS_REVIEW','IN_SCOPE',
      'OUT_OF_SCOPE','OUT_OF_SCOPE_CANDIDATE')
 THEN RAISE EXCEPTION 'INVALID_SCOPE_REVIEW_SELECTION'; END IF;
 identities:=CASE WHEN coalesce(posting_identities,'')=''
  THEN '{}'::text[] ELSE string_to_array(posting_identities,'|') END;
 IF EXISTS(SELECT 1 FROM unnest(identities) x WHERE nullif(btrim(x),'') IS NULL)
    OR (SELECT count(*) FROM unnest(identities)) <>
       (SELECT count(DISTINCT x) FROM unnest(identities) x)
    OR (cardinality(identities)>0 AND (SELECT count(DISTINCT c.posting_identity)
       FROM cs.current_scope c WHERE c.posting_identity=ANY(identities))<>cardinality(identities))
 THEN RAISE EXCEPTION 'UNKNOWN_OR_DUPLICATE_SCOPE_POSTING_IDENTITY'; END IF;
 SELECT count(*),coalesce(jsonb_agg(
   cs.scope_review_case_v1(c.posting_identity,c.role_id)
   ORDER BY c.source_id,c.posting_identity,c.role_id),'[]'::jsonb)
 INTO n,rows FROM cs.current_scope c
 WHERE (coalesce(source_filter,'')='' OR c.source_id=source_filter)
   AND (coalesce(status_filter,'')='' OR c.scope_status=status_filter)
   AND (cardinality(identities)=0 OR c.posting_identity=ANY(identities));
 IF n NOT BETWEEN 1 AND cap THEN
  RAISE EXCEPTION 'SCOPE_REVIEW_SELECTION_EMPTY_OR_EXCEEDS_CAP: %',n;
 END IF;
 RETURN jsonb_build_object('contract','cs-scope-review-v1',
  'policy_id','cs-it-ai-data-v1',
  'source_filter',coalesce(source_filter,''),
  'status_filter',coalesce(status_filter,''),
  'posting_identities',identities,
  'prepared_by',actor,
  'reviewer','',
  'reviewer_kind','human',
  'cases',rows);
END $$;

CREATE OR REPLACE FUNCTION cs.apply_scope_review_v1(packet jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE import_key text:=enrichment.hash(packet::text);
 who text:=packet->>'reviewer'; kind text:=packet->>'reviewer_kind';
 case_row jsonb; expected jsonb; current_row cs.scope_screen%ROWTYPE;
 choice text; family_name text; notes text;
 decision_count integer:=0; unchanged_count integer:=0;
 decision_key bigint; previous cs.scope_decision%ROWTYPE;
 result jsonb; BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('cs-scope-review-import',0));
 IF packet->>'contract' IS DISTINCT FROM 'cs-scope-review-v1'
    OR packet->>'policy_id' IS DISTINCT FROM 'cs-it-ai-data-v1'
    OR nullif(btrim(coalesce(who,'')),'') IS NULL
    OR kind IS NULL OR kind NOT IN ('human','assistant','policy')
    OR jsonb_typeof(packet->'cases') IS DISTINCT FROM 'array'
    OR jsonb_array_length(packet->'cases') NOT BETWEEN 1 AND 1000
 THEN RAISE EXCEPTION 'INVALID_NAMED_SCOPE_REVIEW_PACKET'; END IF;
 SELECT counts INTO result FROM cs.scope_review_import WHERE import_id=import_key;
 IF FOUND THEN
  RETURN result||jsonb_build_object('replayed',true,'import_id',import_key);
 END IF;
 IF EXISTS (
   SELECT 1 FROM jsonb_array_elements(packet->'cases') c
   GROUP BY c->>'posting_identity',c->>'role_id' HAVING count(*)>1
 ) THEN RAISE EXCEPTION 'DUPLICATE_SCOPE_REVIEW_CASE'; END IF;
 FOR case_row IN SELECT jsonb_array_elements(packet->'cases') LOOP
  IF jsonb_typeof(case_row) IS DISTINCT FROM 'object'
     OR nullif(case_row->>'posting_identity','') IS NULL
     OR nullif(case_row->>'role_id','') IS NULL
  THEN RAISE EXCEPTION 'INVALID_SCOPE_REVIEW_CASE'; END IF;
  SELECT * INTO STRICT current_row FROM cs.scope_screen s
   WHERE s.posting_identity=case_row->>'posting_identity'
     AND s.role_id=case_row->>'role_id';
  expected:=cs.scope_review_case_v1(
    case_row->>'posting_identity',case_row->>'role_id');
  IF (case_row-ARRAY['decision','family','notes']) IS DISTINCT FROM
     (expected-ARRAY['decision','family','notes'])
  THEN RAISE EXCEPTION 'SCOPE_REVIEW_CONTEXT_OR_DECISION_CHANGED'; END IF;
  choice:=case_row->>'decision';
  IF choice IS NULL THEN CONTINUE; END IF;
  family_name:=case_row->>'family';
  notes:=case_row->>'notes';
  IF choice NOT IN ('IN_SCOPE','OUT_OF_SCOPE','NEEDS_REVIEW')
     OR nullif(btrim(coalesce(notes,'')),'') IS NULL
     OR (choice='IN_SCOPE' AND (family_name IS NULL OR family_name NOT IN
       ('SOFTWARE','IT_SYSTEMS','SECURITY','DATA','AI')))
     OR (choice<>'IN_SCOPE' AND family_name IS NOT NULL)
  THEN RAISE EXCEPTION 'INVALID_EXPLICIT_SCOPE_REVIEW_DECISION'; END IF;
  SELECT * INTO previous FROM cs.scope_decision d
   WHERE d.policy_id=current_row.policy_id
     AND d.posting_identity=current_row.posting_identity
     AND d.role_id=current_row.role_id
     AND d.binding_hash=current_row.binding_hash
   ORDER BY decision_id DESC LIMIT 1;
  decision_key:=cs.decide_scope_v1(current_row.posting_identity,
    current_row.role_id,current_row.binding_hash,choice,family_name,
    who,kind,notes);
  IF previous.decision_id IS NOT NULL AND
     previous.decision_id=decision_key THEN
   unchanged_count:=unchanged_count+1;
  ELSE
   decision_count:=decision_count+1;
  END IF;
 END LOOP;
 IF decision_count+unchanged_count=0 THEN
  RAISE EXCEPTION 'NO_EXPLICIT_SCOPE_REVIEW_DECISIONS';
 END IF;
 result:=jsonb_build_object('new_decisions',decision_count,
   'unchanged_decisions',unchanged_count,
   'reviewer',who,'reviewer_kind',kind);
 INSERT INTO cs.scope_review_import(import_id,reviewer,reviewer_kind,packet,counts)
 VALUES(import_key,who,kind,packet,result);
 RETURN result||jsonb_build_object('replayed',false,'import_id',import_key);
END $$;

COMMENT ON FUNCTION cs.apply_scope_review_v1(jsonb) IS
'Atomically verifies every exported role/source context and records only explicit scope decisions. Import receipts are immutable and exact packet replay is idempotent.';
COMMIT;
