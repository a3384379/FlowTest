"""Trusted owner setup for two fresh probe projects; no bootstrap or model dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import JsonValue
from scripts.selftest.bootstrap import Installation, _active_password
from scripts.selftest.bootstrap_journal import bootstrap_lock
from scripts.selftest.contracts import Builds, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import StackBinding, private_environment, verify_binding
from scripts.selftest.mcp_governance_contracts import Fixture, Manifest
from scripts.selftest.mcp_negative_budget import ProtocolHttpBudget
from scripts.selftest.mcp_negative_contracts import Actor, FixtureIdentity, ProtocolManifest
from scripts.selftest.mcp_probe_contracts import ProbeAuthority, ProbeFixture
from scripts.selftest.product_agent_client import AgentIdentity
from scripts.selftest.product_setup import _configure, deployment_binding_id
from scripts.selftest.run import _verifier_digest

from app.core.self_test_probes import NegativeProbeGrant
from app.core.self_tests import SelfTestPrincipal, SelfTestSettings
from app.schemas.self_tests import BuildIdentity

ProbePack = Literal["protocol34", "governance42"]
FreezeProbe = Callable[
    [StackBinding, "PreparedFixture", str, str, datetime, datetime, ProbePack],
    Manifest | ProtocolManifest,
]


class ProbeAPI(PublicAPI):
    def __init__(
        self,
        url: str,
        budget: ProtocolHttpBudget,
        token: str = "",
        organization: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(url, token, organization, transport=transport)
        self.budget = budget
        self.api_url = url

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        idempotency_key: str | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> JsonValue:
        if not self.budget.reserve():
            raise HarnessError("SELFTEST_PROBE_HTTP_BUDGET_EXHAUSTED")
        return await super().request(
            method, path, payload, idempotency_key=idempotency_key, allow_status=allow_status
        )


@dataclass(frozen=True, repr=False)
class ProbeCredentials:
    tokens: dict[Actor, str]
    writer_token: str
    reviewer_token: str
    observer_identity: AgentIdentity


@dataclass
class ProbeRPCBudget:
    admitted: int = 0
    rejected: int = 0


@dataclass(frozen=True)
class PreparedFixture:
    identity: FixtureIdentity
    governance: Fixture
    machine_ids: tuple[UUID, ...]


@dataclass(frozen=True, repr=False)
class Provisioned:
    fixture: PreparedFixture
    tokens: dict[Actor, str]
    writer_token: str
    reviewer_token: str


@dataclass(frozen=True, repr=False)
class PreparedProbe:
    binding: StackBinding
    directory: Path
    state: Path
    authority: ProbeAuthority
    fixture: PreparedFixture
    credentials: ProbeCredentials
    budget: ProtocolHttpBudget
    manifest_path: Path
    pack: ProbePack
    rpc_budget: ProbeRPCBudget


async def _login(
    url: str, budget: ProtocolHttpBudget, email: str, password: str, *, new_actor: bool = False
) -> tuple[str, UUID]:
    public = ProbeAPI(url, budget)
    try:
        raw = object_value(
            await public.request(
                "POST", "/auth/login", {"email": email, "password": password}, allow_status=(401,)
            )
        )
        if "access_token" not in raw:
            password = _active_password(password)
            raw = await public.object("POST", "/auth/login", {"email": email, "password": password})
        token = text_value(raw["access_token"])
        user = object_value(raw["user"])
        if user["requires_password_change"] is True:
            if not new_actor:
                raise HarnessError("SELFTEST_PROBE_OWNER_MUST_BE_INITIALIZED")
            authenticated = ProbeAPI(url, budget, token)
            try:
                active = secrets.token_urlsafe(30)
                await authenticated.request(
                    "POST",
                    "/auth/change-password",
                    {"current_password": password, "new_password": active},
                )
            finally:
                await authenticated.close()
            return await _login(url, budget, email, active)
        return token, UUID(text_value(user["id"]))
    finally:
        await public.close()


async def _project(api: ProbeAPI, nonce: str, suffix: str) -> ProbeFixture:
    organization = await api.object(
        "POST",
        "/organizations",
        {"name": "协议负向独立组织 " + suffix, "slug": f"probe-{nonce[:12]}-{suffix}"},
    )
    org = UUID(text_value(organization["id"]))
    api.set_organization(str(org))
    project = await api.object(
        "POST", "/projects", {"name": "协议负向独立项目 " + suffix, "organization_id": str(org)}
    )
    return ProbeFixture(project_id=UUID(text_value(project["id"])), organization_id=org)


async def _account(
    api: ProbeAPI, org: UUID, key: str, scopes: list[str], *, expires: datetime | None = None
) -> tuple[UUID, str]:
    api.set_organization(str(org))
    scope_values: list[JsonValue] = [value for value in scopes]
    data = await api.object(
        "POST",
        f"/organizations/{org}/service-accounts",
        {
            "name": "协议负向机器 " + key,
            "account_key": key,
            "scopes": scope_values,
            "expires_at": expires.isoformat() if expires else None,
        },
    )
    return UUID(text_value(data["id"])), text_value(data["token"])


async def _reviewer(api: ProbeAPI, fixture: ProbeFixture, nonce: str) -> tuple[UUID, str]:
    password = secrets.token_urlsafe(30)
    email = f"probe-reviewer-{nonce[:12]}@example.com"
    user = await api.object(
        "POST",
        "/users",
        {"email": email, "password": password, "display_name": "独立负向fixture评审者"},
    )
    identifier = UUID(text_value(user["id"]))
    await api.object(
        "PUT",
        f"/organizations/{fixture.organization_id}/members/{identifier}",
        {"user_id": str(identifier), "role": "member"},
    )
    await api.object(
        "PUT",
        f"/projects/{fixture.project_id}/members/{identifier}",
        {"user_id": str(identifier), "role": "owner"},
    )
    token, actual = await _login(api.api_url, api.budget, email, password, new_actor=True)
    if actual != identifier:
        raise HarnessError("SELFTEST_PROBE_REVIEWER_IDENTITY_MISMATCH")
    return identifier, token


async def provision(
    binding: StackBinding, directory: Path, state: Path, nonce: str, budget: ProtocolHttpBudget
) -> Provisioned:
    private = private_environment(directory)
    token, owner = await _login(
        binding.runner_url,
        budget,
        "selftest-a@example.com",
        private["FLOWTEST_SELFTEST_RUNNER_PASSWORD"],
    )
    api = ProbeAPI(binding.runner_url, budget, token)
    try:
        first = await _project(api, nonce, "a")
        second = await _project(api, nonce, "b")
        api.set_organization(str(first.organization_id))
        reviewer, reviewer_token = await _reviewer(api, first, nonce)
        keys = ("reader_a", "reader_b", "limited", "revoked", "expired", "writer")
        accounts: dict[str, tuple[UUID, str]] = {}
        expiry = datetime.now(UTC) + timedelta(seconds=3)
        for key in keys:
            scopes = ["project:read"] if key == "limited" else ["mcp:read"]
            if key == "writer":
                scopes += ["mcp:write", "mcp:flow:propose"]
            org = second.organization_id if key == "reader_b" else first.organization_id
            accounts[key] = await _account(
                api,
                org,
                f"probe-{nonce[:12]}-{key}",
                scopes,
                expires=expiry if key == "expired" else None,
            )
        api.set_organization(str(first.organization_id))
        await api.object(
            "POST",
            f"/organizations/{first.organization_id}/service-accounts/{accounts['revoked'][0]}/revoke",
            {},
        )
        ci = await api.object(
            "POST",
            f"/projects/{first.project_id}/service-tokens",
            {"name": "协议类型交叉负向", "scopes": ["read:execution"]},
        )
        identity = FixtureIdentity(
            project_a=first.project_id,
            project_b=second.project_id,
            organization_a=first.organization_id,
            organization_b=second.organization_id,
        )
        fixture = PreparedFixture(
            identity,
            Fixture(
                project_id=first.project_id,
                organization_id=first.organization_id,
                machine_id=accounts["writer"][0],
                owner_user_id=owner,
                reviewer_user_id=reviewer,
            ),
            tuple(value[0] for value in accounts.values()),
        )
        write_json(
            state / "fixture-resources.json",
            {
                "fixture": fixture.identity.model_dump(mode="json"),
                "governance": fixture.governance.model_dump(mode="json"),
                "machine_ids": [str(item) for item in fixture.machine_ids],
                "cleanup": "requires_owned_stack_disposal",
            },
        )
        tokens: dict[Actor, str] = {
            "reader_a": accounts["reader_a"][1],
            "reader_b": accounts["reader_b"][1],
            "none": "",
            "limited": accounts["limited"][1],
            "revoked": accounts["revoked"][1],
            "expired": accounts["expired"][1],
            "human": token,
            "ci": text_value(ci["token"]),
        }
        await asyncio.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.05)
        return Provisioned(fixture, tokens, accounts["writer"][1], reviewer_token)
    finally:
        await api.close()


def _observer(state: Path, authority: ProbeAuthority) -> AgentIdentity:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = state / "negative-O-private.pem"
    with path.open("xb") as output:
        path.chmod(0o600)
        output.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    principal = SelfTestPrincipal(
        id="negative-O-" + authority.probe_id.hex[:12],
        issuer="flowtest-negative-probe",
        subject=str(authority.probe_id),
        audience="flowtest-selftest-api",
        public_key=key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
        allowed_project_ids=tuple(item.project_id for item in authority.fixtures),
        allowed_binding_ids=(authority.binding_id,),
        capabilities=("verify",),
        trusted_verifier=False,
    )
    return AgentIdentity(principal=principal, private_key_file=path)


def configure(
    binding: StackBinding,
    directory: Path,
    state: Path,
    authority: ProbeAuthority,
    identity: AgentIdentity,
    nonce: str,
) -> StackBinding:
    private = private_environment(directory)
    grant = NegativeProbeGrant.model_validate(
        {
            **authority.model_dump(mode="json", exclude={"probe_id", "fixtures"}),
            "id": str(authority.probe_id),
            "fixtures": [item.model_dump(mode="json") for item in authority.fixtures],
            "principal_id": identity.principal.id,
            "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
        }
    )
    existing_principals = json.loads(private.get("FLOWTEST_SELFTEST_PRINCIPALS", "[]"))
    existing_grants = json.loads(private.get("FLOWTEST_SELFTEST_PROBE_GRANTS", "[]"))
    settings = SelfTestSettings(
        principals=(
            *(SelfTestPrincipal.model_validate(value) for value in existing_principals),
            identity.principal,
        ),
        probe_grants=(
            *(NegativeProbeGrant.model_validate(value) for value in existing_grants),
            grant,
        ),
    )
    for field in ("principals", "probe_grants"):
        private[f"FLOWTEST_SELFTEST_{field.upper()}"] = json.dumps(
            settings.model_dump(mode="json")[field], ensure_ascii=False, separators=(",", ":")
        )
    write_json(state / "probe-authority.json", authority)
    write_json(
        state / "probe-public-configuration.json",
        {
            "principal": identity.principal.model_dump(mode="json"),
            "grant": grant.model_dump(mode="json"),
        },
    )
    updated = _configure(binding, directory, state, private)
    _retained_binding(binding, updated)
    verify_binding(updated, directory)
    write_json(directory / "stack.json", updated)
    write_json(
        state / "configuration-receipt.json",
        {
            "completed": True,
            "probe_id": str(authority.probe_id),
            "binding_fingerprint": authority.binding_fingerprint,
        },
    )
    return updated


def _retained_binding(before: StackBinding, after: StackBinding) -> None:
    if before.model_dump(exclude={"runner_container_id"}) != after.model_dump(
        exclude={"runner_container_id"}
    ):
        raise HarnessError("SELFTEST_PROBE_CONFIGURATION_RESOURCE_DRIFT")


def builds(binding: StackBinding) -> Builds:
    return Builds(
        runner=binding.candidate_image_digest,
        target=binding.candidate_image_digest,
        fixture=binding.fixture_image_digest.removeprefix("sha256:"),
        verifier=_verifier_digest(binding.runtime_profile),
    )


def authority(
    binding: StackBinding,
    fixture: PreparedFixture,
    manifest_digest: str,
    nonce: str,
    issued_at: datetime,
    expires_at: datetime,
) -> ProbeAuthority:
    actual_builds = builds(binding)
    return ProbeAuthority(
        probe_id=UUID(nonce),
        binding_id=deployment_binding_id(
            binding.nonce, BuildIdentity.model_validate(actual_builds.model_dump())
        ),
        binding_fingerprint=canonical_digest(
            binding.model_dump(mode="json", exclude={"runner_container_id"})
        ),
        manifest_digest=manifest_digest,
        source_digest=binding.source_digest,
        runtime_profile=binding.runtime_profile,
        builds=actual_builds,
        fixtures=(
            ProbeFixture(
                project_id=fixture.identity.project_a,
                organization_id=fixture.identity.organization_a,
            ),
            ProbeFixture(
                project_id=fixture.identity.project_b,
                organization_id=fixture.identity.organization_b,
            ),
        ),
        owner_user_id=fixture.governance.owner_user_id,
        reviewer_user_id=fixture.governance.reviewer_user_id,
        machine_account_ids=fixture.machine_ids,
        issued_at=issued_at,
        expires_at=expires_at,
    )


async def _prepare_claimed(
    directory: Path, state: Path, *, pack: ProbePack, freeze: FreezeProbe
) -> PreparedProbe:
    binding = StackBinding.model_validate(read_json(directory / "stack.json"))
    verify_binding(binding, directory)
    installation = Installation.model_validate(read_json(directory / "installation.json"))
    if installation.binding_nonce != binding.nonce:
        raise HarnessError("SELFTEST_PROBE_EXISTING_INSTALLATION_REQUIRED")
    with bootstrap_lock(directory, binding.nonce):
        started = datetime.now(UTC)
        deadline = started + timedelta(seconds=600)
        nonce = secrets.token_hex(16)
        budget = ProtocolHttpBudget(
            state / "private/h-http-budget.sqlite3", nonce, deadline.timestamp()
        )
        write_json(
            state / "setup-intent.json",
            {
                "nonce": nonce,
                "pack": pack,
                "source_digest": binding.source_digest,
                "issued_at": started.isoformat(),
                "expires_at": deadline.isoformat(),
                "cleanup": "requires_owned_stack_disposal",
            },
        )
        async with asyncio.timeout((deadline - datetime.now(UTC)).total_seconds()):
            issued = await provision(binding, directory, state, nonce, budget)
            manifest = freeze(binding, issued.fixture, state.name, nonce, started, deadline, pack)
            manifest_path = state / "public/manifest.json"
            write_json(manifest_path, manifest)
            frozen = authority(
                binding,
                issued.fixture,
                canonical_digest(manifest.model_dump(mode="json")),
                nonce,
                started,
                deadline,
            )
            identity = _observer(state, frozen)
            if (deadline - datetime.now(UTC)).total_seconds() < 200:
                raise HarnessError("SELFTEST_PROBE_CONFIGURATION_TIME_BUDGET")
            updated = await configure_owned(binding, directory, state, frozen, identity, nonce)
        return PreparedProbe(
            updated,
            directory,
            state,
            frozen,
            issued.fixture,
            ProbeCredentials(issued.tokens, issued.writer_token, issued.reviewer_token, identity),
            budget,
            manifest_path,
            pack,
            ProbeRPCBudget(),
        )


async def prepare_and_configure(
    directory: Path, state: Path, *, pack: ProbePack, freeze: FreezeProbe
) -> PreparedProbe:
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    return await _prepare_claimed(directory, state, pack=pack, freeze=freeze)


async def configure_owned(
    binding: StackBinding,
    directory: Path,
    state: Path,
    frozen: ProbeAuthority,
    identity: AgentIdentity,
    nonce: str,
) -> StackBinding:
    """Caller holds bootstrap_lock; cancellation cannot release it during recreate."""
    if (frozen.expires_at - datetime.now(UTC)).total_seconds() < 200:
        raise HarnessError("SELFTEST_PROBE_CONFIGURATION_TIME_BUDGET")
    task = asyncio.create_task(
        asyncio.to_thread(configure, binding, directory, state, frozen, identity, nonce)
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
