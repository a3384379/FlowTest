from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class TestDesign(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Approved design aggregate; the existing TestCase model remains the executable asset."""

    __tablename__ = "test_designs"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_designs_project_name"),
        CheckConstraint(
            "status IN ('draft', 'approved', 'rejected', 'archived')",
            name="test_design_status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", index=True
    )
    intent: Mapped[dict[str, Any]] = mapped_column(JSON)
    knowledge_graph: Mapped[dict[str, Any]] = mapped_column(JSON)
    state_model: Mapped[dict[str, Any]] = mapped_column(JSON)
    scenarios: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    oracles: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    confidence: Mapped[float] = mapped_column(Float, default=1, server_default="1")
    review_requirements: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    test_case_refs: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    source_change_set_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_change_sets.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str] = mapped_column(Text, default="", server_default="")


class ChangeSetApproval(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "change_set_approvals"
    __table_args__ = (
        UniqueConstraint("change_set_id", name="uq_change_set_approvals_change_set"),
        CheckConstraint(
            "decision IN ('approved', 'rejected')", name="change_set_approval_decision"
        ),
    )

    change_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_change_sets.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16), index=True)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    approved_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
