-- Run only after replacement_policy_assertions.sql in the exclusive disposable DB.
-- Compatible earlier projectors/readers must fail closed after policy installation.
-- Each original definition is restored even if an assertion fails.
DO $replay_regressions$
DECLARE target record; original_definition text;
 jobs text:='jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f';
BEGIN
 PERFORM pg_temp.assert(replacement_matching.ready(),'replay fixture starts ready');
 FOR target IN SELECT * FROM (VALUES
 ('NCS graph projector','enrichment.metadata_occupation_graph_rows(text,text,boolean)',
 $ncs_replay$CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_graph_rows(
 jobs text,ncs text,include_unreviewed boolean DEFAULT false)
 RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
 LANGUAGE sql STABLE AS $old_ncs$
  SELECT * FROM enrichment.metadata_occupation_graph_rows_legacy(jobs,ncs,include_unreviewed)
  UNION ALL SELECT * FROM enrichment.metadata_occupation_graph_rows_v3(jobs,ncs,include_unreviewed)
 $old_ncs$;$ncs_replay$),
 ('O*NET graph projector','onet_matching.graph_rows(text)',
 $onet_replay$CREATE OR REPLACE FUNCTION onet_matching.graph_rows(id text)
 RETURNS TABLE(edge_id text,posting_identity text,occupation_identity text,properties jsonb,payload_json text,content_hash text)
 LANGUAGE sql STABLE SET jit=off AS $old_onet$
  SELECT a.attempt_id,a.posting_identity,'occ'::text,'{}'::jsonb,'{}'::text,'unfiltered'::text
  FROM onet_matching.attempt a WHERE a.task_id=id AND a.state='VALIDATED'
   AND a.parsed_output->>'outcome'='matched'
 $old_onet$;$onet_replay$),
 ('modern catalogue adapter','catalog._inferred_occupation_rows(text[],text[])',
 $catalog_replay$CREATE OR REPLACE FUNCTION catalog._inferred_occupation_rows(
 occupation_codes text[],posting_choices text[])
 RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,
 occupation_scheme text,occupation_code text,occupation_name text,association_id text,
 review_status text,stage text,confidence_state text,source_hash text,
 normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,catalog_freshness text)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $old_catalog$
  -- Earlier SQL037 adapters trust the source/publication gate, without SQL038's
  -- per-attempt filter. Replay protection must live in that shared gate too.
  SELECT 'jobkorea:'||e.posting_id,e.posting_identity,'jobkorea'::text,g.job_run_id,
   'NCS'::text,'20010701'::text,'AI platform'::text,e.candidate_id,
   'UNREVIEWED'::text,'STAGING'::text,'UNASSESSED'::text,'source'::text,
   NULL::text,NULL::text,g.ncs_run_id,'cat'::text,'CURRENT'::text
  FROM enrichment.metadata_occupation_graph_guard g JOIN enrichment.fixture_edges e
   ON e.payload->>'job_run_id'=g.job_run_id
  WHERE g.state='READY' AND ingestion.jobkorea_ncs_publication_allowed(g.writer_token,g.job_run_id)
   AND (occupation_codes IS NULL OR '20010701'=ANY(occupation_codes))
   AND (posting_choices IS NULL OR 'jobkorea:'||e.posting_id=ANY(posting_choices))
  UNION ALL
  SELECT 'jobkorea:'||(i.source_facts->>'posting_id'),e.posting_identity,i.source_id,i.source_run_id,
   'ONET'::text,e.properties->>'occupation_code','Software QA'::text,e.edge_id,
   'UNREVIEWED'::text,'STAGING'::text,'UNASSESSED'::text,'source'::text,
   NULL::text,e.properties->>'source_facts_sha256','rel'::text,'cat'::text,'CURRENT'::text
  FROM onet_matching.graph_edge e JOIN onet_matching.graph_guard g USING(publication_id)
  JOIN onet_matching.input i ON i.task_id=g.task_id AND i.posting_identity=e.posting_identity
  WHERE g.state='VERIFIED'
   AND ingestion.jobkorea_onet_publication_allowed(g.publication_id,g.task_id,i.source_id,i.source_run_id)
   AND (occupation_codes IS NULL OR e.properties->>'occupation_code'=ANY(occupation_codes))
   AND (posting_choices IS NULL OR 'jobkorea:'||(i.source_facts->>'posting_id')=ANY(posting_choices))
 $old_catalog$;$catalog_replay$)
 ) replay(label,signature,definition) LOOP
  original_definition:=pg_get_functiondef(to_regprocedure(target.signature));
  BEGIN
   EXECUTE target.definition;
   PERFORM pg_temp.assert(NOT replacement_matching.ready(),target.label||' drift disables readiness');
   PERFORM pg_temp.assert(NOT replacement_matching.allowed('NCS','n-good',jobs),
    target.label||' drift blocks previously allowed scoped NCS');
   PERFORM pg_temp.assert(NOT replacement_matching.allowed('ONET','o-good','jkr-20261103-onet'),
    target.label||' drift blocks previously allowed scoped O*NET');
   PERFORM pg_temp.assert((SELECT count(*)=0 FROM catalog._inferred_occupation_rows(ARRAY['20010701'],NULL)),
    target.label||' drift hides existing scoped NCS catalogue associations');
   PERFORM pg_temp.assert((SELECT count(*)=0 FROM catalog._inferred_occupation_rows(ARRAY['15-1253.00'],NULL)),
    target.label||' drift hides existing scoped O*NET catalogue associations');
   BEGIN
    INSERT INTO enrichment.metadata_occupation_graph_guard
    VALUES('replay-ncs-'||target.label,jobs,'ncs',true,'PREPARED',now());
    RAISE EXCEPTION 'REPLAY_ALLOWED_NCS_PUBLICATION';
   EXCEPTION WHEN OTHERS THEN
    IF SQLERRM<>'REPLACEMENT_POLICY_NOT_READY' THEN RAISE; END IF;
   END;
   BEGIN
    INSERT INTO onet_matching.graph_guard
    VALUES('replay-onet-'||target.label,'jkr-20261103-onet','PREPARED','db',now());
    RAISE EXCEPTION 'REPLAY_ALLOWED_ONET_PUBLICATION';
   EXCEPTION WHEN OTHERS THEN
    IF SQLERRM<>'REPLACEMENT_POLICY_NOT_READY' THEN RAISE; END IF;
   END;
  EXCEPTION WHEN OTHERS THEN
   EXECUTE original_definition;
   RAISE;
  END;
  EXECUTE original_definition;
  PERFORM pg_temp.assert(replacement_matching.ready(),target.label||' original definition restores readiness');
  PERFORM pg_temp.assert(replacement_matching.allowed('NCS','n-good',jobs),
   target.label||' restore recovers original NCS assessment');
  PERFORM pg_temp.assert(replacement_matching.allowed('ONET','o-good','jkr-20261103-onet'),
   target.label||' restore recovers original O*NET assessment');
  PERFORM pg_temp.assert((SELECT count(*)=1 FROM catalog._inferred_occupation_rows(ARRAY['20010701'],NULL)),
   target.label||' restore recovers only the allowed NCS association');
  PERFORM pg_temp.assert((SELECT count(*)=1 FROM catalog._inferred_occupation_rows(ARRAY['15-1253.00'],NULL)),
   target.label||' restore recovers only the allowed O*NET association');
 END LOOP;
END $replay_regressions$;
SELECT 'REPLACEMENT_POLICY_REPLAY_PASSED';
