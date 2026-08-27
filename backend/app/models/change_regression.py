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


class ChangeRegressionRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Traceable application aggregate for a change-aware regression run."""

    __tablename__ = "change_regression_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('review_required', 'approved', 'queued', 'running', "
            "'evidence_ready', 'passed', 'blocked', 'failed')",
            name="change_regression_run_status",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_change_regression_project", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200))
    source_ref: Mapped[str] = mapped_column(String(200), default="", server_default="")
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    candidate_ref: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(24), default="review_required", index=True)
    impact_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("impact_runs.id", name="fk_change_regression_impact", ondelete="RESTRICT"),
        index=True,
    )
    test_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_plans.id", name="fk_change_regression_plan", ondelete="RESTRICT"),
        index=True,
    )
    test_plan_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_plan_runs.id", name="fk_change_regression_plan_run", ondelete="SET NULL"),
        index=True,
    )
    release_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("release_policies.id", name="fk_change_regression_policy", ondelete="RESTRICT"),
        index=True,
    )
    release_risk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("release_risks.id", name="fk_change_regression_risk", ondelete="SET NULL"),
        index=True,
    )
    deployment_check_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "deployment_compatibility_checks.id",
            name="fk_change_regression_deployment_check",
            ondelete="SET NULL",
        ),
        index=True,
    )
    change_set_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "ai_change_sets.id", name="fk_change_regression_change_set", ondelete="SET NULL"
        ),
        index=True,
    )
    release_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "release_decisions.id",
            name="fk_change_regression_release_decision",
            ondelete="SET NULL",
        ),
        index=True,
    )
    selected_assets: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    selection_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    missing_tests: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    failure_triage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_change_regression_approver", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_change_regression_creator", ondelete="RESTRICT")
    )


class ChangeRegressionStage(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only stage evidence for the Change -> Release trace."""

    __tablename__ = "change_regression_stages"
    __table_args__ = (
        UniqueConstraint(
            "regression_run_id",
            "sequence",
            name="uq_change_regression_stage_sequence",
        ),
        CheckConstraint(
            "stage IN ('change', 'impact', 'regression_selection', 'missing_test', 'review', "
            "'execution', 'evidence', 'release_gate', 'failure_triage')",
            name="change_regression_stage_kind",
        ),
        CheckConstraint(
            "status IN ('completed', 'pending', 'approved', 'queued', 'running', 'passed', "
            "'blocked', 'failed', 'skipped')",
            name="change_regression_stage_status",
        ),
    )

    regression_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "change_regression_runs.id", name="fk_change_regression_stage_run", ondelete="CASCADE"
        ),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_change_regression_stage_actor", ondelete="SET NULL")
    )


class SemanticGapWaiver(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A durable, per-requirement human waiver; it never represents coverage."""

    __tablename__ = "semantic_gap_waivers"
    __table_args__ = (
        UniqueConstraint(
            "regression_run_id",
            "gap_key",
            "revision",
            name="uq_semantic_gap_waiver_run_gap_revision",
        ),
        CheckConstraint("revision >= 1", name="semantic_gap_waiver_revision_positive"),
    )

    regression_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "change_regression_runs.id",
            name="fk_semantic_gap_waiver_run",
            ondelete="CASCADE",
        ),
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_semantic_gap_waiver_project", ondelete="CASCADE"),
        index=True,
    )
    gap_key: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    supersedes_waiver_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "semantic_gap_waivers.id",
            name="fk_semantic_gap_waiver_supersedes",
            ondelete="SET NULL",
        ),
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text)
    approved_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_semantic_gap_waiver_approver", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    operation_identity: Mapped[dict[str, Any]] = mapped_column(JSON)
    semantic_requirement: Mapped[dict[str, Any]] = mapped_column(JSON)
    requirement_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
