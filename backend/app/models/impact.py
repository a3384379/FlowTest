from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ImpactAssetMapping(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "impact_asset_mappings"
    __table_args__ = (
        UniqueConstraint("project_id", "mapping_key", name="uq_impact_mapping_project_key"),
        CheckConstraint(
            "source_kind IN ('git', 'openapi', 'graphql', 'grpc')",
            name="impact_mapping_source_kind",
        ),
        CheckConstraint(
            "target_type IN ('test_case', 'workflow', 'openapi_contract', "
            "'pact_contract', 'performance')",
            name="impact_mapping_target_type",
        ),
        CheckConstraint(
            "(target_type = 'test_case' AND test_case_id IS NOT NULL AND workflow_id IS NULL "
            "AND contract_run_id IS NULL AND pact_contract_version_id IS NULL "
            "AND performance_scenario_id IS NULL) OR "
            "(target_type = 'workflow' AND test_case_id IS NULL AND workflow_id IS NOT NULL "
            "AND contract_run_id IS NULL AND pact_contract_version_id IS NULL "
            "AND performance_scenario_id IS NULL) OR "
            "(target_type = 'openapi_contract' AND test_case_id IS NULL AND workflow_id IS NULL "
            "AND contract_run_id IS NOT NULL AND pact_contract_version_id IS NULL "
            "AND performance_scenario_id IS NULL) OR "
            "(target_type = 'pact_contract' AND test_case_id IS NULL AND workflow_id IS NULL "
            "AND contract_run_id IS NULL AND pact_contract_version_id IS NOT NULL "
            "AND performance_scenario_id IS NULL) OR "
            "(target_type = 'performance' AND test_case_id IS NULL AND workflow_id IS NULL "
            "AND contract_run_id IS NULL AND pact_contract_version_id IS NULL "
            "AND performance_scenario_id IS NOT NULL)",
            name="impact_mapping_target_reference",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_impact_map_project", ondelete="CASCADE"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(16), index=True)
    source_selector: Mapped[str] = mapped_column(String(512))
    target_type: Mapped[str] = mapped_column(String(24), index=True)
    mapping_key: Mapped[str] = mapped_column(String(64))
    test_case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_cases.id", name="fk_impact_map_case", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflows.id", name="fk_impact_map_workflow", ondelete="CASCADE"), index=True
    )
    contract_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contract_runs.id", name="fk_impact_map_openapi", ondelete="CASCADE"), index=True
    )
    pact_contract_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pact_contract_versions.id", name="fk_impact_map_pact", ondelete="CASCADE"),
        index=True,
    )
    performance_scenario_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("performance_scenarios.id", name="fk_impact_map_perf", ondelete="CASCADE"),
        index=True,
    )
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_impact_map_creator", ondelete="RESTRICT")
    )


class ImpactRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "impact_runs"
    __table_args__ = (
        CheckConstraint("status IN ('completed', 'failed')", name="impact_run_status"),
        CheckConstraint("change_count BETWEEN 1 AND 5000", name="impact_run_change_count"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_impact_run_project", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    source_ref: Mapped[str] = mapped_column(String(200), default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="completed", server_default="completed")
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    source_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    change_count: Mapped[int] = mapped_column(Integer)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_impact_run_creator", ondelete="RESTRICT")
    )


class TestSelection(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_selections"
    __table_args__ = (UniqueConstraint("impact_run_id", name="uq_test_selection_impact_run"),)

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_test_selection_project", ondelete="CASCADE"),
        index=True,
    )
    impact_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("impact_runs.id", name="fk_test_selection_run", ondelete="CASCADE"),
        index=True,
    )
    strategy: Mapped[str] = mapped_column(
        String(32), default="explicit_mapping_v1", server_default="explicit_mapping_v1"
    )
    selected_assets: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    explanations: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_test_selection_creator", ondelete="RESTRICT")
    )


class CoverageSnapshot(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "coverage_snapshots"
    __table_args__ = (
        UniqueConstraint("impact_run_id", name="uq_coverage_snapshot_impact_run"),
        CheckConstraint("total_changes BETWEEN 1 AND 5000", name="coverage_total_changes"),
        CheckConstraint(
            "covered_changes BETWEEN 0 AND total_changes", name="coverage_covered_changes"
        ),
        CheckConstraint("coverage_percent BETWEEN 0 AND 100", name="coverage_percent_range"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_coverage_project", ondelete="CASCADE"), index=True
    )
    impact_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("impact_runs.id", name="fk_coverage_run", ondelete="CASCADE"), index=True
    )
    total_changes: Mapped[int] = mapped_column(Integer)
    covered_changes: Mapped[int] = mapped_column(Integer)
    coverage_percent: Mapped[float] = mapped_column(Float)
    matrix: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_coverage_creator", ondelete="RESTRICT")
    )
