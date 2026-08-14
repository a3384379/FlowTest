"""Add explainable quality intelligence and AI draft change sets.

Revision ID: 20260813_0027
Revises: 20260812_0026
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0027"
down_revision: str | None = "20260812_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _extend_ai_job_type()
    _create_release_risks()
    _create_failure_clusters()
    _create_ai_change_sets()
    _create_ai_change_items()


def downgrade() -> None:
    _drop_ai_change_items()
    _drop_ai_change_sets()
    _drop_failure_clusters()
    _drop_release_risks()
    _restore_ai_job_type()


def _extend_ai_job_type() -> None:
    op.drop_constraint(op.f("ck_ai_jobs_ai_job_type"), "ai_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_jobs_ai_job_type"),
        "ai_jobs",
        "job_type IN ('schema_cases', 'assertion_suggestions', 'workflow_draft', "
        "'failure_analysis', 'change_set')",
    )


def _create_release_risks() -> None:
    op.create_table(
        "release_risks",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("impact_run_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "algorithm_version",
            sa.String(length=32),
            server_default="release_risk_v1",
            nullable=False,
        ),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("quality_trend", sa.JSON(), nullable=False),
        sa.Column("recommended_tests", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "window_days BETWEEN 7 AND 90", name=op.f("ck_release_risks_release_risk_window_days")
        ),
        sa.CheckConstraint(
            "score BETWEEN 0 AND 100", name=op.f("ck_release_risks_release_risk_score")
        ),
        sa.CheckConstraint(
            "quality_score BETWEEN 0 AND 100",
            name=op.f("ck_release_risks_release_quality_score"),
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_release_risks_release_risk_level"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_release_risk_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["impact_run_id"],
            ["impact_runs.id"],
            name="fk_release_risk_impact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_release_risk_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_risks")),
    )
    for column in ("project_id", "impact_run_id", "score", "risk_level", "fingerprint"):
        op.create_index(op.f(f"ix_release_risks_{column}"), "release_risks", [column])


def _create_failure_clusters() -> None:
    op.create_table(
        "failure_clusters",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("release_risk_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("failure_category", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("node_type", sa.String(length=32), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("baseline_count", sa.Integer(), nullable=False),
        sa.Column("affected_workflow_ids", sa.JSON(), nullable=False),
        sa.Column("affected_workflow_names", sa.JSON(), nullable=False),
        sa.Column("sample_execution_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("regression_percent", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "occurrence_count >= 1",
            name=op.f("ck_failure_clusters_failure_cluster_occurrences"),
        ),
        sa.CheckConstraint(
            "baseline_count >= 0", name=op.f("ck_failure_clusters_failure_cluster_baseline")
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name=op.f("ck_failure_clusters_failure_cluster_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_failure_cluster_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_risk_id"],
            ["release_risks.id"],
            name="fk_failure_cluster_risk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_failure_clusters")),
    )
    for column in ("project_id", "release_risk_id", "fingerprint", "failure_category"):
        op.create_index(op.f(f"ix_failure_clusters_{column}"), "failure_clusters", [column])


def _create_ai_change_sets() -> None:
    op.create_table(
        "ai_change_sets",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("impact_run_id", sa.Uuid(), nullable=False),
        sa.Column("release_risk_id", sa.Uuid(), nullable=False),
        sa.Column("ai_job_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="generating", nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'draft', 'partially_reviewed', 'accepted', "
            "'rejected', 'failed')",
            name=op.f("ck_ai_change_sets_ai_change_set_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_ai_change_set_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["impact_run_id"],
            ["impact_runs.id"],
            name="fk_ai_change_set_impact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_risk_id"],
            ["release_risks.id"],
            name="fk_ai_change_set_risk",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ai_job_id"], ["ai_jobs.id"], name="fk_ai_change_set_job", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_ai_change_set_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_change_sets")),
        sa.UniqueConstraint("ai_job_id", name="uq_ai_change_sets_job"),
    )
    for column in (
        "project_id",
        "impact_run_id",
        "release_risk_id",
        "ai_job_id",
        "status",
        "source_fingerprint",
    ):
        op.create_index(op.f(f"ix_ai_change_sets_{column}"), "ai_change_sets", [column])


def _create_ai_change_items() -> None:
    op.create_table(
        "ai_change_items",
        sa.Column("change_set_id", sa.Uuid(), nullable=False),
        sa.Column("suggestion_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("target_resource_id", sa.Uuid(), nullable=True),
        sa.Column("target_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("proposed_content", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("review_note", sa.Text(), server_default="", nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("materialized_resource_type", sa.String(length=32), nullable=True),
        sa.Column("materialized_resource_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "item_type IN ('test_case', 'workflow', 'assertion')",
            name=op.f("ck_ai_change_items_ai_change_item_type"),
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update')", name=op.f("ck_ai_change_items_ai_change_item_action")
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_ai_change_items_ai_change_item_review_status"),
        ),
        sa.CheckConstraint(
            "(action = 'create' AND target_resource_id IS NULL) OR "
            "(action = 'update' AND target_resource_id IS NOT NULL)",
            name=op.f("ck_ai_change_items_ai_change_item_target"),
        ),
        sa.ForeignKeyConstraint(
            ["change_set_id"],
            ["ai_change_sets.id"],
            name="fk_ai_change_item_set",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["suggestion_id"],
            ["ai_suggestions.id"],
            name="fk_ai_change_item_suggestion",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_change_items")),
        sa.UniqueConstraint("change_set_id", "position", name="uq_ai_change_items_set_position"),
        sa.UniqueConstraint("suggestion_id", name=op.f("uq_ai_change_items_suggestion_id")),
    )
    for column in (
        "change_set_id",
        "item_type",
        "target_resource_id",
        "review_status",
        "materialized_resource_id",
    ):
        op.create_index(op.f(f"ix_ai_change_items_{column}"), "ai_change_items", [column])


def _drop_ai_change_items() -> None:
    for column in reversed(
        (
            "change_set_id",
            "item_type",
            "target_resource_id",
            "review_status",
            "materialized_resource_id",
        )
    ):
        op.drop_index(op.f(f"ix_ai_change_items_{column}"), table_name="ai_change_items")
    op.drop_table("ai_change_items")


def _drop_ai_change_sets() -> None:
    for column in reversed(
        (
            "project_id",
            "impact_run_id",
            "release_risk_id",
            "ai_job_id",
            "status",
            "source_fingerprint",
        )
    ):
        op.drop_index(op.f(f"ix_ai_change_sets_{column}"), table_name="ai_change_sets")
    op.drop_table("ai_change_sets")


def _drop_failure_clusters() -> None:
    for column in reversed(("project_id", "release_risk_id", "fingerprint", "failure_category")):
        op.drop_index(op.f(f"ix_failure_clusters_{column}"), table_name="failure_clusters")
    op.drop_table("failure_clusters")


def _drop_release_risks() -> None:
    for column in reversed(("project_id", "impact_run_id", "score", "risk_level", "fingerprint")):
        op.drop_index(op.f(f"ix_release_risks_{column}"), table_name="release_risks")
    op.drop_table("release_risks")


def _restore_ai_job_type() -> None:
    op.execute(sa.text("DELETE FROM ai_jobs WHERE job_type = 'change_set'"))
    op.drop_constraint(op.f("ck_ai_jobs_ai_job_type"), "ai_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_ai_jobs_ai_job_type"),
        "ai_jobs",
        "job_type IN ('schema_cases', 'assertion_suggestions', 'workflow_draft', "
        "'failure_analysis')",
    )
