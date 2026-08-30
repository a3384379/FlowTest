import asyncio
import json
import shutil
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import standalone_schema
from app.core.config import Settings
from app.core.storage import LocalObjectStorage
from app.domain.runtime_profiles import RuntimeProfile, describe_runtime_profile
from app.models import Base
from app.models.test_contexts import ContextEvidenceItem
from app.services.execution_events import (
    ExecutionEvent,
    ExecutionEventType,
    InProcessExecutionEventBus,
)
from app.services.rate_limit import InProcessRateLimiter
from app.tasking import standalone as standalone_tasks
from app.tasking.standalone import StandaloneTaskDispatcher


class _SessionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_standalone_profile_uses_in_process_topology() -> None:
    description = describe_runtime_profile(RuntimeProfile.STANDALONE)
    assert description.worker_topology.value == "in_process"
    assert {feature.value for feature in description.unavailable_features} == {
        "performance_lab",
        "environment_lab",
    }


def test_standalone_rejects_runner_fabric() -> None:
    with pytest.raises(ValidationError, match="Runner Fabric"):
        Settings(
            _env_file=None,
            runtime_profile="standalone",
            feature_runner_fabric_enabled=True,
        )


@pytest.mark.asyncio
async def test_local_object_storage_is_atomic_and_rejects_traversal(tmp_path) -> None:
    storage = LocalObjectStorage(tmp_path / "artifacts")
    await storage.put(key="nested/result.json", content=b"{}", content_type="application/json")
    stored = await storage.get(key="nested/result.json")
    assert stored.content == b"{}"
    assert stored.content_type == "application/json"
    with pytest.raises(ValueError):
        await storage.put(key="../outside", content=b"bad", content_type="text/plain")


@pytest.mark.asyncio
async def test_in_process_event_bus_replays_and_sequences_events() -> None:
    bus = InProcessExecutionEventBus(retention_seconds=60)
    execution_id = uuid4()
    started = ExecutionEvent(
        type=ExecutionEventType.EXECUTION_STARTED,
        execution_id=execution_id,
        emitted_at=datetime.now(UTC),
        execution_status="running",
    )
    completed = ExecutionEvent(
        type=ExecutionEventType.EXECUTION_COMPLETED,
        execution_id=execution_id,
        emitted_at=datetime.now(UTC),
        execution_status="passed",
    )
    await bus.publish(started)
    await bus.publish(completed)
    events = [event async for event in bus.subscribe(execution_id)]
    assert [event.sequence for event in events] == [1, 2]
    assert events[-1].type is ExecutionEventType.EXECUTION_COMPLETED


@pytest.mark.asyncio
async def test_in_process_rate_limiter_enforces_window() -> None:
    limiter = InProcessRateLimiter()
    first = await limiter.check(key="test", limit=1, window_seconds=60)
    second = await limiter.check(key="test", limit=1, window_seconds=60)
    assert first.allowed is True
    assert second.allowed is False
    assert second.remaining == 0


@pytest.mark.asyncio
async def test_standalone_schema_bootstrap_records_revision(tmp_path, monkeypatch) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
    monkeypatch.setattr(standalone_schema, "engine", test_engine)
    await standalone_schema.initialize_standalone_database()
    async with test_engine.connect() as connection:
        value = await connection.scalar(
            standalone_schema.text(
                "SELECT value FROM flowtest_standalone_meta WHERE key = 'schema_baseline'"
            )
        )
    await test_engine.dispose()
    assert value == standalone_schema.BASELINE_REVISION


