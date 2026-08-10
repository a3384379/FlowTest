from celery import Celery

from app.core.config import settings

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
