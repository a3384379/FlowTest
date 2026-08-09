import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import settings
from app.core.database import close_database, session_factory
from app.core.storage import ensure_storage_bucket
from app.services.execution_events import RedisExecutionEventBus
from app.services.notifications import NotificationDeliveryService
from app.services.tasking import TestPlanService
from app.services.test_plan_runner import TestPlanRunCoordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator
from app.services.workflows import WorkflowService
from app.tasking.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="flowtest.run_workflow")  # type: ignore[untyped-decorator]
def run_workflow(execution_id: str) -> None:
    _run_async(lambda: _run_workflow(UUID(execution_id)))


async def _run_workflow(execution_id: UUID) -> None:
    await ensure_storage_bucket()
    async with session_factory() as session:
        plan = await WorkflowService(session).load_execution_plan(execution_id)
    client = _redis_client()
    try:
        events = RedisExecutionEventBus(
            client, retention_seconds=settings.workflow_event_retention_seconds
        )
        await WorkflowRunCoordinator(session_factory, events).run_now(plan)
        await _deliver_workflow_notification(execution_id)
    finally:
        await client.aclose()


@celery_app.task(name="flowtest.run_test_plan")  # type: ignore[untyped-decorator]
def run_test_plan(run_id: str) -> None:
    _run_async(lambda: _run_test_plan(UUID(run_id)))


async def _run_test_plan(run_id: UUID) -> None:
    await ensure_storage_bucket()
    client = _redis_client()
    try:
        events = RedisExecutionEventBus(
            client, retention_seconds=settings.workflow_event_retention_seconds
        )
        await TestPlanRunCoordinator(session_factory, events).run(run_id)
        await _deliver_test_plan_notification(run_id)
    finally:
        await client.aclose()


@celery_app.task(name="flowtest.enqueue_due_test_plans")  # type: ignore[untyped-decorator]
def enqueue_due_test_plans() -> None:
    _run_async(_enqueue_due_test_plans)


async def _enqueue_due_test_plans() -> None:
    async with session_factory() as session:
        runs = await TestPlanService(session).queue_due_runs(datetime.now(UTC))
    for run in runs:
        celery_app.send_task("flowtest.run_test_plan", args=[str(run.id)])


def _run_async(operation: Callable[[], Coroutine[Any, Any, None]]) -> None:
    with asyncio.Runner() as runner:
        try:
            runner.run(operation())
        finally:
            runner.run(close_database())


def _redis_client() -> Redis:
    return cast(
        Redis,
        Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True),
    )


async def _deliver_workflow_notification(execution_id: UUID) -> None:
    try:
        async with session_factory() as session:
            await NotificationDeliveryService(session).deliver_workflow(execution_id)
    except Exception:
        logger.exception(
            "Workflow notification delivery failed",
            extra={"execution_id": str(execution_id)},
        )


async def _deliver_test_plan_notification(run_id: UUID) -> None:
    try:
        async with session_factory() as session:
            await NotificationDeliveryService(session).deliver_test_plan(run_id)
    except Exception:
        logger.exception(
            "Test plan notification delivery failed",
            extra={"test_plan_run_id": str(run_id)},
        )
