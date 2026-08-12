"""Add Pact contract hub and deployment compatibility evidence.

Revision ID: 20260812_0024
Revises: 20260812_0023
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0024"
down_revision: str | None = "20260812_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_catalog_entries",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("service_key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_service_catalog_entries_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_service_catalog_entries_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_catalog_entries")),
        sa.UniqueConstraint("project_id", "service_key", name="uq_service_catalog_project_key"),
        sa.UniqueConstraint("project_id", "display_name", name="uq_service_catalog_project_name"),
    )
    op.create_index(
        op.f("ix_service_catalog_entries_project_id"),
        "service_catalog_entries",
        ["project_id"],
    )

    op.add_column("contract_runs", sa.Column("provider_service_id", sa.Uuid(), nullable=True))
    op.add_column(
        "contract_runs", sa.Column("provider_version", sa.String(length=120), nullable=True)
    )
    op.create_foreign_key(
        "fk_contract_run_provider",
        "contract_runs",
        "service_catalog_entries",
        ["provider_service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_contract_runs_provider_service_id"),
        "contract_runs",
        ["provider_service_id"],
    )

    op.create_table(
        "pact_contract_versions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_service_id", sa.Uuid(), nullable=False),
        sa.Column("provider_service_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_version", sa.String(length=120), nullable=False),
        sa.Column("pact_specification_version", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("contract_document", sa.JSON(), nullable=False),
        sa.Column("interaction_count", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "interaction_count BETWEEN 1 AND 500",
            name=op.f("ck_pact_contract_versions_interaction_count"),
        ),
        sa.CheckConstraint(
            "source_type IN ('upload', 'broker')",
            name=op.f("ck_pact_contract_versions_pact_contract_source_type"),
        ),
        sa.ForeignKeyConstraint(
            ["consumer_service_id"],
            ["service_catalog_entries.id"],
            name="fk_pact_contract_consumer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_pact_contract_versions_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_pact_contract_versions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_service_id"],
            ["service_catalog_entries.id"],
            name="fk_pact_contract_provider",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pact_contract_versions")),
        sa.UniqueConstraint(
            "project_id",
            "consumer_version",
            "content_sha256",
            name="uq_pact_contract_project_version_hash",
        ),
    )
    for column in (
        "project_id",
        "consumer_service_id",
        "provider_service_id",
        "consumer_version",
        "content_sha256",
    ):
        op.create_index(
            op.f(f"ix_pact_contract_versions_{column}"),
            "pact_contract_versions",
            [column],
        )

    op.create_table(
        "pact_provider_verifications",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("pact_contract_version_id", sa.Uuid(), nullable=False),
        sa.Column("provider_version", sa.String(length=120), nullable=False),
        sa.Column("target_base_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("interaction_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("verified_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "failed_count >= 0",
            name=op.f("ck_pact_provider_verifications_failed_count"),
        ),
        sa.CheckConstraint(
            "interaction_count >= 1",
            name=op.f("ck_pact_provider_verifications_interaction_count"),
        ),
        sa.CheckConstraint(
            "passed_count >= 0",
            name=op.f("ck_pact_provider_verifications_passed_count"),
        ),
        sa.CheckConstraint(
            "status IN ('passed', 'failed')",
            name=op.f("ck_pact_provider_verifications_pact_verification_status"),
        ),
        sa.ForeignKeyConstraint(
            ["pact_contract_version_id"],
            ["pact_contract_versions.id"],
            name="fk_pact_verification_contract",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_pact_provider_verifications_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_id"],
            ["users.id"],
            name=op.f("fk_pact_provider_verifications_verified_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pact_provider_verifications")),
    )
    for column in (
        "project_id",
        "pact_contract_version_id",
        "provider_version",
        "status",
    ):
        op.create_index(
            op.f(f"ix_pact_provider_verifications_{column}"),
            "pact_provider_verifications",
            [column],
        )

    op.create_table(
        "deployment_compatibility_checks",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("provider_service_id", sa.Uuid(), nullable=False),
        sa.Column("provider_version", sa.String(length=120), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("checked_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('safe', 'unsafe', 'unknown')",
            name=op.f("ck_deployment_compatibility_checks_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["checked_by_id"],
            ["users.id"],
            name=op.f("fk_deployment_compatibility_checks_checked_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_deployment_compatibility_checks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_service_id"],
            ["service_catalog_entries.id"],
            name="fk_deployment_check_provider",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deployment_compatibility_checks")),
    )
    for column in ("project_id", "provider_service_id", "provider_version", "decision"):
        op.create_index(
            op.f(f"ix_deployment_compatibility_checks_{column}"),
            "deployment_compatibility_checks",
            [column],
        )


def downgrade() -> None:
    for column in ("decision", "provider_version", "provider_service_id", "project_id"):
        op.drop_index(
            op.f(f"ix_deployment_compatibility_checks_{column}"),
            table_name="deployment_compatibility_checks",
        )
    op.drop_table("deployment_compatibility_checks")
    for column in ("status", "provider_version", "pact_contract_version_id", "project_id"):
        op.drop_index(
            op.f(f"ix_pact_provider_verifications_{column}"),
            table_name="pact_provider_verifications",
        )
    op.drop_table("pact_provider_verifications")
    for column in (
        "content_sha256",
        "consumer_version",
        "provider_service_id",
        "consumer_service_id",
        "project_id",
    ):
        op.drop_index(
            op.f(f"ix_pact_contract_versions_{column}"),
            table_name="pact_contract_versions",
        )
    op.drop_table("pact_contract_versions")
    op.drop_index(op.f("ix_contract_runs_provider_service_id"), table_name="contract_runs")
    op.drop_constraint(
        "fk_contract_run_provider",
        "contract_runs",
        type_="foreignkey",
    )
    op.drop_column("contract_runs", "provider_version")
    op.drop_column("contract_runs", "provider_service_id")
    op.drop_index(
        op.f("ix_service_catalog_entries_project_id"), table_name="service_catalog_entries"
    )
    op.drop_table("service_catalog_entries")
