"""Add PostgreSQL runner tasks, leases, fencing, and worker profiles.

Revision ID: 20260812_0026
Revises: 20260812_0025
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0026"
down_revision: str | None = "20260812_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _extend_runner_profiles()
    _expand_project_concurrency()
    _add_queued_execution_status()
    _create_registration_tokens()
    _create_runner_tasks()
    _create_runner_leases()
    _create_runner_events()


def downgrade() -> None:
    _drop_runner_events()
    _drop_runner_leases()
    _drop_runner_tasks()
    _drop_registration_tokens()
    _remove_queued_execution_status()
    _restore_project_concurrency()
    _restore_runner_profiles()


def _extend_runner_profiles() -> None:
    op.add_column(
        "runner_pools",
        sa.Column("runtime", sa.String(length=16), server_default="docker", nullable=False),
    )
    op.add_column(
        "runner_pools",
        sa.Column("capabilities", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "runner_pools",
        sa.Column("lease_timeout_seconds", sa.Integer(), server_default="30", nullable=False),
    )
    op.add_column(
        "runner_pools",
        sa.Column("heartbeat_timeout_seconds", sa.Integer(), server_default="90", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_runner_pools_runner_pool_runtime"),
        "runner_pools",
        "runtime IN ('docker', 'kubernetes')",
    )
    op.create_check_constraint(
        op.f("ck_runner_pools_runner_pool_concurrency"),
        "runner_pools",
        "max_concurrency BETWEEN 1 AND 500",
    )
    op.create_check_constraint(
        op.f("ck_runner_pools_runner_pool_lease_timeout"),
        "runner_pools",
        "lease_timeout_seconds BETWEEN 10 AND 300",
    )
    op.create_check_constraint(
        op.f("ck_runner_pools_runner_pool_heartbeat_timeout"),
        "runner_pools",
        "heartbeat_timeout_seconds BETWEEN 15 AND 600 "
        "AND heartbeat_timeout_seconds > lease_timeout_seconds",
    )

    for column in (
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("runtime", sa.String(length=16), server_default="docker", nullable=False),
        sa.Column("agent_version", sa.String(length=64), server_default="unknown", nullable=False),
        sa.Column("architecture", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default="1", nullable=False),
        sa.Column("draining_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("runners", column)
    op.create_index(op.f("ix_runners_token_hash"), "runners", ["token_hash"], unique=True)
    op.create_check_constraint(
        op.f("ck_runners_runner_runtime"), "runners", "runtime IN ('docker', 'kubernetes')"
    )
    op.create_check_constraint(
        op.f("ck_runners_runner_concurrency"),
        "runners",
        "max_concurrency BETWEEN 1 AND 500",
    )
    op.create_check_constraint(
        op.f("ck_runners_runner_load"),
        "runners",
        "current_load BETWEEN 0 AND max_concurrency",
    )


def _expand_project_concurrency() -> None:
    op.drop_constraint(
        op.f("ck_projects_project_execution_concurrency_limit"),
        "projects",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_projects_project_execution_concurrency_limit"),
        "projects",
        "execution_concurrency_limit BETWEEN 1 AND 500",
    )


def _add_queued_execution_status() -> None:
    op.drop_constraint(
        op.f("ck_workflow_executions_workflow_execution_status"),
        "workflow_executions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_workflow_executions_workflow_execution_status"),
        "workflow_executions",
        "status IN ('queued', 'running', 'passed', 'failed', 'cancelled')",
    )


def _create_registration_tokens() -> None:
    op.create_table(
        "runner_registration_tokens",
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"], ["runner_pools.id"], name="fk_runner_reg_pool", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name="fk_runner_reg_creator", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_registration_tokens")),
    )
    for column in ("pool_id", "token_hash", "expires_at", "consumed_at"):
        op.create_index(
            op.f(f"ix_runner_registration_tokens_{column}"),
            "runner_registration_tokens",
            [column],
            unique=column == "token_hash",
        )


def _create_runner_tasks() -> None:
    op.create_table(
        "runner_tasks",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("required_runner_type", sa.String(length=32), nullable=False),
        sa.Column("required_labels", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("required_capabilities", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="5", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("fencing_token", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selected_runner_id", sa.Uuid(), nullable=True),
        sa.Column("last_lease_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'leased', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_runner_tasks_runner_task_status"),
        ),
        sa.CheckConstraint(
            "priority BETWEEN 0 AND 9", name=op.f("ck_runner_tasks_runner_task_priority")
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND max_attempts AND max_attempts BETWEEN 1 AND 10",
            name=op.f("ck_runner_tasks_runner_task_attempts"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name="fk_runner_task_execution",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_runner_task_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["selected_runner_id"],
            ["runners.id"],
            name="fk_runner_task_runner",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_tasks")),
        sa.UniqueConstraint("execution_id", name="uq_runner_tasks_execution"),
    )
    for column in (
        "execution_id",
        "project_id",
        "required_runner_type",
        "status",
        "available_at",
        "selected_runner_id",
        "last_lease_id",
        "completed_at",
    ):
        op.create_index(op.f(f"ix_runner_tasks_{column}"), "runner_tasks", [column])
    op.create_index(
        "ix_runner_task_claim",
        "runner_tasks",
        ["status", "required_runner_type", "priority", "available_at"],
    )


def _create_runner_leases() -> None:
    op.create_table(
        "runner_leases",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("runner_id", sa.Uuid(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_renewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'expired', 'released')",
            name=op.f("ck_runner_leases_runner_lease_status"),
        ),
        sa.CheckConstraint("fencing_token >= 1", name=op.f("ck_runner_leases_runner_lease_fence")),
        sa.ForeignKeyConstraint(
            ["task_id"], ["runner_tasks.id"], name="fk_runner_lease_task", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"], ["runners.id"], name="fk_runner_lease_runner", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_leases")),
        sa.UniqueConstraint("task_id", "fencing_token", name="uq_runner_lease_task_fence"),
    )
    for column in ("task_id", "runner_id", "status", "acquired_at", "expires_at"):
        op.create_index(op.f(f"ix_runner_leases_{column}"), "runner_leases", [column])
    op.create_index(
        "uq_runner_lease_active_task",
        "runner_leases",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def _create_runner_events() -> None:
    op.create_table(
        "runner_events",
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("runner_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"], ["runner_pools.id"], name="fk_runner_event_pool", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"], ["runners.id"], name="fk_runner_event_runner", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["runner_tasks.id"], name="fk_runner_event_task", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"], ["runner_leases.id"], name="fk_runner_event_lease", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_events")),
    )
    for column in ("pool_id", "runner_id", "task_id", "lease_id", "kind"):
        op.create_index(op.f(f"ix_runner_events_{column}"), "runner_events", [column])


def _drop_runner_events() -> None:
    for column in reversed(("pool_id", "runner_id", "task_id", "lease_id", "kind")):
        op.drop_index(op.f(f"ix_runner_events_{column}"), table_name="runner_events")
    op.drop_table("runner_events")


def _drop_runner_leases() -> None:
    op.drop_index("uq_runner_lease_active_task", table_name="runner_leases")
    for column in reversed(("task_id", "runner_id", "status", "acquired_at", "expires_at")):
        op.drop_index(op.f(f"ix_runner_leases_{column}"), table_name="runner_leases")
    op.drop_table("runner_leases")


def _drop_runner_tasks() -> None:
    op.drop_index("ix_runner_task_claim", table_name="runner_tasks")
    for column in reversed(
        (
            "execution_id",
            "project_id",
            "required_runner_type",
            "status",
            "available_at",
            "selected_runner_id",
            "last_lease_id",
            "completed_at",
        )
    ):
        op.drop_index(op.f(f"ix_runner_tasks_{column}"), table_name="runner_tasks")
    op.drop_table("runner_tasks")


def _drop_registration_tokens() -> None:
    for column in reversed(("pool_id", "token_hash", "expires_at", "consumed_at")):
        op.drop_index(
            op.f(f"ix_runner_registration_tokens_{column}"),
            table_name="runner_registration_tokens",
        )
    op.drop_table("runner_registration_tokens")


def _restore_project_concurrency() -> None:
    op.execute(
        sa.text(
            "UPDATE projects SET execution_concurrency_limit = 100 "
            "WHERE execution_concurrency_limit > 100"
        )
    )
    op.drop_constraint(
        op.f("ck_projects_project_execution_concurrency_limit"),
        "projects",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_projects_project_execution_concurrency_limit"),
        "projects",
        "execution_concurrency_limit BETWEEN 1 AND 100",
    )


def _remove_queued_execution_status() -> None:
    op.execute(
        sa.text(
            "UPDATE workflow_executions SET status = 'cancelled', "
            "error_code = 'RUNNER_FABRIC_DOWNGRADE', "
            "error_message = 'Runner Fabric downgrade cancelled queued execution', "
            "completed_at = now() WHERE status = 'queued'"
        )
    )
    op.drop_constraint(
        op.f("ck_workflow_executions_workflow_execution_status"),
        "workflow_executions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_workflow_executions_workflow_execution_status"),
        "workflow_executions",
        "status IN ('running', 'passed', 'failed', 'cancelled')",
    )


def _restore_runner_profiles() -> None:
    op.drop_constraint(op.f("ck_runners_runner_load"), "runners", type_="check")
    op.drop_constraint(op.f("ck_runners_runner_concurrency"), "runners", type_="check")
    op.drop_constraint(op.f("ck_runners_runner_runtime"), "runners", type_="check")
    op.drop_index(op.f("ix_runners_token_hash"), table_name="runners")
    for column in reversed(
        (
            "token_hash",
            "runtime",
            "agent_version",
            "architecture",
            "max_concurrency",
            "draining_requested_at",
            "disabled_at",
        )
    ):
        op.drop_column("runners", column)
    op.drop_constraint(
        op.f("ck_runner_pools_runner_pool_heartbeat_timeout"),
        "runner_pools",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_runner_pools_runner_pool_lease_timeout"),
        "runner_pools",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_runner_pools_runner_pool_concurrency"),
        "runner_pools",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_runner_pools_runner_pool_runtime"),
        "runner_pools",
        type_="check",
    )
    for column in reversed(
        ("runtime", "capabilities", "lease_timeout_seconds", "heartbeat_timeout_seconds")
    ):
        op.drop_column("runner_pools", column)
