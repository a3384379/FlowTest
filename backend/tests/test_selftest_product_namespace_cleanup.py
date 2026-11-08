"""Real owned Mock namespaces survive unknown runs and are reclaimed after cancellation."""

import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from test_selftest_fixed_baseline import _fixture_apps
from test_selftest_product_api import ProductContext, _ready
from test_selftest_product_api import product as product
from test_tasking_api import tasking_context as tasking_context

from app.core.errors import AppError
from app.core.self_tests import get_self_test_settings
from app.main import app
from app.models.access import User
from app.models.tasking import TestPlanRun as PlanRun
from app.schemas.self_tests import BatchResponse
from app.services.tasking import TestPlanService as PlanService
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanCoordinator

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.io import PublicAPI, object_value, read_json, write_json
from scripts.selftest.product_watchdog import run_expired_watchdogs


@dataclass(repr=False)
class NamespaceWorld:
    product: ProductContext
    directory: Path
    task: dict
    batch: dict
    observer_app: object
    observer: PublicAPI
    writer: PublicAPI
    machine: PublicAPI
    path: str
    foreign_path: str

    async def current(self) -> BatchResponse:
        return BatchResponse.model_validate(
            await self.product.get(self.product.root + f"/runs/{self.batch['id']}")
        )

    async def cancel(self, *, status: int = 200) -> BatchResponse:
        await self.product.post(
            self.product.root + f"/runs/{self.batch['id']}/cancel", {}, status=status
        )
        return await self.current()

    async def cleanup(self, batch: BatchResponse, observer: PublicAPI | None = None) -> dict:
        await run_expired_watchdogs(
            self.machine,
            (batch,),
            self.directory,
            writer=self.writer,
            observer=observer or self.observer,
        )
        return read_json(self.directory / self.batch["id"] / "namespace-cleanup.json")

    async def journal(self, path: str | None = None) -> dict:
        return object_value(
            await self.observer.request(
                "GET", (path or self.path) + "/journal", allow_status=(404,)
            )
        )


@pytest.fixture
async def namespace(
    product: ProductContext,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> AsyncIterator[NamespaceWorld]:
    fixed = getattr(request, "param", False)
    product.binding = product.binding.model_copy(
        update={"builds": product.binding.builds.model_copy(update={"fixture": "f" * 64})}
    )
    product.config = product.config.model_copy(update={"bindings": (product.binding,)})
    app.dependency_overrides[get_self_test_settings] = lambda: product.config
    installed = await _ready(product, "product-test-v1" if fixed else "mcp-core-v1")
    suffix = "runs" if fixed else "generation-batches"
    batch = await product.post(
        product.root + f"/installations/{installed['id']}/{suffix}",
        {},
        key="namespace-cleanup",
        status=202,
    )
    task = await product.post(
        product.agent + f"/runs/{batch['id']}/claim",
        {
            "expected_revision": batch["revision"],
            "nonce": "namespace-owned-" + "1" * 32,
        },
        machine="h",
    )
    write_json(tmp_path / batch["id"] / "private-lease.json", task)
    if fixed:
        batch = await product.post(
            product.agent + f"/runs/{batch['id']}/prepared",
            {
                "lease_token": task["lease_token"],
                "nonce": task["nonce"],
            },
            machine="h",
            status=202,
        )
    _, admin = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=admin),
    )
    writer = PublicAPI(
        "http://runner",
        product.headers["Authorization"].removeprefix("Bearer "),
        transport=httpx.ASGITransport(app=app),
    )
    machine = PublicAPI(
        "http://runner",
        product.machine("h")["Authorization"].removeprefix("Bearer "),
        transport=httpx.ASGITransport(app=app),
    )
    scenario = batch["expected_scenario_set"][0]["scenario_id"]
    path = f"/selftest/batches/{batch['batch_key']}/scenarios/{scenario}"
    foreign = "/selftest/batches/other-owned-batch/scenarios/other-scenario"
    try:
        await observer.request(
            "PUT", path, {"nonce": task["nonce"], "fixture_digest": task["builds"]["fixture"]}
        )
        await observer.request(
            "PUT",
            foreign,
            {"nonce": "other-nonce-" + "2" * 32, "fixture_digest": task["builds"]["fixture"]},
        )
        yield NamespaceWorld(
            product, tmp_path, task, batch, admin, observer, writer, machine, path, foreign
        )
    finally:
        await machine.close()
        await writer.close()
        await observer.close()


