-- Validate original file bytes before native CSV Input reads any data rows.
-- The published artifact has this exact ten-column layout. A changed layout
-- requires review instead of silently discarding or reassigning columns.
CREATE OR REPLACE FUNCTION ingestion.inspect_career_file(raw_bytes bytea)
RETURNS TABLE(expected_rows bigint, csv_encoding text, source_encoding text,
              file_error text, file_valid boolean)
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE
 content text; reconstructed text; rows text[]; row_text text;
 fields text[]; headers text[]; n integer:=0;
 field_pattern text := '(?:"(?:[^"]|"")*"|[^",\r\n]*)';
 row_pattern text;
BEGIN
 BEGIN
 IF octet_length(raw_bytes) NOT BETWEEN 1 AND 67108864 THEN RAISE EXCEPTION 'INVALID_RESPONSE_SIZE'; END IF;
 BEGIN
  content:=convert_from(raw_bytes,'UTF8'); csv_encoding:='UTF-8'; source_encoding:='utf-8-sig';
 EXCEPTION WHEN character_not_in_repertoire OR untranslatable_character THEN
  content:=convert_from(raw_bytes,'UHC'); csv_encoding:='MS949'; source_encoding:='cp949';
 END;
 IF left(content,1)=chr(65279) THEN content:=substr(content,2); END IF;
 row_pattern:='('||field_pattern||'(?:,'||field_pattern||')*)(\r\n|\n|\r|$)';
 SELECT array_agg(m[1]),string_agg(m[1]||m[2],'') INTO rows,reconstructed
 FROM regexp_matches(content,row_pattern,'g') m;
 IF reconstructed IS DISTINCT FROM content THEN RAISE EXCEPTION 'INVALID_CSV_SYNTAX'; END IF;
 FOREACH row_text IN ARRAY rows LOOP
  IF row_text='' THEN CONTINUE; END IF;
  SELECT array_agg(CASE WHEN left(m[1],1)='"' THEN replace(substr(m[1],2,length(m[1])-2),'""','"') ELSE m[1] END)
   INTO fields FROM regexp_matches(row_text,'(?:^|,)("(?:[^"]|"")*"|[^",\r\n]*)','g') m;
  n:=n+1;
  IF n=1 THEN
   headers:=fields;
   IF headers IS DISTINCT FROM ARRAY['대분류코드','중분류코드','소분류코드','직무코드','직무명',
      '직무역량코드','직무역량수준(능력단위수준 이면서 세분류의 자식)','직무역량명','수준(직급수준)','직급명']
    THEN RAISE EXCEPTION 'CHANGED_CSV_HEADER'; END IF;
  ELSIF cardinality(fields)<>cardinality(headers) THEN RAISE EXCEPTION 'INVALID_CSV_ROW_WIDTH'; END IF;
 END LOOP;
 IF n<=1 THEN RAISE EXCEPTION 'EMPTY_CSV'; END IF;
 expected_rows:=n-1; file_valid:=true;
 EXCEPTION
 WHEN raise_exception THEN file_error:=SQLERRM;file_valid:=false;
 WHEN character_not_in_repertoire OR untranslatable_character THEN file_error:='INVALID_CSV_ENCODING';file_valid:=false;
 END;
 RETURN NEXT;
END $fn$;
