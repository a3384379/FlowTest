"""RoundCleanup uses actual management API preconditions, not a synthetic delete counter."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from scripts.selftest.cleanup import RoundCleanup
from scripts.selftest.contracts import Builds
from scripts.selftest.fixed_baseline import execute_fixed_baseline
from scripts.selftest.io import HarnessError, PublicAPI, object_value
from scripts.selftest.namespace_conditions import read_namespace_condition
from test_selftest_fixed_baseline import _fixture_apps


@pytest.mark.parametrize("mode", ["normal", "foreign_before_read", "replace_after_read"])
async def test_round_cleanup_conditions_preserve_foreign_nonce_and_confirm_owned_absence(
    tmp_path: Path,
    mode: str,
) -> None:
    _, observer_app = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=observer_app),
    )
    nonce, digest = "owned-round-cleanup-nonce-001", "a" * 64
    path = "/selftest/batches/round-owned/scenarios/scenario"
    foreign = "foreign-replacement-nonce-001"
    await observer.request(
        "PUT",
        path,
        {"nonce": foreign if mode == "foreign_before_read" else nonce, "fixture_digest": digest},
    )
    deletes = []

    class RaceTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                deletes.append(json.loads(request.content))
                if mode == "replace_after_read":
                    await observer.request("DELETE", path)
                    await observer.request(
                        "PUT", path, {"nonce": foreign, "fixture_digest": digest}
                    )
            return await httpx.ASGITransport(app=observer_app).handle_async_request(request)

    reader = PublicAPI(
        "http://unused",
        transport=httpx.MockTransport(lambda request: pytest.fail("no native run was launched")),
    )
    controlled = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=RaceTransport(),
    )
    subject = RoundCleanup(
        batch_key="round-owned",
        project_id=uuid4(),
        output_dir=tmp_path,
        writer=reader,
        reader=reader,
        observer=controlled,
        nonce=nonce,
        fixture_digest=digest,
    )
    subject.register_fixture("scenario")
    try:
        receipt = await subject.finish()
        result = object_value(await observer.request("GET", path + "/journal", allow_status=(404,)))
        if mode == "normal":
            assert receipt.status == "completed" and result["error"]["code"] == "FIXTURE_NOT_FOUND"
        else:
            assert receipt.status in {"failed", "needs_review"}
            assert result["nonce"] == foreign
        assert len(deletes) == (0 if mode == "foreign_before_read" else 1)
        if deletes:
            assert deletes[0]["expected_nonce"] == nonce
            assert (
                deletes[0]["expected_fixture_epoch"] and deletes[0]["expected_registration_epoch"]
            )
        assert await subject.finish() == receipt
        assert len(deletes) <= 1
    finally:
        await observer.close()
        await controlled.close()
        await reader.close()


@pytest.mark.parametrize("sent", [True, False])
async def test_unknown_registration_uses_actual_metadata_before_conditional_cleanup(
    tmp_path: Path, sent: bool
) -> None:
    _, observer_app = _fixture_apps(tmp_path)
    methods: list[str] = []

    class LostRegistration(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            methods.append(request.method)
            transport = httpx.ASGITransport(app=observer_app)
            if request.method == "PUT":
                if sent:
                    await transport.handle_async_request(request)
                raise httpx.ReadTimeout("unknown registration result", request=request)
            return await transport.handle_async_request(request)

    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=LostRegistration(),
    )
    unused = PublicAPI(
        "http://unused",
        transport=httpx.MockTransport(lambda request: pytest.fail("no assets or Run may start")),
    )
    try:
        result = await execute_fixed_baseline(
            unused,
            unused,
            observer,
            project_id=str(uuid4()),
            environment_id=str(uuid4()),
            service_id=str(uuid4()),
            batch_key="unknown-registration",
            nonce="owned-unknown-registration-nonce",
            fixture_digest="a" * 64,
            builds=Builds(runner="a", target="b", fixture="a" * 64, verifier="o"),
            output_dir=tmp_path,
        )
        assert result.report.batch_verdict == "blocked" and result.report.exit_code == 2
        assert result.installation is None and result.evidence.cleanup_status == "completed"
        assert methods == (["PUT", "GET", "DELETE", "GET"] if sent else ["PUT", "GET"])
    finally:
        await observer.close()
        await unused.close()


@pytest.mark.parametrize("mode", ["drain", "reregister", "deadline", "budget"])
async def test_namespace_active_wait_is_bounded_and_pins_actual_registration(
    tmp_path: Path, mode: str
) -> None:
    business_app, observer_app = _fixture_apps(tmp_path)
    payload = {
        "nonce": "active-drain-owned-nonce-001",
        "fixture_digest": "a" * 64,
        "delay_ms": 200 if mode == "drain" else 1000,
    }
    path = "/selftest/batches/active-drain/scenarios/scenario"
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=observer_app),
    )
    business = PublicAPI(
        "http://target", api_prefix="", transport=httpx.ASGITransport(app=business_app)
    )
    await observer.request("PUT", path, payload)
    pending = asyncio.create_task(
        business.request(
            "POST", "/selftest/active-drain/scenario/request", {"marker": "owned-drain"}
        )
    )
    for _ in range(50):
        raw = await observer.object("GET", path + "/journal")
        if object_value(raw["metrics"])["active_count"] == 1:
            break
        await asyncio.sleep(0.005)
    else:
        pytest.fail("real business request never became active")
    reads = 0

    class ManagementRead(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal reads
            reads += 1
            if mode == "reregister" and reads == 2:
                await observer.request("DELETE", path)
                await observer.request("PUT", path, payload)
            return await httpx.ASGITransport(app=observer_app).handle_async_request(request)

    admitted = 0

    def reserve() -> None:
        nonlocal admitted
        if mode == "budget" and admitted >= 1:
            raise HarnessError("SYNTHETIC_MANAGEMENT_READ_BUDGET")
        admitted += 1

    reader = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=ManagementRead(),
    )
    try:
        operation = read_namespace_condition(
            reader,
            "active-drain",
            "scenario",
            nonce=payload["nonce"],
            fixture_digest=payload["fixture_digest"],
            wait_for_inactive=True,
            deadline=datetime.now(UTC) + timedelta(seconds=0.05 if mode == "deadline" else 2),
            reserve_request=reserve,
        )
        if mode == "drain":
            condition = await operation
            assert condition is not None
            assert (await observer.object("GET", path + "/journal"))["metrics"]["active_count"] == 0
            await observer.request("DELETE", path, condition.body())
        else:
            reason = {
                "reregister": "REGISTRATION_CHANGED",
                "deadline": "READ_TIMEOUT",
                "budget": "MANAGEMENT_READ_BUDGET",
            }[mode]
            with pytest.raises(HarnessError, match=reason):
                await operation
            assert (await observer.object("GET", path + "/journal"))["nonce"] == payload["nonce"]
        assert reads == admitted and admitted <= 12
    finally:
        await pending
        await reader.close()
        await observer.close()
        await business.close()
