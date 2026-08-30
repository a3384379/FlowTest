from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class SandboxPreviewApproval(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sandbox_preview_approvals"
    __table_args__ = (
        CheckConstraint(
            "executor_kind IN ('user', 'service_account')",
            name="preview_approval_executor_kind",
        ),
        CheckConstraint(
            "(consumed_at IS NULL AND execution_id IS NULL) OR "
            "(consumed_at IS NOT NULL AND execution_id IS NOT NULL)",
            name="preview_approval_consumption",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    change_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_change_sets.id", ondelete="CASCADE"), index=True
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), index=True
    )
    environment_fingerprint: Mapped[str] = mapped_column(String(64))
    executor_kind: Mapped[str] = mapped_column(String(24), index=True)
    executor_id: Mapped[UUID] = mapped_column(index=True)
    proposal_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    context_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_context_revisions.id", ondelete="RESTRICT"), index=True
    )
    context_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "workflow_executions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_sandbox_preview_approvals_execution_id_workflow_executions",
        ),
        index=True,
    )
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
