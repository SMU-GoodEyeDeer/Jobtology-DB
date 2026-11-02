-- Independent assertions for the actual SQL038 adapter and additive SQL039.
-- The disposable harness seeds native-shaped publications before this fixture.
-- Compare pairs rather than irrelevant unpaired anchors: SQL036 only emits
-- source/posting-qualified NCS x O*NET pairs matching the requested endpoint.
BEGIN;
CREATE FUNCTION pg_temp.crosswalk_legacy_pairs(node_id text)
RETURNS SETOF jsonb LANGUAGE sql STABLE AS $$
 WITH scope AS (
  SELECT CASE WHEN node_id LIKE 'ncs:occupation:%'
    THEN substr(node_id,length('ncs:occupation:')+1)
   WHEN node_id LIKE 'urn:jobtology:onet:occupation:%'
    THEN substr(node_id,length('urn:jobtology:onet:occupation:')+1) END AS code
 ), anchor AS MATERIALIZED (
  SELECT a.* FROM scope CROSS JOIN LATERAL
   catalog._inferred_occupation_rows(ARRAY[scope.code],NULL) a
  WHERE scope.code IS NOT NULL
 ), counterparts AS MATERIALIZED (
  SELECT a.* FROM catalog._inferred_occupation_rows(NULL,
   coalesce((SELECT array_agg(DISTINCT posting_key) FROM anchor),ARRAY[]::text[])) a
 ), inferred AS MATERIALIZED (
  SELECT * FROM anchor UNION SELECT * FROM counterparts
 )
 SELECT jsonb_build_object('ncs',to_jsonb(n),'onet',to_jsonb(o))
 FROM inferred n JOIN inferred o USING(posting_key,source_id)
 WHERE n.occupation_scheme='NCS' AND o.occupation_scheme='ONET'
  AND (node_id='ncs:occupation:'||n.occupation_code
   OR node_id='urn:jobtology:onet:occupation:'||o.occupation_code)
$$;

CREATE FUNCTION pg_temp.crosswalk_workset_pairs(node_id text)
RETURNS SETOF jsonb LANGUAGE sql STABLE AS $$
 WITH inferred AS MATERIALIZED (
  SELECT * FROM catalog._crosswalk_pair_rows(node_id)
 )
 SELECT jsonb_build_object('ncs',to_jsonb(n),'onet',to_jsonb(o))
 FROM inferred n JOIN inferred o USING(posting_key,source_id)
 WHERE n.occupation_scheme='NCS' AND o.occupation_scheme='ONET'
  AND (node_id='ncs:occupation:'||n.occupation_code
   OR node_id='urn:jobtology:onet:occupation:'||o.occupation_code)
$$;

