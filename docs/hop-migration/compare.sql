-- Table Input query. Bind RUN_ID twice, in order. Both schemas must be reachable
-- through this connection. For separate databases, export the old SELECT result
-- and compare it with Sort Rows + Merge Rows (diff) in Hop instead.
-- The run must name ONE explicit READY reference_processing_run_id.
-- Returns zero rows only when normalized objects AND their multiplicities agree.
WITH target AS (
    SELECT * FROM ingestion.run WHERE run_id = ?
), reference AS (
    SELECT p.*, f.source_id FROM control.processing_run p
    JOIN control.connector_run f USING (connector_run_id)
    JOIN target h ON h.reference_processing_run_id = p.processing_run_id
    WHERE p.state = 'READY' AND f.source_id = h.source_id
), old_records AS (
    SELECT DISTINCT r.revision_id, r.record->'normalized' AS normalized
    FROM control.processing_input i
    JOIN staging.document_record d USING (document_id)
    JOIN staging.record_revision r USING (revision_id)
    JOIN reference p USING (processing_run_id)
), new_records AS (
    SELECT r.normalized FROM ingestion.ready_record r WHERE r.run_id = ?
), missing AS (
    SELECT normalized FROM old_records EXCEPT ALL SELECT normalized FROM new_records
), extra AS (
    SELECT normalized FROM new_records EXCEPT ALL SELECT normalized FROM old_records
)
SELECT 'missing_from_hop' AS difference, normalized FROM missing
UNION ALL
SELECT 'extra_or_changed_in_hop', normalized FROM extra
UNION ALL
SELECT 'reference_missing_wrong_source_or_not_ready', NULL::jsonb
WHERE NOT EXISTS (SELECT 1 FROM reference)
UNION ALL
SELECT 'hop_run_missing_or_not_ready', NULL::jsonb
WHERE NOT EXISTS (SELECT 1 FROM target WHERE state = 'READY' AND mode <> 'SMOKE');
