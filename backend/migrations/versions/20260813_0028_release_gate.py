"""Add release policies and immutable release decision snapshots.

Revision ID: 20260813_0028
Revises: 20260813_0027
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0028"
down_revision: str | None = "20260813_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_release_policies()
    _create_release_decisions()


def downgrade() -> None:
    _drop_release_decisions()
    _drop_release_policies()


def _create_release_policies() -> None:
    op.create_table(
        "release_policies",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("quality_gate_id", sa.Uuid(), nullable=True),
        sa.Column("require_quality_gate", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "require_contract_compatibility", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("require_impact_evidence", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("min_impact_coverage_percent", sa.Float(), server_default="80", nullable=False),
        sa.Column("require_release_risk", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("max_release_risk_score", sa.Float(), server_default="50", nullable=False),
        sa.Column(
            "require_performance_evidence", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("require_runner_evidence", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "min_impact_coverage_percent BETWEEN 0 AND 100",
            name=op.f("ck_release_policies_release_policy_impact_coverage"),
        ),
        sa.CheckConstraint(
            "max_release_risk_score BETWEEN 0 AND 100",
            name=op.f("ck_release_policies_release_policy_risk_score"),
        ),
        sa.CheckConstraint(
            "NOT require_quality_gate OR quality_gate_id IS NOT NULL",
            name=op.f("ck_release_policies_release_policy_quality_gate_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_release_policy_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["quality_gate_id"],
            ["quality_gates.id"],
            name="fk_release_policy_quality_gate",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_release_policy_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_policies")),
        sa.UniqueConstraint("project_id", "name", name="uq_release_policies_project_name"),
    )
    for column in ("project_id", "enabled", "quality_gate_id"):
        op.create_index(op.f(f"ix_release_policies_{column}"), "release_policies", [column])


def _create_release_decisions() -> None:
    op.create_table(
        "release_decisions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("release_policy_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_ref", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("test_plan_run_id", sa.Uuid(), nullable=True),
        sa.Column("deployment_check_id", sa.Uuid(), nullable=True),
        sa.Column("impact_run_id", sa.Uuid(), nullable=True),
        sa.Column("release_risk_id", sa.Uuid(), nullable=True),
        sa.Column("performance_run_id", sa.Uuid(), nullable=True),
        sa.Column("runner_task_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pass', 'block')",
            name=op.f("ck_release_decisions_release_decision_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_release_decision_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_policy_id"],
            ["release_policies.id"],
            name="fk_release_decision_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["test_plan_run_id"], ["test_plan_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["deployment_check_id"],
            ["deployment_compatibility_checks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["impact_run_id"], ["impact_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["release_risk_id"], ["release_risks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["performance_run_id"], ["performance_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["runner_task_id"], ["runner_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_release_decision_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_decisions")),
    )
    for column in (
        "project_id",
        "release_policy_id",
        "candidate_ref",
        "status",
        "fingerprint",
        "test_plan_run_id",
        "deployment_check_id",
        "impact_run_id",
        "release_risk_id",
        "performance_run_id",
        "runner_task_id",
        "created_at",
    ):
        op.create_index(op.f(f"ix_release_decisions_{column}"), "release_decisions", [column])


def _drop_release_decisions() -> None:
    for column in reversed(
        (
            "project_id",
            "release_policy_id",
            "candidate_ref",
            "status",
            "fingerprint",
            "test_plan_run_id",
            "deployment_check_id",
            "impact_run_id",
            "release_risk_id",
            "performance_run_id",
            "runner_task_id",
            "created_at",
        )
    ):
        op.drop_index(op.f(f"ix_release_decisions_{column}"), table_name="release_decisions")
    op.drop_table("release_decisions")


def _drop_release_policies() -> None:
    for column in reversed(("project_id", "enabled", "quality_gate_id")):
        op.drop_index(op.f(f"ix_release_policies_{column}"), table_name="release_policies")
    op.drop_table("release_policies")
