BEGIN;
DO $$ BEGIN
 IF to_regclass('ontology.occupation_membership') IS NULL OR to_regclass('ontology.cohort_profile_membership') IS NULL
  OR to_regclass('ontology.duplicate_membership') IS NULL
 THEN RAISE EXCEPTION 'INSTALL_EDITORIAL_AND_COHORT_PREPARATION_FIRST'; END IF;
 IF pg_collation_actual_version('pg_catalog.pg_c_utf8'::regcollation)<>'1'
 THEN RAISE EXCEPTION 'COHORT_UNICODE_COLLATION_VERSION_UNSUPPORTED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_filter_v1(occupation text,as_of date) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT jsonb_build_object('methodology','posting-cohort-job-alio-v1','occupation_id',occupation,'sources',jsonb_build_array('JOB_ALIO'),
  'country','KR','as_of',as_of,'window_start',as_of-179,'window_end',as_of,'window_days',180,'timezone','Asia/Seoul',
  'experience_policy','reviewed-cohort-profiles-v1','language_policy','job-alio-inline-language-v1',
  'language_min_hangul_syllables',100,'language_min_hangul_letter_percent',30,'letter_collation','pg_c_utf8','collation_version','1',
  'description_fields',jsonb_build_array('description_text','duties_text','eligibility_text','preference_text','disqualification_text','selection_text'),
  'locale_field','locale','duplicate_policy','reviewed-duplicate-groups-v1','representative_scope','ELIGIBLE_MEMBERS',
  'representative_order',jsonb_build_array('effective_modified_at DESC','JOB_ALIO BEFORE SARAMIN','posting_id COLLATE C ASC'),
  'effective_time_fields',jsonb_build_array('source_modified_at','source_published_at','date_posted','retrieved_at'),
  'date_only_ordering','KST_DAY_START_ORDER_KEY_ONLY','minimum_ratio_denominator',30)
$$;

