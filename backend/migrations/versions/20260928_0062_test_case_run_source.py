"""Track precise test case sources on workflow executions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0062"
down_revision: str | None = "20260927_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_executions") as batch:
        batch.add_column(sa.Column("source_case_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("source_case_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_trigger", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("source_plan_run_item_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_workflow_executions_source_case_id_test_cases",
            "test_cases",
            ["source_case_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_workflow_executions_source_plan_run_item_id_test_plan_run_items",
            "test_plan_run_items",
            ["source_plan_run_item_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "workflow_execution_case_source",
            "(source_case_id IS NULL AND source_case_version IS NULL "
            "AND source_trigger IS NULL) OR "
            "(source_case_id IS NOT NULL AND source_case_version >= 1 "
            "AND source_trigger IN ('direct', 'plan'))",
        )
    op.create_index(
        "ix_workflow_executions_case_latest",
        "workflow_executions",
        ["project_id", "source_case_id", "started_at", "id"],
    )
    op.create_index(
        "ix_workflow_executions_source_plan_run_item_id",
        "workflow_executions",
        ["source_plan_run_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_executions_source_plan_run_item_id", table_name="workflow_executions"
    )
    op.drop_index("ix_workflow_executions_case_latest", table_name="workflow_executions")
    with op.batch_alter_table("workflow_executions") as batch:
        batch.drop_constraint("workflow_execution_case_source", type_="check")
        batch.drop_constraint(
            "fk_workflow_executions_source_plan_run_item_id_test_plan_run_items", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_workflow_executions_source_case_id_test_cases", type_="foreignkey"
        )
        batch.drop_column("source_plan_run_item_id")
        batch.drop_column("source_trigger")
        batch.drop_column("source_case_version")
        batch.drop_column("source_case_id")
