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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class EnvironmentTemplate(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "environment_templates"
    __table_args__ = (
        UniqueConstraint("template_key", name="uq_environment_templates_key"),
        CheckConstraint("status IN ('active', 'disabled')", name="environment_template_status"),
    )

    template_key: Mapped[str] = mapped_column(String(120), index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", index=True
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class EnvironmentTemplateVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "environment_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "version", name="uq_environment_template_versions_template_version"
        ),
        CheckConstraint("version >= 1", name="version_number"),
    )

    template_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "environment_templates.id",
            name="fk_env_template_versions_template",
            ondelete="CASCADE",
        ),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(String(64))
    signature_algorithm: Mapped[str] = mapped_column(
        String(32), default="hmac-sha256-v1", server_default="hmac-sha256-v1"
    )
    signed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class EnvironmentInstance(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "environment_instances"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "idempotency_key", name="uq_environment_instances_project_idempotency"
        ),
        UniqueConstraint("runtime_name", name="uq_environment_instances_runtime_name"),
        CheckConstraint(
            "status IN ('queued', 'provisioning', 'ready', 'failed', 'cancelled', "
            "'expired', 'cleaned')",
            name="environment_instance_status",
        ),
        CheckConstraint(
            "cleanup_status IN ('none', 'pending', 'running', 'completed', 'failed')",
            name="environment_instance_cleanup_status",
        ),
        CheckConstraint("ttl_seconds >= 60", name="environment_instance_ttl"),
        CheckConstraint("fencing_token >= 1", name="environment_instance_fencing_token"),
        CheckConstraint("cleanup_attempts >= 0", name="environment_instance_cleanup_attempts"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    template_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "environment_template_versions.id",
            name="fk_env_instances_template_version",
            ondelete="RESTRICT",
        ),
        index=True,
    )
    template_key: Mapped[str] = mapped_column(String(120), index=True)
    template_version: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued", index=True
    )
    cleanup_status: Mapped[str] = mapped_column(
        String(20), default="none", server_default="none", index=True
    )
    runtime_name: Mapped[str] = mapped_column(String(80))
    manifest_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(64))
    ttl_seconds: Mapped[int] = mapped_column(Integer)
    fencing_token: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    endpoints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    seed_evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    cleanup_error_code: Mapped[str | None] = mapped_column(String(64))
    cleanup_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
