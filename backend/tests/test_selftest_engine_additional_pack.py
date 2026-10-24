"""New engine goldens through public APIs; ASGI counters are not deployment receipts."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
import respx
from test_selftest_fixed_baseline import RunningAPI, _dependencies, _fixture_apps
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import Builds, canonical_digest  # noqa: E402
from scripts.selftest.fixed_baseline import execute_fixed_baseline, load_core_pack  # noqa: E402
from scripts.selftest.io import PublicAPI  # noqa: E402

PACK = ROOT / "selftest/packs/engine-additional-v1"


@dataclass
class TargetCounters:
    active: dict[str, int] = field(default_factory=dict)
    peak: dict[str, int] = field(default_factory=dict)
    completed: dict[str, int] = field(default_factory=dict)
    cancelled: dict[str, int] = field(default_factory=dict)

    async def send(self, client: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
        scenario = request.url.path.split("/")[-2]
        self.active[scenario] = self.active.get(scenario, 0) + 1
        self.peak[scenario] = max(self.peak.get(scenario, 0), self.active[scenario])
        try:
            response = await client.request(
                request.method,
                request.url.raw_path.decode(),
                content=request.content,
                headers=dict(request.headers),
            )
            self.completed[scenario] = self.completed.get(scenario, 0) + 1
            return httpx.Response(
                response.status_code, content=response.content, headers=dict(response.headers)
            )
        except asyncio.CancelledError:
            self.cancelled[scenario] = self.cancelled.get(scenario, 0) + 1
            raise
        finally:
            self.active[scenario] -= 1


def test_additional_pack_preserves_frozen_19_and_predeclares_deployment_gaps() -> None:
    original = load_core_pack(ROOT / "selftest/packs/extended-v1")
    pack = load_core_pack(PACK)
    assert original.digest == "8200b66735e0d8b23cc21016fc57612181981a7c9f8e73a5cdc2fd70f7578df4"
    assert len(original.expectations) == 19
    assert pack.manifest.pack_version == "1.1.0"
    assert len(pack.expectations) == 11
    assert sum(len(item.wire) for item in pack.fixtures) == 24
    requirements = json.loads((PACK / "acceptance-requirements.json").read_text())
    assert requirements["pack_digest"] == pack.digest
    assert requirements["deployment_status"] == "not_run"
    assert (
        sum(
            int(item.definition["run_policy"]["request_budget"])
            + int(item.definition["run_policy"]["cleanup_request_budget"])
            for item in pack.workflows
        )
        <= 500
    )


def _base_scenarios():
    pack = load_core_pack(PACK)
    scenarios = pack.manifest.scenario_ids[:9]
    manifest = pack.manifest.model_copy(update={"scenario_ids": scenarios})
    return pack.model_copy(
        update={
            "manifest": manifest,
            "digest": canonical_digest(manifest.model_dump(mode="json")),
            "apis": pack.apis[:9],
            "workflows": pack.workflows[:9],
            "expectations": pack.expectations[:9],
            "fixtures": pack.fixtures[:9],
        }
    )


@pytest.mark.asyncio
async def test_additional_pack_real_native_limits_finally_nested_signals_and_target_peak(
    tasking_context: TaskingTestContext, tmp_path: Path
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    project, environment, service = await _dependencies(api)
    token = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "附加引擎证据", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", str(token["token"]), transport=httpx.ASGITransport(app=app))
    business, management = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=management),
    )
    target = httpx.AsyncClient(
        base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
    )
    counters = TargetCounters()

    async def forward(request: httpx.Request) -> httpx.Response:
        return await counters.send(target, request)

    try:
        with respx.mock as routes:
            routes.route(host="fixed-fixture.example").mock(side_effect=forward)
            result = await execute_fixed_baseline(
                api,
                reader,
                observer,
                project_id=project,
                environment_id=environment,
                service_id=service,
                batch_key="additional-engine-test",
                nonce="additional-engine-nonce-001",
                fixture_digest="a" * 64,
                builds=Builds(
                    runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
                ),
                output_dir=tmp_path / "additional",
                pack=_base_scenarios(),
            )
        assert result.report.batch_verdict == "passed", result.report.model_dump_json(indent=2)
        observations = {item.scenario_id: item for item in result.evidence.scenarios}
        parallel = "ST-ADD-parallel-bound"
        assert counters.peak[parallel] == 2
        assert counters.completed[parallel] == 4
        assert counters.active[parallel] == 0
        limited = observations["ST-ADD-workflow-time-budget"].execution
        slow = next(item for item in limited.nodes if item.node_id == "slow_request")
        assert (limited.status, limited.main_status) == ("cancelled", "cancelled")
        assert (slow.status, slow.phase, slow.attempts, slow.error_code) == (
            "cancelled",
            "main",
            1,
            None,
        )
        assert counters.cancelled["ST-ADD-workflow-time-budget"] == 1
        assert counters.completed.get("ST-ADD-workflow-time-budget", 0) == 0
        budget = observations["ST-ADD-request-budget"].execution
        forbidden = next(item for item in budget.nodes if item.node_id == "forbidden_second")
        assert forbidden.attempts == 0
        assert forbidden.error_code == "REQUEST_BUDGET_EXHAUSTED"
        assert observations["ST-ADD-request-budget"].journal.request_count == 1
        assert all(item.cleanup_status == "completed" for item in result.evidence.scenarios)
        (tmp_path / "additional/independent-target-unit-counters.json").write_text(
            json.dumps(
                {
                    "kind": "asgi_only_not_deployment_receipt",
                    "peak": counters.peak,
                    "completed": counters.completed,
                    "cancelled": counters.cancelled,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await target.aclose()
        await observer.close()
        await reader.close()
        await api.close()
