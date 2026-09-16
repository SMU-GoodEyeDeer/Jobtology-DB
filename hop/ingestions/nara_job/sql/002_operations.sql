BEGIN;
INSERT INTO ingestion.refresh_policy(source_id,interval_seconds,retry_seconds,requests_per_24h,enabled)
VALUES('nara_job',86400,3600,10000,true)
ON CONFLICT(source_id) DO UPDATE SET requests_per_24h=10000;

CREATE OR REPLACE FUNCTION ingestion.reserve_request(target_run text,target_partition text,
 target_page integer,target_confirmation integer,max_requests integer)
RETURNS TABLE(request_allowed boolean,reservation_reason text)
LANGUAGE plpgsql AS $$
DECLARE src text; budget integer;
BEGIN
 SELECT source_id INTO src FROM ingestion.run WHERE run_id=target_run AND state='LOADING';
 IF src IS NULL THEN RETURN QUERY SELECT false,'RUN_NOT_LOADING'::text;RETURN; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('hop-request:'||src,0));
 SELECT requests_per_24h INTO budget FROM ingestion.refresh_policy WHERE source_id=src;
 IF max_requests NOT BETWEEN 1 AND 10000 OR budget IS NULL THEN
  RETURN QUERY SELECT false,'INVALID_REQUEST_BUDGET'::text;RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ingestion.request_attempt WHERE run_id=target_run AND partition_id=target_partition
  AND page_no=target_page AND confirmation_no=target_confirmation) THEN
  RETURN QUERY SELECT false,'REQUEST_ALREADY_RESERVED'::text;RETURN;
 END IF;
 IF (SELECT count(*) FROM ingestion.request_attempt WHERE source_id=src AND reserved_at>clock_timestamp()-interval '24 hours')>=budget THEN
  RETURN QUERY SELECT false,'PROVIDER_QUOTA_RESERVED'::text;RETURN;
 END IF;
 IF (SELECT count(*) FROM ingestion.request_attempt WHERE run_id=target_run)>=max_requests THEN
  RETURN QUERY SELECT false,'RUN_REQUEST_BUDGET_EXCEEDED'::text;RETURN;
 END IF;
 INSERT INTO ingestion.request_attempt(run_id,source_id,partition_id,page_no,confirmation_no)
 VALUES(target_run,src,target_partition,target_page,target_confirmation);
 RETURN QUERY SELECT true,NULL::text;
END $$;
COMMIT;
