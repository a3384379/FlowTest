from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class RunnerRegistrationToken(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runner_registration_tokens"

    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_pools.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class RunnerTask(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runner_tasks"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_runner_tasks_execution"),
        Index(
            "ix_runner_task_claim",
            "status",
            "required_runner_type",
            "priority",
            "available_at",
        ),
        CheckConstraint(
            "status IN ('queued', 'leased', 'completed', 'failed', 'cancelled')",
            name="runner_task_status",
        ),
        CheckConstraint("priority BETWEEN 0 AND 9", name="runner_task_priority"),
        CheckConstraint(
            "attempts BETWEEN 0 AND max_attempts AND max_attempts BETWEEN 1 AND 10",
            name="runner_task_attempts",
        ),
    )

    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    required_runner_type: Mapped[str] = mapped_column(String(32), index=True)
    required_labels: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    required_capabilities: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued", index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    selected_runner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runners.id", ondelete="SET NULL"), index=True
    )
    last_lease_id: Mapped[UUID | None] = mapped_column(index=True)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class RunnerLeaseRecord(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runner_leases"
    __table_args__ = (
        UniqueConstraint("task_id", "fencing_token", name="uq_runner_lease_task_fence"),
        Index(
            "uq_runner_lease_active_task",
            "task_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'expired', 'released')",
            name="runner_lease_status",
        ),
        CheckConstraint("fencing_token >= 1", name="runner_lease_fence"),
    )

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_tasks.id", ondelete="CASCADE"), index=True
    )
    runner_id: Mapped[UUID] = mapped_column(
        ForeignKey("runners.id", ondelete="RESTRICT"), index=True
    )
    fencing_token: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", index=True
    )
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunnerEvent(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runner_events"

    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_pools.id", ondelete="CASCADE"), index=True
    )
    runner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runners.id", ondelete="SET NULL"), index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runner_tasks.id", ondelete="CASCADE"), index=True
    )
    lease_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runner_leases.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
