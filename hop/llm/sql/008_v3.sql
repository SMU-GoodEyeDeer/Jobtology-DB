-- Source-backed composition supports shared suffixes and separated exceptions.
-- ko-v1/v2 validators, prompts, attempts and cache entries remain unchanged.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.join_parts_v3(parts jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT string_agg(value,' ' ORDER BY ordinal)
 FROM jsonb_array_elements_text(parts) WITH ORDINALITY p(value,ordinal) $$;

CREATE OR REPLACE FUNCTION enrichment.adapt_v3(output jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb:=output; section text; rows jsonb; x jsonb; nodes jsonb; n jsonb;
BEGIN
 FOREACH section IN ARRAY ARRAY['duties','requirements'] LOOP
  rows:='[]';
  FOR x IN SELECT jsonb_array_elements(output->section) LOOP
   x:=x||jsonb_build_object('text',enrichment.join_parts_v3(x->'text_parts'));
   IF section='requirements' THEN
    nodes:='[]';
    FOR n IN SELECT jsonb_array_elements(x->'expression') LOOP
     nodes:=nodes||jsonb_build_array(n||jsonb_build_object('text',coalesce(enrichment.join_parts_v3(n->'parts'),'')));
    END LOOP;
    x:=jsonb_set(x,'{expression}',nodes);
   END IF;
   rows:=rows||jsonb_build_array(x);
  END LOOP;
  result:=jsonb_set(result,ARRAY[section],rows);
 END LOOP;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION enrichment.parts_supported_v3(parts jsonb, quote text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_array_length(parts)>0 AND NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements_text(parts) p WHERE nullif(btrim(p),'') IS NULL OR
   coalesce(position(enrichment.fold_space_v2(p) in enrichment.fold_space_v2(quote)),0)=0),false)
$$;

CREATE OR REPLACE FUNCTION enrichment.output_issues_v3(output jsonb, source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb; section text; x jsonb; n jsonb; quote text; passages jsonb:=enrichment.source_passages_v2(source);
BEGIN
 -- Retain v2 identity, polarity, metadata, coverage and tree topology checks.
 -- Replace only the contiguous text/atom tests with independent fragment proofs.
 SELECT coalesce(jsonb_agg(e),'[]') INTO errors
 FROM jsonb_array_elements(enrichment.output_issues_v2(enrichment.adapt_v3(output),source)) e
 WHERE e#>>'{}' NOT IN ('duties:UNSUPPORTED_TEXT','requirements:UNSUPPORTED_TEXT','expression:UNSUPPORTED_ATOM');
 FOREACH section IN ARRAY ARRAY['duties','requirements'] LOOP
  FOR x IN SELECT jsonb_array_elements(output->section) LOOP
   quote:=enrichment.evidence_v2(x->'evidence_ids',passages,source)->>'quote';
   IF NOT enrichment.parts_supported_v3(x->'text_parts',quote)
   THEN errors:=errors||jsonb_build_array(section||':UNSUPPORTED_FRAGMENT'); END IF;
   IF section='requirements' THEN
    FOR n IN SELECT jsonb_array_elements(x->'expression') LOOP
     IF n->>'op'='atom' AND (jsonb_array_length(n->'children')<>0 OR NOT enrichment.parts_supported_v3(n->'parts',quote))
     THEN errors:=errors||'["expression:UNSUPPORTED_FRAGMENT"]'::jsonb; END IF;
     IF n->>'op'<>'atom' AND jsonb_array_length(n->'parts')<>0
     THEN errors:=errors||'["expression:GROUP_HAS_PARTS"]'::jsonb; END IF;
    END LOOP;
   END IF;
  END LOOP;
 END LOOP;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.hydrate_v3(output jsonb, source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT enrichment.hydrate_v2(enrichment.adapt_v3(output),source)||'{"schema_version":"ko-v3"}'::jsonb
$$;
COMMIT;
