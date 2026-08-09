from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.observability.metrics import MetricsRegistry


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, registry: MetricsRegistry) -> None:
        super().__init__(app)
        self._registry = registry

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            self._registry.observe_request(
                method=request.method,
                path=request.url.path,
                status=status_code,
                duration=perf_counter() - started,
            )
