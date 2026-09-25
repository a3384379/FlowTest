"""The project outbound policy migration remains reversible on SQLite."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_project_outbound_limit_migration_round_trip(monkeypatch) -> None:
    migration_path = (
        Path(__file__).parent.parent
        / "migrations/versions/20260925_0058_project_outbound_limits.py"
    )
    spec = spec_from_file_location("project_outbound_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            names = {column["name"] for column in inspect(connection).get_columns("projects")}
            assert {"outbound_concurrency_limit", "outbound_requests_per_minute"} <= names
            assert {"outbound_permits", "outbound_rate_windows"} <= set(
                inspect(connection).get_table_names()
            )

            migration.downgrade()
            names = {column["name"] for column in inspect(connection).get_columns("projects")}
            assert names == {"id"}
            assert "outbound_permits" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()
