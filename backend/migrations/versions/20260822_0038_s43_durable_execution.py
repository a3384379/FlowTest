"""Add durable execution commands and node checkpoints for S43."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0038"
down_revision: str | None = "20260822_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_commands",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("command_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="accepted", nullable=False),
        sa.Column("actor_key", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "command_type IN ('start', 'resume', 'retry', 'cancel')",
            name=op.f("ck_execution_commands_execution_command_type"),
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'dispatched', 'completed', 'failed', 'rejected')",
            name=op.f("ck_execution_commands_execution_command_status"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["workflow_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("project_id", "execution_id", "command_type", "status", "idempotency_key"):
        op.create_index(op.f(f"ix_execution_commands_{column}"), "execution_commands", [column])
    op.create_index(
        op.f("ix_execution_commands_execution_created"),
        "execution_commands",
        ["execution_id", "created_at"],
    )

    op.create_table(
        "execution_checkpoints",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("node_name", sa.String(length=200), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("output_digest", sa.String(length=64), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("extracted_variables", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("fencing_token", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("runner_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'skipped', 'cancelled')",
            name=op.f("ck_execution_checkpoints_execution_checkpoint_status"),
        ),
        sa.CheckConstraint(
            "attempt >= 1", name=op.f("ck_execution_checkpoints_execution_checkpoint_attempt")
        ),
        sa.CheckConstraint(
            "fencing_token >= 0", name=op.f("ck_execution_checkpoints_execution_checkpoint_fence")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["workflow_executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_id",
            "node_id",
            "attempt",
            name=op.f("uq_execution_checkpoint_node_attempt"),
        ),
    )
    for column in ("project_id", "execution_id", "status", "lease_id", "runner_id"):
        op.create_index(
            op.f(f"ix_execution_checkpoints_{column}"), "execution_checkpoints", [column]
        )
    op.create_index(
        op.f("ix_execution_checkpoints_execution_status"),
        "execution_checkpoints",
        ["execution_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_execution_checkpoints_execution_status"), table_name="execution_checkpoints"
    )
    for column in ("runner_id", "lease_id", "status", "execution_id", "project_id"):
        op.drop_index(
            op.f(f"ix_execution_checkpoints_{column}"), table_name="execution_checkpoints"
        )
    op.drop_table("execution_checkpoints")
    op.drop_index(op.f("ix_execution_commands_execution_created"), table_name="execution_commands")
    for column in ("idempotency_key", "status", "command_type", "execution_id", "project_id"):
        op.drop_index(op.f(f"ix_execution_commands_{column}"), table_name="execution_commands")
    op.drop_table("execution_commands")
