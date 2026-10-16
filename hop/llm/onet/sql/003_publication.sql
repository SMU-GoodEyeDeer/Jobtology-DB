-- Flat O*NET inferred relationships only. PostgreSQL retains immutable histories.
BEGIN;
SELECT retention.gate();
CREATE TABLE IF NOT EXISTS onet_matching.candidate_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 attempt_id text NOT NULL REFERENCES onet_matching.attempt, occupation_code text NOT NULL,
 decision text NOT NULL CHECK(decision IN('ACCEPT','REJECT')),
 actor text NOT NULL CHECK(length(btrim(actor))>0), actor_kind text NOT NULL CHECK(actor_kind IN('human','assistant')),
 notes text NOT NULL CHECK(length(btrim(notes))>0), decided_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS onet_matching_candidate_decision_latest ON onet_matching.candidate_decision(attempt_id,occupation_code,decision_id DESC);
CREATE OR REPLACE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON onet_matching.candidate_decision
 FOR EACH ROW EXECUTE FUNCTION onet_matching.immutable();
CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON onet_matching.candidate_decision
 FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.immutable();
CREATE OR REPLACE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.candidate_decision
 FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();
CREATE OR REPLACE FUNCTION onet_matching.decide_candidate(aid text,code text,decision text,actor text,actor_kind text,notes text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE id bigint; BEGIN
 PERFORM retention.gate();
 IF NOT EXISTS(SELECT 1 FROM onet_matching.attempt a CROSS JOIN LATERAL jsonb_array_elements(a.parsed_output->'matches') m
  WHERE a.attempt_id=aid AND a.state='VALIDATED' AND m->>'occupation_code'=code)
 THEN RAISE EXCEPTION 'ONET_MATCHING_REVIEW_REQUIRES_INDIVIDUAL_VALIDATED_MATCH'; END IF;
 INSERT INTO onet_matching.candidate_decision(attempt_id,occupation_code,decision,actor,actor_kind,notes)
 VALUES(aid,code,decision,actor,actor_kind,notes) RETURNING decision_id INTO id;
 RETURN id;
END $$;
CREATE TABLE IF NOT EXISTS onet_matching.graph_guard (
 publication_id text PRIMARY KEY, task_id text NOT NULL REFERENCES onet_matching.task,
 database_id text NOT NULL, rows_hash text NOT NULL, expected_count bigint NOT NULL,
 state text NOT NULL CHECK(state IN('PREPARED','VERIFIED','FAILED')),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), finished_at timestamptz,
 verified_count bigint
);
CREATE UNIQUE INDEX IF NOT EXISTS onet_matching_one_graph_writer ON onet_matching.graph_guard(database_id) WHERE state='PREPARED';
CREATE TABLE IF NOT EXISTS onet_matching.graph_edge (
 publication_id text NOT NULL REFERENCES onet_matching.graph_guard, edge_id text NOT NULL,
 posting_identity text NOT NULL, occupation_identity text NOT NULL, properties jsonb NOT NULL,
 payload_json text NOT NULL, content_hash text NOT NULL,
 PRIMARY KEY(publication_id,edge_id)
);
CREATE OR REPLACE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON onet_matching.graph_edge
 FOR EACH ROW EXECUTE FUNCTION onet_matching.immutable();
CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON onet_matching.graph_edge
 FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.immutable();
CREATE OR REPLACE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.graph_edge
 FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();
CREATE OR REPLACE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.graph_guard
 FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();

