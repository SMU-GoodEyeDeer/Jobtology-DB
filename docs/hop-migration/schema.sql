-- Companion to ../hop-real-data-guide.md. Run on the migration database only.
-- Execute with a SQL workflow action or SQL editor. This DDL does not return rows.
-- For an existing hop_migration schema, follow the guide's rename step first.
-- PostgreSQL 17/18, UTF8. No extensions, existing corpus tables, or public graph writes.
-- Re-running this bootstrap preserves rows; future schema changes need migrations.
BEGIN;
CREATE SCHEMA IF NOT EXISTS ingestion;

CREATE TABLE IF NOT EXISTS ingestion.run (
    run_id text PRIMARY KEY,
    source_id text NOT NULL CHECK (source_id IN (
        'alio_organization', 'job_alio', 'nara_job', 'ncs_career_path',
        'ncs_competency', 'ncs_qualification', 'qnet_schedule')),
    mode text NOT NULL CHECK (mode IN ('SMOKE', 'FULL', 'REPLAY')),
    parser_version text NOT NULL DEFAULT 'hop-normalize-v1',
    policy_revision text NOT NULL,
    state text NOT NULL DEFAULT 'LOADING'
        CHECK (state IN ('LOADING', 'READY', 'REVIEW_REQUIRED', 'FAILED')),
    -- IDs in the original ledger, for an intentional offline comparison.
    reference_connector_run_id text,
    reference_processing_run_id text,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS ingestion.dependency (
    run_id text NOT NULL REFERENCES ingestion.run,
    input_source_id text NOT NULL,
    input_run_id text NOT NULL REFERENCES ingestion.run,
    PRIMARY KEY (run_id, input_source_id),
    CHECK (run_id <> input_run_id)
);

-- Seed every intended partition BEFORE fetching its first page. An absent partition
-- must remain visible as incomplete, including one that will return zero records.
CREATE TABLE IF NOT EXISTS ingestion.partition (
    run_id text NOT NULL REFERENCES ingestion.run,
    partition_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('PAGED', 'DETAIL', 'FILE')),
    request_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    page_size integer NOT NULL CHECK (page_size > 0),
    expected_total integer CHECK (expected_total >= 0),
    PRIMARY KEY (run_id, partition_id),
    CHECK (jsonb_typeof(request_context) = 'object')
);

-- One row per archived HTTP response attempt. page_no=1 is also used for a
-- single detail/file. confirmation_no=1 denotes the SECOND successful empty check.
-- Failed transport attempts with no response file belong in Hop's attempt log;
-- they never count as selected documents or completed partitions.
CREATE TABLE IF NOT EXISTS ingestion.document (
    run_id text NOT NULL,
    document_id text NOT NULL,
    partition_id text NOT NULL,
    page_no integer NOT NULL CHECK (page_no > 0),
    confirmation_no integer NOT NULL DEFAULT 0 CHECK (confirmation_no IN (0, 1)),
    attempt_no integer NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
    raw_path text NOT NULL,
    raw_sha256 text NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    byte_length bigint NOT NULL CHECK (byte_length >= 0),
    encoding text NOT NULL,
    http_status integer NOT NULL,
    provider_result text,
    retrieved_at timestamptz NOT NULL,
    -- For ALIO, retain requested page/size when absent in the response.
    declared_total integer CHECK (declared_total >= 0),
    effective_page integer CHECK (effective_page > 0),
    effective_page_size integer CHECK (effective_page_size > 0),
    item_count integer CHECK (item_count >= 0),
    selected boolean NOT NULL DEFAULT false,
    verified_at timestamptz,
    PRIMARY KEY (run_id, document_id),
    UNIQUE (run_id, partition_id, page_no, confirmation_no, attempt_no),
    FOREIGN KEY (run_id, partition_id) REFERENCES ingestion.partition
);
CREATE UNIQUE INDEX IF NOT EXISTS document_one_selection
    ON ingestion.document (run_id, partition_id, page_no, confirmation_no)
    WHERE selected;

-- Store exactly one source object per row, plus the independently normalized
-- object. Do not concatenate JSON strings by hand. The raw file is byte authority.
-- Keep source_record_id non-unique here so overlapping API pages are detected.
CREATE TABLE IF NOT EXISTS ingestion.record (
    record_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    run_id text NOT NULL,
    document_id text NOT NULL,
    locator text NOT NULL,
    source_record_id text NOT NULL,
    source_payload jsonb NOT NULL CHECK (jsonb_typeof(source_payload) = 'object'),
    normalized jsonb NOT NULL CHECK (jsonb_typeof(normalized) = 'object'),
    field_lineage jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (run_id, document_id, locator),
    FOREIGN KEY (run_id, document_id) REFERENCES ingestion.document,
    CHECK (jsonb_typeof(field_lineage) = 'object'),
    CHECK (jsonb_typeof(quality_flags) = 'array')
);
CREATE INDEX IF NOT EXISTS record_source_identity
    ON ingestion.record (run_id, source_record_id);

