"""Fail-closed authorization/preflight and a review-only Codex invocation plan.

Creating this plan never starts a provider call. Trusted H must resolve its own credential
home and private IPC relay separately; no browser/owner DTO supplies those values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import jwt
from scripts.selftest.contracts import canonical_digest
from scripts.selftest.host_contracts import HostAuthorization
from scripts.selftest.io import HarnessError


@dataclass(frozen=True, repr=False)
class VerifiedGrant:
    authorization: HostAuthorization
    digest: str


@dataclass(frozen=True)
class HostDeployment:
    host_id: str
    cli_executable: Path
    cli_version: str
    credential_home: Path
    isolated_workspace: Path
    relay_executable: Path
    relay_socket: Path
    skill_digest: str
    data_digest: str
    task_digest: str
    # Set only by trusted deployment checks of resolved model-visible tools and auth isolation.
    tool_isolation_attestation: str | None = None
    provider_cap_verified: bool = False
    policy_digest: str | None = None
    relay_prefix_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostReadiness:
    status: Literal["NOT_RUN", "ready"]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class CodexLaunchPlan:
    arguments: tuple[str, ...]
    working_directory: Path
    environment: tuple[tuple[str, str], ...]
    prompt_digest: str
    authorization_digest: str
    deadline: datetime


def verify_authorization(
    token: str,
    *,
    public_key: str,
    algorithm: Literal["RS256", "EdDSA"],
    issuer: str,
    audience: str,
    allowed_digests: frozenset[str],
) -> VerifiedGrant:
    claims = jwt.decode(
        token,
        public_key,
        algorithms=[algorithm],
        issuer=issuer,
        audience=audience,
        options={"require": ["iss", "aud", "sub", "exp", "iat"]},
    )
    authorization = HostAuthorization.model_validate(claims["authorization"])
    digest = canonical_digest(authorization.model_dump(mode="json"))
    if digest not in allowed_digests:
        raise HarnessError("HOST_AUTHORIZATION_NOT_DEPLOYMENT_APPROVED")
    if claims["sub"] != authorization.approved_by:
        raise HarnessError("HOST_AUTHORIZATION_ACTOR_CHANGED")
    return VerifiedGrant(authorization, digest)


def readiness(grant: VerifiedGrant | None, deployment: HostDeployment) -> HostReadiness:
    if grant is None:
        return HostReadiness("NOT_RUN", ("HOST_AUTHORIZATION_PENDING",))
    auth = grant.authorization
    checks = (
        (auth.approved_at <= datetime.now(UTC), "HOST_AUTHORIZATION_NOT_ACTIVE"),
        (auth.expires_at > datetime.now(UTC), "HOST_AUTHORIZATION_EXPIRED"),
        (auth.host_id == deployment.host_id, "HOST_IDENTITY_CHANGED"),
        (auth.cli_version == deployment.cli_version, "HOST_VERSION_CHANGED"),
        (auth.skill_digest == deployment.skill_digest, "HOST_SKILL_CHANGED"),
        (auth.task_digest == deployment.task_digest, "HOST_TASK_CHANGED"),
        (auth.authorized_data_digest == deployment.data_digest, "HOST_DATA_SCOPE_CHANGED"),
        (auth.policy_digest == deployment.policy_digest, "HOST_POLICY_CHANGED"),
        (auth.provider == "openai", "HOST_PROVIDER_UNSUPPORTED"),
        (deployment.tool_isolation_attestation is not None, "HOST_TOOL_ISOLATION_UNVERIFIED"),
        (
            not auth.budget.require_hard_provider_cap
            or (
                deployment.provider_cap_verified and auth.budget.provider_cap_reference is not None
            ),
            "HOST_PROVIDER_CAP_UNVERIFIED",
        ),
    )
    reasons = tuple(code for accepted, code in checks if not accepted)
    return HostReadiness("NOT_RUN" if reasons else "ready", reasons)


def launch_plan(
    grant: VerifiedGrant | None,
    deployment: HostDeployment,
    *,
    prompt: str,
    schema: Path,
    output: Path,
    deadline: datetime,
) -> CodexLaunchPlan | HostReadiness:
    status = readiness(grant, deployment)
    if status.status != "ready" or grant is None:
        return status
    auth = grant.authorization
    if len(prompt.encode()) > auth.budget.maximum_prompt_bytes:
        return HostReadiness("NOT_RUN", ("HOST_PROMPT_BUDGET_EXCEEDED",))
    configuration = {
        "model_provider": auth.provider,
        "features.shell_tool": False,
        "features.multi_agent": False,
        "features.plugins": False,
        "features.hooks": False,
        "features.memories": False,
        "features.goals": False,
        "features.shell_snapshot": False,
        "features.skill_mcp_dependency_install": False,
        "tools.view_image": False,
        "project_doc_max_bytes": 0,
        "project_doc_fallback_filenames": [],
        "web_search": "disabled",
        "shell_environment_policy.inherit": "none",
        "model_providers.openai.request_max_retries": 0,
        "model_providers.openai.stream_max_retries": 0,
        "mcp_servers.flowtest.command": str(deployment.relay_executable),
        "mcp_servers.flowtest.args": [
            *deployment.relay_prefix_args,
            "--socket",
            str(deployment.relay_socket),
        ],
        "mcp_servers.flowtest.required": True,
        "mcp_servers.flowtest.enabled_tools": list(auth.allowed_tools),
    }
    arguments = [
        str(deployment.cli_executable),
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--strict-config",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--model",
        auth.model,
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(output),
        "-",
    ]
    for key, value in configuration.items():
        arguments.extend(("-c", key + "=" + json.dumps(value, ensure_ascii=False)))
    return CodexLaunchPlan(
        tuple(arguments),
        deployment.isolated_workspace,
        (("CODEX_HOME", str(deployment.credential_home)), ("LANG", "en_US.UTF-8")),
        canonical_digest(prompt),
        grant.digest,
        min(
            deadline,
            auth.expires_at,
            datetime.now(UTC) + timedelta(seconds=auth.budget.wall_seconds),
        ),
    )