@pytest.mark.asyncio
async def test_standalone_schema_upgrades_0045_context_tables(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's49-schema.db'}")
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for table in (
            "context_evidence_items",
            "test_context_revisions",
            "test_contexts",
        ):
            await connection.execute(standalone_schema.text(f"DROP TABLE {table}"))
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO flowtest_standalone_meta VALUES ('schema_baseline', '20260823_0045')"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text("INSERT INTO alembic_version VALUES ('20260823_0045')")
        )

    monkeypatch.setattr(standalone_schema, "engine", test_engine)
    await standalone_schema.initialize_standalone_database()
    await standalone_schema.initialize_standalone_database()

    async with test_engine.connect() as connection:
        tables = {
            str(row[0])
            for row in (
                await connection.execute(
                    standalone_schema.text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            ).fetchall()
        }
        context_indexes = {
            str(row[1])
            for row in (
                await connection.execute(standalone_schema.text("PRAGMA index_list(test_contexts)"))
            ).fetchall()
        }
        evidence_indexes = {
            str(row[1])
            for row in (
                await connection.execute(
                    standalone_schema.text("PRAGMA index_list(context_evidence_items)")
                )
            ).fetchall()
        }
        baseline = await connection.scalar(
            standalone_schema.text(
                "SELECT value FROM flowtest_standalone_meta WHERE key = 'schema_baseline'"
            )
        )
        alembic_revision = await connection.scalar(
            standalone_schema.text("SELECT version_num FROM alembic_version")
        )

    await test_engine.dispose()
    assert {
        "test_contexts",
        "test_context_revisions",
        "context_evidence_items",
    }.issubset(tables)
    assert "ix_test_contexts_project_status" in context_indexes
    assert "ix_context_evidence_source" in evidence_indexes
    assert baseline == standalone_schema.BASELINE_REVISION
    assert alembic_revision == standalone_schema.BASELINE_REVISION


@pytest.mark.asyncio
async def test_standalone_schema_upgrades_0046_evidence_provider_constraint(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's52-schema.db'}")
    evidence_id = uuid4().hex
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(standalone_schema.text("DROP TABLE context_evidence_items"))
        current_ddl = str(
            standalone_schema.CreateTable(ContextEvidenceItem.__table__).compile(
                dialect=connection.dialect
            )
        )
        legacy_ddl = current_ddl.replace(
            "'data_profile', 'service_topology', 'existing_test'",
            "'data_profile', 'existing_test'",
        ).replace(
            "'runtime', 'change', 'user_confirmed_rule', 'database'",
            "'runtime', 'database'",
        )
        assert "user_confirmed_rule" not in legacy_ddl
        await connection.execute(standalone_schema.text(legacy_ddl))
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO context_evidence_items ("
                "context_revision_id, source_type, provider_name, provider_version, "
                "source_ref, source_revision, subject_ref, finding_payload, semantic_role, "
                "deterministic, confidence, fingerprint, expires_at, id) VALUES ("
                ":revision_id, 'repository', 'legacy-provider', '1.0.0', "
                "'repository://legacy', 'legacy-revision', 'flowtest://legacy', '{}', "
                "'normative', 1, 1, :fingerprint, '2099-01-01T00:00:00Z', :id)"
            ),
            {
                "revision_id": uuid4().hex,
                "fingerprint": "a" * 64,
                "id": evidence_id,
            },
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO flowtest_standalone_meta VALUES ('schema_baseline', '20260828_0046')"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text("INSERT INTO alembic_version VALUES ('20260828_0046')")
        )

    monkeypatch.setattr(standalone_schema, "engine", test_engine)
    await standalone_schema.initialize_standalone_database()
    await standalone_schema.initialize_standalone_database()

    async with test_engine.begin() as connection:
        table_sql = await connection.scalar(
            standalone_schema.text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'context_evidence_items'"
            )
        )
        baseline = await connection.scalar(
            standalone_schema.text(
                "SELECT value FROM flowtest_standalone_meta WHERE key = 'schema_baseline'"
            )
        )
        alembic_revision = await connection.scalar(
            standalone_schema.text("SELECT version_num FROM alembic_version")
        )
        preserved_source_type = await connection.scalar(
            standalone_schema.text("SELECT source_type FROM context_evidence_items WHERE id = :id"),
            {"id": evidence_id},
        )

    await test_engine.dispose()
    assert "service_topology" in str(table_sql)
    assert "change" in str(table_sql)
    assert "user_confirmed_rule" in str(table_sql)
    assert preserved_source_type == "repository"
    assert baseline == standalone_schema.BASELINE_REVISION
    assert alembic_revision == standalone_schema.BASELINE_REVISION


