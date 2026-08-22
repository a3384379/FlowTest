"""Add organizations, tenant membership, and organization service accounts."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0035"
down_revision: str | None = "20260822_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=4000), server_default="", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
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
            name=op.f("fk_organizations_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index(op.f("ix_organizations_created_by_id"), "organizations", ["created_by_id"])
    op.create_index(op.f("ix_organizations_enabled"), "organizations", ["enabled"])

    op.create_table(
        "organization_members",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="member", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="organization_member_role",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_members_org_user"),
    )
    op.create_index(
        op.f("ix_organization_members_organization_id"),
        "organization_members",
        ["organization_id"],
    )
    op.create_index(op.f("ix_organization_members_user"), "organization_members", ["user_id"])
    op.create_index(op.f("ix_organization_members_user_id"), "organization_members", ["user_id"])

    op.create_table(
        "service_accounts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("account_key", sa.String(length=120), nullable=False),
        sa.Column("token_prefix", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), server_default="{}", nullable=False),
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
            name=op.f("fk_service_accounts_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_service_accounts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_accounts")),
        sa.UniqueConstraint("organization_id", "name", name="uq_service_accounts_org_name"),
        sa.UniqueConstraint("organization_id", "account_key", name="uq_service_accounts_org_key"),
        sa.UniqueConstraint("token_prefix", name="uq_service_accounts_token_prefix"),
    )
    op.create_index(
        op.f("ix_service_accounts_organization_id"), "service_accounts", ["organization_id"]
    )
    op.create_index(op.f("ix_service_accounts_account_key"), "service_accounts", ["account_key"])
    op.create_index(op.f("ix_service_accounts_token_prefix"), "service_accounts", ["token_prefix"])
    op.create_index(
        op.f("ix_service_accounts_token_hash"),
        "service_accounts",
        ["token_hash"],
        unique=True,
    )
    op.create_index(op.f("ix_service_accounts_enabled"), "service_accounts", ["enabled"])
    op.create_index(op.f("ix_service_accounts_expires_at"), "service_accounts", ["expires_at"])
    op.create_index(op.f("ix_service_accounts_revoked_at"), "service_accounts", ["revoked_at"])

    for table in ("projects", "audit_logs", "runner_pools"):
        op.add_column(table, sa.Column("organization_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_organization_id_organizations"),
            table,
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])

    _backfill_default_organization(op.get_bind())


def _backfill_default_organization(bind: sa.Connection) -> None:
    existing = bind.execute(
        sa.text("SELECT id FROM organizations WHERE slug = 'default'")
    ).scalar_one_or_none()
    if existing is None:
        organization_id = uuid4()
        creator = bind.execute(
            sa.text("SELECT id FROM users ORDER BY created_at, id LIMIT 1")
        ).scalar_one_or_none()
        bind.execute(
            sa.text(
                "INSERT INTO organizations "
                "(id, name, slug, description, enabled, created_by_id) "
                "VALUES (:id, :name, :slug, :description, :enabled, :created_by_id)"
            ),
            {
                "id": organization_id,
                "name": "Default Organization",
                "slug": "default",
                "description": "迁移兼容的默认组织",
                "enabled": True,
                "created_by_id": creator,
            },
        )
    else:
        organization_id = existing

    bind.execute(
        sa.text(
            "UPDATE projects SET organization_id = :organization_id WHERE organization_id IS NULL"
        ),
        {"organization_id": organization_id},
    )
    bind.execute(
        sa.text(
            "UPDATE runner_pools SET organization_id = :organization_id "
            "WHERE organization_id IS NULL"
        ),
        {"organization_id": organization_id},
    )
    bind.execute(
        sa.text(
            "UPDATE audit_logs SET organization_id = "
            "(SELECT projects.organization_id FROM projects "
            "WHERE projects.id = audit_logs.project_id) "
            "WHERE organization_id IS NULL AND project_id IS NOT NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE audit_logs SET organization_id = :organization_id WHERE organization_id IS NULL"
        ),
        {"organization_id": organization_id},
    )
    users = bind.execute(sa.text("SELECT id, is_system_admin FROM users ORDER BY created_at, id"))
    for user_id, is_system_admin in users:
        member_exists = bind.execute(
            sa.text(
                "SELECT id FROM organization_members "
                "WHERE organization_id = :organization_id AND user_id = :user_id"
            ),
            {"organization_id": organization_id, "user_id": user_id},
        ).scalar_one_or_none()
        if member_exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO organization_members "
                    "(id, organization_id, user_id, role) "
                    "VALUES (:id, :organization_id, :user_id, :role)"
                ),
                {
                    "id": uuid4(),
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "role": "owner" if is_system_admin else "member",
                },
            )


def downgrade() -> None:
    for table in ("runner_pools", "audit_logs", "projects"):
        op.drop_index(op.f(f"ix_{table}_organization_id"), table_name=table)
        op.drop_constraint(
            op.f(f"fk_{table}_organization_id_organizations"), table, type_="foreignkey"
        )
        op.drop_column(table, "organization_id")
    for index_name in (
        "ix_service_accounts_revoked_at",
        "ix_service_accounts_expires_at",
        "ix_service_accounts_enabled",
        "ix_service_accounts_token_prefix",
        "ix_service_accounts_token_hash",
        "ix_service_accounts_account_key",
        "ix_service_accounts_organization_id",
    ):
        op.drop_index(op.f(index_name), table_name="service_accounts")
    op.drop_table("service_accounts")
    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_index(op.f("ix_organization_members_user"), table_name="organization_members")
    op.drop_index(
        op.f("ix_organization_members_organization_id"), table_name="organization_members"
    )
    op.drop_table("organization_members")
    op.drop_index(op.f("ix_organizations_enabled"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_created_by_id"), table_name="organizations")
    op.drop_table("organizations")
