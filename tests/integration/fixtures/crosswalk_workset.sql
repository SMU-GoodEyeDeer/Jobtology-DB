-- Native-shaped source/catalogue additions around the ACTUAL SQL038 adapter.
ALTER TABLE ingestion.run ADD COLUMN mode text DEFAULT 'FULL', ADD COLUMN created_at timestamptz DEFAULT now(), ADD COLUMN completed_at timestamptz DEFAULT now();
CREATE OR REPLACE VIEW ingestion.latest_ready_run AS SELECT DISTINCT ON(source_id) run_id,source_id,state,completed_at FROM ingestion.run WHERE state='READY' ORDER BY source_id,completed_at DESC,run_id DESC;
CREATE TABLE ingestion.record(run_id text,document_id text,record_id text,normalized jsonb);
CREATE TABLE ingestion.document(run_id text,document_id text,selected boolean);
CREATE VIEW ingestion.ready_record AS SELECT r.run_id,u.source_id,r.normalized FROM ingestion.record r JOIN ingestion.run u USING(run_id) JOIN ingestion.document d USING(run_id,document_id) WHERE u.state='READY' AND d.selected;
CREATE FUNCTION catalog._live_job_postings(text) RETURNS TABLE(posting_id text,normalized jsonb) LANGUAGE sql STABLE AS $$ SELECT normalized->>'posting_id',normalized FROM ingestion.record WHERE run_id=$1 $$;
CREATE FUNCTION catalog._live_source_observations()
RETURNS TABLE(source_id text,priority integer,posting_id text,run_id text,data_as_of timestamptz,normalized jsonb)
LANGUAGE sql STABLE AS $$ SELECT r.source_id,0,'jobkorea:'||(r.normalized->>'posting_id'),r.run_id,u.completed_at,r.normalized
 FROM ingestion.ready_record r JOIN ingestion.run u USING(run_id) WHERE r.source_id='jobkorea' $$;
CREATE FUNCTION catalog._live_source_fact_hash(text,jsonb) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT encode(sha256(convert_to($2::text,'UTF8')),'hex') $$;
CREATE TABLE classification.catalog_release(release_id text PRIMARY KEY,state text);
INSERT INTO classification.catalog_release VALUES('rel','READY');
ALTER TABLE classification.catalog_current ADD COLUMN scheme_id text DEFAULT 'ONET';
ALTER TABLE classification.term ADD COLUMN description text DEFAULT 'Local catalogue description';
UPDATE classification.term SET term_id='urn:jobtology:onet:occupation:'||code;
UPDATE classification.graph_load_node SET node_id='urn:jobtology:onet:occupation:15-1253.00' WHERE node_id='occ';
UPDATE onet_matching.graph_edge SET occupation_identity='urn:jobtology:onet:occupation:15-1253.00' WHERE occupation_identity='occ';
-- The existing scoped o-good ONET observation has a deliberately noncanonical
-- identity. Pair by (source,key), exactly as the original crosswalk does.
INSERT INTO enrichment.item VALUES('pair-good','pair-internal','jkr-20261103-ncs-test','{"title":"인공지능 플랫폼 구축 엔지니어"}','pair-source');
INSERT INTO enrichment.attempt VALUES('pair-good','jkr-20261103-ncs-test','pair-good','VALIDATED','{"outcome":"matched","matches":[{"occupation_code":"20010701"}]}','unchanged',.001);
INSERT INTO enrichment.metadata_occupation_binding VALUES('pair-good','pair-good','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f','ncs','pair-source');
INSERT INTO enrichment.input_bundle VALUES('pair-good','{"document":{"source_record_id":"o-good","normalized_hash":"pair-source"}}');
INSERT INTO enrichment.metadata_occupation_result VALUES('pair-good','pair-good','{"outcome":"matched","matches":[{"occupation_code":"20010701"}]}','pair-good');
INSERT INTO enrichment.metadata_occupation_candidate VALUES('pair-good','pair-good','ncs','20010701');
INSERT INTO ingestion.document VALUES('ncs','ncatalog',true),('jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f','postings',true);
INSERT INTO ingestion.record VALUES('ncs','ncatalog','n-unit','{"code":"2001070101","occupation_code":"20010701","occupation_name":"AI platform","name":"AI platform implementation","definition":"Build an AI platform."}'),('jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f','postings','o-good','{"kind":"JobPosting","representation":"local_listing","metadata_accepted":true,"posting_id":"o-good"}');
