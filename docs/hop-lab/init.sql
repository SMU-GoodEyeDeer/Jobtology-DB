-- Deliberately separate from the application's canonical/staging schemas.
-- These are mutable learning tables, not the production evidence ledger.
CREATE SCHEMA IF NOT EXISTS hop_lab;

CREATE TABLE IF NOT EXISTS hop_lab.organization (
    source_id text NOT NULL,
    organization_code text NOT NULL,
    organization_name text NOT NULL,
    organization_type text,
    website text,
    established_date date,
    PRIMARY KEY (source_id, organization_code)
);

CREATE TABLE IF NOT EXISTS hop_lab.rejected_organization (
    rejected_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_code text,
    organization_name text,
    error_description text,
    rejected_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
