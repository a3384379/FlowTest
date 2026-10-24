"""Public-API ASGI integration for frozen extended native graphs.

These tests exercise the real candidate runner, not a deployment profile claim.
"""

from __future__ import annotations

import sys
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

from scripts.selftest.contracts import Builds  # noqa: E402
from scripts.selftest.extended_pack import load_extended_pack  # noqa: E402
from scripts.selftest.fixed_baseline import execute_fixed_baseline, load_core_pack  # noqa: E402
from scripts.selftest.io import PublicAPI  # noqa: E402


def test_extended_pack_preserves_exact_old_pack_and_bounded_frozen_goldens() -> None:
    original = load_core_pack()
    pack = load_extended_pack()
    assert len(original.expectations) == 8
    assert len(pack.expectations) == 19
    assert pack.manifest.pack_id == "extended-v1"
    assert sum(len(fixture.wire) for fixture in pack.fixtures) == 31
    assert all(
        item.expected.error_code and item.expected.node_id and item.expected.phase
        for item in pack.expectations
        if item.expected.execution_status == "failed"
    )
    assert (
        sum(int(item.definition["run_policy"]["request_budget"]) for item in pack.workflows) <= 500
    )


@pytest.mark.asyncio
async def test_extended_native_pack_public_api_and_real_engine(
    tasking_context: TaskingTestContext, tmp_path: Path
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    project, environment, service = await _dependencies(api)
    token = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "扩展证据", "scopes": ["read:execution"]},
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

    async def forward(request: httpx.Request) -> httpx.Response:
        response = await target.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

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
                batch_key="extended-test",
                nonce="extended-test-nonce-001",
                fixture_digest="a" * 64,
                builds=Builds(
                    runner="candidate", target="candidate", fixture="a" * 64, verifier="observer"
                ),
                output_dir=tmp_path / "extended",
                pack=load_extended_pack(),
            )
        assert result.report.batch_verdict == "passed", result.report.model_dump_json(indent=2)
        assert len(result.evidence.scenarios) == 19
        assert all(item.cleanup_status == "completed" for item in result.evidence.scenarios)
    finally:
        await target.aclose()
        await observer.close()
        await reader.close()
        await api.close()
