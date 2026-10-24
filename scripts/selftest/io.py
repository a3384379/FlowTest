"""Bounded JSON and public HTTP access; credentials never enter receipts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import cast

import httpx
from pydantic import BaseModel, JsonValue

type JsonObject = dict[str, JsonValue]
MAX_JSON_BYTES = 8 * 1024 * 1024


class HarnessError(RuntimeError):
    """A fail-closed harness error with a safe, bounded diagnostic."""


def object_value(value: object) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HarnessError("SELFTEST_EXPECTED_OBJECT")
    return cast(JsonObject, value)


def text_value(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise HarnessError("SELFTEST_EXPECTED_TEXT")
    return value


def integer_value(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise HarnessError("SELFTEST_EXPECTED_INTEGER")
    return value


def objects_value(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        raise HarnessError("SELFTEST_EXPECTED_LIST")
    return [object_value(item) for item in value]


def read_json(path: Path) -> JsonObject:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise HarnessError("SELFTEST_JSON_TOO_LARGE")
    return object_value(json.loads(path.read_text(encoding="utf-8")))


def write_json(path: Path, value: BaseModel | JsonValue) -> None:
    """Atomically replace a local receipt, with private permissions even on first write."""
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    if len(encoded) > MAX_JSON_BYTES:
        raise HarnessError("SELFTEST_JSON_TOO_LARGE")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".selftest-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class PublicAPI:
    """Use the existing REST API without automatic mutation retries or payload logging."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        organization_id: str | None = None,
        *,
        api_prefix: str = "/api/v1/",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        prefix = api_prefix.strip("/")
        api_base = base_url.rstrip("/") + "/" + (prefix + "/" if prefix else "")
        self._client = httpx.AsyncClient(
            base_url=api_base,
            timeout=30,
            trust_env=False,
            transport=transport,
        )
        self._token = token
        self._organization_id = organization_id

    def set_organization(self, organization_id: str) -> None:
        self._organization_id = organization_id

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"X-Requested-With": "FlowTest"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._organization_id:
            headers["X-Organization-ID"] = self._organization_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def upload_synthetic(self, path: str, filename: str, content: bytes) -> JsonObject:
        if len(content) > 8192 or not filename.endswith(".json"):
            raise HarnessError("SELFTEST_SYNTHETIC_UPLOAD_INVALID")
        response = await self._client.post(
            path.lstrip("/"),
            headers=self._headers(),
            files={"file": (filename, content, "application/json")},
        )
        if response.is_error:
            raise HarnessError(_error_summary(response))
        return object_value(response.json())

    async def read_synthetic(self, path: str) -> bytes:
        async with self._client.stream(
            "GET", path.lstrip("/"), headers=self._headers()
        ) as response:
            if response.is_error:
                await response.aread()
                raise HarnessError(_error_summary(response))
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 8192:
                    raise HarnessError("SELFTEST_SYNTHETIC_DOWNLOAD_TOO_LARGE")
            return bytes(content)

    async def upload_synthetic_binary(self, path: str) -> JsonObject:
        """The sole binary input is a fixed public fixture, never a caller-provided file."""
        response = await self._client.post(
            path.lstrip("/"),
            headers=self._headers(),
            files={"file": ("flowtest.bin", b"flowtest-download", "application/octet-stream")},
        )
        if response.is_error:
            raise HarnessError(_error_summary(response))
        return object_value(response.json())

    async def download_synthetic_binary(self, path: str) -> tuple[bytes, str]:
        async with self._client.stream(
            "GET", path.lstrip("/"), headers=self._headers()
        ) as response:
            if response.is_error:
                await response.aread()
                raise HarnessError(_error_summary(response))
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 4096:
                    raise HarnessError("SELFTEST_SYNTHETIC_DOWNLOAD_TOO_LARGE")
            return bytes(content), response.headers.get("content-type", "")

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> JsonValue:
        headers = self._headers(idempotency_key)
        response = await self._client.request(
            method, path.lstrip("/"), json=payload, headers=headers
        )
        if response.is_error and response.status_code not in allow_status:
            raise HarnessError(_error_summary(response))
        if not response.content:
            return None
        if len(response.content) > MAX_JSON_BYTES:
            raise HarnessError("SELFTEST_HTTP_RESPONSE_TOO_LARGE")
        return cast(JsonValue, response.json())

    async def object(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return object_value(
            await self.request(method, path, payload, idempotency_key=idempotency_key)
        )


def _error_summary(response: httpx.Response) -> str:
    code = "HTTP_ERROR"
    trace = response.headers.get("X-Trace-ID", "unknown")
    try:
        body = object_value(response.json())
        error = object_value(body.get("error", {}))
        candidate = error.get("code")
        if isinstance(candidate, str) and candidate.replace("_", "").isalnum():
            code = candidate[:100]
        trace = str(error.get("trace_id", body.get("trace_id", trace)))[:128]
    except (ValueError, HarnessError):
        pass
    return f"SELFTEST_HTTP_{response.status_code}:{code}:trace={trace}"
