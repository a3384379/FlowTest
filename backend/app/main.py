from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.database import close_database, engine, session_factory
from app.core.errors import AppError, register_exception_handlers
from app.core.logging import configure_logging
from app.core.storage import ensure_storage_bucket, object_storage
from app.domain.runtime_profiles import RuntimeProfile
from app.engine.events import ExecutionEventBus
from app.middleware.metrics import MetricsMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.trace import TraceIdMiddleware
from app.observability.metrics import MetricsRegistry
from app.observability.tracing import instrument_fastapi, shutdown_tracing
from app.services.auth import bootstrap_administrator

if settings.runtime_profile is RuntimeProfile.STANDALONE:
    from app.core.standalone_schema import initialize_standalone_database
    from app.services.execution_events import InProcessExecutionEventBus
    from app.tasking.standalone import StandaloneTaskDispatcher
else:
    from app.core.redis import close_redis, redis_client
    from app.services.execution_events import RedisExecutionEventBus
    from app.tasking.celery_app import celery_app
    from app.tasking.dispatch import CeleryTaskDispatcher


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if settings.runtime_profile is RuntimeProfile.STANDALONE:
        await initialize_standalone_database()
    await ensure_storage_bucket()
    async with session_factory() as session:
        await bootstrap_administrator(session)
    standalone_dispatcher: StandaloneTaskDispatcher | None = None
    event_bus: ExecutionEventBus
    dispatcher: object
    if settings.runtime_profile is RuntimeProfile.STANDALONE:
        event_bus = InProcessExecutionEventBus(
            retention_seconds=settings.workflow_event_retention_seconds,
        )
        standalone_dispatcher = StandaloneTaskDispatcher(session_factory, event_bus, object_storage)
        standalone_dispatcher.start_scheduler()
        dispatcher = standalone_dispatcher
        application.state.task_metrics_reader = standalone_dispatcher.metrics_reader
    else:
        event_bus = RedisExecutionEventBus(
            redis_client,
            retention_seconds=settings.workflow_event_retention_seconds,
        )
        dispatcher = CeleryTaskDispatcher(celery_app)
    application.state.database_session_factory = session_factory
    application.state.execution_event_bus = event_bus
    application.state.workflow_run_coordinator = dispatcher
    application.state.test_plan_dispatcher = dispatcher
    application.state.ai_job_dispatcher = dispatcher
    application.state.performance_dispatcher = dispatcher
    application.state.environment_dispatcher = dispatcher
    yield
    if standalone_dispatcher is not None:
        await standalone_dispatcher.shutdown()
    shutdown_tracing()
    if settings.runtime_profile is not RuntimeProfile.STANDALONE:
        await close_redis()
    await close_database()


def create_app() -> FastAPI:
    metrics = MetricsRegistry()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.state.metrics_registry = metrics
    instrument_fastapi(application, engine)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(MetricsMiddleware, registry=metrics)
    application.add_middleware(TraceIdMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    _mount_frontend(application)
    return application


def _mount_frontend(application: FastAPI) -> None:
    if settings.runtime_profile is not RuntimeProfile.STANDALONE:
        return
    configured = settings.frontend_dist_dir.strip()
    if not configured:
        return
    root = Path(configured).expanduser().resolve()
    index = root / "index.html"
    if not index.is_file():
        return

    @application.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str) -> FileResponse:
        api_prefix = settings.api_v1_prefix.strip("/")
        if path == api_prefix or path.startswith(f"{api_prefix}/"):
            raise AppError(code="NOT_FOUND", message="资源不存在", status_code=404)
        candidate = (root / Path(path)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return FileResponse(index)
        return FileResponse(candidate if candidate.is_file() else index)


configure_logging()
app = create_app()
