-- Optional inferred-only bounded worker admission; existing workflows stay unchanged.
BEGIN;
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_execution (
 batch_id text PRIMARY KEY REFERENCES enrichment.batch,
 execution_token uuid NOT NULL UNIQUE,
 workers integer NOT NULL CHECK(workers BETWEEN 1 AND 8),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(batch_id,execution_token)
);
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_request_owner (
 attempt_id text PRIMARY KEY REFERENCES enrichment.attempt,
 batch_id text NOT NULL,
 execution_token uuid NOT NULL,
 claimed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(batch_id,execution_token) REFERENCES enrichment.metadata_occupation_execution(batch_id,execution_token)
);
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_execution_stop (
 execution_token uuid PRIMARY KEY REFERENCES enrichment.metadata_occupation_execution(execution_token),
 reason text NOT NULL CHECK(reason ~ '^[A-Z][A-Z0-9_]{0,99}$'),
 stopped_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_execution_end (
 execution_token uuid PRIMARY KEY REFERENCES enrichment.metadata_occupation_execution(execution_token),
 state text NOT NULL CHECK(state IN ('COMPLETE','STOPPED')),
 ended_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_execution_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'METADATA_OCCUPATION_EXECUTION_IS_APPEND_ONLY';
END $$;
DO $install$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['metadata_occupation_execution','metadata_occupation_request_owner',
  'metadata_occupation_execution_stop','metadata_occupation_execution_end'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS metadata_execution_immutable ON enrichment.%I',t);
  EXECUTE format('CREATE TRIGGER metadata_execution_immutable BEFORE UPDATE OR DELETE ON enrichment.%I FOR EACH ROW EXECUTE FUNCTION enrichment.metadata_occupation_execution_immutable()',t);
  EXECUTE format('DROP TRIGGER IF EXISTS metadata_execution_no_truncate ON enrichment.%I',t);
  EXECUTE format('CREATE TRIGGER metadata_execution_no_truncate BEFORE TRUNCATE ON enrichment.%I FOR EACH STATEMENT EXECUTE FUNCTION enrichment.metadata_occupation_execution_immutable()',t);
  IF to_regprocedure('retention.freeze_writes()') IS NOT NULL THEN
   EXECUTE format('DROP TRIGGER IF EXISTS retention_freeze ON enrichment.%I',t);
   EXECUTE format('CREATE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON enrichment.%I FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',t);
  END IF;
 END LOOP;
END $install$;

CREATE OR REPLACE FUNCTION enrichment.start_metadata_occupation_execution(id text,worker_count integer)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE b enrichment.batch%ROWTYPE; token uuid; BEGIN
 PERFORM retention.gate();
 IF worker_count NOT BETWEEN 1 AND 8 OR worker_count IS NULL THEN RAISE EXCEPTION 'INVALID_METADATA_WORKERS'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-llm-spend',0));
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=id FOR UPDATE;
 IF b.settings->>'metadata_scope' IS DISTINCT FROM 'NCS_OCCUPATION_INFERENCE_V1' THEN RAISE EXCEPTION 'METADATA_BATCH_REQUIRED'; END IF;
 IF b.settings->>'execute_requests'='N' THEN RETURN jsonb_build_object('batch_id',id,'execute_requests','N','workers',worker_count); END IF;
 IF b.state<>'RUNNING' OR b.settings->>'execute_requests'<>'Y' THEN RAISE EXCEPTION 'METADATA_EXECUTION_NOT_RUNNING'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=b.job_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=b.ncs_run_id)
 THEN RAISE EXCEPTION 'METADATA_EXECUTION_PINS_CHANGED'; END IF;
 -- One dispatcher lifetime per batch. A crashed/uncertain batch never resumes paid attempts.
 IF EXISTS(SELECT 1 FROM enrichment.attempt WHERE batch_id=id AND state='RESERVED')
 THEN RAISE EXCEPTION 'METADATA_EXECUTION_ORPHAN_RESERVATION'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.metadata_occupation_execution WHERE batch_id=id)
  OR EXISTS(SELECT 1 FROM enrichment.attempt WHERE batch_id=id AND reserved_at IS NOT NULL)
 THEN RAISE EXCEPTION 'METADATA_EXECUTION_ALREADY_STARTED'; END IF;
 token:=gen_random_uuid();
 INSERT INTO enrichment.metadata_occupation_execution(batch_id,execution_token,workers) VALUES(id,token,worker_count);
 RETURN jsonb_build_object('batch_id',id,'execution_token',token,'workers',worker_count);
END $$;

-- Read-only pre-key gate; the admission function repeats every condition under the spend lock.
CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_request_context(aid text,token uuid)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT b.settings FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id)
 JOIN enrichment.metadata_occupation_execution e ON e.batch_id=b.batch_id AND e.execution_token=token
 WHERE a.attempt_id=aid AND a.stage='categorize' AND a.state='PLANNED'
 AND b.state='RUNNING' AND b.settings->>'execute_requests'='Y'
 AND b.settings->>'metadata_scope'='NCS_OCCUPATION_INFERENCE_V1'
 AND NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_execution_end WHERE execution_token=token)
 AND NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_execution_stop WHERE execution_token=token)
 AND EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=b.job_run_id)
 AND EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=b.ncs_run_id)
 AND NOT EXISTS(SELECT 1 FROM enrichment.attempt stopped WHERE stopped.batch_id=b.batch_id AND
  (stopped.state='BUDGET_BLOCKED' OR (stopped.reserved_at IS NOT NULL AND
   (stopped.state IN ('ERROR','REJECTED') OR (stopped.state IN ('VALIDATED','SKIPPED') AND stopped.cost_usd IS NULL)
    OR (stopped.state='RESERVED' AND NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_request_owner o
     WHERE o.attempt_id=stopped.attempt_id AND o.execution_token=token))))))
