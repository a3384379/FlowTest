from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ReleaseRisk(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "release_risks"
    __table_args__ = (
        CheckConstraint("window_days BETWEEN 7 AND 90", name="release_risk_window_days"),
        CheckConstraint("score BETWEEN 0 AND 100", name="release_risk_score"),
        CheckConstraint("quality_score BETWEEN 0 AND 100", name="release_quality_score"),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="release_risk_level",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_release_risk_project", ondelete="CASCADE"), index=True
    )
    impact_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("impact_runs.id", name="fk_release_risk_impact", ondelete="RESTRICT"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200))
    algorithm_version: Mapped[str] = mapped_column(
        String(32), default="release_risk_v1", server_default="release_risk_v1"
    )
    window_days: Mapped[int] = mapped_column(Integer)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    baseline_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    baseline_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    score: Mapped[float] = mapped_column(Float, index=True)
    quality_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16), index=True)
    factors: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    quality_trend: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    recommended_tests: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_release_risk_creator", ondelete="RESTRICT")
    )


class FailureCluster(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "failure_clusters"
    __table_args__ = (
        CheckConstraint("occurrence_count >= 1", name="failure_cluster_occurrences"),
        CheckConstraint("baseline_count >= 0", name="failure_cluster_baseline"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="failure_cluster_confidence"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_failure_cluster_project", ondelete="CASCADE"),
        index=True,
    )
    release_risk_id: Mapped[UUID] = mapped_column(
        ForeignKey("release_risks.id", name="fk_failure_cluster_risk", ondelete="CASCADE"),
        index=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    failure_category: Mapped[str] = mapped_column(String(32), index=True)
    error_code: Mapped[str | None] = mapped_column(String(100))
    node_type: Mapped[str | None] = mapped_column(String(32))
    occurrence_count: Mapped[int] = mapped_column(Integer)
    baseline_count: Mapped[int] = mapped_column(Integer)
    affected_workflow_ids: Mapped[list[str]] = mapped_column(JSON)
    affected_workflow_names: Mapped[list[str]] = mapped_column(JSON)
    sample_execution_ids: Mapped[list[str]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    regression_percent: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(Text)
