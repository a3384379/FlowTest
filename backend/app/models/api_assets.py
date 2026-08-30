from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.api_assets import AuthKind, BodyKind, HttpMethod
from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class Environment(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "environments"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_environments_project_name"),
        CheckConstraint(
            "classification IN ('unclassified', 'test', 'sandbox', 'staging', 'production')",
            name="environment_classification",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(2048))
    classification: Mapped[str] = mapped_column(
        String(24), default="unclassified", server_default="unclassified", index=True
    )
    default_service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    variables: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class Secret(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "secrets"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "environment_id",
            "name",
            name="uq_secrets_project_environment_name",
            postgresql_nulls_not_distinct=True,
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary(12))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class APIDefinition(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_definitions"
    __table_args__ = (
        Index("ix_api_definitions_project_folder", "project_id", "folder_id"),
        UniqueConstraint("project_id", "import_key", name="uq_api_definitions_project_import_key"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", index=True
    )
    import_key: Mapped[str | None] = mapped_column(String(64), index=True)
    import_fingerprint: Mapped[str | None] = mapped_column(String(64))
    import_source: Mapped[str | None] = mapped_column(String(255), index=True)
    import_source_key: Mapped[str | None] = mapped_column(String(512), index=True)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class APIVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_versions"
    __table_args__ = (
        UniqueConstraint("api_definition_id", "version", name="uq_api_versions_definition_version"),
        CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')", name="api_http_method"
        ),
        CheckConstraint(
            "body_kind IN ('none', 'json', 'raw', 'form', 'multipart')",
            name="api_body_kind",
        ),
        CheckConstraint(
            "auth_kind IN ('none', 'bearer', 'basic', 'api_key')", name="api_auth_kind"
        ),
    )

    api_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_definitions.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(2048))
    query_parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    variables: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    body_kind: Mapped[str] = mapped_column(String(16), default=BodyKind.NONE.value)
    body: Mapped[Any | None] = mapped_column(JSON)
    auth_kind: Mapped[str] = mapped_column(String(16), default=AuthKind.NONE.value)
    auth_config: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    extraction_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    canonical_contract: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    contract_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    contract_completeness: Mapped[str] = mapped_column(
        String(32), default="legacy_partial", server_default="legacy_partial"
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    @property
    def http_method(self) -> HttpMethod:
        return HttpMethod(self.method)
