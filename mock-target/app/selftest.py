"""Opt-in business fixtures and a separately served observer management app."""

import asyncio
import hmac
import os
import sqlite3
from pathlib import Path as FilePath
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .selftest_contracts import (
    SYNTHETIC_FILE_BYTES,
    BinaryResponseSnapshot,
    FixtureConfiguration,
    FixtureJournal,
    FixtureOperation,
    FixtureRemovalCondition,
    SyntheticCookieSnapshot,
    SyntheticHeaderSnapshot,
    SyntheticRequest,
)
from .selftest_journal import FixtureError, FixtureStore
from .selftest_s5 import install_s5_routes, wait_cookie_barrier

PathKey = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")]


class BodyBudgetMiddleware:
    def __init__(self, app: ASGIApp, *, maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.maximum_bytes:
                await _failure("FIXTURE_BODY_LIMIT", "合成请求超过大小上限", 413)(
                    scope, receive, send
                )
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {
                "type": "http.request",
                "body": b"".join(chunks),
                "more_body": False,
            }

        await self.app(scope, replay, send)


def _failure(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": None,
                "trace_id": str(uuid4()),
            }
        },
    )


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def routing_error(_request: Request, error: HTTPException) -> JSONResponse:
        code, message = {
            404: ("FIXTURE_ROUTE_NOT_FOUND", "合成场景接口不存在"),
            405: ("FIXTURE_METHOD_NOT_ALLOWED", "合成场景接口不支持此方法"),
        }.get(error.status_code, ("FIXTURE_HTTP_ERROR", "合成场景请求失败"))
        response = _failure(code, message, error.status_code)
        if error.headers and "Allow" in error.headers:
            response.headers["Allow"] = error.headers["Allow"]
        return response

    @app.exception_handler(FixtureError)
    async def fixture_error(_request: Request, error: FixtureError) -> JSONResponse:
        return _failure(error.code, error.message, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return _failure("FIXTURE_VALIDATION_ERROR", "合成场景参数不合法", 422)

    @app.exception_handler(sqlite3.Error)
    async def journal_error(_request: Request, _error: sqlite3.Error) -> JSONResponse:
        return _failure("FIXTURE_JOURNAL_UNAVAILABLE", "合成场景证据暂不可用", 503)


def _synthetic_precedence_header(request: Request) -> SyntheticHeaderSnapshot | None:
    values = request.headers.getlist("x-selftest-precedence")
    if not values:
        return None
    allowed = {"project", "environment", "api", "case", "runtime", "node"}
    value = values[0] if len(values) == 1 and values[0] in allowed else None
    return SyntheticHeaderSnapshot.model_validate({"value": value, "count": min(len(values), 100)})


def create_business_app(store: FixtureStore) -> FastAPI:
    app = FastAPI(title="FlowTest Synthetic Fixtures", docs_url=None, redoc_url=None)
    app.add_middleware(BodyBudgetMiddleware, maximum_bytes=8192)
    _register_errors(app)

    async def perform(
        batch_key: str,
        scenario_id: str,
        payload: SyntheticRequest,
        request: Request,
        *,
        binary: bool = False,
        synthetic_cookie: SyntheticCookieSnapshot | None = None,
        binary_request: BinaryResponseSnapshot | None = None,
    ) -> Response:
        reply = await run_in_threadpool(
            store.record,
            batch_key,
            scenario_id,
            payload,
            method=request.method,
            authorization_present="authorization" in request.headers,
            cookie_present="cookie" in request.headers,
            operation=_operation(request, binary, synthetic_cookie, binary_request),
            synthetic_precedence_header=_synthetic_precedence_header(request),
            synthetic_cookie=synthetic_cookie,
            binary_request=binary_request,
        )
        completed = cancelled = False
        try:
            if synthetic_cookie is not None and synthetic_cookie.stage == "barrier":
                await wait_cookie_barrier(store, batch_key, scenario_id)
            if reply.delay_ms:
                await asyncio.sleep(reply.delay_ms / 1000)
            response = (
                Response(
                    SYNTHETIC_FILE_BYTES,
                    status_code=reply.status_code,
                    media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="flowtest.bin"'},
                )
                if binary
                else JSONResponse(reply.body.model_dump(mode="json"), status_code=reply.status_code)
            )
            completed = True
            return response
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            # Only bounded synthetic lifecycle facts; no header/body/error payload is added.
            await run_in_threadpool(
                store.finish,
                reply.request_id,
                "completed" if completed else "cancelled" if cancelled else "failed",
            )

    @app.get("/{batch_key}/{scenario_id}/request")
    @app.get("/{batch_key}/{scenario_id}/sequence")
    async def read_fixture(
        batch_key: PathKey,
        scenario_id: PathKey,
        request: Request,
        marker: Annotated[str, Query(max_length=160)] = "",
        branch: Annotated[str, Query(max_length=80)] = "",
        iteration_key: Annotated[str, Query(max_length=80)] = "",
    ) -> Response:
        return await perform(
            batch_key,
            scenario_id,
            SyntheticRequest(marker=marker, branch=branch, iteration_key=iteration_key),
            request,
        )

    @app.post("/{batch_key}/{scenario_id}/request")
    async def write_fixture(
        batch_key: PathKey,
        scenario_id: PathKey,
        payload: SyntheticRequest,
        request: Request,
    ) -> Response:
        return await perform(batch_key, scenario_id, payload, request)

    @app.get("/{batch_key}/{scenario_id}/download")
    async def download_fixture(
        batch_key: PathKey,
        scenario_id: PathKey,
        request: Request,
        marker: Annotated[str, Query(max_length=160)] = "",
    ) -> Response:
        return await perform(
            batch_key,
            scenario_id,
            SyntheticRequest(marker=marker),
            request,
            binary=True,
        )

    install_s5_routes(app, store, perform)
    return app


def _operation(
    request: Request,
    binary: bool,
    cookie: SyntheticCookieSnapshot | None,
    upload: BinaryResponseSnapshot | None,
) -> FixtureOperation:
    if binary:
        return "download"
    if upload is not None:
        return "upload"
    if cookie is not None:
        stages: dict[str, FixtureOperation] = {
            "set": "cookie/set",
            "barrier": "cookie/barrier",
            "check": "cookie/check",
        }
        return stages[cookie.stage]
    return "sequence" if request.url.path.endswith("/sequence") else "request"


def install_business_routes(app: FastAPI, journal_path: FilePath | None = None) -> None:
    """Preserve legacy routes; enable synthetic capture only with an explicit journal path."""
    configured = (
        str(journal_path)
        if journal_path is not None
        else os.environ.get("FLOWTEST_SELFTEST_JOURNAL_PATH", "")
    )
    if not configured:
        return
    store = FixtureStore(FilePath(configured))
    store.start_epoch()
    app.mount("/selftest", create_business_app(store))


def create_observer_app() -> FastAPI:
    """Uvicorn factory for an observer-only listener/process on the management network."""
    configured = os.environ.get("FLOWTEST_SELFTEST_JOURNAL_PATH", "")
    token = os.environ.get("FLOWTEST_SELFTEST_OBSERVER_TOKEN", "")
    if not configured or len(token) < 32:
        raise RuntimeError("Explicit journal path and observer token (32+ characters) required")
    return observer_app(FixtureStore(FilePath(configured)), token)


def observer_app(store: FixtureStore, token: str) -> FastAPI:
    if len(token) < 32:
        raise ValueError("Observer token must contain at least 32 characters")
    app = FastAPI(
        title="FlowTest Fixture Observer",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(BodyBudgetMiddleware, maximum_bytes=16_384)
    _register_errors(app)

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        if not hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
            raise FixtureError("FIXTURE_OBSERVER_AUTH_REQUIRED", "需要独立观察器身份", 401)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.put(
        "/selftest/batches/{batch_key}/scenarios/{scenario_id}",
        dependencies=[Depends(authorize)],
        status_code=204,
    )
    def configure(
        batch_key: PathKey, scenario_id: PathKey, payload: FixtureConfiguration
    ) -> Response:
        store.configure(batch_key, scenario_id, payload)
        return Response(status_code=204)

    @app.get(
        "/selftest/batches/{batch_key}/scenarios/{scenario_id}/journal",
        dependencies=[Depends(authorize)],
        response_model=FixtureJournal,
        response_model_exclude_unset=True,
    )
    def journal(
        batch_key: PathKey,
        scenario_id: PathKey,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> FixtureJournal:
        return store.journal(batch_key, scenario_id, after_sequence=after_sequence, limit=limit)

    @app.delete(
        "/selftest/batches/{batch_key}/scenarios/{scenario_id}",
        dependencies=[Depends(authorize)],
        status_code=204,
    )
    def remove(
        batch_key: PathKey,
        scenario_id: PathKey,
        condition: FixtureRemovalCondition | None = None,
    ) -> Response:
        store.remove(batch_key, scenario_id, condition=condition)
        return Response(status_code=204)

    return app
