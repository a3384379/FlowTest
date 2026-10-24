"""Real PostgreSQL FK admission and routing-mutation exclusion with explicit lock barriers."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.dml import Update

from app.core.config import settings
from app.models.access import Project, User
from app.models.api_assets import Environment
from app.models.organizations import Organization
from app.models.service_targets import Service, ServiceEndpoint
from app.models.workflows import Workflow, WorkflowExecution, WorkflowVersion
from app.services.organization_governance import OrganizationQuotaService
from app.services.self_test_assets import SelfTestAssets

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FLOWTEST_RUN_INTEGRATION") != "1",
        reason="Requires explicit PostgreSQL integration",
    ),
]


@dataclass(frozen=True)
class RoutingFixture:
    actor: UUID
    organization: UUID
    project: UUID
    service: UUID
    environment: UUID
    endpoint: UUID
    workflow: UUID
    version: UUID
    url: str = "https://mapping-lock.test.invalid"


async def seed(sessions: async_sessionmaker[AsyncSession]) -> RoutingFixture:
    marker = uuid4().hex
    async with sessions() as session:
        actor = User(
            email=f"mapping-lock-{marker}@example.invalid",
            display_name=marker,
            password_hash="unused-integration-lock-account",
        )
        session.add(actor)
        await session.flush()
        organization = Organization(name=marker, slug=marker, created_by_id=actor.id)
        session.add(organization)
        await session.flush()
        project = Project(name=marker, organization_id=organization.id, created_by_id=actor.id)
        session.add(project)
        await session.flush()
        service = Service(
            project_id=project.id, service_key=marker, name=marker, created_by_id=actor.id
        )
        session.add(service)
        await session.flush()
        environment = Environment(
            project_id=project.id,
            name=marker,
            base_url=RoutingFixture.url,
            classification="test",
            default_service_id=service.id,
            created_by_id=actor.id,
        )
        workflow = Workflow(
            project_id=project.id, name=marker, draft_definition={}, created_by_id=actor.id
        )
        session.add_all([environment, workflow])
        await session.flush()
        endpoint = ServiceEndpoint(
            project_id=project.id,
            environment_id=environment.id,
            service_id=service.id,
            base_url=RoutingFixture.url,
            created_by_id=actor.id,
        )
        version = WorkflowVersion(
            workflow_id=workflow.id,
            version=1,
            definition={},
            fingerprint="0" * 64,
            created_by_id=actor.id,
            published_at=datetime.now(UTC),
        )
        session.add_all([endpoint, version])
        await session.commit()
        return RoutingFixture(
            actor.id,
            organization.id,
            project.id,
            service.id,
            environment.id,
            endpoint.id,
            workflow.id,
            version.id,
        )


async def cleanup(sessions: async_sessionmaker[AsyncSession], value: RoutingFixture) -> None:
    statements = (
        delete(WorkflowExecution).where(WorkflowExecution.project_id == value.project),
        delete(ServiceEndpoint).where(ServiceEndpoint.project_id == value.project),
        delete(WorkflowVersion).where(WorkflowVersion.id == value.version),
        delete(Workflow).where(Workflow.id == value.workflow),
        delete(Environment).where(Environment.id == value.environment),
        delete(Service).where(Service.id == value.service),
        delete(Project).where(Project.id == value.project),
        delete(Organization).where(Organization.id == value.organization),
        delete(User).where(User.id == value.actor),
    )
    async with sessions() as session:
        for statement in statements:
            await session.execute(statement)
        await session.commit()


async def insert_execution(session: AsyncSession, value: RoutingFixture) -> None:
    try:
        session.add(
            WorkflowExecution(
                project_id=value.project,
                workflow_id=value.workflow,
                workflow_version_id=value.version,
                environment_id=value.environment,
                triggered_by_id=value.actor,
                status="running",
                snapshot={},
                started_at=datetime.now(UTC),
            )
        )
        await session.commit()
    finally:
        await session.rollback()


async def finish_guard(session: AsyncSession, value: RoutingFixture) -> None:
    try:
        await SelfTestAssets(session)._environment(
            value.project, value.environment, value.service, value.url
        )
        await OrganizationQuotaService(session)._lock_organization(value.organization)
        await session.commit()
    finally:
        await session.rollback()


async def finish_native_guard(session: AsyncSession, value: RoutingFixture) -> None:
    try:
        await SelfTestAssets(session)._environment(
            value.project, value.environment, value.service, value.url
        )
        await session.scalar(
            select(Project.id).where(Project.id == value.project).with_for_update()
        )
        await session.commit()
    finally:
        await session.rollback()


@pytest.mark.asyncio
async def test_mapping_guard_does_not_upgrade_project_lock_after_locking_environment() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    value = await seed(sessions)
    tasks: list[asyncio.Task[None]] = []
    try:
        async with sessions() as guard, sessions() as runner, sessions() as observer:
            guard_pid = await guard.scalar(text("SELECT pg_backend_pid()"))
            await runner.scalar(
                select(Project.id)
                .where(Project.id == value.project)
                .with_for_update(read=True, key_share=True)
            )
            tasks.append(asyncio.create_task(finish_native_guard(guard, value)))
            async with asyncio.timeout(5):
                while not await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": guard_pid}
                ):
                    await asyncio.sleep(0.01)
            tasks.append(asyncio.create_task(insert_execution(runner, value)))
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 8)
            assert results == [None, None], results
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await cleanup(sessions, value)
        await engine.dispose()


@pytest.mark.asyncio
async def test_mapping_guard_allows_native_fk_insert_while_waiting_for_quota_lock() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    value = await seed(sessions)
    tasks: list[asyncio.Task[None]] = []
    try:
        async with sessions() as guard, sessions() as runner, sessions() as observer:
            guard_pid = await guard.scalar(text("SELECT pg_backend_pid()"))
            await runner.scalar(
                select(Project).where(Project.id == value.project).with_for_update()
            )
            await OrganizationQuotaService(runner)._lock_organization(value.organization)
            guard_task = asyncio.create_task(finish_guard(guard, value))
            tasks.append(guard_task)
            async with asyncio.timeout(5):
                while not await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": guard_pid}
                ):
                    await asyncio.sleep(0.01)
            tasks.append(asyncio.create_task(insert_execution(runner, value)))
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 8)
            assert results == [None, None], results
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await cleanup(sessions, value)
        await engine.dispose()


async def mutate_route(session: AsyncSession, statement: Update) -> None:
    try:
        await session.execute(statement)
        await session.commit()
    finally:
        await session.rollback()


async def insert_endpoint(session: AsyncSession, value: RoutingFixture) -> None:
    try:
        session.add(
            ServiceEndpoint(
                project_id=value.project,
                environment_id=value.environment,
                service_id=value.service,
                variant="extra",
                base_url=value.url + "/changed",
                created_by_id=value.actor,
            )
        )
        await session.commit()
    finally:
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["environment", "endpoint", "new_endpoint"])
async def test_mapping_guard_still_blocks_routing_changes_until_release(target: str) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    value = await seed(sessions)
    task: asyncio.Task[None] | None = None
    try:
        async with sessions() as guard, sessions() as writer, sessions() as observer:
            await SelfTestAssets(guard)._environment(
                value.project, value.environment, value.service, value.url
            )
            backend_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            if target == "new_endpoint":
                task = asyncio.create_task(insert_endpoint(writer, value))
            else:
                model = Environment if target == "environment" else ServiceEndpoint
                identifier = value.environment if target == "environment" else value.endpoint
                task = asyncio.create_task(
                    mutate_route(
                        writer,
                        update(model)
                        .where(model.id == identifier)
                        .values(base_url=value.url + "/changed"),
                    )
                )
            async with asyncio.timeout(5):
                while not await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": backend_pid}
                ):
                    await asyncio.sleep(0.01)
            assert not task.done()
            await guard.rollback()
            await asyncio.wait_for(task, 5)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await cleanup(sessions, value)
        await engine.dispose()
