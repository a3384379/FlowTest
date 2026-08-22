from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ImportRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_runs"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('openapi3', 'swagger2', 'postman', 'har', 'curl', 'bruno', 'excel')",
            name="import_run_source_type",
        ),
        CheckConstraint("source_kind IN ('file', 'url')", name="import_run_source_kind"),
        CheckConstraint("status IN ('applied', 'preview')", name="import_run_status"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(16), default="file", server_default="file")
    source_key: Mapped[str] = mapped_column(String(512), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    document_url: Mapped[str | None] = mapped_column(String(2048))
    source_sha256: Mapped[str] = mapped_column(String(64))
    added: Mapped[int] = mapped_column(Integer, default=0)
    changed: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="applied", server_default="applied")
    applied_keys: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    payload_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    payload_nonce: Mapped[bytes | None] = mapped_column(LargeBinary(12))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
