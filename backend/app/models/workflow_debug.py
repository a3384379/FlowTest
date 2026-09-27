"""Bounded iteration-debug sessions tied to durable workflow executions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WorkflowDebugSession(TimestampMixin, Base):
    __tablename__ = "workflow_debug_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('armed', 'running', 'paused', 'completed', 'expired', 'cancelled')",
            name="workflow_debug_session_status",
        ),
        CheckConstraint("pause_before_index >= 0", name="workflow_debug_pause_index"),
        CheckConstraint("last_completed_index >= -1", name="workflow_debug_completed_index"),
        CheckConstraint(
            "step_target_index IS NULL OR step_target_index >= 0",
            name="workflow_debug_step_index",
        ),
    )

    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    target_node_id: Mapped[str] = mapped_column(String(128))
    pause_before_index: Mapped[int] = mapped_column(Integer)
    pause_on_error: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="armed", nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(String(32))
    paused_input_index: Mapped[int | None] = mapped_column(Integer)
    last_completed_index: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    step_target_index: Mapped[int | None] = mapped_column(Integer)
    initial_pause_consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
