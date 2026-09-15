-- Versioned extraction contract. All work runs in PostgreSQL via native Hop actions.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.fold_space_v2(v text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT btrim(regexp_replace(v,'[[:space:]]+',' ','g')) $$;

CREATE OR REPLACE FUNCTION enrichment.source_passages_v2(source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 WITH lines AS (
  SELECT key AS field,line,ordinal,
   1+coalesce(sum(length(line)+1) OVER(PARTITION BY key ORDER BY ordinal ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)::integer AS start
  FROM jsonb_each_text(enrichment.input_fields(source))
  CROSS JOIN LATERAL string_to_table(value,E'\n') WITH ORDINALITY AS parts(line,ordinal)
 ) SELECT coalesce(jsonb_agg(jsonb_build_object('id',field||':'||ordinal,'field',field,'text',line,
  'start',start,'end',start+length(line)-1) ORDER BY field COLLATE "C",ordinal),'[]')
 FROM lines WHERE length(btrim(line,E' \t\r'))>0
$$;

-- IDs refer to original offsets, so even a multi-line quotation is exact.
-- Unknown/mixed-field IDs are rejected by output_issues_v2 before hydration.
CREATE OR REPLACE FUNCTION enrichment.evidence_v2(ids jsonb, passages jsonb, source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT jsonb_build_object('field',min(p->>'field'),'quote',
  substring(source->>min(p->>'field') FROM min((p->>'start')::integer)
   FOR max((p->>'end')::integer)-min((p->>'start')::integer)+1))
 FROM jsonb_array_elements(passages) p WHERE ids @> jsonb_build_array(p->>'id')
$$;

CREATE OR REPLACE FUNCTION enrichment.expression_issues_v2(x jsonb, quote text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]'; nodes jsonb:=x->'expression'; n integer; j integer; c integer; node jsonb; seen integer[]:=ARRAY[0]; op text;
BEGIN
 n:=jsonb_array_length(nodes);
 IF x->>'logic' IN ('single','unspecified') THEN
  IF n<>0 THEN RETURN '["expression:UNEXPECTED_TREE"]'; END IF;
  RETURN errors;
 END IF;
 IF n<3 THEN RETURN '["expression:MISSING_TREE"]'; END IF;
 op:=nodes->0->>'op';
 IF (x->>'logic' IN ('all_of','any_of') AND op<>x->>'logic') OR
    (x->>'logic'='conditional' AND op NOT IN ('if_then','except'))
 THEN errors:=errors||'["expression:ROOT_MISMATCH"]'::jsonb; END IF;
 FOR j IN 0..n-1 LOOP
  node:=nodes->j;
  IF NOT j=ANY(seen) THEN errors:=errors||'["expression:UNREACHABLE_NODE"]'::jsonb; END IF;
  IF node->>'op'='atom' THEN
   IF jsonb_array_length(node->'children')<>0 OR nullif(btrim(node->>'text'),'') IS NULL OR
    coalesce(position(enrichment.fold_space_v2(node->>'text') in enrichment.fold_space_v2(quote)),0)=0
   THEN errors:=errors||'["expression:UNSUPPORTED_ATOM"]'::jsonb; END IF;
  ELSE
   IF node->>'text'<>'' OR jsonb_array_length(node->'children')<2 OR
    (node->>'op' IN ('if_then','except') AND jsonb_array_length(node->'children')<>2)
   THEN errors:=errors||'["expression:INVALID_GROUP"]'::jsonb; END IF;
   FOR c IN SELECT value::integer FROM jsonb_array_elements_text(node->'children') LOOP
    IF c<=j OR c>=n OR c=ANY(seen) THEN errors:=errors||'["expression:INVALID_CHILD"]'::jsonb;
    ELSE seen:=array_append(seen,c); END IF;
   END LOOP;
  END IF;
 END LOOP;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.output_issues_v2(output jsonb, source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]'; passages jsonb:=enrichment.source_passages_v2(source); section text; x jsonb; ev jsonb;
 ids jsonb; id text; quote text; field text; value text; kind text; positive_absence boolean;
BEGIN
 IF (SELECT count(*) FROM jsonb_array_elements(output->'positions')) <>
    (SELECT count(DISTINCT p->>'id') FROM jsonb_array_elements(output->'positions') p)
 THEN errors:=errors||'["positions:DUPLICATE_ID"]'::jsonb; END IF;
 FOREACH section IN ARRAY ARRAY['positions','duties','requirements'] LOOP
  FOR x IN SELECT jsonb_array_elements(output->section) LOOP
   ids:=x->'evidence_ids';
   IF jsonb_array_length(ids)=0 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(ids) r WHERE NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(passages) p WHERE p->>'id'=r))
   THEN errors:=errors||jsonb_build_array(section||':UNKNOWN_EVIDENCE_ID'); CONTINUE; END IF;
   IF (SELECT count(DISTINCT p->>'field') FROM jsonb_array_elements(passages) p WHERE ids @> jsonb_build_array(p->>'id'))<>1
   THEN errors:=errors||jsonb_build_array(section||':MIXED_EVIDENCE_FIELDS'); CONTINUE; END IF;
   IF (SELECT count(*) FROM jsonb_array_elements(ids))<>(SELECT count(DISTINCT v) FROM jsonb_array_elements(ids) v)
   THEN errors:=errors||jsonb_build_array(section||':DUPLICATE_EVIDENCE_ID'); END IF;
   ev:=enrichment.evidence_v2(ids,passages,source); field:=ev->>'field'; quote:=ev->>'quote';
   value:=CASE WHEN section='positions' THEN x->>'name' ELSE x->>'text' END;
   IF nullif(btrim(value),'') IS NULL OR
    coalesce(position(enrichment.fold_space_v2(value) in enrichment.fold_space_v2(quote)),0)=0
   THEN errors:=errors||jsonb_build_array(section||':UNSUPPORTED_TEXT'); END IF;
   IF section<>'positions' THEN
    FOR id IN SELECT jsonb_array_elements_text(x->'position_ids') LOOP
     IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(output->'positions') p WHERE p->>'id'=id)
     THEN errors:=errors||jsonb_build_array(section||':UNKNOWN_POSITION_ID'); END IF;
    END LOOP;
    IF (SELECT count(*) FROM jsonb_array_elements(x->'position_ids'))<>
       (SELECT count(DISTINCT v) FROM jsonb_array_elements(x->'position_ids') v)
    THEN errors:=errors||jsonb_build_array(section||':DUPLICATE_POSITION_ID'); END IF;
   END IF;
   IF section='duties' AND field NOT IN ('eligibility_text','selection_text','duties_text','description_text')
    AND NOT enrichment.is_attachment_field(source,field)
   THEN errors:=errors||'["duties:NON_DUTY_FIELD"]'::jsonb; END IF;
   IF section='requirements' THEN
    kind:=x->>'kind';
    IF field IN ('title','organization_name','recruitment_type','employment_type','regions','ncs_category_codes','ncs_category_names')
    THEN errors:=errors||'["requirements:METADATA_AS_CONDITION"]'::jsonb; END IF;
    IF field='preference_text' AND kind<>'preference'
    THEN errors:=errors||'["requirements:PREFERENCE_KIND"]'::jsonb; END IF;
    positive_absence:=value ~ '(결격.{0,25}(없는|없어야|없고|해당하지)|(해당|저촉)(되)?지.{0,5}(않는|아니한|않은))';
    IF field='disqualification_text' AND kind NOT IN ('exclusion','unrestricted') AND NOT positive_absence
    THEN errors:=errors||'["requirements:EXCLUSION_AS_ELIGIBILITY"]'::jsonb; END IF;
    -- Targeted polarity checks catch observed failures; they are not a complete semantic proof.
    IF value ~ '(파산.{0,30}복권되지|징계를 받은 자|징계를 받은 사람)' AND kind<>'exclusion'
    THEN errors:=errors||'["requirements:EXCLUSION_AS_ELIGIBILITY"]'::jsonb; END IF;
    IF positive_absence AND kind='exclusion'
    THEN errors:=errors||'["requirements:ABSENCE_AS_EXCLUSION"]'::jsonb; END IF;
    IF value ~ '^(학력|경력)[[:space:]]*(무관|제한[[:space:]]*없음)[[:space:].]*$' AND kind<>'unrestricted'
    THEN errors:=errors||'["requirements:UNRESTRICTED_AS_REQUIRED"]'::jsonb; END IF;
    -- Do not reject contextual comma-list alternatives. A clear AND-only group is different.
    IF x->>'logic'='any_of' AND value ~ '( 및 | 모두 )' AND
     value !~ '(또는|혹은|거나|중.{0,15}(하나|한.?가지|1개|1가지)|[,/])'
    THEN errors:=errors||'["requirements:OR_FOR_AND_ONLY"]'::jsonb; END IF;
    errors:=errors||enrichment.expression_issues_v2(x,quote);
   END IF;
  END LOOP;
  IF (SELECT count(*) FROM jsonb_array_elements(output->section))<>
     (SELECT count(DISTINCT v) FROM jsonb_array_elements(output->section) v)
  THEN errors:=errors||jsonb_build_array(section||':DUPLICATE'); END IF;
 END LOOP;
 IF (jsonb_array_length(output->'duties')>0) IS DISTINCT FROM (output->>'duties_status'='explicit')
 THEN errors:=errors||'["duties:STATUS_MISMATCH"]'::jsonb; END IF;
 IF nullif(btrim(source->>'education'),'') IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(output->'requirements') r
  WHERE r->>'category'='education' AND EXISTS(SELECT 1 FROM jsonb_array_elements(passages) p
   WHERE p->>'field'='education' AND r->'evidence_ids' @> jsonb_build_array(p->>'id')))
 THEN errors:=errors||'["requirements:EDUCATION_OMITTED"]'::jsonb; END IF;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.hydrate_v2(output jsonb, source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb:=output; passages jsonb:=enrichment.source_passages_v2(source); section text;
 x jsonb; rows jsonb; names jsonb;
BEGIN
 FOREACH section IN ARRAY ARRAY['positions','duties','requirements'] LOOP
  rows:='[]';
  FOR x IN SELECT jsonb_array_elements(output->section) LOOP
   x:=x||jsonb_build_object('evidence',enrichment.evidence_v2(x->'evidence_ids',passages,source));
   IF section<>'positions' THEN
    SELECT coalesce(jsonb_agg(p->'name' ORDER BY p->>'id'),'[]') INTO names
    FROM jsonb_array_elements(output->'positions') p WHERE x->'position_ids' @> jsonb_build_array(p->>'id');
    x:=x||jsonb_build_object('position_names',names,'position',CASE WHEN jsonb_array_length(names)=1 THEN names->0 ELSE 'null'::jsonb END);
   END IF;
   IF section='requirements' THEN x:=x||jsonb_build_object('importance',CASE x->>'kind'
    WHEN 'eligibility' THEN 'required' WHEN 'preference' THEN 'preferred'
    WHEN 'exclusion' THEN 'excluded' WHEN 'unrestricted' THEN 'unrestricted' END); END IF;
   rows:=rows||jsonb_build_array(x);
  END LOOP;
  result:=jsonb_set(result,ARRAY[section],rows);
 END LOOP;
 -- Source metadata stays authoritative and is copied without model inference.
 RETURN result||jsonb_build_object('schema_version','ko-v2','source_metadata',
  enrichment.source_fields(source)-ARRAY['eligibility_text','preference_text','selection_text','disqualification_text','duties_text','description_text']);
END $$;

-- Korean word fragments recover compound nouns/particles; document frequency discounts
-- generic matches. Equal per-duty ranks prevent one position consuming the whole list.
CREATE OR REPLACE FUNCTION enrichment.candidates_v2(ncs_run text, source jsonb, extraction jsonb, cap integer)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 WITH words AS MATERIALIZED (
  SELECT DISTINCT ordinal AS duty,word FROM jsonb_array_elements(extraction->'duties') WITH ORDINALITY d(value,ordinal)
  CROSS JOIN LATERAL regexp_split_to_table(lower(d.value->>'text'),'[^가-힣a-z0-9]+') word
  WHERE length(word) BETWEEN 2 AND 40 AND word NOT IN ('업무','직무','관련','담당','수행','관리','지원','대한','통한','기타','회사','전반','포함')
 ), terms AS MATERIALIZED (
  SELECT duty,term,max(weight) AS weight FROM (
   SELECT duty,word AS term,1.0::numeric AS weight FROM words
   UNION ALL
   SELECT duty,substring(word FROM pos FOR len),CASE WHEN len=3 THEN 0.65 ELSE 0.35 END
   FROM words CROSS JOIN generate_series(2,3) len CROSS JOIN LATERAL generate_series(1,length(word)-len+1) pos
   WHERE word ~ '^[가-힣]+$' AND length(word)>len
  ) t WHERE term NOT IN ('업무','직무','관련','담당','수행','관리','지원','대한','통한','기타','회사','전반','포함','하는','한다','에서','으로')
  GROUP BY duty,term ORDER BY duty,weight DESC,length(term) DESC,term LIMIT 480
 ), hits AS MATERIALIZED (
  SELECT t.*,c.code,CASE WHEN position(t.term in lower(c.name))>0 THEN 8
   WHEN position(t.term in lower(coalesce(c.occupation_name,'')))>0 THEN 4 ELSE 1 END AS location_weight
  FROM enrichment.ncs_catalog c JOIN terms t ON position(t.term in
   lower(c.name||' '||coalesce(c.occupation_name,'')||' '||coalesce(c.definition,'')))>0 WHERE c.run_id=ncs_run
 ), frequencies AS (
  SELECT term,count(DISTINCT code) AS df FROM hits GROUP BY term
 ), scored AS (
  SELECT h.duty,h.code,sum(h.weight*h.location_weight*ln(1.0+
   (SELECT count(*) FROM enrichment.ncs_catalog WHERE run_id=ncs_run)::numeric/f.df)) AS score
  FROM hits h JOIN frequencies f USING(term) GROUP BY h.duty,h.code
 ), ranked AS (
  SELECT *,row_number() OVER(PARTITION BY duty ORDER BY score DESC,code) AS rank FROM scored
 ), picked AS (
  SELECT code,max(score) AS score,min(rank) AS rank FROM ranked GROUP BY code ORDER BY min(rank),max(score) DESC,code LIMIT cap
 ) SELECT coalesce(jsonb_agg(jsonb_build_object('code',c.code,'name',c.name,'definition',c.definition,
   'occupation_code',c.occupation_code,'occupation_name',c.occupation_name,'retrieval_score',round(p.score,3))
   ORDER BY p.rank,p.score DESC,c.code),'[]') FROM picked p JOIN enrichment.ncs_catalog c USING(code) WHERE c.run_id=ncs_run
$$;
COMMIT;
