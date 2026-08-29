"""Persistence models for immutable V6 test-context revisions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class TestContext(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_contexts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('collecting', 'ready', 'incomplete', 'conflicted', 'expired', 'closed')",
            name="test_context_status",
        ),
        CheckConstraint("current_revision >= 1", name="test_context_current_revision_positive"),
        CheckConstraint(
            "created_by_type IN ('user', 'service_account')",
            name="test_context_creator_type",
        ),
        Index("ix_test_contexts_project_status", "project_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    target_environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default="collecting", server_default="collecting", index=True
    )
    current_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_type: Mapped[str] = mapped_column(String(24))
    created_by_id: Mapped[UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class TestContextRevision(UuidPrimaryKeyMixin, Base):
    __tablename__ = "test_context_revisions"
    __table_args__ = (
        UniqueConstraint(
            "context_id", "revision", name="uq_test_context_revisions_context_revision"
        ),
        CheckConstraint("revision >= 1", name="test_context_revision_positive"),
        CheckConstraint(
            "created_by_type IN ('user', 'service_account')",
            name="test_context_revision_creator_type",
        ),
        Index("ix_test_context_revisions_context_fingerprint", "context_id", "fingerprint"),
    )

    context_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_contexts.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    repository_revisions: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    contract_revisions: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    data_profile_revisions: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    existing_test_revision: Mapped[dict[str, str] | None] = mapped_column(JSON)
    knowledge_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    completeness: Mapped[dict[str, Any]] = mapped_column(JSON)
    conflict_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_fingerprints: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_by_type: Mapped[str] = mapped_column(String(24))
    created_by_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContextEvidenceItem(UuidPrimaryKeyMixin, Base):
    __tablename__ = "context_evidence_items"
    __table_args__ = (
        UniqueConstraint(
            "context_revision_id",
            "fingerprint",
            name="uq_context_evidence_revision_fingerprint",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="context_evidence_confidence"),
        CheckConstraint(
            "source_type IN ('repository', 'contract', 'data_profile', "
            "'service_topology', 'existing_test', 'workflow', 'runtime', 'change', "
            "'user_confirmed_rule', 'database')",
            name="context_evidence_source_type",
        ),
        CheckConstraint(
            "semantic_role IN ('normative', 'observed', 'mixed', 'coverage', "
            "'supporting', 'conflict')",
            name="context_evidence_semantic_role",
        ),
        CheckConstraint(
            "data_classification = 'internal_redacted'",
            name="context_evidence_classification",
        ),
        Index("ix_context_evidence_source", "source_ref", "source_revision"),
    )

    context_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_context_revisions.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    provider_name: Mapped[str] = mapped_column(String(160))
    provider_version: Mapped[str] = mapped_column(String(80))
    source_ref: Mapped[str] = mapped_column(String(512), index=True)
    source_revision: Mapped[str] = mapped_column(String(160))
    subject_ref: Mapped[str] = mapped_column(String(512), index=True)
    finding_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    semantic_role: Mapped[str] = mapped_column(String(24), index=True)
    deterministic: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    redactions: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    warnings: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, server_default="[]")
    data_classification: Mapped[str] = mapped_column(
        String(32), default="internal_redacted", server_default="internal_redacted"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@event.listens_for(TestContextRevision, "before_update")
@event.listens_for(ContextEvidenceItem, "before_update")
def _prevent_revision_snapshot_mutation(*_: object) -> None:
    raise ValueError("Test context revision snapshots are immutable")
