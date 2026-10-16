-- Batch-free source storage retention. Durable PostgreSQL archives remain;
-- retention neither creates nor deletes Neo4j history or business entities.
-- Install 001_retention and graph 002_source_graph_projection first.
BEGIN;
ALTER TABLE retention.plan_run ADD COLUMN IF NOT EXISTS source_projection_verified boolean NOT NULL DEFAULT false;
CREATE OR REPLACE FUNCTION retention.protection(id text,keep_count integer) RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE u ingestion.run; ontology_pinned boolean; BEGIN
 SELECT * INTO u FROM ingestion.run WHERE run_id=id;
 IF NOT FOUND THEN RETURN 'MISSING_RUN'; END IF;
 IF u.source_id='jobkorea' THEN RETURN 'UNSUPPORTED_JOBKOREA_STORAGE_RETENTION'; END IF;
 IF u.state<>'READY' OR u.mode='SMOKE' THEN RETURN 'NOT_ACCEPTED_FULL_SNAPSHOT'; END IF;
 IF id IN (SELECT run_id FROM ingestion.run WHERE source_id=u.source_id AND state='READY' AND mode<>'SMOKE'
   ORDER BY created_at DESC,run_id DESC LIMIT keep_count) THEN RETURN 'KEEP_LATEST'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.dependency WHERE input_run_id=id) THEN RETURN 'UPSTREAM_DEPENDENCY'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.dataset WHERE job_run_id=id OR ncs_run_id=id) THEN RETURN 'EVALUATION_DATASET'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.batch WHERE job_run_id=id OR ncs_run_id=id) THEN RETURN 'LLM_BATCH'; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.ncs_catalog WHERE run_id=id) THEN RETURN 'LLM_CATALOG'; END IF;
 -- Optional ontology installation. Check before touching graph/raw files, not
 -- only when a later PostgreSQL FK would reject deletion.
 IF to_regclass('ontology.source_pin') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM ontology.source_pin WHERE run_id=$1)' INTO ontology_pinned USING id;
  IF ontology_pinned THEN RETURN 'ONTOLOGY_RELEASE'; END IF;
 END IF;
 IF to_regclass('attachment.batch') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM attachment.batch WHERE job_run_id=$1)' INTO ontology_pinned USING id;
  IF ontology_pinned THEN RETURN 'ATTACHMENT_BATCH'; END IF;
 END IF;
 IF to_regclass('ontology.observation_run') IS NOT NULL THEN
  EXECUTE 'SELECT EXISTS(SELECT 1 FROM ontology.observation_run WHERE run_id=$1)' INTO ontology_pinned USING id;
  IF ontology_pinned THEN RETURN 'ONTOLOGY_OBSERVATION_HISTORY'; END IF;
 END IF;
 IF to_regclass('enrichment.link_publication') IS NOT NULL THEN
  IF to_regclass('enrichment.link_publication_source_run') IS NOT NULL THEN
   EXECUTE 'SELECT EXISTS(SELECT 1 FROM enrichment.link_publication p WHERE p.job_run_id=$1 OR p.ncs_run_id=$1 OR EXISTS
    (SELECT 1 FROM enrichment.link_publication_source_run s WHERE s.publication_id=p.publication_id AND s.run_id=$1))'
    INTO ontology_pinned USING id;
  ELSE
   EXECUTE 'SELECT EXISTS(SELECT 1 FROM enrichment.link_publication WHERE job_run_id=$1 OR ncs_run_id=$1)'
    INTO ontology_pinned USING id;
  END IF;
  IF ontology_pinned THEN RETURN 'REVIEWED_LINK_PUBLICATION'; END IF;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.graph_export WHERE run_id=id) THEN RETURN 'GRAPH_NOT_CHECKPOINTED'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.request_attempt WHERE run_id=id AND reserved_at>clock_timestamp()-interval '24 hours')
   THEN RETURN 'REQUEST_QUOTA_WINDOW'; END IF;
 IF EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=id) THEN RETURN 'VALIDATION_ISSUES'; END IF;
 RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION retention.archive(id text,owner text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.assert_owner(archive.id,owner);
 PERFORM ingestion.assert_source_graph_projection(r.run_id) FROM retention.plan_run r
 WHERE r.plan_id=archive.id AND r.selected;
 IF (SELECT phase FROM retention.plan WHERE plan_id=archive.id)<>'PLANNED' THEN RETURN; END IF;
 WITH reference_rows AS MATERIALIZED (
 SELECT x.record_id,jsonb_agg(to_jsonb(x) ORDER BY field,identity_id) AS refs
 FROM ingestion.graph_reference x WHERE x.run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=archive.id AND selected) GROUP BY x.record_id
 )
 INSERT INTO retention.archive_record(source_id,source_record_id,run_id,source_created_at,record_payload,
 run_metadata,document_metadata,dependencies,graph_payload,graph_references,archive_id,archive_hash,plan_id)
 SELECT DISTINCT ON(r.source_id,r.source_record_id) r.source_id,r.source_record_id,r.run_id,p.created_at,to_jsonb(r),
 p.run_metadata,to_jsonb(d),p.dependencies,to_jsonb(g),coalesce(refs.refs,'[]'),
 'archive:'||encode(sha256(convert_to(jsonb_build_array(r.source_id,r.source_record_id)::text,'UTF8')),'hex'),
 encode(sha256(convert_to(jsonb_build_array(to_jsonb(r),to_jsonb(g),coalesce(refs.refs,'[]'),p.run_metadata,to_jsonb(d),p.dependencies)::text,'UTF8')),'hex'),archive.id
 FROM ingestion.ready_record r JOIN retention.plan_run p ON p.run_id=r.run_id AND p.plan_id=archive.id AND p.selected
 JOIN ingestion.document d ON d.run_id=r.run_id AND d.document_id=r.document_id
 JOIN ingestion.graph_record g ON g.run_id=r.run_id AND g.record_id=r.record_id
 LEFT JOIN reference_rows refs ON refs.record_id=g.id
 ORDER BY r.source_id,r.source_record_id,p.created_at DESC,r.run_id DESC
 ON CONFLICT(source_id,source_record_id) DO UPDATE SET
 run_id=excluded.run_id,source_created_at=excluded.source_created_at,record_payload=excluded.record_payload,
 run_metadata=excluded.run_metadata,document_metadata=excluded.document_metadata,dependencies=excluded.dependencies,
 graph_payload=excluded.graph_payload,graph_references=excluded.graph_references,archive_hash=excluded.archive_hash,
 plan_id=excluded.plan_id,archived_at=clock_timestamp()
 WHERE (excluded.source_created_at,excluded.run_id)>(retention.archive_record.source_created_at,retention.archive_record.run_id);
 UPDATE retention.plan SET phase='ARCHIVED' WHERE plan_id=archive.id;
