-- Synthetic interfaces around actual policy/publication/modern-reader functions.
CREATE SCHEMA retention; CREATE SCHEMA ingestion; CREATE SCHEMA enrichment;
CREATE SCHEMA onet_matching; CREATE SCHEMA classification; CREATE SCHEMA catalog;
CREATE FUNCTION retention.gate() RETURNS void LANGUAGE sql AS $$ SELECT NULL::void $$;
CREATE FUNCTION retention.freeze_writes() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;
CREATE TABLE ingestion.run(run_id text,source_id text,state text);
CREATE VIEW ingestion.latest_ready_run AS SELECT * FROM ingestion.run;
CREATE FUNCTION ingestion.jobkorea_ncs_publication_allowed(text,text) RETURNS boolean LANGUAGE sql AS $$ SELECT true $$;
CREATE FUNCTION ingestion.jobkorea_onet_publication_allowed(text,text,text,text) RETURNS boolean LANGUAGE sql AS $$ SELECT true $$;
CREATE FUNCTION catalog._ncs_catalog_revalidation(text,text,text) RETURNS jsonb LANGUAGE sql AS $$ SELECT NULL::jsonb $$;
CREATE TABLE enrichment.batch(batch_id text PRIMARY KEY,job_run_id text,ncs_run_id text,settings jsonb,created_at timestamptz DEFAULT now());
CREATE TABLE enrichment.item(item_id text PRIMARY KEY,posting_id text,batch_id text,source_data jsonb,source_hash text);
CREATE TABLE enrichment.attempt(attempt_id text PRIMARY KEY,batch_id text,item_id text,state text,parsed_output jsonb,response_body text,cost_usd numeric);
CREATE TABLE enrichment.metadata_occupation_binding(item_id text,bundle_id text,job_run_id text,ncs_run_id text,source_hash text);
CREATE TABLE enrichment.input_bundle(bundle_id text,manifest jsonb);
CREATE TABLE enrichment.metadata_occupation_result(item_id text,result_id text,output jsonb,attempt_id text);
CREATE TABLE enrichment.metadata_occupation_candidate(result_id text,candidate_id text,ncs_run_id text,occupation_code text);
CREATE TABLE enrichment.metadata_occupation_catalog(ncs_run_id text,occupation_code text,occupation_name text,catalog_hash text);
CREATE TABLE enrichment.metadata_occupation_decision(result_id text,decision text,reviewer_kind text,decision_id bigint);
CREATE TABLE enrichment.metadata_occupation_candidate_decision(candidate_id text,decision text,reviewer_kind text,decision_id bigint);
CREATE TABLE enrichment.metadata_occupation_graph_guard(writer_token text,job_run_id text,ncs_run_id text,include_unreviewed boolean,state text,completed_at timestamptz DEFAULT now());
CREATE FUNCTION enrichment.hash(text) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT encode(sha256(convert_to($1,'UTF8')),'hex') $$;
CREATE FUNCTION enrichment.metadata_occupation_fields(jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$ SELECT $1 $$;
CREATE TABLE enrichment.fixture_edges(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb);
CREATE FUNCTION enrichment.metadata_occupation_graph_rows_legacy(jobs text,ncs text,include_unreviewed boolean)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql AS $$ SELECT * FROM enrichment.fixture_edges WHERE payload->>'job_run_id'=jobs $$;
CREATE FUNCTION enrichment.metadata_occupation_graph_rows_v3(text,text,boolean)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql AS $$ SELECT * FROM enrichment.fixture_edges WHERE false $$;
CREATE TABLE onet_matching.task(task_id text PRIMARY KEY,release_id text,database_id text,catalog_hash text,settings jsonb,settings_hash text);
CREATE TABLE onet_matching.input(task_id text,posting_identity text,source_id text,source_run_id text,source_record_id text,source_facts_sha256 text,source_hash text,candidates_hash text,request_hash text,input_hash text,source_fields jsonb,source_facts jsonb);
CREATE TABLE onet_matching.attempt(attempt_id text PRIMARY KEY,task_id text,posting_identity text,batch_id text,state text,parsed_output jsonb,actual_model text,provider text,cost_usd numeric,response_body text);
CREATE TABLE onet_matching.candidate_decision(attempt_id text,occupation_code text,decision_id bigint,decision text,actor text,actor_kind text,notes text);
CREATE TABLE onet_matching.graph_guard(publication_id text,task_id text,state text,database_id text,finished_at timestamptz DEFAULT now());
CREATE TABLE onet_matching.graph_edge(publication_id text,edge_id text,posting_identity text,occupation_identity text,properties jsonb,payload_json text,content_hash text);
CREATE FUNCTION onet_matching.hash(jsonb) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT encode(sha256(convert_to($1::text,'UTF8')),'hex') $$;
CREATE TABLE classification.term(release_id text,term_kind text,code text,term_id text,preferred_label text);
CREATE TABLE classification.catalog_current(database_id text,release_id text,load_id text);
CREATE TABLE classification.graph_load_node(load_id text,node_id text,content_hash text);
CREATE FUNCTION pg_temp.assert(ok boolean,msg text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'ASSERT:%',msg; END IF; END $$;
CREATE FUNCTION catalog._inferred_occupation_rows(text[],text[])
RETURNS TABLE(posting_key text,posting_identity text,source_id text,source_run_id text,occupation_scheme text,occupation_code text,occupation_name text,association_id text,review_status text,stage text,confidence_state text,source_hash text,normalized_hash text,source_facts_sha256 text,catalog_pin text,catalog_hash text,catalog_freshness text)
LANGUAGE sql AS $$ SELECT NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text WHERE false $$;

CREATE FUNCTION ingestion.jobkorea_replacement_current() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{"phase":"SERVING","ncs_writer_token":"n-pub","job_run_id":"jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f","onet_publication_id":"o-pub","onet_task_id":"jkr-20261103-onet"}'::jsonb $$;
CREATE FUNCTION ingestion.jobkorea_serving_run_allowed(text) RETURNS boolean LANGUAGE sql AS $$ SELECT true $$;
CREATE FUNCTION enrichment.metadata_occupation_graph_rows(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql AS $$ SELECT * FROM enrichment.fixture_edges WHERE payload->>'job_run_id'=jobs $$;
CREATE FUNCTION onet_matching.graph_rows(id text)
RETURNS TABLE(edge_id text,posting_identity text,occupation_identity text,properties jsonb,payload_json text,content_hash text)
LANGUAGE sql AS $$ SELECT NULL::text,NULL::text,NULL::text,NULL::jsonb,NULL::text,NULL::text WHERE false $$;
