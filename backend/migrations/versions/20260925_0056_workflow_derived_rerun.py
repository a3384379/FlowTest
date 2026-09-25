"""Track derived workflow runs and their original input indices."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0056"
down_revision: str | None = "20260910_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_executions") as batch:
        batch.add_column(sa.Column("derived_from_execution_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("rerun_loop_node_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("rerun_input_indices", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_workflow_executions_derived_from_execution_id_workflow_executions"),
            "workflow_executions",
            ["derived_from_execution_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            op.f("ck_workflow_executions_workflow_execution_derived_run"),
            "(derived_from_execution_id IS NULL AND rerun_loop_node_id IS NULL "
            "AND rerun_input_indices IS NULL) OR "
            "(derived_from_execution_id IS NOT NULL AND rerun_loop_node_id IS NOT NULL "
            "AND rerun_input_indices IS NOT NULL AND parent_execution_id IS NULL)",
        )
    op.create_index(
        op.f("ix_workflow_executions_derived_from_execution_id"),
        "workflow_executions",
        ["derived_from_execution_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_executions_derived_from_execution_id"),
        table_name="workflow_executions",
    )
    with op.batch_alter_table("workflow_executions") as batch:
        batch.drop_constraint(
            op.f("ck_workflow_executions_workflow_execution_derived_run"), type_="check"
        )
        batch.drop_constraint(
            op.f("fk_workflow_executions_derived_from_execution_id_workflow_executions"),
            type_="foreignkey",
        )
        batch.drop_column("rerun_input_indices")
        batch.drop_column("rerun_loop_node_id")
        batch.drop_column("derived_from_execution_id")