async def test_cancelled_generation_reclaims_only_registered_namespaces_without_sealing(
    namespace: NamespaceWorld,
) -> None:
    cancelled = await namespace.cancel()
    receipt = await namespace.cleanup(cancelled)
    assert (
        receipt["status"] == "completed" and receipt["independent_verification"] == "not_performed"
    )
    assert (await namespace.journal())["error"]["code"] == "FIXTURE_NOT_FOUND"
    assert (await namespace.journal(namespace.foreign_path))["batch_key"] == "other-owned-batch"
    await namespace.cleanup(cancelled)
    assert (await namespace.current()).phase == "cancelled"
    current = await namespace.current()
    assert (
        current.verdict == "blocked"
        and current.cleanup_status != "completed"
        and current.sealed_at is None
    )
    text = (namespace.directory / namespace.batch["id"] / "namespace-cleanup.json").read_text()
    assert (
        namespace.task["nonce"] not in text and "Bearer" not in text and "lease_token" not in text
    )


@pytest.mark.parametrize("mutation", ["nonce", "build", "binding", "missing_state"])
async def test_changed_private_state_or_foreign_nonce_never_deletes_a_namespace(
    namespace: NamespaceWorld,
    mutation: str,
) -> None:
    cancelled = await namespace.cancel()
    path = namespace.directory / namespace.batch["id"] / "private-lease.json"
    task = dict(namespace.task)
    if mutation == "nonce":
        await namespace.observer.request("DELETE", namespace.path)
        await namespace.observer.request(
            "PUT",
            namespace.path,
            {
                "nonce": "foreign-recreated-" + "3" * 32,
                "fixture_digest": task["builds"]["fixture"],
            },
        )
    elif mutation == "missing_state":
        path.unlink()
    else:
        if mutation == "build":
            task["builds"] = {**task["builds"], "fixture": "a" * 64}
        else:
            task["binding_fingerprint"] = "b" * 64
        write_json(path, task)
    await run_expired_watchdogs(
        namespace.machine,
        (cancelled,),
        namespace.directory,
        writer=namespace.writer,
        observer=namespace.observer,
    )
    assert "error" not in await namespace.journal()
    assert (await namespace.current()).verdict == "blocked"


@pytest.mark.parametrize("sent", [False, True])
async def test_unknown_namespace_delete_uses_readback_without_repeating_mutation(
    namespace: NamespaceWorld,
    sent: bool,
) -> None:
    class DropDelete(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.ASGITransport(app=namespace.observer_app)
            self.deletes = 0
            self.reads = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                self.reads += 1
            if request.method == "DELETE":
                self.deletes += 1
                assert self.deletes == 1
                if not sent:
                    raise httpx.ReadTimeout("private credential omitted", request=request)
            response = await self.inner.handle_async_request(request)
            if request.method == "DELETE":
                await response.aclose()
                raise httpx.ReadTimeout("private credential omitted", request=request)
            return response

    transport = DropDelete()
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=transport,
    )
    try:
        cancelled = await namespace.cancel()
        first = await namespace.cleanup(cancelled, observer)
        assert first["status"] == "needs_review"
        second = await namespace.cleanup(cancelled, observer)
        assert second["status"] == ("completed" if sent else "needs_review")
        assert transport.deletes == 1
        archive = namespace.directory / namespace.batch["id"] / "namespace-cleanup-attempt-1.json"
        assert read_json(archive) == first
        if not sent:
            third = await namespace.cleanup(cancelled, observer)
            assert third["attempts"] == 3
            reads = transport.reads
            for _ in range(2):
                limited = await namespace.cleanup(cancelled, observer)
            assert transport.reads == reads
            assert limited["attempts"] == 3 and limited["admitted_requests"] <= 100
            assert "SELFTEST_NAMESPACE_RECOVERY_LIMIT" in limited["reason_codes"]
    finally:
        await observer.close()
    assert "private credential" not in str(second)
    assert (await namespace.current()).verdict == "blocked"