@pytest.mark.asyncio
async def test_standalone_schema_upgrades_0044_waivers_and_survives_restore(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "standalone-0044.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    waiver_id = uuid4().hex
    regression_run_id = uuid4().hex
    project_id = uuid4().hex
    approver_id = uuid4().hex
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(standalone_schema.text("DROP TABLE semantic_gap_waivers"))
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE semantic_gap_waivers ("
                "regression_run_id CHAR(32) NOT NULL, project_id CHAR(32) NOT NULL, "
                "gap_key VARCHAR(64) NOT NULL, reason TEXT NOT NULL, "
                "approved_by_id CHAR(32) NOT NULL, approved_at DATETIME NOT NULL, "
                "expires_at DATETIME, operation_identity JSON NOT NULL, "
                "semantic_requirement JSON NOT NULL, "
                "requirement_fingerprint VARCHAR(64) NOT NULL, id CHAR(32) PRIMARY KEY, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "CONSTRAINT uq_semantic_gap_waiver_run_gap "
                "UNIQUE (regression_run_id, gap_key), "
                "CONSTRAINT fk_semantic_gap_waiver_run FOREIGN KEY (regression_run_id) "
                "REFERENCES change_regression_runs (id) ON DELETE CASCADE, "
                "CONSTRAINT fk_semantic_gap_waiver_project FOREIGN KEY (project_id) "
                "REFERENCES projects (id) ON DELETE CASCADE, "
                "CONSTRAINT fk_semantic_gap_waiver_approver FOREIGN KEY (approved_by_id) "
                "REFERENCES users (id) ON DELETE RESTRICT)"
            )
        )
        for index_sql in (
            "CREATE INDEX ix_semantic_gap_waivers_approved_at "
            "ON semantic_gap_waivers (approved_at)",
            "CREATE INDEX ix_semantic_gap_waivers_expires_at ON semantic_gap_waivers (expires_at)",
            "CREATE INDEX ix_semantic_gap_waivers_gap_key ON semantic_gap_waivers (gap_key)",
            "CREATE INDEX ix_semantic_gap_waivers_project_id ON semantic_gap_waivers (project_id)",
            "CREATE INDEX ix_semantic_gap_waivers_regression_run_id "
            "ON semantic_gap_waivers (regression_run_id)",
            "CREATE INDEX ix_semantic_gap_waivers_requirement_fingerprint "
            "ON semantic_gap_waivers (requirement_fingerprint)",
        ):
            await connection.execute(standalone_schema.text(index_sql))
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO semantic_gap_waivers ("
                "regression_run_id, project_id, gap_key, reason, approved_by_id, approved_at, "
                "operation_identity, semantic_requirement, requirement_fingerprint, id) "
                "VALUES (:run_id, :project_id, 'missing-status-assertion', 'historical reason', "
                ":approver_id, CURRENT_TIMESTAMP, '{}', '{}', :fingerprint, :waiver_id)"
            ),
            {
                "run_id": regression_run_id,
                "project_id": project_id,
                "approver_id": approver_id,
                "fingerprint": "a" * 64,
                "waiver_id": waiver_id,
            },
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO flowtest_standalone_meta VALUES ('schema_baseline', '20260823_0044')"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text("INSERT INTO alembic_version VALUES ('20260823_0044')")
        )

    monkeypatch.setattr(standalone_schema, "engine", test_engine)
    await standalone_schema.initialize_standalone_database()
    await standalone_schema.initialize_standalone_database()

    superseding_id = uuid4().hex
    async with test_engine.begin() as connection:
        columns = {
            str(row[1])
            for row in (
                await connection.execute(
                    standalone_schema.text("PRAGMA table_info(semantic_gap_waivers)")
                )
            ).fetchall()
        }
        historical = (
            await connection.execute(
                standalone_schema.text(
                    "SELECT reason, revision, supersedes_waiver_id "
                    "FROM semantic_gap_waivers WHERE id = :waiver_id"
                ),
                {"waiver_id": waiver_id},
            )
        ).one()
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO semantic_gap_waivers ("
                "regression_run_id, project_id, gap_key, revision, supersedes_waiver_id, "
                "reason, approved_by_id, approved_at, operation_identity, "
                "semantic_requirement, requirement_fingerprint, id) "
                "VALUES (:run_id, :project_id, 'missing-status-assertion', 2, :previous_id, "
                "'superseding reason', :approver_id, CURRENT_TIMESTAMP, '{}', '{}', "
                ":fingerprint, :waiver_id)"
            ),
            {
                "run_id": regression_run_id,
                "project_id": project_id,
                "previous_id": waiver_id,
                "approver_id": approver_id,
                "fingerprint": "b" * 64,
                "waiver_id": superseding_id,
            },
        )
        baseline = await connection.scalar(
            standalone_schema.text(
                "SELECT value FROM flowtest_standalone_meta WHERE key = 'schema_baseline'"
            )
        )
        alembic_revision = await connection.scalar(
            standalone_schema.text("SELECT version_num FROM alembic_version")
        )
        table_sql = await connection.scalar(
            standalone_schema.text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'semantic_gap_waivers'"
            )
        )
        indexes = {
            str(row[1])
            for row in (
                await connection.execute(
                    standalone_schema.text("PRAGMA index_list(semantic_gap_waivers)")
                )
            ).fetchall()
        }
        foreign_keys = {
            (str(row[2]), str(row[3]), str(row[4]), str(row[6]))
            for row in (
                await connection.execute(
                    standalone_schema.text("PRAGMA foreign_key_list(semantic_gap_waivers)")
                )
            ).fetchall()
        }

    assert {"revision", "supersedes_waiver_id"}.issubset(columns)
    assert historical == ("historical reason", 1, None)
    assert baseline == standalone_schema.BASELINE_REVISION
    assert alembic_revision == standalone_schema.BASELINE_REVISION
    assert "revision >= 1" in str(table_sql)
    assert "ix_semantic_gap_waivers_supersedes_waiver_id" in indexes
    assert (
        "semantic_gap_waivers",
        "supersedes_waiver_id",
        "id",
        "SET NULL",
    ) in foreign_keys

    duplicate_parameters = {
        "run_id": regression_run_id,
        "project_id": project_id,
        "previous_id": waiver_id,
        "approver_id": approver_id,
        "fingerprint": "c" * 64,
        "waiver_id": uuid4().hex,
    }
    insert_sql = standalone_schema.text(
        "INSERT INTO semantic_gap_waivers ("
        "regression_run_id, project_id, gap_key, revision, supersedes_waiver_id, "
        "reason, approved_by_id, approved_at, operation_identity, semantic_requirement, "
        "requirement_fingerprint, id) VALUES (:run_id, :project_id, "
        "'missing-status-assertion', :revision, :previous_id, 'invalid', :approver_id, "
        "CURRENT_TIMESTAMP, '{}', '{}', :fingerprint, :waiver_id)"
    )
    with pytest.raises(IntegrityError):
        async with test_engine.begin() as connection:
            await connection.execute(insert_sql, {**duplicate_parameters, "revision": 2})
    with pytest.raises(IntegrityError):
        async with test_engine.begin() as connection:
            await connection.execute(
                insert_sql,
                {**duplicate_parameters, "revision": 0, "waiver_id": uuid4().hex},
            )

    await test_engine.dispose()
    restored_path = tmp_path / "restored-standalone.db"
    shutil.copy2(database_path, restored_path)
    restored_engine = create_async_engine(f"sqlite+aiosqlite:///{restored_path}")
    async with restored_engine.connect() as connection:
        restored_rows = (
            await connection.execute(
                standalone_schema.text(
                    "SELECT id, revision, supersedes_waiver_id FROM semantic_gap_waivers "
                    "ORDER BY revision"
                )
            )
        ).all()
        restored_revision = await connection.scalar(
            standalone_schema.text("SELECT version_num FROM alembic_version")
        )
    await restored_engine.dispose()

    assert restored_rows == [(waiver_id, 1, None), (superseding_id, 2, waiver_id)]
    assert restored_revision == standalone_schema.BASELINE_REVISION


