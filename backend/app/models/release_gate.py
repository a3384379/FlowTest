from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ReleasePolicy(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "release_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_release_policies_project_name"),
        CheckConstraint(
            "min_impact_coverage_percent BETWEEN 0 AND 100",
            name="release_policy_impact_coverage",
        ),
        CheckConstraint(
            "max_release_risk_score BETWEEN 0 AND 100",
            name="release_policy_risk_score",
        ),
        CheckConstraint(
            "NOT require_quality_gate OR quality_gate_id IS NOT NULL",
            name="release_policy_quality_gate_reference",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_release_policy_project", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    quality_gate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("quality_gates.id", name="fk_release_policy_quality_gate", ondelete="SET NULL"),
        index=True,
    )
    require_quality_gate: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    require_contract_compatibility: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    require_impact_evidence: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    min_impact_coverage_percent: Mapped[float] = mapped_column(
        Float, default=80, server_default="80"
    )
    require_release_risk: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    max_release_risk_score: Mapped[float] = mapped_column(Float, default=50, server_default="50")
    require_performance_evidence: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    require_runner_evidence: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_release_policy_creator", ondelete="RESTRICT")
    )


class ReleaseDecision(UuidPrimaryKeyMixin, Base):
    __tablename__ = "release_decisions"
    __table_args__ = (
        CheckConstraint("status IN ('pass', 'block')", name="release_decision_status"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_release_decision_project", ondelete="CASCADE"),
        index=True,
    )
    release_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("release_policies.id", name="fk_release_decision_policy", ondelete="RESTRICT"),
        index=True,
    )
    candidate_ref: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    policy_snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    evidence_snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    reasons: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    test_plan_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_plan_runs.id", ondelete="RESTRICT"), index=True
    )
    deployment_check_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("deployment_compatibility_checks.id", ondelete="RESTRICT"), index=True
    )
    impact_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("impact_runs.id", ondelete="RESTRICT"), index=True
    )
    release_risk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("release_risks.id", ondelete="RESTRICT"), index=True
    )
    performance_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("performance_runs.id", ondelete="RESTRICT"), index=True
    )
    runner_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runner_tasks.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_release_decision_creator", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


@event.listens_for(ReleaseDecision, "before_update")
@event.listens_for(ReleaseDecision, "before_delete")
def _prevent_release_decision_mutation(*_: object) -> None:
    raise ValueError("ReleaseDecision is immutable")
