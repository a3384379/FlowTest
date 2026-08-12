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


class PerformanceScenario(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "performance_scenarios"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "name", "version", name="uq_performance_scenarios_project_name_version"
        ),
        CheckConstraint("version >= 1", name="performance_scenario_version"),
        CheckConstraint("status IN ('draft', 'published')", name="performance_scenario_status"),
        CheckConstraint(
            "target_type IN ('rest', 'http_workflow')", name="performance_scenario_target_type"
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", index=True
    )
    target_type: Mapped[str] = mapped_column(String(24), index=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    compiled_sha256: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class PerformanceRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "performance_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'cancelled')",
            name="performance_run_status",
        ),
        CheckConstraint("scenario_version >= 1", name="performance_run_scenario_version"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    scenario_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_scenarios.id", ondelete="RESTRICT"), index=True
    )
    scenario_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued", index=True
    )
    definition_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    compiled_sha256: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    threshold_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    baseline_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("performance_runs.id", ondelete="SET NULL"), index=True
    )
    raw_metrics_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class PerformanceGateEvaluation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "performance_gate_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "quality_gate_id", "performance_run_id", name="uq_performance_gate_evaluation_run"
        ),
        CheckConstraint("status IN ('passed', 'failed')", name="performance_gate_status"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    quality_gate_id: Mapped[UUID] = mapped_column(
        ForeignKey("quality_gates.id", ondelete="CASCADE"), index=True
    )
    performance_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_runs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    violations: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
