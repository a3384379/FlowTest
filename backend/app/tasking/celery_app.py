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
    beat_schedule={
        "enqueue-due-test-plans": {
            "task": "flowtest.enqueue_due_test_plans",
            "schedule": settings.scheduler_poll_seconds,
        }
    },
)
