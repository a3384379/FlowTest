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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class AIJob(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('schema_cases', 'assertion_suggestions', "
            "'workflow_draft', 'failure_analysis')",
            name="ai_job_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ai_job_status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    sanitized_input: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_sha256: Mapped[str] = mapped_column(String(64), index=True)
    prompt_template_version: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str] = mapped_column(String(200))
    sample_included: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    token_usage: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class AISuggestion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_suggestions"
    __table_args__ = (
        CheckConstraint(
            "suggestion_type IN ('test_case', 'assertion', 'workflow', 'failure_analysis')",
            name="ai_suggestion_type",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ai_suggestion_review_status",
        ),
        UniqueConstraint("job_id", "position", name="uq_ai_suggestions_job_position"),
    )

    job_id: Mapped[UUID] = mapped_column(ForeignKey("ai_jobs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    suggestion_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    review_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_resource_type: Mapped[str | None] = mapped_column(String(32))
    accepted_resource_id: Mapped[UUID | None] = mapped_column(index=True)
