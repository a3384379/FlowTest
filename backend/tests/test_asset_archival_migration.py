from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_asset_archival_migration_retains_rows_versions_and_reverses_with_foreign_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(__file__).parent.parent / "migrations/versions/20261003_0063_test_asset_archival.py"
    spec = spec_from_file_location("test_asset_archival_sqlite", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            for table in ("test_cases", "test_suites"):
                connection.exec_driver_sql(
                    f"CREATE TABLE {table} (id TEXT PRIMARY KEY, "
                    "project_id TEXT, folder_id TEXT, name TEXT)"
                )
                connection.exec_driver_sql(
                    f"INSERT INTO {table} VALUES ('asset-1', 'project-1', NULL, '保留资产')"
                )
            connection.exec_driver_sql(
                "CREATE TABLE test_case_versions (id TEXT PRIMARY KEY, "
                "test_case_id TEXT REFERENCES test_cases(id), definition TEXT)"
            )
            connection.exec_driver_sql(
                "INSERT INTO test_case_versions VALUES "
                "('version-1', 'asset-1', 'frozen-definition')"
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            for table in ("test_cases", "test_suites"):
                columns = {item["name"] for item in inspect(connection).get_columns(table)}
                assert "archived_at" in columns
                assert (
                    connection.exec_driver_sql(f"SELECT archived_at FROM {table}").scalar() is None
                )
                connection.exec_driver_sql(f"UPDATE {table} SET archived_at='2026-10-03T00:00:00Z'")
                indexes = {item["name"] for item in inspect(connection).get_indexes(table)}
                assert f"ix_{table}_project_folder_active" in indexes
            migration.downgrade()
            for table in ("test_cases", "test_suites"):
                columns = {item["name"] for item in inspect(connection).get_columns(table)}
                assert "archived_at" not in columns
                assert (
                    connection.exec_driver_sql(f"SELECT name FROM {table}").scalar() == "保留资产"
                )
            assert (
                connection.exec_driver_sql("SELECT definition FROM test_case_versions").scalar()
                == "frozen-definition"
            )
    finally:
        engine.dispose()


def test_asset_archival_migration_compiles_for_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path(__file__).parent.parent / "migrations/versions/20261003_0063_test_asset_archival.py"
    spec = spec_from_file_location("test_asset_archival_postgresql", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    for table in ("test_cases", "test_suites"):
        assert f"ALTER TABLE {table} ADD COLUMN archived_at" in output.getvalue()
        assert f"ALTER TABLE {table} DROP COLUMN archived_at" in output.getvalue()
