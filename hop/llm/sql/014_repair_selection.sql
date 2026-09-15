-- Operational selection guard; no immutable prompt/validation contract changes.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.repair_reasons_v6(old_id text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE i enrichment.item%ROWTYPE; a enrichment.attempt%ROWTYPE; b enrichment.batch%ROWTYPE;
 audit enrichment.extraction_audit%ROWTYPE; decision text; notes text; errors jsonb:='[]'; audited_version text; latest_item text;
BEGIN
 SELECT * INTO STRICT i FROM enrichment.item WHERE item_id=old_id;
 SELECT * INTO a FROM enrichment.attempt WHERE attempt_id=i.extraction_id;
 IF NOT FOUND OR a.state IN ('RESERVED','SKIPPED') THEN RETURN NULL; END IF;
 IF i.source_hash IS DISTINCT FROM enrichment.hash(i.source_data::text) THEN RAISE EXCEPTION 'REPAIR_SOURCE_HASH_MISMATCH'; END IF;
 SELECT * INTO STRICT b FROM enrichment.batch WHERE batch_id=i.batch_id;
 -- Revisions across repair batches supersede older items for the same content.
 -- Evaluation dataset/mode boundaries remain independent.
 SELECT r.item_id INTO latest_item FROM enrichment.extraction_revision r
 JOIN enrichment.item ri USING(item_id) JOIN enrichment.batch rb USING(batch_id)
 WHERE ri.posting_id=i.posting_id AND ri.source_hash=i.source_hash AND ri.source_data=i.source_data
  AND rb.mode=b.mode AND rb.dataset_id IS NOT DISTINCT FROM b.dataset_id
 ORDER BY r.revision_no DESC LIMIT 1;
 IF latest_item IS NOT NULL AND latest_item<>old_id THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM enrichment.item other JOIN enrichment.batch ob USING(batch_id)
  JOIN enrichment.attempt oa ON oa.attempt_id=other.extraction_id
  WHERE other.item_id<>old_id AND other.posting_id=i.posting_id AND other.source_hash=i.source_hash AND other.source_data=i.source_data
   AND ob.mode=b.mode AND ob.dataset_id IS NOT DISTINCT FROM b.dataset_id AND oa.state='RESERVED')
 THEN RETURN NULL; END IF;
 SELECT d.decision,d.notes INTO decision,notes FROM enrichment.extraction_revision r
 LEFT JOIN enrichment.latest_extraction_decision d USING(revision_id) WHERE r.item_id=old_id ORDER BY revision_no DESC LIMIT 1;
 IF FOUND THEN
  IF decision IS DISTINCT FROM 'REJECT' THEN RETURN NULL; END IF;
  errors:=jsonb_build_array('INDEPENDENT_EXTRACTION_REJECTED',notes);
 END IF;
 audited_version:=CASE WHEN b.settings->>'prompt_version' IN ('ko-v4','ko-v5') THEN 'ko-v5' ELSE b.settings->>'prompt_version' END;
 SELECT * INTO audit FROM enrichment.extraction_audit WHERE attempt_id=a.attempt_id AND validator_version=audited_version;
 IF FOUND THEN
  IF audit.raw_output_hash IS DISTINCT FROM enrichment.hash(coalesce(a.raw_output::text,'null')) OR audit.source_hash IS DISTINCT FROM i.source_hash
  THEN RAISE EXCEPTION 'REPAIR_AUDIT_INPUT_CHANGED'; END IF;
  errors:=errors||audit.issues;
  RETURN CASE WHEN errors<>'[]' THEN errors END;
 END IF;
 IF a.state IN ('REJECTED','ERROR','BUDGET_BLOCKED','PLANNED') THEN
  errors:=errors||CASE WHEN a.issues='[]' THEN jsonb_build_array('PRIOR_EXTRACTION_'||a.state) ELSE a.issues END;
 END IF;
 RETURN CASE WHEN errors<>'[]' THEN errors END;
END $$;
COMMIT;
