from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.core import standalone_schema
from app.models import Base
from app.models.access import Project, User
from app.models.ai import AIChangeItem, AIChangeSet, AIJob, AISuggestion
from app.models.test_design import ChangeSetApproval

Rows = tuple[tuple[object, ...], ...]


@dataclass(frozen=True)
class LegacyEvidence:
    change_sets: Rows
    items: Rows
    approvals: Rows


@pytest.mark.asyncio
async def test_standalone_startup_adds_review_baselines_without_rebuilding_s62_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'existing-s62.db'}")
    monkeypatch.setattr(standalone_schema, "engine", engine)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        ai_id, mcp_id = await _seed_reviewed_changes(engine)
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE ai_change_sets DROP COLUMN review_baselines")
            )
            columns = await connection.run_sync(
                lambda sync: inspect(sync).get_columns("ai_change_sets")
            )
            assert {column["name"] for column in columns} == {
                column.name
                for column in AIChangeSet.__table__.columns
                if column.name != "review_baselines"
            }
            assert not await standalone_schema._flow_spec_tables_need_rebuild(connection)
            original = await _evidence(connection)

        await standalone_schema.initialize_standalone_database()
        async with engine.connect() as connection:
            assert await _evidence(connection) == original
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            records = (await session.scalars(select(AIChangeSet))).all()
            assert {record.id for record in records} == {ai_id, mcp_id}
            assert all(record.review_baselines == [] for record in records)
            frozen = [
                {
                    "target_type": "workflow",
                    "target_id": str(uuid4()),
                    "snapshot_sha256": "e" * 64,
                    "content": {
                        "name": "新冻结的人工草稿",
                        "description": "已授权值 alice@example.com [REDACTED]",
                        "definition": {"variables": {"literal": "[REDACTED]"}},
                    },
                    "current_version": 1,
                    "draft_revision": 2,
                    "updated_at": "2026-10-22T00:00:00+00:00",
                    "redaction_mode": "off",
                    "redaction_policy_version": 1,
                }
            ]
            ai_record = next(record for record in records if record.id == ai_id)
            ai_record.review_baselines = frozen
            await session.commit()

        async with engine.connect() as connection:
            saved = await _evidence(connection)
        for _ in range(2):
            await standalone_schema.initialize_standalone_database()
            async with engine.connect() as connection:
                assert await _evidence(connection) == saved
                assert (await connection.execute(text("PRAGMA foreign_key_check"))).all() == []
            async with sessions() as session:
                ai_record = await session.get(AIChangeSet, ai_id)
                mcp_record = await session.get(AIChangeSet, mcp_id)
                assert ai_record is not None and ai_record.review_baselines == frozen
                assert mcp_record is not None and mcp_record.review_baselines == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_standalone_fresh_start_can_read_change_sets_and_keeps_baseline_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh-review.db'}")
    monkeypatch.setattr(standalone_schema, "engine", engine)
    try:
        await standalone_schema.initialize_standalone_database()
        await standalone_schema.initialize_standalone_database()
        await _seed_reviewed_changes(engine)
        async with async_sessionmaker(engine)() as session:
            records = (await session.scalars(select(AIChangeSet))).all()
            assert len(records) == 2
            assert all(record.review_baselines == [] for record in records)
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: inspect(sync).get_columns("ai_change_sets")
            )
            column = next(column for column in columns if column["name"] == "review_baselines")
            assert column["nullable"] is False and column["default"] == "'[]'"
    finally:
        await engine.dispose()


async def _seed_reviewed_changes(engine: AsyncEngine) -> tuple[UUID, UUID]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        actor = User(
            email="legacy-review@example.com", display_name="旧审核人", password_hash="unused"
        )
        session.add(actor)
        await session.flush()
        project = Project(name="旧审核项目", created_by_id=actor.id)
        session.add(project)
        await session.flush()
        job = AIJob(
            project_id=project.id,
            job_type="change_set",
            status="completed",
            sanitized_input={"metadata": {"source": "legacy"}},
            input_sha256="a" * 64,
            prompt_template_version="legacy-review-v1",
            model_name="legacy-model",
            created_by_id=actor.id,
        )
        session.add(job)
        await session.flush()
        suggestion = AISuggestion(
            job_id=job.id,
            position=0,
            suggestion_type="workflow",
            title="旧 AI 建议",
            content={"name": "旧草稿"},
        )
        session.add(suggestion)
        ai = AIChangeSet(
            project_id=project.id,
            ai_job_id=job.id,
            title="旧 AI 变更集",
            status="accepted",
            source_snapshot={"metadata": {"source": "ai-legacy"}},
            source_fingerprint="b" * 64,
            source_type="ai",
            actor_type="user",
            actor_id=actor.id,
            created_by_id=actor.id,
        )
        reviewed_at = datetime(2026, 10, 20, tzinfo=UTC)
        mcp = AIChangeSet(
            project_id=project.id,
            title="旧 MCP 变更集",
            status="accepted",
            source_snapshot={"governance": {"manual_approval_required": True}},
            source_fingerprint="c" * 64,
            source_type="mcp",
            source_ref="mcp://legacy/reviewed",
            actor_type="service_account",
            actor_id=actor.id,
            applied_at=reviewed_at,
            created_by_id=actor.id,
        )
        session.add_all([ai, mcp])
        await session.flush()
        session.add(
            ChangeSetApproval(
                change_set_id=mcp.id,
                decision="approved",
                note="保留旧审批",
                approved_by_id=actor.id,
                approved_at=reviewed_at,
            )
        )
        for change_set, item_type, resource_type, suggestion_id in (
            (ai, "workflow", "workflow", suggestion.id),
            (mcp, "test_plan_update", "test_plan", None),
        ):
            target_id = uuid4() if item_type == "test_plan_update" else None
            session.add(
                AIChangeItem(
                    change_set_id=change_set.id,
                    suggestion_id=suggestion_id,
                    position=0,
                    item_type=item_type,
                    action="update" if target_id else "create",
                    title="旧审核项",
                    target_resource_id=target_id,
                    target_snapshot_sha256="d" * 64 if target_id else None,
                    proposed_content={"source": "旧授权内容 alice@example.com"},
                    review_status="accepted",
                    review_note="保留旧审核备注",
                    reviewed_by_id=actor.id,
                    reviewed_at=reviewed_at,
                    materialized_resource_type=resource_type,
                    materialized_resource_id=target_id or uuid4(),
                )
            )
        await session.commit()
        return ai.id, mcp.id


async def _evidence(connection: AsyncConnection) -> LegacyEvidence:
    return LegacyEvidence(
        change_sets=await _rows(connection, AIChangeSet.__table__),
        items=await _rows(connection, AIChangeItem.__table__),
        approvals=await _rows(connection, ChangeSetApproval.__table__),
    )


async def _rows(connection: AsyncConnection, table: Table) -> Rows:
    columns = tuple(column for column in table.columns if column.name != "review_baselines")
    result = await connection.execute(select(*columns).order_by(table.c.id))
    return tuple(tuple(row) for row in result)
