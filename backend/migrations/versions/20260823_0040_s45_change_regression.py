"""Add the S45 change-aware regression trace and stage evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0040"
down_revision: str | None = "20260822_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_ai_change_sets_ai_change_set_source_type"),
        "ai_change_sets",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_ai_change_sets_ai_change_set_source_type"),
        "ai_change_sets",
        "source_type IN ('ai', 'flow_spec', 'mcp', 'rest', 'cli', 'change_regression')",
    )

    op.create_table(
        "change_regression_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_ref", sa.String(length=200), server_default="", nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_ref", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("impact_run_id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_run_id", sa.Uuid(), nullable=True),
        sa.Column("release_policy_id", sa.Uuid(), nullable=False),
        sa.Column("release_risk_id", sa.Uuid(), nullable=True),
        sa.Column("deployment_check_id", sa.Uuid(), nullable=True),
        sa.Column("change_set_id", sa.Uuid(), nullable=True),
        sa.Column("release_decision_id", sa.Uuid(), nullable=True),
        sa.Column("selected_assets", sa.JSON(), nullable=False),
        sa.Column("selection_summary", sa.JSON(), nullable=False),
        sa.Column("missing_tests", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("failure_triage", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('review_required', 'approved', 'queued', 'running', "
            "'evidence_ready', 'passed', 'blocked', 'failed')",
            name=op.f("ck_change_regression_runs_change_regression_run_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_change_regression_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["impact_run_id"],
            ["impact_runs.id"],
            name=op.f("fk_change_regression_impact"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["test_plan_id"],
            ["test_plans.id"],
            name=op.f("fk_change_regression_plan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["test_plan_run_id"],
            ["test_plan_runs.id"],
            name=op.f("fk_change_regression_plan_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_policy_id"],
            ["release_policies.id"],
            name=op.f("fk_change_regression_policy"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_risk_id"],
            ["release_risks.id"],
            name=op.f("fk_change_regression_risk"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deployment_check_id"],
            ["deployment_compatibility_checks.id"],
            name=op.f("fk_change_regression_deployment_check"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["change_set_id"],
            ["ai_change_sets.id"],
            name=op.f("fk_change_regression_change_set"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_decision_id"],
            ["release_decisions.id"],
            name=op.f("fk_change_regression_release_decision"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_change_regression_approver"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_change_regression_creator"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "project_id",
        "source_fingerprint",
        "candidate_ref",
        "status",
        "impact_run_id",
        "test_plan_id",
        "test_plan_run_id",
        "release_policy_id",
        "release_risk_id",
        "deployment_check_id",
        "change_set_id",
        "release_decision_id",
    ):
        op.create_index(
            op.f(f"ix_change_regression_runs_{column}"),
            "change_regression_runs",
            [column],
        )

    op.create_table(
        "change_regression_stages",
        sa.Column("regression_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "stage IN ('change', 'impact', 'regression_selection', 'missing_test', 'review', "
            "'execution', 'evidence', 'release_gate', 'failure_triage')",
            name=op.f("ck_change_regression_stages_change_regression_stage_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'pending', 'approved', 'queued', 'running', 'passed', "
            "'blocked', 'failed', 'skipped')",
            name=op.f("ck_change_regression_stages_change_regression_stage_status"),
        ),
        sa.ForeignKeyConstraint(
            ["regression_run_id"],
            ["change_regression_runs.id"],
            name=op.f("fk_change_regression_stage_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_change_regression_stage_actor"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "regression_run_id",
            "sequence",
            name=op.f("uq_change_regression_stage_sequence"),
        ),
    )
    op.create_index(
        op.f("ix_change_regression_stages_regression_run_id"),
        "change_regression_stages",
        ["regression_run_id"],
    )
    op.create_index(
        op.f("ix_change_regression_stages_stage"), "change_regression_stages", ["stage"]
    )
    op.create_index(
        op.f("ix_change_regression_stages_status"), "change_regression_stages", ["status"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_change_regression_stages_status"), table_name="change_regression_stages")
    op.drop_index(op.f("ix_change_regression_stages_stage"), table_name="change_regression_stages")
    op.drop_index(
        op.f("ix_change_regression_stages_regression_run_id"),
        table_name="change_regression_stages",
    )
    op.drop_table("change_regression_stages")
    for column in (
        "release_decision_id",
        "change_set_id",
        "release_policy_id",
        "deployment_check_id",
        "release_risk_id",
        "test_plan_run_id",
        "test_plan_id",
        "impact_run_id",
        "status",
        "candidate_ref",
        "source_fingerprint",
        "project_id",
    ):
        op.drop_index(
            op.f(f"ix_change_regression_runs_{column}"), table_name="change_regression_runs"
        )
    op.drop_table("change_regression_runs")
    op.drop_constraint(
        op.f("ck_ai_change_sets_ai_change_set_source_type"),
        "ai_change_sets",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_ai_change_sets_ai_change_set_source_type"),
        "ai_change_sets",
        "source_type IN ('ai', 'flow_spec', 'mcp', 'rest', 'cli')",
    )