CREATE FUNCTION pg_temp.assert_crosswalk_workset(node_id text,label text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_temp.assert(NOT EXISTS(
  (SELECT * FROM pg_temp.crosswalk_legacy_pairs(node_id)
   EXCEPT ALL SELECT * FROM pg_temp.crosswalk_workset_pairs(node_id))
  UNION ALL
  (SELECT * FROM pg_temp.crosswalk_workset_pairs(node_id)
   EXCEPT ALL SELECT * FROM pg_temp.crosswalk_legacy_pairs(node_id))
 ),label||': complete paired adapter rows are equivalent');
END
$$;

SELECT pg_temp.assert_crosswalk_workset(NULL,'NULL endpoint');
SELECT pg_temp.assert_crosswalk_workset('','empty endpoint');
SELECT pg_temp.assert_crosswalk_workset('unsupported:occupation:15-1253.00',
 'unsupported endpoint');
SELECT pg_temp.assert((SELECT count(*)=0 FROM catalog._crosswalk_pair_rows(NULL)),
 'NULL endpoint returns an empty workset');
SELECT pg_temp.assert((SELECT count(*)=0 FROM catalog._crosswalk_pair_rows('')),
 'empty endpoint returns an empty workset');

SELECT pg_temp.assert_crosswalk_workset('ncs:occupation:20010701','baseline NCS endpoint');
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'baseline O*NET endpoint');
SELECT pg_temp.assert((SELECT count(*)>0 FROM pg_temp.crosswalk_legacy_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'baseline has a nonvacuous shared pair');

CREATE FUNCTION pg_temp.assert_scoped_crosswalk_hidden(label text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_temp.assert(NOT replacement_matching.ready(),label||': readiness fails closed');
 PERFORM pg_temp.assert(NOT EXISTS(
  SELECT 1 FROM pg_temp.crosswalk_workset_pairs(
   'urn:jobtology:onet:occupation:15-1253.00') p(value)
  WHERE p.value#>>'{ncs,source_run_id}'=
   'jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f'
   OR p.value#>>'{onet,source_run_id}'=
   'jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f'
 ),label||': existing scoped crosswalk pairs disappear');
 PERFORM pg_temp.assert_crosswalk_workset('ncs:occupation:20010701',label||' NCS');
 PERFORM pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
  label||' O*NET');
END
$$;

-- Function configuration is part of the immutable qualified signature. These
-- compatible definitions must still hide scoped data until restored.
SAVEPOINT adapter_signature_drift;
ALTER FUNCTION catalog._inferred_occupation_rows(text[],text[]) SET statement_timeout='41s';
SELECT pg_temp.assert_scoped_crosswalk_hidden('modern adapter signature drift');
ROLLBACK TO adapter_signature_drift;
SELECT pg_temp.assert(replacement_matching.ready(),'modern adapter signature restored');

SAVEPOINT ncs_projector_signature_drift;
ALTER FUNCTION enrichment.metadata_occupation_graph_rows(text,text,boolean)
 SET statement_timeout='41s';
SELECT pg_temp.assert_scoped_crosswalk_hidden('NCS projector signature drift');
ROLLBACK TO ncs_projector_signature_drift;
SELECT pg_temp.assert(replacement_matching.ready(),'NCS projector signature restored');

SAVEPOINT onet_projector_signature_drift;
ALTER FUNCTION onet_matching.graph_rows(text) SET statement_timeout='41s';
SELECT pg_temp.assert_scoped_crosswalk_hidden('O*NET projector signature drift');
ROLLBACK TO onet_projector_signature_drift;
SELECT pg_temp.assert(replacement_matching.ready(),'O*NET projector signature restored');

SAVEPOINT disabled_assessor;
ALTER TABLE enrichment.attempt DISABLE TRIGGER replacement_policy_assess;
SELECT pg_temp.assert_scoped_crosswalk_hidden('disabled NCS assessor');
ROLLBACK TO disabled_assessor;
SELECT pg_temp.assert(replacement_matching.ready(),'NCS assessor restored');

-- Seed intentionally pairs canonical NCS identity with noncanonical O*NET
-- identity "o-good". The established pair key is source + native posting key.
SELECT pg_temp.assert(EXISTS(
 SELECT 1 FROM pg_temp.crosswalk_workset_pairs(
  'urn:jobtology:onet:occupation:15-1253.00') p(value)
 WHERE p.value#>>'{ncs,posting_identity}' IS DISTINCT FROM
  p.value#>>'{onet,posting_identity}'
),'same source/key with different scheme identities remains paired');

SAVEPOINT freshness_and_null_pins;
UPDATE enrichment.input_bundle SET manifest=jsonb_set(manifest,
 '{document,normalized_hash}','null'::jsonb) WHERE bundle_id='pair-good';
UPDATE onet_matching.graph_edge SET properties=properties-
 'source_facts_sha256'-'release_id' WHERE posting_identity='o-good';
UPDATE classification.graph_load_node SET content_hash='changed-catalogue';
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'UNKNOWN source hashes and NULL/stale catalogue pin');
SELECT pg_temp.assert(EXISTS(
 SELECT 1 FROM pg_temp.crosswalk_workset_pairs(
  'urn:jobtology:onet:occupation:15-1253.00') p(value)
 WHERE p.value#>>'{ncs,normalized_hash}' IS NULL
  AND p.value#>>'{onet,source_facts_sha256}' IS NULL
  AND p.value#>>'{onet,catalog_pin}' IS NULL
  AND p.value#>>'{onet,catalog_freshness}'='STALE'
),'UNKNOWN/NULL/stale paired evidence is retained');
SELECT pg_temp.assert(EXISTS(
 SELECT 1 FROM jsonb_array_elements(catalog.ncs_onet_crosswalk_v1(
  'urn:jobtology:onet:occupation:15-1253.00',100,0)->'items') p(value)
 WHERE p.value->>'basis'='SHARED_POSTINGS'
  AND p.value->>'source_freshness'='STALE'
),'NULL stored O*NET hash compared with available live hash stays STALE');
-- A NULL live fact hash, rather than a missing observation or merely a NULL
-- stored hash, exercises the established UNKNOWN branch for O*NET.
CREATE OR REPLACE FUNCTION catalog._live_source_fact_hash(text,jsonb)
RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT NULL::text $$;
DO $unknown_source_result$
DECLARE answer jsonb;
BEGIN
 answer:=catalog.ncs_onet_crosswalk_v1(
  'urn:jobtology:onet:occupation:15-1253.00',100,0);
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(answer->'items') p(value)
  WHERE p.value->>'basis'='SHARED_POSTINGS'
   AND p.value->>'source_freshness'='UNKNOWN') THEN
  RAISE EXCEPTION 'UNKNOWN freshness fixture failed; observations=%; answer=%',
   (SELECT jsonb_agg(to_jsonb(p)) FROM
    catalog._live_source_observations(ARRAY['jobkorea:o-good']) p),answer;
 END IF;
