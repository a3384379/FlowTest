"""Add organization governance, quota and key lifecycle records for S44."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0039"
down_revision: str | None = "20260822_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_governance",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("audit_retention_days", sa.Integer(), server_default="365", nullable=False),
        sa.Column("quota_policies", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("runner_policy", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("active_key_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "audit_retention_days BETWEEN 1 AND 3650",
            name=op.f("ck_organization_governance_audit_retention"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id"),
    )

    op.create_table(
        "organization_key_versions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("key_reference", sa.String(length=200), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "migration_status", sa.String(length=16), server_default="planned", nullable=False
        ),
        sa.Column("previous_version", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("migrated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'retiring', 'retired', 'rolled_back')",
            name=op.f("ck_organization_key_versions_key_status"),
        ),
        sa.CheckConstraint(
            "migration_status IN ('planned', 'migrating', 'migrated', 'rolled_back')",
            name=op.f("ck_organization_key_versions_key_migration_status"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "version", name=op.f("uq_organization_key_versions_org_version")
        ),
    )
    op.create_index(
        op.f("ix_organization_key_versions_organization_id"),
        "organization_key_versions",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_organization_key_versions_status"), "organization_key_versions", ["status"]
    )
    op.create_index(
        op.f("ix_organization_key_versions_migration_status"),
        "organization_key_versions",
        ["migration_status"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_organization_key_versions_migration_status"),
        table_name="organization_key_versions",
    )
    op.drop_index(
        op.f("ix_organization_key_versions_status"), table_name="organization_key_versions"
    )
    op.drop_index(
        op.f("ix_organization_key_versions_organization_id"),
        table_name="organization_key_versions",
    )
    op.drop_table("organization_key_versions")
    op.drop_table("organization_governance")