CREATE TABLE IF NOT EXISTS ingestion.rejected_row (
    run_id text NOT NULL,
    document_id text NOT NULL,
    locator text NOT NULL,
    error_code text NOT NULL,
    source_payload jsonb NOT NULL,
    PRIMARY KEY (run_id, document_id, locator),
    FOREIGN KEY (run_id, document_id) REFERENCES ingestion.document
);

-- Public-to-this-experiment read interface: incomplete runs are invisible.
CREATE OR REPLACE VIEW ingestion.ready_record AS
SELECT r.*, u.source_id
FROM ingestion.record r
JOIN ingestion.run u USING (run_id)
JOIN ingestion.document d USING (run_id, document_id)
WHERE u.state = 'READY' AND u.mode <> 'SMOKE' AND d.selected;

CREATE OR REPLACE VIEW ingestion.organization AS
SELECT r.run_id, r.document_id, r.locator, n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
    code text, name text, government_code text, organization_type text,
    supervising_organization_code text, website text, address text, established_date date)
WHERE r.source_id = 'alio_organization';

CREATE OR REPLACE VIEW ingestion.competency AS
SELECT r.run_id, r.document_id, r.locator, n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
    code text, name text, definition text, level integer, occupation_code text,
    occupation_name text, classification_names jsonb)
WHERE r.source_id = 'ncs_competency';

CREATE OR REPLACE VIEW ingestion.career_path AS
SELECT r.run_id, r.document_id, r.locator, n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
    occupation_code text, occupation_name text, competency_code text,
    competency_name text, competency_level integer, rank_level integer, rank_name text)
WHERE r.source_id = 'ncs_career_path';

CREATE OR REPLACE VIEW ingestion.qualification_mapping AS
SELECT r.run_id, r.document_id, r.locator, n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
    competency_code text, qualification_code text, qualification_name text,
    standard_version text, unit_type text, minimum_training_hours integer,
    total_training_hours integer, examining_organization text)
WHERE r.source_id = 'ncs_qualification';

CREATE OR REPLACE VIEW ingestion.exam_session AS
SELECT r.run_id, r.document_id, r.locator, n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
    qualification_code text, year integer, round integer, category_code text,
    name text, dates jsonb)
WHERE r.source_id = 'qnet_schedule';

CREATE OR REPLACE VIEW ingestion.posting_representation AS
SELECT r.run_id, r.document_id, r.locator, r.normalized, n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
    posting_id text, representation text, title text, organization_code text,
    organization_name text, date_posted date, closing_date date, ongoing boolean,
    source_url text, recruitment_type text, education text, employment_type text,
    regions text, ncs_category_codes text, ncs_category_names text, headcount integer,
    eligibility_text text, disqualification_text text, preference_text text, selection_text text)
WHERE r.source_id = 'job_alio';

-- 나라일터 publishes one index row and three companion resources per active
-- posting.  Keep the representations separate in the ledger so every API
-- response remains independently auditable, then assemble one posting here.
CREATE OR REPLACE VIEW ingestion.nara_posting_representation AS
SELECT r.run_id, r.document_id, r.locator, r.source_payload, r.normalized, n.*
FROM ingestion.ready_record r
CROSS JOIN LATERAL jsonb_to_record(r.normalized) AS n(
    posting_id text, representation text, title text, organization_name text,
    date_posted date, modified_date date, closing_date date, ongoing boolean,
    source_url text, regions text, recruitment_type text, description_text text,
    positions jsonb, attachment_refs jsonb, source_links jsonb)
WHERE r.source_id = 'nara_job';

CREATE OR REPLACE VIEW ingestion.nara_job_posting AS
WITH representations AS MATERIALIZED (
    SELECT * FROM ingestion.nara_posting_representation
), active_list AS (
    SELECT * FROM representations WHERE representation='list' AND ongoing
)
SELECT l.run_id,l.posting_id,l.document_id AS list_document_id,l.locator AS list_locator,
       d.document_id AS detail_document_id,d.locator AS detail_locator,
       (l.normalized || jsonb_strip_nulls(d.normalized)
        || jsonb_strip_nulls(p.normalized) || jsonb_strip_nulls(f.normalized))
        - 'representation' AS normalized,
       jsonb_build_object(
         'list_document_id',l.document_id,'list_locator',l.locator,
         'detail_document_id',d.document_id,'detail_locator',d.locator,
         'positions_document_id',p.document_id,'files_document_id',f.document_id
       ) AS field_origin
FROM active_list l
JOIN representations d ON d.run_id=l.run_id AND d.posting_id=l.posting_id
 AND d.representation='detail'
JOIN representations p ON p.run_id=l.run_id AND p.posting_id=l.posting_id
 AND p.representation='positions'
