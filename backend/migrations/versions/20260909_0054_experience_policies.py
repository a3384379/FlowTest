"""Add project redaction policy and archive state for environments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0054"
down_revision: str | None = "20260908_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("redaction_mode", sa.String(length=8), nullable=True))
        batch.add_column(
            sa.Column("redaction_policy_version", sa.Integer(), server_default="1", nullable=False)
        )
        batch.create_check_constraint(
            op.f("ck_projects_redaction_mode"),
            "redaction_mode IS NULL OR redaction_mode IN ('off', 'on')",
        )
    with op.batch_alter_table("environments") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("workflows") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("ix_environments_archived_at"), "environments", ["archived_at"], unique=False
    )
    op.create_index(op.f("ix_workflows_archived_at"), "workflows", ["archived_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_environments_archived_at"), table_name="environments")
    with op.batch_alter_table("environments") as batch:
        batch.drop_column("archived_at")
    op.drop_index(op.f("ix_workflows_archived_at"), table_name="workflows")
    with op.batch_alter_table("workflows") as batch:
        batch.drop_column("archived_at")
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint(op.f("ck_projects_redaction_mode"), type_="check")
        batch.drop_column("redaction_policy_version")
        batch.drop_column("redaction_mode")
