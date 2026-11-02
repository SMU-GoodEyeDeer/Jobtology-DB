CREATE FUNCTION pg_temp.assert(ok boolean,label text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'ASSERTION_FAILED: %',label; END IF; END $$;
SELECT pg_temp.assert((SELECT count(*)=3 FROM catalog._live_source_observations()),'legacy source set');
SELECT pg_temp.assert((SELECT count(*)=3 FROM catalog._inferred_occupation_rows(NULL,NULL)),'legacy mapping set');
SELECT ingestion.prepare_jobkorea_replacement('replacement','new',repeat('a',64),1,'ncs','new-task');
INSERT INTO ingestion.run VALUES ('new','jobkorea','READY','FULL',clock_timestamp(),clock_timestamp());
INSERT INTO ingestion.document VALUES ('new','d',true);
INSERT INTO ingestion.record VALUES ('new','d',4,'{"kind":"JobPosting","representation":"local_listing","metadata_accepted":true,"posting_id":"1","title":"new"}');
INSERT INTO ingestion.jobkorea_import VALUES('new',repeat('a',64));
INSERT INTO ingestion.source_graph_projection VALUES('new','READY');
INSERT INTO onet_matching.attempt VALUES('new-task','VALIDATED',now(),0.001);
-- No new NCS row represents a freshly validated abstention. Old match must disappear.
INSERT INTO enrichment.metadata_occupation_graph_guard VALUES('new-ncs','new','ncs',true,'READY',now());
INSERT INTO onet_matching.input VALUES ('new-task','jk1','jobkorea','new','{"posting_id":"1"}');
INSERT INTO onet_matching.graph_guard VALUES('new-onet','new-task','VERIFIED','db',now());
INSERT INTO onet_matching.graph_edge VALUES ('new-onet','edge-jk-new','jk1','occ','{"occupation_code":"15-1211.00","task_id":"new-task"}','{}');
SELECT pg_temp.assert((SELECT count(*)=3 AND bool_and(CASE WHEN source_id='jobkorea' THEN run_id='old' ELSE true END) FROM catalog._live_source_observations()),'prepared retains old observations');
SELECT pg_temp.assert((SELECT count(*)=2 FROM catalog._live_source_observations(ARRAY['jobkorea:1','jobkorea:2'])),'prepared bounded old set');
SELECT pg_temp.assert((SELECT count(*)=3 AND bool_and(source_run_id<>'new') FROM catalog._inferred_occupation_rows(NULL,NULL)),'prepared hides fresh mapping');
DO $$ BEGIN
 BEGIN UPDATE ingestion.jobkorea_replacement SET expected_count=2; RAISE EXCEPTION 'immutable update accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'IMMUTABLE_JOBKOREA_REPLACEMENT_HISTORY' THEN RAISE; END IF; END;
 BEGIN TRUNCATE ingestion.jobkorea_replacement_event; RAISE EXCEPTION 'immutable truncate accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'IMMUTABLE_JOBKOREA_REPLACEMENT_HISTORY' THEN RAISE; END IF; END;
 BEGIN INSERT INTO enrichment.metadata_occupation_graph_guard VALUES('replayed','old','ncs',true,'READY',now()); RAISE EXCEPTION 'old NCS replay accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'JOBKOREA_REPLACEMENT_RETIRED_GRAPH_PIN' THEN RAISE; END IF; END;
 BEGIN INSERT INTO onet_matching.graph_guard VALUES('replayed','old-task','VERIFIED','db',now()); RAISE EXCEPTION 'old ONET replay accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'JOBKOREA_REPLACEMENT_RETIRED_GRAPH_PIN' THEN RAISE; END IF; END;
END $$;
SELECT ingestion.block_jobkorea_replacement('replacement');
SELECT pg_temp.assert((SELECT count(*)=1 AND bool_and(source_id='job_alio') FROM catalog._live_source_observations()),'blocked preserves ALIO');
SELECT pg_temp.assert((SELECT count(*)=0 FROM catalog._live_source_observations(ARRAY['jobkorea:1'])),'blocked bounded hides JobKorea');
SELECT pg_temp.assert((SELECT count(*)=1 AND bool_and(source_id='job_alio') FROM catalog._inferred_occupation_rows(NULL,NULL)),'blocked mapping preserves ALIO');
DO $$ BEGIN
 BEGIN PERFORM ingestion.activate_jobkorea_replacement('replacement','old-ncs','new-onet','{"status":"VERIFIED","job_run_id":"new","replacement_id":"replacement"}'); RAISE EXCEPTION 'old NCS publication accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'JOBKOREA_REPLACEMENT_NCS_PUBLICATION_MISMATCH' THEN RAISE; END IF; END;
 BEGIN PERFORM ingestion.activate_jobkorea_replacement('replacement','new-ncs','old-onet','{"status":"VERIFIED","job_run_id":"new","replacement_id":"replacement"}'); RAISE EXCEPTION 'old ONET publication accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'JOBKOREA_REPLACEMENT_ONET_PUBLICATION_MISMATCH' THEN RAISE; END IF; END;
 BEGIN PERFORM ingestion.activate_jobkorea_replacement('replacement','new-ncs','new-onet','{"status":"VERIFIED","job_run_id":"old","replacement_id":"replacement"}'); RAISE EXCEPTION 'unbound graph receipt accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'JOBKOREA_REPLACEMENT_GRAPH_RECEIPT_MISMATCH' THEN RAISE; END IF; END;
END $$;
UPDATE onet_matching.attempt SET state='PLANNED' WHERE task_id='new-task';
DO $$ BEGIN
 BEGIN PERFORM ingestion.activate_jobkorea_replacement('replacement','new-ncs','new-onet','{"status":"VERIFIED","job_run_id":"new","replacement_id":"replacement"}'); RAISE EXCEPTION 'unsettled ONET cohort accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'JOBKOREA_REPLACEMENT_ONET_COHORT_UNSETTLED' THEN RAISE; END IF; END;
END $$;
UPDATE onet_matching.attempt SET state='VALIDATED' WHERE task_id='new-task';
UPDATE ingestion.jobkorea_import SET file_sha256=repeat('b',64) WHERE run_id='new';
DO $$ BEGIN
 BEGIN PERFORM ingestion.activate_jobkorea_replacement('replacement','new-ncs','new-onet','{"status":"VERIFIED","job_run_id":"new","replacement_id":"replacement"}'); RAISE EXCEPTION 'different file accepted'; EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'JOBKOREA_REPLACEMENT_INPUT_MISMATCH' THEN RAISE; END IF; END;
END $$;
UPDATE ingestion.jobkorea_import SET file_sha256=repeat('a',64) WHERE run_id='new';
SELECT ingestion.activate_jobkorea_replacement('replacement','new-ncs','new-onet','{"status":"VERIFIED","job_run_id":"new","replacement_id":"replacement"}');
SELECT pg_temp.assert((SELECT count(*)=2 AND bool_and(CASE WHEN source_id='jobkorea' THEN run_id='new' ELSE true END) FROM catalog._live_source_observations()),'serving exact fresh cohort');
SELECT pg_temp.assert((SELECT count(*)=1 AND min(posting_id)='jobkorea:1' FROM catalog._live_source_observations(ARRAY['jobkorea:1','jobkorea:2'])),'omitted posting gone from bounded reader');
SELECT pg_temp.assert((SELECT count(*)=2 AND count(*) FILTER(WHERE source_id='jobkorea' AND occupation_scheme='NCS')=0 AND count(*) FILTER(WHERE source_id='jobkorea' AND occupation_code='15-1211.00')=1 FROM catalog._inferred_occupation_rows(NULL,NULL)),'fresh abstention retires old NCS and ONET code removed');
SELECT ingestion.prepare_jobkorea_replacement('second','next',repeat('b',64),1,'ncs','next-task');
SELECT pg_temp.assert((SELECT count(*)=2 AND bool_and(CASE WHEN source_id='jobkorea' THEN run_id='new' ELSE true END) FROM catalog._live_source_observations()),'second preparation cannot resurrect omitted historical identities');
SELECT pg_temp.assert((SELECT count(*)=2 FROM catalog._inferred_occupation_rows(NULL,NULL)),'second preparation retains first active mapping pins');
SELECT pg_temp.assert((SELECT count(*)=4 FROM ingestion.record),'immutable source history preserved');
SELECT pg_temp.assert((SELECT count(*)=3 FROM onet_matching.graph_edge),'immutable mapping history preserved');
SELECT 'JOBKOREA_REPLACEMENT_SQL037_PASSED';

CREATE ROLE replacement_fixture_reader NOLOGIN;
SELECT pg_temp.assert(NOT has_function_privilege('replacement_fixture_reader','ingestion.jobkorea_replacement_current()','EXECUTE'),'activation metadata helper is private');
SELECT pg_temp.assert(NOT has_function_privilege('replacement_fixture_reader','ingestion.prepare_jobkorea_replacement(text,text,text,bigint,text,text)','EXECUTE'),'activation writer is private');
SELECT pg_temp.assert(NOT has_table_privilege('replacement_fixture_reader','ingestion.jobkorea_replacement_event','SELECT,INSERT,UPDATE,DELETE,TRUNCATE'),'activation audit table is private');
