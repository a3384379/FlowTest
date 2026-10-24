"""Small self-test metadata aggregates; native assets and executions remain authoritative."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
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


class SelfTestInstallation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "self_test_installations"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "binding_id", "pack_digest", name="uq_self_test_installation_binding_pack"
        ),
        UniqueConstraint(
            "project_id", "idempotency_key", name="uq_self_test_installation_idempotency"
        ),
        CheckConstraint(
            "status IN ('needs_input','queued','installing','ready','blocked','archived')",
            name="self_test_installation_status",
        ),
        CheckConstraint("revision >= 0", name="self_test_installation_revision"),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    binding_id: Mapped[UUID] = mapped_column(index=True)
    template_id: Mapped[str] = mapped_column(String(200))
    template_version: Mapped[str] = mapped_column(String(200))
    pack_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    binding_fingerprint: Mapped[str] = mapped_column(String(64))
    environment_fingerprint: Mapped[str] = mapped_column(String(64))
    resource_mapping: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str | None] = mapped_column(String(200))
    host_id: Mapped[str | None] = mapped_column(String(200))
    registered_capabilities: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    registration_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nonce_hash: Mapped[str | None] = mapped_column(String(64))
    receipt_digest: Mapped[str | None] = mapped_column(String(64))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class SelfTestBatch(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "self_test_batches"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_self_test_batch_idempotency"),
        CheckConstraint(
            "batch_kind IN ('fixed_baseline','mcp_generated')", name="self_test_batch_kind"
        ),
        CheckConstraint(
            "generation_mode IS NULL OR generation_mode IN ('deterministic_mcp','host_llm_mcp')",
            name="self_test_generation_mode",
        ),
        CheckConstraint(
            "phase IN ('pending','generating','awaiting_review','ready','running',"
            "'collecting','completed','cancelled','expired')",
            name="self_test_batch_phase",
        ),
        CheckConstraint(
            "verdict IN ('pending','passed','failed','blocked')", name="self_test_batch_verdict"
        ),
        CheckConstraint(
            "provenance IN ('local_untrusted','trusted_ci')", name="self_test_batch_provenance"
        ),
        CheckConstraint(
            "evidence_integrity IN ('complete','missing','expired')",
            name="self_test_batch_integrity",
        ),
        CheckConstraint(
            "expected_count > 0 AND expected_count <= 100", name="self_test_batch_expected_count"
        ),
        CheckConstraint("revision >= 0", name="self_test_batch_revision"),
        CheckConstraint(
            "readiness IN ('ready','needs_input','needs_review','unsupported','blocked')",
            name="self_test_batch_readiness",
        ),
        CheckConstraint(
            "verification_scope IN ('full_pack','selected_suites','diagnostic_subset')",
            name="self_test_batch_scope",
        ),
        CheckConstraint(
            "cleanup_status IN ('pending','completed','failed','needs_review')",
            name="self_test_batch_cleanup",
        ),
        CheckConstraint(
            "generation_stage IN ('discovering','reading_contract','designing','compiling',"
            "'proposing','awaiting_review','publishing','ready','blocked','cancelled')",
            name="self_test_batch_generation_stage",
        ),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    installation_id: Mapped[UUID] = mapped_column(
        ForeignKey("self_test_installations.id", ondelete="RESTRICT"), index=True
    )
    binding_id: Mapped[UUID] = mapped_column(index=True)
    batch_key: Mapped[str] = mapped_column(String(200), unique=True)
    batch_kind: Mapped[str] = mapped_column(String(24))
    generation_mode: Mapped[str | None] = mapped_column(String(24))
    generation_stage: Mapped[str] = mapped_column(String(32))
    readiness: Mapped[str] = mapped_column(String(24))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    phase: Mapped[str] = mapped_column(String(24), index=True)
    verdict: Mapped[str] = mapped_column(String(16))
    verification_scope: Mapped[str] = mapped_column(String(24))
    provenance: Mapped[str] = mapped_column(
        String(24), default="local_untrusted", server_default="local_untrusted"
    )
    evidence_integrity: Mapped[str] = mapped_column(
        String(16), default="missing", server_default="missing"
    )
    cleanup_status: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending"
    )
    expected_count: Mapped[int] = mapped_column(Integer)
    frozen_manifest: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    manifest_digest: Mapped[str] = mapped_column(String(64))
    resource_digest: Mapped[str | None] = mapped_column(String(64))
    expected_set_digest: Mapped[str] = mapped_column(String(64))
    required_set_digest: Mapped[str] = mapped_column(String(64))
    policy_digest: Mapped[str] = mapped_column(String(64))
    binding_fingerprint: Mapped[str] = mapped_column(String(64))
    environment_fingerprint: Mapped[str] = mapped_column(String(64))
    builds: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    generation_summary: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON)
    artifact_refs: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    plan_run_ids: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    execution_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_plans.id", ondelete="SET NULL")
    )
    suite_ref: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON)
    resource_snapshot: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    host_id: Mapped[str | None] = mapped_column(String(200))
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nonce_hash: Mapped[str | None] = mapped_column(String(64))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ci_run_id: Mapped[str | None] = mapped_column(String(200))
    ci_attempt: Mapped[int | None] = mapped_column(Integer)
    receipt_digest: Mapped[str | None] = mapped_column(String(64))
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SelfTestScenarioResult(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "self_test_scenario_results"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "scenario_id", "variant_key", name="uq_self_test_scenario_variant"
        ),
        CheckConstraint(
            "verification_status IN ('pending','matched','mismatched','incomplete',"
            "'error','unsupported')",
            name="self_test_scenario_verification",
        ),
        CheckConstraint(
            "generation_attempt >= 0 AND generation_attempt <= 10",
            name="self_test_scenario_generation_attempt",
        ),
        CheckConstraint(
            "observed_status IS NULL OR observed_status IN "
            "('queued','running','passed','failed','cancelled','quarantined')",
            name="self_test_scenario_observed_status",
        ),
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("self_test_batches.id", ondelete="CASCADE"), index=True
    )
    scenario_id: Mapped[str] = mapped_column(String(160))
    variant_key: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer)
    frozen_scenario: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    generation_attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON)
    published_assets: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON)
    test_plan_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_plan_runs.id", ondelete="SET NULL"), index=True
    )
    run_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_plan_run_items.id", ondelete="SET NULL"), index=True
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="SET NULL"), index=True
    )
    execution_refs: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    observed_status: Mapped[str | None] = mapped_column(String(24))
    verification_status: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending"
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    evidence_refs: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
