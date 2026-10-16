-- Batch-free publication only. No model planning, frozen history or spend changes.
-- Requires graph/sql/002_batchfree_source_graph.sql at publication time.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_graph_rows(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql STABLE AS $$
 SELECT s.posting_id,'source:posting:jobkorea:'||enrichment.hash(ib.manifest#>>'{document,source_record_id}'),
  'ncs:occupation:'||c.occupation_code,c.candidate_id,
  jsonb_build_object('result_id',r.result_id,'candidate_id',c.candidate_id,'occupation_code',c.occupation_code,
   'occupation_name',cat.occupation_name,'job_run_id',jobs,'ncs_run_id',ncs,
   'bundle_id',binding.bundle_id,'source_hash',binding.source_hash,'binding_hash',binding.binding_hash,
   'catalog_hash',cat.catalog_hash,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
   'item_id',i.item_id,'batch_id',i.batch_id,'attempt_id',r.attempt_id,
   'model',coalesce(a.actual_model,b.settings->>'categorize_model'),
   'prompt_version',b.settings->>'prompt_version','actor',r.actor,
   'confidence',NULL,'confidence_state','UNASSESSED','reason',c.reason,'evidence',c.evidence,
   'validation_status','VALIDATED','stage','STAGING','accepted',coalesce(d.decision='ACCEPT',false),
   'review_status',CASE WHEN d.decision='ACCEPT' AND d.reviewer_kind='human' THEN 'HUMAN_REVIEWED'
     WHEN d.decision='ACCEPT' THEN 'ASSISTANT_REVIEWED' ELSE 'UNREVIEWED' END,
   'decision_id',d.decision_id,'reviewer',d.reviewer,'reviewer_kind',d.reviewer_kind,'review_notes',d.notes)
 FROM enrichment.metadata_occupation_status(jobs,ncs) s
 JOIN enrichment.metadata_occupation_result r ON r.result_id=s.result_id
 JOIN enrichment.metadata_occupation_binding binding ON binding.item_id=s.item_id
 JOIN enrichment.item i ON i.item_id=binding.item_id
 JOIN enrichment.batch b ON b.batch_id=i.batch_id
 JOIN enrichment.attempt a ON a.attempt_id=r.attempt_id
 JOIN enrichment.input_bundle ib ON ib.bundle_id=binding.bundle_id
 JOIN enrichment.metadata_occupation_candidate c ON c.result_id=r.result_id
 JOIN enrichment.metadata_occupation_catalog cat ON cat.ncs_run_id=c.ncs_run_id AND cat.occupation_code=c.occupation_code
 LEFT JOIN LATERAL (SELECT d.* FROM enrichment.metadata_occupation_decision d WHERE d.result_id=r.result_id ORDER BY decision_id DESC LIMIT 1) d ON true
 WHERE r.output->>'outcome'='matched' AND d.decision IS DISTINCT FROM 'REJECT'
  AND (d.decision='ACCEPT' OR include_unreviewed)
  AND EXISTS(SELECT 1 FROM ingestion.run WHERE source_id='jobkorea' AND run_id=jobs AND state='READY')
  AND EXISTS(SELECT 1 FROM ingestion.run WHERE source_id='ncs_competency' AND run_id=ncs AND state='READY')
$$;

CREATE OR REPLACE FUNCTION enrichment.check_metadata_occupation_source_graphs(jobs text,ncs text,include_unreviewed boolean)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE row record; BEGIN
 PERFORM ingestion.assert_source_graph_projection(jobs);
 PERFORM ingestion.assert_source_graph_projection(ncs);
 IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=jobs AND source_id='jobkorea' AND state='READY')
  OR NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=ncs AND source_id='ncs_competency' AND state='READY')
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_REQUIRES_EXACT_SOURCE_GRAPHS'; END IF;
 -- Compare the frozen catalogue to its historical source, never the latest pin.
 IF EXISTS(SELECT 1 FROM enrichment.metadata_occupation_catalog c LEFT JOIN (
   SELECT normalized->>'occupation_code' AS code,
    enrichment.hash(jsonb_agg(normalized ORDER BY normalized->>'code')::text) AS hash
   FROM ingestion.ready_record WHERE run_id=ncs AND source_id='ncs_competency'
   GROUP BY normalized->>'occupation_code') source ON source.code=c.occupation_code
   WHERE c.ncs_run_id=ncs AND c.catalog_hash IS DISTINCT FROM source.hash)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_CATALOG_CHANGED'; END IF;
 FOR row IN SELECT DISTINCT payload->>'item_id' AS item_id
  FROM enrichment.metadata_occupation_graph_rows(jobs,ncs,include_unreviewed) LOOP
  PERFORM enrichment.verify_item_input(row.item_id);
 END LOOP;
 IF EXISTS(SELECT 1 FROM enrichment.metadata_occupation_graph_rows(jobs,ncs,include_unreviewed) g
  JOIN enrichment.metadata_occupation_binding b ON b.item_id=g.payload->>'item_id'
  JOIN enrichment.item i USING(item_id)
  JOIN enrichment.input_bundle ib ON ib.bundle_id=b.bundle_id
  WHERE b.job_run_id IS DISTINCT FROM jobs OR b.ncs_run_id IS DISTINCT FROM ncs
   OR b.source_hash IS DISTINCT FROM i.source_hash OR b.source_hash IS DISTINCT FROM ib.source_hash
   OR b.metadata_hash IS DISTINCT FROM enrichment.hash(enrichment.metadata_occupation_fields(i.source_data)::text)
   OR b.candidates_hash IS DISTINCT FROM enrichment.hash(b.candidates::text)
   OR b.binding_hash IS DISTINCT FROM enrichment.hash(jsonb_build_array('metadata-occupation-binding-v1',
    jobs,ncs,b.bundle_id,b.source_hash,b.metadata_hash,b.candidates_hash)::text)
   OR NOT EXISTS(SELECT 1 FROM ingestion.source_graph_membership m
    WHERE m.run_id=jobs AND m.identity_id=g.posting_identity AND m.kind='JobPosting')
   OR NOT EXISTS(SELECT 1 FROM ingestion.source_graph_membership m
    WHERE m.run_id=ncs AND m.identity_id=g.occupation_identity AND m.kind='Occupation'
     AND m.code=g.payload->>'occupation_code'))
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_PINNED_EVIDENCE_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION enrichment.begin_metadata_occupation_graph(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE token text:=gen_random_uuid()::text; BEGIN
 PERFORM retention.gate();
 IF EXISTS(SELECT 1 FROM retention.writer WHERE writer_id='metadata-occupation-graph')
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_ALREADY_ACTIVE'; END IF;
 PERFORM enrichment.check_metadata_occupation_source_graphs(jobs,ncs,include_unreviewed);
 PERFORM retention.enter_writer('metadata-occupation-graph','METADATA_OCCUPATION_GRAPH',token);
 INSERT INTO enrichment.metadata_occupation_graph_guard(writer_token,job_run_id,ncs_run_id,include_unreviewed,rows_hash,state)
 VALUES(token,jobs,ncs,include_unreviewed,enrichment.metadata_occupation_graph_hash(jobs,ncs,include_unreviewed),'PREPARED');
 RETURN token;
END $$;

CREATE OR REPLACE FUNCTION enrichment.check_metadata_occupation_graph(token text)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE guard enrichment.metadata_occupation_graph_guard%ROWTYPE; BEGIN
 SELECT * INTO STRICT guard FROM enrichment.metadata_occupation_graph_guard WHERE writer_token=token;
 IF guard.state<>'PREPARED' OR NOT EXISTS(SELECT 1 FROM retention.writer
   WHERE writer_id='metadata-occupation-graph' AND kind='METADATA_OCCUPATION_GRAPH' AND target_id=token)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_LEASE_MISMATCH'; END IF;
 PERFORM enrichment.check_metadata_occupation_source_graphs(guard.job_run_id,guard.ncs_run_id,guard.include_unreviewed);
 IF guard.rows_hash<>enrichment.metadata_occupation_graph_hash(guard.job_run_id,guard.ncs_run_id,guard.include_unreviewed)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_GRAPH_SOURCE_OR_REVIEW_CHANGED'; END IF;
END $$;
COMMIT;
