-- Install after schema.sql. These are snapshot/membership checks, in addition to
-- the field/type/date validators described in the guide. No state changes here.
-- This script CREATES the validation view; use a SQL workflow action or SQL editor.
CREATE OR REPLACE VIEW ingestion.validation_issue AS
WITH selected AS (
    SELECT d.* FROM ingestion.document d WHERE d.selected
), facts AS (
    SELECT r.run_id,r.document_id,r.locator,r.source_record_id,r.normalized,d.partition_id
    FROM ingestion.record r JOIN selected d USING (run_id, document_id)
), partition_counts AS (
    SELECT p.*, count(d.document_id) AS documents,
           min(d.page_no) AS first_page, max(d.page_no) AS last_page
    FROM ingestion.partition p
    LEFT JOIN selected d USING (run_id, partition_id)
    GROUP BY p.run_id, p.partition_id
), pairs AS (
    SELECT f.run_id, f.normalized->>'posting_id' AS posting_id,
           count(*) FILTER (WHERE f.normalized->>'representation' = 'list') AS lists,
           count(*) FILTER (WHERE f.normalized->>'representation' = 'detail') AS details
    FROM facts f JOIN ingestion.run u USING (run_id)
    WHERE u.source_id = 'job_alio'
    GROUP BY f.run_id, f.normalized->>'posting_id'
), nara_pairs AS (
    SELECT f.run_id,f.normalized->>'posting_id' AS posting_id,
      count(*) FILTER(WHERE f.normalized->>'representation'='list') AS lists,
      count(*) FILTER(WHERE f.normalized->>'representation'='list' AND coalesce((f.normalized->>'ongoing')::boolean,false)) AS active_lists,
      count(*) FILTER(WHERE f.normalized->>'representation'='detail') AS details,
      count(*) FILTER(WHERE f.normalized->>'representation'='positions') AS positions,
      count(*) FILTER(WHERE f.normalized->>'representation'='files') AS files
    FROM facts f JOIN ingestion.run u USING(run_id)
    WHERE u.source_id='nara_job'
    GROUP BY f.run_id,f.normalized->>'posting_id'
)
SELECT u.run_id, 'SMOKE_NOT_FULL'::text AS issue, ''::text AS location
FROM ingestion.run u WHERE u.mode = 'SMOKE'
UNION ALL
SELECT u.run_id, 'NO_PARTITIONS', '' FROM ingestion.run u
WHERE NOT EXISTS (SELECT 1 FROM ingestion.partition p WHERE p.run_id = u.run_id)
UNION ALL
SELECT d.run_id, 'DEPENDENCY_NOT_READY_OR_WRONG_SOURCE', d.input_source_id
FROM ingestion.dependency d JOIN ingestion.run u ON u.run_id = d.input_run_id
WHERE u.state <> 'READY' OR u.mode = 'SMOKE' OR u.source_id <> d.input_source_id
UNION ALL
SELECT u.run_id, 'MISSING_DEPENDENCY', u.source_id
FROM ingestion.run u
WHERE u.source_id IN ('ncs_qualification', 'qnet_schedule', 'job_alio')
  AND NOT EXISTS (
      SELECT 1 FROM ingestion.dependency d WHERE d.run_id = u.run_id
      AND d.input_source_id = CASE u.source_id
          WHEN 'ncs_qualification' THEN 'ncs_competency'
          WHEN 'qnet_schedule' THEN 'ncs_qualification'
          WHEN 'job_alio' THEN 'alio_organization' END)
UNION ALL
SELECT run_id, 'PARTITION_INCOMPLETE', partition_id FROM partition_counts
WHERE expected_total IS NULL
   OR (kind = 'PAGED' AND (documents <> CASE WHEN expected_total = 0 THEN 2
                    ELSE ceil(expected_total::numeric / page_size)::integer END
       OR first_page <> 1
       OR last_page <> greatest(1, ceil(expected_total::numeric / page_size)::integer)))
   OR (kind <> 'PAGED' AND (documents <> 1 OR first_page <> 1 OR last_page <> 1))
UNION ALL
SELECT d.run_id, 'DOCUMENT_METADATA_OR_FILE_NOT_VERIFIED', d.document_id
FROM selected d
JOIN ingestion.partition p USING (run_id, partition_id)
JOIN ingestion.run u USING (run_id)
WHERE d.http_status <> 200 OR d.byte_length = 0 OR d.verified_at IS NULL
   OR d.item_count IS NULL OR d.effective_page IS DISTINCT FROM d.page_no
   OR (p.kind = 'PAGED' AND (
          d.declared_total IS DISTINCT FROM p.expected_total
       OR d.effective_page_size IS DISTINCT FROM p.page_size
       OR d.item_count IS DISTINCT FROM
            greatest(0, least(p.page_size, p.expected_total - (d.page_no - 1) * p.page_size))
       OR (p.expected_total > 0 AND d.confirmation_no <> 0)
       OR (p.expected_total = 0 AND d.page_no <> 1)))
   OR (p.kind = 'DETAIL' AND (d.item_count <> 1 OR d.confirmation_no <> 0))
   OR (p.kind = 'FILE' AND (d.item_count IS DISTINCT FROM p.expected_total
                          OR d.item_count = 0 OR d.confirmation_no <> 0))
   OR (u.source_id IN ('alio_organization', 'job_alio')
       AND d.provider_result IS DISTINCT FROM '200')
   OR (u.source_id IN ('ncs_qualification', 'qnet_schedule')
       AND (d.provider_result IS NULL OR d.provider_result NOT IN ('00', '0', 'SUCCESS')))