@pytest.mark.asyncio
async def test_standalone_schema_upgrades_existing_project_policy_column(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy-schema.db'}")
    async with test_engine.begin() as connection:
        await connection.execute(
            standalone_schema.text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)")
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE flowtest_standalone_meta "
                "(key VARCHAR(100) PRIMARY KEY, value VARCHAR(500) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO flowtest_standalone_meta (key, value) "
                "VALUES ('schema_baseline', '20260822_0032')"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text("INSERT INTO alembic_version VALUES ('20260822_0032')")
        )
        await standalone_schema._ensure_incremental_columns(connection)
        columns = await connection.execute(standalone_schema.text("PRAGMA table_info(projects)"))
        version = await connection.scalar(
            standalone_schema.text("SELECT version_num FROM alembic_version")
        )

    await test_engine.dispose()
    assert "outbound_policy_enabled" in {str(row[1]) for row in columns.fetchall()}
    assert version == standalone_schema.BASELINE_REVISION


@pytest.mark.asyncio
async def test_standalone_schema_upgrades_s55_preview_contract(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's55-schema.db'}")
    execution_id = uuid4().hex
    project_id = uuid4().hex
    workflow_id = uuid4().hex
    workflow_version_id = uuid4().hex
    environment_id = uuid4().hex
    actor_id = uuid4().hex
    async with test_engine.begin() as connection:
        await connection.execute(standalone_schema.text("PRAGMA foreign_keys = ON"))
        for table in ("projects", "workflows", "workflow_versions", "environments", "users"):
            await connection.execute(
                standalone_schema.text(f"CREATE TABLE {table} (id CHAR(32) PRIMARY KEY)")
            )
        for table, identifier in (
            ("projects", project_id),
            ("workflows", workflow_id),
            ("workflow_versions", workflow_version_id),
            ("environments", environment_id),
            ("users", actor_id),
        ):
            await connection.execute(
                standalone_schema.text(f"INSERT INTO {table} (id) VALUES (:id)"),
                {"id": identifier},
            )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE workflow_executions ("
                "project_id CHAR(32) NOT NULL, workflow_id CHAR(32) NOT NULL, "
                "workflow_version_id CHAR(32) NOT NULL, environment_id CHAR(32) NOT NULL, "
                "triggered_by_id CHAR(32) NOT NULL, parent_execution_id CHAR(32), "
                "dataset_row_index INTEGER, status VARCHAR(16) NOT NULL, snapshot JSON NOT NULL, "
                "context JSON NOT NULL, error_code VARCHAR(100), error_message TEXT, "
                "cancel_requested_at DATETIME, started_at DATETIME NOT NULL, "
                "completed_at DATETIME, run_payload_ciphertext BLOB, run_payload_nonce BLOB, "
                "id CHAR(32) PRIMARY KEY, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        now = datetime.now(UTC).isoformat()
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO workflow_executions ("
                "project_id, workflow_id, workflow_version_id, environment_id, triggered_by_id, "
                "status, snapshot, context, started_at, id, created_at, updated_at) VALUES ("
                ":project, :workflow, :version, :environment, :actor, 'passed', '{}', '{}', "
                ":now, :id, :now, :now)"
            ),
            {
                "project": project_id,
                "workflow": workflow_id,
                "version": workflow_version_id,
                "environment": environment_id,
                "actor": actor_id,
                "now": now,
                "id": execution_id,
            },
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE workflow_node_executions (id CHAR(32) PRIMARY KEY)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE execution_checkpoints (id CHAR(32) PRIMARY KEY, "
                "attempt INTEGER CHECK (attempt >= 1), "
                "status VARCHAR(16) CHECK (status IN ('passed', 'failed', 'skipped', 'cancelled')))"
            )
        )
        await connection.run_sync(Base.metadata.create_all)

        await standalone_schema._ensure_s55_schema(connection)
        await standalone_schema._ensure_s55_schema(connection)
        environment_columns = (
            await connection.execute(standalone_schema.text("PRAGMA table_info(environments)"))
        ).fetchall()
        execution_columns = (
            await connection.execute(
                standalone_schema.text("PRAGMA table_info(workflow_executions)")
            )
        ).fetchall()
        checkpoint_sql = await connection.scalar(
            standalone_schema.text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'execution_checkpoints'"
            )
        )
        approval_table = await connection.scalar(
            standalone_schema.text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'sandbox_preview_approvals'"
            )
        )
        approval_columns = (
            await connection.execute(
                standalone_schema.text("PRAGMA table_info(sandbox_preview_approvals)")
            )
        ).fetchall()
        approval_foreign_keys = (
            await connection.execute(
                standalone_schema.text("PRAGMA foreign_key_list(sandbox_preview_approvals)")
            )
        ).fetchall()
        foreign_key_violations = (
            await connection.execute(standalone_schema.text("PRAGMA foreign_key_check"))
        ).fetchall()
        preserved = (
            await connection.execute(
                standalone_schema.text(
                    "SELECT run_purpose, main_status FROM workflow_executions WHERE id = :id"
                ),
                {"id": execution_id},
            )
        ).one()

    await test_engine.dispose()
    environment_names = {str(row[1]) for row in environment_columns}
    execution_contract = {str(row[1]): bool(row[3]) for row in execution_columns}
    assert "classification" in environment_names
    assert {
        "run_purpose",
        "source_change_set_id",
        "preview_approval_id",
        "preview_budget",
        "preview_evidence",
        "cleanup_report",
    }.issubset(execution_contract)
    assert execution_contract["workflow_id"] is False
    assert execution_contract["workflow_version_id"] is False
    assert approval_table == "sandbox_preview_approvals"
    assert "target_snapshot_fingerprint" in {str(row[1]) for row in approval_columns}
    approval_targets = {str(row[2]) for row in approval_foreign_keys}
    assert "workflow_executions" in approval_targets
    assert "workflow_executions_0047_legacy" not in approval_targets
    assert foreign_key_violations == []
    assert "'running'" in str(checkpoint_sql)
    assert "attempt >= 0" in str(checkpoint_sql)
    assert preserved == ("standard", "passed")


