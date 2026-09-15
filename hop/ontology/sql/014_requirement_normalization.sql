-- Typed conditions are separate, append-only interpretations of reviewed source atoms.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.requirement_normalization (
 normalization_id text PRIMARY KEY,
 normalization_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 source_claim_id text NOT NULL REFERENCES ontology.claim,
 node_index integer NOT NULL CHECK(node_index>=-1),
 parent_id text REFERENCES ontology.requirement_normalization,
 created_in_release text NOT NULL REFERENCES ontology.corpus_release,
 document jsonb NOT NULL,
 condition jsonb NOT NULL,
 source_binding jsonb NOT NULL,
 target_bindings jsonb NOT NULL,
 requirement_key text CHECK(requirement_key ~ '^[0-9a-f]{64}$'),
 key_payload jsonb,
 key_algorithm text NOT NULL DEFAULT 'sha256-jcs-requirement-v1',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((requirement_key IS NULL)=(key_payload IS NULL))
);
CREATE INDEX IF NOT EXISTS ontology_requirement_latest ON ontology.requirement_normalization(source_claim_id,node_index,normalization_no DESC);
CREATE TABLE IF NOT EXISTS ontology.requirement_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 normalization_id text NOT NULL REFERENCES ontology.requirement_normalization,
 decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant')),
 notes text NOT NULL CHECK(length(btrim(notes))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ontology_requirement_review_latest ON ontology.requirement_decision(normalization_id,decision_id DESC);
CREATE TABLE IF NOT EXISTS ontology.requirement_freeze (
 release_id text PRIMARY KEY REFERENCES ontology.review_freeze,
 normalization_cutoff bigint NOT NULL,
 decision_cutoff bigint NOT NULL,
 frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 policy_version text NOT NULL DEFAULT 'typed-source-atoms-v1'
);
CREATE TABLE IF NOT EXISTS ontology.requirement_selection (
 release_id text NOT NULL REFERENCES ontology.requirement_freeze,
 source_claim_id text NOT NULL,
 node_index integer NOT NULL,
 normalization_id text REFERENCES ontology.requirement_normalization,
 decision_id bigint REFERENCES ontology.requirement_decision,
 outcome text NOT NULL CHECK(outcome IN ('NOT_PROPOSED','PENDING','UNRESOLVED','REJECTED','TARGET_REVISION_MISMATCH','REVIEWED')),
 PRIMARY KEY(release_id,source_claim_id,node_index),
 FOREIGN KEY(release_id,source_claim_id) REFERENCES ontology.release_claim
);
CREATE TABLE IF NOT EXISTS ontology.requirement_membership (
 release_id text PRIMARY KEY REFERENCES ontology.requirement_freeze,
 manifest jsonb NOT NULL,
 manifest_hash text NOT NULL,
 bound_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['requirement_normalization','requirement_decision','requirement_freeze','requirement_selection','requirement_membership'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||name AND tgrelid=('ontology.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

-- This serializer implements the JCS subset used by the strict condition schema:
-- ASCII object keys, Unicode strings, booleans/null, arrays and 32-bit integers.
-- Reject unsupported numbers/keys instead of pretending to canonicalize all JSON.
CREATE OR REPLACE FUNCTION ontology.requirement_jcs_v1(v jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result text; BEGIN
 CASE jsonb_typeof(v)
 WHEN 'object' THEN
  IF EXISTS(SELECT 1 FROM jsonb_object_keys(v) k WHERE k !~ '^[A-Za-z_][A-Za-z0-9_]*$')
  THEN RAISE EXCEPTION 'REQUIREMENT_JCS_NON_ASCII_KEY'; END IF;
  SELECT '{'||coalesce(string_agg(to_jsonb(k)::text||':'||ontology.requirement_jcs_v1(x),',' ORDER BY k COLLATE "C"),'')||'}'
   INTO result FROM jsonb_each(v) e(k,x);
 WHEN 'array' THEN
  SELECT '['||coalesce(string_agg(ontology.requirement_jcs_v1(x),',' ORDER BY n),'')||']'
   INTO result FROM jsonb_array_elements(v) WITH ORDINALITY e(x,n);
 WHEN 'number' THEN
  IF v::text !~ '^-?[0-9]+$' OR (v::text)::numeric NOT BETWEEN -2147483648 AND 2147483647
  THEN RAISE EXCEPTION 'REQUIREMENT_JCS_UNSUPPORTED_NUMBER'; END IF;
  result:=((v::text)::integer)::text;
 ELSE result:=v::text;
 END CASE;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.normalize_condition_v1(value jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE c jsonb:=value; field text; sorted jsonb; BEGIN
 FOREACH field IN ARRAY ARRAY['accepted_major_groups','capability_ids','administrative_codes'] LOOP
  IF c ? field THEN
   SELECT coalesce(jsonb_agg(v ORDER BY v COLLATE "C"),'[]') INTO sorted
    FROM (SELECT DISTINCT jsonb_array_elements_text(c->field) v) entries;
   c:=jsonb_set(c,ARRAY[field],sorted);
  END IF;
 END LOOP;
 RETURN c;
END $$;

CREATE OR REPLACE FUNCTION ontology.requirement_key_payload_v1(c jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT CASE WHEN c->>'kind'='UNRESOLVED' THEN NULL
  WHEN c->>'kind' IN ('SKILL','LANGUAGE') THEN c-'target_kind'
  ELSE c END
$$;

CREATE OR REPLACE VIEW ontology.requirement_atom AS
SELECT m.release_id,m.entity_id,c.claim_id AS source_claim_id,c.posting_revision_id,n.node_index,n.text AS source_text,
 c.applicability,c.logic,c.category
FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id)
JOIN ontology.condition_node n USING(claim_id) WHERE c.kind='REQUIREMENT' AND n.operator='atom'
UNION ALL
SELECT m.release_id,m.entity_id,c.claim_id,c.posting_revision_id,-1,c.text,c.applicability,c.logic,c.category
FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id)
WHERE c.kind='REQUIREMENT' AND NOT EXISTS(SELECT 1 FROM ontology.condition_node n WHERE n.claim_id=c.claim_id);

CREATE OR REPLACE FUNCTION ontology.requirement_source_v1(claim text,idx integer) RETURNS jsonb
LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('source_claim_id',c.claim_id,'posting_revision_id',c.posting_revision_id,'node_index',idx,
  'source_text',CASE WHEN idx=-1 THEN c.text ELSE n.text END,'claim_hash',c.content_hash,
  'applicability',c.applicability,'logic',c.logic,'source_payload',c.payload,
  'positions',coalesce((SELECT jsonb_agg(p.position_id ORDER BY p.position_id) FROM ontology.claim_position p WHERE p.claim_id=c.claim_id),'[]'),
  'expression_nodes',coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY node_index) FROM ontology.condition_node t WHERE t.claim_id=c.claim_id),'[]'),
  'expression_edges',coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY parent_index,ordinal) FROM ontology.condition_child t WHERE t.claim_id=c.claim_id),'[]'),
  'evidence',coalesce((SELECT jsonb_agg(jsonb_build_object('part_index',e.part_index,'span',to_jsonb(s)) ORDER BY e.part_index)
   FROM (SELECT part_index,evidence_id FROM ontology.claim_evidence WHERE claim_id=c.claim_id AND idx=-1
    UNION ALL SELECT part_index,evidence_id FROM ontology.condition_evidence WHERE claim_id=c.claim_id AND node_index=idx) e
   JOIN ontology.evidence_span s USING(evidence_id)),'[]'))
 FROM ontology.claim c LEFT JOIN ontology.condition_node n ON n.claim_id=c.claim_id AND n.node_index=idx
 WHERE c.claim_id=claim AND c.kind='REQUIREMENT' AND
  ((idx=-1 AND NOT EXISTS(SELECT 1 FROM ontology.condition_node x WHERE x.claim_id=c.claim_id)) OR n.operator='atom')
