from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class Credential(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_credentials_project_name"),
        CheckConstraint(
            "kind IN ('postgresql', 'mysql', 'redis', 'grpc_mtls')",
            name="credential_kind",
        ),
        CheckConstraint("port >= 1 AND port <= 65535", name="credential_port"),
        CheckConstraint(
            "(secret_provider = 'local' AND ciphertext IS NOT NULL "
            "AND nonce IS NOT NULL AND provider_reference IS NULL) OR "
            "(secret_provider = 'vault_kv_v2' AND ciphertext IS NULL "
            "AND nonce IS NULL AND provider_reference IS NOT NULL)",
            name="credential_secret_storage",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    database_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    username: Mapped[str] = mapped_column(String(255), default="", server_default="")
    secret_provider: Mapped[str] = mapped_column(
        String(32), default="local", server_default="local", index=True
    )
    provider_reference: Mapped[str | None] = mapped_column(String(1024))
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary(12))
    tls_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class MockService(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mock_services"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_mock_services_project_name"),
        UniqueConstraint("slug", name="uq_mock_services_slug"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class MockRoute(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mock_routes"
    __table_args__ = (
        UniqueConstraint("mock_service_id", "name", name="uq_mock_routes_service_name"),
        CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')",
            name="mock_route_method",
        ),
        CheckConstraint(
            "response_status >= 100 AND response_status <= 599",
            name="mock_status_code",
        ),
        CheckConstraint("delay_ms >= 0 AND delay_ms <= 30000", name="mock_delay_ms"),
        CheckConstraint("priority >= -1000 AND priority <= 1000", name="mock_priority"),
    )

    mock_service_id: Mapped[UUID] = mapped_column(
        ForeignKey("mock_services.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    method: Mapped[str] = mapped_column(String(10), index=True)
    path_pattern: Mapped[str] = mapped_column(String(1024))
    query_conditions: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    header_conditions: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    response_status: Mapped[int] = mapped_column(Integer, default=200, server_default="200")
    response_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    response_body: Mapped[Any | None] = mapped_column(JSON)
    delay_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    scenario: Mapped[str | None] = mapped_column(String(80), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class MockRequestLog(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mock_request_logs"

    mock_service_id: Mapped[UUID] = mapped_column(
        ForeignKey("mock_services.id", ondelete="CASCADE"), index=True
    )
    mock_route_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("mock_routes.id", ondelete="SET NULL"), index=True
    )
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(2048))
    query_parameters: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    body: Mapped[Any | None] = mapped_column(JSON)
    matched: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    scenario: Mapped[str | None] = mapped_column(String(80))
    response_status: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
