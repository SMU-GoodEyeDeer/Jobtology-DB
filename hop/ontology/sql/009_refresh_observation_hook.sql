-- Generated from docs/hop-migration/operations.sql. The source checkpoint extension is optional.
BEGIN;
CREATE OR REPLACE FUNCTION ingestion.record_graph_export_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r ingestion.run;
BEGIN
 SELECT * INTO r FROM ingestion.run WHERE run_id=id AND state='READY' AND mode<>'SMOKE';
 IF NOT FOUND THEN RAISE EXCEPTION 'GRAPH_EXPORT_REQUIRES_READY_SNAPSHOT'; END IF;
 IF r.source_id='job_alio' AND r.mode='FULL' AND to_regprocedure('ontology.capture_posting_census_v1(text)') IS NOT NULL THEN
  EXECUTE 'SELECT ontology.capture_posting_census_v1($1)' USING id;
 END IF;
 INSERT INTO ingestion.graph_export(run_id,loader_version) VALUES(id,'hop-graph-v2')
 ON CONFLICT(run_id) DO UPDATE SET exported_at=clock_timestamp(),loader_version=EXCLUDED.loader_version;
END $$;
COMMIT;