$$;

-- References are checked against release-selected revisions, not whichever row is latest.
CREATE OR REPLACE FUNCTION ontology.requirement_targets_v1(id text,c jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE refs jsonb:='[]'; ref jsonb; v ontology.revision%ROWTYPE; result jsonb:='[]'; code text; BEGIN
 IF c->>'kind' IN ('SKILL','LANGUAGE','CREDENTIAL') THEN
  refs:=refs||jsonb_build_array(jsonb_build_object('role','target','entity_id',c->>'target_id'));
 END IF;
 IF c->>'context_id' IS NOT NULL THEN refs:=refs||jsonb_build_array(jsonb_build_object('role','context','entity_id',c->>'context_id')); END IF;
 IF c->>'proficiency_scheme_id' IS NOT NULL THEN refs:=refs||jsonb_build_array(jsonb_build_object('role','proficiency','entity_id',c->>'proficiency_scheme_id')); END IF;
 IF c->>'vocabulary_id' IS NOT NULL THEN refs:=refs||jsonb_build_array(jsonb_build_object('role','eligibility_vocabulary','entity_id',c->>'vocabulary_id')); END IF;
 FOR code IN SELECT jsonb_array_elements_text(coalesce(c->'capability_ids','[]')) LOOP
  refs:=refs||jsonb_build_array(jsonb_build_object('role','capability','entity_id',code));
 END LOOP;
 FOR code IN SELECT jsonb_array_elements_text(coalesce(c->'administrative_codes','[]')) LOOP
  IF (SELECT count(*) FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
   WHERE m.release_id=id AND r.kind='place' AND r.payload->>'administrative_code'=code)<>1
  THEN RAISE EXCEPTION 'UNKNOWN_OR_AMBIGUOUS_ADMINISTRATIVE_CODE: %',code; END IF;
  SELECT r.* INTO STRICT v FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
   WHERE m.release_id=id AND r.kind='place' AND r.payload->>'administrative_code'=code;
  refs:=refs||jsonb_build_array(jsonb_build_object('role','place','entity_id',v.entity_id));
 END LOOP;
 FOR ref IN SELECT x FROM jsonb_array_elements(refs) x ORDER BY x->>'role' COLLATE "C",x->>'entity_id' COLLATE "C" LOOP
  SELECT r.* INTO v FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id)
   WHERE m.release_id=id AND m.entity_id=ref->>'entity_id';
  IF NOT FOUND THEN RAISE EXCEPTION 'REQUIREMENT_TARGET_NOT_IN_RELEASE: %',ref; END IF;
  IF v.payload_hash<>ontology.hash(v.payload) THEN RAISE EXCEPTION 'REQUIREMENT_TARGET_CONTENT_CHANGED'; END IF;
  IF ref->>'role'='target' AND (
    (c->>'kind'='CREDENTIAL' AND v.kind<>'qualification') OR
    (c->>'kind' IN ('SKILL','LANGUAGE') AND v.kind<>CASE c->>'target_kind' WHEN 'Skill' THEN 'skill' ELSE 'ncsCompetency' END) OR
    (c->>'kind'='LANGUAGE' AND (v.kind<>'skill' OR v.payload->>'kind' IS DISTINCT FROM 'LANGUAGE')))
   OR (ref->>'role'='context' AND v.kind NOT IN ('occupation','skill'))
   OR (ref->>'role'='capability' AND v.kind NOT IN ('skill','ncsCompetency'))
  THEN RAISE EXCEPTION 'REQUIREMENT_TARGET_TYPE_MISMATCH: %',ref; END IF;
  IF ref->>'role'='proficiency' AND (v.kind<>'conceptScheme' OR v.payload->>'kind' IS DISTINCT FROM 'PROFICIENCY'
   OR NOT coalesce(v.payload->'ordered_values' @> jsonb_build_array((c->>'minimum_proficiency')::integer),false))
  THEN RAISE EXCEPTION 'UNKNOWN_PROFICIENCY_LEVEL'; END IF;
  IF ref->>'role'='eligibility_vocabulary' AND (v.kind<>'conceptScheme' OR v.payload->>'kind' IS DISTINCT FROM 'ELIGIBILITY'
   OR v.payload->>'review_state' IS DISTINCT FROM 'HUMAN_ACCEPTED'
   OR NOT coalesce(v.payload->'codes' ? (c->>'code'),false))
  THEN RAISE EXCEPTION 'ELIGIBILITY_CODE_NOT_REVIEWED'; END IF;
  result:=result||jsonb_build_array(ref||jsonb_build_object('revision_id',v.revision_id,'payload_hash',v.payload_hash));
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.capture_requirement_v1(document jsonb) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE errors jsonb; source jsonb; c jsonb; refs jsonb; payload jsonb; key text; id text; previous text; BEGIN
 errors:=enrichment.schema_issues_v6(document,(SELECT schema FROM ontology.requirement_contract WHERE version='hop-requirement-normalization-v1'));
 IF errors<>'[]' THEN RAISE EXCEPTION 'INVALID_REQUIREMENT_DOCUMENT: %',errors; END IF;
 PERFORM ontology.require_preparing(document->>'release_id');
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=document->>'release_id' AND manifest IS NOT NULL)
 THEN RAISE EXCEPTION 'REQUIREMENT_RELEASE_ALREADY_SEALED'; END IF;
 PERFORM ontology.check_frozen_sources(document->>'release_id');
 PERFORM ontology.verify_claims(document->>'release_id');
 IF NOT EXISTS(SELECT 1 FROM ontology.requirement_atom WHERE release_id=document->>'release_id'
  AND source_claim_id=document->>'source_claim_id' AND node_index=(document->>'node_index')::integer)
 THEN RAISE EXCEPTION 'UNKNOWN_RELEASE_REQUIREMENT_ATOM'; END IF;
 -- Serialize competing proposals and their reviews for this immutable source group.
 PERFORM 1 FROM ontology.claim WHERE claim_id=document->>'source_claim_id' FOR UPDATE;
 source:=ontology.requirement_source_v1(document->>'source_claim_id',(document->>'node_index')::integer);
 IF source IS NULL OR jsonb_array_length(source->'evidence')=0 THEN RAISE EXCEPTION 'REQUIREMENT_SOURCE_EVIDENCE_REQUIRED'; END IF;
 IF nullif(btrim(document->>'actor'),'') IS NULL OR nullif(btrim(document->>'reason'),'') IS NULL
  OR nullif(btrim(document->>'resolver_version'),'') IS NULL THEN RAISE EXCEPTION 'REQUIREMENT_PROVENANCE_REQUIRED'; END IF;
 c:=ontology.normalize_condition_v1(document->'condition');
 IF c->>'kind' IN ('SKILL','LANGUAGE') AND ((c->>'proficiency_scheme_id' IS NULL)<>(c->>'minimum_proficiency' IS NULL))
 THEN RAISE EXCEPTION 'INCOMPLETE_PROFICIENCY'; END IF;
 IF c->>'kind'='LANGUAGE' AND c->>'target_kind'<>'Skill' THEN RAISE EXCEPTION 'LANGUAGE_REQUIRES_LANGUAGE_SKILL'; END IF;
 IF c->>'kind'='EXPERIENCE' AND (c->>'maximum_months')::integer<(c->>'minimum_months')::integer
 THEN RAISE EXCEPTION 'EXPERIENCE_RANGE_ORDER'; END IF;
 IF c->>'kind'='AVAILABILITY' AND c->>'earliest_start' IS NOT NULL AND
  ((c->>'earliest_start') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' OR to_char((c->>'earliest_start')::date,'YYYY-MM-DD')<>c->>'earliest_start')
 THEN RAISE EXCEPTION 'INVALID_AVAILABILITY_DATE'; END IF;
 IF (c->>'kind'='UNRESOLVED' AND c->>'mention' IS DISTINCT FROM source->>'source_text') OR
  (c->>'kind'='ELIGIBILITY' AND c->>'source_text' IS DISTINCT FROM source->>'source_text')
 THEN RAISE EXCEPTION 'REQUIREMENT_EXACT_SOURCE_TEXT_REQUIRED'; END IF;
 IF document->>'polarity'<>'NO_CONSTRAINT' AND (
  (c->>'kind'='EXPERIENCE' AND c->>'minimum_months' IS NULL AND c->>'maximum_months' IS NULL) OR
  (c->>'kind'='EDUCATION' AND c->>'minimum_degree' IS NULL AND c->'accepted_major_groups'='[]' AND c->>'accepts_expected_graduate' IS NULL) OR
  (c->>'kind'='PROJECT' AND c->>'minimum_count' IS NULL AND c->>'portfolio_required' IS NULL AND c->'capability_ids'='[]') OR
  (c->>'kind'='LOCATION' AND c->'administrative_codes'='[]' AND c->>'work_mode'='UNKNOWN') OR
  (c->>'kind'='AVAILABILITY' AND c->>'earliest_start' IS NULL AND c->>'schedule_text' IS NULL))
 THEN RAISE EXCEPTION 'EMPTY_TYPED_CONDITION'; END IF;
 refs:=ontology.requirement_targets_v1(document->>'release_id',c);
 payload:=ontology.requirement_key_payload_v1(c);
 key:=encode(sha256(convert_to(ontology.requirement_jcs_v1(payload),'UTF8')),'hex');
 document:=jsonb_set(document,'{condition}',c);
 id:=ontology.hash(jsonb_build_object('document',document-'release_id','source_binding',source,'target_bindings',refs));
 IF EXISTS(SELECT 1 FROM ontology.requirement_normalization WHERE normalization_id=id) THEN RETURN id; END IF;
 SELECT n.normalization_id INTO previous FROM ontology.requirement_normalization n
  WHERE n.source_claim_id=capture_requirement_v1.document->>'source_claim_id'
   AND n.node_index=(capture_requirement_v1.document->>'node_index')::integer ORDER BY n.normalization_no DESC LIMIT 1;
 IF document->>'parent_id' IS DISTINCT FROM previous THEN RAISE EXCEPTION 'STALE_REQUIREMENT_PARENT'; END IF;
 INSERT INTO ontology.requirement_normalization(normalization_id,source_claim_id,node_index,parent_id,created_in_release,
  document,condition,source_binding,target_bindings,requirement_key,key_payload)
 VALUES(id,document->>'source_claim_id',(document->>'node_index')::integer,document->>'parent_id',document->>'release_id',
  document,c,source,refs,key,payload);
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION ontology.decide_requirement_v1(id text,choice text,who text,kind text,explanation text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE target ontology.requirement_normalization%ROWTYPE; newest text; result bigint; BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 SELECT * INTO STRICT target FROM ontology.requirement_normalization WHERE normalization_id=id;
 PERFORM 1 FROM ontology.claim WHERE claim_id=target.source_claim_id FOR UPDATE;
 SELECT normalization_id INTO newest FROM ontology.requirement_normalization
  WHERE source_claim_id=target.source_claim_id AND node_index=target.node_index ORDER BY normalization_no DESC LIMIT 1;
 IF choice='ACCEPT' AND newest<>id THEN RAISE EXCEPTION 'REQUIREMENT_NORMALIZATION_SUPERSEDED'; END IF;
 IF who=target.document->>'actor' THEN RAISE EXCEPTION 'INDEPENDENT_REQUIREMENT_REVIEW_REQUIRED'; END IF;
 IF choice='ACCEPT' AND (target.condition->>'kind'='UNRESOLVED' OR target.document->>'necessity'='UNSPECIFIED')
 THEN RAISE EXCEPTION 'UNRESOLVED_REQUIREMENT_CANNOT_BE_ACCEPTED'; END IF;
 INSERT INTO ontology.requirement_decision(normalization_id,decision,reviewer,reviewer_kind,notes)
 VALUES(id,choice,who,kind,explanation) RETURNING decision_id INTO result;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION ontology.requirement_candidates_v1(id text)
RETURNS TABLE(release_id text,source_claim_id text,node_index integer,normalization_id text,decision_id bigint,outcome text)
LANGUAGE sql STABLE AS $$
 SELECT a.release_id,a.source_claim_id,a.node_index,n.normalization_id,d.decision_id,
  CASE WHEN n.normalization_id IS NULL THEN 'NOT_PROPOSED'
   WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(n.target_bindings) t LEFT JOIN ontology.release_revision m
    ON m.release_id=id AND m.entity_id=t->>'entity_id' WHERE m.revision_id IS DISTINCT FROM t->>'revision_id') THEN 'TARGET_REVISION_MISMATCH'
   WHEN d.decision='REJECT' THEN 'REJECTED'
   WHEN n.condition->>'kind'='UNRESOLVED' THEN 'UNRESOLVED'
   WHEN d.decision='ACCEPT' THEN 'REVIEWED' ELSE 'PENDING' END
 FROM ontology.requirement_atom a JOIN ontology.requirement_freeze f USING(release_id)
 LEFT JOIN LATERAL (SELECT * FROM ontology.requirement_normalization p
  WHERE p.source_claim_id=a.source_claim_id AND p.node_index=a.node_index AND p.normalization_no<=f.normalization_cutoff
  ORDER BY normalization_no DESC LIMIT 1) n ON true
 LEFT JOIN LATERAL (SELECT * FROM ontology.requirement_decision r WHERE r.normalization_id=n.normalization_id
  AND r.decision_id<=f.decision_cutoff ORDER BY decision_id DESC LIMIT 1) d ON true
 WHERE a.release_id=id
$$;

CREATE OR REPLACE FUNCTION ontology.requirement_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','typed-source-atoms-v1','freeze',(SELECT to_jsonb(f) FROM ontology.requirement_freeze f WHERE release_id=id),
  'atom_count',(SELECT count(*) FROM ontology.requirement_selection WHERE release_id=id),
  'selection_hash',ontology.hash(coalesce((SELECT jsonb_agg(jsonb_build_object('selection',to_jsonb(s),
   'normalization',to_jsonb(n),'review',to_jsonb(d),'source_binding',ontology.requirement_source_v1(s.source_claim_id,s.node_index))
   ORDER BY s.source_claim_id,s.node_index)
   FROM ontology.requirement_selection s LEFT JOIN ontology.requirement_normalization n USING(normalization_id)
   LEFT JOIN ontology.requirement_decision d ON d.decision_id=s.decision_id WHERE s.release_id=id),'[]')))
