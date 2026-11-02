-- Explicitly authorized fresh inference for one reviewed JobKorea replacement.
-- Historical shared $40 and task/batch admission caps remain unchanged.
BEGIN;
SELECT retention.gate();
DO $$ BEGIN
 IF to_regclass('onet_matching.accounted_attempt') IS NULL
  OR to_regclass('onet_matching.route_incident_acknowledgement') IS NULL
 THEN RAISE EXCEPTION 'ONET_REPLACEMENT_REQUIRES_RECONCILIATION_AND_ROUTE_CONTRACTS'; END IF;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.replacement_reinference_allowed(
 task_row onet_matching.task,new_input onet_matching.input,old_input onet_matching.input)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce((task_row).task_id='jkr-20261103-onet'
  AND (task_row).settings->>'replacement_scope_sha256' ~ '^[0-9a-f]{64}$'
  AND (task_row).settings->>'max_cost_usd'='7'
  AND (new_input).source_id='jobkorea'
  AND (new_input).source_run_id='jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f'
  AND (old_input).source_run_id IS DISTINCT FROM (new_input).source_run_id,false)
$$;
CREATE OR REPLACE FUNCTION onet_matching.admit_request(aid text,token uuid) RETURNS boolean
LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; b onet_matching.batch; t onet_matching.task; workers integer;
 held numeric; own_held numeric; batch_held numeric; reserve numeric; paid bigint; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 IF onet_matching.request_context(aid,token) IS NULL THEN RETURN false; END IF;
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid FOR UPDATE;
 SELECT * INTO STRICT b FROM onet_matching.batch WHERE batch_id=a.batch_id;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 SELECT e.workers INTO STRICT workers FROM onet_matching.execution e WHERE execution_token=token;
 IF (SELECT count(*) FROM onet_matching.accounted_attempt x JOIN onet_matching.request_owner o USING(attempt_id)
  WHERE o.execution_token=token AND x.state='RESERVED')>=workers THEN RETURN false; END IF;
 -- Never reserve the entire cohort. Each worker reserves only its next POST.
 SELECT coalesce(sum(coalesce(x.effective_cost_usd,x.reserve_usd)),0) INTO held FROM onet_matching.accounted_attempt x
  JOIN onet_matching.task xt USING(task_id) WHERE xt.budget_key=t.budget_key AND x.reserved_at IS NOT NULL;
 SELECT coalesce(sum(coalesce(effective_cost_usd,reserve_usd)),0) INTO own_held FROM onet_matching.accounted_attempt WHERE task_id=t.task_id AND reserved_at IS NOT NULL;
 SELECT count(*) INTO paid FROM onet_matching.accounted_attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL;
 SELECT coalesce(sum(coalesce(effective_cost_usd,reserve_usd)),0) INTO batch_held FROM onet_matching.accounted_attempt WHERE batch_id=b.batch_id AND reserved_at IS NOT NULL;
 reserve:=(t.settings->>'request_reserve_usd')::numeric;
 IF held+reserve>(SELECT cap_usd FROM onet_matching.budget WHERE budget_key=t.budget_key)
  OR own_held+reserve>(t.settings->>'max_cost_usd')::numeric OR batch_held+reserve>b.max_cost_usd OR paid>=b.max_requests
 THEN UPDATE onet_matching.attempt SET state='BUDGET_BLOCKED',issues='["COMBINED_ACCOUNTING_CAP_OR_REQUEST_COUNT"]' WHERE attempt_id=aid;
  INSERT INTO onet_matching.execution_stop(execution_token,reason) VALUES(token,'BUDGET_OR_REQUEST_COUNT') ON CONFLICT DO NOTHING;
  RETURN false;
 END IF;
 -- Same frozen paid request cannot be retried under a fresh task identity.
 IF EXISTS(SELECT 1 FROM onet_matching.accounted_attempt old JOIN onet_matching.input oi USING(task_id,posting_identity)
  JOIN onet_matching.task ot USING(task_id) JOIN onet_matching.input current ON current.task_id=a.task_id AND current.posting_identity=a.posting_identity
  WHERE old.reserved_at IS NOT NULL AND ot.budget_key=t.budget_key AND oi.posting_identity=current.posting_identity
   AND oi.source_hash=current.source_hash AND oi.request_hash=current.request_hash AND ot.catalog_hash=t.catalog_hash
   AND NOT onet_matching.replacement_reinference_allowed(t,current,oi))
 THEN RAISE EXCEPTION 'ONET_MATCHING_ALREADY_PAID_NO_RETRY'; END IF;
 UPDATE onet_matching.attempt SET state='RESERVED',reserve_usd=reserve,reserved_at=clock_timestamp() WHERE attempt_id=aid;
 INSERT INTO onet_matching.request_owner(attempt_id,execution_token) VALUES(aid,token);
 RETURN true;
END $$;
COMMIT;
