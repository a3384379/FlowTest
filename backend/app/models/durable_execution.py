from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ExecutionCommand(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Durable command envelope for start, resume, retry, and cancel operations."""

    __tablename__ = "execution_commands"
    __table_args__ = (
        Index("ix_execution_commands_execution_created", "execution_id", "created_at"),
        CheckConstraint(
            "command_type IN ('start', 'resume', 'retry', 'cancel')",
            name="execution_command_type",
        ),
        CheckConstraint(
            "status IN ('accepted', 'dispatched', 'completed', 'failed', 'rejected')",
            name="execution_command_status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True
    )
    command_type: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="accepted", server_default="accepted", index=True
    )
    actor_key: Mapped[str] = mapped_column(String(160))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    fencing_token: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionCheckpoint(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Redacted node checkpoint used to resume an immutable execution plan."""

    __tablename__ = "execution_checkpoints"
    __table_args__ = (
        Index("ix_execution_checkpoints_execution_status", "execution_id", "status"),
        UniqueConstraint(
            "execution_id",
            "node_id",
            "attempt",
            name="uq_execution_checkpoint_node_attempt",
        ),
        CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'skipped', 'cancelled')",
            name="execution_checkpoint_status",
        ),
        CheckConstraint("attempt >= 0", name="execution_checkpoint_attempt"),
        CheckConstraint("fencing_token >= 0", name="execution_checkpoint_fence"),
        CheckConstraint("phase IN ('main', 'cleanup')", name="execution_checkpoint_phase"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str] = mapped_column(String(128))
    node_type: Mapped[str] = mapped_column(String(32))
    node_name: Mapped[str] = mapped_column(String(200))
    phase: Mapped[str] = mapped_column(String(16), default="main", server_default="main")
    best_effort: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    attempt: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    output_digest: Mapped[str] = mapped_column(String(64))
    output: Mapped[Any | None] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    extracted_variables: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_id: Mapped[UUID | None] = mapped_column(index=True)
    runner_id: Mapped[UUID | None] = mapped_column(index=True)