@pytest.mark.asyncio
async def test_standalone_schema_upgrades_s47_test_design_columns(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's47-schema.db'}")
    async with test_engine.begin() as connection:
        await connection.execute(
            standalone_schema.text("CREATE TABLE test_designs (id VARCHAR(36) PRIMARY KEY)")
        )
        await standalone_schema._ensure_s47_test_design_columns(connection)
        columns = await connection.execute(
            standalone_schema.text("PRAGMA table_info(test_designs)")
        )

    await test_engine.dispose()
    definitions = {str(row[1]): (str(row[2]), int(row[3]), row[4]) for row in columns.fetchall()}
    assert set(definitions) >= {
        "scenarios",
        "evidence_refs",
        "warnings",
        "confidence",
        "review_requirements",
    }
    assert definitions["scenarios"] == ("JSON", 1, "'[]'")
    assert definitions["confidence"] == ("FLOAT", 1, "1")


@pytest.mark.asyncio
async def test_standalone_api_version_service_identity_is_backfilled_once(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's51-schema.db'}")
    async with test_engine.begin() as connection:
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE api_definitions (id VARCHAR(36) PRIMARY KEY, service_id CHAR(32))"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE api_versions ("
                "id VARCHAR(36) PRIMARY KEY, api_definition_id VARCHAR(36) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text("INSERT INTO api_definitions VALUES ('api-1', 'service-old')")
        )
        await connection.execute(
            standalone_schema.text("INSERT INTO api_versions VALUES ('version-1', 'api-1')")
        )
        await standalone_schema._ensure_api_version_service_identity(connection)
        first = await connection.scalar(
            standalone_schema.text("SELECT service_id FROM api_versions WHERE id = 'version-1'")
        )
        await connection.execute(
            standalone_schema.text(
                "UPDATE api_definitions SET service_id = 'service-new' WHERE id = 'api-1'"
            )
        )
        await standalone_schema._ensure_api_version_service_identity(connection)
        second = await connection.scalar(
            standalone_schema.text("SELECT service_id FROM api_versions WHERE id = 'version-1'")
        )

    await test_engine.dispose()
    assert first == "service-old"
    assert second == "service-old"


