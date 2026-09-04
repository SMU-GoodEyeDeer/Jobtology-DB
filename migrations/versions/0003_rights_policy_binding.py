"""Bind every new fetch run to a reviewed source-rights policy.

Revision ID: 0003_rights_policy_binding
Revises: 0002_storage_error_outcome
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_rights_policy_binding"
down_revision: str | None = "0002_storage_error_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connector_run",
        sa.Column("rights_registry_revision", sa.String(length=32), nullable=True),
        schema="control",
    )
    op.add_column(
        "connector_run",
        sa.Column("rights_policy_version", sa.Integer(), nullable=True),
        schema="control",
    )
    op.add_column(
        "connector_run",
        sa.Column("rights_policy_hash", sa.String(length=64), nullable=True),
        schema="control",
    )
    op.create_check_constraint(
        "ck_connector_run_rights_binding_complete",
        "connector_run",
        "(rights_registry_revision IS NULL AND rights_policy_version IS NULL "
        "AND rights_policy_hash IS NULL) OR "
        "(rights_registry_revision IS NOT NULL AND rights_policy_version IS NOT NULL "
        "AND rights_policy_hash IS NOT NULL)",
        schema="control",
    )
    op.create_check_constraint(
        "ck_connector_run_rights_policy_version_positive",
        "connector_run",
        "rights_policy_version IS NULL OR rights_policy_version >= 1",
        schema="control",
    )
    op.create_check_constraint(
        "ck_connector_run_rights_policy_hash",
        "connector_run",
        "rights_policy_hash IS NULL OR rights_policy_hash ~ '^[0-9a-f]{64}$'",
        schema="control",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_connector_run_rights_policy_hash",
        "connector_run",
        schema="control",
        type_="check",
    )
    op.drop_constraint(
        "ck_connector_run_rights_policy_version_positive",
        "connector_run",
        schema="control",
        type_="check",
    )
    op.drop_constraint(
        "ck_connector_run_rights_binding_complete",
        "connector_run",
        schema="control",
        type_="check",
    )
    op.drop_column("connector_run", "rights_policy_hash", schema="control")
    op.drop_column("connector_run", "rights_policy_version", schema="control")
    op.drop_column("connector_run", "rights_registry_revision", schema="control")
