from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class Service(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A project-local logical request service.

    This intentionally does not reuse the Contract Hub service catalog.  A target
    service owns runtime routing metadata and is identified across instances by
    ``service_key`` rather than by its database UUID.
    """

    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("project_id", "service_key", name="uq_services_project_service_key"),
        CheckConstraint("service_key <> ''", name="service_service_key_not_empty"),
        CheckConstraint(
            "service_type IN ('http', 'https', 'grpc', 'graphql', 'other')", name="service_type"
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    service_key: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    owner_team: Mapped[str | None] = mapped_column(String(160))
    service_type: Mapped[str] = mapped_column(String(16), default="http", server_default="http")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class ServiceEndpoint(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A concrete endpoint variant for a service in one environment."""

    __tablename__ = "service_endpoints"
    __table_args__ = (
        UniqueConstraint(
            "environment_id",
            "service_id",
            "variant",
            name="uq_service_endpoints_environment_service_variant",
        ),
        CheckConstraint("variant <> ''", name="service_endpoint_variant_not_empty"),
        CheckConstraint(
            "connect_timeout_ms BETWEEN 100 AND 300000",
            name="service_endpoint_connect_timeout",
        ),
        CheckConstraint(
            "read_timeout_ms BETWEEN 100 AND 300000",
            name="service_endpoint_read_timeout",
        ),
        CheckConstraint(
            "health_expected_status IS NULL OR health_expected_status BETWEEN 100 AND 599",
            name="service_endpoint_health_status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), index=True
    )
    variant: Mapped[str] = mapped_column(String(80), default="default", server_default="default")
    base_url: Mapped[str] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    connect_timeout_ms: Mapped[int] = mapped_column(Integer, default=5000, server_default="5000")
    read_timeout_ms: Mapped[int] = mapped_column(Integer, default=30000, server_default="30000")
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    proxy_ref: Mapped[str | None] = mapped_column(String(255))
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    variables: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    secret_refs: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    health_check_path: Mapped[str | None] = mapped_column(String(2048))
    health_expected_status: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    def snapshot_metadata(self) -> dict[str, Any]:
        return {
            "endpoint_id": str(self.id),
            "variant": self.variant,
            "revision": self.revision,
            "connect_timeout_ms": self.connect_timeout_ms,
            "read_timeout_ms": self.read_timeout_ms,
            "tls_verify": self.tls_verify,
            "proxy_ref": self.proxy_ref,
            "secret_refs": list(self.secret_refs),
        }
