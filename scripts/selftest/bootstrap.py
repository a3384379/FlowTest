"""Provision exact isolated identities and dependencies through public APIs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from scripts.selftest.bootstrap_journal import BootstrapJournal, bootstrap_lock
from scripts.selftest.contracts import Contract
from scripts.selftest.io import (
    HarnessError,
    PublicAPI,
    object_value,
    objects_value,
    read_json,
    text_value,
    write_json,
)
from scripts.selftest.local_stack import StackBinding, private_environment, verify_binding


class Installation(Contract):
    schema_version: str = "flowtest-selftest-installation-v1"
    binding_nonce: str
    organization_id: UUID
    project_id: UUID
    reviewer_id: UUID
    reviewer_email: str
    mcp_account_id: UUID
    target_project_id: UUID
    target_organization_id: UUID | None = None
    target_user_id: UUID
    target_email: str
    fixture_environment_id: UUID
    target_environment_id: UUID
    fixture_service_id: UUID
    target_service_id: UUID
    capture_viewer_id: UUID | None = None
    capture_viewer_email: str | None = None
    target_viewer_id: UUID | None = None
    target_viewer_email: str | None = None
    denied_user_id: UUID | None = None
    denied_email: str | None = None
    reused: bool = False


@dataclass(frozen=True, repr=False)
class Credentials:
    admin_token: str
    reviewer_token: str
    target_admin_token: str
    mcp_token: str
    observer_token: str
    capture_viewer_token: str
    target_viewer_token: str
    target_cleanup_token: str = ""


@dataclass(frozen=True)
class BootstrapResult:
    installation: Installation
    credentials: Credentials


def _active_password(initial: str) -> str:
    return "Selftest-" + hashlib.sha256((initial + ":initialized").encode()).hexdigest()[:40]


async def login(base_url: str, email: str, initial_password: str) -> tuple[str, str]:
    api = PublicAPI(base_url)
    try:
        response = object_value(
            await api.request(
                "POST",
                "/auth/login",
                {"email": email, "password": initial_password},
                allow_status=(401,),
            )
        )
        password = initial_password
        if "access_token" not in response:
            password = _active_password(initial_password)
            response = await api.object(
                "POST", "/auth/login", {"email": email, "password": password}
            )
        token = text_value(response["access_token"])
        user = object_value(response["user"])
        if user["requires_password_change"] is True:
            authenticated = PublicAPI(base_url, token)
            try:
                await authenticated.request(
                    "POST",
                    "/auth/change-password",
                    {
                        "current_password": password,
                        "new_password": _active_password(password),
                    },
                )
            finally:
                await authenticated.close()
            return await login(base_url, email, _active_password(password))
        return token, password
    finally:
        await api.close()


async def bootstrap(
    binding: StackBinding,
    directory: Path,
    *,
    credential_role: Literal["all", "harness", "observer"] = "all",
) -> BootstrapResult:
    verify_binding(binding, directory)
    with bootstrap_lock(directory, binding.nonce):
        return await _bootstrap_owned(binding, directory, credential_role=credential_role)


async def _bootstrap_owned(
    binding: StackBinding,
    directory: Path,
    *,
    credential_role: Literal["all", "harness", "observer"] = "all",
) -> BootstrapResult:
    private = private_environment(directory)
    journal = BootstrapJournal(directory, binding.nonce)
    a_token, _ = await login(
        binding.runner_url, "selftest-a@example.com", private["FLOWTEST_SELFTEST_RUNNER_PASSWORD"]
    )
    b_token, _ = await login(
        binding.target_url, "selftest-b@example.com", private["FLOWTEST_SELFTEST_TARGET_PASSWORD"]
    )
    a, b = PublicAPI(binding.runner_url, a_token), PublicAPI(binding.target_url, b_token)
    try:
        path = directory / "installation.json"
        if path.exists():
            installed = Installation.model_validate(read_json(path))
            if installed.binding_nonce != binding.nonce:
                raise HarnessError("SELFTEST_INSTALLATION_BINDING_MISMATCH")
            a.set_organization(str(installed.organization_id))
            await _validate_installation(a, b, binding, installed)
            installation = installed.model_copy(update={"reused": True})
        else:
            installation = await _install(a, b, binding, private, journal)
            write_json(path, installation)
        installation, capture_token, target_token = await _viewer_credentials(
            a, b, binding, private, journal, installation
        )
        installation = await _denied_actor(a, b, binding, private, journal, installation)
        write_json(path, installation)
        reviewer_initial = _reviewer_password(private)
        reviewer, _ = await login(binding.runner_url, installation.reviewer_email, reviewer_initial)
        issued = (
            await a.object(
                "POST",
                f"/organizations/{installation.organization_id}/service-accounts/{installation.mcp_account_id}/rotate",
            )
            if credential_role != "observer"
            else {"token": "not-issued-to-observer"}
        )
        observer = (
            await _observer_credential(a, installation, directory)
            if credential_role != "harness"
            else "not-issued-to-harness"
        )
        return BootstrapResult(
            installation,
            Credentials(
                a_token,
                reviewer,
                b_token,
                text_value(issued["token"]),
                observer,
                capture_token,
                target_token,
            ),
        )
    finally:
        await a.close()
        await b.close()


def _reviewer_password(private: dict[str, str]) -> str:
    return (
        "Reviewer-"
        + hashlib.sha256(private["FLOWTEST_SELFTEST_RUNNER_KEY"].encode()).hexdigest()[:40]
    )


def _viewer_password(private: dict[str, str], role: Literal["RUNNER", "TARGET"]) -> str:
    return (
        "Observer-"
        + hashlib.sha256(
            (private[f"FLOWTEST_SELFTEST_{role}_KEY"] + ":viewer").encode()
        ).hexdigest()[:40]
    )


async def _viewer_member(api: PublicAPI, project: UUID, organization: UUID, user: str) -> None:
    await api.object(
        "PUT",
        f"/organizations/{organization}/members/{user}",
        {"user_id": user, "role": "member"},
    )
    await api.object(
        "PUT",
        f"/projects/{project}/members/{user}",
        {"user_id": user, "role": "viewer"},
    )


async def _validate_viewer(api: PublicAPI, user_id: str, project_id: UUID) -> None:
    user = await api.object("GET", "/auth/me")
    permissions = await api.object("GET", f"/projects/{project_id}/permissions")
    if (
        user.get("id") != user_id
        or user.get("is_system_admin") is not False
        or permissions.get("effective_role") != "viewer"
    ):
        raise HarnessError("SELFTEST_OBSERVER_VIEWER_IDENTITY_INVALID")


async def _viewer_credentials(
    a: PublicAPI,
    b: PublicAPI,
    binding: StackBinding,
    private: dict[str, str],
    journal: BootstrapJournal,
    installed: Installation,
) -> tuple[Installation, str, str]:
    if installed.target_organization_id is None:
        raise HarnessError("SELFTEST_TARGET_ORGANIZATION_MISSING")
    capture = await _viewer_identity(
        a,
        binding.runner_url,
        binding.nonce,
        private,
        journal,
        phase="capture_viewer",
        role="RUNNER",
        project=installed.project_id,
        organization=installed.organization_id,
        previous=installed.capture_viewer_id,
    )
    target = await _viewer_identity(
        b,
        binding.target_url,
        binding.nonce,
        private,
        journal,
        phase="target_viewer",
        role="TARGET",
        project=installed.target_project_id,
        organization=installed.target_organization_id,
        previous=installed.target_viewer_id,
    )
    updated = installed.model_copy(
        update={
            "capture_viewer_id": capture.user_id,
            "capture_viewer_email": capture.email,
            "target_viewer_id": target.user_id,
            "target_viewer_email": target.email,
        }
    )
    return updated, capture.token, target.token


@dataclass(frozen=True, repr=False)
class ViewerIdentity:
    user_id: UUID
    email: str
    token: str


async def _viewer_identity(
    api: PublicAPI,
    base_url: str,
    nonce: str,
    private: dict[str, str],
    journal: BootstrapJournal,
    *,
    phase: Literal["capture_viewer", "target_viewer"],
    role: Literal["RUNNER", "TARGET"],
    project: UUID,
    organization: UUID,
    previous: UUID | None,
) -> ViewerIdentity:
    email = f"{phase.replace('_', '-')}-{nonce[:12]}@example.com"
    password = _viewer_password(private, role)
    user_id = await _user(api, email, password, journal, phase)
    if previous is not None and str(previous) != user_id:
        raise HarnessError("SELFTEST_OBSERVER_VIEWER_IDENTITY_CHANGED")
    await _viewer_member(api, project, organization, user_id)
    token, _ = await login(base_url, email, password)
    viewer = PublicAPI(base_url, token, str(organization))
    try:
        await _validate_viewer(viewer, user_id, project)
    finally:
        await viewer.close()
    return ViewerIdentity(UUID(user_id), email, token)


async def _user(
    api: PublicAPI, email: str, password: str, journal: BootstrapJournal, phase: str
) -> str:
    user = await journal.create(
        api,
        phase,
        "/users",
        {
            "email": email,
            "password": password,
            "display_name": "隔离自测身份",
        },
    )
    return text_value(user["id"])


async def _denied_actor(
    a: PublicAPI,
    b: PublicAPI,
    binding: StackBinding,
    private: dict[str, str],
    journal: BootstrapJournal,
    installed: Installation,
) -> Installation:
    if installed.target_organization_id is None:
        raise HarnessError("SELFTEST_TARGET_ORGANIZATION_MISSING")
    email = f"denied-actor-{binding.nonce[:12]}@example.com"
    initial = (
        "Denied-"
        + hashlib.sha256(
            (private["FLOWTEST_SELFTEST_TARGET_KEY"] + ":denied-actor").encode()
        ).hexdigest()[:40]
    )
    user_id = await _user(b, email, initial, journal, "denied_actor")
    if installed.denied_user_id is not None and str(installed.denied_user_id) != user_id:
        raise HarnessError("SELFTEST_DENIED_ACTOR_IDENTITY_CHANGED")
    await _viewer_member(b, installed.target_project_id, installed.target_organization_id, user_id)
    token, active = await login(binding.target_url, email, initial)
    viewer = PublicAPI(binding.target_url, token, str(installed.target_organization_id))
    try:
        await _validate_viewer(viewer, user_id, installed.target_project_id)
    finally:
        await viewer.close()
    await a.object(
        "PUT",
        f"/projects/{installed.project_id}/secrets",
        {"name": "SELFTEST_B_DENIED_PASSWORD", "value": active},
    )
    return installed.model_copy(update={"denied_user_id": UUID(user_id), "denied_email": email})


async def _member(api: PublicAPI, project: str, organization: str, user: str) -> None:
    await api.object(
        "PUT", f"/organizations/{organization}/members/{user}", {"user_id": user, "role": "admin"}
    )
    await api.object(
        "PUT", f"/projects/{project}/members/{user}", {"user_id": user, "role": "owner"}
    )


async def _install(
    a: PublicAPI,
    b: PublicAPI,
    binding: StackBinding,
    private: dict[str, str],
    journal: BootstrapJournal,
) -> Installation:
    organization = await journal.create(
        a,
        "organization",
        "/organizations",
        {"name": binding.project_name, "slug": binding.project_name},
        read_prefix="/organizations",
    )
    org_id = text_value(organization["id"])
    a.set_organization(org_id)
    project = await journal.create(
        a,
        "runner_project",
        "/projects",
        {"name": "自测控制项目", "organization_id": org_id},
        read_prefix="/projects",
    )
    project_id = text_value(project["id"])
    await a.object(
        "PUT",
        f"/projects/{project_id}/security-policy",
        {
            "enabled": True,
            "allowed_hosts": ["target", "mock-target"],
            "allowed_private_cidrs": [binding.private_subnet],
        },
    )
    reviewer_email = f"reviewer-{binding.nonce[:12]}@example.com"
    reviewer_id = await _user(a, reviewer_email, _reviewer_password(private), journal, "reviewer")
    await _member(a, project_id, org_id, reviewer_id)
    account = await journal.create(
        a,
        "mcp_account",
        f"/organizations/{org_id}/service-accounts",
        {
            "name": "MCP 隔离生成身份",
            "account_key": "selftest-generator",
            "scopes": [
                "project:read",
                "project:write",
                "mcp:read",
                "mcp:write",
                "mcp:flow:propose",
                "mcp:evidence:write",
                "mcp:project:bootstrap",
                "mcp:contract:import",
                "mcp:test-plan:propose",
            ],
            "expires_at": (journal.document.created_at + timedelta(hours=2)).isoformat(),
        },
    )
    target_project = await journal.create(
        b, "target_project", "/projects", {"name": "自测业务隔离项目"}, read_prefix="/projects"
    )
    target_id = text_value(target_project["id"])
    target_org = text_value(target_project["organization_id"])
    b.set_organization(target_org)
    target_email = f"actor-{binding.nonce[:12]}@example.com"
    target_password = (
        "Actor-" + hashlib.sha256(private["FLOWTEST_SELFTEST_TARGET_KEY"].encode()).hexdigest()[:40]
    )
    target_user_id = await _user(b, target_email, target_password, journal, "target_user")
    await _member(b, target_id, target_org, target_user_id)
    _, active_target_password = await login(binding.target_url, target_email, target_password)
    await a.object(
        "PUT",
        f"/projects/{project_id}/secrets",
        {"name": "SELFTEST_B_PASSWORD", "value": active_target_password},
    )
    fixture = await _environment(
        a, project_id, "确定性 Mock", binding.fixture_internal_url, journal, "fixture_environment"
    )
    target = await _environment(
        a, project_id, "隔离 FlowTest B", binding.target_internal_url, journal, "target_environment"
    )
    fixture_service = await _service(
        a, project_id, fixture, "selftest_mock", binding.fixture_internal_url, journal
    )
    target_service = await _service(
        a, project_id, target, "selftest_target", binding.target_internal_url, journal
    )
    return Installation(
        binding_nonce=binding.nonce,
        organization_id=UUID(org_id),
        project_id=UUID(project_id),
        reviewer_id=UUID(reviewer_id),
        reviewer_email=reviewer_email,
        mcp_account_id=UUID(text_value(account["id"])),
        target_project_id=UUID(target_id),
        target_organization_id=UUID(target_org),
        target_user_id=UUID(target_user_id),
        target_email=target_email,
        fixture_environment_id=UUID(fixture),
        target_environment_id=UUID(target),
        fixture_service_id=UUID(fixture_service),
        target_service_id=UUID(target_service),
    )


async def _environment(
    api: PublicAPI, project: str, name: str, base_url: str, journal: BootstrapJournal, phase: str
) -> str:
    value = await journal.create(
        api,
        phase,
        f"/projects/{project}/environments",
        {"name": name, "base_url": base_url, "classification": "test"},
    )
    return text_value(value["id"])


async def _service(
    api: PublicAPI, project: str, environment: str, key: str, url: str, journal: BootstrapJournal
) -> str:
    service = await journal.create(
        api, f"{key}_service", f"/projects/{project}/services", {"name": key, "service_key": key}
    )
    service_id = text_value(service["id"])
    await journal.create(
        api,
        f"{key}_endpoint",
        f"/projects/{project}/environments/{environment}/service-endpoints",
        {"service_id": service_id, "variant": "default", "base_url": url},
    )
    await api.object(
        "PATCH",
        f"/projects/{project}/environments/{environment}",
        {"default_service_id": service_id},
    )
    return service_id


async def _validate_installation(
    a: PublicAPI, b: PublicAPI, binding: StackBinding, installed: Installation
) -> None:
    project = await a.object("GET", f"/projects/{installed.project_id}")
    if project.get("organization_id") != str(installed.organization_id):
        raise HarnessError("SELFTEST_INSTALLATION_ORGANIZATION_CHANGED")
    if installed.target_organization_id is not None:
        b.set_organization(str(installed.target_organization_id))
    await b.object("GET", f"/projects/{installed.target_project_id}")
    environments = objects_value(
        await a.request("GET", f"/projects/{installed.project_id}/environments")
    )
    actual = {item["id"]: item for item in environments}
    for environment, url, service in (
        (
            installed.fixture_environment_id,
            binding.fixture_internal_url,
            installed.fixture_service_id,
        ),
        (installed.target_environment_id, binding.target_internal_url, installed.target_service_id),
    ):
        value = actual.get(str(environment))
        if (
            value is None
            or str(value.get("base_url", "")).rstrip("/") != url
            or value.get("default_service_id") != str(service)
        ):
            raise HarnessError("SELFTEST_INSTALLATION_ENVIRONMENT_DRIFT")


class ObserverCredentialLease(Contract):
    binding_nonce: str
    status: Literal["creating", "issued"]
    token_id: UUID | None = None


async def _observer_credential(api: PublicAPI, installed: Installation, directory: Path) -> str:
    path = directory / "observer-credential-lease.json"
    if path.exists():
        lease = ObserverCredentialLease.model_validate(read_json(path))
        if (
            lease.binding_nonce != installed.binding_nonce
            or lease.status != "issued"
            or lease.token_id is None
        ):
            raise HarnessError("SELFTEST_OBSERVER_CREDENTIAL_NEEDS_REVIEW")
        await api.request(
            "DELETE", f"/projects/{installed.project_id}/service-tokens/{lease.token_id}"
        )
    write_json(
        path, ObserverCredentialLease(binding_nonce=installed.binding_nonce, status="creating")
    )
    issued = await api.object(
        "POST",
        f"/projects/{installed.project_id}/service-tokens",
        {
            "name": "独立核验只读凭据",
            "scopes": ["read:execution"],
            "expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        },
    )
    write_json(
        path,
        ObserverCredentialLease(
            binding_nonce=installed.binding_nonce,
            status="issued",
            token_id=UUID(text_value(issued["id"])),
        ),
    )
    return text_value(issued["token"])
