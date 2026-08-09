"""Create S2 API asset and environment tables.

Revision ID: 20260809_0002
Revises: 20260809_0001
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0002"
down_revision: str | None = "20260809_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    empty_json = sa.text("'{}'::json")
    op.add_column(
        "projects",
        sa.Column("variables", sa.JSON(), server_default=empty_json, nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("headers", sa.JSON(), server_default=empty_json, nullable=False),
    )
    _create_environments()
    _create_api_definitions()
    _create_secrets()
    _create_api_versions()


def _create_environments() -> None:
    op.create_table(
        "environments",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
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
            name=op.f("fk_environments_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_environments_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environments")),
        sa.UniqueConstraint("project_id", "name", name="uq_environments_project_name"),
    )
    op.create_index(op.f("ix_environments_project_id"), "environments", ["project_id"])


def _create_api_definitions() -> None:
    op.create_table(
        "api_definitions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
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
            name=op.f("fk_api_definitions_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folders.id"],
            name=op.f("fk_api_definitions_folder_id_folders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_api_definitions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_definitions")),
    )
    op.create_index(op.f("ix_api_definitions_folder_id"), "api_definitions", ["folder_id"])
    op.create_index(
        "ix_api_definitions_project_folder",
        "api_definitions",
        ["project_id", "folder_id"],
    )
    op.create_index(op.f("ix_api_definitions_project_id"), "api_definitions", ["project_id"])


def _create_secrets() -> None:
    op.create_table(
        "secrets",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
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
            name=op.f("fk_secrets_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name=op.f("fk_secrets_environment_id_environments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_secrets_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secrets")),
        sa.UniqueConstraint(
            "project_id",
            "environment_id",
            "name",
            name="uq_secrets_project_environment_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_secrets_environment_id"), "secrets", ["environment_id"])
    op.create_index(op.f("ix_secrets_project_id"), "secrets", ["project_id"])


def _create_api_versions() -> None:
    op.create_table(
        "api_versions",
        sa.Column("api_definition_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("query_parameters", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body_kind", sa.String(length=16), nullable=False),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("auth_kind", sa.String(length=16), nullable=False),
        sa.Column("auth_config", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "auth_kind IN ('none', 'bearer', 'basic', 'api_key')", name="api_auth_kind"
        ),
        sa.CheckConstraint("body_kind IN ('none', 'json', 'raw', 'form')", name="api_body_kind"),
        sa.CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')", name="api_http_method"
        ),
        sa.ForeignKeyConstraint(
            ["api_definition_id"],
            ["api_definitions.id"],
            name=op.f("fk_api_versions_api_definition_id_api_definitions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_api_versions_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_versions")),
        sa.UniqueConstraint(
            "api_definition_id", "version", name="uq_api_versions_definition_version"
        ),
    )
    op.create_index(
        op.f("ix_api_versions_api_definition_id"),
        "api_versions",
        ["api_definition_id"],
    )


def downgrade() -> None:
    op.drop_table("api_versions")
    op.drop_table("secrets")
    op.drop_table("api_definitions")
    op.drop_table("environments")
    op.drop_column("projects", "headers")
    op.drop_column("projects", "variables")
