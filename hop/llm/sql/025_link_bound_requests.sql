-- Build a response schema from the exact linking input. Historical prompt rows
-- and already-saved attempts remain immutable; only new requests use this policy.
BEGIN;

ALTER TABLE enrichment.attempt ADD COLUMN IF NOT EXISTS normalization jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE OR REPLACE FUNCTION enrichment.dedup_exact_matches_v1(output jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT jsonb_set(output,'{matches}',coalesce((SELECT jsonb_agg(value ORDER BY first_ordinal)
  FROM (SELECT m.value,min(m.ordinal) AS first_ordinal
   FROM jsonb_array_elements(output->'matches') WITH ORDINALITY m(value,ordinal)
   GROUP BY m.value) unique_matches),'[]'::jsonb))
$$;

CREATE OR REPLACE FUNCTION enrichment.link_bound_extract_schema_v1(base jsonb, source jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE schema jsonb:=base; passages jsonb:=enrichment.source_passages_v2(source);
 section text; field_name text; fields jsonb; branches jsonb; branch jsonb;
BEGIN
 FOREACH section IN ARRAY ARRAY['positions','duties'] LOOP
  branches:='[]'::jsonb;
  FOR field_name IN SELECT DISTINCT p->>'field' FROM jsonb_array_elements(passages) p
   WHERE section='positions' OR p->>'field' IN ('eligibility_text','selection_text','duties_text','description_text')
    OR enrichment.is_attachment_field(source,p->>'field') ORDER BY 1 LOOP
   branch:=base#>ARRAY['properties',section,'items','properties','evidence_ids'];
   branch:=jsonb_set(branch,'{items}',jsonb_build_object('type','string','minLength',1,
    'maxLength',100,'pattern',enrichment.passage_pattern_v1(passages,field_name)));
   branches:=branches||jsonb_build_array(branch||jsonb_build_object('minItems',1));
  END LOOP;
  IF branches='[]'::jsonb THEN
   schema:=jsonb_set(schema,ARRAY['properties',section,'maxItems'],'0'::jsonb);
  ELSE
   schema:=jsonb_set(schema,ARRAY['properties',section,'items','properties','evidence_ids'],
    jsonb_build_object('anyOf',branches));
  END IF;
 END LOOP;
 RETURN schema||jsonb_build_object('description','jobtology:link-bound-v1');
END $$;

CREATE OR REPLACE FUNCTION enrichment.link_bound_categorize_schema_v1(
 base jsonb, extraction jsonb, candidates jsonb, max_matches integer)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE schema jsonb:=base; duty_count integer; codes jsonb;
BEGIN
 duty_count:=jsonb_array_length(extraction->'duties');
 SELECT coalesce(jsonb_agg(code ORDER BY code),'[]'::jsonb) INTO codes
 FROM (SELECT DISTINCT c->>'code' AS code FROM jsonb_array_elements(candidates) c
  WHERE nullif(c->>'code','') IS NOT NULL) distinct_codes;
 schema:=jsonb_set(schema,'{properties,matches,maxItems}',to_jsonb(least(max_matches,20)));
 IF duty_count=0 OR codes='[]'::jsonb THEN
  schema:=jsonb_set(schema,'{properties,matches,maxItems}','0'::jsonb);
 ELSE
  schema:=jsonb_set(schema,'{properties,matches,items,properties,duty_index,maximum}',
   to_jsonb(least(duty_count-1,59)));
  schema:=jsonb_set(schema,'{properties,matches,items,properties,competency_code,enum}',codes);
 END IF;
 RETURN schema||jsonb_build_object('description','jobtology:link-bound-v1');
END $$;
COMMIT;
