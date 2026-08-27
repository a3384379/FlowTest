import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.context import get_trace_id

SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "cookie",
        "password",
        "proxy-authorization",
        "refresh_token",
        "secret",
        "set-cookie",
        "token",
        "x-api-key",
    }
)


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        variable_name = value.get("variable")
        sensitive_variable = isinstance(variable_name, str) and _is_sensitive_key(variable_name)
        return {
            str(key): (
                "***"
                if _is_sensitive_key(str(key)) or (sensitive_variable and str(key) == "value")
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in SENSITIVE_KEYS:
        return True
    segments = {segment for segment in re.split(r"[^a-z0-9]+", lowered) if segment}
    if segments & {"password", "authorization", "cookie", "token", "secret"}:
        return True
    normalized = "".join(character for character in lowered if character.isalnum())
    return normalized.endswith(("password", "authorization", "cookie", "token", "secret", "apikey"))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": get_trace_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), ensure_ascii=False, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # httpx includes the complete request URL in INFO logs. Import document URLs may
    # contain short-lived credentials, so only retain failures from the client.
    logging.getLogger("httpx").setLevel(logging.WARNING)
