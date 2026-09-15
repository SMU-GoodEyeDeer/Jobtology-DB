-- Constrain new ko-v7 provider requests to their exact source passage IDs.
-- Historical prompt schemas, attempts and semantic validators stay unchanged.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.passage_pattern_v1(passages jsonb,field_name text DEFAULT NULL)
RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE pattern text; BEGIN
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(passages) p
  WHERE p->>'field' !~ '^[a-z][a-z0-9_]*$' OR p->>'id' !~ '^[a-z][a-z0-9_]*:[1-9][0-9]*$')
 THEN RAISE EXCEPTION 'INVALID_GENERATED_PASSAGE_ID'; END IF;
 SELECT '^('||string_agg(field||':('||numbers||')','|' ORDER BY field COLLATE "C")||')$' INTO pattern
 FROM (SELECT p->>'field' AS field,string_agg(split_part(p->>'id',':',2),'|' ORDER BY (p->>'start')::integer) AS numbers
  FROM jsonb_array_elements(passages) p WHERE field_name IS NULL OR p->>'field'=field_name GROUP BY p->>'field') f;
 -- minLength=1 in every referring schema makes an empty-source pattern impossible.
 RETURN coalesce(pattern,'^$');
END $$;

CREATE OR REPLACE FUNCTION enrichment.source_bound_schema_v1(base jsonb,source jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE schema jsonb:=base; passages jsonb:=enrichment.source_passages_v2(source);
 field_name text; section text; branch jsonb; branches jsonb; choices jsonb:='[]'; properties jsonb;
 idx integer; ref jsonb; path text[]; BEGIN
 IF base#>'{properties,unhandled_ranges,items,properties}' IS NULL
 THEN RAISE EXCEPTION 'SOURCE_BOUND_REQUEST_REQUIRES_V7_SCHEMA'; END IF;
 schema:=jsonb_set(schema,ARRAY['$defs','source_evidence_id'],jsonb_build_object(
  'type','string','minLength',1,'maxLength',100,'pattern',enrichment.passage_pattern_v1(passages)));
 ref:='{"$ref":"#/$defs/source_evidence_id"}';
 FOREACH section IN ARRAY ARRAY['positions','duties'] LOOP
  schema:=jsonb_set(schema,ARRAY['properties',section,'items','properties','evidence_ids','items'],ref);
 END LOOP;
 FOR idx IN 0..jsonb_array_length(base#>'{properties,requirements,items,anyOf}')-1 LOOP
  schema:=jsonb_set(schema,ARRAY['properties','requirements','items','anyOf',idx::text,'properties','evidence_ids','items'],ref);
 END LOOP;
 schema:=jsonb_set(schema,ARRAY['$defs','range_plain_disposition'],
  '{"type":"string","enum":["heading","procedure","attachment_reference","no_condition","unresolved"]}');
 schema:=jsonb_set(schema,ARRAY['$defs','range_context_kind'],
  '{"type":"string","enum":["employment_terms","application_form","institution_background","job_profile","document_structure","privacy_notice"]}');
 FOR field_name IN SELECT DISTINCT p->>'field' FROM jsonb_array_elements(passages) p
  WHERE enrichment.narrative_field(source,p->>'field') ORDER BY 1 LOOP
  schema:=jsonb_set(schema,ARRAY['$defs','range_id_'||field_name],jsonb_build_object(
   'type','string','minLength',1,'maxLength',100,'pattern',enrichment.passage_pattern_v1(passages,field_name)));
  properties:=base#>'{properties,unhandled_ranges,items,properties}'||jsonb_build_object(
   'first_id',jsonb_build_object('$ref','#/$defs/range_id_'||field_name),
   'last_id',jsonb_build_object('$ref','#/$defs/range_id_'||field_name));
  branches:='[]';
  FOR idx IN 1..3 LOOP
   branch:=base#>'{properties,unhandled_ranges,items}';
   branch:=jsonb_set(branch,'{properties}',properties||CASE idx
    WHEN 1 THEN '{"disposition":{"$ref":"#/$defs/range_plain_disposition"},"context_kind":{"type":"null"},"duplicate_of":{"type":"null"}}'::jsonb
    WHEN 2 THEN '{"disposition":{"type":"string","enum":["document_context"]},"context_kind":{"$ref":"#/$defs/range_context_kind"},"duplicate_of":{"type":"null"}}'::jsonb
    ELSE '{"disposition":{"type":"string","enum":["duplicate"]},"context_kind":{"type":"null"},"duplicate_of":{"$ref":"#/$defs/source_evidence_id"}}'::jsonb END);
   branches:=branches||jsonb_build_array(branch);
  END LOOP;
  schema:=jsonb_set(schema,ARRAY['$defs','range_'||field_name],jsonb_build_object('anyOf',branches));
  choices:=choices||jsonb_build_array(jsonb_build_object('$ref','#/$defs/range_'||field_name));
 END LOOP;
 IF choices='[]' THEN schema:=jsonb_set(schema,'{properties,unhandled_ranges,maxItems}','0');
 ELSE schema:=jsonb_set(schema,'{properties,unhandled_ranges,items}',jsonb_build_object('anyOf',choices)); END IF;
 IF passages='[]' THEN
  FOREACH section IN ARRAY ARRAY['positions','duties','requirements'] LOOP
   schema:=jsonb_set(schema,ARRAY['properties',section,'maxItems'],'0');
  END LOOP;
 END IF;
 RETURN schema||jsonb_build_object('description','jobtology:source-bound-ranges-v1');
END $$;

CREATE OR REPLACE FUNCTION enrichment.source_accounting_context_v1(source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 WITH fields AS (SELECT DISTINCT p->>'field' AS field FROM jsonb_array_elements(enrichment.source_passages_v2(source)) p)
 SELECT jsonb_build_object('policy','source-bound-ranges-v1',
  'narrative_fields',coalesce(jsonb_agg(field ORDER BY field) FILTER(WHERE enrichment.narrative_field(source,field)),'[]'),
  'metadata_fields',coalesce(jsonb_agg(field ORDER BY field) FILTER(WHERE NOT enrichment.narrative_field(source,field)),'[]'),
  'instructions','Account for every narrative passage using claims or ranges. Metadata fields never need ranges. Ranges must use real nonempty lines from one narrative field, in ascending order. Only a single identical already-cited line can be duplicate; all other dispositions require duplicate_of=null. Document context requires a nonnull context_kind; all other dispositions require context_kind=null. Source references do not prove semantic correctness. Recheck the scope of each requirement against the advertised positions and its parent heading; research scoring rules and other definitions that determine an eligibility threshold belong with that condition, not general document context.') FROM fields
$$;

-- Independent validator for the generated request schema, including exact-ID patterns.
CREATE OR REPLACE FUNCTION enrichment.schema_issues_request_v1(v jsonb, s jsonb, root jsonb DEFAULT NULL, path text DEFAULT '$', depth integer DEFAULT 0)
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
  RETURN enrichment.schema_issues_request_v1(v,resolved,actual_root,path,depth+1);
 END IF;
 IF s ? 'anyOf' THEN
  IF jsonb_typeof(s->'anyOf') IS DISTINCT FROM 'array' OR jsonb_array_length(s->'anyOf') NOT BETWEEN 1 AND 1024
  THEN RETURN jsonb_build_array(path||':INVALID_SCHEMA_UNION'); END IF;
  FOR branch IN SELECT jsonb_array_elements(s->'anyOf') LOOP
   IF enrichment.schema_issues_request_v1(v,branch,actual_root,path,depth+1)='[]' THEN RETURN '[]'; END IF;
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
   IF s->'properties' ? k THEN errors:=errors||enrichment.schema_issues_request_v1(x,s->'properties'->k,actual_root,path||'.'||k,depth+1);
   ELSIF s->'additionalProperties'='false'::jsonb THEN errors:=errors||jsonb_build_array(path||':EXTRA_PROPERTY'); END IF;
  END LOOP;
 ELSIF actual='array' THEN
  IF jsonb_array_length(v)<coalesce((s->>'minItems')::integer,0) THEN errors:=errors||jsonb_build_array(path||':TOO_FEW_ITEMS'); END IF;
  IF jsonb_array_length(v)>coalesce((s->>'maxItems')::integer,2147483647) THEN errors:=errors||jsonb_build_array(path||':TOO_MANY_ITEMS'); END IF;
  FOR x IN SELECT jsonb_array_elements(v) LOOP
   errors:=errors||enrichment.schema_issues_request_v1(x,s->'items',actual_root,path||'['||idx||']',depth+1); idx:=idx+1;
  END LOOP;
 ELSIF actual='string' THEN
  IF s ? 'pattern' AND (v#>>'{}') !~ (s->>'pattern') THEN errors:=errors||jsonb_build_array(path||':PATTERN'); END IF;
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
COMMIT;