CREATE OR REPLACE FUNCTION onet_matching.graph_rows(id text)
RETURNS TABLE(edge_id text,posting_identity text,occupation_identity text,properties jsonb,payload_json text,content_hash text)
LANGUAGE sql STABLE SET jit=off AS $$
 WITH selected AS (
  SELECT t.*,a.attempt_id,a.batch_id,a.parsed_output,a.actual_model,a.provider,a.cost_usd,
   i.posting_identity,i.source_id,i.source_run_id,i.source_record_id,i.source_facts_sha256,
   i.source_hash,i.candidates_hash,i.request_hash,i.input_hash,match.value AS match,
   term.term_id,term.code,term.preferred_label,gn.content_hash AS occupation_content_hash,
   d.decision_id,d.decision,d.actor AS reviewer,d.actor_kind AS reviewer_kind,d.notes AS review_notes,
   CASE WHEN d.decision='ACCEPT' AND d.actor_kind='human' THEN 'HUMAN_REVIEWED'
    WHEN d.decision='ACCEPT' THEN 'ASSISTANT_REVIEWED' ELSE 'UNREVIEWED' END AS review_status
  FROM onet_matching.task t JOIN onet_matching.attempt a USING(task_id)
  JOIN onet_matching.input i USING(task_id,posting_identity)
  CROSS JOIN LATERAL jsonb_array_elements(a.parsed_output->'matches') match
  JOIN classification.term term ON term.release_id=t.release_id AND term.term_kind='OCCUPATION'
   AND term.code=match.value->>'occupation_code'
  JOIN classification.catalog_current current ON current.release_id=t.release_id AND current.database_id=t.database_id
  JOIN classification.graph_load_node gn ON gn.load_id=current.load_id AND gn.node_id=term.term_id
  LEFT JOIN LATERAL (SELECT * FROM onet_matching.candidate_decision d WHERE d.attempt_id=a.attempt_id
    AND d.occupation_code=term.code ORDER BY decision_id DESC LIMIT 1) d ON true
  WHERE t.task_id=id AND a.state='VALIDATED' AND a.parsed_output->>'outcome'='matched'
    AND d.decision IS DISTINCT FROM 'REJECT'
 ), identified AS (
  SELECT *, 'urn:jobtology:inferred-onet-occupation:'||onet_matching.hash(jsonb_build_array(posting_identity,'ONET',release_id,code)) AS edge_id,
   jsonb_build_object('task_id',task_id,'batch_id',batch_id,'attempt_id',attempt_id,'posting_identity',posting_identity,
    'occupation_scheme','ONET','release_id',release_id,'occupation_code',code,'occupation_name',preferred_label,
    'source_id',source_id,'source_run_id',source_run_id,'source_record_id',source_record_id,
    'source_facts_sha256',source_facts_sha256,'source_hash',source_hash,'candidates_hash',candidates_hash,
    'request_hash',request_hash,'input_hash',input_hash,'catalog_hash',catalog_hash,'settings_hash',settings_hash,
    'prompt_hash',settings->>'prompt_hash','retrieval_hash',settings->>'retrieval_hash','model',actual_model,
    'provider',provider,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED','confidence',NULL,
    'confidence_state','UNASSESSED','validation_status','VALIDATED','review_status',review_status,
    'decision_id',decision_id,'reviewer',reviewer,'reviewer_kind',reviewer_kind,'review_notes',review_notes,
    'stage','STAGING','serving_scope','STAGING','accepted',coalesce(decision='ACCEPT',false),'current',false,
    'match_rank',match->'match_rank','rank_basis','SOURCE_DISPLAY_ORDER','reason',match->>'reason',
    'evidence',match->'evidence') AS payload
  FROM selected
 ), projected AS (
  SELECT edge_id,posting_identity,term_id AS occupation_identity,payload::text AS payload_json,
   jsonb_build_object('id',edge_id,'managed_by','jobtology-onet-matching-v1','occupation_scheme','ONET',
    'release_id',release_id,'task_id',task_id,'attempt_id',attempt_id,'batch_id',batch_id,
    'occupation_code',code,'occupation_name',preferred_label,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
    'confidence_state','UNASSESSED','validation_status','VALIDATED','review_status',review_status,
    'stage','STAGING','serving_scope','STAGING','accepted',coalesce(decision='ACCEPT',false),'current',false,
    'source_facts_sha256',source_facts_sha256,'catalog_hash',catalog_hash,'input_hash',input_hash,
    'occupation_content_hash',occupation_content_hash,'match_rank',match->'match_rank',
    'model',actual_model,'prompt_hash',settings->>'prompt_hash','payload_json',payload::text,
    'payload_hash',onet_matching.hash(payload)) AS properties
  FROM identified
 ) SELECT edge_id,posting_identity,occupation_identity,properties,payload_json,onet_matching.hash(properties)
 FROM projected ORDER BY edge_id
$$;

