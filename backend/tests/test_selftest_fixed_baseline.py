"""Exercise frozen native graphs via public installation APIs and the real runner.

The synthetic target runs in ASGI; the Docker stack remains separate acceptance.
"""

from __future__ import annotations

import importlib
import json
import shutil
import sys
import types
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.main import app
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import Builds, canonical_digest  # noqa: E402
from scripts.selftest.fixed_baseline import (  # noqa: E402
    PACK_DIRECTORY,
    _mutate,
    _wire_matches,
    execute_fixed_baseline,
    install_fixed_baseline,
    load_core_pack,
)
from scripts.selftest.io import HarnessError, PublicAPI  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402


def _fixture_apps(tmp_path: Path) -> tuple[FastAPI, FastAPI]:
    # A distinct package avoids importing mock-target/app as the candidate's app.
    package = types.ModuleType("flowtest_fixed_fixture")
    package.__path__ = [str(ROOT / "mock-target" / "app")]
    sys.modules[package.__name__] = package
    fixture = importlib.import_module("flowtest_fixed_fixture.selftest")
    storage = importlib.import_module("flowtest_fixed_fixture.selftest_journal")
    store = storage.FixtureStore(tmp_path / "journal.sqlite3")
    store.start_epoch()
    business = FastAPI()
    business.mount("/selftest", fixture.create_business_app(store))
    return business, fixture.observer_app(store, "synthetic-observer-token-only-for-tests-0001")


def test_fixed_pack_rejects_changed_golden_expectations(tmp_path: Path) -> None:
    directory = tmp_path / "core-v1"
    shutil.copytree(PACK_DIRECTORY, directory)
    pack = load_core_pack(directory)
    assert len(pack.expectations) == 8
    assert sum(len(item.wire) for item in pack.fixtures) == 18
    expectations = directory / "expectations.json"
    changed = json.loads(expectations.read_text())
    changed["expectations"][1]["expected"]["error_code"] = "NETWORK_TIMEOUT"
    expectations.write_text(json.dumps(changed))
    with pytest.raises(HarnessError, match="PACK_DIGEST_MISMATCH"):
        load_core_pack(directory)


class RunningAPI(PublicAPI):
    def __init__(self, context: TaskingTestContext, token: str) -> None:
        super().__init__("http://test", token, transport=httpx.ASGITransport(app=app))
        self.context = context
        self.posts: list[str] = []

    async def object(self, method: str, path: str, payload=None, *, idempotency_key=None):
        result = await super().object(method, path, payload, idempotency_key=idempotency_key)
        if method == "POST":
            self.posts.append(path)
        if method == "POST" and "/test-plans/" in path and path.endswith("/runs"):
            await PlanRunCoordinator(self.context.session_maker, self.context.events).run(
                UUID(result["id"])
            )
        return result


async def _dependencies(api: PublicAPI) -> tuple[str, str, str]:
    project = await api.object("POST", "/projects", {"name": "固定包隔离测试"})
    root = f"/projects/{project['id']}"
    environment = await api.object(
        "POST",
        root + "/environments",
        {"name": "合成目标", "base_url": "http://fixed-fixture.example", "classification": "test"},
    )
    service = await api.object(
        "POST", root + "/services", {"name": "固定合成目标", "service_key": "fixed_fixture"}
    )
    await api.object(
        "POST",
        root + f"/environments/{environment['id']}/service-endpoints",
        {
            "service_id": service["id"],
            "variant": "default",
            "base_url": "http://fixed-fixture.example",
        },
    )
    await api.object(
        "PATCH", root + f"/environments/{environment['id']}", {"default_service_id": service["id"]}
    )
    return str(project["id"]), str(environment["id"]), str(service["id"])


