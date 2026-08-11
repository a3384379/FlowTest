"""Add reviewable AI jobs and suggestions.

Revision ID: 20260812_0018
Revises: 20260811_0017
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0018"
down_revision: str | None = "20260811_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "ai_sample_sharing_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "ai_jobs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("sanitized_input", sa.JSON(), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("sample_included", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("token_usage", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_message", sa.String(length=500)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "job_type IN ('schema_cases', 'assertion_suggestions', "
            "'workflow_draft', 'failure_analysis')",
            name=op.f("ck_ai_jobs_ai_job_type"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_ai_jobs_ai_job_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_ai_jobs_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_ai_jobs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_jobs")),
    )
    op.create_index(op.f("ix_ai_jobs_project_id"), "ai_jobs", ["project_id"])
    op.create_index(op.f("ix_ai_jobs_job_type"), "ai_jobs", ["job_type"])
    op.create_index(op.f("ix_ai_jobs_status"), "ai_jobs", ["status"])
    op.create_index(op.f("ix_ai_jobs_input_sha256"), "ai_jobs", ["input_sha256"])
    op.create_table(
        "ai_suggestions",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("suggestion_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("review_note", sa.Text(), server_default="", nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_resource_type", sa.String(length=32)),
        sa.Column("accepted_resource_id", sa.Uuid()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "suggestion_type IN ('test_case', 'assertion', 'workflow', 'failure_analysis')",
            name=op.f("ck_ai_suggestions_ai_suggestion_type"),
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_ai_suggestions_ai_suggestion_review_status"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ai_jobs.id"],
            name=op.f("fk_ai_suggestions_job_id_ai_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name=op.f("fk_ai_suggestions_reviewed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_suggestions")),
        sa.UniqueConstraint("job_id", "position", name="uq_ai_suggestions_job_position"),
    )
    op.create_index(op.f("ix_ai_suggestions_job_id"), "ai_suggestions", ["job_id"])
    op.create_index(
        op.f("ix_ai_suggestions_suggestion_type"), "ai_suggestions", ["suggestion_type"]
    )
    op.create_index(op.f("ix_ai_suggestions_review_status"), "ai_suggestions", ["review_status"])
    op.create_index(
        op.f("ix_ai_suggestions_accepted_resource_id"),
        "ai_suggestions",
        ["accepted_resource_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_suggestions_accepted_resource_id"), table_name="ai_suggestions")
    op.drop_index(op.f("ix_ai_suggestions_review_status"), table_name="ai_suggestions")
    op.drop_index(op.f("ix_ai_suggestions_suggestion_type"), table_name="ai_suggestions")
    op.drop_index(op.f("ix_ai_suggestions_job_id"), table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
    op.drop_index(op.f("ix_ai_jobs_input_sha256"), table_name="ai_jobs")
    op.drop_index(op.f("ix_ai_jobs_status"), table_name="ai_jobs")
    op.drop_index(op.f("ix_ai_jobs_job_type"), table_name="ai_jobs")
    op.drop_index(op.f("ix_ai_jobs_project_id"), table_name="ai_jobs")
    op.drop_table("ai_jobs")
    op.drop_column("projects", "ai_sample_sharing_enabled")