$$;

CREATE OR REPLACE FUNCTION enrichment.admit_metadata_occupation_request(aid text,token uuid)
RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE id text; worker_count integer; active integer; BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-llm-spend',0));
 IF enrichment.metadata_occupation_request_context(aid,token) IS NULL THEN RETURN false; END IF;
 SELECT batch_id,workers INTO STRICT id,worker_count FROM enrichment.metadata_occupation_execution WHERE execution_token=token;
 SELECT count(*) INTO active FROM enrichment.attempt a JOIN enrichment.metadata_occupation_request_owner o USING(attempt_id)
 WHERE o.execution_token=token AND a.state='RESERVED';
 IF active>=worker_count THEN RETURN false; END IF;
 -- The existing ledger function atomically enforces batch, request-count and global daily limits.
 PERFORM enrichment.reserve_request(aid);
 IF NOT EXISTS(SELECT 1 FROM enrichment.attempt WHERE attempt_id=aid AND state='RESERVED') THEN RETURN false; END IF;
 INSERT INTO enrichment.metadata_occupation_request_owner(attempt_id,batch_id,execution_token) VALUES(aid,id,token);
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION enrichment.stop_metadata_occupation_execution(token uuid,why text)
RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-llm-spend',0));
 IF NOT EXISTS(SELECT 1 FROM enrichment.metadata_occupation_execution WHERE execution_token=token)
 THEN RAISE EXCEPTION 'METADATA_EXECUTION_TOKEN_UNKNOWN'; END IF;
 INSERT INTO enrichment.metadata_occupation_execution_stop(execution_token,reason) VALUES(token,why) ON CONFLICT DO NOTHING;
END $$;

CREATE OR REPLACE FUNCTION enrichment.end_metadata_occupation_execution(token uuid)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE id text; final_state text; BEGIN
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-llm-spend',0));
 SELECT batch_id INTO STRICT id FROM enrichment.metadata_occupation_execution WHERE execution_token=token;
 IF EXISTS(SELECT 1 FROM enrichment.attempt WHERE batch_id=id AND state='RESERVED')
 THEN RAISE EXCEPTION 'METADATA_EXECUTION_RESERVATION_UNSETTLED'; END IF;
 final_state:=CASE WHEN EXISTS(SELECT 1 FROM enrichment.metadata_occupation_execution_stop WHERE execution_token=token)
  OR EXISTS(SELECT 1 FROM enrichment.attempt WHERE batch_id=id AND
   (state IN ('PLANNED','ERROR','BUDGET_BLOCKED') OR (reserved_at IS NOT NULL AND
    (state='REJECTED' OR (state='VALIDATED' AND cost_usd IS NULL))))) THEN 'STOPPED' ELSE 'COMPLETE' END;
 INSERT INTO enrichment.metadata_occupation_execution_end(execution_token,state) VALUES(token,final_state) ON CONFLICT DO NOTHING;
 SELECT state INTO STRICT final_state FROM enrichment.metadata_occupation_execution_end WHERE execution_token=token;
 RETURN jsonb_build_object('batch_id',id,'execution_token',token,'state',final_state,
  'requests',(SELECT count(*) FROM enrichment.metadata_occupation_request_owner WHERE execution_token=token),
  'never_sent',(SELECT count(*) FROM enrichment.attempt WHERE batch_id=id AND reserved_at IS NULL AND state IN ('PLANNED','BUDGET_BLOCKED')));
END $$;
COMMIT;