@pytest.mark.parametrize("namespace", [True], indirect=True)
async def test_unknown_native_cancellation_prevents_delete_until_actual_run_is_stopped(
    namespace: NamespaceWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = PlanService.cancel_run

    async def unavailable(
        self: PlanService, *, actor: User, project_id: UUID, run_id: UUID
    ) -> PlanRun:
        raise AppError(code="SYNTHETIC_CANCEL_UNKNOWN", message="本轮合成故障", status_code=503)

    monkeypatch.setattr(PlanService, "cancel_run", unavailable)
    cancelled = await namespace.cancel(status=503)
    receipt = await namespace.cleanup(cancelled)
    assert receipt["status"] == "needs_review" and "error" not in await namespace.journal()
    monkeypatch.setattr(PlanService, "cancel_run", original)
    cancelled = await namespace.cancel()
    receipt = await namespace.cleanup(cancelled)
    assert receipt["status"] == "completed"
    assert (await namespace.journal())["error"]["code"] == "FIXTURE_NOT_FOUND"
    assert len(namespace.product.native.queue.test_plan_run_ids) == 1


@respx.mock
@pytest.mark.parametrize("namespace", [True], indirect=True)
async def test_real_terminal_failed_run_permits_physical_cleanup_without_rewriting_raw_result(
    namespace: NamespaceWorld,
) -> None:
    respx.get("http://fixture.example/value").mock(
        return_value=httpx.Response(200, json={"actual": 1})
    )
    identifier = namespace.batch["plan_run_ids"][0]
    await PlanCoordinator(
        namespace.product.native.session_maker, namespace.product.native.events
    ).run(UUID(identifier))
    cancelled = await namespace.cancel()
    receipt = await namespace.cleanup(cancelled)
    assert receipt["status"] == "completed"
    raw = await namespace.product.get(
        f"/api/v1/projects/{namespace.product.project_id}/test-plan-runs/{identifier}"
    )
    assert raw["run"]["status"] == "failed"
    assert {item["status"] for item in raw["items"]} == {"passed", "failed"}
    current = await namespace.current()
    assert current.verdict == "blocked" and current.cleanup_status != "completed"


@respx.mock
@pytest.mark.parametrize("namespace", [True], indirect=True)
@pytest.mark.parametrize(
    "flag,value",
    [
        ("children_complete", False),
        ("children_truncated", True),
        ("has_more", True),
        ("children_total", 1),
        ("next_cursor", "unseen-page"),
    ],
)
async def test_incomplete_child_projection_on_real_terminal_run_never_permits_namespace_delete(
    namespace: NamespaceWorld,
    flag: str,
    value: object,
) -> None:
    respx.get("http://fixture.example/value").mock(
        return_value=httpx.Response(200, json={"actual": 1})
    )
    await PlanCoordinator(
        namespace.product.native.session_maker, namespace.product.native.events
    ).run(UUID(namespace.batch["plan_run_ids"][0]))
    cancelled = await namespace.cancel()

    class IncompleteChildren(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            response = await httpx.ASGITransport(app=app).handle_async_request(request)
            if "/workflow-executions/" in request.url.path:
                await response.aread()
                return httpx.Response(response.status_code, json={**response.json(), flag: value})
            return response

    writer = PublicAPI(
        "http://runner",
        namespace.product.headers["Authorization"].removeprefix("Bearer "),
        transport=IncompleteChildren(),
    )
    try:
        await run_expired_watchdogs(
            namespace.machine,
            (cancelled,),
            namespace.directory,
            writer=writer,
            observer=namespace.observer,
        )
    finally:
        await writer.close()
    receipt = read_json(namespace.directory / namespace.batch["id"] / "namespace-cleanup.json")
    assert receipt["status"] == "needs_review"
    assert "error" not in await namespace.journal()
