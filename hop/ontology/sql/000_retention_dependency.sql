-- Generated from retention/sql/001_retention.sql. Requires installed manual retention.
BEGIN;
SELECT retention.gate();
DO $$ BEGIN IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF; END $$;
CREATE OR REPLACE FUNCTION retention.protection(id text,keep_count integer) RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE u ingestion.run; ontology_pinned boolean; BEGIN
 SELECT * INTO u FROM ingestion.run WHERE run_id=id;
 IF NOT FOUND THEN RETURN 'MISSING_RUN'; END IF;
 IF u.state<>'READY' OR u.mode='SMOKE' THEN RETURN 'NOT_ACCEPTED_FULL_SNAPSHOT'; END IF;
 IF id IN (SELECT run_id FROM ingestion.run WHERE source_id=u.source_id AND state='READY' AND mode<>'SMOKE'
   ORDER BY created_at DESC,run_id DESC LIMIT keep_count) THEN RETURN 'KEEP_LATEST'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.dependency WHERE input_run_id=id) THEN RETURN 'UPSTREAM_DEPENDENCY'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.dataset WHERE job_run_id=id OR ncs_run_id=id) THEN RETURN 'EVALUATION_DATASET'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.batch WHERE job_run_id=id OR ncs_run_id=id) THEN RETURN 'LLM_BATCH'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.ncs_catalog WHERE run_id=id) THEN RETURN 'LLM_CATALOG'; END IF;
 -- Optional ontology installation. Check before touching graph/raw files, not
 -- only when a later PostgreSQL FK would reject deletion.
 IF to_regclass('ontology.source_pin') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM ontology.source_pin WHERE run_id=$1)' INTO ontology_pinned USING id;
  IF ontology_pinned THEN RETURN 'ONTOLOGY_RELEASE'; END IF;
 END IF;
 IF to_regclass('attachment.batch') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM attachment.batch WHERE job_run_id=$1)' INTO ontology_pinned USING id;
  IF ontology_pinned THEN RETURN 'ATTACHMENT_BATCH'; END IF;
 END IF;
 IF to_regclass('ontology.observation_run') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM ontology.observation_run WHERE run_id=$1)' INTO ontology_pinned USING id;
  IF ontology_pinned THEN RETURN 'ONTOLOGY_OBSERVATION_HISTORY'; END IF;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=id) THEN RETURN 'GRAPH_NOT_CHECKPOINTED'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.request_attempt WHERE run_id=id AND reserved_at>clock_timestamp()-interval '24 hours')
   THEN RETURN 'REQUEST_QUOTA_WINDOW'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=id) THEN RETURN 'VALIDATION_ISSUES'; END IF;
 RETURN NULL;
END $$;
COMMIT;
