from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class APICallExecution(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_call_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'error')",
            name="api_execution_status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    api_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_definitions.id", ondelete="RESTRICT"), index=True
    )
    api_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_versions.id", ondelete="RESTRICT"), index=True
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), index=True
    )
    triggered_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    request_method: Mapped[str] = mapped_column(String(10))
    request_url: Mapped[str] = mapped_column(String(4096))
    request_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    request_body: Mapped[Any | None] = mapped_column(JSON)
    target_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    response_body: Mapped[Any | None] = mapped_column(JSON)
    response_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), index=True
    )
    response_size_bytes: Mapped[int | None] = mapped_column(Integer)
    elapsed_ms: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AssertionResult(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assertion_results"

    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_call_executions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(32))
    target: Mapped[str | None] = mapped_column(String(2048))
    expected: Mapped[Any | None] = mapped_column(JSON)
    actual: Mapped[Any | None] = mapped_column(JSON)
    passed: Mapped[bool]
    message: Mapped[str] = mapped_column(Text)
