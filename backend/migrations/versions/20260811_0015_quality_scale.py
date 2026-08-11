"""Add quality gates, flaky records, cron schedules and project quotas.

Revision ID: 20260811_0015
Revises: 20260811_0014
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0015"
down_revision: str | None = "20260811_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("execution_concurrency_limit", sa.Integer(), server_default="20", nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("queued_run_limit", sa.Integer(), server_default="1000", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_projects_project_execution_concurrency_limit"),
        "projects",
        "execution_concurrency_limit BETWEEN 1 AND 100",
    )
    op.create_check_constraint(
        op.f("ck_projects_project_queued_run_limit"),
        "projects",
        "queued_run_limit BETWEEN 1 AND 5000",
    )
    _add_test_plan_schedule_columns()
    _add_test_plan_run_columns()
    _replace_run_item_status_constraint(include_quarantined=True)
    _create_quality_gates()
    _create_flaky_records()
    _create_gate_evaluations()


def downgrade() -> None:
    op.drop_table("quality_gate_evaluations")
    op.drop_table("flaky_records")
    op.drop_table("quality_gates")
    _replace_run_item_status_constraint(include_quarantined=False)
    op.drop_constraint(
        op.f("ck_test_plan_runs_test_plan_run_queue_name"),
        "test_plan_runs",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_test_plan_runs_test_plan_run_queue_priority"),
        "test_plan_runs",
        type_="check",
    )
    op.drop_index(op.f("ix_test_plan_runs_queue_priority"), table_name="test_plan_runs")
    op.drop_index(op.f("ix_test_plan_runs_baseline_run_id"), table_name="test_plan_runs")
    op.drop_constraint(
        op.f("fk_test_plan_runs_baseline_run_id_test_plan_runs"),
        "test_plan_runs",
        type_="foreignkey",
    )
    op.drop_column("test_plan_runs", "quality_summary")
    op.drop_column("test_plan_runs", "baseline_run_id")
    op.drop_column("test_plan_runs", "queue_name")
    op.drop_column("test_plan_runs", "queue_priority")
    op.drop_constraint(op.f("ck_test_plans_test_plan_schedule_kind"), "test_plans", type_="check")
    op.drop_constraint(op.f("ck_test_plans_test_plan_queue_priority"), "test_plans", type_="check")
    op.drop_column("test_plans", "queue_priority")
    op.drop_column("test_plans", "schedule_timezone")
    op.drop_column("test_plans", "schedule_cron")
    op.drop_constraint(op.f("ck_projects_project_queued_run_limit"), "projects", type_="check")
    op.drop_constraint(
        op.f("ck_projects_project_execution_concurrency_limit"),
        "projects",
        type_="check",
    )
    op.drop_column("projects", "queued_run_limit")
    op.drop_column("projects", "execution_concurrency_limit")


def _add_test_plan_schedule_columns() -> None:
    op.add_column("test_plans", sa.Column("schedule_cron", sa.String(length=120)))
    op.add_column(
        "test_plans",
        sa.Column(
            "schedule_timezone",
            sa.String(length=64),
            server_default="Asia/Shanghai",
            nullable=False,
        ),
    )
    op.add_column(
        "test_plans", sa.Column("queue_priority", sa.Integer(), server_default="5", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_test_plans_test_plan_schedule_kind"),
        "test_plans",
        "NOT (schedule_interval_seconds IS NOT NULL AND schedule_cron IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_test_plans_test_plan_queue_priority"),
        "test_plans",
        "queue_priority BETWEEN 0 AND 9",
    )


def _add_test_plan_run_columns() -> None:
    op.add_column(
        "test_plan_runs",
        sa.Column("queue_priority", sa.Integer(), server_default="5", nullable=False),
    )
    op.add_column(
        "test_plan_runs",
        sa.Column("queue_name", sa.String(length=16), server_default="general", nullable=False),
    )
    op.add_column("test_plan_runs", sa.Column("baseline_run_id", sa.Uuid()))
    op.add_column(
        "test_plan_runs",
        sa.Column("quality_summary", sa.JSON(), server_default="{}", nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_test_plan_runs_baseline_run_id_test_plan_runs"),
        "test_plan_runs",
        "test_plan_runs",
        ["baseline_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_test_plan_runs_baseline_run_id"), "test_plan_runs", ["baseline_run_id"]
    )
    op.create_index(op.f("ix_test_plan_runs_queue_priority"), "test_plan_runs", ["queue_priority"])
    op.create_check_constraint(
        op.f("ck_test_plan_runs_test_plan_run_queue_priority"),
        "test_plan_runs",
        "queue_priority BETWEEN 0 AND 9",
    )
    op.create_check_constraint(
        op.f("ck_test_plan_runs_test_plan_run_queue_name"),
        "test_plan_runs",
        "queue_name IN ('general', 'data', 'ai')",
    )


def _replace_run_item_status_constraint(*, include_quarantined: bool) -> None:
    name = op.f("ck_test_plan_run_items_test_plan_run_item_status")
    op.drop_constraint(name, "test_plan_run_items", type_="check")
    values = "'queued', 'running', 'passed', 'failed', 'cancelled'"
    if include_quarantined:
        values += ", 'quarantined'"
    op.create_check_constraint(name, "test_plan_run_items", f"status IN ({values})")


def _create_quality_gates() -> None:
    op.create_table(
        "quality_gates",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("min_pass_rate", sa.Float(), server_default="100", nullable=False),
        sa.Column("max_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_flaky", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "max_duration_regression_percent", sa.Float(), server_default="20", nullable=False
        ),
        sa.Column(
            "require_no_breaking_changes", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "min_pass_rate BETWEEN 0 AND 100", name=op.f("ck_quality_gates_quality_gate_pass_rate")
        ),
        sa.CheckConstraint(
            "max_failed >= 0", name=op.f("ck_quality_gates_quality_gate_max_failed")
        ),
        sa.CheckConstraint("max_flaky >= 0", name=op.f("ck_quality_gates_quality_gate_max_flaky")),
        sa.CheckConstraint(
            "max_duration_regression_percent >= 0",
            name=op.f("ck_quality_gates_quality_gate_duration_regression"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_quality_gates_project_name"),
    )
    op.create_index(op.f("ix_quality_gates_project_id"), "quality_gates", ["project_id"])


def _create_flaky_records() -> None:
    op.create_table(
        "flaky_records",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("total_runs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passed_runs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_runs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("transitions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("flaky_score", sa.Float(), server_default="0", nullable=False),
        sa.Column("quarantined", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_status", sa.String(length=16)),
        sa.Column("last_run_id", sa.Uuid()),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "total_runs >= 0", name=op.f("ck_flaky_records_flaky_record_total_runs")
        ),
        sa.CheckConstraint(
            "passed_runs >= 0", name=op.f("ck_flaky_records_flaky_record_passed_runs")
        ),
        sa.CheckConstraint(
            "failed_runs >= 0", name=op.f("ck_flaky_records_flaky_record_failed_runs")
        ),
        sa.CheckConstraint(
            "transitions >= 0", name=op.f("ck_flaky_records_flaky_record_transitions")
        ),
        sa.CheckConstraint(
            "flaky_score BETWEEN 0 AND 100", name=op.f("ck_flaky_records_flaky_record_score")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_run_id"], ["test_plan_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "target_type",
            "target_id",
            "target_version",
            name="uq_flaky_records_project_target",
        ),
    )
    for column in ("project_id", "target_type", "target_id", "flaky_score", "quarantined"):
        op.create_index(op.f(f"ix_flaky_records_{column}"), "flaky_records", [column])


def _create_gate_evaluations() -> None:
    op.create_table(
        "quality_gate_evaluations",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("quality_gate_id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("metrics", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("violations", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('passed', 'failed')",
            name=op.f("ck_quality_gate_evaluations_gate_evaluation_status"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quality_gate_id"], ["quality_gates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_plan_run_id"], ["test_plan_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quality_gate_id", "test_plan_run_id", name="uq_gate_evaluation_run"),
    )
    for column in ("project_id", "quality_gate_id", "test_plan_run_id", "status"):
        op.create_index(
            op.f(f"ix_quality_gate_evaluations_{column}"),
            "quality_gate_evaluations",
            [column],
        )
