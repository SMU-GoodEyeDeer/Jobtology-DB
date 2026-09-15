-- Source-grounded interpretations are distinct from immutable extractor responses.
BEGIN;
CREATE TABLE IF NOT EXISTS enrichment.rule_interpretation (
 interpretation_id text PRIMARY KEY,
 interpretation_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 revision_id text NOT NULL REFERENCES enrichment.extraction_revision,
 requirement_index integer NOT NULL CHECK(requirement_index>=0),
 parent_id text REFERENCES enrichment.rule_interpretation,
 schema_version text NOT NULL REFERENCES enrichment.rule_contract,
 extraction_hash text NOT NULL,
 source_hash text NOT NULL,
 document jsonb NOT NULL,
 actor text NOT NULL CHECK(length(btrim(actor))>0),
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.rule_interpretation_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 interpretation_id text NOT NULL REFERENCES enrichment.rule_interpretation,
 decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant','policy')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
 notes text NOT NULL CHECK(length(btrim(notes))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['rule_contract','rule_interpretation','rule_interpretation_decision'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='immutable_'||name AND tgrelid=('enrichment.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON enrichment.%I FOR EACH ROW EXECUTE FUNCTION enrichment.append_only_review()',
    'immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

-- Only consecutive cited passages form a range; uncited intervening text cannot
-- become evidence merely because two surrounding lines were cited.
CREATE OR REPLACE FUNCTION enrichment.rule_evidence_ranges(ids jsonb,source jsonb)
RETURNS TABLE(evidence_ids jsonb,source_field text,quote text) LANGUAGE sql IMMUTABLE AS $$
 WITH passages AS (
  SELECT p,ids @> jsonb_build_array(p->>'id') AS selected FROM jsonb_array_elements(enrichment.source_passages_v2(source)) p
 ), grouped AS (
  SELECT *,sum(CASE WHEN selected THEN 0 ELSE 1 END) OVER(PARTITION BY p->>'field' ORDER BY (p->>'start')::integer) AS island
  FROM passages
 ) SELECT jsonb_agg(p->>'id' ORDER BY (p->>'start')::integer),p->>'field',
  substring(source->>(p->>'field') FROM min((p->>'start')::integer) FOR max((p->>'end')::integer)-min((p->>'start')::integer)+1)
 FROM grouped WHERE selected GROUP BY p->>'field',island
$$;

CREATE OR REPLACE FUNCTION enrichment.rule_interpretation_issues(document jsonb,claim jsonb,source jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE errors jsonb; schema jsonb; rule jsonb; other jsonb; node jsonb; flat jsonb; size jsonb; quote text;
 current_id text; visited text[]; count_ids integer;
BEGIN
 SELECT output_schema INTO schema FROM enrichment.rule_contract WHERE schema_version='guarded-rules-v1';
 errors:=enrichment.schema_issues_v6(document,schema);
 IF errors<>'[]' THEN RETURN errors; END IF;
 SELECT count(DISTINCT r->>'id') INTO count_ids FROM jsonb_array_elements(document->'rules') r;
 IF count_ids<>jsonb_array_length(document->'rules') THEN errors:=errors||'["rules:DUPLICATE_ID"]'; END IF;
 FOR rule IN SELECT jsonb_array_elements(document->'rules') LOOP
  IF rule->>'id' !~ '^[a-zA-Z][a-zA-Z0-9_-]{0,39}$' THEN errors:=errors||'["rules:INVALID_ID"]'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(rule->'evidence_ids') e WHERE NOT (claim->'evidence_ids' @> jsonb_build_array(e))) OR
   jsonb_array_length(rule->'evidence_ids')<>(SELECT count(DISTINCT e) FROM jsonb_array_elements(rule->'evidence_ids') e)
  THEN errors:=errors||'["rules:EVIDENCE_OUTSIDE_REQUIREMENT_OR_DUPLICATE"]'; CONTINUE; END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(enrichment.source_passages_v2(source)) p WHERE rule->'evidence_ids' @> jsonb_build_array(p->>'id'))<>jsonb_array_length(rule->'evidence_ids') OR
   (SELECT count(DISTINCT source_field) FROM enrichment.rule_evidence_ranges(rule->'evidence_ids',source))<>1
  THEN errors:=errors||'["rules:UNKNOWN_OR_MIXED_EVIDENCE"]'; CONTINUE; END IF;
  quote:=enrichment.evidence_v2(rule->'evidence_ids',enrichment.source_passages_v2(source),source)->>'quote';
  IF quote IS NULL OR NOT enrichment.parts_supported_v3(rule->'statement_parts',quote) OR EXISTS(
   SELECT 1 FROM jsonb_array_elements(rule->'statement_parts') part WHERE NOT EXISTS(
    SELECT 1 FROM enrichment.rule_evidence_ranges(rule->'evidence_ids',source) r WHERE enrichment.parts_supported_v3(jsonb_build_array(part),r.quote)))
  THEN errors:=errors||'["rules:UNSUPPORTED_STATEMENT"]'; END IF;
  size:=enrichment.tree_size_v6(rule->'guard');
  IF (size->>'nodes')::integer>60 OR (size->>'depth')::integer>12
  THEN errors:=errors||'["rules:GUARD_SIZE_LIMIT"]'; CONTINUE; END IF;
  flat:=enrichment.flatten_tree_v6(rule->'guard');
  FOR node IN SELECT jsonb_array_elements(flat) LOOP
   IF node->>'op'='atom' THEN
    IF jsonb_array_length(node->'children')<>0 OR jsonb_array_length(node->'parts')=0
    THEN errors:=errors||'["rules:INVALID_ATOM"]'; END IF;
    IF quote IS NULL OR NOT enrichment.parts_supported_v3(node->'parts',quote) OR EXISTS(
     SELECT 1 FROM jsonb_array_elements(node->'parts') part WHERE NOT EXISTS(
      SELECT 1 FROM enrichment.rule_evidence_ranges(rule->'evidence_ids',source) r WHERE enrichment.parts_supported_v3(jsonb_build_array(part),r.quote)))
    THEN errors:=errors||'["rules:UNSUPPORTED_GUARD"]'; END IF;
   ELSE
    IF jsonb_array_length(node->'parts')<>0 OR
     (node->>'op' IN ('all_of','any_of') AND jsonb_array_length(node->'children')<2) OR
     (node->>'op'='not' AND jsonb_array_length(node->'children')<>1)
    THEN errors:=errors||'["rules:INVALID_PREDICATE_GROUP"]'; END IF;
   END IF;
  END LOOP;
  IF (rule->>'action' IN ('LIMIT','DISABLE')) IS DISTINCT FROM (rule->>'target_rule_id' IS NOT NULL)
  THEN errors:=errors||'["rules:INVALID_TARGET_ROLE"]'; END IF;
  IF rule->>'target_rule_id' IS NOT NULL THEN
   SELECT x INTO other FROM jsonb_array_elements(document->'rules') x WHERE x->>'id'=rule->>'target_rule_id';
   IF other IS NULL THEN errors:=errors||'["rules:UNKNOWN_TARGET"]'; END IF;
   IF rule->>'action'='LIMIT' AND other->>'action' IS DISTINCT FROM 'PREFER'
   THEN errors:=errors||'["rules:LIMIT_REQUIRES_PREFERENCE_TARGET"]'; END IF;
  END IF;
  current_id:=rule->>'id'; visited:=ARRAY[]::text[];
  WHILE current_id IS NOT NULL LOOP
   IF current_id=ANY(visited) THEN errors:=errors||'["rules:CYCLIC_TARGETS"]'; EXIT; END IF;
   visited:=visited||current_id;
   SELECT x->>'target_rule_id' INTO current_id FROM jsonb_array_elements(document->'rules') x WHERE x->>'id'=current_id;
  END LOOP;
 END LOOP;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.capture_rule_interpretation(revision text,idx integer,who text,why text,document jsonb,parent text DEFAULT NULL)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE r enrichment.extraction_revision%ROWTYPE; i enrichment.item%ROWTYPE; b enrichment.batch%ROWTYPE;
 claim jsonb; errors jsonb; previous text; newest text; id text;
BEGIN
 IF nullif(btrim(who),'') IS NULL OR nullif(btrim(why),'') IS NULL THEN RAISE EXCEPTION 'INTERPRETATION_PROVENANCE_REQUIRED'; END IF;
 SELECT * INTO STRICT r FROM enrichment.extraction_revision WHERE revision_id=revision;
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=r.item_id FOR UPDATE;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=i.batch_id;
 IF b.mode<>'ENRICH' THEN RAISE EXCEPTION 'EVAL_CANNOT_ENTER_PRODUCTION_REVIEW'; END IF;
 IF idx IS NULL OR idx<0 OR idx>=jsonb_array_length(r.extraction->'requirements') THEN RAISE EXCEPTION 'UNKNOWN_REQUIREMENT_INDEX'; END IF;
 IF i.source_hash IS DISTINCT FROM enrichment.hash(i.source_data::text) THEN RAISE EXCEPTION 'INTERPRETATION_SOURCE_CHANGED'; END IF;
 SELECT x.revision_id INTO newest FROM enrichment.extraction_revision x JOIN enrichment.item xi USING(item_id)
  JOIN enrichment.batch xb USING(batch_id) WHERE xb.mode='ENRICH' AND xi.posting_id=i.posting_id AND xi.source_hash=i.source_hash
   AND xi.source_data=i.source_data ORDER BY x.revision_no DESC LIMIT 1;
 IF newest IS DISTINCT FROM revision THEN RAISE EXCEPTION 'INTERPRETATION_REQUIRES_CURRENT_EXTRACTION'; END IF;
 claim:=r.extraction->'requirements'->idx;
 errors:=enrichment.rule_interpretation_issues(document,claim,i.source_data);
 IF errors<>'[]' THEN RAISE EXCEPTION 'INVALID_RULE_INTERPRETATION: %',errors; END IF;
 id:=enrichment.hash(jsonb_build_array(revision,idx,parent,document)::text);
 IF EXISTS(SELECT 1 FROM enrichment.rule_interpretation WHERE interpretation_id=id) THEN RETURN id; END IF;
 SELECT interpretation_id INTO previous FROM enrichment.rule_interpretation WHERE revision_id=revision AND requirement_index=idx ORDER BY interpretation_no DESC LIMIT 1;
 IF parent IS DISTINCT FROM previous THEN RAISE EXCEPTION 'STALE_INTERPRETATION_PARENT'; END IF;
 INSERT INTO enrichment.rule_interpretation(interpretation_id,revision_id,requirement_index,parent_id,schema_version,extraction_hash,source_hash,document,actor,reason)
 VALUES(id,revision,idx,parent,document->>'schema_version',enrichment.hash(r.extraction::text),i.source_hash,document,who,why);
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION enrichment.decide_rule_interpretation(id text,choice text,who text,kind text,explanation text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE target enrichment.rule_interpretation%ROWTYPE; newest text;
BEGIN
 SELECT * INTO STRICT target FROM enrichment.rule_interpretation WHERE interpretation_id=id FOR SHARE;
 IF choice='ACCEPT' THEN
  SELECT interpretation_id INTO newest FROM enrichment.rule_interpretation WHERE revision_id=target.revision_id AND requirement_index=target.requirement_index ORDER BY interpretation_no DESC LIMIT 1;
  IF newest IS DISTINCT FROM id THEN RAISE EXCEPTION 'INTERPRETATION_SUPERSEDED'; END IF;
 END IF;
 INSERT INTO enrichment.rule_interpretation_decision(interpretation_id,decision,reviewer,reviewer_kind,notes)
 VALUES(id,choice,who,kind,explanation);
END $$;

CREATE OR REPLACE VIEW enrichment.current_rule_interpretation AS
SELECT selected.*,decision.decision,decision.decision_id,decision.reviewer,decision.reviewer_kind,decision.notes
FROM (SELECT DISTINCT ON(revision_id,requirement_index) * FROM enrichment.rule_interpretation
 ORDER BY revision_id,requirement_index,interpretation_no DESC) selected
LEFT JOIN LATERAL (SELECT * FROM enrichment.rule_interpretation_decision d WHERE d.interpretation_id=selected.interpretation_id
 ORDER BY decision_id DESC LIMIT 1) decision ON true;

-- SQL three-valued logic: an absent observation is UNKNOWN, never false.
-- This evaluates activation only, not whether a person satisfies the statement.
CREATE OR REPLACE FUNCTION enrichment.predicate_value(tree jsonb,observations jsonb,path text,depth integer DEFAULT 0)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result boolean; value boolean; child jsonb; ordinal integer:=0; raw jsonb;
BEGIN
 IF depth>12 THEN RAISE EXCEPTION 'GUARD_DEPTH_LIMIT'; END IF;
 IF tree IS NULL OR tree='null' THEN RETURN true; END IF;
 IF tree->>'op'='atom' THEN
  raw:=observations->path;
  IF raw IS NULL OR raw='null' THEN RETURN NULL; END IF;
  IF jsonb_typeof(raw)<>'boolean' THEN RAISE EXCEPTION 'PREDICATE_OBSERVATION_MUST_BE_BOOLEAN'; END IF;
  RETURN (raw::text)::boolean;
 END IF;
 IF tree->>'op' NOT IN ('all_of','any_of','not') OR tree->>'op' IS NULL THEN RAISE EXCEPTION 'UNKNOWN_PREDICATE_OPERATOR'; END IF;
 result:=CASE WHEN tree->>'op'='all_of' THEN true ELSE false END;
 FOR child IN SELECT jsonb_array_elements(tree->'children') LOOP
  value:=enrichment.predicate_value(child,observations,path||'/'||ordinal,depth+1); ordinal:=ordinal+1;
  IF tree->>'op'='not' THEN RETURN NOT value;
  ELSIF tree->>'op'='all_of' THEN result:=result AND value; ELSE result:=result OR value; END IF;
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION enrichment.rule_active(document jsonb,id text,observations jsonb,ancestors text[] DEFAULT ARRAY[]::text[])
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE rule jsonb; disabling jsonb; result boolean; current boolean;
BEGIN
 IF id=ANY(ancestors) OR cardinality(ancestors)>100 THEN RAISE EXCEPTION 'CYCLIC_RULE_ACTIVATION'; END IF;
 SELECT x INTO rule FROM jsonb_array_elements(document->'rules') x WHERE x->>'id'=id;
 IF rule IS NULL THEN RAISE EXCEPTION 'UNKNOWN_RULE'; END IF;
 result:=enrichment.predicate_value(rule->'guard',observations,id);
 FOR disabling IN SELECT x FROM jsonb_array_elements(document->'rules') x WHERE x->>'action'='DISABLE' AND x->>'target_rule_id'=id LOOP
  current:=enrichment.rule_active(document,disabling->>'id',observations,ancestors||id);
  result:=result AND NOT current;
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION enrichment.rule_activation_preview(id text,observations jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE interpretation enrichment.rule_interpretation%ROWTYPE; known text[]; entry record;
BEGIN
 SELECT * INTO STRICT interpretation FROM enrichment.rule_interpretation WHERE interpretation_id=id;
 IF jsonb_typeof(observations) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'OBSERVATIONS_MUST_BE_OBJECT'; END IF;
 WITH RECURSIVE nodes(path,node) AS (
  SELECT r->>'id',r->'guard' FROM jsonb_array_elements(interpretation.document->'rules') r
  UNION ALL SELECT n.path||'/'||(c.ordinal-1),c.node FROM nodes n
   CROSS JOIN LATERAL jsonb_array_elements(n.node->'children') WITH ORDINALITY c(node,ordinal)
 ) SELECT coalesce(array_agg(path) FILTER(WHERE node->>'op'='atom'),ARRAY[]::text[]) INTO known FROM nodes;
 FOR entry IN SELECT * FROM jsonb_each(observations) LOOP
  IF NOT entry.key=ANY(known) THEN RAISE EXCEPTION 'UNKNOWN_PREDICATE_OBSERVATION: %',entry.key; END IF;
  IF jsonb_typeof(entry.value) NOT IN ('boolean','null') THEN RAISE EXCEPTION 'PREDICATE_OBSERVATION_MUST_BE_BOOLEAN'; END IF;
 END LOOP;
 RETURN (SELECT jsonb_agg(jsonb_build_object('rule_id',r->>'id','action',r->>'action',
  'target_rule_id',r->>'target_rule_id','statement_parts',r->'statement_parts',
  'active',enrichment.rule_active(interpretation.document,r->>'id',observations),
  'meaning','Rule activation only; not applicant eligibility or satisfaction of the statement.') ORDER BY ord)
 FROM jsonb_array_elements(interpretation.document->'rules') WITH ORDINALITY rule(r,ord));
END $$;
COMMIT;
