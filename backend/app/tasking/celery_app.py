from celery import Celery
from celery.signals import (
    heartbeat_sent,
    task_failure,
    task_retry,
    task_success,
    worker_process_init,
    worker_process_shutdown,
    worker_ready,
    worker_shutdown,
)
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from app.core.config import settings
from app.observability.task_metrics import (
    record_task_result,
    record_worker_heartbeat,
    remove_worker,
)
from app.observability.tracing import configure_worker_tracing, shutdown_tracing

celery_app = Celery(
    "flowtest",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasking.tasks"],
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86_400,
    broker_connection_retry_on_startup=True,
    task_default_queue="general",
    task_routes={
        "flowtest.run_workflow": {"queue": "general"},
        "flowtest.run_test_plan": {"queue": "general"},
        "flowtest.*data*": {"queue": "data"},
        "flowtest.*ai*": {"queue": "ai"},
    },
    beat_schedule={
        "enqueue-due-test-plans": {
            "task": "flowtest.enqueue_due_test_plans",
            "schedule": settings.scheduler_poll_seconds,
        },
        "cleanup-retention": {
            "task": "flowtest.cleanup_retention",
            "schedule": settings.retention_cleanup_interval_seconds,
        },
    },
)


def _initialize_worker_tracing(**_kwargs: object) -> None:
    configure_worker_tracing(settings.otel_worker_service_name)


def _shutdown_worker_tracing(**_kwargs: object) -> None:
    shutdown_tracing()


def _worker_hostname(sender: object | None) -> str:
    sources = (
        sender,
        getattr(sender, "controller", None),
        getattr(sender, "eventer", None),
        getattr(sender, "worker", None),
    )
    for source in sources:
        hostname = getattr(source, "hostname", None)
        if hostname:
            return str(hostname)
    return "unknown-worker"


def _record_worker(sender: object | None = None, **_kwargs: object) -> None:
    record_worker_heartbeat(_worker_hostname(sender))


def _remove_worker(sender: object | None = None, **_kwargs: object) -> None:
    remove_worker(_worker_hostname(sender))


def _record_task_success(**_kwargs: object) -> None:
    record_task_result("succeeded")


def _record_task_failure(**_kwargs: object) -> None:
    record_task_result("failed")


def _record_task_retry(**_kwargs: object) -> None:
    record_task_result("retried")


worker_ready.connect(_record_worker, weak=False)
heartbeat_sent.connect(_record_worker, weak=False)
worker_shutdown.connect(_remove_worker, weak=False)
task_success.connect(_record_task_success, weak=False)
task_failure.connect(_record_task_failure, weak=False)
task_retry.connect(_record_task_retry, weak=False)


if settings.otel_enabled:
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
    worker_process_init.connect(_initialize_worker_tracing, weak=False)
    worker_process_shutdown.connect(_shutdown_worker_tracing, weak=False)
