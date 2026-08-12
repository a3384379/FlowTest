"""Add signed environment templates and provisioned instances.

Revision ID: 20260812_0023
Revises: 20260812_0022
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0023"
down_revision: str | None = "20260812_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "environment_templates",
        sa.Column("template_key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name=op.f("ck_environment_templates_environment_template_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_environment_templates_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_templates")),
        sa.UniqueConstraint("template_key", name="uq_environment_templates_key"),
    )
    op.create_index(
        op.f("ix_environment_templates_template_key"),
        "environment_templates",
        ["template_key"],
    )
    op.create_index(op.f("ix_environment_templates_status"), "environment_templates", ["status"])

    op.create_table(
        "environment_template_versions",
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column(
            "signature_algorithm",
            sa.String(length=32),
            server_default="hmac-sha256-v1",
            nullable=False,
        ),
        sa.Column("signed_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_environment_template_versions_version_number"),
        ),
        sa.ForeignKeyConstraint(
            ["signed_by_id"],
            ["users.id"],
            name=op.f("fk_environment_template_versions_signed_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["environment_templates.id"],
            name="fk_env_template_versions_template",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_template_versions")),
        sa.UniqueConstraint(
            "template_id",
            "version",
            name="uq_environment_template_versions_template_version",
        ),
    )
    op.create_index(
        op.f("ix_environment_template_versions_template_id"),
        "environment_template_versions",
        ["template_id"],
    )
    op.create_index(
        op.f("ix_environment_template_versions_manifest_sha256"),
        "environment_template_versions",
        ["manifest_sha256"],
    )

    op.create_table(
        "environment_instances",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("template_version_id", sa.Uuid(), nullable=False),
        sa.Column("template_key", sa.String(length=120), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("cleanup_status", sa.String(length=20), server_default="none", nullable=False),
        sa.Column("runtime_name", sa.String(length=80), nullable=False),
        sa.Column("manifest_snapshot", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), server_default="1", nullable=False),
        sa.Column("endpoints", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("seed_evidence", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("cleanup_error_code", sa.String(length=64), nullable=True),
        sa.Column("cleanup_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "cleanup_attempts >= 0",
            name=op.f("ck_environment_instances_environment_instance_cleanup_attempts"),
        ),
        sa.CheckConstraint(
            "cleanup_status IN ('none', 'pending', 'running', 'completed', 'failed')",
            name=op.f("ck_environment_instances_environment_instance_cleanup_status"),
        ),
        sa.CheckConstraint(
            "fencing_token >= 1",
            name=op.f("ck_environment_instances_environment_instance_fencing_token"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'provisioning', 'ready', 'failed', 'cancelled', "
            "'expired', 'cleaned')",
            name=op.f("ck_environment_instances_environment_instance_status"),
        ),
        sa.CheckConstraint(
            "ttl_seconds >= 60",
            name=op.f("ck_environment_instances_environment_instance_ttl"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_environment_instances_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_environment_instances_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["environment_template_versions.id"],
            name="fk_env_instances_template_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_instances")),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_environment_instances_project_idempotency",
        ),
        sa.UniqueConstraint("runtime_name", name="uq_environment_instances_runtime_name"),
    )
    for column in (
        "project_id",
        "template_version_id",
        "template_key",
        "status",
        "cleanup_status",
        "expires_at",
    ):
        op.create_index(
            op.f(f"ix_environment_instances_{column}"),
            "environment_instances",
            [column],
        )


def downgrade() -> None:
    for column in (
        "expires_at",
        "cleanup_status",
        "status",
        "template_key",
        "template_version_id",
        "project_id",
    ):
        op.drop_index(
            op.f(f"ix_environment_instances_{column}"),
            table_name="environment_instances",
        )
    op.drop_table("environment_instances")
    op.drop_index(
        op.f("ix_environment_template_versions_manifest_sha256"),
        table_name="environment_template_versions",
    )
    op.drop_index(
        op.f("ix_environment_template_versions_template_id"),
        table_name="environment_template_versions",
    )
    op.drop_table("environment_template_versions")
    op.drop_index(op.f("ix_environment_templates_status"), table_name="environment_templates")
    op.drop_index(op.f("ix_environment_templates_template_key"), table_name="environment_templates")
    op.drop_table("environment_templates")