-- This is the description adapter for the current structured API body. It
-- does not read attachments or count extracted/model-generated summaries.
CREATE OR REPLACE FUNCTION ontology.cohort_language_v1(payload jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE k text;v text;body text:='';fields jsonb:='[]';locale text;hangul bigint;letters bigint; BEGIN
 FOREACH k IN ARRAY ARRAY['title','description_text','duties_text','eligibility_text','preference_text','disqualification_text','selection_text'] LOOP
  IF jsonb_typeof(payload->k)='string' THEN
   v:=ontology.normalize_text(payload->>k);
   IF length(v)>0 THEN
    body:=body||CASE WHEN body='' THEN '' ELSE E'\n' END||v;
    fields:=fields||jsonb_build_array(jsonb_build_object('field',k,'text_hash',enrichment.hash(v),'code_points',length(v)));
   END IF;
  END IF;
 END LOOP;
 IF jsonb_typeof(payload->'locale')='string' THEN locale:=payload->>'locale'; END IF;
 hangul:=length(regexp_replace(body COLLATE pg_catalog.pg_c_utf8,'[^가-힣]','','g'));
 letters:=length(regexp_replace(body COLLATE pg_catalog.pg_c_utf8,'[^[:alpha:]]','','g'));
 RETURN jsonb_build_object('policy','job-alio-inline-language-v1','fields',fields,'text_hash',enrichment.hash(body),
  'locale',locale,'locale_field',CASE WHEN locale IS NOT NULL THEN 'locale' END,
  'hangul_syllables',hangul,'letter_count',letters,'hangul_letter_ratio',CASE WHEN letters>0 THEN hangul::numeric/letters END,
  'eligible',coalesce(replace(lower(locale),'_','-')~'^ko(-[a-z0-9]{2,8})*$',false) OR (hangul>=100 AND hangul*10>=letters*3));
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_temporal_v1(payload jsonb,retrieved_at timestamptz) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE published date;date_issue text;field text;raw text;stamp timestamptz;precision text;issue text; BEGIN
 raw:=nullif(btrim(payload->>'date_posted'),'');
 IF raw IS NULL THEN date_issue:='POSTING_DATE_UNKNOWN';
 ELSE
  BEGIN
   IF raw !~ '^\d{4}-\d{2}-\d{2}$' THEN RAISE EXCEPTION 'invalid'; END IF;
   published:=raw::date;IF NOT isfinite(published) THEN RAISE EXCEPTION 'invalid'; END IF;
  EXCEPTION WHEN OTHERS THEN date_issue:='POSTING_DATE_INVALID';published:=NULL;END;
 END IF;
 IF nullif(btrim(payload->>'source_modified_at'),'') IS NOT NULL THEN field:='source_modified_at';
 ELSIF nullif(btrim(payload->>'source_published_at'),'') IS NOT NULL THEN field:='source_published_at';
 ELSIF published IS NOT NULL THEN field:='date_posted'; ELSE field:='retrieved_at'; END IF;
 raw:=CASE WHEN field='retrieved_at' THEN to_char(retrieved_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') ELSE payload->>field END;
 IF field='date_posted' THEN stamp:=published::timestamp AT TIME ZONE 'Asia/Seoul';precision:='DAY';
 ELSIF field='retrieved_at' THEN stamp:=retrieved_at;precision:='INSTANT';
 ELSE
  precision:='INSTANT';
  BEGIN
   IF raw !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$' THEN RAISE EXCEPTION 'invalid'; END IF;
   stamp:=raw::timestamptz;IF NOT isfinite(stamp) THEN RAISE EXCEPTION 'invalid'; END IF;
  EXCEPTION WHEN OTHERS THEN issue:='ORDERING_TIMESTAMP_INVALID';stamp:=NULL;END;
 END IF;
 IF stamp IS NULL AND issue IS NULL THEN issue:='ORDERING_TIMESTAMP_UNKNOWN'; END IF;
 RETURN jsonb_build_object('published_on',published,'date_field','date_posted','date_value',payload->>'date_posted',
  'date_precision','DAY','date_issue',date_issue,'ordering_field',field,'ordering_source_value',raw,'effective_precision',precision,
  'effective_timestamp_at',CASE WHEN precision='INSTANT' THEN to_char(stamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') END,
  'ordering_at',to_char(stamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'ordering_issue',issue,
  'date_only_ordering','KST_DAY_START_ORDER_KEY_ONLY');
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_dependencies_v1(id text) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.observation_membership WHERE release_id=id)
  OR NOT EXISTS(SELECT 1 FROM ontology.occupation_membership WHERE release_id=id)
  OR NOT EXISTS(SELECT 1 FROM ontology.requirement_membership WHERE release_id=id)
  OR NOT EXISTS(SELECT 1 FROM ontology.cohort_profile_membership WHERE release_id=id)
  OR NOT EXISTS(SELECT 1 FROM ontology.duplicate_membership WHERE release_id=id)
 THEN RAISE EXCEPTION 'COHORT_FROZEN_INPUTS_REQUIRED'; END IF;
 PERFORM ontology.verify_claims(id);PERFORM ontology.verify_observation_membership_v1(id);
 PERFORM editorial.verify_pin_v1(id);PERFORM ontology.verify_occupations_v1(id);
 PERFORM ontology.verify_requirements_v1(id);PERFORM ontology.verify_cohort_profiles_v1(id);PERFORM ontology.verify_duplicates_v1(id);
 RETURN jsonb_build_object('observation',(SELECT manifest_hash FROM ontology.observation_membership WHERE release_id=id),
  'editorial',(SELECT manifest_hash FROM editorial.release_pin WHERE release_id=id),
  'occupation',(SELECT manifest_hash FROM ontology.occupation_membership WHERE release_id=id),
  'requirement',(SELECT manifest_hash FROM ontology.requirement_membership WHERE release_id=id),
  'profile',(SELECT manifest_hash FROM ontology.cohort_profile_membership WHERE release_id=id),
  'duplicate',(SELECT manifest_hash FROM ontology.duplicate_membership WHERE release_id=id),
  'collation_version',pg_collation_actual_version('pg_catalog.pg_c_utf8'::regcollation));
END $$;
COMMIT;
