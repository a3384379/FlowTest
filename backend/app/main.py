from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import close_database, session_factory
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.redis import close_redis, redis_client
from app.core.storage import ensure_storage_bucket
from app.middleware.trace import TraceIdMiddleware
from app.services.auth import bootstrap_administrator
from app.services.execution_events import RedisExecutionEventBus
from app.tasking.celery_app import celery_app
from app.tasking.dispatch import CeleryTaskDispatcher


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    await ensure_storage_bucket()
    async with session_factory() as session:
        await bootstrap_administrator(session)
    event_bus = RedisExecutionEventBus(
        redis_client,
        retention_seconds=settings.workflow_event_retention_seconds,
    )
    dispatcher = CeleryTaskDispatcher(celery_app)
    application.state.database_session_factory = session_factory
    application.state.execution_event_bus = event_bus
    application.state.workflow_run_coordinator = dispatcher
    application.state.test_plan_dispatcher = dispatcher
    yield
    await close_redis()
    await close_database()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(TraceIdMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


configure_logging()
app = create_app()
