"""Add declarative performance scenarios, runs, and gate evaluations.

Revision ID: 20260812_0022
Revises: 20260812_0021
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0022"
down_revision: str | None = "20260812_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "performance_scenarios",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("compiled_sha256", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published')",
            name=op.f("ck_performance_scenarios_performance_scenario_status"),
        ),
        sa.CheckConstraint(
            "target_type IN ('rest', 'http_workflow')",
            name=op.f("ck_performance_scenarios_performance_scenario_target_type"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_performance_scenarios_performance_scenario_version"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_performance_scenarios_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_performance_scenarios_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_scenarios")),
        sa.UniqueConstraint(
            "project_id",
            "name",
            "version",
            name="uq_performance_scenarios_project_name_version",
        ),
    )
    op.create_index(
        op.f("ix_performance_scenarios_project_id"), "performance_scenarios", ["project_id"]
    )
    op.create_index(op.f("ix_performance_scenarios_name"), "performance_scenarios", ["name"])
    op.create_index(op.f("ix_performance_scenarios_status"), "performance_scenarios", ["status"])
    op.create_index(
        op.f("ix_performance_scenarios_target_type"),
        "performance_scenarios",
        ["target_type"],
    )
    op.create_index(
        op.f("ix_performance_scenarios_compiled_sha256"),
        "performance_scenarios",
        ["compiled_sha256"],
    )
    op.create_table(
        "performance_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("definition_snapshot", sa.JSON(), nullable=False),
        sa.Column("compiled_sha256", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("threshold_results", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
        sa.Column("raw_metrics_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "scenario_version >= 1",
            name=op.f("ck_performance_runs_performance_run_scenario_version"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'cancelled')",
            name=op.f("ck_performance_runs_performance_run_status"),
        ),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"],
            ["performance_runs.id"],
            name=op.f("fk_performance_runs_baseline_run_id_performance_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_performance_runs_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_performance_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raw_metrics_artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_performance_runs_raw_metrics_artifact_id_artifacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["performance_scenarios.id"],
            name=op.f("fk_performance_runs_scenario_id_performance_scenarios"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_runs")),
    )
    for column in ("project_id", "scenario_id", "status", "baseline_run_id"):
        op.create_index(op.f(f"ix_performance_runs_{column}"), "performance_runs", [column])
    op.create_table(
        "performance_gate_evaluations",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("quality_gate_id", sa.Uuid(), nullable=False),
        sa.Column("performance_run_id", sa.Uuid(), nullable=False),
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
            name=op.f("ck_performance_gate_evaluations_performance_gate_status"),
        ),
        sa.ForeignKeyConstraint(
            ["performance_run_id"],
            ["performance_runs.id"],
            name=op.f("fk_performance_gate_evaluations_performance_run_id_performance_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_performance_gate_evaluations_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quality_gate_id"],
            ["quality_gates.id"],
            name=op.f("fk_performance_gate_evaluations_quality_gate_id_quality_gates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_gate_evaluations")),
        sa.UniqueConstraint(
            "quality_gate_id",
            "performance_run_id",
            name="uq_performance_gate_evaluation_run",
        ),
    )
    for column in ("project_id", "quality_gate_id", "performance_run_id", "status"):
        op.create_index(
            op.f(f"ix_performance_gate_evaluations_{column}"),
            "performance_gate_evaluations",
            [column],
        )


def downgrade() -> None:
    for column in ("status", "performance_run_id", "quality_gate_id", "project_id"):
        op.drop_index(
            op.f(f"ix_performance_gate_evaluations_{column}"),
            table_name="performance_gate_evaluations",
        )
    op.drop_table("performance_gate_evaluations")
    for column in ("baseline_run_id", "status", "scenario_id", "project_id"):
        op.drop_index(op.f(f"ix_performance_runs_{column}"), table_name="performance_runs")
    op.drop_table("performance_runs")
    op.drop_index(
        op.f("ix_performance_scenarios_compiled_sha256"), table_name="performance_scenarios"
    )
    op.drop_index(op.f("ix_performance_scenarios_target_type"), table_name="performance_scenarios")
    op.drop_index(op.f("ix_performance_scenarios_status"), table_name="performance_scenarios")
    op.drop_index(op.f("ix_performance_scenarios_name"), table_name="performance_scenarios")
    op.drop_index(op.f("ix_performance_scenarios_project_id"), table_name="performance_scenarios")
    op.drop_table("performance_scenarios")