$$;

CREATE OR REPLACE FUNCTION ontology.verify_requirements_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE n ontology.requirement_normalization%ROWTYPE; expected jsonb; actual jsonb; BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=id) THEN RETURN; END IF;
 SELECT jsonb_agg(to_jsonb(s) ORDER BY source_claim_id,node_index) INTO expected FROM ontology.requirement_candidates_v1(id) s;
 SELECT jsonb_agg(to_jsonb(s) ORDER BY source_claim_id,node_index) INTO actual FROM ontology.requirement_selection s WHERE release_id=id;
 IF expected IS DISTINCT FROM actual THEN RAISE EXCEPTION 'REQUIREMENT_SELECTION_MISMATCH'; END IF;
 FOR n IN SELECT p.* FROM ontology.requirement_selection s JOIN ontology.requirement_normalization p USING(normalization_id) WHERE s.release_id=id LOOP
  IF n.source_binding IS DISTINCT FROM ontology.requirement_source_v1(n.source_claim_id,n.node_index)
   OR n.condition IS DISTINCT FROM ontology.normalize_condition_v1(n.document->'condition')
   OR n.key_payload IS DISTINCT FROM ontology.requirement_key_payload_v1(n.condition)
   OR n.requirement_key IS DISTINCT FROM encode(sha256(convert_to(ontology.requirement_jcs_v1(n.key_payload),'UTF8')),'hex')
   OR n.normalization_id<>ontology.hash(jsonb_build_object('document',n.document-'release_id','source_binding',n.source_binding,'target_bindings',n.target_bindings))
  THEN RAISE EXCEPTION 'REQUIREMENT_NORMALIZATION_CHANGED'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(n.target_bindings) t LEFT JOIN ontology.revision r ON r.revision_id=t->>'revision_id'
   WHERE r.entity_id IS DISTINCT FROM t->>'entity_id' OR r.payload_hash IS DISTINCT FROM t->>'payload_hash' OR r.payload_hash IS DISTINCT FROM ontology.hash(r.payload))
  THEN RAISE EXCEPTION 'REQUIREMENT_TARGET_CONTENT_CHANGED'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM ontology.requirement_membership WHERE release_id=id AND manifest=ontology.requirement_manifest_v1(id) AND manifest_hash=ontology.hash(manifest))
 THEN RAISE EXCEPTION 'REQUIREMENT_MEMBERSHIP_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.freeze_requirements_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE manifest jsonb; BEGIN
 PERFORM ontology.require_preparing(id); PERFORM ontology.check_frozen_sources(id);
 PERFORM ontology.verify_observation_membership_v1(id); PERFORM ontology.verify_claims(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'ASSEMBLE_REVIEWED_CLAIMS_FIRST'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=id) THEN PERFORM ontology.verify_requirements_v1(id); RETURN; END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release r WHERE r.release_id=id AND r.manifest IS NOT NULL) THEN RAISE EXCEPTION 'REQUIREMENT_RELEASE_ALREADY_SEALED'; END IF;
 LOCK TABLE ontology.requirement_normalization,ontology.requirement_decision IN SHARE MODE;
 INSERT INTO ontology.requirement_freeze(release_id,normalization_cutoff,decision_cutoff)
 SELECT id,(SELECT coalesce(max(normalization_no),0) FROM ontology.requirement_normalization),(SELECT coalesce(max(decision_id),0) FROM ontology.requirement_decision);
 INSERT INTO ontology.requirement_selection SELECT * FROM ontology.requirement_candidates_v1(id);
 manifest:=ontology.requirement_manifest_v1(id);
 INSERT INTO ontology.requirement_membership(release_id,manifest,manifest_hash) VALUES(id,manifest,ontology.hash(manifest));
 PERFORM ontology.verify_requirements_v1(id);
