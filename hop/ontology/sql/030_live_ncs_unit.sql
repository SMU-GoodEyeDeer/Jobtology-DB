BEGIN;

CREATE OR REPLACE FUNCTION catalog.live_ncs_unit_v1(base_code text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ncs_run ingestion.run%ROWTYPE; unit_item jsonb;
BEGIN
 IF base_code IS NULL OR base_code !~ '^[0-9]{10}$'
 THEN RAISE EXCEPTION 'INVALID_LIVE_FILTER'; END IF;
 SELECT * INTO ncs_run FROM ingestion.latest_ready_run WHERE source_id='ncs_competency';
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 SELECT jsonb_build_object('base_code',base_code,'code',c.code,'name',c.name,'level',c.level,
  'definition',CASE WHEN c.definition ~ '^[[:space:]]*$' THEN NULL ELSE c.definition END)
 INTO unit_item FROM ingestion.competency c
 WHERE c.run_id=ncs_run.run_id AND left(c.code,10)=base_code AND c.name NOT LIKE '%(구버전)%'
 ORDER BY c.code COLLATE "C" DESC LIMIT 1;
 RETURN jsonb_build_object('contract_version','hop-live-source-v1',
  'sources',jsonb_build_array(jsonb_build_object('source_id','ncs_competency',
   'run_id',ncs_run.run_id,'data_as_of',ncs_run.completed_at)),
  'item',unit_item);
END $$;

REVOKE ALL ON FUNCTION catalog.live_ncs_unit_v1(text) FROM PUBLIC;
COMMIT;