@pytest.mark.asyncio
async def test_standalone_schema_backfills_safe_partial_api_contract(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's471-schema.db'}")
    async with test_engine.begin() as connection:
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE api_versions ("
                "id VARCHAR(36) PRIMARY KEY, version INTEGER NOT NULL, "
                "method VARCHAR(16) NOT NULL, path VARCHAR(2048) NOT NULL, "
                "query_parameters JSON NOT NULL, headers JSON NOT NULL, "
                "body JSON, auth_kind VARCHAR(32) NOT NULL, auth_config JSON NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO api_versions VALUES ("
                "'version-1', 1, 'POST', '/orders/{order_id}', :query, :headers, :body, "
                "'bearer', '{}')"
            ),
            {
                "query": json.dumps(
                    [{"name": "trace", "required": True, "value": "must-not-survive"}]
                ),
                "headers": json.dumps({"X-Trace": "must-not-survive"}),
                "body": json.dumps({"quantity": 99}),
            },
        )
        for column, definition in (
            ("canonical_contract", "JSON NOT NULL DEFAULT '{}'"),
            ("contract_fingerprint", "VARCHAR(64)"),
            ("contract_completeness", "VARCHAR(32) NOT NULL DEFAULT 'legacy_partial'"),
        ):
            await standalone_schema._add_column_if_missing(
                connection,
                table="api_versions",
                column=column,
                definition=definition,
            )
        await standalone_schema._ensure_s471_api_version_contracts(connection)
        # Re-running an incremental upgrade must preserve the frozen snapshot.
        await standalone_schema._ensure_s471_api_version_contracts(connection)
        row = (
            await connection.execute(
                standalone_schema.text(
                    "SELECT canonical_contract, contract_fingerprint, contract_completeness "
                    "FROM api_versions WHERE id = 'version-1'"
                )
            )
        ).one()

    await test_engine.dispose()
    contract = json.loads(str(row[0]))
    parameter_identity = {
        (parameter["name"], parameter["location"], parameter["required"])
        for parameter in contract["parameters"]
    }
    assert parameter_identity == {
        ("order_id", "path", True),
        ("trace", "query", True),
        ("X-Trace", "header", False),
    }
    assert contract["completeness"] == "legacy_partial"
    assert contract["responses"] == {}
    assert "must-not-survive" not in str(row[0])
    assert len(str(row[1])) == 64
    assert row[2] == "legacy_partial"


@pytest.mark.asyncio
async def test_standalone_s472_sanitizes_existing_contract_data_irreversibly(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's472-security.db'}")
    raw_contract = {
        "operation": "orders.create",
        "method": "POST",
        "path": "/orders",
        "request_body": {
            "schema": {
                "type": "object",
                "properties": {
                    "password": {"type": "string", "example": "database-password"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "NORMAL",
                            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123",
                        ],
                    },
                },
            }
        },
        "responses": {
            "200": {
                "description": "ok",
                "schema": {"type": "string", "default": "database-token"},
            }
        },
        "completeness": "complete",
    }
    async with test_engine.begin() as connection:
        await connection.execute(
            standalone_schema.text(
                "CREATE TABLE api_versions ("
                "id VARCHAR(36) PRIMARY KEY, canonical_contract JSON NOT NULL, "
                "contract_fingerprint VARCHAR(64), contract_completeness VARCHAR(32) NOT NULL)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                "INSERT INTO api_versions VALUES "
                "('version-1', :contract, 'old-fingerprint', 'complete')"
            ),
            {"contract": json.dumps(raw_contract)},
        )
        await standalone_schema._sanitize_s472_api_version_contracts(connection)
        first = (
            await connection.execute(
                standalone_schema.text(
                    "SELECT canonical_contract, contract_fingerprint, contract_completeness "
                    "FROM api_versions WHERE id = 'version-1'"
                )
            )
        ).one()
        await standalone_schema._sanitize_s472_api_version_contracts(connection)
        second = (
            await connection.execute(
                standalone_schema.text(
                    "SELECT canonical_contract, contract_fingerprint, contract_completeness "
                    "FROM api_versions WHERE id = 'version-1'"
                )
            )
        ).one()

    await test_engine.dispose()
    persisted = str(first[0])
    assert "database-password" not in persisted
    assert "database-token" not in persisted
    assert "eyJhbGci" not in persisted
    assert first[2] == "redacted_partial"
    assert len(str(first[1])) == 64
    assert first == second