END $$;

CREATE OR REPLACE VIEW ontology.typed_requirement_issue AS
SELECT r.release_id,NULL::text AS source_claim_id,NULL::integer AS node_index,'REQUIREMENT_NORMALIZATION_NOT_FROZEN'::text AS issue
FROM ontology.corpus_release r WHERE NOT EXISTS(SELECT 1 FROM ontology.requirement_freeze f WHERE f.release_id=r.release_id)
UNION ALL SELECT s.release_id,s.source_claim_id,s.node_index,'REQUIREMENT_'||s.outcome FROM ontology.requirement_selection s WHERE outcome<>'REVIEWED'
UNION ALL SELECT a.release_id,a.source_claim_id,a.node_index,'REQUIREMENT_SCOPE_UNRESOLVED' FROM ontology.requirement_atom a WHERE applicability NOT IN ('all_positions','posting_metadata','explicit_positions')
UNION ALL SELECT a.release_id,a.source_claim_id,a.node_index,'REQUIREMENT_GUARD_NORMALIZATION_PENDING' FROM ontology.requirement_atom a
 WHERE EXISTS(SELECT 1 FROM ontology.condition_node n WHERE n.claim_id=a.source_claim_id AND n.operator IN ('if_then','except'))
UNION ALL SELECT s.release_id,s.source_claim_id,s.node_index,'REQUIREMENT_CONFIDENCE_UNASSESSED' FROM ontology.requirement_selection s WHERE outcome='REVIEWED';

