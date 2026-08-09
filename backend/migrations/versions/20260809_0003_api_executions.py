"""Create S3 API execution history tables.

Revision ID: 20260809_0003
Revises: 20260809_0002
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0003"
down_revision: str | None = "20260809_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_call_executions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("api_definition_id", sa.Uuid(), nullable=False),
        sa.Column("api_version_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("triggered_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("request_method", sa.String(length=10), nullable=False),
        sa.Column("request_url", sa.String(length=4096), nullable=False),
        sa.Column("request_headers", sa.JSON(), nullable=False),
        sa.Column("request_body", sa.JSON(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("response_size_bytes", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'error')",
            name="api_execution_status",
        ),
        sa.ForeignKeyConstraint(
            ["api_definition_id"],
            ["api_definitions.id"],
            name=op.f("fk_api_call_executions_api_definition_id_api_definitions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["api_version_id"],
            ["api_versions.id"],
            name=op.f("fk_api_call_executions_api_version_id_api_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name=op.f("fk_api_call_executions_environment_id_environments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_api_call_executions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_id"],
            ["users.id"],
            name=op.f("fk_api_call_executions_triggered_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_call_executions")),
    )
    for column in (
        "api_definition_id",
        "api_version_id",
        "completed_at",
        "environment_id",
        "project_id",
        "started_at",
        "status",
        "triggered_by_id",
    ):
        op.create_index(op.f(f"ix_api_call_executions_{column}"), "api_call_executions", [column])

    op.create_table(
        "assertion_results",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("operator", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=2048), nullable=True),
        sa.Column("expected", sa.JSON(), nullable=True),
        sa.Column("actual", sa.JSON(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["api_call_executions.id"],
            name=op.f("fk_assertion_results_execution_id_api_call_executions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assertion_results")),
    )
    op.create_index(
        op.f("ix_assertion_results_execution_id"),
        "assertion_results",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_table("assertion_results")
    op.drop_table("api_call_executions")
