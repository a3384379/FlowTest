import hashlib
import logging
from typing import cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.errors import error_response
from app.core.redis import redis_client
from app.services.rate_limit import RateLimitDecision, RedisRateClient, RedisRateLimiter

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._limiter = RedisRateLimiter(cast(RedisRateClient, redis_client))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rule = _rule(request)
        if not settings.rate_limit_enabled or rule is None:
            return await call_next(request)
        bucket, limit = rule
        try:
            decision = await self._limiter.check(
                key=f"{bucket}:{_identity(request)}",
                limit=limit,
                window_seconds=60,
            )
        except Exception as error:
            logger.warning("Rate limiter unavailable: %s", type(error).__name__)
            return await call_next(request)
        if not decision.allowed:
            response: Response = error_response(
                code="RATE_LIMITED",
                message="请求过于频繁, 请稍后重试",
                status_code=429,
                details={"retry_after": decision.retry_after},
            )
        else:
            response = await call_next(request)
        _apply_headers(response, decision)
        return response


def _rule(request: Request) -> tuple[str, int] | None:
    path = request.url.path
    if path.endswith("/auth/login"):
        return "auth-login", settings.auth_rate_limit_per_minute
    if path.startswith(f"{settings.api_v1_prefix}/mock/"):
        return "mock-dispatch", settings.execution_rate_limit_per_minute
    if request.method == "POST" and (
        path.endswith("/execute")
        or path.endswith("/executions")
        or path.endswith("/runs")
        or "/webhooks/" in path
    ):
        return "execution", settings.execution_rate_limit_per_minute
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "write", settings.write_rate_limit_per_minute
    return None


def _identity(request: Request) -> str:
    authorization = request.headers.get("Authorization")
    if authorization:
        return hashlib.sha256(authorization.encode()).hexdigest()[:24]
    client = request.client.host if request.client else "unknown"
    return hashlib.sha256(client.encode()).hexdigest()[:24]


def _apply_headers(response: Response, decision: RateLimitDecision) -> None:
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    if not decision.allowed:
        response.headers["Retry-After"] = str(decision.retry_after)
