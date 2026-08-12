"""Add Kafka schemas and immutable event sources.

Revision ID: 20260812_0021
Revises: 20260812_0020
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0021"
down_revision: str | None = "20260812_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_schema_artifacts_schema_artifact_protocol"),
        "schema_artifacts",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_schema_artifacts_schema_artifact_source_format"),
        "schema_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_schema_artifacts_schema_artifact_protocol"),
        "schema_artifacts",
        "protocol IN ('graphql', 'grpc', 'kafka')",
    )
    op.create_check_constraint(
        op.f("ck_schema_artifacts_schema_artifact_source_format"),
        "schema_artifacts",
        "source_format IN ('graphql_sdl', 'graphql_introspection', "
        "'proto_source', 'proto_descriptor_set', 'grpc_reflection', "
        "'event_avro', 'event_json_schema', 'event_protobuf')",
    )
    op.create_table(
        "event_sources",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("endpoints", sa.JSON(), nullable=False),
        sa.Column("schema_registry_url", sa.String(length=2048), nullable=True),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('kafka', 'websocket')",
            name=op.f("ck_event_sources_event_source_kind"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_event_sources_event_source_version"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_event_sources_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_event_sources_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_sources")),
        sa.UniqueConstraint(
            "project_id",
            "kind",
            "name",
            "version",
            name="uq_event_sources_project_kind_name_version",
        ),
        sa.UniqueConstraint(
            "project_id",
            "kind",
            "config_sha256",
            name="uq_event_sources_project_kind_hash",
        ),
    )
    op.create_index(op.f("ix_event_sources_project_id"), "event_sources", ["project_id"])
    op.create_index(op.f("ix_event_sources_kind"), "event_sources", ["kind"])
    op.create_index(op.f("ix_event_sources_config_sha256"), "event_sources", ["config_sha256"])


def downgrade() -> None:
    op.drop_index(op.f("ix_event_sources_config_sha256"), table_name="event_sources")
    op.drop_index(op.f("ix_event_sources_kind"), table_name="event_sources")
    op.drop_index(op.f("ix_event_sources_project_id"), table_name="event_sources")
    op.drop_table("event_sources")
    op.drop_constraint(
        op.f("ck_schema_artifacts_schema_artifact_source_format"),
        "schema_artifacts",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_schema_artifacts_schema_artifact_protocol"),
        "schema_artifacts",
        type_="check",
    )
    # Kafka artifacts cannot exist in the S23 schema. A deliberate downgrade
    # removes only S24-owned protocol assets before restoring the old checks.
    op.execute(sa.text("DELETE FROM schema_artifacts WHERE protocol = 'kafka'"))
    op.create_check_constraint(
        op.f("ck_schema_artifacts_schema_artifact_protocol"),
        "schema_artifacts",
        "protocol IN ('graphql', 'grpc')",
    )
    op.create_check_constraint(
        op.f("ck_schema_artifacts_schema_artifact_source_format"),
        "schema_artifacts",
        "source_format IN ('graphql_sdl', 'graphql_introspection', "
        "'proto_source', 'proto_descriptor_set', 'grpc_reflection')",
    )
