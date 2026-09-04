"""Create the immutable fetch ledger.

Revision ID: 0001_fetch_ledger
Revises:
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0001_fetch_ledger"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema("control"))
    op.execute(sa.schema.CreateSchema("raw_manifest"))

    op.create_table(
        "connector_run",
        sa.Column("connector_run_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("connector_version", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetch_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_key_count", sa.Integer(), nullable=True),
        sa.Column("discovered_manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("planned_request_count", sa.Integer(), nullable=True),
        sa.Column("successful_request_count", sa.Integer(), nullable=True),
        sa.Column("pagination_terminal_marker", sa.Text(), nullable=True),
        sa.Column("all_attempt_observation_set_hash", sa.String(length=64), nullable=True),
        sa.Column("selected_success_observation_set_hash", sa.String(length=64), nullable=True),
        sa.Column("validation_report_id", sa.String(length=128), nullable=True),
        sa.Column("validation_report_hash", sa.String(length=64), nullable=True),
        sa.Column("source_count_override_id", sa.String(length=128), nullable=True),
        sa.Column("source_count_override_hash", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "mode IN ('SCHEDULED_FULL', 'BACKFILL')",
            name="ck_connector_run_mode",
        ),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'REVIEW_REQUIRED', 'SUCCEEDED', 'FAILED')",
            name="ck_connector_run_state",
        ),
        sa.CheckConstraint(
            "discovered_key_count IS NULL OR discovered_key_count >= 0",
            name="ck_connector_run_discovered_count_nonnegative",
        ),
        sa.CheckConstraint(
            "planned_request_count IS NULL OR planned_request_count >= 0",
            name="ck_connector_run_planned_count_nonnegative",
        ),
        sa.CheckConstraint(
            "successful_request_count IS NULL OR successful_request_count >= 0",
            name="ck_connector_run_successful_count_nonnegative",
        ),
        sa.CheckConstraint(
            "planned_request_count IS NULL OR successful_request_count IS NULL "
            "OR successful_request_count <= planned_request_count",
            name="ck_connector_run_successful_not_above_planned",
        ),
        sa.PrimaryKeyConstraint("connector_run_id", name="pk_connector_run"),
        schema="control",
    )
    op.create_index(
        "ix_connector_run_run_id",
        "connector_run",
        ["run_id"],
        schema="control",
    )
    op.create_index(
        "ix_connector_run_source_state_started",
        "connector_run",
        ["source_id", "state", "started_at"],
        schema="control",
    )

    op.create_table(
        "connector_request",
        sa.Column("connector_run_id", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("partition_id", sa.String(length=128), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("request_url_redacted", sa.Text(), nullable=False),
        sa.Column("selected_observation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "planned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number >= 0",
            name="ck_connector_request_page_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["connector_run_id"],
            ["control.connector_run.connector_run_id"],
            name="fk_connector_request_run",
        ),
        sa.PrimaryKeyConstraint(
            "connector_run_id",
            "request_fingerprint",
            name="pk_connector_request",
        ),
        sa.UniqueConstraint(
            "selected_observation_id",
            name="uq_connector_request_selected_observation",
        ),
        schema="control",
    )
    op.create_index(
        "ix_connector_request_run_partition_page",
        "connector_request",
        ["connector_run_id", "partition_id", "page_number"],
        schema="control",
    )

    op.create_table(
        "source_snapshot",
        sa.Column("snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("raw_object_path", sa.Text(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "parser_state",
            sa.String(length=32),
            server_default=sa.text("'UNPARSED'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_source_snapshot_sha256",
        ),
        sa.CheckConstraint(
            "byte_length >= 0",
            name="ck_source_snapshot_byte_length_nonnegative",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_source_snapshot"),
        sa.UniqueConstraint(
            "source_id",
            "content_sha256",
            name="uq_source_snapshot_source_content",
        ),
        schema="raw_manifest",
    )
    op.create_index(
        "ix_source_snapshot_content_sha256",
        "source_snapshot",
        ["content_sha256"],
        schema="raw_manifest",
    )
    op.create_index(
        "ix_source_snapshot_source_first_observed",
        "source_snapshot",
        ["source_id", "first_observed_at"],
        schema="raw_manifest",
    )

    op.create_table(
        "fetch_observation",
        sa.Column("observation_id", sa.String(length=128), nullable=False),
        sa.Column("connector_run_id", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_ordinal", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column("request_url_redacted", sa.Text(), nullable=False),
        sa.Column("response_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("snapshot_id", sa.String(length=128), nullable=True),
        sa.Column(
            "selected",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "response_ordinal >= 0",
            name="ck_fetch_observation_response_ordinal_nonnegative",
        ),
        sa.CheckConstraint(
            "attempt_no >= 1",
            name="ck_fetch_observation_attempt_no_positive",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="ck_fetch_observation_http_status",
        ),
        sa.CheckConstraint(
            "outcome IN ('SELECTED_SUCCESS', 'HTTP_ERROR', 'TRANSPORT_ERROR', 'RESPONSE_INVALID')",
            name="ck_fetch_observation_outcome",
        ),
        sa.CheckConstraint(
            "NOT selected OR (outcome = 'SELECTED_SUCCESS' AND snapshot_id IS NOT NULL "
            "AND http_status BETWEEN 200 AND 299)",
            name="ck_fetch_observation_selected_success",
        ),
        sa.CheckConstraint(
            "outcome <> 'SELECTED_SUCCESS' OR selected",
            name="ck_fetch_observation_success_is_selected",
        ),
        sa.ForeignKeyConstraint(
            ["connector_run_id", "request_fingerprint"],
            [
                "control.connector_request.connector_run_id",
                "control.connector_request.request_fingerprint",
            ],
            name="fk_fetch_observation_request",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["raw_manifest.source_snapshot.snapshot_id"],
            name="fk_fetch_observation_snapshot",
        ),
        sa.PrimaryKeyConstraint("observation_id", name="pk_fetch_observation"),
        sa.UniqueConstraint(
            "connector_run_id",
            "request_fingerprint",
            "response_ordinal",
            "attempt_no",
            name="uq_fetch_observation_attempt",
        ),
        sa.UniqueConstraint(
            "connector_run_id",
            "request_fingerprint",
            "observation_id",
            name="uq_fetch_observation_request_observation",
        ),
        schema="raw_manifest",
    )
    op.create_index(
        "ix_fetch_observation_source_retrieved",
        "fetch_observation",
        ["source_id", "retrieved_at"],
        schema="raw_manifest",
    )
    op.create_index(
        "uq_fetch_observation_one_selected_per_request",
        "fetch_observation",
        ["connector_run_id", "request_fingerprint"],
        unique=True,
        schema="raw_manifest",
        postgresql_where=sa.text("selected"),
    )

    # This composite reference guarantees that the selected observation belongs to the
    # same logical request. It is added after both tables to resolve their intentional cycle.
    op.create_foreign_key(
        "fk_connector_request_selected_observation",
        "connector_request",
        "fetch_observation",
        ["connector_run_id", "request_fingerprint", "selected_observation_id"],
        ["connector_run_id", "request_fingerprint", "observation_id"],
        source_schema="control",
        referent_schema="raw_manifest",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_connector_request_selected_observation",
        "connector_request",
        schema="control",
        type_="foreignkey",
    )
    op.drop_table("fetch_observation", schema="raw_manifest")
    op.drop_table("source_snapshot", schema="raw_manifest")
    op.drop_table("connector_request", schema="control")
    op.drop_table("connector_run", schema="control")
    op.execute(sa.schema.DropSchema("raw_manifest"))
    op.execute(sa.schema.DropSchema("control"))