JOIN representations f ON f.run_id=l.run_id AND f.posting_id=l.posting_id
 AND f.representation='files';

-- One draft posting per matching list/detail pair. Validation must precede READY.
-- Keep BOTH input locations. Strip nulls from detail so null does not erase list.
CREATE OR REPLACE VIEW ingestion.job_posting AS
WITH postings AS MATERIALIZED (
    -- Parse each JSON object once before pairing list/detail. Otherwise the
    -- planner can repeatedly parse long posting text inside a nested-loop join.
    SELECT * FROM ingestion.posting_representation
)
SELECT l.run_id, l.posting_id,
       l.document_id AS list_document_id, l.locator AS list_locator,
       d.document_id AS detail_document_id, d.locator AS detail_locator,
       (l.normalized || jsonb_strip_nulls(d.normalized)) - 'representation' AS normalized,
       (SELECT jsonb_object_agg(k, CASE WHEN d.normalized->k IS NOT NULL
                           AND d.normalized->k <> 'null'::jsonb THEN 'detail' ELSE 'list' END)
        FROM jsonb_object_keys(l.normalized || d.normalized) AS keys(k)
        WHERE k <> 'representation') AS field_origin
FROM postings l
JOIN postings d
  ON d.run_id = l.run_id AND d.posting_id = l.posting_id
 AND d.representation = 'detail'
WHERE l.representation = 'list';

-- Stable production input for the source-neutral LLM planner.  JOB-ALIO keeps
-- its legacy numeric ID; additional sources receive a collision-proof key.
CREATE OR REPLACE VIEW ingestion.llm_posting AS
SELECT 'job_alio'::text AS source_id,p.run_id,p.posting_id,p.normalized
FROM ingestion.job_posting p
UNION ALL
SELECT 'nara_job',p.run_id,
       'ext-nara_job-'||encode(sha256(convert_to(p.posting_id,'UTF8')),'hex'),
       p.normalized
FROM ingestion.nara_job_posting p;

-- Rebuildable graph projection. Record identities are scoped to this experiment;
-- they are intentionally not the Python loader's content-addressed revision IDs.
CREATE OR REPLACE VIEW ingestion.graph_record AS
SELECT 'hop:' || r.run_id || ':' || r.record_id::text AS id,
       r.run_id, r.record_id, r.source_id, r.source_record_id,
       r.normalized->>'kind' AS kind,
       COALESCE(r.normalized->>'name', r.normalized->>'title',
                r.normalized->>'qualification_name', r.normalized->>'occupation_name') AS name,
       (r.normalized - ARRAY['definition', 'eligibility_text', 'disqualification_text',
          'preference_text', 'selection_text', 'address', 'website', 'source_url'])::text AS facts_json
FROM ingestion.ready_record r;

CREATE OR REPLACE VIEW ingestion.graph_reference AS
SELECT 'hop:' || r.run_id || ':' || r.record_id::text AS record_id, r.run_id,
       ref.namespace || ':' || ref.code AS identity_id, ref.kind, ref.code, ref.field
FROM ingestion.ready_record r
CROSS JOIN LATERAL (
    SELECT 'ncs:occupation' AS namespace, 'Occupation' AS kind,
           r.normalized->>'occupation_code' AS code, 'occupation_code' AS field
    WHERE r.source_id IN ('ncs_career_path', 'ncs_competency')
    UNION ALL
    SELECT 'ncs:unversioned-unit', 'Competency', r.normalized->>'competency_code', 'competency_code'
    WHERE r.source_id = 'ncs_career_path'
    UNION ALL
    SELECT 'ncs:unit', 'Competency', r.normalized->>'code', 'code'
    WHERE r.source_id = 'ncs_competency'
    UNION ALL
    SELECT 'ncs:unit', 'Competency', r.normalized->>'competency_code', 'competency_code'
    WHERE r.source_id = 'ncs_qualification'
    UNION ALL
    SELECT 'qnet:qualification', 'Qualification', r.normalized->>'qualification_code', 'qualification_code'
    WHERE r.source_id IN ('ncs_qualification', 'qnet_schedule')
    UNION ALL
    SELECT 'alio:organization', 'Organization', r.normalized->>'code', 'code'
    WHERE r.source_id = 'alio_organization'
    UNION ALL
    SELECT 'alio:organization', 'Organization', r.normalized->>'organization_code', 'organization_code'
    WHERE r.source_id = 'job_alio'
    UNION ALL
    SELECT 'job-alio:posting', 'JobPosting', r.normalized->>'posting_id', 'posting_id'
    WHERE r.source_id = 'job_alio'
    UNION ALL
    SELECT 'source:posting:nara_job', 'JobPosting',
           encode(sha256(convert_to(r.normalized->>'posting_id','UTF8')),'hex'), 'posting_id'
    WHERE r.source_id = 'nara_job'
) ref
WHERE ref.code IS NOT NULL;
COMMIT;
