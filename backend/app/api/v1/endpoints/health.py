import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.database import check_database
from app.core.redis import check_redis
from app.core.storage import check_storage
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(response: Response) -> ReadinessResponse:
    checks: dict[str, Callable[[], Awaitable[None]]] = {
        "database": check_database,
        "redis": check_redis,
        "storage": check_storage,
    }
    results = await asyncio.gather(*(check() for check in checks.values()), return_exceptions=True)
    statuses = {
        name: "error" if isinstance(result, BaseException) else "ok"
        for name, result in zip(checks, results, strict=True)
    }
    if "error" in statuses.values():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", checks=statuses)
    return ReadinessResponse(status="ok", checks=statuses)
