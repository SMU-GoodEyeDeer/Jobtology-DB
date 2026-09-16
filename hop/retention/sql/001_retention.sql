-- Manual source-snapshot retention. Requires ingestion + operations + enrichment SQL.
-- No scheduled deletion. Install before deploying the guarded graph workflows.
BEGIN;
CREATE SCHEMA IF NOT EXISTS retention;
CREATE TABLE IF NOT EXISTS retention.plan (
 plan_id text PRIMARY KEY, source_id text NOT NULL, selection_mode text NOT NULL,
 amount integer NOT NULL, keep_latest integer NOT NULL, raw_base text NOT NULL,
 cutoff timestamptz, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 state text NOT NULL DEFAULT 'PLANNED' CHECK(state IN ('PLANNED','ACTIVE','COMPLETE','CANCELLED')),
 phase text NOT NULL DEFAULT 'PLANNED', owner_id text, started_at timestamptz, completed_at timestamptz,
 last_error text
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_retention ON retention.plan((true)) WHERE state='ACTIVE';
ALTER TABLE retention.plan ADD COLUMN IF NOT EXISTS graph_anchor_run_id text;
ALTER TABLE retention.plan ADD COLUMN IF NOT EXISTS graph_database_id text;
CREATE OR REPLACE FUNCTION ingestion.maintenance_active() RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM retention.plan WHERE state='ACTIVE');
$$;
CREATE TABLE IF NOT EXISTS retention.plan_run (
 plan_id text NOT NULL REFERENCES retention.plan, run_id text NOT NULL,
 source_id text NOT NULL, created_at timestamptz NOT NULL, selected boolean NOT NULL,
 reason text NOT NULL, fingerprint text NOT NULL, record_count bigint NOT NULL,
 document_count bigint NOT NULL, raw_bytes bigint NOT NULL,
 run_metadata jsonb NOT NULL, dependencies jsonb NOT NULL,
 graph_deleted boolean NOT NULL DEFAULT false, PRIMARY KEY(plan_id,run_id)
);
CREATE TABLE IF NOT EXISTS retention.plan_file (
 plan_id text NOT NULL, run_id text NOT NULL, document_id text NOT NULL,
 raw_path text NOT NULL, raw_sha256 text NOT NULL, byte_length bigint NOT NULL,
 deleted_at timestamptz, PRIMARY KEY(plan_id,run_id,document_id),
 FOREIGN KEY(plan_id,run_id) REFERENCES retention.plan_run
);
-- These rows deliberately have no FK to ingestion.run: the snapshot will be removed.
CREATE TABLE IF NOT EXISTS retention.archive_record (
 source_id text NOT NULL, source_record_id text NOT NULL, run_id text NOT NULL,
 source_created_at timestamptz NOT NULL, record_payload jsonb NOT NULL,
 run_metadata jsonb NOT NULL, document_metadata jsonb NOT NULL, dependencies jsonb NOT NULL,
 graph_payload jsonb NOT NULL, graph_references jsonb NOT NULL,
 archive_id text NOT NULL UNIQUE, archive_hash text NOT NULL,
 plan_id text NOT NULL REFERENCES retention.plan, archived_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(source_id,source_record_id)
);
CREATE TABLE IF NOT EXISTS retention.writer (
 writer_id text PRIMARY KEY, kind text NOT NULL, target_id text NOT NULL,
 started_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION retention.gate() RETURNS void LANGUAGE sql AS $$
 SELECT pg_advisory_xact_lock(hashtextextended('jobtology-retention-gate-v1',0));
$$;
CREATE OR REPLACE FUNCTION retention.freeze_writes() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE active_id text; BEGIN
 PERFORM retention.gate();
 SELECT plan_id INTO active_id FROM retention.plan WHERE state='ACTIVE';
 IF active_id IS NOT NULL AND current_setting('jobtology.retention_owner',true) IS DISTINCT FROM
   (SELECT owner_id FROM retention.plan WHERE plan_id=active_id) THEN
  RAISE EXCEPTION 'RETENTION_ACTIVE: %; resume that plan before writing source data',active_id;
 END IF;
 -- A disconnected executor must still keep the maintenance fence in place.
 IF active_id IS NOT NULL AND (SELECT owner_id IS NULL FROM retention.plan WHERE plan_id=active_id) THEN
  RAISE EXCEPTION 'RETENTION_ACTIVE: %; executor stopped; resume that plan',active_id;
 END IF;
 RETURN NULL;
END $$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['ingestion.run','ingestion.dependency','ingestion.partition','ingestion.document',
 'ingestion.record','ingestion.rejected_row','ingestion.request_attempt','ingestion.graph_export',
 'enrichment.batch','enrichment.dataset','enrichment.ncs_catalog'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER retention_write_guard BEFORE INSERT OR UPDATE OR DELETE ON %s FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',t);
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION retention.enter_writer(id text,writer_kind text,target text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM retention.plan WHERE state='ACTIVE') THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF nullif(id,'') IS NULL THEN RAISE EXCEPTION 'WRITER_ID_REQUIRED'; END IF;
 INSERT INTO retention.writer(writer_id,kind,target_id) VALUES(id,writer_kind,coalesce(target,''));
END $$;
CREATE OR REPLACE FUNCTION retention.leave_writer(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM retention.gate(); DELETE FROM retention.writer WHERE writer_id=id; END $$;

CREATE OR REPLACE FUNCTION retention.run_fingerprint(id text) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT md5(jsonb_build_object('run',(SELECT to_jsonb(u) FROM ingestion.run u WHERE run_id=id),
 'documents',(SELECT jsonb_agg(to_jsonb(d) ORDER BY document_id) FROM ingestion.document d WHERE run_id=id),
 'records',(SELECT md5(string_agg(to_jsonb(r)::text,E'\n' ORDER BY document_id,locator)) FROM ingestion.record r WHERE run_id=id),
 'dependencies',(SELECT jsonb_agg(to_jsonb(d) ORDER BY input_source_id) FROM ingestion.dependency d WHERE run_id=id))::text);
$$;
CREATE OR REPLACE FUNCTION retention.protection(id text,keep_count integer) RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE u ingestion.run; ontology_pinned boolean; BEGIN
 SELECT * INTO u FROM ingestion.run WHERE run_id=id;
 IF NOT FOUND THEN RETURN 'MISSING_RUN'; END IF;
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

CREATE OR REPLACE FUNCTION retention.resolve_raw_path(source text,base text,path text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE WHEN left(path,1)='/' THEN path ELSE base||'/'||
 CASE source WHEN 'alio_organization' THEN 'alio-raw' WHEN 'job_alio' THEN 'job-alio-raw' WHEN 'ncs_competency' THEN 'ncs-raw' ELSE source||'-raw' END||'/'||path END;
$$;

CREATE OR REPLACE FUNCTION retention.preview(id text,source text,choice text,n integer,keep_count integer,base text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE cut timestamptz; BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM retention.plan WHERE state='ACTIVE') THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.refresh_policy WHERE source_id=source) OR choice NOT IN ('OLDEST_COUNT','OLDER_THAN_DAYS')
  OR n NOT BETWEEN 1 AND 100000 OR keep_count NOT BETWEEN 1 AND 1000
  OR base !~ '^/[^:]+/data$' OR base ~ '(^|/)\.\.?(/|$)' OR base LIKE '%//%'
  THEN RAISE EXCEPTION 'INVALID_RETENTION_OPTIONS'; END IF;
 cut:=CASE WHEN choice='OLDER_THAN_DAYS' THEN clock_timestamp()-make_interval(days=>n) END;
 INSERT INTO retention.plan(plan_id,source_id,selection_mode,amount,keep_latest,raw_base,cutoff)
 VALUES(id,source,choice,n,keep_count,base,cut);
 INSERT INTO retention.plan_run(plan_id,run_id,source_id,created_at,selected,reason,fingerprint,
  record_count,document_count,raw_bytes,run_metadata,dependencies)
 SELECT id,u.run_id,u.source_id,u.created_at,false,coalesce(retention.protection(u.run_id,keep_count),'ELIGIBLE'),
 retention.run_fingerprint(u.run_id),(SELECT count(*) FROM ingestion.ready_record r WHERE r.run_id=u.run_id),
 (SELECT count(*) FROM ingestion.document d WHERE d.run_id=u.run_id),
 coalesce((SELECT sum(byte_length) FROM ingestion.document d WHERE d.run_id=u.run_id),0),to_jsonb(u),
 coalesce((SELECT jsonb_agg(to_jsonb(d) ORDER BY input_source_id) FROM ingestion.dependency d WHERE d.run_id=u.run_id),'[]')
 FROM ingestion.run u WHERE u.source_id=source;
 -- Count selects up to N oldest eligible runs AFTER protection; it never substitutes at execution time.
 UPDATE retention.plan_run SET selected=true,reason='SELECTED' WHERE plan_id=id AND run_id IN (
  SELECT run_id FROM retention.plan_run WHERE plan_id=id AND reason='ELIGIBLE' AND (cut IS NULL OR created_at<cut)
  ORDER BY created_at,run_id LIMIT CASE WHEN choice='OLDEST_COUNT' THEN n ELSE 2147483647 END);
 UPDATE retention.plan_run SET reason=CASE WHEN cut IS NULL THEN 'OUTSIDE_COUNT' ELSE 'NEWER_THAN_CUTOFF' END
 WHERE plan_id=id AND reason='ELIGIBLE';
 UPDATE retention.plan SET graph_anchor_run_id=(SELECT u.run_id FROM ingestion.run u JOIN ingestion.graph_export g USING(run_id)
 WHERE u.source_id=source AND u.state='READY' AND u.mode<>'SMOKE'
 AND NOT EXISTS(SELECT 1 FROM retention.plan_run r WHERE r.plan_id=id AND r.run_id=u.run_id AND r.selected)
 ORDER BY u.created_at DESC,u.run_id DESC LIMIT 1) WHERE plan_id=id;
 INSERT INTO retention.plan_file(plan_id,run_id,document_id,raw_path,raw_sha256,byte_length)
 SELECT id,d.run_id,d.document_id,retention.resolve_raw_path(source,base,d.raw_path),d.raw_sha256,d.byte_length FROM ingestion.document d
 JOIN retention.plan_run p ON p.run_id=d.run_id AND p.plan_id=id AND p.selected;
END $$;
CREATE OR REPLACE VIEW retention.plan_report AS
SELECT p.plan_id,p.source_id,p.selection_mode,p.amount,p.keep_latest,p.raw_base,p.cutoff,p.created_at,
 p.state,p.phase,p.owner_id,p.started_at,p.completed_at,p.last_error,
 count(r.run_id) FILTER(WHERE selected) AS selected_runs,
 count(r.run_id) FILTER(WHERE NOT selected) AS skipped_runs,
 coalesce(sum(record_count) FILTER(WHERE selected),0) AS source_records_to_prune,
 coalesce(sum(document_count) FILTER(WHERE selected),0) AS raw_files_to_delete,
 coalesce(sum(raw_bytes) FILTER(WHERE selected),0) AS raw_bytes_to_delete
FROM retention.plan p LEFT JOIN retention.plan_run r USING(plan_id) GROUP BY p.plan_id;

CREATE OR REPLACE FUNCTION retention.assert_owner(id text,owner text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM retention.plan WHERE plan_id=id AND state='ACTIVE' AND owner_id=owner)
 THEN RAISE EXCEPTION 'RETENTION_EXECUTOR_NOT_OWNER'; END IF;
END $$;
CREATE OR REPLACE FUNCTION retention.begin_execution(id text,owner text,base text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p retention.plan; r record; folder text; BEGIN
 PERFORM retention.gate(); SELECT * INTO p FROM retention.plan WHERE plan_id=id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_PLAN'; END IF;
 IF p.state='COMPLETE' THEN RETURN; END IF;
 IF p.state='CANCELLED' OR nullif(owner,'') IS NULL OR p.raw_base<>base THEN RAISE EXCEPTION 'INVALID_PLAN_EXECUTION'; END IF;
 IF p.owner_id IS NOT NULL THEN RAISE EXCEPTION 'EXECUTOR_ALREADY_RUNNING: %',p.owner_id; END IF;
 IF EXISTS(SELECT 1 FROM retention.plan WHERE state='ACTIVE' AND plan_id<>id) THEN RAISE EXCEPTION 'ANOTHER_RETENTION_ACTIVE'; END IF;
 IF EXISTS(SELECT 1 FROM retention.writer) OR EXISTS(SELECT 1 FROM ingestion.run WHERE state='LOADING')
  OR EXISTS(SELECT 1 FROM enrichment.batch WHERE state='RUNNING') THEN RAISE EXCEPTION 'WRITERS_BUSY'; END IF;
 IF NOT EXISTS(SELECT 1 FROM retention.plan_run WHERE plan_id=id AND selected) THEN RAISE EXCEPTION 'NO_ELIGIBLE_SNAPSHOTS'; END IF;
 FOR r IN SELECT * FROM retention.plan_run WHERE plan_id=id AND selected LOOP
  IF retention.protection(r.run_id,p.keep_latest) IS NOT NULL OR retention.run_fingerprint(r.run_id)<>r.fingerprint
  THEN RAISE EXCEPTION 'STALE_PLAN: %; create a new preview',r.run_id; END IF;
 END LOOP;
 folder:=CASE p.source_id WHEN 'alio_organization' THEN 'alio-raw' WHEN 'job_alio' THEN 'job-alio-raw' WHEN 'ncs_competency' THEN 'ncs-raw'
  ELSE p.source_id||'-raw' END;
 -- Exact manifest paths only; no glob, folder deletion, arbitrary root or traversal.
 IF EXISTS(SELECT 1 FROM retention.plan_file f WHERE plan_id=id AND
  (f.run_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
   OR left(raw_path,length(base||'/'||folder||'/'||f.run_id||'/'))<>base||'/'||folder||'/'||f.run_id||'/'
   OR raw_path ~ '(^|/)\.\.?(/|$)' OR raw_path LIKE '%//%' OR raw_path ~ '[:\\]' OR raw_path ~ '[[:cntrl:]]'))
 THEN RAISE EXCEPTION 'UNSAFE_RAW_PATH: only standard project data source/run files are supported'; END IF;
 IF EXISTS(SELECT 1 FROM retention.plan_file f JOIN (ingestion.document d JOIN ingestion.run u USING(run_id))
  ON retention.resolve_raw_path(u.source_id,base,d.raw_path)=f.raw_path
  WHERE f.plan_id=id AND d.run_id<>f.run_id) THEN RAISE EXCEPTION 'SHARED_RAW_PATH'; END IF;
 UPDATE retention.plan SET state='ACTIVE',owner_id=owner,started_at=coalesce(started_at,clock_timestamp()),last_error=NULL WHERE plan_id=id;
END $$;

CREATE OR REPLACE FUNCTION retention.archive(id text,owner text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.assert_owner(archive.id,owner);
 IF (SELECT graph_database_id FROM retention.plan WHERE plan_id=archive.id) IS NULL THEN RAISE EXCEPTION 'GRAPH_TARGET_NOT_VERIFIED'; END IF;
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
CREATE OR REPLACE FUNCTION retention.bind_graph(id text,owner text,database_id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.assert_owner(id,owner);
 IF nullif(database_id,'') IS NULL OR EXISTS(SELECT 1 FROM retention.plan WHERE plan_id=id AND graph_database_id IS NOT NULL AND graph_database_id<>database_id)
 THEN RAISE EXCEPTION 'GRAPH_DATABASE_CHANGED'; END IF;
 UPDATE retention.plan SET graph_database_id=database_id WHERE plan_id=id;
END $$;
CREATE OR REPLACE FUNCTION retention.mark_graph(id text,owner text,target text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM retention.assert_owner(id,owner);
 UPDATE retention.plan_run SET graph_deleted=true WHERE plan_id=id AND run_id=target AND selected;
END $$;
CREATE OR REPLACE FUNCTION retention.mark_file(id text,owner text,target text,doc text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM retention.assert_owner(id,owner);
 IF EXISTS(SELECT 1 FROM retention.plan_run WHERE plan_id=id AND selected AND NOT graph_deleted)
 THEN RAISE EXCEPTION 'GRAPH_CLEANUP_INCOMPLETE'; END IF;
 UPDATE retention.plan_file SET deleted_at=clock_timestamp() WHERE plan_id=id AND run_id=target AND document_id=doc;
END $$;
CREATE OR REPLACE FUNCTION retention.finish(id text,owner text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM retention.plan WHERE plan_id=id AND state='COMPLETE') THEN RETURN; END IF;
 PERFORM retention.assert_owner(id,owner);
 IF (SELECT phase FROM retention.plan WHERE plan_id=id)<>'ARCHIVED'
  OR EXISTS(SELECT 1 FROM retention.plan_run WHERE plan_id=id AND selected AND NOT graph_deleted)
  OR EXISTS(SELECT 1 FROM retention.plan_file WHERE plan_id=id AND deleted_at IS NULL)
 THEN RAISE EXCEPTION 'RETENTION_CHECKPOINTS_INCOMPLETE'; END IF;
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
CREATE OR REPLACE FUNCTION retention.release_executor(id text,owner text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM retention.gate();
 UPDATE retention.plan SET owner_id=NULL,last_error='Executor stopped. Inspect Hop log and resume this exact PLAN_ID.'
 WHERE plan_id=id AND owner_id=owner AND state='ACTIVE';
END $$;
CREATE OR REPLACE FUNCTION retention.cancel(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate();
 UPDATE retention.plan SET state='CANCELLED' WHERE plan_id=id AND state='PLANNED';
 IF NOT FOUND THEN RAISE EXCEPTION 'ONLY_UNEXECUTED_PLAN_CAN_BE_CANCELLED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION retention.recover(id text,owner text,kind text,confirmation text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF confirmation IS DISTINCT FROM 'STOPPED' THEN RAISE EXCEPTION 'CONFIRM_THE_OLD_WORKFLOW_IS_STOPPED'; END IF;
 IF kind='EXECUTOR' THEN PERFORM retention.release_executor(id,owner);
 ELSIF kind='WRITER' THEN PERFORM retention.leave_writer(owner);
 ELSE RAISE EXCEPTION 'INVALID_RECOVERY_KIND'; END IF;
END $$;

-- Archive is a last-known history interface. Current READY-only source views stay unchanged.
CREATE OR REPLACE VIEW retention.last_known_record AS
SELECT DISTINCT ON(source_id,source_record_id) * FROM (
 SELECT r.source_id,r.source_record_id,r.run_id,u.created_at AS source_created_at,
 r.source_payload,r.normalized,r.field_lineage,r.quality_flags,false AS archived
 FROM ingestion.ready_record r JOIN ingestion.run u USING(run_id)
 UNION ALL
 SELECT a.source_id,a.source_record_id,a.run_id,a.source_created_at,
 record_payload->'source_payload',record_payload->'normalized',record_payload->'field_lineage',record_payload->'quality_flags',true
 FROM retention.archive_record a
) s ORDER BY source_id,source_record_id,source_created_at DESC,run_id DESC,archived;
CREATE OR REPLACE VIEW retention.last_known_job_posting AS
WITH p AS MATERIALIZED(SELECT * FROM retention.last_known_record WHERE source_id='job_alio')
SELECT l.run_id,l.source_created_at,l.normalized->>'posting_id' AS posting_id,
 (l.normalized||jsonb_strip_nulls(d.normalized))-'representation' AS normalized,
 l.archived OR d.archived AS archived,
 EXISTS(SELECT 1 FROM ingestion.job_posting j JOIN ingestion.latest_ready_run u USING(run_id)
 WHERE j.posting_id=l.normalized->>'posting_id') AS in_latest_snapshot
FROM p l JOIN p d ON d.run_id=l.run_id AND d.normalized->>'posting_id'=l.normalized->>'posting_id'
 AND d.normalized->>'representation'='detail' WHERE l.normalized->>'representation'='list';
COMMIT;
