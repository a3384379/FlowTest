"""The test case source columns migrate reversibly on SQLite."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_case_run_source_migration_round_trip(monkeypatch) -> None:
    path = (
        Path(__file__).parent.parent / "migrations/versions/20260928_0062_test_case_run_source.py"
    )
    spec = spec_from_file_location("test_case_run_source_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE test_cases (id VARCHAR(36) PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE test_plan_run_items (id VARCHAR(36) PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE workflow_executions ("
                "id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36), started_at DATETIME)"
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            names = {
                column["name"] for column in inspect(connection).get_columns("workflow_executions")
            }
            assert {
                "source_case_id",
                "source_case_version",
                "source_trigger",
                "source_plan_run_item_id",
            } <= names
            assert "ix_workflow_executions_case_latest" in {
                index["name"] for index in inspect(connection).get_indexes("workflow_executions")
            }
            migration.downgrade()
            names = {
                column["name"] for column in inspect(connection).get_columns("workflow_executions")
            }
            assert names == {"id", "project_id", "started_at"}
    finally:
        engine.dispose()
