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


class ContractRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contract_runs"
    __table_args__ = (
        CheckConstraint("status IN ('completed', 'failed')", name="contract_run_status"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    baseline_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contract_runs.id", ondelete="SET NULL"), index=True
    )
    source_name: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="completed", server_default="completed")
    schema_document: Mapped[dict[str, Any]] = mapped_column(JSON)
    diff_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    breaking_changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON)
    generated_case_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class GeneratedContractCase(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generated_contract_cases"
    __table_args__ = (
        UniqueConstraint(
            "contract_run_id",
            "operation_key",
            "generation_kind",
            name="uq_generated_contract_cases_run_operation_kind",
        ),
        CheckConstraint(
            "generation_kind IN ('example', 'boundary', 'property', 'negative')",
            name="generated_contract_case_kind",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="generated_case_review_status",
        ),
    )

    contract_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("contract_runs.id", ondelete="CASCADE"), index=True
    )
    operation_key: Mapped[str] = mapped_column(String(64), index=True)
    operation_id: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(2048))
    generation_kind: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(200))
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    review_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
