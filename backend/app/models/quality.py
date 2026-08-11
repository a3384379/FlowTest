from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class QualityGate(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quality_gates"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_quality_gates_project_name"),
        CheckConstraint("min_pass_rate BETWEEN 0 AND 100", name="quality_gate_pass_rate"),
        CheckConstraint("max_failed >= 0", name="quality_gate_max_failed"),
        CheckConstraint("max_flaky >= 0", name="quality_gate_max_flaky"),
        CheckConstraint(
            "max_duration_regression_percent >= 0",
            name="quality_gate_duration_regression",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    min_pass_rate: Mapped[float] = mapped_column(Float, default=100, server_default="100")
    max_failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_flaky: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_duration_regression_percent: Mapped[float] = mapped_column(
        Float, default=20, server_default="20"
    )
    require_no_breaking_changes: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class FlakyRecord(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "flaky_records"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "target_type",
            "target_id",
            "target_version",
            name="uq_flaky_records_project_target",
        ),
        CheckConstraint("total_runs >= 0", name="flaky_record_total_runs"),
        CheckConstraint("passed_runs >= 0", name="flaky_record_passed_runs"),
        CheckConstraint("failed_runs >= 0", name="flaky_record_failed_runs"),
        CheckConstraint("transitions >= 0", name="flaky_record_transitions"),
        CheckConstraint("flaky_score BETWEEN 0 AND 100", name="flaky_record_score"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(16), index=True)
    target_id: Mapped[UUID] = mapped_column(index=True)
    target_version: Mapped[int] = mapped_column(Integer)
    total_runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    passed_runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    transitions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    flaky_score: Mapped[float] = mapped_column(Float, default=0, server_default="0", index=True)
    quarantined: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_plan_runs.id", ondelete="SET NULL")
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QualityGateEvaluation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quality_gate_evaluations"
    __table_args__ = (
        UniqueConstraint("quality_gate_id", "test_plan_run_id", name="uq_gate_evaluation_run"),
        CheckConstraint("status IN ('passed', 'failed')", name="gate_evaluation_status"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    quality_gate_id: Mapped[UUID] = mapped_column(
        ForeignKey("quality_gates.id", ondelete="CASCADE"), index=True
    )
    test_plan_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_plan_runs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    violations: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
