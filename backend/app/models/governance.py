"""Organization governance persistence models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class IdempotencyRecord(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "actor_key",
            "operation",
            "idempotency_key",
            name="uq_idempotency_operation_key",
        ),
        CheckConstraint("status IN ('pending', 'completed')", name="idempotency_status"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    actor_key: Mapped[str] = mapped_column(String(160))
    operation: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OrganizationGovernance(TimestampMixin, Base):
    __tablename__ = "organization_governance"
    __table_args__ = (
        CheckConstraint(
            "audit_retention_days BETWEEN 1 AND 3650",
            name="audit_retention",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    audit_retention_days: Mapped[int] = mapped_column(
        Integer, default=365, server_default="365", nullable=False
    )
    quota_policies: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}", nullable=False
    )
    runner_policy: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}", nullable=False
    )
    active_key_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )


class OrganizationKeyVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_key_versions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "version", name="uq_organization_key_versions_org_version"
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'retiring', 'retired', 'rolled_back')",
            name="key_status",
        ),
        CheckConstraint(
            "migration_status IN ('planned', 'migrating', 'migrated', 'rolled_back')",
            name="key_migration_status",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    key_reference: Mapped[str] = mapped_column(String(200))
    key_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    migration_status: Mapped[str] = mapped_column(
        String(16), default="planned", server_default="planned", index=True
    )
    previous_version: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    migrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
