import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_trace_id
from app.core.logging import redact

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def error_response(
    *, code: str, message: str, status_code: int, details: Any = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": redact(details),
                "trace_id": get_trace_id(),
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, error: AppError) -> JSONResponse:
        return error_response(
            code=error.code,
            message=error.message,
            status_code=error.status_code,
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            code="VALIDATION_ERROR",
            message="请求参数不合法",
            status_code=422,
            details=_safe_validation_errors(error),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        code, message = _http_error_contract(error.status_code)
        return error_response(
            code=code,
            message=message,
            status_code=error.status_code,
            details=None,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=error)
        return error_response(
            code="INTERNAL_ERROR",
            message="服务暂时不可用",
            status_code=500,
        )


_SENSITIVE_LOCATION_PARTS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "envelope",
        "evidence",
        "password",
        "secret",
        "token",
    }
)


def _safe_validation_errors(error: RequestValidationError) -> list[dict[str, Any]]:
    """Keep validation shape while removing request values from sensitive fields."""

    safe_errors: list[dict[str, Any]] = []
    for item in error.errors():
        safe_item = _json_safe_validation_value(redact(dict(item)))
        location = item.get("loc", ())
        if isinstance(location, (list, tuple)) and any(
            _is_sensitive_location_part(str(part)) for part in location
        ):
            safe_item["input"] = "***"
        safe_errors.append(safe_item)
    return safe_errors


def _json_safe_validation_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_validation_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_validation_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _is_sensitive_location_part(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if normalized in _SENSITIVE_LOCATION_PARTS:
        return True
    return normalized.endswith(tuple(_SENSITIVE_LOCATION_PARTS))


def _http_error_contract(status_code: int) -> tuple[str, str]:
    contracts = {
        400: ("BAD_REQUEST", "请求不合法"),
        401: ("AUTHENTICATION_REQUIRED", "请先登录"),
        403: ("FORBIDDEN", "没有执行此操作的权限"),
        404: ("NOT_FOUND", "资源不存在"),
        405: ("METHOD_NOT_ALLOWED", "请求方法不支持"),
        409: ("CONFLICT", "请求与当前资源状态冲突"),
        429: ("RATE_LIMITED", "请求过于频繁, 请稍后重试"),
    }
    return contracts.get(status_code, (f"HTTP_{status_code}", "请求失败"))
