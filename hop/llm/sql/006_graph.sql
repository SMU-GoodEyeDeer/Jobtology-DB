BEGIN;
CREATE OR REPLACE VIEW enrichment.graph_item AS
SELECT r.item_id,r.batch_id,r.posting_id,r.review_id,r.decision,
 'job-alio:posting:'||r.posting_id AS posting_identity,
 coalesce(r.source_data->>'title',r.posting_id) AS name,r.source_hash,r.job_run_id,r.ncs_run_id,
 coalesce(r.extraction,'{}')::text AS extraction_json,coalesce(r.categorization,'{}')::text AS categorization_json,
 coalesce(r.extraction_model,r.settings->>'extract_model') AS extraction_model,
 coalesce(r.categorization_model,r.settings->>'categorize_model') AS categorization_model,
 r.settings->>'prompt_version' AS prompt_version,
 CASE WHEN r.decision='ACCEPT' THEN jsonb_array_length(r.categorization->'matches') ELSE 0 END::bigint AS match_count
FROM enrichment.result r WHERE r.mode='ENRICH' AND r.decision IS NOT NULL;
CREATE OR REPLACE VIEW enrichment.graph_match AS
SELECT r.item_id,r.batch_id,r.review_id,'ncs:unit:'||(m->>'competency_code') AS competency_identity,
 m->>'competency_code' AS competency_code,(m->>'duty_index')::bigint AS duty_index,m->>'reason' AS reason,
 r.extraction->'duties'->((m->>'duty_index')::integer)->>'text' AS duty,
 r.extraction->'duties'->((m->>'duty_index')::integer)->'evidence'->>'field' AS evidence_field,
 r.extraction->'duties'->((m->>'duty_index')::integer)->'evidence'->>'quote' AS evidence_quote
FROM enrichment.result r CROSS JOIN LATERAL jsonb_array_elements(r.categorization->'matches') m
WHERE r.mode='ENRICH' AND r.state='VALIDATED' AND r.decision='ACCEPT';

CREATE OR REPLACE FUNCTION enrichment.import_gold(document jsonb) RETURNS void LANGUAGE plpgsql AS $$
DECLARE c jsonb; BEGIN
 IF jsonb_typeof(document) IS DISTINCT FROM 'object' OR
  jsonb_typeof(document->'cases') IS DISTINCT FROM 'array' OR
  nullif(document->>'dataset_id','') IS NULL OR nullif(btrim(document->>'reviewer'),'') IS NULL
 THEN RAISE EXCEPTION 'INVALID_GOLD_DOCUMENT'; END IF;
 FOR c IN SELECT jsonb_array_elements(document->'cases') LOOP
  PERFORM enrichment.set_gold(document->>'dataset_id',c->>'posting_id',c->'labels',document->>'reviewer');
 END LOOP;
END $$;
COMMIT;
