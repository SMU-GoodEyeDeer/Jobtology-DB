-- Source-specific checks compose through the stable shared validator hook.
BEGIN;

CREATE OR REPLACE FUNCTION ingestion.jobkorea_cs_collision_issue()
RETURNS TABLE(run_id text,issue text,location text) LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF to_regclass('cs.posting_input') IS NULL THEN RETURN; END IF;
 RETURN QUERY EXECUTE $query$
  SELECT r.run_id,'JOBKOREA_CS_IDENTITY_COLLISION'::text,r.locator
  FROM ingestion.record r JOIN ingestion.run u USING(run_id)
  JOIN cs.posting_input i ON i.source_id='jobkorea' AND i.snapshot_run_id=r.run_id
   AND i.source_posting_id=r.source_record_id
  WHERE u.source_id='jobkorea'
 $query$;
END $$;

-- Keep this hook on ordinary installer replay; SQL006 replaces the stub.
DO $$ BEGIN
 IF to_regprocedure('ingestion.jobkorea_ndjson_validation_issue()') IS NULL THEN
  EXECUTE 'CREATE FUNCTION ingestion.jobkorea_ndjson_validation_issue()
   RETURNS TABLE(run_id text,issue text,location text) LANGUAGE sql STABLE AS
   $body$ SELECT NULL::text,NULL::text,NULL::text WHERE false $body$';
 END IF;
END $$;

CREATE OR REPLACE VIEW ingestion.jobkorea_validation_issue AS
SELECT i.run_id,i.code AS issue,i.locator||CASE WHEN i.field<>'' THEN ':'||i.field ELSE '' END AS location
FROM ingestion.jobkorea_issue i WHERE i.severity='ERROR'
UNION ALL
SELECT u.run_id,'JOBKOREA_IMPORT_PROVENANCE_MISSING','' FROM ingestion.run u
WHERE u.source_id='jobkorea' AND NOT EXISTS(SELECT 1 FROM ingestion.jobkorea_import i WHERE i.run_id=u.run_id)
UNION ALL
SELECT i.run_id,'JOBKOREA_IMPORT_METADATA_CONFLICT','' FROM ingestion.jobkorea_import i
JOIN ingestion.run u USING(run_id)
WHERE u.source_id<>'jobkorea' OR u.mode<>'REPLAY' OR u.parser_version<>i.parser_version OR u.policy_revision<>i.policy_revision
 OR i.policy_revision<>'2026-10-07.1'
 OR (i.file_format='JSON_ARRAY' AND (i.parser_version<>'hop-jobkorea-v1'
  OR i.raw_path<>'jobkorea/'||i.file_sha256||'/source.json'
  OR i.run_id<>'jobkorea-'||encode(sha256(convert_to('hop-jobkorea-v1:2026-10-07.1:'||i.file_sha256,'UTF8')),'hex')))
 OR (i.file_format='NDJSON' AND (i.parser_version<>'hop-jobkorea-ndjson-v1'
  OR i.raw_path<>'jobkorea/'||i.file_sha256||'/source.ndjson'
  OR i.run_id<>'jobkorea-ndjson-'||encode(sha256(convert_to('hop-jobkorea-ndjson-v1:2026-10-07.1:'||i.file_sha256,'UTF8')),'hex')))
 OR i.scope<>'FILE_ONLY' OR i.provider_complete
UNION ALL
SELECT i.run_id,'JOBKOREA_FILE_NOT_PROCESSED','' FROM ingestion.jobkorea_import i
WHERE NOT i.loaded OR i.processed_at IS NULL OR i.payload_sha256 IS DISTINCT FROM i.file_sha256 OR i.error_code IS NOT NULL
UNION ALL
SELECT i.run_id,'JOBKOREA_ROW_MANIFEST_CONFLICT','' FROM ingestion.jobkorea_import i
WHERE i.loaded AND i.row_manifest_sha256 IS DISTINCT FROM ingestion.jobkorea_row_manifest(i.run_id)
UNION ALL
SELECT i.run_id,'JOBKOREA_LOCAL_DOCUMENT_CONFLICT',i.document_id FROM ingestion.jobkorea_import i
LEFT JOIN ingestion.document d ON d.run_id=i.run_id AND d.document_id=i.document_id
WHERE d.document_id IS NULL OR d.transport<>'LOCAL_FILE' OR d.http_status IS NOT NULL OR d.provider_result IS NOT NULL
 OR d.raw_sha256<>i.file_sha256 OR d.byte_length<>i.byte_length OR d.raw_path<>i.raw_path OR d.encoding<>'UTF-8'
 OR d.retrieved_at<>i.received_at OR d.partition_id<>'local-file' OR d.page_no<>1 OR d.confirmation_no<>0 OR d.attempt_no<>1
 OR NOT d.selected OR d.verified_at IS NULL
 OR d.item_count IS NULL OR d.item_count=0 OR d.declared_total IS DISTINCT FROM d.item_count
 OR d.effective_page<>1 OR d.effective_page_size IS DISTINCT FROM d.item_count
 OR (SELECT count(*) FROM ingestion.document x WHERE x.run_id=i.run_id)<>1
