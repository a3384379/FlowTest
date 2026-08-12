"""Add immutable GraphQL and gRPC schema artifacts.

Revision ID: 20260812_0020
Revises: 20260812_0019
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0020"
down_revision: str | None = "20260812_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_credentials_credential_kind"), "credentials", type_="check")
    op.create_check_constraint(
        op.f("ck_credentials_credential_kind"),
        "credentials",
        "kind IN ('postgresql', 'mysql', 'redis', 'grpc_mtls')",
    )
    op.create_table(
        "schema_artifacts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_format", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("canonical_content", sa.LargeBinary(), nullable=False),
        sa.Column("source_content", sa.LargeBinary(), nullable=False),
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
            "protocol IN ('graphql', 'grpc')",
            name=op.f("ck_schema_artifacts_schema_artifact_protocol"),
        ),
        sa.CheckConstraint(
            "source_format IN ('graphql_sdl', 'graphql_introspection', "
            "'proto_source', 'proto_descriptor_set', 'grpc_reflection')",
            name=op.f("ck_schema_artifacts_schema_artifact_source_format"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_schema_artifacts_schema_artifact_version"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_schema_artifacts_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_schema_artifacts_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schema_artifacts")),
        sa.UniqueConstraint(
            "project_id",
            "protocol",
            "name",
            "version",
            name="uq_schema_artifacts_project_protocol_name_version",
        ),
        sa.UniqueConstraint(
            "project_id",
            "protocol",
            "content_sha256",
            name="uq_schema_artifacts_project_protocol_hash",
        ),
    )
    op.create_index(op.f("ix_schema_artifacts_project_id"), "schema_artifacts", ["project_id"])
    op.create_index(op.f("ix_schema_artifacts_protocol"), "schema_artifacts", ["protocol"])
    op.create_index(
        op.f("ix_schema_artifacts_content_sha256"),
        "schema_artifacts",
        ["content_sha256"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_schema_artifacts_content_sha256"), table_name="schema_artifacts")
    op.drop_index(op.f("ix_schema_artifacts_protocol"), table_name="schema_artifacts")
    op.drop_index(op.f("ix_schema_artifacts_project_id"), table_name="schema_artifacts")
    op.drop_table("schema_artifacts")
    op.drop_constraint(op.f("ck_credentials_credential_kind"), "credentials", type_="check")
    op.create_check_constraint(
        op.f("ck_credentials_credential_kind"),
        "credentials",
        "kind IN ('postgresql', 'mysql', 'redis')",
    )
