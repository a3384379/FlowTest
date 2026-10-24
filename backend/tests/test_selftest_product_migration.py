from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.models.self_tests import SelfTestBatch, SelfTestInstallation, SelfTestScenarioResult


def _migration(name: str = "20261023_0066_self_tests.py"):
    path = Path(__file__).parent.parent / "migrations/versions" / name
    spec = spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_selftest_migration_compiles_upgrade_and_downgrade(monkeypatch, dialect: str) -> None:
    migration, output = _migration(), StringIO()
    registration = _migration("20261023_0067_self_test_host_registration.py")
    context = MigrationContext.configure(
        dialect_name=dialect, opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    monkeypatch.setattr(registration, "op", Operations(context))
    migration.upgrade()
    registration.upgrade()
    registration.downgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE self_test_installations" in sql
    assert "CREATE TABLE self_test_batches" in sql
    assert "CREATE TABLE self_test_scenario_results" in sql
    assert "ON DELETE SET NULL" in sql and "ON DELETE RESTRICT" in sql
    assert sql.index("DROP TABLE self_test_scenario_results") < sql.index(
        "DROP TABLE self_test_batches"
    )
    assert sql.index("DROP TABLE self_test_batches") < sql.index(
        "DROP TABLE self_test_installations"
    )


def test_selftest_migration_round_trip_matches_model_columns_and_constraints(monkeypatch) -> None:
    migration = _migration()
    registration = _migration("20261023_0067_self_test_host_registration.py")
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            for name in (
                "projects",
                "users",
                "test_plans",
                "test_plan_runs",
                "test_plan_run_items",
                "workflow_executions",
            ):
                connection.exec_driver_sql(f"CREATE TABLE {name} (id CHAR(32) PRIMARY KEY)")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            monkeypatch.setattr(
                registration, "op", Operations(MigrationContext.configure(connection))
            )
            migration.upgrade()
            registration.upgrade()
            inspector = inspect(connection)
            for model in (SelfTestInstallation, SelfTestBatch, SelfTestScenarioResult):
                table = model.__table__
                assert {column["name"] for column in inspector.get_columns(table.name)} == set(
                    table.columns.keys()
                )
                database_checks = {
                    check["sqltext"] for check in inspector.get_check_constraints(table.name)
                }
                model_checks = {
                    str(constraint.sqltext)
                    for constraint in table.constraints
                    if hasattr(constraint, "sqltext")
                }
                assert database_checks == model_checks
            registration.downgrade()
            migration.downgrade()
            assert not any(
                name.startswith("self_test_") for name in inspect(connection).get_table_names()
            )
    finally:
        engine.dispose()
