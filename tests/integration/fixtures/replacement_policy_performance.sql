-- Bounded synthetic 5k projection/modern-reader proof, with realistic lookup indexes.
CREATE UNIQUE INDEX ON onet_matching.input(task_id,posting_identity);
CREATE INDEX ON enrichment.metadata_occupation_binding(item_id);
CREATE INDEX ON enrichment.metadata_occupation_result(item_id);
CREATE INDEX ON enrichment.metadata_occupation_candidate(result_id);
INSERT INTO enrichment.item SELECT 'ns-'||n,'ns-'||n,'jkr-20261103-ncs-test','{"title":"인공지능 플랫폼 구축 엔지니어"}',md5(n::text) FROM generate_series(1,5000)n;
INSERT INTO enrichment.attempt SELECT 'ns-'||n,'jkr-20261103-ncs-test','ns-'||n,'VALIDATED','{"outcome":"matched","matches":[{"occupation_code":"20010701"}]}','raw',.001 FROM generate_series(1,5000)n;
INSERT INTO enrichment.metadata_occupation_binding SELECT item_id,item_id,'jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f','ncs',source_hash FROM enrichment.item WHERE item_id LIKE 'ns-%';
INSERT INTO enrichment.input_bundle SELECT item_id,jsonb_build_object('document',jsonb_build_object('source_record_id',posting_id,'normalized_hash',source_hash)) FROM enrichment.item WHERE item_id LIKE 'ns-%';
INSERT INTO enrichment.metadata_occupation_result SELECT item_id,attempt_id,parsed_output,attempt_id FROM enrichment.attempt WHERE item_id LIKE 'ns-%';
INSERT INTO enrichment.metadata_occupation_candidate SELECT attempt_id,attempt_id,'ncs','20010701' FROM enrichment.attempt WHERE item_id LIKE 'ns-%';
INSERT INTO enrichment.fixture_edges SELECT attempt_id,attempt_id,'ncs:occupation:20010701',attempt_id,jsonb_build_object('attempt_id',attempt_id,'job_run_id','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f') FROM enrichment.attempt WHERE item_id LIKE 'ns-%';
INSERT INTO onet_matching.input SELECT 'jkr-20261103-onet','os-'||n,'jobkorea','jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f','os-'||n,'facts','src','candidates','request','os-'||n,'{"title":"Software QA Engineer"}',jsonb_build_object('posting_id','os-'||n) FROM generate_series(1,5000)n;
INSERT INTO onet_matching.attempt SELECT 'os-'||n,'jkr-20261103-onet','os-'||n,'obatch','VALIDATED','{"outcome":"matched","matches":[{"occupation_code":"15-1253.00","match_rank":1}]}','openai/gpt-5.6-luna','OpenAI',.001,'raw' FROM generate_series(1,5000)n;
CREATE FUNCTION pg_temp.timed(label text,query text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE started timestamptz:=clock_timestamp(); bytes bigint; BEGIN
 EXECUTE query INTO bytes;
 RETURN jsonb_build_object('benchmark',label,'elapsed_ms',round(extract(epoch FROM clock_timestamp()-started)*1000,3),'bytes',bytes);
END $$;
SET statement_timeout='5s';
SELECT pg_temp.timed('ncs_graph_5001',$q$SELECT sum(octet_length(payload::text)) FROM enrichment.metadata_occupation_graph_rows('jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f','ncs',true)$q$);
SELECT pg_temp.timed('ncs_api_5001',$q$SELECT sum(octet_length(to_jsonb(r)::text)) FROM catalog._inferred_occupation_rows(ARRAY['20010701'],NULL)r$q$);
SELECT pg_temp.timed('onet_graph_5001',$q$SELECT sum(octet_length(payload_json)) FROM onet_matching.graph_rows('jkr-20261103-onet')$q$);
INSERT INTO onet_matching.graph_edge SELECT 'o-pub',g.* FROM onet_matching.graph_rows('jkr-20261103-onet')g WHERE posting_identity LIKE 'os-%';
SELECT pg_temp.timed('onet_api_5001',$q$SELECT sum(octet_length(to_jsonb(r)::text)) FROM catalog._inferred_occupation_rows(ARRAY['15-1253.00'],NULL)r$q$);
RESET statement_timeout;
