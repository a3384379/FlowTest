"""Add encrypted credentials and rule-based mock services.

Revision ID: 20260810_0013
Revises: 20260810_0012
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0013"
down_revision: str | None = "20260810_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_credentials()
    _create_mock_services()


def downgrade() -> None:
    op.drop_index(op.f("ix_mock_request_logs_mock_route_id"), table_name="mock_request_logs")
    op.drop_index(op.f("ix_mock_request_logs_mock_service_id"), table_name="mock_request_logs")
    op.drop_table("mock_request_logs")
    op.drop_index(op.f("ix_mock_routes_scenario"), table_name="mock_routes")
    op.drop_index(op.f("ix_mock_routes_method"), table_name="mock_routes")
    op.drop_index(op.f("ix_mock_routes_mock_service_id"), table_name="mock_routes")
    op.drop_table("mock_routes")
    op.drop_index(op.f("ix_mock_services_slug"), table_name="mock_services")
    op.drop_index(op.f("ix_mock_services_project_id"), table_name="mock_services")
    op.drop_table("mock_services")
    op.drop_index(op.f("ix_credentials_kind"), table_name="credentials")
    op.drop_index(op.f("ix_credentials_project_id"), table_name="credentials")
    op.drop_table("credentials")


def _create_credentials() -> None:
    op.create_table(
        "credentials",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("username", sa.String(length=255), server_default="", nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("tls_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('postgresql', 'mysql', 'redis')",
            name=op.f("ck_credentials_credential_kind"),
        ),
        sa.CheckConstraint(
            "port >= 1 AND port <= 65535",
            name=op.f("ck_credentials_credential_port"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_credentials_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_credentials_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credentials")),
        sa.UniqueConstraint("project_id", "name", name="uq_credentials_project_name"),
    )
    op.create_index(op.f("ix_credentials_project_id"), "credentials", ["project_id"])
    op.create_index(op.f("ix_credentials_kind"), "credentials", ["kind"])


def _create_mock_services() -> None:
    op.create_table(
        "mock_services",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
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
            name=op.f("fk_mock_services_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_mock_services_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mock_services")),
        sa.UniqueConstraint("project_id", "name", name="uq_mock_services_project_name"),
        sa.UniqueConstraint("slug", name="uq_mock_services_slug"),
    )
    op.create_index(op.f("ix_mock_services_project_id"), "mock_services", ["project_id"])
    op.create_index(op.f("ix_mock_services_slug"), "mock_services", ["slug"])
    _create_mock_routes()
    _create_mock_logs()


def _create_mock_routes() -> None:
    op.create_table(
        "mock_routes",
        sa.Column("mock_service_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path_pattern", sa.String(length=1024), nullable=False),
        sa.Column("query_conditions", sa.JSON(), nullable=False),
        sa.Column("header_conditions", sa.JSON(), nullable=False),
        sa.Column("response_status", sa.Integer(), server_default="200", nullable=False),
        sa.Column("response_headers", sa.JSON(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("delay_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')",
            name=op.f("ck_mock_routes_mock_route_method"),
        ),
        sa.CheckConstraint(
            "response_status >= 100 AND response_status <= 599",
            name=op.f("ck_mock_routes_mock_status_code"),
        ),
        sa.CheckConstraint(
            "delay_ms >= 0 AND delay_ms <= 30000",
            name=op.f("ck_mock_routes_mock_delay_ms"),
        ),
        sa.CheckConstraint(
            "priority >= -1000 AND priority <= 1000",
            name=op.f("ck_mock_routes_mock_priority"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_mock_routes_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mock_service_id"],
            ["mock_services.id"],
            name=op.f("fk_mock_routes_mock_service_id_mock_services"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mock_routes")),
        sa.UniqueConstraint("mock_service_id", "name", name="uq_mock_routes_service_name"),
    )
    op.create_index(op.f("ix_mock_routes_mock_service_id"), "mock_routes", ["mock_service_id"])
    op.create_index(op.f("ix_mock_routes_method"), "mock_routes", ["method"])
    op.create_index(op.f("ix_mock_routes_scenario"), "mock_routes", ["scenario"])


def _create_mock_logs() -> None:
    op.create_table(
        "mock_request_logs",
        sa.Column("mock_service_id", sa.Uuid(), nullable=False),
        sa.Column("mock_route_id", sa.Uuid(), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("query_parameters", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("matched", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["mock_route_id"],
            ["mock_routes.id"],
            name=op.f("fk_mock_request_logs_mock_route_id_mock_routes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["mock_service_id"],
            ["mock_services.id"],
            name=op.f("fk_mock_request_logs_mock_service_id_mock_services"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mock_request_logs")),
    )
    op.create_index(
        op.f("ix_mock_request_logs_mock_service_id"),
        "mock_request_logs",
        ["mock_service_id"],
    )
    op.create_index(
        op.f("ix_mock_request_logs_mock_route_id"),
        "mock_request_logs",
        ["mock_route_id"],
    )
