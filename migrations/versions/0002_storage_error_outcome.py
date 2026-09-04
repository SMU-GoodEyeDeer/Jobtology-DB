"""Allow explicit raw-storage failures in the fetch ledger.

Revision ID: 0002_storage_error_outcome
Revises: 0001_fetch_ledger
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_storage_error_outcome"
down_revision: str | None = "0001_fetch_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_fetch_observation_outcome",
        "fetch_observation",
        schema="raw_manifest",
        type_="check",
    )
    op.create_check_constraint(
        "ck_fetch_observation_outcome",
        "fetch_observation",
        "outcome IN ('SELECTED_SUCCESS', 'HTTP_ERROR', 'TRANSPORT_ERROR', "
        "'RESPONSE_INVALID', 'STORAGE_ERROR')",
        schema="raw_manifest",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_fetch_observation_outcome",
        "fetch_observation",
        schema="raw_manifest",
        type_="check",
    )
    op.create_check_constraint(
        "ck_fetch_observation_outcome",
        "fetch_observation",
        "outcome IN ('SELECTED_SUCCESS', 'HTTP_ERROR', 'TRANSPORT_ERROR', 'RESPONSE_INVALID')",
        schema="raw_manifest",
    )