UNION ALL
SELECT i.run_id,'JOBKOREA_LOCAL_PARTITION_CONFLICT','local-file' FROM ingestion.jobkorea_import i
LEFT JOIN ingestion.partition p ON p.run_id=i.run_id AND p.partition_id='local-file'
LEFT JOIN ingestion.document d ON d.run_id=i.run_id AND d.document_id=i.document_id
WHERE p.partition_id IS NULL OR p.kind<>'FILE' OR p.expected_total IS DISTINCT FROM d.item_count
 OR p.page_size IS DISTINCT FROM d.item_count
 OR p.request_context IS DISTINCT FROM '{"transport":"LOCAL_FILE","scope":"FILE_ONLY","provider_complete":false,"absence_is_closure":false}'::jsonb
 OR (SELECT count(*) FROM ingestion.partition x WHERE x.run_id=i.run_id)<>1
UNION ALL
SELECT r.run_id,'JOBKOREA_RECORD_NORMALIZATION_CONFLICT',r.locator
FROM ingestion.record r JOIN ingestion.run u USING(run_id)
JOIN ingestion.jobkorea_import i USING(run_id)
CROSS JOIN LATERAL ingestion.normalize_jobkorea_row(r.source_payload,r.locator) n
WHERE u.source_id='jobkorea' AND (r.normalized IS DISTINCT FROM n.normalized OR r.field_lineage IS DISTINCT FROM n.field_lineage
 OR r.quality_flags IS DISTINCT FROM n.quality_flags OR jsonb_array_length(n.errors)>0
 OR r.source_record_id IS DISTINCT FROM r.normalized->>'posting_id'
 OR (i.file_format='JSON_ARRAY' AND r.locator !~ '^/(0|[1-9][0-9]*)$')
 OR (i.file_format='NDJSON' AND r.locator !~ '^line:[1-9][0-9]*$')
 OR r.document_id<>'local-json')
UNION ALL
SELECT i.run_id,'JOBKOREA_LOCATOR_ACCOUNTING_CONFLICT','' FROM ingestion.jobkorea_import i
JOIN ingestion.document d ON d.run_id=i.run_id AND d.document_id=i.document_id
WHERE i.file_format='JSON_ARRAY' AND d.item_count IS NOT NULL AND (
 (SELECT count(DISTINCT locator) FROM (
  SELECT locator FROM ingestion.record r WHERE r.run_id=i.run_id
  UNION ALL SELECT locator FROM ingestion.rejected_row r WHERE r.run_id=i.run_id) x)<>d.item_count
 OR EXISTS(SELECT 1 FROM (
  SELECT locator FROM ingestion.record r WHERE r.run_id=i.run_id
  UNION ALL SELECT locator FROM ingestion.rejected_row r WHERE r.run_id=i.run_id) x
  WHERE x.locator !~ '^/(0|[1-9][0-9]*)$' OR length(x.locator)>12
   OR CASE WHEN x.locator ~ '^/(0|[1-9][0-9]*)$' AND length(x.locator)<=12
     THEN substring(x.locator FROM 2)::bigint>=d.item_count ELSE true END))
UNION ALL
SELECT u.run_id,'JOBKOREA_UNEXPECTED_HTTP_REQUEST','' FROM ingestion.run u
WHERE u.source_id='jobkorea' AND EXISTS(SELECT 1 FROM ingestion.request_attempt a WHERE a.run_id=u.run_id)
UNION ALL
SELECT u.run_id,'JOBKOREA_UNEXPECTED_DEPENDENCY','' FROM ingestion.run u
WHERE u.source_id='jobkorea' AND EXISTS(SELECT 1 FROM ingestion.dependency a WHERE a.run_id=u.run_id)
UNION ALL
SELECT * FROM ingestion.jobkorea_cs_collision_issue()
UNION ALL SELECT * FROM ingestion.jobkorea_ndjson_validation_issue();

CREATE OR REPLACE FUNCTION ingestion.local_file_validation_issue()
RETURNS TABLE(run_id text,issue text,location text) LANGUAGE sql STABLE AS $$
 SELECT * FROM ingestion.jobkorea_validation_issue
$$;

CREATE OR REPLACE FUNCTION ingestion.finalize_jobkorea_import(p_run_id text)
RETURNS TABLE(state text,record_count bigint,issue_count bigint)
LANGUAGE plpgsql AS $$
DECLARE prior_state text;
BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_run_id,0));
 SELECT u.state INTO STRICT prior_state FROM ingestion.run u WHERE u.run_id=p_run_id AND u.source_id='jobkorea' FOR UPDATE;
 SELECT count(*) INTO record_count FROM ingestion.record r WHERE r.run_id=p_run_id;
 SELECT count(*) INTO issue_count FROM (
  SELECT issue,location FROM ingestion.validation_issue v WHERE v.run_id=p_run_id
  UNION SELECT issue,location FROM ingestion.jobkorea_validation_issue v WHERE v.run_id=p_run_id) x;
 IF prior_state='READY' THEN
  IF issue_count>0 THEN RAISE EXCEPTION 'JOBKOREA_READY_VALIDATION_FAILED'; END IF;
  state:='READY'; RETURN NEXT; RETURN;
 END IF;
 IF prior_state IN('FAILED','REVIEW_REQUIRED') THEN state:=prior_state; RETURN NEXT; RETURN; END IF;
 state:=CASE WHEN issue_count=0 THEN 'READY' ELSE 'REVIEW_REQUIRED' END;
 UPDATE ingestion.run u SET state=finalize_jobkorea_import.state,completed_at=clock_timestamp() WHERE u.run_id=p_run_id;
 RETURN NEXT;
END $$;
COMMIT;
