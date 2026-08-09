import re
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import reset_trace_id, set_trace_id

TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        requested_trace_id = request.headers.get("X-Trace-ID", "")
        trace_id = (
            requested_trace_id if TRACE_ID_PATTERN.fullmatch(requested_trace_id) else uuid4().hex
        )
        token = set_trace_id(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            reset_trace_id(token)
