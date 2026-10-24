"""Observe a real, server-minted user JWT expire under a separately owned short-TTL policy."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import Field
from scripts.selftest.boundary_pack import load_boundary_pack
from scripts.selftest.boundary_reporting import write_boundary_junit
from scripts.selftest.contracts import Contract, Identity, Sha256, canonical_digest
from scripts.selftest.io import HarnessError, integer_value, object_value, text_value, write_json
from scripts.selftest.local_stack import StackBinding
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.target_auth_policy import TargetAuthPolicy


@dataclass(frozen=True, repr=False)
class LoginCredentials:
    email: str
    password: str


class ExpiryHTTPObservation(Contract):
    status: int = Field(ge=100, le=599)
    code: Identity | None = None
    trace_id: Identity | None = None
    response_digest: Sha256
    observed_at: datetime


class AuthExpiryManifest(Contract):
    pack_id: Literal["auth-expiry-v1"] = "auth-expiry-v1"
    pack_digest: Sha256
    schema_version: Literal["flowtest-auth-expiry-v1"] = "flowtest-auth-expiry-v1"
    scenario_id: Literal["ST-SECURITY-access-expired"] = "ST-SECURITY-access-expired"
    acceptance_id: Literal["ST-API-001"] = "ST-API-001"
    project_name: Identity
    nonce: Identity
    runtime_profile: Identity
    target_container_id: Identity
    target_image: Identity
    source_digest: Identity
    policy: TargetAuthPolicy
    policy_digest: Sha256
    expected_expires_in: Literal[60] = 60
    expected_error: Literal["ACCESS_TOKEN_EXPIRED"] = "ACCESS_TOKEN_EXPIRED"
    created_at: datetime
    deadline: datetime
    provenance: Literal["local_untrusted"] = "local_untrusted"


class AuthExpiryEvidence(Contract):
    user_id: UUID
    token_digest: Sha256
    expires_in: int = Field(ge=1, le=3600)
    minted_response_at: datetime
    initial: ExpiryHTTPObservation
    expired: ExpiryHTTPObservation
    elapsed_monotonic_seconds: float = Field(ge=0, le=600, allow_inf_nan=False)
    logout: ExpiryHTTPObservation
    http_attempts: int = Field(ge=0, le=500)
    rejected_attempts: int = Field(ge=0)


class AuthExpiryResult(Contract):
    manifest: AuthExpiryManifest
    evidence: AuthExpiryEvidence
    batch_verdict: Literal["passed", "blocked"]
    exit_code: Literal[0, 2]
    reason_codes: tuple[Identity, ...]


def verify_auth_expiry(
    manifest: AuthExpiryManifest, evidence: AuthExpiryEvidence
) -> tuple[str, ...]:
    policy = manifest.policy
    reasons: list[str] = []
    if manifest.pack_digest != load_boundary_pack("auth-expiry-v1", (manifest.scenario_id,)).digest:
        reasons.append("AUTH_EXPIRY_PACK_MISMATCH")
    if manifest.deadline.tzinfo is None or datetime.now(UTC) > manifest.deadline:
        reasons.append("AUTH_EXPIRY_BATCH_EXPIRED")
    if (
        policy.project_name != manifest.project_name
        or policy.nonce != manifest.nonce
        or policy.target_access_token_minutes != 1
        or canonical_digest(policy.model_dump(mode="json")) != manifest.policy_digest
    ):
        reasons.append("AUTH_EXPIRY_POLICY_BINDING_MISMATCH")
    if evidence.expires_in != 60 or evidence.elapsed_monotonic_seconds < 61:
        reasons.append("AUTH_EXPIRY_REAL_ELAPSED_REQUIRED")
    if evidence.initial.status != 200 or evidence.initial.code is not None:
        reasons.append("AUTH_EXPIRY_POSITIVE_CONTROL_MISSING")
    if (
        evidence.expired.status != 401
        or evidence.expired.code != manifest.expected_error
        or not evidence.expired.trace_id
    ):
        reasons.append("AUTH_EXPIRY_EXACT_ERROR_MISMATCH")
    times = (
        manifest.created_at,
        evidence.minted_response_at,
        evidence.initial.observed_at,
        evidence.expired.observed_at,
        evidence.logout.observed_at,
        manifest.deadline,
    )
    if any(value.tzinfo is None for value in times) or tuple(sorted(times)) != times:
        reasons.append("AUTH_EXPIRY_TIME_WINDOW_MISMATCH")
    if evidence.logout.status != 204 or evidence.http_attempts != 4 or evidence.rejected_attempts:
        reasons.append("AUTH_EXPIRY_SESSION_CLEANUP_OR_BUDGET_MISMATCH")
    return tuple(reasons)


def _observation(response: httpx.Response) -> ExpiryHTTPObservation:
    code, trace = None, None
    if response.is_error:
        error = object_value(object_value(response.json())["error"])
        code, trace = text_value(error["code"]), text_value(error["trace_id"])
    return ExpiryHTTPObservation(
        status=response.status_code,
        code=code,
        trace_id=trace,
        response_digest=hashlib.sha256(response.content).hexdigest(),
        observed_at=datetime.now(UTC),
    )


async def execute_auth_expiry(
    *,
    binding: StackBinding,
    policy: TargetAuthPolicy,
    login: LoginCredentials,
    budget: ProtocolHttpBudget,
    output_dir: Path,
    deadline: datetime,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AuthExpiryResult:
    if (
        policy.project_name != binding.project_name
        or policy.nonce != binding.nonce
        or policy.target_access_token_minutes != 1
    ):
        raise HarnessError("SELFTEST_AUTH_EXPIRY_EXPLICIT_SHORT_TARGET_POLICY_REQUIRED")
    remaining = (deadline - datetime.now(UTC)).total_seconds() if deadline.tzinfo else -1
    if not 65 <= remaining <= 600 or budget.counts() != (0, 0):
        raise HarnessError("SELFTEST_AUTH_EXPIRY_DEADLINE_OR_FRESH_BUDGET_REQUIRED")
    manifest = AuthExpiryManifest(
        pack_digest=load_boundary_pack("auth-expiry-v1", ("ST-SECURITY-access-expired",)).digest,
        project_name=binding.project_name,
        nonce=binding.nonce,
        runtime_profile=binding.runtime_profile,
        target_container_id=binding.target_container_id,
        target_image=binding.candidate_image_digest,
        source_digest=binding.source_digest,
        policy=policy,
        policy_digest=canonical_digest(policy.model_dump(mode="json")),
        created_at=datetime.now(UTC),
        deadline=deadline,
    )
    write_json(output_dir / "manifest.json", manifest)
    async with httpx.AsyncClient(
        base_url=binding.target_url.rstrip("/") + "/api/v1/",
        transport=transport,
        trust_env=False,
        timeout=10,
        headers={"X-Requested-With": "FlowTest"},
    ) as api:
        async with asyncio.timeout(remaining):
            pair, minted_at = await _mint(api, login, budget)
            try:
                minted = object_value(pair.json())
                token, ttl = text_value(minted["access_token"]), integer_value(minted["expires_in"])
                initial = _observation(await _get_identity(api, budget, token))
                if ttl != 60:
                    raise HarnessError("SELFTEST_AUTH_EXPIRY_SERVER_TTL_NOT_SHORT_POLICY")
                elapsed_start = time.monotonic()
                await asyncio.sleep(ttl + 1)
                elapsed = time.monotonic() - elapsed_start
                expired = _observation(await _get_identity(api, budget, token))
            finally:
                if not budget.reserve():
                    raise HarnessError("SELFTEST_AUTH_EXPIRY_SESSION_CLEANUP_BUDGET_EXHAUSTED")
                logout = _observation(await api.post("auth/logout"))
                if logout.status != 204:
                    raise HarnessError("SELFTEST_AUTH_EXPIRY_SESSION_CLEANUP_UNCONFIRMED")
    admitted, rejected = budget.counts()
    evidence = AuthExpiryEvidence(
        user_id=UUID(text_value(object_value(minted["user"])["id"])),
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_in=ttl,
        minted_response_at=minted_at,
        initial=initial,
        expired=expired,
        elapsed_monotonic_seconds=elapsed,
        logout=logout,
        http_attempts=admitted,
        rejected_attempts=rejected,
    )
    reasons = verify_auth_expiry(manifest, evidence)
    result = AuthExpiryResult(
        manifest=manifest,
        evidence=evidence,
        batch_verdict="blocked" if reasons else "passed",
        exit_code=2 if reasons else 0,
        reason_codes=reasons,
    )
    write_json(output_dir / "evidence.json", evidence)
    write_json(output_dir / "result.json", result)
    write_boundary_junit(
        output_dir, (manifest.scenario_id,), reasons, purpose="public_authentication_fixture_only"
    )
    return result


async def _mint(
    api: httpx.AsyncClient,
    login: LoginCredentials,
    budget: ProtocolHttpBudget,
) -> tuple[httpx.Response, datetime]:
    if not budget.reserve():
        raise HarnessError("SELFTEST_AUTH_EXPIRY_BUDGET_EXHAUSTED")
    response = await api.post("auth/login", json={"email": login.email, "password": login.password})
    if response.status_code != 200:
        raise HarnessError("SELFTEST_AUTH_EXPIRY_LOGIN_REJECTED")
    return response, datetime.now(UTC)


async def _get_identity(
    api: httpx.AsyncClient, budget: ProtocolHttpBudget, token: str
) -> httpx.Response:
    if not budget.reserve():
        raise HarnessError("SELFTEST_AUTH_EXPIRY_BUDGET_EXHAUSTED")
    return await api.get("auth/me", headers={"Authorization": "Bearer " + token})
