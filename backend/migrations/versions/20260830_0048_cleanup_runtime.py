"""Persist bounded cleanup runtime state and force-cancel audit data."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0048"
down_revision: str | None = "20260829_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_executions") as batch:
        batch.add_column(sa.Column("main_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("cleanup_status", sa.String(length=16), nullable=True))
        batch.add_column(
            sa.Column("cleanup_report", sa.JSON(), server_default="{}", nullable=False)
        )
        batch.add_column(
            sa.Column("force_cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("force_cancel_reason", sa.Text(), nullable=True))
        batch.create_check_constraint(
            op.f("ck_workflow_executions_workflow_execution_main_status"),
            "main_status IS NULL OR main_status IN ('passed', 'failed', 'cancelled')",
        )
        batch.create_check_constraint(
            op.f("ck_workflow_executions_workflow_execution_cleanup_status"),
            "cleanup_status IS NULL OR cleanup_status IN ('passed', 'failed', 'cancelled')",
        )
    op.create_index(
        op.f("ix_workflow_executions_force_cancel_requested_at"),
        "workflow_executions",
        ["force_cancel_requested_at"],
        unique=False,
    )
    op.execute(
        "UPDATE workflow_executions SET main_status = status "
        "WHERE status IN ('passed', 'failed', 'cancelled')"
    )
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.add_column(
            sa.Column("phase", sa.String(length=16), server_default="main", nullable=False)
        )
        batch.add_column(
            sa.Column("best_effort", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_check_constraint(
            op.f("ck_workflow_node_executions_workflow_node_execution_phase"),
            "phase IN ('main', 'cleanup')",
        )
    with op.batch_alter_table("execution_checkpoints") as batch:
        batch.add_column(
            sa.Column("phase", sa.String(length=16), server_default="main", nullable=False)
        )
        batch.add_column(
            sa.Column("best_effort", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_check_constraint(
            op.f("ck_execution_checkpoints_execution_checkpoint_phase"),
            "phase IN ('main', 'cleanup')",
        )


def downgrade() -> None:
    with op.batch_alter_table("execution_checkpoints") as batch:
        batch.drop_constraint(
            op.f("ck_execution_checkpoints_execution_checkpoint_phase"), type_="check"
        )
        batch.drop_column("best_effort")
        batch.drop_column("phase")
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.drop_constraint(
            op.f("ck_workflow_node_executions_workflow_node_execution_phase"), type_="check"
        )
        batch.drop_column("best_effort")
        batch.drop_column("phase")
    op.drop_index(
        op.f("ix_workflow_executions_force_cancel_requested_at"),
        table_name="workflow_executions",
    )
    with op.batch_alter_table("workflow_executions") as batch:
        batch.drop_constraint(
            op.f("ck_workflow_executions_workflow_execution_cleanup_status"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_workflow_executions_workflow_execution_main_status"), type_="check"
        )
        batch.drop_column("force_cancel_reason")
        batch.drop_column("force_cancel_requested_at")
        batch.drop_column("cleanup_report")
        batch.drop_column("cleanup_status")
        batch.drop_column("main_status")
