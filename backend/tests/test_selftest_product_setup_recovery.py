"""Fresh product H directories reuse one actor through real ASGI public APIs.

Docker verification/configuration, bootstrap provisioning and the independent B
cleanup actor are isolated scaffolding; service-account requests are not mocked.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from test_selftest_ci_runner_lineage import binding
from test_selftest_native_api_security import SecurityWorld, login, payload
from test_selftest_native_api_security import world as world

from app.core.config import settings
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest import product_mcp_identity as identity_module  # noqa: E402
from scripts.selftest import product_setup as subject  # noqa: E402
from scripts.selftest.bootstrap import BootstrapResult, Credentials, Installation  # noqa: E402
from scripts.selftest.io import HarnessError, PublicAPI, read_json, write_json  # noqa: E402
from scripts.selftest.local_stack import StackBinding  # noqa: E402
from scripts.selftest.product_agent_client import AgentRuntime  # noqa: E402


class ObservedPublicAPI(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, int]] = []
        self.delegate = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        self.lose_create_response = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.delegate.handle_async_request(request)
        self.requests.append((request.method, request.url.path, response.status_code))
        if self.lose_create_response and request.method == "POST" and response.status_code == 201:
            raise httpx.ReadError("synthetic lost acknowledged create", request=request)
        return response


@dataclass
class RecoveryWorld:
    world: SecurityWorld
    administrator: dict[str, str]
    directory: Path
    stack: StackBinding
    transport: ObservedPublicAPI

    @property
    def mutations(self) -> list[tuple[str, str]]:
        return [
            (method, path)
            for method, path, _ in self.transport.requests
            if method != "GET" and "/service-accounts" in path
        ]

    def legacy(self) -> None:
        for name in ("product-mcp-identity.private.json", "product-mcp-identity-intent.json"):
            (self.directory / name).unlink(missing_ok=True)


@pytest.fixture
async def recovery(
    world: SecurityWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> RecoveryWorld:
    administrator = await login(world.client, settings.bootstrap_admin_email)
    token = administrator["Authorization"].removeprefix("Bearer ")
    me = payload(await world.client.get("/api/v1/auth/me", headers=administrator), 200)
    stack = binding()
    directory = tmp_path / "owned-stack"
    write_json(directory / "stack.json", stack)
    write_json(
        directory / "ownership.json", {"project_name": stack.project_name, "nonce": stack.nonce}
    )
    installed = Installation(
        binding_nonce=stack.nonce,
        organization_id=UUID(world.organization),
        project_id=UUID(world.project),
        reviewer_id=UUID(me["id"]),
        reviewer_email=settings.bootstrap_admin_email,
        mcp_account_id=uuid4(),
        target_project_id=UUID(world.project),
        target_organization_id=UUID(world.organization),
        target_user_id=UUID(me["id"]),
        target_email=settings.bootstrap_admin_email,
        fixture_environment_id=uuid4(),
        target_environment_id=uuid4(),
        fixture_service_id=uuid4(),
        target_service_id=uuid4(),
    )
    boot = BootstrapResult(
        installed,
        Credentials(token, token, token, "not-issued-to-observer", "reader", "capture", "viewer"),
    )
    transport = ObservedPublicAPI()

    def public_api(base: str, credential: str = "", organization: str | None = None) -> PublicAPI:
        return PublicAPI(base, credential, organization, transport=transport)

    async def bootstrap(*_args: object, **_kwargs: object) -> BootstrapResult:
        return boot

    async def cleanup_actor(*_args: object, **_kwargs: object) -> str:
        return "synthetic-cleanup-actor"

    monkeypatch.setattr(subject, "PublicAPI", public_api)
    monkeypatch.setattr(subject, "bootstrap", bootstrap)
    monkeypatch.setattr(subject, "verify_binding", lambda actual, path: None)
    monkeypatch.setattr(subject, "_configure", lambda actual, *_args: actual)
    monkeypatch.setattr(subject, "target_cleanup_identity", cleanup_actor)
    monkeypatch.setattr(
        subject,
        "private_environment",
        lambda _: {
            "FLOWTEST_SELFTEST_TARGET_KEY": "synthetic-target-key",
            "FLOWTEST_SELFTEST_OBSERVER_TOKEN": "synthetic-fixture-management-token",
            "FLOWTEST_SELFTEST_RUNNER_ENCRYPTION_KEY": "synthetic-encryption-key-" + "a" * 32,
        },
    )
    return RecoveryWorld(world, administrator, directory, stack, transport)


@pytest.mark.asyncio
async def test_two_product_setup_states_reuse_owned_service_account_without_create_or_rotate(
    recovery: RecoveryWorld, tmp_path: Path
) -> None:
    world, directory = recovery.world, recovery.directory
    first, second = tmp_path / "state-1", tmp_path / "state-2"
    await subject.setup(directory, first)
    first_runtime = AgentRuntime.model_validate(read_json(first / "harness-runtime.json"))
    original_receipt = (first / "mcp-account-receipt.json").read_bytes()
    connection = payload(
        await world.client.post(
            "/api/v1/mcp/connection",
            headers={"Authorization": "Bearer " + first_runtime.mcp_token},
            json={},
        ),
        200,
    )
    assert connection["service_account_id"] == str(first_runtime.installation.mcp_account_id)
    await subject.setup(directory, second)
    second_runtime = AgentRuntime.model_validate(read_json(second / "harness-runtime.json"))
    assert second_runtime.mcp_token == first_runtime.mcp_token
    assert second_runtime.installation.mcp_account_id == first_runtime.installation.mcp_account_id
    assert (first / "mcp-account-receipt.json").read_bytes() == original_receipt
    assert recovery.mutations == [
        ("POST", f"/api/v1/organizations/{world.organization}/service-accounts")
    ]
    rows = payload(
        await world.client.get(
            f"/api/v1/organizations/{world.organization}/service-accounts",
            headers=recovery.administrator,
        ),
        200,
    )
    assert len(rows) == 1
    assert rows[0]["id"] == connection["service_account_id"]
    assert rows[0]["token_prefix"] == first_runtime.mcp_token[:16]
    assert first_runtime.mcp_token not in original_receipt.decode()
    private = directory / "product-mcp-identity.private.json"
    assert private.stat().st_mode & 0o077 == 0
    assert first_runtime.mcp_token not in private.read_text()
    assert "token_ciphertext" in read_json(private)


@pytest.mark.asyncio
async def test_explicit_old_state_recovery_allows_owned_build_upgrade_and_preserves_origin(
    recovery: RecoveryWorld, tmp_path: Path
) -> None:
    first, second = tmp_path / "original", tmp_path / "upgraded"
    await subject.setup(recovery.directory, first)
    original = {path.name: path.read_bytes() for path in first.glob("*.json")}
    recovery.legacy()
    updated = recovery.stack.model_copy(
        update={"candidate_image_digest": "sha256:" + "9" * 64, "source_digest": "8" * 64}
    )
    write_json(recovery.directory / "stack.json", updated)
    await subject.setup(recovery.directory, second, recover_state=first)
    before = AgentRuntime.model_validate(read_json(first / "harness-runtime.json"))
    after = AgentRuntime.model_validate(read_json(second / "harness-runtime.json"))
    assert after.mcp_token == before.mcp_token
    assert after.installation.mcp_account_id == before.installation.mcp_account_id
    assert len(recovery.mutations) == 1
    assert all((first / name).read_bytes() == value for name, value in original.items())


@pytest.mark.asyncio
async def test_unknown_committed_create_stays_pending_and_is_never_replayed(
    recovery: RecoveryWorld, tmp_path: Path
) -> None:
    recovery.transport.lose_create_response = True
    with pytest.raises(httpx.ReadError, match="synthetic lost acknowledged"):
        await subject.setup(recovery.directory, tmp_path / "lost")
    recovery.transport.lose_create_response = False
    with pytest.raises(HarnessError, match="UNKNOWN_RESULT_NEEDS_REVIEW"):
        await subject.setup(recovery.directory, tmp_path / "retry")
    assert len(recovery.mutations) == 1
    assert (recovery.directory / "product-mcp-identity-intent.json").is_file()
    assert not (recovery.directory / "product-mcp-identity.private.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed", ["binding_nonce", "organization_id", "project_id", "scopes", "account_id"]
)
async def test_changed_owned_cache_never_creates_or_rotates(
    recovery: RecoveryWorld, tmp_path: Path, changed: str
) -> None:
    await subject.setup(recovery.directory, tmp_path / "first")
    cache = recovery.directory / "product-mcp-identity.private.json"
    document = read_json(cache)
    document[changed] = (
        ["mcp:read"]
        if changed == "scopes"
        else ("3" * 32 if changed == "binding_nonce" else str(uuid4()))
    )
    write_json(cache, document)
    with pytest.raises(HarnessError, match=r"PRIVATE_IDENTITY_INVALID|ACCOUNT_CHANGED_OR_EXPIRED"):
        await subject.setup(recovery.directory, tmp_path / "changed")
    assert len(recovery.mutations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    ["binding_nonce", "organization_id", "project_id", "expired", "account_id", "receipt_expiry"],
)
async def test_explicit_legacy_recovery_rejects_foreign_or_expired_origin(
    recovery: RecoveryWorld, tmp_path: Path, changed: str
) -> None:
    original = tmp_path / "origin"
    await subject.setup(recovery.directory, original)
    recovery.legacy()
    path = original / "harness-runtime.json"
    document = read_json(path)
    if changed == "expired":
        document["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    elif changed == "receipt_expiry":
        path = original / "mcp-account-receipt.json"
        document = read_json(path)
        document["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    else:
        document["installation"]["mcp_account_id" if changed == "account_id" else changed] = (
            "3" * 32 if changed == "binding_nonce" else str(uuid4())
        )
    write_json(path, document)
    with pytest.raises(
        HarnessError, match=r"RECOVERY_(BINDING_MISMATCH|RUNTIME_INVALID|RECEIPT_MISMATCH)"
    ):
        await subject.setup(recovery.directory, tmp_path / "recovery", recover_state=original)
    assert len(recovery.mutations) == 1


@pytest.mark.asyncio
async def test_old_server_account_without_explicit_recovery_never_reposts_duplicate(
    recovery: RecoveryWorld, tmp_path: Path
) -> None:
    await subject.setup(recovery.directory, tmp_path / "origin")
    recovery.legacy()
    with pytest.raises(HarnessError, match="RECOVERY_REQUIRED"):
        await subject.setup(recovery.directory, tmp_path / "without-explicit-source")
    assert len(recovery.mutations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["rotate", "revoke"])
async def test_revoked_or_rotated_real_account_is_not_silently_replaced(
    recovery: RecoveryWorld, tmp_path: Path, operation: str
) -> None:
    original = tmp_path / "origin"
    await subject.setup(recovery.directory, original)
    runtime = AgentRuntime.model_validate(read_json(original / "harness-runtime.json"))
    response = await recovery.world.client.post(
        f"/api/v1/organizations/{recovery.world.organization}/service-accounts/{runtime.installation.mcp_account_id}/{operation}",
        headers=recovery.administrator,
    )
    payload(response, 200)
    with pytest.raises(HarnessError, match="ACCOUNT_CHANGED_OR_EXPIRED"):
        await subject.setup(recovery.directory, tmp_path / "rotated")
    assert len(recovery.mutations) == 1


@pytest.mark.asyncio
async def test_cached_account_expiry_blocks_before_inspecting_or_rotating_token(
    recovery: RecoveryWorld, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "origin"
    await subject.setup(recovery.directory, original)
    receipt = identity_module.AccountReceipt.model_validate(
        read_json(original / "mcp-account-receipt.json")
    )

    class ExpiredClock:
        @staticmethod
        def now(_zone: object) -> datetime:
            return receipt.expires_at + timedelta(seconds=1)

    monkeypatch.setattr(identity_module, "datetime", ExpiredClock)
    admitted = len(recovery.transport.requests)
    with pytest.raises(HarnessError, match="ACCOUNT_CHANGED_OR_EXPIRED"):
        await subject.setup(recovery.directory, tmp_path / "expired")
    assert len(recovery.mutations) == 1
    assert all(
        path != "/api/v1/mcp/connection" for _, path, _ in recovery.transport.requests[admitted:]
    )
