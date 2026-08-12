"""Add change impact, deterministic selection, and coverage evidence.

Revision ID: 20260812_0025
Revises: 20260812_0024
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0025"
down_revision: str | None = "20260812_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "impact_asset_mappings",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_selector", sa.String(length=512), nullable=False),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("mapping_key", sa.String(length=64), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("contract_run_id", sa.Uuid(), nullable=True),
        sa.Column("pact_contract_version_id", sa.Uuid(), nullable=True),
        sa.Column("performance_scenario_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_kind IN ('git', 'openapi', 'graphql', 'grpc')",
            name=op.f("ck_impact_asset_mappings_impact_mapping_source_kind"),
        ),
        sa.CheckConstraint(
            "target_type IN ('test_case', 'workflow', 'openapi_contract', "
            "'pact_contract', 'performance')",
            name=op.f("ck_impact_asset_mappings_impact_mapping_target_type"),
        ),
        sa.CheckConstraint(
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
            name=op.f("ck_impact_asset_mappings_impact_mapping_target_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_impact_map_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"], ["test_cases.id"], name="fk_impact_map_case", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflows.id"], name="fk_impact_map_workflow", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contract_run_id"],
            ["contract_runs.id"],
            name="fk_impact_map_openapi",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pact_contract_version_id"],
            ["pact_contract_versions.id"],
            name="fk_impact_map_pact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["performance_scenario_id"],
            ["performance_scenarios.id"],
            name="fk_impact_map_perf",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_impact_map_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_asset_mappings")),
        sa.UniqueConstraint("project_id", "mapping_key", name="uq_impact_mapping_project_key"),
    )
    _mapping_indexes()

    op.create_table(
        "impact_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_ref", sa.String(length=200), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="completed", nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_summary", sa.JSON(), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')", name=op.f("ck_impact_runs_impact_run_status")
        ),
        sa.CheckConstraint(
            "change_count BETWEEN 1 AND 5000",
            name=op.f("ck_impact_runs_impact_run_change_count"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_impact_run_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_impact_run_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_runs")),
    )
    op.create_index(op.f("ix_impact_runs_project_id"), "impact_runs", ["project_id"])
    op.create_index(
        op.f("ix_impact_runs_source_fingerprint"), "impact_runs", ["source_fingerprint"]
    )

    op.create_table(
        "test_selections",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("impact_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "strategy", sa.String(length=32), server_default="explicit_mapping_v1", nullable=False
        ),
        sa.Column("selected_assets", sa.JSON(), nullable=False),
        sa.Column("explanations", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_test_selection_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["impact_run_id"],
            ["impact_runs.id"],
            name="fk_test_selection_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_test_selection_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_selections")),
        sa.UniqueConstraint("impact_run_id", name="uq_test_selection_impact_run"),
    )
    op.create_index(op.f("ix_test_selections_project_id"), "test_selections", ["project_id"])
    op.create_index(op.f("ix_test_selections_impact_run_id"), "test_selections", ["impact_run_id"])

    op.create_table(
        "coverage_snapshots",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("impact_run_id", sa.Uuid(), nullable=False),
        sa.Column("total_changes", sa.Integer(), nullable=False),
        sa.Column("covered_changes", sa.Integer(), nullable=False),
        sa.Column("coverage_percent", sa.Float(), nullable=False),
        sa.Column("matrix", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "total_changes BETWEEN 1 AND 5000",
            name=op.f("ck_coverage_snapshots_coverage_total_changes"),
        ),
        sa.CheckConstraint(
            "covered_changes BETWEEN 0 AND total_changes",
            name=op.f("ck_coverage_snapshots_coverage_covered_changes"),
        ),
        sa.CheckConstraint(
            "coverage_percent BETWEEN 0 AND 100",
            name=op.f("ck_coverage_snapshots_coverage_percent_range"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_coverage_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["impact_run_id"],
            ["impact_runs.id"],
            name="fk_coverage_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_coverage_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coverage_snapshots")),
        sa.UniqueConstraint("impact_run_id", name="uq_coverage_snapshot_impact_run"),
    )
    op.create_index(op.f("ix_coverage_snapshots_project_id"), "coverage_snapshots", ["project_id"])
    op.create_index(
        op.f("ix_coverage_snapshots_impact_run_id"),
        "coverage_snapshots",
        ["impact_run_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_coverage_snapshots_impact_run_id"), table_name="coverage_snapshots")
    op.drop_index(op.f("ix_coverage_snapshots_project_id"), table_name="coverage_snapshots")
    op.drop_table("coverage_snapshots")
    op.drop_index(op.f("ix_test_selections_impact_run_id"), table_name="test_selections")
    op.drop_index(op.f("ix_test_selections_project_id"), table_name="test_selections")
    op.drop_table("test_selections")
    op.drop_index(op.f("ix_impact_runs_source_fingerprint"), table_name="impact_runs")
    op.drop_index(op.f("ix_impact_runs_project_id"), table_name="impact_runs")
    op.drop_table("impact_runs")
    _drop_mapping_indexes()
    op.drop_table("impact_asset_mappings")


def _mapping_indexes() -> None:
    for column in (
        "project_id",
        "source_kind",
        "target_type",
        "test_case_id",
        "workflow_id",
        "contract_run_id",
        "pact_contract_version_id",
        "performance_scenario_id",
    ):
        op.create_index(
            op.f(f"ix_impact_asset_mappings_{column}"), "impact_asset_mappings", [column]
        )


def _drop_mapping_indexes() -> None:
    for column in reversed(
        (
            "project_id",
            "source_kind",
            "target_type",
            "test_case_id",
            "workflow_id",
            "contract_run_id",
            "pact_contract_version_id",
            "performance_scenario_id",
        )
    ):
        op.drop_index(
            op.f(f"ix_impact_asset_mappings_{column}"), table_name="impact_asset_mappings"
        )
