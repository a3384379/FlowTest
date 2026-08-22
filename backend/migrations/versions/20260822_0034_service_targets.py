"""Add project-local Service and ServiceEndpoint request targets.

Existing environments are kept executable by creating one ``default`` service
per project and one ``default`` endpoint per environment.  The legacy
``Environment.base_url`` remains available as the final resolver fallback.
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0034"
down_revision: str | None = "20260822_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("service_key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("owner_team", sa.String(length=160), nullable=True),
        sa.Column("service_type", sa.String(length=16), server_default="http", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("service_key <> ''", name="service_service_key_not_empty"),
        sa.CheckConstraint(
            "service_type IN ('http', 'https', 'grpc', 'graphql', 'other')",
            name="service_type",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_services_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_services_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_services")),
        sa.UniqueConstraint("project_id", "service_key", name="uq_services_project_service_key"),
    )
    op.create_index(op.f("ix_services_project_id"), "services", ["project_id"])
    op.create_index(op.f("ix_services_service_key"), "services", ["service_key"])
    op.create_index(op.f("ix_services_enabled"), "services", ["enabled"])

    op.create_table(
        "service_endpoints",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("variant", sa.String(length=80), server_default="default", nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("connect_timeout_ms", sa.Integer(), server_default="5000", nullable=False),
        sa.Column("read_timeout_ms", sa.Integer(), server_default="30000", nullable=False),
        sa.Column("tls_verify", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("proxy_ref", sa.String(length=255), nullable=True),
        sa.Column("headers", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("variables", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("secret_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("health_check_path", sa.String(length=2048), nullable=True),
        sa.Column("health_expected_status", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("variant <> ''", name="service_endpoint_variant_not_empty"),
        sa.CheckConstraint(
            "connect_timeout_ms BETWEEN 100 AND 300000",
            name="service_endpoint_connect_timeout",
        ),
        sa.CheckConstraint(
            "read_timeout_ms BETWEEN 100 AND 300000",
            name="service_endpoint_read_timeout",
        ),
        sa.CheckConstraint(
            "health_expected_status IS NULL OR health_expected_status BETWEEN 100 AND 599",
            name="service_endpoint_health_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_service_endpoints_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name=op.f("fk_service_endpoints_environment_id_environments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_service_endpoints_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name=op.f("fk_service_endpoints_service_id_services"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_endpoints")),
        sa.UniqueConstraint(
            "environment_id",
            "service_id",
            "variant",
            name="uq_service_endpoints_environment_service_variant",
        ),
    )
    for column in ("project_id", "environment_id", "service_id", "enabled"):
        op.create_index(op.f(f"ix_service_endpoints_{column}"), "service_endpoints", [column])

    op.add_column(
        "environments",
        sa.Column("default_service_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_environments_default_service_id_services"),
        "environments",
        "services",
        ["default_service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_environments_default_service_id"), "environments", ["default_service_id"]
    )

    op.add_column("api_definitions", sa.Column("service_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_api_definitions_service_id_services"),
        "api_definitions",
        "services",
        ["service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_api_definitions_service_id"), "api_definitions", ["service_id"])

    op.add_column(
        "api_versions",
        sa.Column("variables", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "api_call_executions",
        sa.Column("target_snapshot", sa.JSON(), server_default="{}", nullable=False),
    )

    _backfill_default_targets(op.get_bind())


def _backfill_default_targets(bind: sa.Connection) -> None:
    services = sa.table(
        "services",
        sa.column("id", sa.Uuid()),
        sa.column("project_id", sa.Uuid()),
        sa.column("service_key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("created_by_id", sa.Uuid()),
    )
    endpoints = sa.table(
        "service_endpoints",
        sa.column("id", sa.Uuid()),
        sa.column("project_id", sa.Uuid()),
        sa.column("environment_id", sa.Uuid()),
        sa.column("service_id", sa.Uuid()),
        sa.column("variant", sa.String()),
        sa.column("base_url", sa.String()),
        sa.column("created_by_id", sa.Uuid()),
    )
    project_rows = bind.execute(
        sa.text("SELECT id, created_by_id FROM projects ORDER BY id")
    ).mappings()
    for project in project_rows:
        service_id = uuid4()
        bind.execute(
            services.insert().values(
                id=service_id,
                project_id=project["id"],
                service_key="default",
                name="Default Service",
                created_by_id=project["created_by_id"],
            )
        )
        bind.execute(
            sa.text(
                "UPDATE environments SET default_service_id = :service_id "
                "WHERE project_id = :project_id"
            ),
            {"service_id": service_id, "project_id": project["id"]},
        )
        bind.execute(
            sa.text(
                "UPDATE api_definitions SET service_id = :service_id "
                "WHERE project_id = :project_id AND service_id IS NULL"
            ),
            {"service_id": service_id, "project_id": project["id"]},
        )
        environment_rows = bind.execute(
            sa.text(
                "SELECT id, base_url, created_by_id FROM environments "
                "WHERE project_id = :project_id ORDER BY id"
            ),
            {"project_id": project["id"]},
        ).mappings()
        for environment in environment_rows:
            bind.execute(
                endpoints.insert().values(
                    id=uuid4(),
                    project_id=project["id"],
                    environment_id=environment["id"],
                    service_id=service_id,
                    variant="default",
                    base_url=environment["base_url"],
                    created_by_id=environment["created_by_id"],
                )
            )


def downgrade() -> None:
    op.drop_column("api_call_executions", "target_snapshot")
    op.drop_column("api_versions", "variables")
    op.drop_index(op.f("ix_api_definitions_service_id"), table_name="api_definitions")
    op.drop_constraint(
        op.f("fk_api_definitions_service_id_services"), "api_definitions", type_="foreignkey"
    )
    op.drop_column("api_definitions", "service_id")
    op.drop_index(op.f("ix_environments_default_service_id"), table_name="environments")
    op.drop_constraint(
        op.f("fk_environments_default_service_id_services"), "environments", type_="foreignkey"
    )
    op.drop_column("environments", "default_service_id")
    for column in ("project_id", "environment_id", "service_id", "enabled"):
        op.drop_index(op.f(f"ix_service_endpoints_{column}"), table_name="service_endpoints")
    op.drop_table("service_endpoints")
    op.drop_index(op.f("ix_services_enabled"), table_name="services")
    op.drop_index(op.f("ix_services_service_key"), table_name="services")
    op.drop_index(op.f("ix_services_project_id"), table_name="services")
    op.drop_table("services")
