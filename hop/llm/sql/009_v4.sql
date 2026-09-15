-- Deterministic source interpretation and conservative semantic checks.
-- Native PostgreSQL invoked by Hop. Raw provider objects and v1-v3 stay unchanged.
BEGIN;

-- Repair only whitespace-separated composition: output words and their order do
-- not change. Every resulting fragment must independently occur in the quote.
-- A word not present in the cited source is NEVER repaired or silently dropped.
CREATE OR REPLACE FUNCTION enrichment.prove_parts_v4(parts jsonb, quote text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb:='[]'; part text; words text[]; i integer; j integer; chosen integer; candidate text;
BEGIN
 FOR part IN SELECT jsonb_array_elements_text(parts) LOOP
  IF enrichment.parts_supported_v3(jsonb_build_array(part),quote) THEN
   result:=result||jsonb_build_array(part); CONTINUE;
  END IF;
  words:=regexp_split_to_array(enrichment.fold_space_v2(part),'[[:space:]]+'); i:=1;
  WHILE i<=cardinality(words) LOOP
   chosen:=NULL;
   FOR j IN REVERSE cardinality(words)..i LOOP
    candidate:=array_to_string(words[i:j],' ');
    IF enrichment.parts_supported_v3(jsonb_build_array(candidate),quote) THEN chosen:=j; EXIT; END IF;
   END LOOP;
   IF chosen IS NULL THEN RETURN parts; END IF;
   result:=result||jsonb_build_array(array_to_string(words[i:chosen],' ')); i:=chosen+1;
  END LOOP;
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION enrichment.education_v4(source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE value text:=btrim(source->>'education'); levels text[]; level text; nodes jsonb:='[]';
 ids jsonb; logic text; kind text; mixed boolean;
BEGIN
 IF nullif(value,'') IS NULL THEN RETURN NULL; END IF;
 SELECT array_agg(btrim(v) ORDER BY ord) INTO levels
 FROM string_to_table(value,',') WITH ORDINALITY a(v,ord);
 IF EXISTS(SELECT 1 FROM unnest(levels) v WHERE v NOT IN
  ('학력무관','중졸이하','고졸','대졸(2~3년)','대졸(4년)','석사','박사')) OR
  cardinality(levels)<>(SELECT count(DISTINCT v) FROM unnest(levels) v)
 THEN RETURN NULL; END IF;
 SELECT jsonb_agg(p->>'id' ORDER BY p->>'id') INTO ids
 FROM jsonb_array_elements(enrichment.source_passages_v2(source)) p WHERE p->>'field'='education';
 mixed:='학력무관'=ANY(levels) AND cardinality(levels)>1;
 kind:=CASE WHEN levels=ARRAY['학력무관'] THEN 'unrestricted' ELSE 'eligibility' END;
 logic:=CASE WHEN mixed THEN 'unspecified' WHEN cardinality(levels)=1 THEN 'single' ELSE 'any_of' END;
 IF logic='any_of' THEN
  nodes:=jsonb_build_array(jsonb_build_object('op','any_of','parts','[]'::jsonb,
   'children',(SELECT jsonb_agg(i) FROM generate_series(1,cardinality(levels)) i)));
  FOREACH level IN ARRAY levels LOOP
   nodes:=nodes||jsonb_build_array(jsonb_build_object('op','atom','parts',jsonb_build_array(level),'children','[]'::jsonb));
  END LOOP;
 END IF;
 RETURN jsonb_build_object('position_ids','[]'::jsonb,'category','education','kind',kind,'logic',logic,
  'text_parts',jsonb_build_array(value),'evidence_ids',ids,'expression',nodes,
  'derivation','source-education-v1','applicability',CASE WHEN mixed THEN 'unresolved_positions' ELSE 'posting_metadata' END);
END $$;

CREATE OR REPLACE FUNCTION enrichment.normalize_v4(output jsonb, source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb:=output; section text; x jsonb; rows jsonb; n jsonb; nodes jsonb;
 quote text; passages jsonb:=enrichment.source_passages_v2(source); education jsonb:=enrichment.education_v4(source);
BEGIN
 FOREACH section IN ARRAY ARRAY['duties','requirements'] LOOP
  rows:='[]';
  FOR x IN SELECT jsonb_array_elements(output->section) LOOP
   -- Replace only exclusively education-field rows, never narrative conditions.
   IF education IS NOT NULL AND section='requirements' AND jsonb_array_length(x->'evidence_ids')>0 AND
    NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(x->'evidence_ids') id WHERE NOT EXISTS(
     SELECT 1 FROM jsonb_array_elements(passages) p WHERE p->>'id'=id AND p->>'field'='education'))
   THEN CONTINUE; END IF;
   quote:=enrichment.evidence_v2(x->'evidence_ids',passages,source)->>'quote';
   x:=jsonb_set(x,'{text_parts}',enrichment.prove_parts_v4(x->'text_parts',quote));
   IF section='requirements' THEN
    nodes:='[]';
    FOR n IN SELECT jsonb_array_elements(x->'expression') LOOP
     IF n->>'op'='atom' THEN n:=jsonb_set(n,'{parts}',enrichment.prove_parts_v4(n->'parts',quote)); END IF;
     nodes:=nodes||jsonb_build_array(n);
    END LOOP;
    x:=jsonb_set(x,'{expression}',nodes);
   END IF;
   rows:=rows||jsonb_build_array(x);
  END LOOP;
  IF section='requirements' AND education IS NOT NULL THEN rows:=rows||jsonb_build_array(education); END IF;
  result:=jsonb_set(result,ARRAY[section],rows);
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION enrichment.output_issues_v4(output jsonb, source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE normalized jsonb:=enrichment.normalize_v4(output,source); errors jsonb; x jsonb; excerpt text; quote text;
 passages jsonb:=enrichment.source_passages_v2(source);
BEGIN
 errors:=enrichment.output_issues_v3(normalized,source);
 IF nullif(btrim(source->>'education'),'') IS NOT NULL AND enrichment.education_v4(source) IS NULL
 THEN errors:=errors||'["education:UNKNOWN_SOURCE_VALUE"]'::jsonb; END IF;
 FOR x IN SELECT jsonb_array_elements(normalized->'requirements') LOOP
  excerpt:=enrichment.join_parts_v3(x->'text_parts');
  IF x->>'kind'='unrestricted' AND excerpt !~ '(무관|제한.{0,5}(없|하지)|상관.{0,3}없|제한.{0,5}두지)'
  THEN errors:=errors||'["requirements:UNPROVEN_UNRESTRICTED"]'::jsonb; END IF;
  IF excerpt ~ '(다만|단[[:space:]]*[,，:]|\(단[[:space:]])' AND x->>'logic'<>'conditional'
  THEN errors:=errors||'["requirements:EXCEPTION_WITHOUT_CONDITIONAL"]'::jsonb; END IF;
 END LOOP;
 FOR x IN SELECT jsonb_array_elements(normalized->'positions') LOOP
  IF x->>'name' ~ ' 및 ' THEN errors:=errors||'["positions:COMBINED_ROLES_REVIEW_REQUIRED"]'::jsonb; END IF;
 END LOOP;
 FOR x IN SELECT jsonb_array_elements(normalized->'duties') LOOP
  excerpt:=enrichment.fold_space_v2(enrichment.join_parts_v3(x->'text_parts'));
  quote:=enrichment.evidence_v2(x->'evidence_ids',passages,source)->>'quote';
  IF (EXISTS(SELECT 1 FROM jsonb_array_elements(normalized->'positions') p
      WHERE excerpt=enrichment.fold_space_v2(p->>'name')) OR
      (position(excerpt in coalesce(source->>'title',''))>0 AND excerpt !~ '[[:space:]]')) AND
      quote !~ '(담당[[:space:]]*업무|주요[[:space:]]*업무|수행[[:space:]]*업무|직무[[:space:]]*(내용|수행)|업무[[:space:]]*내용)'
  THEN errors:=errors||'["duties:TITLE_ONLY_REVIEW_REQUIRED"]'::jsonb; END IF;
  IF excerpt ~ '(서류[[:space:]]*(심사|전형|합격)|면접[[:space:]]*(심사|전형|시험)|필기[[:space:]]*(전형|시험)|전형[[:space:]]*(절차|단계))'
   AND quote !~ '(담당[[:space:]]*업무|주요[[:space:]]*업무|수행[[:space:]]*업무|직무[[:space:]]*(내용|수행)|업무[[:space:]]*내용)'
  THEN errors:=errors||'["duties:RECRUITMENT_PROCEDURE_REVIEW_REQUIRED"]'::jsonb; END IF;
 END LOOP;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.hydrate_v4(output jsonb, source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT enrichment.hydrate_v3(n,source)||jsonb_build_object('schema_version','ko-v4',
  'normalization',jsonb_build_object('policy','source-proof-v1','changed',n<>output,
   'provider_output_hash',enrichment.hash(output::text),'normalized_output_hash',enrichment.hash(n::text),
   'education_policy',CASE WHEN enrichment.education_v4(source) IS NOT NULL THEN 'source-education-v1' END))
 FROM (SELECT enrichment.normalize_v4(output,source) n) s
$$;
COMMIT;
