"""Bootstrap the current schema for the single-process runtime.

Standalone installs intentionally do not invoke a separate migration container.  The
database is created from the checked-in SQLAlchemy metadata on first start and is
stamped with the latest migration revision.  Subsequent schema changes still use
Alembic; the stamp keeps the normal migration tooling aware of the installed baseline.
"""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.database import engine
from app.models import Base

BASELINE_REVISION = "20260822_0034"


async def initialize_standalone_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "INSERT OR IGNORE INTO flowtest_standalone_meta (key, value) "
                "VALUES ('schema_baseline', :revision)"
            ),
            {"revision": BASELINE_REVISION},
        )
        await connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        await connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "SELECT :revision WHERE NOT EXISTS (SELECT 1 FROM alembic_version)"
            ),
            {"revision": BASELINE_REVISION},
        )
        await _ensure_incremental_columns(connection)


async def _ensure_incremental_columns(connection: AsyncConnection) -> None:
    """Keep an existing offline SQLite installation bootable after an upgrade."""

    await _add_column_if_missing(
        connection,
        table="projects",
        column="outbound_policy_enabled",
        definition="BOOLEAN NOT NULL DEFAULT 1",
    )
    await _add_column_if_missing(
        connection,
        table="environments",
        column="default_service_id",
        definition="CHAR(32)",
    )
    await _add_column_if_missing(
        connection,
        table="api_definitions",
        column="service_id",
        definition="CHAR(32)",
    )
    await _add_column_if_missing(
        connection,
        table="api_versions",
        column="variables",
        definition="JSON NOT NULL DEFAULT '{}'",
    )
    await _add_column_if_missing(
        connection,
        table="api_call_executions",
        column="target_snapshot",
        definition="JSON NOT NULL DEFAULT '{}'",
    )
    await _ensure_default_targets(connection)
    await connection.execute(
        text(
            "UPDATE flowtest_standalone_meta SET value = :revision "
            "WHERE key = 'schema_baseline' AND value IN ('20260822_0032', '20260822_0033')"
        ),
        {"revision": BASELINE_REVISION},
    )
    await connection.execute(
        text(
            "UPDATE alembic_version SET version_num = :revision "
            "WHERE version_num IN ('20260822_0032', '20260822_0033')"
        ),
        {"revision": BASELINE_REVISION},
    )


async def _add_column_if_missing(
    connection: AsyncConnection,
    *,
    table: str,
    column: str,
    definition: str,
) -> None:
    result = await connection.execute(text(f"PRAGMA table_info({table})"))
    rows = result.fetchall()
    if not rows:
        return
    columns = {str(row[1]) for row in rows}
    if column not in columns:
        await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


async def _ensure_default_targets(connection: AsyncConnection) -> None:
    required_tables = {
        "projects",
        "services",
        "environments",
        "api_definitions",
        "service_endpoints",
    }
    existing_tables = {
        table
        for table in required_tables
        if (await connection.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    }
    if existing_tables != required_tables:
        return
    projects = await connection.execute(text("SELECT id, created_by_id FROM projects"))
    for project_id, created_by_id in projects.fetchall():
        service = await connection.execute(
            text(
                "SELECT id FROM services WHERE project_id = :project_id AND service_key = 'default'"
            ),
            {"project_id": project_id},
        )
        service_id = service.scalar_one_or_none()
        if service_id is None:
            service_id = uuid4().hex
            await connection.execute(
                text(
                    "INSERT INTO services "
                    "(id, project_id, service_key, name, created_by_id) "
                    "VALUES (:id, :project_id, 'default', 'Default Service', :created_by_id)"
                ),
                {
                    "id": service_id,
                    "project_id": project_id,
                    "created_by_id": created_by_id,
                },
            )
        await connection.execute(
            text(
                "UPDATE environments SET default_service_id = :service_id "
                "WHERE project_id = :project_id AND default_service_id IS NULL"
            ),
            {"service_id": service_id, "project_id": project_id},
        )
        await connection.execute(
            text(
                "UPDATE api_definitions SET service_id = :service_id "
                "WHERE project_id = :project_id AND service_id IS NULL"
            ),
            {"service_id": service_id, "project_id": project_id},
        )
        environments = await connection.execute(
            text(
                "SELECT id, base_url, created_by_id FROM environments "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
        for environment_id, base_url, environment_created_by_id in environments.fetchall():
            existing = await connection.execute(
                text(
                    "SELECT id FROM service_endpoints WHERE environment_id = :environment_id "
                    "AND service_id = :service_id AND variant = 'default'"
                ),
                {"environment_id": environment_id, "service_id": service_id},
            )
            if existing.scalar_one_or_none() is None:
                await connection.execute(
                    text(
                        "INSERT INTO service_endpoints "
                        "(id, project_id, environment_id, service_id, variant, base_url, "
                        "created_by_id) "
                        "VALUES (:id, :project_id, :environment_id, :service_id, 'default', "
                        ":base_url, :created_by_id)"
                    ),
                    {
                        "id": uuid4().hex,
                        "project_id": project_id,
                        "environment_id": environment_id,
                        "service_id": service_id,
                        "base_url": base_url,
                        "created_by_id": environment_created_by_id,
                    },
                )
