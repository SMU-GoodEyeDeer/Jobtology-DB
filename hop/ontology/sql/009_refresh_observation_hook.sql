-- Generated from docs/hop-migration/operations.sql. The source checkpoint extension is optional.
BEGIN;
CREATE OR REPLACE FUNCTION ingestion.record_graph_export_v1(id text) RETURNS void LANGUAGE plpgsql SET jit=off AS $$
DECLARE r ingestion.run;
BEGIN
 SELECT * INTO r FROM ingestion.run WHERE run_id=id AND state='READY' AND mode<>'SMOKE';
 IF NOT FOUND THEN RAISE EXCEPTION 'GRAPH_EXPORT_REQUIRES_READY_SNAPSHOT'; END IF;
 IF to_regprocedure('ingestion.assert_source_graph_projection(text)') IS NULL
 THEN RAISE EXCEPTION 'BATCHFREE_SOURCE_GRAPH_CONTRACT_REQUIRED'; END IF;
 PERFORM ingestion.assert_source_graph_projection(id);
 IF r.source_id='job_alio' AND r.mode='FULL' AND to_regprocedure('ontology.capture_posting_census_v1(text)') IS NOT NULL THEN
  EXECUTE 'SELECT ontology.capture_posting_census_v1($1)' USING id;
 END IF;
 INSERT INTO ingestion.graph_export(run_id,loader_version) VALUES(id,'hop-graph-batchfree-v1')
 ON CONFLICT(run_id) DO UPDATE SET exported_at=clock_timestamp(),loader_version=EXCLUDED.loader_version;
END $$;
COMMIT;
