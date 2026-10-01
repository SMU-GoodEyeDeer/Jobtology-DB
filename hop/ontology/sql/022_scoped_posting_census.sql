-- Snapshot validation guarantees one list and one detail per posting before capture.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.posting_census_v1(id text)
RETURNS TABLE(run_id text,posting_id text,entity_id text,normalized jsonb,source_hash text,
 first_observed_at timestamptz,last_observed_at timestamptz,list_record_id bigint,detail_record_id bigint)
LANGUAGE sql STABLE AS $$
 WITH postings AS MATERIALIZED (
  SELECT * FROM ingestion.posting_representation WHERE run_id=id
 ), pairs AS (
  SELECT p.run_id,p.posting_id,
   (jsonb_agg(p.normalized) FILTER (WHERE p.representation='list'))->0 AS list_data,
   (jsonb_agg(p.normalized) FILTER (WHERE p.representation='detail'))->0 AS detail_data,
   min(d.retrieved_at) AS first_observed_at,max(d.retrieved_at) AS last_observed_at,
   max(r.record_id) FILTER (WHERE p.representation='list') AS list_record_id,
   max(r.record_id) FILTER (WHERE p.representation='detail') AS detail_record_id
  FROM postings p JOIN ingestion.record r USING(run_id,document_id,locator)
   JOIN ingestion.document d USING(run_id,document_id)
  GROUP BY p.run_id,p.posting_id
 ), candidates AS (
  SELECT p.*,(p.list_data||jsonb_strip_nulls(p.detail_data))-'representation' AS paired
  FROM pairs p WHERE p.list_data IS NOT NULL AND p.detail_data IS NOT NULL
 )
 SELECT p.run_id,p.posting_id,ontology.iri('jobPosting','job_alio:'||p.posting_id),p.paired,
  ontology.hash(p.paired),p.first_observed_at,p.last_observed_at,p.list_record_id,p.detail_record_id
 FROM candidates p
$$;
COMMIT;
