"""Actual public API/native engine with synthetic ASGI fixtures; no deployment claim."""

import base64
import sys
from pathlib import Path

import httpx
import pytest
import respx
from test_artifacts_and_auth_api import MemoryObjectStorage
from test_selftest_engine_dependencies import DependencyContext
from test_selftest_engine_dependencies import dependency_context as dependency_context
from test_tasking_api import tasking_context as tasking_context

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import Builds, canonical_digest  # noqa: E402
from scripts.selftest.fixed_baseline import execute_fixed_baseline  # noqa: E402
from scripts.selftest.s5_native import bind_s5_pack, observe_s5_artifact  # noqa: E402
from scripts.selftest.verify import verify_batch  # noqa: E402


@pytest.mark.asyncio
async def test_synthetic_file_and_cookie_barrier_use_native_case_suite_plan_and_independent_o(
    dependency_context: DependencyContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = dependency_context
    monkeypatch.setattr("app.services.artifacts.object_storage", MemoryObjectStorage())
    artifact = await context.api.upload_synthetic_binary(f"/projects/{context.project}/files")
    pack = bind_s5_pack(str(artifact["id"]), context.project, tmp_path / "bound", None)

    async def forward(request: httpx.Request) -> httpx.Response:
        # Forward exact engine headers; no shared test-client cookie jar may supply them.
        response = await context.target.send(
            httpx.Request(
                request.method,
                request.url,
                content=request.content,
                headers=dict(request.headers),
            )
        )
        context.target.cookies.clear()
        return httpx.Response(
            response.status_code, content=response.content, headers=response.headers
        )

    async def enrich(installed, observations):
        return await observe_s5_artifact(context.api, pack, installed, observations)

    with respx.mock as routes:
        routes.route(host="fixed-fixture.example").mock(side_effect=forward)
        result = await execute_fixed_baseline(
            context.api,
            context.reader,
            context.observer,
            project_id=context.project,
            environment_id=context.environment,
            service_id=context.service,
            batch_key="s5-native-asgi",
            nonce="s5-native-nonce-0001",
            fixture_digest="a" * 64,
            builds=Builds(runner="unit", target="unit", fixture="a" * 64, verifier="unit"),
            output_dir=tmp_path / "run",
            pack=pack,
            enrich_observations=enrich,
        )
    assert result.report.exit_code == 0, result.report.model_dump(mode="json")
    assert len(result.report.scenarios) == 3
    assert all(s.observed_status == "passed" for s in result.report.scenarios)
    original = canonical_digest(result.evidence.model_dump(mode="json"))
    first = result.evidence.scenarios[0]
    assert first.synthetic_artifact is not None
    corrupt = first.synthetic_artifact.model_copy(
        update={"content_base64": base64.b64encode(b"different-bytes").decode()}
    )
    evidence = result.evidence.model_copy(
        update={
            "scenarios": (
                first.model_copy(update={"synthetic_artifact": corrupt}),
                *result.evidence.scenarios[1:],
            )
        }
    )
    assert verify_batch(result.manifest, evidence).exit_code != 0
    cookie = result.evidence.scenarios[2]
    assert cookie.journal is not None
    entries = list(cookie.journal.entries)
    index = next(
        i
        for i, e in enumerate(entries)
        if e.synthetic_cookie and e.synthetic_cookie.stage == "check"
    )
    entry = entries[index]
    entries[index] = entry.model_copy(
        update={"synthetic_cookie": entry.synthetic_cookie.model_copy(update={"value": "wrong"})}
    )
    altered = cookie.model_copy(
        update={"journal": cookie.journal.model_copy(update={"entries": tuple(entries)})}
    )
    evidence = result.evidence.model_copy(
        update={"scenarios": (*result.evidence.scenarios[:2], altered)}
    )
    assert verify_batch(result.manifest, evidence).exit_code != 0
    assert canonical_digest(result.evidence.model_dump(mode="json")) == original
