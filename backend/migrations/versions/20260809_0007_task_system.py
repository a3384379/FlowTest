"""Add encrypted workflow plans, test plans, runs, and service tokens.

Revision ID: 20260809_0007
Revises: 20260809_0006
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0007"
down_revision: str | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_executions", sa.Column("run_payload_ciphertext", sa.LargeBinary()))
    op.add_column("workflow_executions", sa.Column("run_payload_nonce", sa.LargeBinary()))
    _create_test_plans()
    _create_test_plan_items()
    _create_test_plan_runs()
    _create_test_plan_run_items()
    _create_service_tokens()


def _create_test_plans() -> None:
    op.create_table(
        "test_plans",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("schedule_interval_seconds", sa.Integer()),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("webhook_secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "schedule_interval_seconds IS NULL OR schedule_interval_seconds >= 60",
            name=op.f("ck_test_plans_test_plan_schedule_interval"),
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_test_plans_project_name"),
    )
    op.create_index(op.f("ix_test_plans_project_id"), "test_plans", ["project_id"])
    op.create_index(op.f("ix_test_plans_enabled"), "test_plans", ["enabled"])
    op.create_index(op.f("ix_test_plans_next_run_at"), "test_plans", ["next_run_at"])


def _create_test_plan_items() -> None:
    op.create_table(
        "test_plan_items",
        sa.Column("test_plan_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="0", nullable=False),
        sa.Column("runtime_variables", sa.JSON(), nullable=False),
        sa.Column("runtime_headers", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_test_plan_items_test_plan_item_position")
        ),
        sa.CheckConstraint(
            "workflow_version >= 1", name=op.f("ck_test_plan_items_test_plan_item_workflow_version")
        ),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 3",
            name=op.f("ck_test_plan_items_test_plan_item_max_retries"),
        ),
        sa.ForeignKeyConstraint(["test_plan_id"], ["test_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_plan_id", "position", name="uq_test_plan_items_plan_position"),
    )
    op.create_index(op.f("ix_test_plan_items_test_plan_id"), "test_plan_items", ["test_plan_id"])
    op.create_index(op.f("ix_test_plan_items_workflow_id"), "test_plan_items", ["workflow_id"])
    op.create_index(
        op.f("ix_test_plan_items_environment_id"), "test_plan_items", ["environment_id"]
    )


def _create_test_plan_runs() -> None:
    op.create_table(
        "test_plan_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'cancelled')",
            name=op.f("ck_test_plan_runs_test_plan_run_status"),
        ),
        sa.CheckConstraint(
            "trigger_type IN ('manual', 'schedule', 'ci', 'webhook')",
            name=op.f("ck_test_plan_runs_test_plan_run_trigger_type"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_plan_id"], ["test_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("project_id", "test_plan_id", "requested_by_id", "status", "trigger_type"):
        op.create_index(op.f(f"ix_test_plan_runs_{column}"), "test_plan_runs", [column])


def _create_test_plan_run_items() -> None:
    op.create_table(
        "test_plan_run_items",
        sa.Column("test_plan_run_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("runtime_variables", sa.JSON(), nullable=False),
        sa.Column("runtime_headers", sa.JSON(), nullable=False),
        sa.Column("workflow_execution_id", sa.Uuid()),
        sa.Column("error_message", sa.Text()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'cancelled')",
            name=op.f("ck_test_plan_run_items_test_plan_run_item_status"),
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 4",
            name=op.f("ck_test_plan_run_items_test_plan_run_item_attempts"),
        ),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 3",
            name=op.f("ck_test_plan_run_items_test_plan_run_item_max_retries"),
        ),
        sa.ForeignKeyConstraint(["test_plan_run_id"], ["test_plan_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_execution_id"], ["workflow_executions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_plan_run_id", "position", name="uq_test_plan_run_items_position"),
    )
    for column in ("test_plan_run_id", "workflow_id", "workflow_execution_id", "status"):
        op.create_index(op.f(f"ix_test_plan_run_items_{column}"), "test_plan_run_items", [column])


def _create_service_tokens() -> None:
    op.create_table(
        "service_tokens",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_prefix", name="uq_service_tokens_prefix"),
    )
    for column in ("project_id", "token_prefix", "expires_at", "revoked_at"):
        op.create_index(op.f(f"ix_service_tokens_{column}"), "service_tokens", [column])


def downgrade() -> None:
    op.drop_table("service_tokens")
    op.drop_table("test_plan_run_items")
    op.drop_table("test_plan_runs")
    op.drop_table("test_plan_items")
    op.drop_table("test_plans")
    op.drop_column("workflow_executions", "run_payload_nonce")
    op.drop_column("workflow_executions", "run_payload_ciphertext")
