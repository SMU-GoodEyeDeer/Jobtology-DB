-- Execute SQL script: execute for each row, bind parameters, single statement.
-- Bind in order: run_id, document_id, locator, source_payload_json,
-- normalized_block_json, field_lineage_json, quality_flags_json.
-- JSON Output must emit {"row":[{...}]} with exactly one row per block.
-- This statement writes only LOADING runs. Treat zero affected rows as an error.
WITH input AS (
    SELECT CAST(? AS text) AS run_id, CAST(? AS text) AS document_id,
           CAST(? AS text) AS locator, CAST(? AS jsonb) AS source_payload,
           CAST(? AS jsonb)->'row'->0 AS flat,
           CAST(? AS jsonb) AS field_lineage, CAST(? AS jsonb) AS quality_flags
), shaped AS (
    SELECT i.*, u.source_id,
      CASE u.source_id
        WHEN 'ncs_competency' THEN
          (flat - ARRAY['classification_1', 'classification_2', 'classification_3'])
          || jsonb_build_object('classification_names', jsonb_build_array(
               COALESCE(flat->>'classification_1', ''),
               COALESCE(flat->>'classification_2', ''),
               COALESCE(flat->>'classification_3', '')))
        WHEN 'qnet_schedule' THEN
          (flat - ARRAY['docRegStartDt', 'docRegEndDt', 'docExamStartDt', 'docExamEndDt',
                       'docPassDt', 'pracRegStartDt', 'pracRegEndDt', 'pracExamStartDt',
                       'pracExamEndDt', 'pracPassDt'])
          || jsonb_build_object('dates', jsonb_build_object(
               'docRegStartDt', flat->'docRegStartDt', 'docRegEndDt', flat->'docRegEndDt',
               'docExamStartDt', flat->'docExamStartDt', 'docExamEndDt', flat->'docExamEndDt',
               'docPassDt', flat->'docPassDt', 'pracRegStartDt', flat->'pracRegStartDt',
               'pracRegEndDt', flat->'pracRegEndDt', 'pracExamStartDt', flat->'pracExamStartDt',
               'pracExamEndDt', flat->'pracExamEndDt', 'pracPassDt', flat->'pracPassDt'))
        ELSE flat END AS normalized
    FROM input i JOIN ingestion.run u USING (run_id)
    WHERE u.state = 'LOADING'
), keyed AS (
    SELECT s.*,
      CASE source_id
        WHEN 'alio_organization' THEN normalized->>'code'
        WHEN 'ncs_competency' THEN normalized->>'code'
        WHEN 'job_alio' THEN (normalized->>'posting_id') || ':' || (normalized->>'representation')
        WHEN 'ncs_qualification' THEN (normalized->>'competency_code') || ':'
            || (normalized->>'qualification_code') || ':' || (normalized->>'standard_version')
        WHEN 'qnet_schedule' THEN (normalized->>'qualification_code') || ':'
            || (normalized->>'year') || ':' || (normalized->>'category_code') || ':'
            || (normalized->>'round')
        -- New, versioned migration identity: NOT the Python JSON serialization/hash.
        WHEN 'ncs_career_path' THEN 'hop-career-v1:' || encode(
            sha256(convert_to(normalized::text, 'UTF8')), 'hex') END AS source_record_id
    FROM shaped s
)
INSERT INTO ingestion.record
    (run_id, document_id, locator, source_record_id, source_payload,
     normalized, field_lineage, quality_flags)
SELECT run_id, document_id, locator, source_record_id, source_payload,
       normalized, field_lineage, quality_flags FROM keyed
ON CONFLICT (run_id, document_id, locator) DO UPDATE SET
    source_record_id = EXCLUDED.source_record_id, source_payload = EXCLUDED.source_payload,
    normalized = EXCLUDED.normalized, field_lineage = EXCLUDED.field_lineage,
    quality_flags = EXCLUDED.quality_flags;
