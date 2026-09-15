-- Clause scope and parent-list evidence. Earlier validators remain unchanged.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.logic_text_v5(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT regexp_replace(
  regexp_replace(value,'[「『][^」』]*[」』]','','g'),
  '제[0-9]+조(제[0-9]+항)?(제[0-9]+호)?[[:space:]]*및[[:space:]]*제[0-9]+(조|항|호)','법령조항','g')
$$;

CREATE OR REPLACE FUNCTION enrichment.parent_context_v5(x jsonb,source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 WITH passages AS MATERIALIZED (SELECT p FROM jsonb_array_elements(enrichment.source_passages_v2(source)) p),
 children AS (SELECT p FROM passages WHERE x->'evidence_ids' @> jsonb_build_array(p->>'id')
  AND p->>'text' ~ '^[[:space:]]*[가나다라마바사아자차카타파하][.)][[:space:]]*'),
 parents AS (
  SELECT DISTINCT parent.p FROM children c CROSS JOIN LATERAL (
   SELECT a.p FROM passages a WHERE a.p->>'field'=c.p->>'field'
   AND (a.p->>'start')::integer<(c.p->>'start')::integer
   AND a.p->>'text' ~ '(다음|아래).{0,40}(어느|하나|각[[:space:]]*[목호])'
   AND NOT EXISTS(SELECT 1 FROM passages b WHERE b.p->>'field'=c.p->>'field'
    AND (b.p->>'start')::integer>(a.p->>'start')::integer AND (b.p->>'start')::integer<(c.p->>'start')::integer
    AND b.p->>'text' ~ '^[[:space:]]*[0-9]+[.)][[:space:]]*')
   ORDER BY (a.p->>'start')::integer DESC LIMIT 1
  ) parent
 ) SELECT coalesce(jsonb_agg(p ORDER BY p->>'id'),'[]') FROM parents
$$;

CREATE OR REPLACE FUNCTION enrichment.output_issues_v5(output jsonb,source jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE normalized jsonb:=enrichment.normalize_v4(output,source); errors jsonb; x jsonb; parent jsonb;
 value text; logic_value text; quote text; kind text; positive_absence boolean; direct_bar boolean;
 parent_text text; passages jsonb:=enrichment.source_passages_v2(source);
BEGIN
 -- Preserve fragment, education, topology, scope and exception checks. Replace
 -- only the three observed broad polarity/AND tests with versioned checks.
 SELECT coalesce(jsonb_agg(e),'[]') INTO errors FROM jsonb_array_elements(enrichment.output_issues_v4(output,source)) e
 WHERE e#>>'{}' NOT IN ('requirements:EXCLUSION_AS_ELIGIBILITY','requirements:ABSENCE_AS_EXCLUSION','requirements:OR_FOR_AND_ONLY');
 FOR x IN SELECT jsonb_array_elements(normalized->'requirements') LOOP
  value:=enrichment.fold_space_v2(enrichment.join_parts_v3(x->'text_parts')); kind:=x->>'kind';
  quote:=enrichment.evidence_v2(x->'evidence_ids',passages,source)->>'quote';
  positive_absence:=value ~ '(결격.{0,25}(없는|없어야|없고|해당하지)|(해당|저촉)(되)?지.{0,5}(않는|아니한|않은)|(사실|전력)이[[:space:]]*없는)';
  direct_bar:=value ~ '((응시|임용|채용|지원).{0,12}(수[[:space:]]*없|불가)|파산.{0,30}복권되지|징계를 받은 (자|사람))';
  IF direct_bar AND positive_absence
  THEN errors:=errors||'["requirements:MIXED_POLARITY_REVIEW_REQUIRED"]'::jsonb; END IF;
  IF direct_bar AND NOT positive_absence AND kind<>'exclusion'
  THEN errors:=errors||'["requirements:EXCLUSION_AS_ELIGIBILITY"]'::jsonb; END IF;
  IF positive_absence AND kind='exclusion'
  THEN errors:=errors||'["requirements:ABSENCE_AS_EXCLUSION"]'::jsonb; END IF;
  -- Field names alone do not determine polarity. Quoted law names and article
  -- references also do not define Boolean logic between applicant conditions.
  logic_value:=enrichment.logic_text_v5(value);
  IF x->>'logic'='any_of' AND logic_value ~ '( 및 | 모두 )'
   AND enrichment.logic_text_v5(coalesce(quote,'')) !~ '(또는|혹은|거나|어느[[:space:]]*하나|중.{0,15}(하나|한.?가지|1개|1가지)|[,/])'
  THEN errors:=errors||'["requirements:OR_FOR_AND_ONLY"]'::jsonb; END IF;
  FOR parent IN SELECT jsonb_array_elements(enrichment.parent_context_v5(x,source)) LOOP
   IF NOT x->'evidence_ids' @> jsonb_build_array(parent->>'id')
   THEN errors:=errors||'["requirements:PARENT_CONTEXT_NOT_CITED"]'::jsonb; END IF;
   parent_text:=enrichment.fold_space_v2(regexp_replace(parent->>'text','^[[:space:]]*[0-9]+[.)][[:space:]]*',''));
   IF parent_text ~ '(벌금|징역|금고|[0-9]+[[:space:]]*(년|개월|만원)|필수|이상|이하|경과|지나)' THEN
    IF coalesce(position(parent_text in value),0)=0
    THEN errors:=errors||'["requirements:PARENT_CONDITION_OMITTED"]'::jsonb; END IF;
    IF x->>'logic' NOT IN ('all_of','conditional')
    THEN errors:=errors||'["requirements:SHARED_CONDITION_SCOPE_REVIEW_REQUIRED"]'::jsonb; END IF;
   END IF;
  END LOOP;
 END LOOP;
 RETURN errors;
END $$;

CREATE OR REPLACE FUNCTION enrichment.hydrate_v5(output jsonb,source jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT enrichment.hydrate_v4(output,source)||jsonb_build_object('schema_version','ko-v5','validation_policy','clause-scope-v5')
$$;

-- An audit never changes an attempt, makes a paid request or accepts a claim.
CREATE OR REPLACE FUNCTION enrichment.audit_extractions(id text,version text DEFAULT 'ko-v5') RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE b enrichment.batch%ROWTYPE; r record; existing enrichment.extraction_audit%ROWTYPE; errors jsonb; n integer:=0; digest text;
BEGIN
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=id FOR SHARE;
 IF b.state NOT IN ('COMPLETE','PARTIAL','FAILED') THEN RAISE EXCEPTION 'AUDIT_REQUIRES_TERMINAL_BATCH'; END IF;
 IF version IS DISTINCT FROM 'ko-v5' OR coalesce(b.settings->>'prompt_version','') NOT IN ('ko-v4','ko-v5')
  OR NOT EXISTS(SELECT 1 FROM enrichment.prompt WHERE prompt.version=audit_extractions.version AND stage='extract')
 THEN RAISE EXCEPTION 'UNSUPPORTED_AUDIT_CONTRACT'; END IF;
 FOR r IN SELECT i.source_data,i.source_hash,a.attempt_id,a.raw_output,a.state
  FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.batch_id=id LOOP
  IF r.state='RESERVED' THEN CONTINUE; END IF; -- The outcome of an in-flight call is still unknown.
  IF r.source_hash IS DISTINCT FROM enrichment.hash(r.source_data::text)
  THEN RAISE EXCEPTION 'AUDIT_SOURCE_HASH_MISMATCH'; END IF;
  digest:=enrichment.hash(coalesce(r.raw_output::text,'null'));
  SELECT * INTO existing FROM enrichment.extraction_audit WHERE attempt_id=r.attempt_id AND validator_version=version;
  IF FOUND THEN
   IF existing.raw_output_hash<>digest OR existing.source_hash<>r.source_hash THEN RAISE EXCEPTION 'AUDIT_INPUT_CHANGED'; END IF;
   CONTINUE;
  END IF;
  IF r.raw_output IS NULL THEN errors:='["MISSING_PROVIDER_OUTPUT"]'::jsonb;
  ELSE
   SELECT enrichment.schema_issues(r.raw_output,p.output_schema) INTO errors FROM enrichment.prompt p WHERE p.version=audit_extractions.version AND stage='extract';
   IF errors='[]' THEN errors:=enrichment.output_issues_v5(r.raw_output,r.source_data); END IF;
  END IF;
  INSERT INTO enrichment.extraction_audit(attempt_id,validator_version,raw_output_hash,source_hash,issues)
  VALUES(r.attempt_id,version,digest,r.source_hash,errors); n:=n+1;
 END LOOP;
 RETURN n;
END $$;

-- Compatible JSON shape, separately recorded interpretation policy. Do not
-- pretend the original model was called with the newer prompt or charge again.
CREATE OR REPLACE FUNCTION enrichment.capture_revalidated(id text,actor text,reason text,version text DEFAULT 'ko-v5') RETURNS text
LANGUAGE plpgsql AS $$
DECLARE i enrichment.item%ROWTYPE; b enrichment.batch%ROWTYPE; a enrichment.attempt%ROWTYPE;
 audit enrichment.extraction_audit%ROWTYPE; output jsonb; rid text;
BEGIN
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=id FOR UPDATE;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=i.batch_id;
 IF b.mode<>'ENRICH' THEN RAISE EXCEPTION 'EVAL_CANNOT_ENTER_PRODUCTION_REVIEW'; END IF;
 IF b.state NOT IN ('COMPLETE','PARTIAL','FAILED') THEN RAISE EXCEPTION 'CAPTURE_REQUIRES_TERMINAL_ENRICHMENT'; END IF;
 IF version IS DISTINCT FROM 'ko-v5' OR coalesce(b.settings->>'prompt_version','') NOT IN ('ko-v4','ko-v5') THEN RAISE EXCEPTION 'UNSUPPORTED_AUDIT_CONTRACT'; END IF;
 IF nullif(btrim(actor),'') IS NULL OR nullif(btrim(reason),'') IS NULL THEN RAISE EXCEPTION 'REVIEW_PROVENANCE_REQUIRED'; END IF;
 SELECT * INTO STRICT a FROM enrichment.attempt WHERE attempt_id=i.extraction_id;
 SELECT * INTO STRICT audit FROM enrichment.extraction_audit WHERE attempt_id=a.attempt_id AND validator_version=version;
 IF audit.issues<>'[]' OR audit.raw_output_hash<>enrichment.hash(coalesce(a.raw_output::text,'null')) OR audit.source_hash<>i.source_hash
  OR i.source_hash IS DISTINCT FROM enrichment.hash(i.source_data::text)
 THEN RAISE EXCEPTION 'REVALIDATION_NOT_CLEAN_OR_CHANGED'; END IF;
 IF enrichment.output_issues_v5(a.raw_output,i.source_data)<>'[]' THEN RAISE EXCEPTION 'REVALIDATION_NOT_CLEAN_OR_CHANGED'; END IF;
 output:=enrichment.hydrate_v5(a.raw_output,i.source_data)||jsonb_build_object('provider_prompt_version',b.settings->>'prompt_version',
  'revalidation',jsonb_build_object('validator_version',version,'original_attempt_id',a.attempt_id,'original_state',a.state,'audit_raw_hash',audit.raw_output_hash));
 rid:=enrichment.hash(jsonb_build_array(id,NULL,b.settings->>'prompt_version',version,a.raw_output)::text);
 IF EXISTS(SELECT 1 FROM enrichment.extraction_revision WHERE revision_id=rid) THEN RETURN rid; END IF;
 -- Never displace a later manual correction or an existing review silently.
 IF EXISTS(SELECT 1 FROM enrichment.extraction_revision WHERE item_id=id) THEN RAISE EXCEPTION 'EXISTING_REVISION_REQUIRES_EXPLICIT_CORRECTION'; END IF;
 INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason)
 VALUES(rid,id,a.raw_output,output,actor,reason);
 RETURN rid;
END $$;

CREATE OR REPLACE FUNCTION enrichment.capture_clean_audit(id text,actor text,reason text,version text DEFAULT 'ko-v5') RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE r record; n integer:=0;
BEGIN
 IF version IS DISTINCT FROM 'ko-v5' THEN RAISE EXCEPTION 'UNSUPPORTED_AUDIT_CONTRACT'; END IF;
 IF nullif(btrim(actor),'') IS NULL OR nullif(btrim(reason),'') IS NULL THEN RAISE EXCEPTION 'REVIEW_PROVENANCE_REQUIRED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM enrichment.batch WHERE batch_id=id AND mode='ENRICH' AND state IN ('COMPLETE','PARTIAL','FAILED'))
 THEN RAISE EXCEPTION 'CAPTURE_REQUIRES_TERMINAL_ENRICHMENT'; END IF;
 FOR r IN SELECT i.item_id FROM enrichment.item i JOIN enrichment.extraction_audit a ON a.attempt_id=i.extraction_id
  WHERE i.batch_id=id AND a.validator_version=version AND a.issues='[]'
  AND NOT EXISTS(SELECT 1 FROM enrichment.extraction_revision e WHERE e.item_id=i.item_id) LOOP
  PERFORM enrichment.capture_revalidated(r.item_id,actor,reason,version); n:=n+1;
 END LOOP;
 RETURN n;
END $$;
COMMIT;