UNION ALL
SELECT d.run_id, 'ROW_COUNT_MISMATCH', d.document_id FROM selected d
WHERE d.item_count IS DISTINCT FROM (
    (SELECT count(*) FROM ingestion.record r
     WHERE r.run_id = d.run_id AND r.document_id = d.document_id)
  + (SELECT count(*) FROM ingestion.rejected_row e
     WHERE e.run_id = d.run_id AND e.document_id = d.document_id))
UNION ALL
SELECT e.run_id, 'REJECTED_ROW', e.document_id || ':' || e.locator
FROM ingestion.rejected_row e JOIN selected d USING (run_id, document_id)
UNION ALL
SELECT run_id, 'DUPLICATE_SOURCE_ID', source_record_id FROM facts
GROUP BY run_id, source_record_id HAVING count(*) <> 1
UNION ALL
SELECT f.run_id, 'WRONG_RECORD_KIND', f.document_id || ':' || f.locator
FROM facts f JOIN ingestion.run u USING (run_id)
WHERE f.normalized->>'kind' IS DISTINCT FROM CASE u.source_id
    WHEN 'alio_organization' THEN 'Organization' WHEN 'job_alio' THEN 'JobPosting'
    WHEN 'nara_job' THEN 'JobPosting'
    WHEN 'ncs_career_path' THEN 'CareerPath' WHEN 'ncs_competency' THEN 'Competency'
    WHEN 'ncs_qualification' THEN 'QualificationMapping' WHEN 'qnet_schedule' THEN 'ExamSession' END
UNION ALL
SELECT f.run_id, 'PARTITION_IDENTITY_MISMATCH', f.document_id || ':' || f.locator
FROM facts f JOIN ingestion.run u USING (run_id)
WHERE (u.source_id = 'ncs_qualification'
       AND f.partition_id IS DISTINCT FROM 'ncs-' || (f.normalized->>'competency_code'))
   OR (u.source_id = 'qnet_schedule'
       AND f.partition_id IS DISTINCT FROM 'year-' || (f.normalized->>'year')
                                           || '-item-' || (f.normalized->>'qualification_code'))
   OR (u.source_id = 'job_alio' AND (
       (f.normalized->>'representation' = 'list' AND f.partition_id <> 'index')
       OR (f.normalized->>'representation' = 'detail'
           AND f.partition_id IS DISTINCT FROM 'detail-' || (f.normalized->>'posting_id'))))
   OR (u.source_id = 'nara_job' AND (
       (f.normalized->>'representation' = 'list' AND f.partition_id <> 'index')
       OR (f.normalized->>'representation' IN ('detail','positions','files')
           AND f.partition_id IS DISTINCT FROM (f.normalized->>'representation') || '-' || (f.normalized->>'posting_id'))))
UNION ALL
SELECT run_id, 'POSTING_PAIR_MISSING_OR_DUPLICATED', posting_id FROM pairs
WHERE lists <> 1 OR details <> 1
UNION ALL
SELECT run_id,'NARA_ACTIVE_RESOURCE_MISSING_OR_DUPLICATED',posting_id FROM nara_pairs
WHERE lists<>1 OR (active_lists=1 AND (details<>1 OR positions<>1 OR files<>1))
   OR (active_lists=0 AND (details<>0 OR positions<>0 OR files<>0))
UNION ALL
SELECT l.run_id,'NARA_POSTING_CONFLICT',l.normalized->>'posting_id'
FROM facts l JOIN ingestion.run u ON u.run_id=l.run_id AND u.source_id='nara_job'
JOIN facts d ON d.run_id=l.run_id AND d.normalized->>'posting_id'=l.normalized->>'posting_id'
 AND d.normalized->>'representation'='detail'
WHERE l.normalized->>'representation'='list'
 AND nullif(d.normalized->>'title','') IS NOT NULL
 AND l.normalized->>'title' IS DISTINCT FROM d.normalized->>'title'
UNION ALL
SELECT l.run_id, 'POSTING_PAIR_CONFLICT', l.normalized->>'posting_id'
FROM facts l JOIN ingestion.run u ON u.run_id=l.run_id AND u.source_id='job_alio'
JOIN facts d ON d.run_id = l.run_id
 AND d.normalized->>'posting_id' = l.normalized->>'posting_id'
 AND d.normalized->>'representation' = 'detail'
WHERE l.normalized->>'representation' = 'list'
  AND (l.normalized->'title' IS DISTINCT FROM d.normalized->'title'
    OR l.normalized->'organization_code' IS DISTINCT FROM d.normalized->'organization_code'
    OR l.normalized->'date_posted' IS DISTINCT FROM d.normalized->'date_posted'
    OR l.normalized->'closing_date' IS DISTINCT FROM d.normalized->'closing_date'
    OR (d.normalized->>'ongoing' IS NOT NULL
        AND l.normalized->'ongoing' IS DISTINCT FROM d.normalized->'ongoing'));
