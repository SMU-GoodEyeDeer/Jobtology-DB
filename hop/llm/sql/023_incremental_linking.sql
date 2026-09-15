-- Read-only selection; paid execution remains an explicit workflow parameter.
BEGIN;
CREATE OR REPLACE FUNCTION enrichment.changed_linking_inputs(cap integer,retry_failed boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE jobs text;ncs text;rows jsonb;ids text;bundles text;count_rows integer;remaining integer; BEGIN
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_INCREMENTAL_CAP'; END IF;
 SELECT run_id INTO jobs FROM ingestion.latest_ready_run WHERE source_id='job_alio';
 SELECT run_id INTO ncs FROM ingestion.latest_ready_run WHERE source_id='ncs_competency';
 IF jobs IS NULL OR ncs IS NULL THEN RAISE EXCEPTION 'READY_SOURCES_REQUIRED'; END IF;
 -- Require prepared documents whenever the selected input contains attachments.
 -- Mixing inline-only and document inputs is allowed by creating an empty-document
 -- bundle for postings with no eligible files in the common preparation workflow.
 SELECT jsonb_agg(to_jsonb(c) ORDER BY posting_id) INTO rows FROM (
  SELECT s.posting_id,s.source_hash,b.bundle_id FROM enrichment.linking_status s
  LEFT JOIN LATERAL (SELECT bundle_id FROM enrichment.input_bundle b
    WHERE b.job_run_id=jobs AND b.posting_id=s.posting_id AND b.source_hash=s.source_hash
    ORDER BY b.created_at DESC,b.bundle_id DESC LIMIT 1) b ON true
  WHERE (s.outcome='PENDING_EXTRACTION' OR (retry_failed AND s.outcome='EXTRACTION_FAILED'))
  AND b.bundle_id IS NOT NULL
  AND NOT EXISTS(SELECT 1 FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
    JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.posting_id=s.posting_id AND i.source_hash=s.source_hash
    AND b.mode='ENRICH' AND a.state='VALIDATED' AND b.settings->>'prompt_version'='ko-link-v1')
  ORDER BY s.posting_id LIMIT cap) c;
 SELECT count(*)::integer,string_agg(v->>'posting_id','|' ORDER BY v->>'posting_id'),
 string_agg(v->>'bundle_id','|' ORDER BY v->>'posting_id') INTO count_rows,ids,bundles FROM jsonb_array_elements(coalesce(rows,'[]')) v;
 SELECT count(*) INTO remaining FROM enrichment.linking_status WHERE outcome IN ('PENDING_EXTRACTION','EXTRACTION_FAILED');
 RETURN jsonb_build_object('job_run_id',jobs,'ncs_run_id',ncs,'posting_ids',coalesce(ids,''),
 'bundle_ids',coalesce(bundles,''),'selected',count_rows,'pending_or_failed_total',remaining,
 'run_needed',CASE WHEN count_rows>0 THEN 'Y' ELSE 'N' END);
END $$;
COMMIT;

CREATE OR REPLACE FUNCTION enrichment.valid_request_workers(n integer) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN
 IF n IS NULL OR n NOT BETWEEN 1 AND 4 THEN RAISE EXCEPTION 'REQUEST_WORKERS_MUST_BE_1_TO_4'; END IF;
 RETURN true;
END $$;
