from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class TestPlan(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_plans_project_name"),
        CheckConstraint(
            "schedule_interval_seconds IS NULL OR schedule_interval_seconds >= 60",
            name="test_plan_schedule_interval",
        ),
        CheckConstraint(
            "NOT (schedule_interval_seconds IS NOT NULL AND schedule_cron IS NOT NULL)",
            name="test_plan_schedule_kind",
        ),
        CheckConstraint("queue_priority BETWEEN 0 AND 9", name="test_plan_queue_priority"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    schedule_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    schedule_cron: Mapped[str | None] = mapped_column(String(120))
    schedule_timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Shanghai", server_default="Asia/Shanghai"
    )
    queue_priority: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    webhook_secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    webhook_secret_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class TestPlanItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_plan_items"
    __table_args__ = (
        UniqueConstraint("test_plan_id", "position", name="uq_test_plan_items_plan_position"),
        CheckConstraint("position >= 0", name="test_plan_item_position"),
        CheckConstraint(
            "target_type IN ('workflow', 'case', 'suite')",
            name="test_plan_item_target_type",
        ),
        CheckConstraint("target_version >= 1", name="test_plan_item_target_version"),
        CheckConstraint(
            "target_type != 'workflow' OR "
            "(workflow_id IS NOT NULL AND environment_id IS NOT NULL AND workflow_version >= 1)",
            name="test_plan_item_workflow_target",
        ),
        CheckConstraint("max_retries BETWEEN 0 AND 3", name="test_plan_item_max_retries"),
    )

    test_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_plans.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(
        String(16), default="workflow", server_default="workflow"
    )
    target_id: Mapped[UUID] = mapped_column(index=True)
    target_version: Mapped[int] = mapped_column(Integer)
    workflow_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="RESTRICT"), index=True
    )
    environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), index=True
    )
    workflow_version: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    max_retries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    runtime_variables: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    runtime_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class TestPlanRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_plan_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'cancelled')",
            name="test_plan_run_status",
        ),
        CheckConstraint(
            "trigger_type IN ('manual', 'schedule', 'ci', 'webhook')",
            name="test_plan_run_trigger_type",
        ),
        CheckConstraint("queue_priority BETWEEN 0 AND 9", name="test_plan_run_queue_priority"),
        CheckConstraint("queue_name IN ('general', 'data', 'ai')", name="test_plan_run_queue_name"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    test_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_plans.id", ondelete="RESTRICT"), index=True
    )
    requested_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    trigger_type: Mapped[str] = mapped_column(String(16), index=True)
    queue_priority: Mapped[int] = mapped_column(Integer, default=5, server_default="5", index=True)
    queue_name: Mapped[str] = mapped_column(String(16), default="general", server_default="general")
    baseline_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_plan_runs.id", ondelete="SET NULL"), index=True
    )
    quality_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class TestPlanRunItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_plan_run_items"
    __table_args__ = (
        UniqueConstraint("test_plan_run_id", "position", name="uq_test_plan_run_items_position"),
        CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'cancelled', 'quarantined')",
            name="test_plan_run_item_status",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 4", name="test_plan_run_item_attempts"),
        CheckConstraint("max_retries BETWEEN 0 AND 3", name="test_plan_run_item_max_retries"),
        CheckConstraint(
            "target_type IN ('workflow', 'case')",
            name="test_plan_run_item_target_type",
        ),
        CheckConstraint("target_version >= 1", name="test_plan_run_item_target_version"),
    )

    test_plan_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_plan_runs.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(
        String(16), default="workflow", server_default="workflow"
    )
    target_id: Mapped[UUID] = mapped_column(index=True)
    target_version: Mapped[int] = mapped_column(Integer)
    target_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="RESTRICT"), index=True
    )
    environment_id: Mapped[UUID] = mapped_column(ForeignKey("environments.id", ondelete="RESTRICT"))
    workflow_version: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    max_retries: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), index=True)
    runtime_variables: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    runtime_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    workflow_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="SET NULL"), index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class ServiceToken(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "service_tokens"
    __table_args__ = (UniqueConstraint("token_prefix", name="uq_service_tokens_prefix"),)

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    token_prefix: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
