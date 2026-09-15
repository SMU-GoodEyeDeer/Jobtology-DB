-- Compact source accounting; historical ko-v1..v6 contracts remain unchanged.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.range_passages_v7(output jsonb,source jsonb)
RETURNS TABLE(range_index integer,range_data jsonb,passage jsonb) LANGUAGE sql IMMUTABLE AS $$
 WITH passages AS MATERIALIZED (SELECT p FROM jsonb_array_elements(enrichment.source_passages_v2(source)) p)
 SELECT (r.ordinality-1)::integer,r.value,p
 FROM jsonb_array_elements(output->'unhandled_ranges') WITH ORDINALITY r
 JOIN passages ON split_part(p->>'id',':',1)=split_part(r.value->>'first_id',':',1)
  AND split_part(p->>'id',':',2)::integer BETWEEN split_part(r.value->>'first_id',':',2)::integer AND split_part(r.value->>'last_id',':',2)::integer
$$;

CREATE OR REPLACE FUNCTION enrichment.range_issues_v7(output jsonb,source jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:='[]';r jsonb;first_passage jsonb;last_passage jsonb;
 passages jsonb:=enrichment.source_passages_v2(source); BEGIN
 FOR r IN SELECT jsonb_array_elements(output->'unhandled_ranges') LOOP
  SELECT p INTO first_passage FROM jsonb_array_elements(passages) p WHERE p->>'id'=r->>'first_id';
  SELECT p INTO last_passage FROM jsonb_array_elements(passages) p WHERE p->>'id'=r->>'last_id';
  IF first_passage IS NULL OR last_passage IS NULL THEN errors:=errors||'["coverage:UNKNOWN_RANGE_BOUNDARY"]';CONTINUE; END IF;
  IF first_passage->>'field'<>last_passage->>'field' OR (first_passage->>'start')::integer>(last_passage->>'start')::integer
  THEN errors:=errors||'["coverage:INVALID_RANGE_ORDER_OR_FIELD"]'; END IF;
  IF NOT enrichment.narrative_field(source,first_passage->>'field') THEN errors:=errors||'["coverage:NON_NARRATIVE_RANGE"]'; END IF;
  IF (r->>'disposition'='document_context') IS DISTINCT FROM (r->>'context_kind' IS NOT NULL)
  THEN errors:=errors||'["coverage:INVALID_CONTEXT_KIND"]'; END IF;
  IF (r->>'disposition'='duplicate') IS DISTINCT FROM (r->>'duplicate_of' IS NOT NULL) OR
   (r->>'disposition'='duplicate' AND r->>'first_id'<>r->>'last_id')
  THEN errors:=errors||'["coverage:INVALID_DUPLICATE_RANGE"]'; END IF;
 END LOOP;
 IF errors<>'[]' THEN RETURN errors; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.range_passages_v7(output,source) GROUP BY passage->>'id' HAVING count(*)>1)
 THEN errors:=errors||'["coverage:OVERLAPPING_RANGES"]'; END IF;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.expand_ranges_v7(output jsonb,source jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT (output-'unhandled_ranges')||jsonb_build_object('unhandled_passages',coalesce((
  SELECT jsonb_agg(jsonb_build_object('evidence_id',passage->>'id',
   'disposition',CASE WHEN range_data->>'disposition'='document_context' THEN 'procedure' ELSE range_data->>'disposition' END,
   'reason',range_data->>'reason','duplicate_of',range_data->>'duplicate_of') ORDER BY range_index,(passage->>'start')::integer)
  FROM enrichment.range_passages_v7(output,source)),'[]'))
$$;

CREATE OR REPLACE FUNCTION enrichment.heading_v7(value text) RETURNS boolean LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT enrichment.heading_v6(value) OR (length(value)<=80 AND
  enrichment.fold_space_v2(regexp_replace(translate(value,'<>[]○·※*-:()【】□■','                  '),'^[[:space:]0-9.ⅠⅡⅢⅣ]+',''))
  ~ '^(붙임[[:space:]]*[0-9]*|별첨[[:space:]]*[0-9]*|채용[[:space:]]*(공고|분야|인원|분야[[:space:]]*및[[:space:]]*인원)|모집[[:space:]]*(분야|인원)|응시원서|입사지원서|이력서|자기소개서|개인정보[[:space:]]*(수집|이용|수집·이용)[[:space:]]*동의서|직무기술서|직무[[:space:]]*(분류|내용|수행내용)|필요[[:space:]]*(지식|기술|태도)|직무수행태도|근무[[:space:]]*(조건|장소|예정지)|보수|급여|연봉|전형[[:space:]]*(일정|절차)|제출[[:space:]]*서류|지원[[:space:]]*방법|접수[[:space:]]*(기간|방법)|유의[[:space:]]*사항|성명|생년월일|연락처|주소|학력|경력|자격|자격증|비고|구분|항목|내용|인원|분야|직종|직급|전공|대분류|중분류|소분류|세분류|능력단위|담당업무|참고[[:space:]]*사이트)$')
$$;

-- These guards distinguish recognizable document context from obvious applicant
-- restrictions. They are not a semantic approval or a complete Korean parser.
CREATE OR REPLACE FUNCTION enrichment.context_allowed_v7(kind text,line text,body text,first_line text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN
 IF line ~ '(소지자|소지한[[:space:]]*자|응시자격|지원자격|결격|병역.*(기피|불이행)|가점|가산|우대(사항|조건|대상|자격|[[:space:]:()]|$)|필수([[:space:]:()]|조건|자격|요건)|합격.*취소|자격.*미달|부적격|응시.*(제한|불가)|만[[:space:]]*[0-9]+[[:space:]]*세|정년|경력[[:space:]]*[0-9]+[[:space:]]*(년|개월))'
 THEN RETURN false; END IF;
 CASE kind
 WHEN 'employment_terms' THEN RETURN body ~ '(급여|보수|연봉|월급|임금|수당|근무|근로|계약|시급|휴일|복리후생)';
 WHEN 'application_form' THEN RETURN first_line ~ '(응시원서|입사지원서|지원서[[:space:]]*양식|이력서|자기소개서|동의서|서약서|신청서)';
 WHEN 'institution_background' THEN RETURN body ~ '(기관|병원|공단|공사|재단|설립|소개|목적|미션|비전|역할)' AND line !~ '(응시|지원자|학위|면허|자격증)';
 WHEN 'job_profile' THEN RETURN body ~ '(지식|기술|능력|태도|직무|직업|NCS|분류)' AND line !~ '(응시|지원자|지원[[:space:]]*가능)';
 WHEN 'document_structure' THEN RETURN enrichment.heading_v7(line) OR btrim(line) ~ '^[-_[:space:]0-9()/.ⅠⅡⅢⅣ]+$';
 WHEN 'privacy_notice' THEN RETURN body ~ '(개인정보|수집|보유|처리|제공|파기|동의)' AND line !~ '(면허|자격증|학위|경력)';
 ELSE RETURN false;
 END CASE;
END $$;

CREATE OR REPLACE FUNCTION enrichment.output_issues_v7(output jsonb,source jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE errors jsonb:=enrichment.range_issues_v7(output,source);expanded jsonb;issue text;ref text;
 p jsonb;u jsonb;body text;first_line text; BEGIN
 IF errors<>'[]' THEN RETURN errors; END IF;
 expanded:=enrichment.expand_ranges_v7(output,source);
 FOR issue IN SELECT jsonb_array_elements_text(enrichment.output_issues_v6(expanded,source)) LOOP
  IF issue LIKE 'coverage:UNPROVEN_HEADING:%' THEN
   ref:=substring(issue FROM length('coverage:UNPROVEN_HEADING:')+1);
   SELECT passage INTO p FROM enrichment.range_passages_v7(output,source) WHERE passage->>'id'=ref;
   IF enrichment.heading_v7(p->>'text') THEN CONTINUE; END IF;
  ELSIF issue LIKE 'coverage:POSSIBLE_OMITTED_CONDITION:%' THEN
   ref:=substring(issue FROM length('coverage:POSSIBLE_OMITTED_CONDITION:')+1);
   SELECT passage,range_data INTO p,u FROM enrichment.range_passages_v7(output,source) WHERE passage->>'id'=ref;
   IF u->>'disposition'='document_context' THEN
    SELECT string_agg(passage->>'text',E'\n' ORDER BY (passage->>'start')::integer),
     (array_agg(passage->>'text' ORDER BY (passage->>'start')::integer))[1] INTO body,first_line
    FROM enrichment.range_passages_v7(output,source) WHERE range_data=u;
    IF enrichment.context_allowed_v7(u->>'context_kind',p->>'text',body,first_line) THEN CONTINUE; END IF;
   END IF;
  END IF;
  errors:=errors||jsonb_build_array(issue);
 END LOOP;
 FOR u IN SELECT jsonb_array_elements(output->'unhandled_ranges') LOOP
  IF u->>'disposition'<>'document_context' THEN CONTINUE; END IF;
  SELECT string_agg(passage->>'text',E'\n' ORDER BY (passage->>'start')::integer),
   (array_agg(passage->>'text' ORDER BY (passage->>'start')::integer))[1] INTO body,first_line
   FROM enrichment.range_passages_v7(output,source) WHERE range_data=u;
  FOR p IN SELECT passage FROM enrichment.range_passages_v7(output,source) WHERE range_data=u LOOP
   IF NOT enrichment.context_allowed_v7(u->>'context_kind',p->>'text',body,first_line)
   THEN errors:=errors||jsonb_build_array('coverage:UNPROVEN_DOCUMENT_CONTEXT:'||(p->>'id')); END IF;
  END LOOP;
 END LOOP;
 FOR u IN SELECT jsonb_array_elements(output->'requirements') LOOP
  body:=enrichment.join_parts_v3(u->'text_parts');
  IF u->>'logic' IN ('single','unspecified') AND u->>'kind' IN ('eligibility','exclusion')
   AND body ~ '(면허증?|자격증|학위)[^.!?;]{0,80}[[:space:]]및[[:space:]].*(면허|자격증|학위|경력)'
   AND body !~ '(또는|중[[:space:]]*(하나|1)|어느[[:space:]]*하나|선택)'
  THEN errors:=errors||'["requirements:COMPOUND_CREDENTIAL_LOGIC_REQUIRED"]'; END IF;
 END LOOP;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.coverage_v7(output jsonb,source jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 WITH baseline AS (SELECT c,ordinality FROM jsonb_array_elements(enrichment.coverage_v6(enrichment.expand_ranges_v7(output,source),source)) WITH ORDINALITY t(c,ordinality))
 SELECT coalesce(jsonb_agg(c||CASE WHEN r.range_data IS NOT NULL THEN jsonb_build_object('disposition',r.range_data->>'disposition',
  'context_kind',r.range_data->'context_kind','range_index',r.range_index) ELSE '{}'::jsonb END ORDER BY b.ordinality),'[]')
 FROM baseline b LEFT JOIN enrichment.range_passages_v7(output,source) r ON r.passage->>'id'=c->>'evidence_id'
$$;

CREATE OR REPLACE FUNCTION enrichment.hydrate_v7(output jsonb,source jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT base||jsonb_build_object('schema_version','ko-v7','validation_policy','ranged-source-accounting-v1',
  'provider_output_hash',enrichment.hash(output::text),'source_coverage',enrichment.coverage_v7(output,source),
  'source_ranges',output->'unhandled_ranges','source_accounting_encoding','ranges-to-passages-v1',
  'normalization',(base->'normalization')||jsonb_build_object('policy','ranged-source-proof-v1','provider_output_hash',enrichment.hash(output::text)))
 FROM (SELECT enrichment.hydrate_v6(enrichment.expand_ranges_v7(output,source),source) AS base) h
$$;
COMMIT;
