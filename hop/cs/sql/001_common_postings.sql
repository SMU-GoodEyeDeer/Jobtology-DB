-- Additive source interface. Install after ingestion, enrichment and link-publication SQL.
-- ALIO posting IDs and source/content hashes remain exactly as previously reviewed.
BEGIN;
CREATE SCHEMA IF NOT EXISTS cs;

CREATE OR REPLACE FUNCTION cs.external_posting_key(source_id text, source_posting_id text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT 'ext-'||source_id||'-'||enrichment.hash(source_posting_id)
$$;

CREATE OR REPLACE FUNCTION cs.external_posting_identity(source_id text, source_posting_id text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT 'source:posting:'||source_id||':'||enrichment.hash(source_posting_id)
$$;

-- Additional providers can be staged here without changing the fixed source enum
-- of the existing ingestion ledger. Only READY snapshots are visible to readers.
CREATE TABLE IF NOT EXISTS cs.source_snapshot (
 source_id text NOT NULL CHECK (source_id ~ '^[a-z][a-z0-9_-]{1,31}$' AND source_id <> 'job_alio'),
 snapshot_run_id text NOT NULL,
 state text NOT NULL DEFAULT 'LOADING' CHECK (state IN ('LOADING','READY','FAILED')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 completed_at timestamptz,
 PRIMARY KEY (source_id,snapshot_run_id),
 CHECK ((state='READY')=(completed_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS cs.posting_input (
 source_id text NOT NULL,
 snapshot_run_id text NOT NULL,
 source_posting_id text NOT NULL CHECK (length(source_posting_id) BETWEEN 1 AND 512),
 employer text,
 title text NOT NULL CHECK (length(btrim(title))>0),
 categories jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(categories) IN ('object','array')),
 normalized jsonb NOT NULL CHECK (jsonb_typeof(normalized)='object'),
 source_data jsonb NOT NULL CHECK (jsonb_typeof(source_data)='object'),
 attachment_refs jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(attachment_refs)='array'),
 evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence)='object'),
 PRIMARY KEY (source_id,snapshot_run_id,source_posting_id),
 FOREIGN KEY (source_id,snapshot_run_id) REFERENCES cs.source_snapshot
);

-- This view includes every READY snapshot. Consumers pin snapshot_run_id; they
-- must not mistake historical rows for the current corpus. The ALIO adapter uses
-- the original input whitelist and link hash (including prepared attachments).
CREATE OR REPLACE VIEW cs.common_posting AS
SELECT 'job_alio'::text AS source_id,
 p.posting_id AS source_posting_id,
 p.posting_id AS posting_id,
 'job-alio:posting:'||p.posting_id AS posting_identity,
 p.run_id AS snapshot_run_id,
 p.normalized->>'organization_name' AS employer,
 p.normalized->>'title' AS title,
 jsonb_build_object('ncs_category_codes',p.normalized->>'ncs_category_codes',
                    'ncs_category_names',p.normalized->>'ncs_category_names') AS categories,
 p.normalized,
 enrichment.source_fields(p.normalized) AS source_data,
 enrichment.hash(enrichment.source_fields(p.normalized)::text) AS inline_source_hash,
 enrichment.linking_input_hash(p.run_id,p.posting_id) AS content_hash,
 coalesce(d.source_payload->'files','[]'::jsonb) AS attachment_refs,
 jsonb_build_object('list_document_id',p.list_document_id,'list_locator',p.list_locator,
                    'detail_document_id',p.detail_document_id,'detail_locator',p.detail_locator,
                    'field_origin',p.field_origin) AS evidence
FROM ingestion.job_posting p
JOIN ingestion.run r ON r.run_id=p.run_id AND r.source_id='job_alio'
 AND r.state='READY' AND r.mode<>'SMOKE'
LEFT JOIN ingestion.ready_record d ON d.run_id=p.run_id
 AND d.source_record_id=p.posting_id||':detail' AND d.source_id='job_alio'
UNION ALL
SELECT 'nara_job'::text AS source_id,
 p.posting_id AS source_posting_id,
 cs.external_posting_key('nara_job',p.posting_id) AS posting_id,
 cs.external_posting_identity('nara_job',p.posting_id) AS posting_identity,
 p.run_id AS snapshot_run_id,
 p.normalized->>'organization_name' AS employer,
 p.normalized->>'title' AS title,
 jsonb_build_object('posting_type_code',p.normalized->>'posting_type_code',
                    'institution_type_code',p.normalized->>'institution_type_code') AS categories,
 p.normalized,
 enrichment.source_fields(p.normalized) AS source_data,
 enrichment.hash(enrichment.source_fields(p.normalized)::text) AS inline_source_hash,
 enrichment.hash(enrichment.source_fields(p.normalized)::text) AS content_hash,
 coalesce(p.normalized->'attachment_refs','[]'::jsonb) AS attachment_refs,
 p.field_origin AS evidence
FROM ingestion.nara_job_posting p
JOIN ingestion.run r ON r.run_id=p.run_id AND r.source_id='nara_job'
 AND r.state='READY' AND r.mode<>'SMOKE'
UNION ALL
SELECT i.source_id,
 i.source_posting_id,
 cs.external_posting_key(i.source_id,i.source_posting_id) AS posting_id,
 cs.external_posting_identity(i.source_id,i.source_posting_id) AS posting_identity,
 i.snapshot_run_id,
 i.employer,
 i.title,
 i.categories,
 i.normalized,
 i.source_data,
 enrichment.hash(i.source_data::text) AS inline_source_hash,
 enrichment.hash(i.source_data::text) AS content_hash,
 i.attachment_refs,
 i.evidence
FROM cs.posting_input i JOIN cs.source_snapshot s
 USING (source_id,snapshot_run_id) WHERE s.state='READY';

COMMENT ON VIEW cs.common_posting IS
'Source-independent posting read interface. ALIO identifiers and hashes are legacy-compatible; additional providers use source-qualified identities. Pin snapshot_run_id for analysis.';

-- A compatibility bridge for saved work. It resolves source-qualified identity
-- and current content to existing ENRICH items/revisions without copying or
-- changing their IDs, source hashes, reviewer attribution or producing model.
-- Additional providers are selectable for scope analysis. The existing
-- enrichment.plan_batch and link publication paths still require ALIO snapshots;
-- generic rows have no work lineage until those consumers gain source adapters.
CREATE OR REPLACE VIEW cs.posting_work_lineage AS
SELECT p.source_id,p.source_posting_id,p.posting_id,p.posting_identity,
 p.snapshot_run_id,p.content_hash,
 work.batch_id,work.item_id,work.extraction_id,work.revision_id,
 work.revision_no,work.review_decision,work.reviewer_kind
FROM cs.common_posting p
LEFT JOIN LATERAL (
 SELECT i.batch_id,i.item_id,i.extraction_id,
  r.revision_id,r.revision_no,r.decision AS review_decision,r.reviewer_kind
 FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
 LEFT JOIN enrichment.extraction_review_state r USING(item_id)
 WHERE b.job_run_id=p.snapshot_run_id AND b.mode='ENRICH'
  AND i.posting_id=p.posting_id AND i.source_hash=p.content_hash
) work ON true;

COMMENT ON VIEW cs.posting_work_lineage IS
'Existing extraction/review lineage under the common identity. A NULL item_id means there is no exact content-hash match; it does not prove the source was never processed historically.';
COMMIT;
