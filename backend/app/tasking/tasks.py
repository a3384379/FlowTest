import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import settings
from app.core.database import close_database, session_factory
from app.core.storage import ensure_storage_bucket, object_storage
from app.http.ai import OpenAICompatibleConfiguration, OpenAICompatibleProvider
from app.runner.environment import ControlledDockerEnvironmentRuntime
from app.runner.k6 import K6ProcessRunner
from app.services.ai import AIJobRunner
from app.services.environment_lab import (
    EnvironmentReconciliationService,
    EnvironmentRunCoordinator,
)
from app.services.execution_events import RedisExecutionEventBus
from app.services.notifications import NotificationDeliveryService
from app.services.performance import PerformanceRunCoordinator
from app.services.retention import RetentionCleanupService
from app.services.tasking import TestPlanService
from app.services.test_plan_runner import TestPlanRunCoordinator
from app.services.workflow_coordinator import WorkflowRunCoordinator
from app.services.workflows import WorkflowService
from app.tasking.celery_app import celery_app
from app.tasking.dispatch import CeleryTaskDispatcher

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
        celery_app.send_task(
            "flowtest.run_test_plan",
            args=[str(run.id)],
            queue=run.queue_name,
            priority=run.queue_priority,
        )


@celery_app.task(name="flowtest.cleanup_retention")  # type: ignore[untyped-decorator]
def cleanup_retention() -> None:
    _run_async(_cleanup_retention)


async def _cleanup_retention() -> None:
    async with session_factory() as session:
        summary = await RetentionCleanupService(session).cleanup()
    logger.info("Retention cleanup completed: %s", summary)


@celery_app.task(name="flowtest.run_ai_job")  # type: ignore[untyped-decorator]
def run_ai_job(job_id: str) -> None:
    _run_async(lambda: _run_ai_job(UUID(job_id)))


async def _run_ai_job(job_id: UUID) -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfiguration(
            base_url=settings.ai_base_url,
            model=settings.ai_model,
            api_key=settings.ai_api_key,
            timeout_seconds=settings.ai_request_timeout_seconds,
        )
    )
    async with session_factory() as session:
        await AIJobRunner(session, provider).run(job_id)


@celery_app.task(name="flowtest.run_performance")  # type: ignore[untyped-decorator]
def run_performance(run_id: str) -> None:
    _run_async(lambda: _run_performance(UUID(run_id)))


async def _run_performance(run_id: UUID) -> None:
    await ensure_storage_bucket()
    await PerformanceRunCoordinator(
        session_factory,
        K6ProcessRunner(raw_metrics_limit_bytes=settings.artifact_limit_bytes),
        object_storage,
    ).run(run_id)


@celery_app.task(name="flowtest.provision_environment")  # type: ignore[untyped-decorator]
def provision_environment(instance_id: str) -> None:
    _run_async(lambda: _provision_environment(UUID(instance_id)))


async def _provision_environment(instance_id: UUID) -> None:
    await EnvironmentRunCoordinator(
        session_factory,
        ControlledDockerEnvironmentRuntime(),
    ).provision(instance_id)


@celery_app.task(name="flowtest.cleanup_environment")  # type: ignore[untyped-decorator]
def cleanup_environment(instance_id: str) -> None:
    _run_async(lambda: _cleanup_environment(UUID(instance_id)))


async def _cleanup_environment(instance_id: UUID) -> None:
    await EnvironmentRunCoordinator(
        session_factory,
        ControlledDockerEnvironmentRuntime(),
    ).cleanup(instance_id)


@celery_app.task(name="flowtest.reconcile_environments")  # type: ignore[untyped-decorator]
def reconcile_environments() -> None:
    _run_async(_reconcile_environments)


async def _reconcile_environments() -> None:
    async with session_factory() as session:
        count = await EnvironmentReconciliationService(session).dispatch_due(
            CeleryTaskDispatcher(celery_app)
        )
    if count:
        logger.info("Environment reconciliation dispatched %s operations", count)


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
