"""Real SDK/native passed counterexamples must fail independent semantic review."""

from __future__ import annotations

import copy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from test_selftest_bad_targets import _actual_loopback, _inputs
from test_selftest_fixed_baseline import RunningAPI, _fixture_apps
from test_tasking_api import TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.main import app

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import Builds, canonical_digest  # noqa: E402
from scripts.selftest.io import PublicAPI  # noqa: E402
from scripts.selftest.local_stack import StackBinding  # noqa: E402
from scripts.selftest.mcp_protocol_runner import stdio_protocol  # noqa: E402
from scripts.selftest.semantic_contracts import SemanticEvidence, SemanticManifest  # noqa: E402
from scripts.selftest.semantic_pack import execute_semantic_pack  # noqa: E402
from scripts.selftest.semantic_verify import verify_semantic  # noqa: E402


def _binding() -> StackBinding:
    return StackBinding(
        project_name="flowtest-selftest-" + "1" * 12,
        nonce="2" * 32,
        runner_url="http://runner.test",
        target_url="http://target.test",
        observer_url="http://observer.test",
        private_subnet="172.27.9.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "a" * 64,
        fixture_image="fixture",
        fixture_image_digest="sha256:" + "b" * 64,
        source_digest="c" * 64,
        dependency_digest="d" * 64,
        runner_container_id="e" * 64,
        target_container_id="f" * 64,
        observer_container_id="0" * 64,
        runner_volume="owned-runner",
        target_volume="owned-target",
    )


@pytest.mark.asyncio
async def test_actual_sdk_publishes_five_native_passed_artifacts_but_rubric_rejects_four(
    tasking_context: TaskingTestContext,
    tmp_path: Path,
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    installation, token, reader_token = await _inputs(api)
    reader = PublicAPI("http://test", reader_token, transport=httpx.ASGITransport(app=app))
    business, admin = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=admin),
    )
    target = httpx.AsyncClient(
        base_url="http://fixed-fixture.example",
        transport=httpx.ASGITransport(app=business),
    )
    calls = []

    async def forward(request):
        calls.append((request.method, request.url.path))
        response = await target.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code, content=response.content, headers=dict(response.headers)
        )

    binding = _binding()
    try:
        async with (
            _actual_loopback() as base,
            stdio_protocol(
                python=Path(sys.executable),
                backend=ROOT / "backend",
                api_url=base,
                token=token,
                batch_key="semantic-sdk",
                output_dir=tmp_path / "sdk",
            ) as client,
        ):
            with respx.mock(assert_all_called=False, assert_all_mocked=False) as routes:
                routes.route(host="fixed-fixture.example").mock(side_effect=forward)
                manifest, evidence, report = await execute_semantic_pack(
                    client,
                    api,
                    reader,
                    observer,
                    installation=installation,
                    binding=binding,
                    batch_key="semantic-sdk",
                    nonce="semantic-sdk-fixture-nonce",
                    builds=Builds(
                        runner=binding.candidate_image_digest,
                        target=binding.candidate_image_digest,
                        fixture="b" * 64,
                        verifier="independent-o",
                    ),
                    output_dir=tmp_path / "round",
                    deadline=datetime.now(UTC) + timedelta(seconds=600),
                )
        assert report.exit_code == 2, report.model_dump_json(indent=2)
        assert report.reason_codes == ("SEMANTIC_OWNED_DISPOSAL_PENDING",)
        assert [row.raw_status for row in report.scenarios] == ["passed"] * 5
        assert [row.source_rejected for row in report.scenarios] == [False, True, True, True, True]
        assert all(not row.reason_codes for row in report.scenarios)
        assert len(calls) == 5
        _tamper(manifest, evidence)
    finally:
        await target.aclose()
        await reader.close()
        await observer.close()
        await api.close()


def _tamper(manifest: SemanticManifest, evidence: SemanticEvidence) -> None:
    for change in (
        "remove_row",
        "zero_requests",
        "reuse_execution",
        "raw_failed",
        "wrong_binding",
        "source_expected",
        "missing_call",
    ):
        value = copy.deepcopy(evidence.model_dump(mode="json"))
        frozen = copy.deepcopy(manifest.model_dump(mode="json"))
        if change == "remove_row":
            value["observations"].pop()
        elif change == "zero_requests":
            value["journal"]["request_count"] = 0
        elif change == "reuse_execution":
            value["observations"][1]["execution"]["id"] = value["observations"][0]["execution"][
                "id"
            ]
        elif change == "raw_failed":
            value["observations"][1]["execution"]["status"] = "failed"
        elif change == "wrong_binding":
            value["observations"][1]["run"]["target_snapshot_digest"] = "0" * 64
        elif change == "source_expected":
            frozen["artifacts"][1]["design"]["oracles"][0]["expected"] = 500
            value["manifest_digest"] = canonical_digest(frozen)
        else:
            value["tool_receipts"].pop()
        result = verify_semantic(
            SemanticManifest.model_validate(frozen), SemanticEvidence.model_validate(value)
        )
        assert result.exit_code == 1, (change, result.model_dump_json(indent=2))
