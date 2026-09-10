"""Checkpointed processing, immutable staging revisions, and scheduler state."""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_processing"
down_revision: str | None = "0003_rights_policy_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    statements = """
    CREATE SCHEMA staging;
    CREATE SCHEMA quality;
    CREATE TABLE control.processing_run (
        processing_run_id TEXT PRIMARY KEY,
        connector_run_id VARCHAR(128) NOT NULL REFERENCES control.connector_run,
        processor_version TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('RUNNING','READY','REVIEW_REQUIRED','FAILED')),
        attempts INTEGER NOT NULL DEFAULT 1,
        started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        error_code TEXT,
        summary JSONB,
        UNIQUE (connector_run_id, processor_version)
    );
    CREATE TABLE staging.document (
        document_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        snapshot_id VARCHAR(128) NOT NULL REFERENCES raw_manifest.source_snapshot,
        partition_id TEXT NOT NULL,
        processor_version TEXT NOT NULL,
        metadata JSONB NOT NULL,
        UNIQUE (snapshot_id, partition_id, processor_version)
    );
    CREATE TABLE staging.record_revision (
        revision_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        processor_version TEXT NOT NULL,
        record JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX ix_record_source_identity ON staging.record_revision(source_id, source_record_id);
    CREATE TABLE staging.document_record (
        document_id TEXT NOT NULL REFERENCES staging.document,
        locator TEXT NOT NULL,
        revision_id TEXT NOT NULL REFERENCES staging.record_revision,
        PRIMARY KEY (document_id, locator)
    );
    CREATE TABLE quality.rejected_row (
        document_id TEXT NOT NULL REFERENCES staging.document,
        locator TEXT NOT NULL,
        error_code TEXT NOT NULL,
        source_payload JSONB NOT NULL,
        PRIMARY KEY (document_id, locator)
    );
    CREATE TABLE control.processing_input (
        processing_run_id TEXT NOT NULL REFERENCES control.processing_run,
        observation_id VARCHAR(128) NOT NULL REFERENCES raw_manifest.fetch_observation,
        document_id TEXT NOT NULL REFERENCES staging.document,
        PRIMARY KEY (processing_run_id, observation_id)
    );
    CREATE INDEX ix_processing_run_connector ON control.processing_run(connector_run_id);
    CREATE TABLE control.source_sync (
        source_id TEXT PRIMARY KEY,
        last_attempt_at TIMESTAMPTZ,
        last_success_at TIMESTAMPTZ,
        next_due_at TIMESTAMPTZ,
        connector_run_id VARCHAR(128) REFERENCES control.connector_run,
        processing_run_id TEXT REFERENCES control.processing_run,
        configuration_hash TEXT,
        content_set_hash TEXT,
        normalized_set_hash TEXT,
        state TEXT NOT NULL CHECK (state IN ('RUNNING','READY','FAILED')),
        error_code TEXT
    );
    CREATE TABLE control.graph_load (
        processing_run_id TEXT NOT NULL REFERENCES control.processing_run,
        target_hash TEXT NOT NULL,
        loader_version TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('RUNNING','READY','FAILED')),
        completed_at TIMESTAMPTZ,
        PRIMARY KEY (processing_run_id, target_hash, loader_version)
    )
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "control.graph_load",
        "control.source_sync",
        "control.processing_input",
        "quality.rejected_row",
        "staging.document_record",
        "staging.record_revision",
        "staging.document",
        "control.processing_run",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP SCHEMA quality")
    op.execute("DROP SCHEMA staging")