def test_standalone_partial_contract_schema_inference_is_bounded() -> None:
    assert standalone_schema._standalone_inferred_schema(True) == {"type": "boolean"}
    assert standalone_schema._standalone_inferred_schema(1.5) == {"type": "number"}
    assert standalone_schema._standalone_inferred_schema([]) == {
        "type": "array",
        "items": {},
    }
    assert standalone_schema._standalone_inferred_schema([1]) == {
        "type": "array",
        "items": {"type": "integer"},
    }
    assert standalone_schema._standalone_inferred_schema(None) == {}
    assert standalone_schema._standalone_inferred_schema("opaque") == {"type": "string"}
    assert standalone_schema._json_value({"safe": True}) == {"safe": True}
    assert standalone_schema._json_value("not-json") is None


@pytest.mark.asyncio
async def test_standalone_schema_rebuilds_legacy_change_set_tables(tmp_path) -> None:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy-change-sets.db'}")
    async with test_engine.begin() as connection:
        await connection.execute(
            standalone_schema.text(
                """
                CREATE TABLE ai_change_sets (
                  project_id CHAR(32) NOT NULL,
                  impact_run_id CHAR(32) NOT NULL,
                  release_risk_id CHAR(32) NOT NULL,
                  ai_job_id CHAR(32) NOT NULL,
                  title VARCHAR(200) NOT NULL,
                  status VARCHAR(24) NOT NULL DEFAULT 'generating',
                  source_snapshot JSON NOT NULL,
                  source_fingerprint VARCHAR(64) NOT NULL,
                  created_by_id CHAR(32) NOT NULL,
                  id CHAR(32) NOT NULL PRIMARY KEY,
                  created_at DATETIME NOT NULL,
                  updated_at DATETIME NOT NULL,
                  CONSTRAINT uq_ai_change_sets_job UNIQUE (ai_job_id)
                )
                """
            )
        )
        await connection.execute(
            standalone_schema.text(
                """
                CREATE TABLE ai_change_items (
                  change_set_id CHAR(32) NOT NULL,
                  suggestion_id CHAR(32) NOT NULL,
                  position INTEGER NOT NULL,
                  item_type VARCHAR(32) NOT NULL,
                  action VARCHAR(16) NOT NULL,
                  title VARCHAR(200) NOT NULL,
                  target_resource_id CHAR(32),
                  target_snapshot_sha256 VARCHAR(64),
                  proposed_content JSON NOT NULL,
                  review_status VARCHAR(16) NOT NULL DEFAULT 'pending',
                  review_note TEXT NOT NULL DEFAULT '',
                  reviewed_by_id CHAR(32),
                  reviewed_at DATETIME,
                  materialized_resource_type VARCHAR(32),
                  materialized_resource_id CHAR(32),
                  id CHAR(32) NOT NULL PRIMARY KEY,
                  created_at DATETIME NOT NULL,
                  updated_at DATETIME NOT NULL,
                  CONSTRAINT uq_ai_change_items_set_position UNIQUE (change_set_id, position),
                  CONSTRAINT uq_ai_change_items_suggestion_id UNIQUE (suggestion_id)
                )
                """
            )
        )
        await connection.execute(
            standalone_schema.text(
                "CREATE INDEX ix_ai_change_sets_project_id ON ai_change_sets(project_id)"
            )
        )
        await connection.execute(
            standalone_schema.text(
                """
                INSERT INTO ai_change_sets VALUES
                ('p', 'i', 'r', 'j', 'old', 'draft', '{}', 'fingerprint', 'u', 'c',
                 '2026-01-01', '2026-01-01')
                """
            )
        )
        await standalone_schema._ensure_flow_spec_change_set_columns(connection)
        set_columns = await connection.execute(
            standalone_schema.text("PRAGMA table_info(ai_change_sets)")
        )
        item_columns = await connection.execute(
            standalone_schema.text("PRAGMA table_info(ai_change_items)")
        )
        stored = await connection.execute(
            standalone_schema.text(
                "SELECT source_type, actor_type, impact_run_id FROM ai_change_sets"
            )
        )

    await test_engine.dispose()
    set_info = {str(row[1]): bool(row[3]) for row in set_columns.fetchall()}
    item_info = {str(row[1]): bool(row[3]) for row in item_columns.fetchall()}
    assert set_info["impact_run_id"] is False
    assert set_info["source_type"] is True
    assert item_info["suggestion_id"] is False
    assert stored.fetchone() == ("ai", "user", "i")


