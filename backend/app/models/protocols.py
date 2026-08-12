from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
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


class SchemaArtifact(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "schema_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "protocol",
            "name",
            "version",
            name="uq_schema_artifacts_project_protocol_name_version",
        ),
        UniqueConstraint(
            "project_id",
            "protocol",
            "content_sha256",
            name="uq_schema_artifacts_project_protocol_hash",
        ),
        CheckConstraint("protocol IN ('graphql', 'grpc')", name="schema_artifact_protocol"),
        CheckConstraint(
            "source_format IN ('graphql_sdl', 'graphql_introspection', "
            "'proto_source', 'proto_descriptor_set', 'grpc_reflection')",
            name="schema_artifact_source_format",
        ),
        CheckConstraint("version >= 1", name="schema_artifact_version"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    protocol: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    version: Mapped[int] = mapped_column(Integer)
    source_format: Mapped[str] = mapped_column(String(32))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    canonical_content: Mapped[bytes] = mapped_column(LargeBinary)
    source_content: Mapped[bytes] = mapped_column(LargeBinary)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