@pytest.mark.asyncio
async def test_fixed_native_pack_installs_and_runs_all_eight_frozen_scenarios(
    tasking_context: TaskingTestContext,
    tmp_path: Path,
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    project, environment, service = await _dependencies(api)
    token = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "固定证据读取", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", str(token["token"]), transport=httpx.ASGITransport(app=app))
    business, admin = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=admin),
    )
    business_client = httpx.AsyncClient(
        base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
    )
    calls: list[tuple[str, Any]] = []

    async def target(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/ST-CORE-timeout/request"):
            assert request.extensions["timeout"]["read"] == 1
        # The real scheduler bounds this ASGI request at 1s. The fixture's 2s
        # delay therefore exercises NODE_TIMEOUT without injecting an error.
        reply = await business_client.request(
            request.method, request.url.path, content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(reply.status_code, content=reply.content, headers=dict(reply.headers))

    output = tmp_path / "fixed"
    try:
        with respx.mock as routes:
            routes.route(host="fixed-fixture.example").mock(side_effect=target)
            result = await execute_fixed_baseline(
                api,
                reader,
                observer,
                project_id=project,
                environment_id=environment,
                service_id=service,
                batch_key="fixed-test",
                nonce="fixed-test-nonce-001",
                fixture_digest="a" * 64,
                builds=Builds(
                    runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
                ),
                output_dir=output,
            )
        assert result.report.batch_verdict == "passed", result.report.model_dump_json(indent=2)
        assert len(result.evidence.scenarios) == 8
        assert [item.execution.status for item in result.evidence.scenarios] == [
            "passed",
            "failed",
            "failed",
            "passed",
            "passed",
            "passed",
            "passed",
            "passed",
        ]
        assert len(calls) == 18
        echo = [body["value"] for path, body in calls if "echo-boundaries" in path]
        assert [canonical_digest(value) for value in echo] == [
            canonical_digest(value) for value in [0, False, None, "", "中文"]
        ]
        assert (output / "execution.junit.xml").read_text().count("<failure") == 2
        assert "<failure" not in (output / "verification.junit.xml").read_text()
        assert all(item.cleanup_status == "completed" for item in result.evidence.scenarios)
        # A second installer call reuses confirmed mutations and verifies real
        # immutable versions instead of creating duplicate assets.
        posts = len(api.posts)
        resumed = await install_fixed_baseline(
            api,
            project_id=project,
            environment_id=environment,
            service_id=service,
            batch_key="fixed-test",
            nonce="fixed-test-nonce-001",
            output_dir=output,
        )
        assert resumed == result.installation
        assert len(api.posts) == posts + 1  # readonly package preview POST only
        # The Observer cannot accept a boolean in place of the frozen integer 0.
        first = result.evidence.scenarios[0]
        assert first.journal is not None
        entry = first.journal.entries[0]
        assert entry.request_body is not None
        changed_entry = entry.model_copy(
            update={"request_body": entry.request_body.model_copy(update={"value": False})}
        )
        altered = first.model_copy(
            update={
                "journal": first.journal.model_copy(
                    update={"entries": (changed_entry, *first.journal.entries[1:])}
                ),
                "postcondition_matched": False,
            }
        )
        assert not _wire_matches(load_core_pack().fixtures[0], altered)
        changed = result.evidence.model_copy(
            update={"scenarios": (altered, *result.evidence.scenarios[1:])}
        )
        assert verify_batch(result.manifest, changed).batch_verdict != "passed"
    finally:
        await business_client.aclose()
        await observer.close()
        await reader.close()
        await api.close()


@pytest.mark.asyncio
async def test_unknown_mutation_is_recorded_and_never_blindly_repeated(tmp_path: Path) -> None:
    calls = 0

    def unknown(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("unknown completion", request=request)

    api = PublicAPI("http://test", transport=httpx.MockTransport(unknown))
    try:
        with pytest.raises(httpx.ReadTimeout):
            await _mutate(api, tmp_path, "api-0", "/projects/project/apis", {"name": "synthetic"})
        with pytest.raises(HarnessError, match="UNKNOWN_RESULT_NEEDS_REVIEW"):
            await _mutate(api, tmp_path, "api-0", "/projects/project/apis", {"name": "synthetic"})
        assert calls == 1
        assert (
            json.loads((tmp_path / "mutation-receipts/api-0.json").read_text())["status"]
            == "pending"
        )
    finally:
        await api.close()


@pytest.mark.asyncio
async def test_unknown_fixture_registration_without_readback_proof_never_guesses_delete(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    methods: list[str] = []

    def observer_failure(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT":
            raise httpx.ReadTimeout("unknown fixture registration", request=request)
        return httpx.Response(204)

    observer = PublicAPI(
        "http://observer", api_prefix="", transport=httpx.MockTransport(observer_failure)
    )
    api = PublicAPI(
        "http://unused", transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    try:
        result = await execute_fixed_baseline(
            api,
            api,
            observer,
            project_id=str(uuid4()),
            environment_id=str(uuid4()),
            service_id=str(uuid4()),
            batch_key="fixed-error",
            nonce="fixed-failure-nonce-001",
            fixture_digest="a" * 64,
            builds=Builds(
                runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
            ),
            output_dir=tmp_path,
        )
        assert result.report.batch_verdict == "blocked"
        assert result.report.exit_code == 2
        assert result.installation is None
        assert result.evidence.cleanup_status == "failed"
        assert len(result.evidence.scenarios) == 8
        assert methods == ["PUT", "GET"]
        assert (tmp_path / "verification.junit.xml").is_file()
        assert (tmp_path / "execution.junit.xml").read_text().count("<skipped") == 8
    finally:
        await api.close()
        await observer.close()


async def test_fixed_observer_deadline_cancels_actual_queued_plan_before_cleanup(
    tasking_context: TaskingTestContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = PublicAPI(
        "http://test",
        headers["Authorization"].split(" ")[1],
        transport=httpx.ASGITransport(app=app),
    )
    project, environment, service = await _dependencies(api)
    token = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "超时清理只读证据", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", str(token["token"]), transport=httpx.ASGITransport(app=app))
    _, admin = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=admin),
    )

    async def deadline(*arguments: object) -> None:
        raise HarnessError("SELFTEST_OBSERVER_DEADLINE_EXCEEDED")

    monkeypatch.setattr("scripts.selftest.fixed_baseline.wait_plan", deadline)
    try:
        result = await execute_fixed_baseline(
            api,
            reader,
            observer,
            project_id=project,
            environment_id=environment,
            service_id=service,
            batch_key="fixed-deadline",
            nonce="fixed-deadline-nonce",
            fixture_digest="a" * 64,
            builds=Builds(
                runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
            ),
            output_dir=tmp_path / "fixed-deadline",
        )
        assert result.report.exit_code != 0
        assert result.evidence.observer_error == "SELFTEST_OBSERVER_DEADLINE_EXCEEDED"
        cleanup = json.loads((tmp_path / "fixed-deadline/cleanup.json").read_text())
        assert cleanup["status"] == "completed"
        assert cleanup["plan"]["cancel_requested"] is True
        assert all(item["status"] == "completed" for item in cleanup["fixtures"])
        raw = await reader.object(
            "GET", f"/ci/projects/{project}/test-plan-runs/{cleanup['plan']['run_id']}"
        )
        assert raw["status"] == "cancelled"
        assert {item["status"] for item in raw["items"]} == {"cancelled"}
        assert all(item["attempts"] == 0 for item in raw["items"])
    finally:
        await api.close()
        await reader.close()
        await observer.close()
