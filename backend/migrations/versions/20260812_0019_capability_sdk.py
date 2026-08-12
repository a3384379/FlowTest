"""Add V3 capability, plugin, and runner contracts.

Revision ID: 20260812_0019
Revises: 20260812_0018
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0019"
down_revision: str | None = "20260812_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("plugin_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("oci_repository", sa.String(length=500), nullable=False),
        sa.Column("oci_digest", sa.String(length=71), nullable=False),
        sa.Column("signature_identity", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'disabled')",
            name=op.f("ck_plugins_plugin_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_plugins_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plugins")),
        sa.UniqueConstraint("oci_digest", name="uq_plugins_oci_digest"),
        sa.UniqueConstraint("plugin_key", "version", name="uq_plugins_plugin_key_version"),
    )
    op.create_index(op.f("ix_plugins_plugin_key"), "plugins", ["plugin_key"])

    op.create_table(
        "capabilities",
        sa.Column("capability_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("runner_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("plugin_id", sa.Uuid()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('builtin', 'plugin')",
            name=op.f("ck_capabilities_capability_source"),
        ),
        sa.ForeignKeyConstraint(
            ["plugin_id"],
            ["plugins.id"],
            name=op.f("fk_capabilities_plugin_id_plugins"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capabilities")),
        sa.UniqueConstraint(
            "capability_key",
            "version",
            name="uq_capabilities_capability_key_version",
        ),
    )
    op.create_index(op.f("ix_capabilities_capability_key"), "capabilities", ["capability_key"])
    op.create_index(op.f("ix_capabilities_category"), "capabilities", ["category"])
    op.create_index(op.f("ix_capabilities_runner_type"), "capabilities", ["runner_type"])
    op.create_index(op.f("ix_capabilities_source"), "capabilities", ["source"])
    op.create_index(op.f("ix_capabilities_schema_hash"), "capabilities", ["schema_hash"])
    op.create_index(op.f("ix_capabilities_plugin_id"), "capabilities", ["plugin_id"])

    op.create_table(
        "runner_pools",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("runner_type", sa.String(length=32), nullable=False),
        sa.Column("network_zone", sa.String(length=100), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default="20", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
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
            name=op.f("fk_runner_pools_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_pools")),
        sa.UniqueConstraint("name", name="uq_runner_pools_name"),
    )
    op.create_index(op.f("ix_runner_pools_runner_type"), "runner_pools", ["runner_type"])

    op.create_table(
        "runners",
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("identity_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="offline", nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("current_load", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('offline', 'online', 'draining', 'disabled')",
            name=op.f("ck_runners_runner_status"),
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"],
            ["runner_pools.id"],
            name=op.f("fk_runners_pool_id_runner_pools"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runners")),
        sa.UniqueConstraint(
            "identity_fingerprint",
            name="uq_runners_identity_fingerprint",
        ),
        sa.UniqueConstraint("pool_id", "name", name="uq_runners_pool_name"),
    )
    op.create_index(op.f("ix_runners_pool_id"), "runners", ["pool_id"])
    op.create_index(op.f("ix_runners_status"), "runners", ["status"])
    op.create_index(op.f("ix_runners_last_seen_at"), "runners", ["last_seen_at"])

    op.add_column("workflow_node_executions", sa.Column("result", sa.JSON()))


def downgrade() -> None:
    op.drop_column("workflow_node_executions", "result")
    op.drop_index(op.f("ix_runners_last_seen_at"), table_name="runners")
    op.drop_index(op.f("ix_runners_status"), table_name="runners")
    op.drop_index(op.f("ix_runners_pool_id"), table_name="runners")
    op.drop_table("runners")
    op.drop_index(op.f("ix_runner_pools_runner_type"), table_name="runner_pools")
    op.drop_table("runner_pools")
    op.drop_index(op.f("ix_capabilities_plugin_id"), table_name="capabilities")
    op.drop_index(op.f("ix_capabilities_schema_hash"), table_name="capabilities")
    op.drop_index(op.f("ix_capabilities_source"), table_name="capabilities")
    op.drop_index(op.f("ix_capabilities_runner_type"), table_name="capabilities")
    op.drop_index(op.f("ix_capabilities_category"), table_name="capabilities")
    op.drop_index(op.f("ix_capabilities_capability_key"), table_name="capabilities")
    op.drop_table("capabilities")
    op.drop_index(op.f("ix_plugins_plugin_key"), table_name="plugins")
    op.drop_table("plugins")
