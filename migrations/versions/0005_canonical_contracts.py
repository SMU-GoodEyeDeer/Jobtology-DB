"""Canonical corpus contracts and grounding; private Person state stays in jobtology_app."""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_canonical_contracts"
down_revision: str | None = "0004_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    statements = """
    CREATE SCHEMA canonical;
    CREATE SCHEMA grounding;
    REVOKE ALL ON SCHEMA canonical, grounding FROM PUBLIC;
    CREATE TABLE grounding.document (
        document_id TEXT PRIMARY KEY,
        snapshot_id VARCHAR(128) NOT NULL REFERENCES raw_manifest.source_snapshot,
        source_id TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX ix_document_source ON grounding.document(source_id,source_record_id);
    CREATE TABLE grounding.document_observation (
        document_id TEXT NOT NULL REFERENCES grounding.document,
        observation_id VARCHAR(128) NOT NULL REFERENCES raw_manifest.fetch_observation,
        PRIMARY KEY(document_id,observation_id)
    );
    CREATE TABLE grounding.text_block (
        document_id TEXT NOT NULL REFERENCES grounding.document,
        block_id TEXT NOT NULL,
        locator TEXT NOT NULL,
        text TEXT NOT NULL,
        sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        PRIMARY KEY(document_id,block_id)
    );
    CREATE INDEX ix_text_block_search ON grounding.text_block
        USING GIN (to_tsvector('simple', text));
    CREATE TABLE grounding.evidence_span (
        evidence_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
        end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
        excerpt TEXT NOT NULL,
        record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
        CHECK (char_length(excerpt) = end_offset-start_offset),
        FOREIGN KEY(document_id,block_id) REFERENCES grounding.text_block
    );
    CREATE TABLE canonical.entity (
        entity_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('ConceptScheme','Occupation','NCSClass',
            'NCSCompetencyUnit','Skill','Credential','Organization','JobPosting')),
        namespace TEXT NOT NULL,
        source_key TEXT NOT NULL,
        record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
        UNIQUE(namespace,source_key),
        UNIQUE(entity_id,kind)
    );
    CREATE TABLE canonical.revision (
        revision_id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        display_name TEXT,
        record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(entity_id,kind) REFERENCES canonical.entity(entity_id,kind)
    );
    CREATE INDEX ix_canonical_revision_entity ON canonical.revision(entity_id,created_at);
    CREATE INDEX ix_canonical_revision_name ON canonical.revision(kind,display_name);
    CREATE INDEX ix_canonical_revision_payload ON canonical.revision
        USING GIN(record jsonb_path_ops);
    CREATE TABLE canonical.revision_document (
        revision_id TEXT NOT NULL REFERENCES canonical.revision,
        document_id TEXT NOT NULL REFERENCES grounding.document,
        PRIMARY KEY(revision_id,document_id)
    );
    CREATE TABLE canonical.field_evidence (
        revision_id TEXT NOT NULL REFERENCES canonical.revision,
        field TEXT NOT NULL,
        evidence_id TEXT NOT NULL REFERENCES grounding.evidence_span,
        PRIMARY KEY(revision_id,field,evidence_id)
    );
    CREATE TABLE grounding.extraction (
        extraction_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES grounding.document,
        record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE grounding.requirement_claim (
        claim_id TEXT PRIMARY KEY,
        subject_revision_id TEXT NOT NULL REFERENCES canonical.revision,
        extraction_id TEXT NOT NULL REFERENCES grounding.extraction,
        kind TEXT NOT NULL,
        review_status TEXT NOT NULL CHECK (review_status IN
            ('PENDING','AUTO_ACCEPTED','HUMAN_ACCEPTED','REJECTED')),
        record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX ix_claim_subject ON grounding.requirement_claim(subject_revision_id,review_status);
    CREATE INDEX ix_claim_condition ON grounding.requirement_claim USING GIN(record jsonb_path_ops);
    CREATE TABLE grounding.claim_evidence (
        claim_id TEXT NOT NULL REFERENCES grounding.requirement_claim,
        evidence_id TEXT NOT NULL REFERENCES grounding.evidence_span,
        PRIMARY KEY(claim_id,evidence_id)
    )
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "grounding.claim_evidence",
        "grounding.requirement_claim",
        "grounding.extraction",
        "canonical.field_evidence",
        "canonical.revision_document",
        "canonical.revision",
        "canonical.entity",
        "grounding.evidence_span",
        "grounding.text_block",
        "grounding.document_observation",
        "grounding.document",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP SCHEMA grounding")
    op.execute("DROP SCHEMA canonical")
