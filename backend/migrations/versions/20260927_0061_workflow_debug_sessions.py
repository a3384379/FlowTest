"""Persist bounded iteration-debug sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0061"
down_revision: str | None = "20260927_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_debug_sessions",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("target_node_id", sa.String(length=128), nullable=False),
        sa.Column("pause_before_index", sa.Integer(), nullable=False),
        sa.Column("pause_on_error", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pause_reason", sa.String(length=32), nullable=True),
        sa.Column("paused_input_index", sa.Integer(), nullable=True),
        sa.Column("last_completed_index", sa.Integer(), nullable=False),
        sa.Column("step_target_index", sa.Integer(), nullable=True),
        sa.Column("initial_pause_consumed", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('armed', 'running', 'paused', 'completed', 'expired', 'cancelled')",
            name="workflow_debug_session_status",
        ),
        sa.CheckConstraint("pause_before_index >= 0", name="workflow_debug_pause_index"),
        sa.CheckConstraint("last_completed_index >= -1", name="workflow_debug_completed_index"),
        sa.CheckConstraint(
            "step_target_index IS NULL OR step_target_index >= 0",
            name="workflow_debug_step_index",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["workflow_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    op.create_index(
        "ix_workflow_debug_sessions_project_id", "workflow_debug_sessions", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_debug_sessions_project_id", table_name="workflow_debug_sessions")
    op.drop_table("workflow_debug_sessions")
