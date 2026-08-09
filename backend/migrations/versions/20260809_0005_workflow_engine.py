"""Create workflow drafts, immutable versions, snapshots, and node executions.

Revision ID: 20260809_0005
Revises: 20260809_0004
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0005"
down_revision: str | None = "20260809_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_workflows()
    _create_workflow_versions()
    _create_workflow_executions()
    _create_workflow_node_executions()


def _create_workflows() -> None:
    op.create_table(
        "workflows",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid()),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("draft_definition", sa.JSON(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("current_version", sa.Integer()),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_workflows_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folders.id"],
            ondelete="SET NULL",
            name=op.f("fk_workflows_folder_id_folders"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflows_created_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
        sa.UniqueConstraint("project_id", "name", name="uq_workflows_project_name"),
    )
    op.create_index(op.f("ix_workflows_project_id"), "workflows", ["project_id"])
    op.create_index(op.f("ix_workflows_folder_id"), "workflows", ["folder_id"])


def _create_workflow_versions() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            ondelete="CASCADE",
            name=op.f("fk_workflow_versions_workflow_id_workflows"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflow_versions_created_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_versions")),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )
    op.create_index(op.f("ix_workflow_versions_workflow_id"), "workflow_versions", ["workflow_id"])
    op.create_index(
        op.f("ix_workflow_versions_published_at"), "workflow_versions", ["published_at"]
    )


def _create_workflow_executions() -> None:
    op.create_table(
        "workflow_executions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("triggered_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'cancelled')",
            name="workflow_execution_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_workflow_executions_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflow_executions_workflow_id_workflows"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflow_executions_workflow_version_id_workflow_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflow_executions_environment_id_environments"),
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflow_executions_triggered_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_executions")),
    )
    for column in (
        "project_id",
        "workflow_id",
        "workflow_version_id",
        "environment_id",
        "triggered_by_id",
        "status",
        "cancel_requested_at",
        "started_at",
        "completed_at",
    ):
        op.create_index(op.f(f"ix_workflow_executions_{column}"), "workflow_executions", [column])


def _create_workflow_node_executions() -> None:
    op.create_table(
        "workflow_node_executions",
        sa.Column("workflow_execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("output", sa.JSON()),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'skipped', 'cancelled')",
            name="workflow_node_execution_status",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id"],
            ["workflow_executions.id"],
            ondelete="CASCADE",
            name=op.f("fk_workflow_node_executions_workflow_execution_id_workflow_executions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_node_executions")),
        sa.UniqueConstraint(
            "workflow_execution_id",
            "node_id",
            name="uq_workflow_node_executions_execution_node",
        ),
    )
    op.create_index(
        op.f("ix_workflow_node_executions_workflow_execution_id"),
        "workflow_node_executions",
        ["workflow_execution_id"],
    )
    op.create_index(
        op.f("ix_workflow_node_executions_status"), "workflow_node_executions", ["status"]
    )


def downgrade() -> None:
    op.drop_table("workflow_node_executions")
    op.drop_table("workflow_executions")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