END
$unknown_source_result$;
ROLLBACK TO freshness_and_null_pins;

SAVEPOINT review_and_unreviewed;
UPDATE enrichment.metadata_occupation_graph_guard SET include_unreviewed=false
 WHERE writer_token='n-pub';
SELECT pg_temp.assert((SELECT count(*)=0 FROM pg_temp.crosswalk_workset_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'unreviewed inclusion flag is respected');
INSERT INTO enrichment.metadata_occupation_decision
 VALUES('pair-good','ACCEPT','human',90001);
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'human-reviewed association under reviewed-only publication');
SELECT pg_temp.assert(EXISTS(
 SELECT 1 FROM pg_temp.crosswalk_workset_pairs(
  'urn:jobtology:onet:occupation:15-1253.00') p(value)
 WHERE p.value#>>'{ncs,review_status}'='HUMAN_REVIEWED'
),'human review provenance is unchanged');
INSERT INTO enrichment.metadata_occupation_decision
 VALUES('pair-good','REJECT','assistant',90002);
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'latest native review rejects association');
SELECT pg_temp.assert((SELECT count(*)=0 FROM pg_temp.crosswalk_workset_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'latest REJECT prevents pairing');
ROLLBACK TO review_and_unreviewed;

SAVEPOINT payload_task_and_source_identity;
INSERT INTO onet_matching.input
 SELECT (jsonb_populate_record(NULL::onet_matching.input,
  to_jsonb(i)||'{"task_id":"crosswalk-alternate-task"}'::jsonb)).*
 FROM onet_matching.input i
 WHERE i.task_id='jkr-20261103-onet' AND i.posting_identity='o-good';
UPDATE onet_matching.graph_edge SET properties=properties-'task_id',
 payload_json=((payload_json::jsonb)||
  '{"task_id":"crosswalk-alternate-task"}'::jsonb)::text
 WHERE posting_identity='o-good';
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'payload task fallback and same identity in multiple tasks');
SELECT pg_temp.assert((SELECT count(*)>0 FROM pg_temp.crosswalk_workset_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'alternate property task remains visible');
UPDATE onet_matching.input SET source_id='nara_job'
 WHERE task_id='crosswalk-alternate-task' AND posting_identity='o-good';
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'identical native ID in another source cannot pair with JobKorea');
SELECT pg_temp.assert((SELECT count(*)=0 FROM pg_temp.crosswalk_workset_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'source identity prevents false pairing');
ROLLBACK TO payload_task_and_source_identity;

-- A newer row can pass its guard-source pin while its payload task has no
-- input. Selecting/joining inputs before latest-edge DISTINCT revives the old
-- row and would silently create a pair absent from the established reader.
SAVEPOINT latest_edge_missing_input;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_replacement_current()
RETURNS jsonb LANGUAGE sql AS $$ SELECT NULL::jsonb $$;
INSERT INTO onet_matching.graph_guard
 VALUES('crosswalk-newer','jkr-20261103-onet','VERIFIED','db',now()+interval '1 hour');
INSERT INTO onet_matching.graph_edge
 SELECT 'crosswalk-newer',e.edge_id,e.posting_identity,e.occupation_identity,
  e.properties||'{"task_id":"crosswalk-missing-input"}'::jsonb,
  e.payload_json,e.content_hash FROM onet_matching.graph_edge e
 WHERE e.publication_id='o-pub' AND e.posting_identity='o-good';
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'newer selected edge with missing payload-task input');
SELECT pg_temp.assert((SELECT count(*)=0 FROM pg_temp.crosswalk_workset_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'newer missing-input edge does not revive old pair');
ROLLBACK TO latest_edge_missing_input;

-- Filtering by occupation precedes DISTINCT for an O*NET anchor. An NCS
-- anchor has no O*NET-code filter and must instead see the newest changed code.
SAVEPOINT latest_edge_changed_code;
CREATE OR REPLACE FUNCTION ingestion.jobkorea_replacement_current()
RETURNS jsonb LANGUAGE sql AS $$ SELECT NULL::jsonb $$;
INSERT INTO onet_matching.graph_guard
 VALUES('crosswalk-changed','jkr-20261103-onet','VERIFIED','db',now()+interval '1 hour');
INSERT INTO onet_matching.graph_edge
 SELECT 'crosswalk-changed',e.edge_id,e.posting_identity,e.occupation_identity,
  e.properties||'{"occupation_code":"15-1252.00"}'::jsonb,
  e.payload_json,e.content_hash FROM onet_matching.graph_edge e
 WHERE e.publication_id='o-pub' AND e.posting_identity='o-good';
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'O*NET code filter precedes latest-edge selection');
SELECT pg_temp.assert((SELECT count(*)>0 FROM pg_temp.crosswalk_workset_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'O*NET anchor retains older matching-code edge');
SELECT pg_temp.assert_crosswalk_workset('ncs:occupation:20010701',
 'NCS anchor selects globally newest edge code');
SELECT pg_temp.assert(NOT EXISTS(
 SELECT 1 FROM pg_temp.crosswalk_workset_pairs('ncs:occupation:20010701') p(value)
 WHERE p.value#>>'{onet,occupation_code}'='15-1253.00'
),'NCS anchor does not revive superseded old-code edge');
SELECT pg_temp.assert(EXISTS(
 SELECT 1 FROM pg_temp.crosswalk_workset_pairs('ncs:occupation:20010701') p(value)
 WHERE p.value#>>'{onet,occupation_code}'='15-1252.00'
),'NCS anchor retains new-code association');
ROLLBACK TO latest_edge_changed_code;

-- Missing optimized prerequisites preserve the earlier optional-adapter
-- contract. Use legacy, out-of-replacement rows and an old-shaped adapter;
-- restore both catalogue and qualified definition before leaving this case.
SAVEPOINT partial_installation_fallback;
CREATE TEMP TABLE crosswalk_legacy_fixture_rows AS
 SELECT * FROM catalog._inferred_occupation_rows(
  ARRAY['20010701','15-1253.00'],ARRAY['jobkorea:o-good']);
UPDATE crosswalk_legacy_fixture_rows SET source_run_id='unrelated-legacy-source';
ALTER TABLE enrichment.metadata_occupation_catalog RENAME TO crosswalk_hidden_catalog;
CREATE OR REPLACE FUNCTION catalog._inferred_occupation_rows(
 occupation_codes text[],posting_choices text[])
RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,
 occupation_scheme text,occupation_code text,occupation_name text,association_id text,
 review_status text,stage text,confidence_state text,source_hash text,
 normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,
 catalog_freshness text)
