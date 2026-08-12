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
            "'workflow_draft', 'failure_analysis', 'change_set')",
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


class AIChangeSet(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_change_sets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('generating', 'draft', 'partially_reviewed', 'accepted', "
            "'rejected', 'failed')",
            name="ai_change_set_status",
        ),
        UniqueConstraint("ai_job_id", name="uq_ai_change_sets_job"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_ai_change_set_project", ondelete="CASCADE"),
        index=True,
    )
    impact_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("impact_runs.id", name="fk_ai_change_set_impact", ondelete="RESTRICT"),
        index=True,
    )
    release_risk_id: Mapped[UUID] = mapped_column(
        ForeignKey("release_risks.id", name="fk_ai_change_set_risk", ondelete="RESTRICT"),
        index=True,
    )
    ai_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_jobs.id", name="fk_ai_change_set_job", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(24), default="generating", server_default="generating", index=True
    )
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_ai_change_set_creator", ondelete="RESTRICT")
    )


class AIChangeItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_change_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('test_case', 'workflow', 'assertion')",
            name="ai_change_item_type",
        ),
        CheckConstraint("action IN ('create', 'update')", name="ai_change_item_action"),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ai_change_item_review_status",
        ),
        CheckConstraint(
            "(action = 'create' AND target_resource_id IS NULL) OR "
            "(action = 'update' AND target_resource_id IS NOT NULL)",
            name="ai_change_item_target",
        ),
        UniqueConstraint("change_set_id", "position", name="uq_ai_change_items_set_position"),
    )

    change_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_change_sets.id", name="fk_ai_change_item_set", ondelete="CASCADE"),
        index=True,
    )
    suggestion_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_suggestions.id", name="fk_ai_change_item_suggestion", ondelete="CASCADE"),
        unique=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    target_resource_id: Mapped[UUID | None] = mapped_column(index=True)
    target_snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    proposed_content: Mapped[dict[str, Any]] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    review_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    materialized_resource_type: Mapped[str | None] = mapped_column(String(32))
    materialized_resource_id: Mapped[UUID | None] = mapped_column(index=True)
