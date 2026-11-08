"""External bridge behavioral boundaries; these checks do not stand in for deployment acceptance."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.io import HarnessError, PublicAPI  # noqa: E402
from scripts.selftest.product_agent_client import AgentIdentity, task_nonce  # noqa: E402
from scripts.selftest.product_setup import deployment_binding_id  # noqa: E402
from scripts.selftest.review_driver import HumanReviewDriver, PendingReview  # noqa: E402

from app.core.self_tests import SelfTestPrincipal  # noqa: E402
from app.schemas.self_tests import BuildIdentity  # noqa: E402


def test_updated_deployment_keeps_failed_installation_under_its_original_binding() -> None:
    builds = BuildIdentity(runner="a" * 64, target="a" * 64, fixture="b" * 64, verifier="c" * 64)
    original = deployment_binding_id("isolated-stack-1", builds)
    assert original == deployment_binding_id("isolated-stack-1", builds)
    assert original != deployment_binding_id("isolated-stack-2", builds)
    for field in ("runner", "target", "fixture", "verifier"):
        changed = builds.model_copy(update={field: "d" * 64})
        assert original != deployment_binding_id("isolated-stack-1", changed)


@pytest.mark.parametrize("review_mode", ["human", "ci_fixture"])
async def test_human_review_reads_real_receipts_without_approving_applying_or_publishing(
    tmp_path: Path,
    review_mode: Literal["human", "ci_fixture"],
) -> None:
    project, proposal, workflow, reviewer = (str(uuid4()) for _ in range(4))
    definition = {
        "nodes": [{"id": "request", "type": "api", "config": {"api_definition_id": "api-1"}}]
    }
    requests: list[httpx.Request] = []
    pending: list[PendingReview] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("visual-proposal"):
            data = {
                "proposal": {"source_fingerprint": "a" * 64, "project_id": project},
                "proposed_definition": definition,
            }
        elif request.url.path.endswith(f"/flow-specs/change-sets/{proposal}"):
            data = {
                "project_id": project,
                "source_fingerprint": "a" * 64,
                "review_status": "accepted",
                "materialized_workflow_id": workflow,
                "reviewed_by_id": reviewer,
                "applied_at": datetime.now(UTC).isoformat(),
            }
        elif "/mcp/write/" in request.url.path:
            return httpx.Response(404, json={"error": {"code": "MCP_CHANGE_SET_NOT_FOUND"}})
        elif request.url.path.endswith("/versions"):
            data = [
                {
                    "id": str(uuid4()),
                    "version": 1,
                    "definition": definition,
                    "fingerprint": "b" * 64,
                }
            ]
        else:
            data = {"id": workflow, "draft_definition": definition, "current_version": 1}
        return httpx.Response(200, json=data)

    async def on_pending(value: PendingReview) -> None:
        pending.append(value)

    api = PublicAPI("http://runner.invalid", transport=httpx.MockTransport(respond))
    try:
        result = await HumanReviewDriver(
            datetime.now(UTC) + timedelta(seconds=30), on_pending, review_mode=review_mode
        ).flow(
            api,
            project_id=project,
            reviewer_id=str(uuid4()),
            proposal_id=proposal,
            expected_definition=definition,
            expected_api_ids=("api-1",),
            output_dir=tmp_path,
        )
    finally:
        await api.close()
    assert len(pending) == 1 and pending[0].proposal_id == result.proposal.proposal_id
    assert result.proposal.review_mode == review_mode
    assert result.proposal.item_id is None
    assert str(result.proposal.reviewer_id) == reviewer
    assert len(requests) == 4


async def test_rejected_human_review_stops_without_materialization(tmp_path: Path) -> None:
    project, proposal = str(uuid4()), str(uuid4())
    definition = {
        "nodes": [{"id": "request", "type": "api", "config": {"api_definition_id": "api-1"}}]
    }

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path.endswith("visual-proposal"):
            return httpx.Response(
                200,
                json={
                    "proposal": {"source_fingerprint": "a" * 64},
                    "proposed_definition": definition,
                },
            )
        return httpx.Response(
            200,
            json={
                "project_id": project,
                "source_fingerprint": "a" * 64,
                "review_status": "rejected",
            },
        )

    async def pending(_: PendingReview) -> None:
        return None

    api = PublicAPI("http://runner.invalid", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(HarnessError, match="HUMAN_REVIEW_REJECTED"):
            await HumanReviewDriver(datetime.now(UTC) + timedelta(seconds=30), pending).flow(
                api,
                project_id=project,
                reviewer_id=str(uuid4()),
                proposal_id=proposal,
                expected_definition=definition,
                expected_api_ids=("api-1",),
                output_dir=tmp_path,
            )
    finally:
        await api.close()


def test_nonce_is_stable_per_task_and_never_reused_across_tasks(tmp_path: Path) -> None:
    first, second = uuid4(), uuid4()
    nonce = task_nonce(tmp_path, first)
    assert task_nonce(tmp_path, first) == nonce
    assert task_nonce(tmp_path, second) != nonce
    assert (tmp_path / str(first) / "nonce.json").stat().st_mode & 0o077 == 0
    assert set(json.loads((tmp_path / str(first) / "nonce.json").read_text())) == {"nonce"}


def test_signing_key_is_private_and_jwt_has_exact_deployment_audience(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    path = tmp_path / "agent-key.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    project, binding = uuid4(), uuid4()
    principal = SelfTestPrincipal(
        id="local-H",
        issuer="isolated-H",
        subject="harness",
        audience="selftest-only",
        public_key=public,
        allowed_project_ids=(project,),
        allowed_binding_ids=(binding,),
        capabilities=("install", "deterministic_mcp"),
    )
    identity = AgentIdentity(principal=principal, private_key_file=path)
    path.chmod(0o644)
    with pytest.raises(HarnessError, match="SIGNING_KEY_PERMISSIONS"):
        identity.token()
    path.chmod(0o600)
    token = identity.token()
    claims = jwt.decode(
        token, public, algorithms=["RS256"], issuer="isolated-H", audience="selftest-only"
    )
    assert claims["sub"] == "harness" and claims["exp"] - claims["iat"] == 900
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(token, public, algorithms=["RS256"], audience="other-project")


async def test_short_installation_lease_renews_before_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from scripts.selftest import product_agent_client as client

    from app.schemas.self_tests import AgentTaskResponse

    task = AgentTaskResponse.model_construct(
        task_kind="installation",
        task_id=uuid4(),
        project_id=uuid4(),
        lease_token="l" * 48,
        nonce="n" * 64,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    started, release = asyncio.Event(), asyncio.Event()
    waits: list[float] = []
    original_wait = asyncio.wait_for

    async def early_wait(awaitable: object, timeout: float) -> object:
        waits.append(timeout)
        if len(waits) == 1:
            awaitable.close()
            raise TimeoutError
        return await original_wait(awaitable, timeout=timeout)

    async def response(*_: object) -> dict[str, object]:
        started.set()
        await release.wait()
        return {}

    api = AsyncMock(spec=PublicAPI)
    api.object.side_effect = response
    monkeypatch.setattr(client.asyncio, "wait_for", early_wait)
    monkeypatch.setattr(client.AgentTaskResponse, "model_validate", lambda _: task)
    async with client.keep_lease(api, task):
        await started.wait()
        release.set()
    assert 0 < waits[0] <= 10
    assert "/installations/" in api.object.call_args.args[1]
    assert api.object.call_args.args[1].endswith("/lease")


async def test_agent_rechecks_owned_endpoints_before_credentials_or_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.selftest import product_agent
    from scripts.selftest.io import write_json
    from scripts.selftest.local_stack import StackBinding

    stack = StackBinding(
        project_name="flowtest-selftest-123456789abc",
        nonce="a" * 32,
        runner_url="http://127.0.0.1:43001",
        target_url="http://127.0.0.1:43002",
        observer_url="http://127.0.0.1:43003",
        private_subnet="172.27.9.0/24",
        candidate_image="candidate",
        candidate_image_digest="sha256:" + "1" * 64,
        fixture_image="fixture",
        fixture_image_digest="sha256:" + "2" * 64,
        source_digest="source",
        dependency_digest="dependencies",
        runner_container_id="a" * 64,
        target_container_id="b" * 64,
        observer_container_id="c" * 64,
        runner_volume="runner-data",
        target_volume="target-data",
    )
    write_json(tmp_path / "stack.json", stack)
    inspected = []

    def reject(actual: StackBinding, directory: Path) -> None:
        inspected.append((actual, directory))
        raise HarnessError("SELFTEST_CONTAINER_BUILD_MISMATCH")

    monkeypatch.setattr(product_agent, "verify_agent_endpoints", reject, raising=False)
    with pytest.raises(HarnessError, match="CONTAINER_BUILD_MISMATCH"):
        await product_agent.poll(
            stack_directory=tmp_path,
            state_directory=tmp_path / "state",
            config_path=tmp_path / "missing-private-config.json",
            role="observer",
        )
    assert inspected == [(stack, tmp_path)]
    assert not (tmp_path / "state").exists()