CREATE OR REPLACE FUNCTION ontology.query_requirements_v1(release_choice text,preview boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE id text; result jsonb; BEGIN
 id:=ontology.read_release_v1(release_choice,preview); PERFORM ontology.verify_requirements_v1(id);
 SELECT ontology.read_context_v1(id,preview)||jsonb_build_object('contract','typed-source-atoms-v1',
  'membership',(SELECT to_jsonb(m) FROM ontology.requirement_membership m WHERE m.release_id=id),
  'issues',coalesce((SELECT jsonb_agg(to_jsonb(i) ORDER BY source_claim_id,node_index,issue) FROM ontology.typed_requirement_issue i WHERE i.release_id=id),'[]'),
  'atoms',coalesce((SELECT jsonb_agg(jsonb_build_object('source',to_jsonb(a),'source_binding',ontology.requirement_source_v1(a.source_claim_id,a.node_index),
   'selection',to_jsonb(s),'normalization',to_jsonb(n),'review',to_jsonb(d),
   'requirement_scope',CASE WHEN n.condition->>'kind' IN ('LOCATION','ELIGIBILITY','AVAILABILITY') THEN 'POSTING_FILTER'
    WHEN n.condition->>'kind' IN ('SKILL','LANGUAGE','CREDENTIAL','EDUCATION','EXPERIENCE','PROJECT') THEN 'CAPABILITY' ELSE NULL END,
   'review_status',CASE WHEN s.outcome='REVIEWED' THEN CASE d.reviewer_kind WHEN 'human' THEN 'HUMAN_ACCEPTED' ELSE 'ASSISTANT_REVIEWED' END
    WHEN s.outcome='REJECTED' THEN 'REJECTED' ELSE 'PENDING' END,
   'confidence',NULL,'confidence_state','UNASSESSED') ORDER BY a.source_claim_id,a.node_index)
   FROM ontology.requirement_atom a LEFT JOIN ontology.requirement_selection s USING(release_id,source_claim_id,node_index)
   LEFT JOIN ontology.requirement_normalization n USING(normalization_id) LEFT JOIN ontology.requirement_decision d ON d.decision_id=s.decision_id
   WHERE a.release_id=id),'[]')) INTO result;
 RETURN result;
END $$;
COMMENT ON TABLE ontology.requirement_normalization IS 'Typed interpretation of one exact source atom. Original positions, AND/OR/guards and spans are preserved. Review is separate; no confidence is inferred from validation.';
COMMIT;
