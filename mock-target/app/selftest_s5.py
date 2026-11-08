"""Opt-in routes for frozen synthetic files and barrier-synchronized branch cookies."""

import asyncio
import hashlib
from typing import Annotated, Literal, Protocol

from fastapi import FastAPI, File, Path, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from .selftest_contracts import (
    SYNTHETIC_FILE_BYTES,
    BinaryResponseSnapshot,
    CookieStage,
    SyntheticCookieSnapshot,
    SyntheticRequest,
)
from .selftest_journal import FixtureError, FixtureStore

PathKey = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")]
Branch = Literal["left", "right"]


class Perform(Protocol):
    async def __call__(
        self,
        batch_key: str,
        scenario_id: str,
        payload: SyntheticRequest,
        request: Request,
        *,
        binary: bool = False,
        synthetic_cookie: SyntheticCookieSnapshot | None = None,
        binary_request: BinaryResponseSnapshot | None = None,
    ) -> Response: ...


async def wait_cookie_barrier(store: FixtureStore, batch: str, scenario: str) -> None:
    try:
        async with asyncio.timeout(5):
            while True:
                journal = await run_in_threadpool(store.journal, batch, scenario)
                arrivals = {
                    entry.request_body.branch
                    for entry in journal.entries
                    if entry.synthetic_cookie is not None
                    and entry.synthetic_cookie.stage == "barrier"
                }
                if arrivals == {"left", "right"}:
                    return
                await asyncio.sleep(0.01)
    except TimeoutError as error:
        raise FixtureError("FIXTURE_BARRIER_DEADLINE", "合成并行分支未同时到达屏障", 409) from error


def install_s5_routes(app: FastAPI, store: FixtureStore, perform: Perform) -> None:
    @app.post("/{batch_key}/{scenario_id}/upload")
    async def upload(
        batch_key: PathKey,
        scenario_id: PathKey,
        request: Request,
        file: Annotated[UploadFile, File()],
        marker: Annotated[str, Query(max_length=160)] = "",
    ) -> Response:
        content = await file.read(4097)
        if (
            file.filename != "flowtest.bin"
            or file.content_type != "application/octet-stream"
            or content != SYNTHETIC_FILE_BYTES
        ):
            raise FixtureError("FIXTURE_SYNTHETIC_FILE_REQUIRED", "只接受冻结的合成文件", 422)
        snapshot = BinaryResponseSnapshot(
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content_type="application/octet-stream",
            filename="flowtest.bin",
        )
        return await perform(
            batch_key,
            scenario_id,
            SyntheticRequest(marker=marker, value=snapshot.model_dump(mode="json")),
            request,
            binary_request=snapshot,
        )

    @app.get("/{batch_key}/{scenario_id}/cookie/{stage}")
    async def cookie(
        batch_key: PathKey,
        scenario_id: PathKey,
        stage: CookieStage,
        request: Request,
        branch: Branch,
        marker: Annotated[str, Query(max_length=160)] = "",
    ) -> Response:
        candidate = request.cookies.get("flowtest_synthetic_branch")
        received: Branch | None = (
            "left" if candidate == "left" else "right" if candidate == "right" else None
        )
        response = await perform(
            batch_key,
            scenario_id,
            SyntheticRequest(
                marker=marker, branch=branch, value=received if stage == "check" else branch
            ),
            request,
            synthetic_cookie=SyntheticCookieSnapshot(stage=stage, value=received),
        )
        if stage == "set":
            response.set_cookie(
                "flowtest_synthetic_branch",
                branch,
                path=f"{request.scope.get('root_path', '')}/{batch_key}/{scenario_id}",
                httponly=True,
                samesite="strict",
            )
        return response
