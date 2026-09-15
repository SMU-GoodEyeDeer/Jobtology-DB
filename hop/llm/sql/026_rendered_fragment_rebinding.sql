-- Manual, source-exact suggestions for model text joined over Markdown <br>
-- boundaries. No attempt, review decision or graph row is changed here.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.split_rendered_fragment_v1(part text, quote text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE pieces text[]; candidate jsonb; found jsonb; left_part text; right_part text;
 previous_text text; next_text text; i integer; j integer; k integer;
BEGIN
 IF part IS NULL OR quote IS NULL OR part !~ '[[:space:]]' OR quote NOT LIKE '%<br>%' THEN RETURN NULL; END IF;
 pieces:=string_to_array(quote,'<br>');
 IF cardinality(pieces)<2 THEN RETURN NULL; END IF;
 FOR i IN 1..cardinality(pieces)-1 LOOP
  previous_text:=rtrim(pieces[i],E' \t\r\n');
  IF previous_text='' THEN CONTINUE; END IF;
  j:=i+1;
  WHILE j<=cardinality(pieces) AND btrim(pieces[j],E' \t\r\n')='' LOOP j:=j+1; END LOOP;
  IF j>cardinality(pieces) THEN CONTINUE; END IF;
  next_text:=ltrim(pieces[j],E' \t\r\n');
  FOR k IN 2..length(part)-1 LOOP
   IF substring(part FROM k FOR 1) !~ '[[:space:]]' THEN CONTINUE; END IF;
   left_part:=btrim(substring(part FROM 1 FOR k-1),E' \t\r\n');
   right_part:=btrim(substring(part FROM k+1),E' \t\r\n');
   IF length(left_part)<2 OR length(right_part)<2 OR
    length(left_part)>length(previous_text) OR length(right_part)>length(next_text)
   THEN CONTINUE; END IF;
   IF right(previous_text,length(left_part))=left_part AND left(next_text,length(right_part))=right_part THEN
    candidate:=jsonb_build_array(left_part,right_part);
    IF found IS NOT NULL AND found<>candidate THEN RETURN NULL; END IF;
    found:=candidate;
   END IF;
  END LOOP;
 END LOOP;
 RETURN found;
END $$;

CREATE OR REPLACE FUNCTION enrichment.suggest_rendered_fragment_revision_v1(output jsonb,source jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE old_issues jsonb; revised jsonb:=output; duties jsonb:='[]'::jsonb;
 duty jsonb; part text; pieces jsonb; replacement jsonb; quote text;
 passages jsonb:=enrichment.source_passages_v2(source); changed boolean:=false;
BEGIN
 old_issues:=enrichment.output_issues_link_v1(output,source);
 IF NOT old_issues @> '["duties:UNSUPPORTED_FRAGMENT"]'::jsonb OR EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(old_issues) issue WHERE issue<>'duties:UNSUPPORTED_FRAGMENT')
 THEN RETURN NULL; END IF;
 FOR duty IN SELECT jsonb_array_elements(output->'duties') LOOP
  quote:=enrichment.evidence_v2(duty->'evidence_ids',passages,source)->>'quote';
  replacement:='[]'::jsonb;
  FOR part IN SELECT jsonb_array_elements_text(duty->'text_parts') LOOP
   IF enrichment.parts_supported_v3(jsonb_build_array(part),quote) THEN
    replacement:=replacement||jsonb_build_array(part);
   ELSE
    pieces:=enrichment.split_rendered_fragment_v1(part,quote);
    IF pieces IS NULL THEN RETURN NULL; END IF;
    replacement:=replacement||pieces;
    changed:=true;
   END IF;
  END LOOP;
  duties:=duties||jsonb_build_array(jsonb_set(duty,'{text_parts}',replacement));
 END LOOP;
 IF NOT changed THEN RETURN NULL; END IF;
 revised:=jsonb_set(revised,'{duties}',duties);
 IF enrichment.output_issues_link_v1(revised,source)<>'[]'::jsonb THEN RETURN NULL; END IF;
 RETURN revised;
END $$;
COMMIT;
