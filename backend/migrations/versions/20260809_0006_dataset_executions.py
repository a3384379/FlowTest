"""Add parent and dataset row identity to workflow executions.

Revision ID: 20260809_0006
Revises: 20260809_0005
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0006"
down_revision: str | None = "20260809_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_executions", sa.Column("parent_execution_id", sa.Uuid()))
    op.add_column("workflow_executions", sa.Column("dataset_row_index", sa.Integer()))
    op.create_foreign_key(
        op.f("fk_workflow_executions_parent_execution_id_workflow_executions"),
        "workflow_executions",
        "workflow_executions",
        ["parent_execution_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_workflow_executions_parent_execution_id"),
        "workflow_executions",
        ["parent_execution_id"],
    )
    op.create_unique_constraint(
        "uq_workflow_executions_parent_dataset_row",
        "workflow_executions",
        ["parent_execution_id", "dataset_row_index"],
    )
    op.create_check_constraint(
        "workflow_execution_dataset_child",
        "workflow_executions",
        "(parent_execution_id IS NULL AND dataset_row_index IS NULL) OR "
        "(parent_execution_id IS NOT NULL AND dataset_row_index IS NOT NULL "
        "AND dataset_row_index >= 0)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_workflow_executions_workflow_execution_dataset_child"),
        "workflow_executions",
        type_="check",
    )
    op.drop_constraint(
        op.f("uq_workflow_executions_parent_dataset_row"),
        "workflow_executions",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_workflow_executions_parent_execution_id"),
        table_name="workflow_executions",
    )
    op.drop_constraint(
        op.f("fk_workflow_executions_parent_execution_id_workflow_executions"),
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_column("workflow_executions", "dataset_row_index")
    op.drop_column("workflow_executions", "parent_execution_id")
