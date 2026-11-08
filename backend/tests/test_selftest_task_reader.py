"""The product O has a lease-bound reader, never an A project-wide read/capture JWT."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from test_selftest_product_api import ProductContext, _fixed
from test_selftest_product_api import product as product
from test_selftest_task_evidence import _claim
from test_tasking_api import tasking_context as tasking_context

from app.main import app
from app.schemas.self_tests import AgentTaskResponse

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.bootstrap import Installation
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.product_agent_client import AgentIdentity, AgentRuntime, ProductAgentConfig
from scripts.selftest.product_evidence import TaskEvidenceReader


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.inner = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return await self.inner.handle_async_request(request)


async def _reader(
    product: ProductContext,
) -> tuple[TaskEvidenceReader, AgentTaskResponse, RecordingTransport]:
    batch, nonce = await _fixed(product)
    task = AgentTaskResponse.model_validate(await _claim(product, batch, nonce))
    transport = RecordingTransport()
    reader = TaskEvidenceReader(
        "http://test",
        product.machine("o")["Authorization"].removeprefix("Bearer "),
        task,
        transport=transport,
    )
    return reader, task, transport


async def test_real_asgi_reader_maps_ci_projection_and_rejects_other_paths_before_send(
    product: ProductContext,
) -> None:
    reader, task, transport = await _reader(product)
    assert task.batch is not None
    root = f"/ci/projects/{task.project_id}"
    try:
        data = await reader.object(
            "GET", root + f"/test-plan-runs/{task.batch.plan_run_ids[0]}?page=1&page_size=1"
        )
        assert data["run_id"] == str(task.batch.plan_run_ids[0]) and data["status"] == "queued"
        assert transport.paths == [
            f"/api/v1/agent/projects/{task.project_id}/self-tests/runs/{task.task_id}/evidence/test-plan-runs/{task.batch.plan_run_ids[0]}"
        ]
        for path in (
            root + f"/test-plan-runs/{uuid4()}",
            root.replace(str(task.project_id), str(uuid4()))
            + "/test-plan-runs/"
            + str(task.batch.plan_run_ids[0]),
            f"/projects/{task.project_id}/workflow-executions/{uuid4()}",
            root + f"/test-plan-runs/{task.batch.plan_run_ids[0]}?page_size=101",
            root + f"/test-plan-runs/{task.batch.plan_run_ids[0]}?page=1&page=2",
            "https://other.invalid" + root + f"/test-plan-runs/{task.batch.plan_run_ids[0]}",
        ):
            with pytest.raises(HarnessError):
                await reader.object("GET", path)
        with pytest.raises(HarnessError, match="READONLY"):
            await reader.request("POST", root + f"/test-plan-runs/{task.batch.plan_run_ids[0]}")
        with pytest.raises(HarnessError, match="READONLY"):
            await reader.upload_synthetic("/projects/irrelevant/files", "synthetic.json", b"{}")
        assert len(transport.paths) == 1
    finally:
        await reader.close()


async def test_reader_uses_task_deadline_and_request_budget_without_broad_credential_fallback(
    product: ProductContext,
) -> None:
    reader, task, transport = await _reader(product)
    assert task.batch is not None
    path = f"/ci/projects/{task.project_id}/test-plan-runs/{task.batch.plan_run_ids[0]}"
    reader._remaining_requests = 1
    try:
        await reader.object("GET", path)
        with pytest.raises(HarnessError, match="BUDGET_EXHAUSTED"):
            await reader.object("GET", path)
        reader._remaining_requests = 1
        reader._deadline = datetime.now(UTC) - timedelta(seconds=1)
        with pytest.raises(HarnessError, match="BUDGET_EXHAUSTED"):
            await reader.object("GET", path)
        assert len(transport.paths) == 1
    finally:
        await reader.close()


def test_role_runtime_schema_cannot_carry_a_reader_or_capture_token() -> None:
    assert "reader_token" not in AgentRuntime.model_fields
    assert "capture_viewer_token" not in AgentRuntime.model_fields
    assert AgentRuntime.model_fields["fixture_management_token"].repr is False


async def test_observer_poll_uses_only_private_role_runtime_without_opening_admin_environment(
    product: ProductContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.selftest import local_stack, product_agent
    from scripts.selftest.run import _verifier_digest

    stack = StackBinding(
        project_name="flowtest-selftest-" + "1" * 12,
        nonce="2" * 32,
        runner_url="http://runner.test",
        target_url="http://target.test",
        observer_url="http://observer.test",
        private_subnet="172.18.0.0/24",
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
    installed = Installation(
        binding_nonce=stack.nonce,
        organization_id=uuid4(),
        project_id=product.project_id,
        reviewer_id=uuid4(),
        reviewer_email="reviewer@example.test",
        mcp_account_id=uuid4(),
        target_project_id=product.binding.target_project_id,
        target_user_id=product.binding.target_user_id,
        target_email="target@example.test",
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
    )
    builds = product.binding.builds.model_copy(
        update={
            "runner": stack.candidate_image_digest,
            "target": stack.candidate_image_digest,
            "fixture": "b" * 64,
            "verifier": _verifier_digest(),
        }
    )
    identities = {
        role: AgentIdentity(principal=principal, private_key_file=tmp_path / f"{role}.pem")
        for role, principal in zip(("h", "o"), product.config.principals, strict=True)
    }
    config = ProductAgentConfig(
        project_id=product.project_id,
        binding=product.binding.model_copy(update={"builds": builds}),
        harness=identities["h"],
        observer=identities["o"],
        host_id="deterministic-test-host",
    )
    now = datetime.now(UTC)
    runtime = AgentRuntime(
        role="observer",
        installation=installed,
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
        fixture_management_token="fixture-private-" + "f" * 32,
        target_viewer_token="b-private-viewer",
    )
    forbidden = runtime.model_copy(update={"target_cleanup_token": "h-only-target-editor"})
    with pytest.raises(HarnessError, match="SELFTEST_OBSERVER_WRITE_CREDENTIAL_FORBIDDEN"):
        forbidden.bootstrap_result("observer", stack)
    write_json(tmp_path / "stack.json", stack)
    write_json(tmp_path / "agent-config.json", config)
    write_json(tmp_path / "observer-runtime.json", runtime)
    assert (tmp_path / "observer-runtime.json").stat().st_mode & 0o077 == 0
    assert runtime.fixture_management_token not in repr(runtime)
    assert runtime.target_viewer_token not in repr(runtime)
    opened: list[str] = []
    requests: list[tuple[str, str]] = []

    def public_file(path: Path) -> dict:
        opened.append(path.name)
        assert path.name in {"stack.json", "agent-config.json", "observer-runtime.json"}
        return read_json(path)

    def forbidden_environment(*_: object) -> dict:
        pytest.fail("the role process attempted to read all deployment secrets")

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json={"installations": [], "batches": []})

    monkeypatch.setattr(product_agent, "read_json", public_file)
    endpoint_checks: list[tuple[StackBinding, Path]] = []
    monkeypatch.setattr(
        product_agent,
        "verify_agent_endpoints",
        lambda actual, directory: endpoint_checks.append((actual, directory)),
    )
    monkeypatch.setattr(local_stack, "private_environment", forbidden_environment)
    monkeypatch.setattr(
        product_agent,
        "agent_api",
        lambda *_: PublicAPI("http://runner.test", transport=httpx.MockTransport(respond)),
    )
    assert not (tmp_path / "private.env").exists()
    assert (
        await product_agent.poll(
            stack_directory=tmp_path,
            state_directory=tmp_path / "state",
            config_path=tmp_path / "agent-config.json",
            role="observer",
        )
        == 0
    )
    assert opened == ["stack.json", "agent-config.json", "observer-runtime.json"]
    assert endpoint_checks == [(stack, tmp_path)]
    assert requests == [
        ("POST", f"/api/v1/agent/projects/{product.project_id}/self-tests/register"),
        ("GET", f"/api/v1/agent/projects/{product.project_id}/self-tests/tasks"),
    ]