@pytest.mark.asyncio
async def test_standalone_dispatcher_runs_and_stops_in_process_tasks(monkeypatch) -> None:
    dispatcher = StandaloneTaskDispatcher(
        lambda: _SessionContext(),
        InProcessExecutionEventBus(retention_seconds=60),
        LocalObjectStorage(),
    )
    called: list[str] = []

    async def operation() -> None:
        called.append("ok")

    dispatcher._spawn("unit", operation)
    await asyncio.gather(*tuple(dispatcher._tasks))
    await asyncio.sleep(0)
    assert called == ["ok"]
    assert (await dispatcher.metrics_reader.read()).task_counts == {"succeeded": 1}

    async def failure() -> None:
        raise RuntimeError("expected")

    dispatcher._spawn("failure", failure)
    with pytest.raises(RuntimeError):
        await asyncio.gather(*tuple(dispatcher._tasks))
    await asyncio.sleep(0)
    assert (await dispatcher.metrics_reader.read()).task_counts["failed"] == 1

    with pytest.raises(Exception, match="性能任务"):
        dispatcher.start_performance_run(uuid4())
    with pytest.raises(Exception, match="环境任务"):
        dispatcher.start_environment_provision(uuid4())
    with pytest.raises(Exception, match="环境任务"):
        dispatcher.start_environment_cleanup(uuid4())
    await dispatcher.shutdown()
    with pytest.raises(Exception, match="后台任务运行时已关闭"):
        dispatcher.start_test_plan(uuid4(), queue_name="general", priority=5)


@pytest.mark.asyncio
async def test_standalone_dispatcher_executes_workflow_plan_and_ai(monkeypatch) -> None:
    dispatcher = StandaloneTaskDispatcher(
        lambda: _SessionContext(),
        InProcessExecutionEventBus(retention_seconds=60),
        LocalObjectStorage(),
    )
    workflow_called: list[object] = []
    notification_called: list[object] = []

    async def run_now(plan) -> None:
        workflow_called.append(plan)

    async def workflow_notification(execution_id) -> None:
        notification_called.append(execution_id)

    monkeypatch.setattr(dispatcher._workflow, "run_now", run_now)
    monkeypatch.setattr(dispatcher, "_deliver_workflow_notification", workflow_notification)
    plan = SimpleNamespace(execution_id="execution")
    await dispatcher._run_workflow(plan)
    assert workflow_called == [plan]
    assert notification_called == ["execution"]

    test_plan_called: list[object] = []

    class FakeTestPlanCoordinator:
        def __init__(self, *_args) -> None:
            pass

        async def run(self, run_id) -> None:
            test_plan_called.append(run_id)

    monkeypatch.setattr(standalone_tasks, "TestPlanRunCoordinator", FakeTestPlanCoordinator)
    monkeypatch.setattr(dispatcher, "_deliver_test_plan_notification", workflow_notification)
    await dispatcher._run_test_plan("run")
    assert test_plan_called == ["run"]

    ai_called: list[object] = []

    class FakeAIJobRunner:
        def __init__(self, *_args) -> None:
            pass

        async def run(self, job_id) -> None:
            ai_called.append(job_id)

    monkeypatch.setattr(standalone_tasks, "AIJobRunner", FakeAIJobRunner)
    monkeypatch.setattr(standalone_tasks, "OpenAICompatibleProvider", lambda _config: object())
    await dispatcher._run_ai_job("job")
    assert ai_called == ["job"]
    await dispatcher.shutdown()


@pytest.mark.asyncio
async def test_standalone_scheduler_enqueues_and_cleans_up(monkeypatch) -> None:
    dispatcher = StandaloneTaskDispatcher(
        lambda: _SessionContext(),
        InProcessExecutionEventBus(retention_seconds=60),
        LocalObjectStorage(),
    )
    run = SimpleNamespace(id="run", queue_name="general", queue_priority=5)
    queued: list[tuple[object, str, int]] = []
    cleaned: list[object] = []

    class FakeTaskPlanService:
        def __init__(self, _session) -> None:
            pass

        async def queue_due_runs(self, _now):
            return [run]

    class FakeRetentionService:
        def __init__(self, _session, _storage) -> None:
            pass

        async def cleanup(self):
            cleaned.append("done")
            return "summary"

    def record_run(run_id, *, queue_name, priority) -> None:
        queued.append((run_id, queue_name, priority))

    monkeypatch.setattr(standalone_tasks, "TestPlanService", FakeTaskPlanService)
    monkeypatch.setattr(standalone_tasks, "RetentionCleanupService", FakeRetentionService)
    monkeypatch.setattr(dispatcher, "start_test_plan", record_run)
    await dispatcher._enqueue_due_test_plans()
    await dispatcher._cleanup_retention()
    assert queued == [("run", "general", 5)]
    assert cleaned == ["done"]
    dispatcher.start_scheduler()
    await dispatcher.shutdown()
