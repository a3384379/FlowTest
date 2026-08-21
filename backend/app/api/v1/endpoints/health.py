import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.api.dependencies import SessionDependency
from app.core.config import settings
from app.core.database import check_database
from app.core.redis import check_redis
from app.core.storage import check_storage
from app.domain.runtime_profiles import RuntimeProfile, describe_runtime_profile
from app.observability.metrics import MetricsRegistry, render_metrics
from app.observability.task_metrics import InProcessTaskMetricsReader, RedisTaskMetricsReader
from app.schemas.health import (
    FeatureFlagsResponse,
    HealthResponse,
    ReadinessResponse,
    RuntimeProfileResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/runtime-profile", response_model=RuntimeProfileResponse)
async def runtime_profile() -> RuntimeProfileResponse:
    profile = describe_runtime_profile(settings.runtime_profile)
    return RuntimeProfileResponse(
        profile=profile.profile,
        worker_topology=profile.worker_topology,
        unavailable_features=profile.unavailable_features,
    )


@router.get("/features", response_model=FeatureFlagsResponse)
async def feature_flags() -> FeatureFlagsResponse:
    return FeatureFlagsResponse(
        teams=settings.feature_teams_enabled,
        test_assets=settings.feature_test_assets_enabled,
        advanced_workflows=settings.feature_advanced_workflows_enabled,
        data_nodes=settings.feature_data_nodes_enabled,
        contract_testing=settings.feature_contract_testing_enabled,
        quality_center=settings.feature_quality_center_enabled,
        oidc=settings.feature_oidc_enabled,
        ai=settings.feature_ai_enabled,
        multi_protocol=settings.feature_multi_protocol_enabled,
        event_protocols=settings.feature_event_protocols_enabled,
        performance_lab=settings.feature_performance_lab_enabled,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(response: Response) -> ReadinessResponse:
    checks: dict[str, Callable[[], Awaitable[None]]] = {
        "database": check_database,
        "storage": check_storage,
    }
    if settings.runtime_profile is not RuntimeProfile.STANDALONE:
        checks["redis"] = check_redis
    results = await asyncio.gather(*(check() for check in checks.values()), return_exceptions=True)
    statuses = {
        name: "error" if isinstance(result, BaseException) else "ok"
        for name, result in zip(checks, results, strict=True)
    }
    if "error" in statuses.values():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", checks=statuses)
    return ReadinessResponse(status="ok", checks=statuses)


@router.get("/metrics", include_in_schema=False, response_class=PlainTextResponse)
async def metrics(request: Request, session: SessionDependency) -> PlainTextResponse:
    registry = request.app.state.metrics_registry
    if not isinstance(registry, MetricsRegistry):
        return PlainTextResponse("", status_code=503)
    task_metrics = getattr(request.app.state, "task_metrics_reader", None)
    if task_metrics is None:
        task_metrics = (
            InProcessTaskMetricsReader()
            if settings.runtime_profile is RuntimeProfile.STANDALONE
            else RedisTaskMetricsReader()
        )
    content = await render_metrics(registry, session, task_metrics)
    return PlainTextResponse(content, media_type="text/plain; version=0.0.4; charset=utf-8")