LANGUAGE sql STABLE AS $$
 SELECT * FROM pg_temp.crosswalk_legacy_fixture_rows r
 WHERE (occupation_codes IS NULL OR r.occupation_code=ANY(occupation_codes))
  AND (posting_choices IS NULL OR r.posting_key=ANY(posting_choices))
$$;
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'actual missing-prerequisite fallback with earlier adapter');
SELECT pg_temp.assert((SELECT count(*)>0 FROM pg_temp.crosswalk_workset_pairs(
 'urn:jobtology:onet:occupation:15-1253.00')),'legacy fallback remains nonvacuous');
ROLLBACK TO partial_installation_fallback;
SELECT pg_temp.assert(replacement_matching.ready(),'qualified definitions restored after fallback');
SELECT pg_temp.assert_crosswalk_workset('urn:jobtology:onet:occupation:15-1253.00',
 'complete fixture restores original scoped reader');
SELECT pg_temp.assert(NOT EXISTS(
 SELECT 1 FROM pg_proc p CROSS JOIN LATERAL
  aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
 WHERE p.oid='catalog._crosswalk_pair_rows(text)'::regprocedure
  AND a.grantee=0 AND a.privilege_type='EXECUTE'
),'private crosswalk helper is not executable by PUBLIC');

SELECT 'CROSSWALK_WORKSET_ASSERTIONS_PASSED';
ROLLBACK;
