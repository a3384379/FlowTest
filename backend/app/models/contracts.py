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
    provider_service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "service_catalog_entries.id", name="fk_contract_run_provider", ondelete="SET NULL"
        ),
        index=True,
        nullable=True,
    )
    provider_version: Mapped[str | None] = mapped_column(String(120), nullable=True)


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


class ServiceCatalogEntry(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "service_catalog_entries"
    __table_args__ = (
        UniqueConstraint("project_id", "service_key", name="uq_service_catalog_project_key"),
        UniqueConstraint("project_id", "display_name", name="uq_service_catalog_project_name"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    service_key: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class PactContractVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pact_contract_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "consumer_version",
            "content_sha256",
            name="uq_pact_contract_project_version_hash",
        ),
        CheckConstraint("source_type IN ('upload', 'broker')", name="pact_contract_source_type"),
        CheckConstraint("interaction_count BETWEEN 1 AND 500", name="interaction_count"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    consumer_service_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "service_catalog_entries.id", name="fk_pact_contract_consumer", ondelete="RESTRICT"
        ),
        index=True,
    )
    provider_service_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "service_catalog_entries.id", name="fk_pact_contract_provider", ondelete="RESTRICT"
        ),
        index=True,
    )
    consumer_version: Mapped[str] = mapped_column(String(120), index=True)
    pact_specification_version: Mapped[str] = mapped_column(String(32))
    source_type: Mapped[str] = mapped_column(String(16))
    source_name: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    contract_document: Mapped[dict[str, Any]] = mapped_column(JSON)
    interaction_count: Mapped[int] = mapped_column(Integer)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class PactProviderVerification(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pact_provider_verifications"
    __table_args__ = (
        CheckConstraint("status IN ('passed', 'failed')", name="pact_verification_status"),
        CheckConstraint("interaction_count >= 1", name="interaction_count"),
        CheckConstraint("passed_count >= 0", name="passed_count"),
        CheckConstraint("failed_count >= 0", name="failed_count"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    pact_contract_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "pact_contract_versions.id", name="fk_pact_verification_contract", ondelete="CASCADE"
        ),
        index=True,
    )
    provider_version: Mapped[str] = mapped_column(String(120), index=True)
    target_base_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(16), index=True)
    interaction_count: Mapped[int] = mapped_column(Integer)
    passed_count: Mapped[int] = mapped_column(Integer)
    failed_count: Mapped[int] = mapped_column(Integer)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    verified_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class DeploymentCompatibilityCheck(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deployment_compatibility_checks"
    __table_args__ = (
        CheckConstraint("decision IN ('safe', 'unsafe', 'unknown')", name="decision"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    provider_service_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "service_catalog_entries.id", name="fk_deployment_check_provider", ondelete="CASCADE"
        ),
        index=True,
    )
    provider_version: Mapped[str] = mapped_column(String(120), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    checked_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
