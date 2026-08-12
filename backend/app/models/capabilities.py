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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class Plugin(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plugins"
    __table_args__ = (
        UniqueConstraint("plugin_key", "version", name="uq_plugins_plugin_key_version"),
        UniqueConstraint("oci_digest", name="uq_plugins_oci_digest"),
        CheckConstraint(
            "status IN ('pending', 'active', 'disabled')",
            name="plugin_status",
        ),
    )

    plugin_key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(120))
    oci_repository: Mapped[str] = mapped_column(String(500))
    oci_digest: Mapped[str] = mapped_column(String(71))
    signature_identity: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class Capability(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "capabilities"
    __table_args__ = (
        UniqueConstraint(
            "capability_key",
            "version",
            name="uq_capabilities_capability_key_version",
        ),
        CheckConstraint("source IN ('builtin', 'plugin')", name="capability_source"),
    )

    capability_key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32), index=True)
    runner_type: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    schema_hash: Mapped[str] = mapped_column(String(64), index=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    plugin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("plugins.id", ondelete="RESTRICT"),
        index=True,
    )


class RunnerPool(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runner_pools"
    __table_args__ = (UniqueConstraint("name", name="uq_runner_pools_name"),)

    name: Mapped[str] = mapped_column(String(120))
    runner_type: Mapped[str] = mapped_column(String(32), index=True)
    network_zone: Mapped[str] = mapped_column(String(100), default="default")
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class Runner(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runners"
    __table_args__ = (
        UniqueConstraint("pool_id", "name", name="uq_runners_pool_name"),
        UniqueConstraint("identity_fingerprint", name="uq_runners_identity_fingerprint"),
        CheckConstraint(
            "status IN ('offline', 'online', 'draining', 'disabled')",
            name="runner_status",
        ),
    )

    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("runner_pools.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120))
    identity_fingerprint: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16),
        default="offline",
        server_default="offline",
        index=True,
    )
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_load: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
