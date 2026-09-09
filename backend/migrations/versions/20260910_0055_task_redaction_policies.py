"""Capture redaction policy versions on queued execution and AI tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_0055"
down_revision: str | None = "20260909_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("workflow_executions", "ai_jobs"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "redaction_mode",
                    sa.String(length=8),
                    server_default="off",
                    nullable=False,
                )
            )
            batch.add_column(
                sa.Column(
                    "redaction_policy_version",
                    sa.Integer(),
                    server_default="1",
                    nullable=False,
                )
            )
            batch.create_check_constraint(
                op.f(f"ck_{table}_redaction_mode"),
                "redaction_mode IN ('off', 'on')",
            )


def downgrade() -> None:
    for table in ("ai_jobs", "workflow_executions"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(op.f(f"ck_{table}_redaction_mode"), type_="check")
            batch.drop_column("redaction_policy_version")
            batch.drop_column("redaction_mode")
