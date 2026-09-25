"""Store structured-control report rows for on-demand paging."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0057"
down_revision: str | None = "20260925_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_executions") as batch:
        batch.add_column(sa.Column("context_summary", sa.JSON(none_as_null=True), nullable=True))
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.add_column(sa.Column("output_summary", sa.JSON(none_as_null=True), nullable=True))
        batch.add_column(sa.Column("result_summary", sa.JSON(none_as_null=True), nullable=True))
    op.create_table(
        "workflow_control_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("test_verdict", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('iteration', 'branch')",
            name=op.f("ck_workflow_control_records_workflow_control_record_kind"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0", name=op.f("ck_workflow_control_records_workflow_control_record_ordinal")
        ),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id"], ["workflow_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_execution_id",
            "node_id",
            "kind",
            "ordinal",
            name="uq_workflow_control_records_execution_node_kind_ordinal",
        ),
    )
    op.create_index(
        op.f("ix_workflow_control_records_workflow_execution_id"),
        "workflow_control_records",
        ["workflow_execution_id"],
    )
    op.create_index(
        "ix_workflow_control_records_verdict_page",
        "workflow_control_records",
        ["workflow_execution_id", "node_id", "kind", "test_verdict", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_control_records_verdict_page", table_name="workflow_control_records")
    op.drop_index(
        op.f("ix_workflow_control_records_workflow_execution_id"),
        table_name="workflow_control_records",
    )
    op.drop_table("workflow_control_records")
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.drop_column("result_summary")
        batch.drop_column("output_summary")
    with op.batch_alter_table("workflow_executions") as batch:
        batch.drop_column("context_summary")