END $$;
CREATE OR REPLACE FUNCTION retention.verify_source_projections(id text,owner text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE selected_run record; BEGIN
 IF EXISTS(SELECT 1 FROM retention.plan WHERE plan_id=id AND state='COMPLETE') THEN RETURN; END IF;
 PERFORM retention.assert_owner(id,owner);
 IF (SELECT phase FROM retention.plan WHERE plan_id=id)<>'ARCHIVED'
 THEN RAISE EXCEPTION 'POSTGRESQL_ARCHIVE_REQUIRED'; END IF;
 FOR selected_run IN SELECT * FROM retention.plan_run WHERE plan_id=id AND selected LOOP
  PERFORM ingestion.assert_source_graph_projection(selected_run.run_id);
  IF NOT EXISTS(SELECT 1 FROM ingestion.source_graph_projection p
   WHERE p.run_id=selected_run.run_id AND p.source_id=selected_run.source_id
    AND p.record_count=selected_run.record_count AND p.state='READY')
  THEN RAISE EXCEPTION 'SOURCE_PROJECTION_RETENTION_MISMATCH'; END IF;
  UPDATE retention.plan_run SET source_projection_verified=true
   WHERE plan_id=id AND run_id=selected_run.run_id;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION retention.mark_graph(id text,owner text,target text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'GRAPH_RETENTION_RETIRED: use retention.verify_source_projections'; END $$;
CREATE OR REPLACE FUNCTION retention.bind_graph(id text,owner text,database_id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'GRAPH_RETENTION_RETIRED: source retention uses PostgreSQL proofs'; END $$;
CREATE OR REPLACE FUNCTION retention.mark_file(id text,owner text,target text,doc text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM retention.assert_owner(id,owner);
 IF EXISTS(SELECT 1 FROM retention.plan_run WHERE plan_id=id AND selected AND NOT source_projection_verified)
 THEN RAISE EXCEPTION 'SOURCE_PROJECTION_CHECKPOINT_INCOMPLETE'; END IF;
 UPDATE retention.plan_file SET deleted_at=clock_timestamp() WHERE plan_id=id AND run_id=target AND document_id=doc;
END $$;
CREATE OR REPLACE FUNCTION retention.finish(id text,owner text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM retention.plan WHERE plan_id=id AND state='COMPLETE') THEN RETURN; END IF;
 PERFORM retention.assert_owner(id,owner);
 IF (SELECT phase FROM retention.plan WHERE plan_id=id)<>'ARCHIVED'
  OR EXISTS(SELECT 1 FROM retention.plan_run WHERE plan_id=id AND selected AND NOT source_projection_verified)
  OR EXISTS(SELECT 1 FROM retention.plan_file WHERE plan_id=id AND deleted_at IS NULL)
 THEN RAISE EXCEPTION 'RETENTION_CHECKPOINTS_INCOMPLETE'; END IF;
 PERFORM ingestion.assert_source_graph_projection(r.run_id) FROM retention.plan_run r WHERE r.plan_id=id AND r.selected;
 PERFORM set_config('jobtology.retention_owner',owner,true);
 -- Same atomic PostgreSQL transaction; no CASCADE and no LLM history deletion.
 DELETE FROM ingestion.graph_export WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 DELETE FROM ingestion.request_attempt WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 DELETE FROM ingestion.rejected_row WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 DELETE FROM ingestion.record WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 DELETE FROM ingestion.document WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 DELETE FROM ingestion.partition WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 DELETE FROM ingestion.dependency WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 DELETE FROM ingestion.run WHERE run_id IN(SELECT run_id FROM retention.plan_run WHERE plan_id=id AND selected);
 UPDATE retention.plan SET state='COMPLETE',phase='COMPLETE',owner_id=NULL,completed_at=clock_timestamp() WHERE plan_id=id;
END $$;
COMMIT;
