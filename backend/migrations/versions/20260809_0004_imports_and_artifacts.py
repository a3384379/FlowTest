"""Create S4 import tracking and artifact storage metadata.

Revision ID: 20260809_0004
Revises: 20260809_0003
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0004"
down_revision: str | None = "20260809_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _extend_api_assets()
    _create_import_runs()
    _create_artifacts()
    op.add_column("api_call_executions", sa.Column("response_artifact_id", sa.Uuid()))
    op.create_foreign_key(
        op.f("fk_api_call_executions_response_artifact_id_artifacts"),
        "api_call_executions",
        "artifacts",
        ["response_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_api_call_executions_response_artifact_id"),
        "api_call_executions",
        ["response_artifact_id"],
    )


def _extend_api_assets() -> None:
    op.add_column("api_definitions", sa.Column("import_key", sa.String(length=64)))
    op.add_column("api_definitions", sa.Column("import_fingerprint", sa.String(length=64)))
    op.add_column("api_definitions", sa.Column("import_source", sa.String(length=255)))
    op.create_index(op.f("ix_api_definitions_import_key"), "api_definitions", ["import_key"])
    op.create_index(op.f("ix_api_definitions_import_source"), "api_definitions", ["import_source"])
    op.create_unique_constraint(
        "uq_api_definitions_project_import_key",
        "api_definitions",
        ["project_id", "import_key"],
    )
    op.drop_constraint("api_body_kind", "api_versions", type_="check")
    op.create_check_constraint(
        "api_body_kind",
        "api_versions",
        "body_kind IN ('none', 'json', 'raw', 'form', 'multipart')",
    )


def _create_import_runs() -> None:
    op.create_table(
        "import_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("added", sa.Integer(), nullable=False),
        sa.Column("changed", sa.Integer(), nullable=False),
        sa.Column("deleted", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_type IN ('openapi3', 'swagger2', 'postman')",
            name="import_run_source_type",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_import_runs_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_import_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_runs")),
    )
    op.create_index(op.f("ix_import_runs_project_id"), "import_runs", ["project_id"])


def _create_artifacts() -> None:
    op.create_table(
        "artifacts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
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
            name=op.f("fk_artifacts_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_artifacts_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint("object_key", name=op.f("uq_artifacts_object_key")),
    )
    op.create_index(op.f("ix_artifacts_project_id"), "artifacts", ["project_id"])
    op.create_index("ix_artifacts_project_created", "artifacts", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index(
        op.f("ix_api_call_executions_response_artifact_id"),
        table_name="api_call_executions",
    )
    op.drop_constraint(
        op.f("fk_api_call_executions_response_artifact_id_artifacts"),
        "api_call_executions",
        type_="foreignkey",
    )
    op.drop_column("api_call_executions", "response_artifact_id")
    op.drop_table("artifacts")
    op.drop_table("import_runs")
    op.drop_constraint("api_body_kind", "api_versions", type_="check")
    op.create_check_constraint(
        "api_body_kind", "api_versions", "body_kind IN ('none', 'json', 'raw', 'form')"
    )
    op.drop_constraint("uq_api_definitions_project_import_key", "api_definitions", type_="unique")
    op.drop_index(op.f("ix_api_definitions_import_source"), table_name="api_definitions")
    op.drop_index(op.f("ix_api_definitions_import_key"), table_name="api_definitions")
    op.drop_column("api_definitions", "import_source")
    op.drop_column("api_definitions", "import_fingerprint")
    op.drop_column("api_definitions", "import_key")