CREATE OR REPLACE FUNCTION onet_matching.begin_graph(id text,token text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET jit=off AS $$
DECLARE t onet_matching.task; publication text:=coalesce(nullif(token,''),gen_random_uuid()::text); digest text; count_rows bigint;
BEGIN
 PERFORM retention.gate(); SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=id;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 IF NOT EXISTS(SELECT 1 FROM onet_matching.freeze WHERE task_id=id) OR
  EXISTS(SELECT 1 FROM onet_matching.attempt WHERE task_id=id AND state='RESERVED')
 THEN RAISE EXCEPTION 'ONET_MATCHING_GRAPH_REQUIRES_FROZEN_SETTLED_INPUT'; END IF;
 IF EXISTS(SELECT 1 FROM onet_matching.source_pin pin LEFT JOIN ingestion.source_graph_projection p USING(run_id)
  WHERE pin.task_id=id AND (p.run_id IS NULL OR p.state<>'READY' OR p.content_sha256 IS DISTINCT FROM pin.content_sha256
   OR p.verified_at IS DISTINCT FROM pin.verified_at)) THEN RAISE EXCEPTION 'ONET_MATCHING_GRAPH_SOURCE_PIN_CHANGED'; END IF;
 IF EXISTS(SELECT 1 FROM onet_matching.attempt a JOIN onet_matching.input i USING(task_id,posting_identity)
  WHERE a.task_id=id AND a.state='VALIDATED' AND (a.cost_usd IS NULL OR a.is_byok IS DISTINCT FROM true
   OR onet_matching.output_issues(a.parsed_output,i.source_fields,i.candidates,(t.settings->>'max_matches')::integer)<>'[]'::jsonb))
 THEN RAISE EXCEPTION 'ONET_MATCHING_GRAPH_INVALID_RESULT'; END IF;
 SELECT count(*),encode(sha256(convert_to(coalesce(string_agg(content_hash,E'\n' ORDER BY edge_id),''),'UTF8')),'hex')
 INTO count_rows,digest FROM onet_matching.graph_rows(id);
 PERFORM retention.enter_writer(publication,'ONET_MATCHING_GRAPH',id);
 INSERT INTO onet_matching.graph_guard(publication_id,task_id,database_id,rows_hash,expected_count,state)
 VALUES(publication,id,t.database_id,digest,count_rows,'PREPARED');
 INSERT INTO onet_matching.graph_edge SELECT publication,g.* FROM onet_matching.graph_rows(id) g;
 RETURN jsonb_build_object('publication_id',publication,'task_id',id,'expected_count',count_rows,'rows_hash',digest);
END $$;
CREATE OR REPLACE FUNCTION onet_matching.check_graph(token text) RETURNS void LANGUAGE plpgsql STABLE SET jit=off AS $$
DECLARE g onet_matching.graph_guard; t onet_matching.task; digest text; current_digest text; n bigint;
BEGIN
 SELECT * INTO STRICT g FROM onet_matching.graph_guard WHERE publication_id=token;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=g.task_id;
 PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);
 IF g.state<>'PREPARED' OR NOT EXISTS(SELECT 1 FROM retention.writer WHERE writer_id=token AND kind='ONET_MATCHING_GRAPH' AND target_id=g.task_id)
 THEN RAISE EXCEPTION 'ONET_MATCHING_GRAPH_LEASE_MISMATCH'; END IF;
 SELECT count(*),encode(sha256(convert_to(coalesce(string_agg(content_hash,E'\n' ORDER BY edge_id),''),'UTF8')),'hex')
 INTO n,digest FROM onet_matching.graph_edge WHERE publication_id=token;
 SELECT encode(sha256(convert_to(coalesce(string_agg(content_hash,E'\n' ORDER BY edge_id),''),'UTF8')),'hex')
 INTO current_digest FROM onet_matching.graph_rows(g.task_id);
 IF (n,digest) IS DISTINCT FROM (g.expected_count,g.rows_hash) OR current_digest IS DISTINCT FROM g.rows_hash
  OR EXISTS(SELECT 1 FROM onet_matching.graph_edge e
  WHERE e.publication_id=token AND e.content_hash<>onet_matching.hash(e.properties))
 THEN RAISE EXCEPTION 'ONET_MATCHING_GRAPH_PLAN_CHANGED'; END IF;
END $$;
CREATE OR REPLACE FUNCTION onet_matching.finish_graph(token text,count_edges bigint) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE g onet_matching.graph_guard; BEGIN
 PERFORM retention.gate(); PERFORM onet_matching.check_graph(token);
 SELECT * INTO STRICT g FROM onet_matching.graph_guard WHERE publication_id=token;
 IF count_edges IS DISTINCT FROM g.expected_count THEN RAISE EXCEPTION 'ONET_MATCHING_GRAPH_COUNT_MISMATCH'; END IF;
 UPDATE onet_matching.graph_guard SET state='VERIFIED',verified_count=count_edges,finished_at=clock_timestamp() WHERE publication_id=token;
 PERFORM retention.leave_writer(token);
 RETURN jsonb_build_object('publication_id',token,'state','VERIFIED','verified_count',count_edges,'rows_hash',g.rows_hash);
END $$;
CREATE OR REPLACE FUNCTION onet_matching.fail_graph(token text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM retention.gate(); UPDATE onet_matching.graph_guard SET state='FAILED',finished_at=clock_timestamp() WHERE publication_id=token AND state='PREPARED';
 IF FOUND THEN PERFORM retention.leave_writer(token); END IF;
END $$;
COMMIT;
