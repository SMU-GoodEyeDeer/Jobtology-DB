-- Nested provider trees, deterministic indices and explicit source accounting.
-- Existing validators and response contracts are unchanged.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.schema_issues_v6(v jsonb, s jsonb, root jsonb DEFAULT NULL, path text DEFAULT '$', depth integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]'; actual text; wanted jsonb; k text; x jsonb; idx integer:=0; resolved jsonb; branch jsonb; actual_root jsonb:=coalesce(root,s); reference text;
BEGIN
 IF depth>64 THEN RETURN jsonb_build_array(path||':SCHEMA_DEPTH_LIMIT'); END IF;
 IF s ? '$ref' THEN
  reference:=s->>'$ref';
  IF reference !~ '^#/[\$]defs/[A-Za-z0-9_-]+$' OR (s-'$ref'-'description')<>'{}'::jsonb
  THEN RETURN jsonb_build_array(path||':UNSUPPORTED_SCHEMA_REFERENCE'); END IF;
  resolved:=actual_root#>ARRAY['$defs',split_part(reference,'/',3)];
  IF resolved IS NULL THEN RETURN jsonb_build_array(path||':UNKNOWN_SCHEMA_REFERENCE'); END IF;
  RETURN enrichment.schema_issues_v6(v,resolved,actual_root,path,depth+1);
 END IF;
 IF s ? 'anyOf' THEN
  IF jsonb_typeof(s->'anyOf') IS DISTINCT FROM 'array' OR jsonb_array_length(s->'anyOf') NOT BETWEEN 1 AND 16
  THEN RETURN jsonb_build_array(path||':INVALID_SCHEMA_UNION'); END IF;
  FOR branch IN SELECT jsonb_array_elements(s->'anyOf') LOOP
   IF enrichment.schema_issues_v6(v,branch,actual_root,path,depth+1)='[]' THEN RETURN '[]'; END IF;
  END LOOP;
  RETURN jsonb_build_array(path||':ANY_OF');
 END IF;
 actual:=jsonb_typeof(v); wanted:=s->'type';
 IF actual='number' AND v::text ~ '^-?[0-9]+$' AND
  (wanted='"integer"'::jsonb OR wanted @> '["integer"]'::jsonb) THEN actual:='integer'; END IF;
 IF actual IS NULL OR wanted IS NULL OR NOT coalesce(wanted=to_jsonb(actual) OR
  (jsonb_typeof(wanted)='array' AND wanted @> jsonb_build_array(actual)),false) THEN
  RETURN jsonb_build_array(path||':TYPE');
 END IF;
 IF s ? 'enum' AND NOT (s->'enum' @> jsonb_build_array(v)) THEN errors:=errors||jsonb_build_array(path||':ENUM'); END IF;
 IF actual='object' THEN
  FOR k IN SELECT jsonb_array_elements_text(coalesce(s->'required','[]')) LOOP
   IF NOT v ? k THEN errors:=errors||jsonb_build_array(path||'.'||k||':REQUIRED'); END IF;
  END LOOP;
  FOR k,x IN SELECT * FROM jsonb_each(v) LOOP
   IF s->'properties' ? k THEN errors:=errors||enrichment.schema_issues_v6(x,s->'properties'->k,actual_root,path||'.'||k,depth+1);
   ELSIF s->'additionalProperties'='false'::jsonb THEN errors:=errors||jsonb_build_array(path||':EXTRA_PROPERTY'); END IF;
  END LOOP;
 ELSIF actual='array' THEN
  IF jsonb_array_length(v)<coalesce((s->>'minItems')::integer,0) THEN errors:=errors||jsonb_build_array(path||':TOO_FEW_ITEMS'); END IF;
  IF jsonb_array_length(v)>coalesce((s->>'maxItems')::integer,2147483647) THEN errors:=errors||jsonb_build_array(path||':TOO_MANY_ITEMS'); END IF;
  FOR x IN SELECT jsonb_array_elements(v) LOOP
   errors:=errors||enrichment.schema_issues_v6(x,s->'items',actual_root,path||'['||idx||']',depth+1); idx:=idx+1;
  END LOOP;
 ELSIF actual='string' THEN
  IF length(v#>>'{}')<coalesce((s->>'minLength')::integer,0) OR
     length(v#>>'{}')>coalesce((s->>'maxLength')::integer,2147483647)
  THEN errors:=errors||jsonb_build_array(path||':STRING_LENGTH'); END IF;
 ELSIF actual IN ('number','integer') THEN
  IF (s ? 'minimum' AND (v::text)::numeric<(s->>'minimum')::numeric) OR
     (s ? 'maximum' AND (v::text)::numeric>(s->>'maximum')::numeric)
  THEN errors:=errors||jsonb_build_array(path||':NUMBER_RANGE'); END IF;
 END IF;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.tree_size_v6(tree jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 WITH RECURSIVE walk(node,depth) AS (
  SELECT tree,1 WHERE tree IS NOT NULL AND tree<>'null'::jsonb
  UNION ALL SELECT c,w.depth+1 FROM walk w CROSS JOIN LATERAL jsonb_array_elements(w.node->'children') c WHERE w.depth<13
 ), bounded AS (SELECT depth FROM walk LIMIT 61)
 SELECT jsonb_build_object('nodes',count(*),'depth',coalesce(max(depth),0)) FROM bounded
$$;
CREATE OR REPLACE FUNCTION enrichment.flatten_tree_v6(tree jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE size jsonb:=enrichment.tree_size_v6(tree); result jsonb;
BEGIN
 IF (size->>'nodes')::integer>60 OR (size->>'depth')::integer>12 THEN RAISE EXCEPTION 'NESTED_TREE_LIMIT'; END IF;
 WITH RECURSIVE walk(node,path) AS (
  SELECT tree,ARRAY[]::integer[] WHERE tree IS NOT NULL AND tree<>'null'::jsonb
  UNION ALL SELECT c,w.path||(ordinal-1)::integer FROM walk w
   CROSS JOIN LATERAL jsonb_array_elements(w.node->'children') WITH ORDINALITY a(c,ordinal)
 ), indexed AS MATERIALIZED (SELECT *,row_number() OVER(ORDER BY path)-1 AS idx FROM walk)
 SELECT coalesce(jsonb_agg(jsonb_build_object('op',n.node->'op','parts',n.node->'parts','children',
  (SELECT coalesce(jsonb_agg(c.idx ORDER BY c.path),'[]') FROM indexed c
   WHERE cardinality(c.path)=cardinality(n.path)+1 AND c.path[1:cardinality(n.path)]=n.path)) ORDER BY n.idx),'[]')
 INTO result FROM indexed n;
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION enrichment.adapt_v6(output jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT jsonb_set(output-'unhandled_passages','{requirements}',coalesce((
  SELECT jsonb_agg((r-'condition')||jsonb_build_object('expression',enrichment.flatten_tree_v6(r->'condition')) ORDER BY ordinal)
  FROM jsonb_array_elements(output->'requirements') WITH ORDINALITY x(r,ordinal)), '[]'))
$$;

CREATE OR REPLACE FUNCTION enrichment.coverage_v6(output jsonb,source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 WITH passages AS MATERIALIZED (SELECT p FROM jsonb_array_elements(enrichment.source_passages_v2(source)) p),
 used AS (SELECT DISTINCT e#>>'{}' AS id FROM (SELECT r FROM jsonb_array_elements(output->'requirements') r
   UNION ALL SELECT r FROM jsonb_array_elements(output->'duties') r
   UNION ALL SELECT r FROM jsonb_array_elements(output->'positions') r) claims
   CROSS JOIN LATERAL jsonb_array_elements(r->'evidence_ids') e)
 SELECT coalesce(jsonb_agg(jsonb_build_object('evidence_id',p->>'id','field',p->>'field',
  'disposition',CASE WHEN NOT enrichment.narrative_field(source,p->>'field') THEN 'metadata'
   WHEN used.id IS NOT NULL THEN 'cited' ELSE coalesce(u->>'disposition','unaccounted') END,
  'reason',u->>'reason','duplicate_of',u->>'duplicate_of') ORDER BY p->>'id'),'[]')
 FROM passages LEFT JOIN used ON used.id=p->>'id'
 LEFT JOIN LATERAL (SELECT u FROM jsonb_array_elements(output->'unhandled_passages') u WHERE u->>'evidence_id'=p->>'id' LIMIT 1) untouched ON true
$$;

CREATE OR REPLACE FUNCTION enrichment.heading_v6(value text) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT enrichment.fold_space_v2(regexp_replace(translate(value,'<>[]○·※*-:()','               '),'^[[:space:]0-9.]+',''))
 ~ '^(공통|공통[[:space:]]*자격|기관공통|필수|우대|응시자격|지원자격([[:space:]]*등)?|결격사유|우대내용|우대사항|수행업무|수행업무[[:space:]]*및[[:space:]]*근로조건|직종별[[:space:]]*자격|근무시간|근무기간|채용절차|채용방법|전형방법[[:space:]]*및[[:space:]]*절차|기타)$'
$$;

CREATE OR REPLACE FUNCTION enrichment.output_issues_v6(output jsonb,source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]'; adapted jsonb; x jsonb; size jsonb; p jsonb; u jsonb; all_text text; marker text;
 passages jsonb:=enrichment.source_passages_v2(source); narrative boolean; cited boolean; reference text; node jsonb; exception_node jsonb;
BEGIN
 FOR x IN SELECT jsonb_array_elements(output->'requirements') LOOP
  size:=enrichment.tree_size_v6(x->'condition');
  IF (size->>'nodes')::integer>60 OR (size->>'depth')::integer>12
  THEN errors:=errors||'["expression:NESTED_TREE_LIMIT"]'::jsonb; END IF;
 END LOOP;
 IF errors<>'[]' THEN RETURN errors; END IF;
 adapted:=enrichment.adapt_v6(output);
 errors:=enrichment.output_issues_v5(adapted,source);
 IF (SELECT count(*) FROM jsonb_array_elements(output->'unhandled_passages'))<>
    (SELECT count(DISTINCT entry->>'evidence_id') FROM jsonb_array_elements(output->'unhandled_passages') entry)
 THEN errors:=errors||'["coverage:DUPLICATE_DISPOSITION"]'::jsonb; END IF;
 FOR u IN SELECT jsonb_array_elements(output->'unhandled_passages') LOOP
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(passages) known WHERE known->>'id'=u->>'evidence_id')
  THEN errors:=errors||'["coverage:UNKNOWN_PASSAGE"]'::jsonb; END IF;
 END LOOP;
 FOR p IN SELECT jsonb_array_elements(passages) LOOP
  narrative:=enrichment.narrative_field(source,p->>'field');
  SELECT u0 INTO u FROM jsonb_array_elements(output->'unhandled_passages') u0 WHERE u0->>'evidence_id'=p->>'id' LIMIT 1;
  SELECT string_agg(enrichment.join_parts_v3(r->'text_parts'),' ') INTO all_text FROM (
   SELECT r FROM jsonb_array_elements(output->'requirements') r UNION ALL SELECT r FROM jsonb_array_elements(output->'duties') r
  ) claims WHERE r->'evidence_ids' @> jsonb_build_array(p->>'id');
  cited:=all_text IS NOT NULL OR EXISTS(SELECT 1 FROM jsonb_array_elements(output->'positions') r WHERE r->'evidence_ids' @> jsonb_build_array(p->>'id'));
  IF u IS NOT NULL AND (cited OR NOT narrative) THEN errors:=errors||jsonb_build_array('coverage:CONFLICTING_DISPOSITION:'||(p->>'id')); END IF;
  IF NOT narrative THEN CONTINUE; END IF;
  IF NOT cited AND u IS NULL THEN errors:=errors||jsonb_build_array('coverage:UNACCOUNTED_PASSAGE:'||(p->>'id')); END IF;
  IF u IS NOT NULL THEN
   IF u->>'disposition'='unresolved' THEN errors:=errors||jsonb_build_array('coverage:SOURCE_REVIEW_REQUIRED:'||(p->>'id'));
   ELSIF u->>'disposition'='duplicate' THEN
    IF u->>'duplicate_of'=p->>'id' OR NOT EXISTS(
     SELECT 1 FROM jsonb_array_elements(passages) other WHERE other->>'id'=u->>'duplicate_of'
      AND enrichment.fold_space_v2(other->>'text')=enrichment.fold_space_v2(p->>'text')
      AND EXISTS(SELECT 1 FROM (
       SELECT r FROM jsonb_array_elements(output->'requirements') r UNION ALL SELECT r FROM jsonb_array_elements(output->'duties') r
       UNION ALL SELECT r FROM jsonb_array_elements(output->'positions') r) claims
       WHERE r->'evidence_ids' @> jsonb_build_array(other->>'id')))
    THEN errors:=errors||jsonb_build_array('coverage:DUPLICATE_NOT_GROUNDED:'||(p->>'id')); END IF;
   ELSE
    IF u->>'duplicate_of' IS NOT NULL THEN errors:=errors||'["coverage:UNEXPECTED_DUPLICATE_REFERENCE"]'::jsonb; END IF;
    IF u->>'disposition'='heading' AND NOT enrichment.heading_v6(p->>'text')
    THEN errors:=errors||jsonb_build_array('coverage:UNPROVEN_HEADING:'||(p->>'id')); END IF;
    IF u->>'disposition'='no_condition' AND enrichment.fold_space_v2(p->>'text') !~ '^[[:space:]○·※*-]*(없음|해당[[:space:]]*없음|없습니다)[.[:space:]]*$'
    THEN errors:=errors||jsonb_build_array('coverage:UNPROVEN_NO_CONDITION:'||(p->>'id')); END IF;
    IF u->>'disposition'='attachment_reference' AND p->>'text' !~ '(첨부|붙임|공고문)'
    THEN errors:=errors||jsonb_build_array('coverage:UNPROVEN_ATTACHMENT_REFERENCE:'||(p->>'id')); END IF;
    IF p->>'field'<>'selection_text' AND NOT (u->>'disposition'='heading' AND enrichment.heading_v6(p->>'text'))
     AND p->>'text' ~ '(소지|면허|자격증|경력|이수|졸업|필수|우대|결격|기피|제한|무관|가점|가산|미만|이상|이하|다만|단[[:space:]]*[,，:]|[0-9]+[[:space:]]*(%|년|개월|만원)|할[[:space:]]*수[[:space:]]*없|불가|부적격)'
    THEN errors:=errors||jsonb_build_array('coverage:POSSIBLE_OMITTED_CONDITION:'||(p->>'id')); END IF;
   END IF;
  END IF;
  IF all_text IS NOT NULL THEN
   -- Exact cited text alone does not prove that a numeric qualifier was retained.
   FOR marker IN SELECT m[1] FROM regexp_matches(p->>'text','([0-9]+([.][0-9]+)?[[:space:]]*(%|퍼센트|년|개월|만원|점|세))','g') m LOOP
    IF position(regexp_replace(marker,'[[:space:]]','','g') in regexp_replace(all_text,'[[:space:]]','','g'))=0
    THEN errors:=errors||jsonb_build_array('coverage:NUMERIC_QUALIFIER_OMITTED:'||(p->>'id')); END IF;
   END LOOP;
   IF p->>'text' ~ '(다만|단[[:space:]]*[,，:]|\(단[[:space:]])' AND NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(output->'requirements') r WHERE r->'evidence_ids' @> jsonb_build_array(p->>'id') AND r->>'logic'='conditional')
   THEN errors:=errors||jsonb_build_array('coverage:EXCEPTION_NOT_MODELED:'||(p->>'id')); END IF;
  END IF;
 END LOOP;
 FOR x IN SELECT jsonb_array_elements(adapted->'requirements') LOOP
  FOR node IN SELECT jsonb_array_elements(x->'expression') LOOP
   IF node->>'op'='except' THEN
    exception_node:=x->'expression'->((node->'children'->>1)::integer);
    IF enrichment.join_parts_v3(exception_node->'parts') ~ '(한정|한함)'
    THEN errors:=errors||'["expression:APPLICABILITY_AS_EXEMPTION_REVIEW_REQUIRED"]'::jsonb; END IF;
   END IF;
  END LOOP;
 END LOOP;
 RETURN errors;
END $$;
CREATE OR REPLACE FUNCTION enrichment.hydrate_v6(output jsonb,source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT base||jsonb_build_object(
  'schema_version','ko-v6','validation_policy','nested-source-accounting-v1',
  'provider_output_hash',enrichment.hash(output::text),'condition_encoding','nested-to-preorder-v1',
  'source_coverage',enrichment.coverage_v6(output,source),
  'normalization',(base->'normalization')||jsonb_build_object('policy','nested-source-proof-v1',
   'provider_output_hash',enrichment.hash(output::text),'adapted_output_hash',enrichment.hash(enrichment.adapt_v6(output)::text),
   'changed',enrichment.normalize_v4(enrichment.adapt_v6(output),source)<>output))
 FROM (SELECT enrichment.hydrate_v5(enrichment.adapt_v6(output),source) AS base) adapted
$$;

-- New-format repairs can use a compatible prior audit or an explicit independent
-- rejection. A pending/accepted correction is never replaced automatically.
CREATE OR REPLACE FUNCTION enrichment.repair_reasons_v6(old_id text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE i enrichment.item%ROWTYPE; a enrichment.attempt%ROWTYPE; b enrichment.batch%ROWTYPE;
 audit enrichment.extraction_audit%ROWTYPE; decision text; notes text; errors jsonb:='[]'; audited_version text;
BEGIN
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=old_id;
 SELECT * INTO a FROM enrichment.attempt WHERE attempt_id=i.extraction_id;
 IF NOT FOUND OR a.state IN ('RESERVED','SKIPPED') THEN RETURN NULL; END IF;
 IF i.source_hash IS DISTINCT FROM enrichment.hash(i.source_data::text) THEN RAISE EXCEPTION 'REPAIR_SOURCE_HASH_MISMATCH'; END IF;
 SELECT d.decision,d.notes INTO decision,notes FROM enrichment.extraction_revision r
 LEFT JOIN enrichment.latest_extraction_decision d USING(revision_id) WHERE r.item_id=old_id ORDER BY revision_no DESC LIMIT 1;
 IF FOUND THEN
  IF decision IS DISTINCT FROM 'REJECT' THEN RETURN NULL; END IF;
  errors:=jsonb_build_array('INDEPENDENT_EXTRACTION_REJECTED',notes);
 END IF;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=i.batch_id;
 audited_version:=CASE WHEN b.settings->>'prompt_version' IN ('ko-v4','ko-v5') THEN 'ko-v5' ELSE b.settings->>'prompt_version' END;
 SELECT * INTO audit FROM enrichment.extraction_audit WHERE attempt_id=a.attempt_id AND validator_version=audited_version;
 IF FOUND THEN
  IF audit.raw_output_hash IS DISTINCT FROM enrichment.hash(coalesce(a.raw_output::text,'null')) OR audit.source_hash IS DISTINCT FROM i.source_hash
  THEN RAISE EXCEPTION 'REPAIR_AUDIT_INPUT_CHANGED'; END IF;
  errors:=errors||audit.issues;
  RETURN CASE WHEN errors<>'[]' THEN errors END;
 END IF;
 IF a.state IN ('REJECTED','ERROR','BUDGET_BLOCKED','PLANNED') THEN
  errors:=errors||CASE WHEN a.issues='[]' THEN jsonb_build_array('PRIOR_EXTRACTION_'||a.state) ELSE a.issues END;
 END IF;
 RETURN CASE WHEN errors<>'[]' THEN errors END;
END $$;
COMMIT;
