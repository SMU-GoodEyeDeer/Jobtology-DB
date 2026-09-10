"""Resumable canonical assembly manifests and structured exam sessions."""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_canonical_assembly"
down_revision: str | None = "0005_canonical_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    statements = """
    ALTER TABLE canonical.entity DROP CONSTRAINT entity_kind_check;
    ALTER TABLE canonical.entity ADD CONSTRAINT entity_kind_check CHECK (kind IN (
        'ConceptScheme','Occupation','NCSClass','NCSCompetencyUnit','Skill','Credential',
        'Organization','JobPosting','ExamSession'));
    CREATE TABLE control.canonical_run (
        assembly_run_id TEXT PRIMARY KEY,
        processing_run_id TEXT NOT NULL REFERENCES control.processing_run,
        assembler_version TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('RUNNING','READY','FAILED')),
        started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        error_code TEXT,
        summary JSONB,
        UNIQUE(processing_run_id,assembler_version)
    );
    CREATE TABLE canonical.assembly_item (
        assembly_run_id TEXT NOT NULL REFERENCES control.canonical_run,
        item_id TEXT NOT NULL,
        bundle_hash TEXT NOT NULL,
        PRIMARY KEY(assembly_run_id,item_id)
    );
    CREATE TABLE canonical.assembly_input (
        assembly_run_id TEXT NOT NULL REFERENCES control.canonical_run,
        staging_revision_id TEXT NOT NULL REFERENCES staging.record_revision(revision_id),
        document_id TEXT NOT NULL REFERENCES grounding.document,
        PRIMARY KEY(assembly_run_id,staging_revision_id,document_id)
    );
    CREATE TABLE canonical.assembly_revision (
        assembly_run_id TEXT NOT NULL REFERENCES control.canonical_run,
        revision_id TEXT NOT NULL REFERENCES canonical.revision,
        PRIMARY KEY(assembly_run_id,revision_id)
    )
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "canonical.assembly_revision",
        "canonical.assembly_input",
        "canonical.assembly_item",
        "control.canonical_run",
    ):
        op.execute(f"DROP TABLE {table}")
    # Do not silently discard exam data during a downgrade.
    op.execute("ALTER TABLE canonical.entity DROP CONSTRAINT entity_kind_check")
    op.execute("""ALTER TABLE canonical.entity ADD CONSTRAINT entity_kind_check CHECK (kind IN (
        'ConceptScheme','Occupation','NCSClass','NCSCompetencyUnit','Skill','Credential',
        'Organization','JobPosting'))""")
