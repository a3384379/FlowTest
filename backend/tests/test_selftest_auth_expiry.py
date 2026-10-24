"""Real server-minted 1-minute user JWT expiry; no token forgery or clock patch."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_selftest_native_api_security import SecurityWorld
from test_selftest_native_api_security import world as world

from app.core.config import settings
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.auth_expiry import (  # noqa: E402
    LoginCredentials,
    execute_auth_expiry,
    verify_auth_expiry,
)
from scripts.selftest.io import HarnessError  # noqa: E402
from scripts.selftest.local_stack import StackBinding  # noqa: E402
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget  # noqa: E402
from scripts.selftest.target_auth_policy import TargetAuthPolicy  # noqa: E402


def binding() -> StackBinding:
    return StackBinding(
        project_name="flowtest-selftest-123456789abc",
        nonce="a" * 32,
        runner_url="http://runner",
        target_url="http://owned-security",
        observer_url="http://observer",
        private_subnet="192.0.2.0/24",
        candidate_image="owned-candidate",
        candidate_image_digest="b" * 64,
        fixture_image="owned-fixture",
        fixture_image_digest="c" * 64,
        source_digest="d" * 64,
        dependency_digest="e" * 64,
        runner_container_id="runner-asgi-local",
        target_container_id="target-asgi-local",
        observer_container_id="observer-asgi-local",
        runner_volume="owned-runner",
        target_volume="owned-target",
    )


@pytest.mark.asyncio
async def test_server_minted_access_token_naturally_expires_after_real_wall_time(
    world: SecurityWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "access_token_minutes", 1)
    frozen = binding()
    policy = TargetAuthPolicy(
        project_name=frozen.project_name, nonce=frozen.nonce, target_access_token_minutes=1
    )
    deadline = datetime.now(UTC) + timedelta(seconds=120)
    budget = ProtocolHttpBudget(
        tmp_path / "private-budget.sqlite3", frozen.nonce, deadline.timestamp()
    )
    result = await execute_auth_expiry(
        binding=frozen,
        policy=policy,
        login=LoginCredentials(**world.owner_login),
        budget=budget,
        output_dir=tmp_path / "safe",
        deadline=deadline,
        transport=httpx.ASGITransport(app=app),
    )
    assert result.exit_code == 0, result.model_dump_json(indent=2)
    assert verify_auth_expiry(result.manifest, result.evidence) == ()
    assert result.evidence.expired.code == "ACCESS_TOKEN_EXPIRED"
    assert result.evidence.expired.status == 401 and result.evidence.expired.trace_id
    assert result.evidence.elapsed_monotonic_seconds >= 61
    assert result.evidence.http_attempts == 4
    serialized = json.dumps(result.model_dump(mode="json"))
    assert world.owner_login["password"] not in serialized
    assert 'access_token"' not in serialized and "Bearer " not in serialized
    for change in ("invalid", "early", "not_expired", "wrong_policy", "missing_trace"):
        evidence = result.evidence
        manifest = result.manifest
        if change == "invalid":
            evidence = evidence.model_copy(
                update={
                    "expired": evidence.expired.model_copy(update={"code": "INVALID_ACCESS_TOKEN"})
                }
            )
        elif change == "early":
            evidence = evidence.model_copy(update={"elapsed_monotonic_seconds": 1.0})
        elif change == "not_expired":
            evidence = evidence.model_copy(
                update={"expired": evidence.expired.model_copy(update={"status": 200})}
            )
        elif change == "missing_trace":
            evidence = evidence.model_copy(
                update={"expired": evidence.expired.model_copy(update={"trace_id": None})}
            )
        else:
            manifest = manifest.model_copy(update={"policy_digest": "f" * 64})
        assert verify_auth_expiry(manifest, evidence), change


@pytest.mark.asyncio
async def test_default_fifteen_minute_policy_never_mints_or_substitutes_invalid_token(
    tmp_path: Path,
) -> None:
    frozen = binding()
    policy = TargetAuthPolicy(
        project_name=frozen.project_name, nonce=frozen.nonce, target_access_token_minutes=15
    )
    deadline = datetime.now(UTC) + timedelta(seconds=120)
    budget = ProtocolHttpBudget(tmp_path / "budget.sqlite3", frozen.nonce, deadline.timestamp())
    with pytest.raises(HarnessError, match="EXPLICIT_SHORT_TARGET_POLICY_REQUIRED"):
        await execute_auth_expiry(
            binding=frozen,
            policy=policy,
            login=LoginCredentials("never@example.test", "never-used-password"),
            budget=budget,
            output_dir=tmp_path / "safe",
            deadline=deadline,
        )
    assert budget.counts() == (0, 0)
    assert not (tmp_path / "safe").exists()


@pytest.mark.asyncio
async def test_server_policy_mismatch_logs_out_the_known_session_without_waiting_or_fake_expiry(
    world: SecurityWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "access_token_minutes", 15)
    paths: list[str] = []

    class ObservedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return await httpx.ASGITransport(app=app).handle_async_request(request)

    frozen = binding()
    deadline = datetime.now(UTC) + timedelta(seconds=120)
    budget = ProtocolHttpBudget(tmp_path / "budget.sqlite3", frozen.nonce, deadline.timestamp())
    with pytest.raises(HarnessError, match="SERVER_TTL_NOT_SHORT_POLICY"):
        await execute_auth_expiry(
            binding=frozen,
            policy=TargetAuthPolicy(
                project_name=frozen.project_name, nonce=frozen.nonce, target_access_token_minutes=1
            ),
            login=LoginCredentials(**world.owner_login),
            budget=budget,
            output_dir=tmp_path / "safe",
            deadline=deadline,
            transport=ObservedTransport(),
        )
    assert paths == ["/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout"]
    assert budget.counts() == (3, 0)
    assert not (tmp_path / "safe" / "evidence.json").exists()
