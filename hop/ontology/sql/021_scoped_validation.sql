-- Inline the reusable validation CTEs so a pinned run is filtered before its facts are built.
BEGIN;
DO $$
DECLARE definition text;
BEGIN
 definition:=pg_get_viewdef('ingestion.validation_issue'::regclass,true);
 -- The ontology unit fixture deliberately installs an empty validator before the native installer.
 IF current_database()='ontologytest' AND btrim(definition)='SELECT NULL::text AS run_id,
    NULL::text AS issue
  WHERE false;' THEN RETURN; END IF;
 IF position('selected AS (' IN definition)=0 AND position('selected AS NOT MATERIALIZED (' IN definition)=0 THEN
  RAISE EXCEPTION 'VALIDATION_VIEW_SELECTED_CTE_UNRECOGNIZED';
 END IF;
 IF position('facts AS (' IN definition)=0 AND position('facts AS NOT MATERIALIZED (' IN definition)=0 THEN
  RAISE EXCEPTION 'VALIDATION_VIEW_FACTS_CTE_UNRECOGNIZED';
 END IF;
 definition:=replace(replace(definition,'selected AS (','selected AS NOT MATERIALIZED ('),
  'facts AS (','facts AS NOT MATERIALIZED (');
 EXECUTE 'CREATE OR REPLACE VIEW ingestion.validation_issue AS '||definition;
END $$;
COMMIT;
