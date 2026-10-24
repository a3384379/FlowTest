"""Deployment JWT identities and leased API transport for external H/O processes."""

from __future__ import annotations

import asyncio
import base64
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import jwt
from pydantic import Field
from scripts.selftest.bootstrap import BootstrapResult, Credentials, Installation
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import HarnessError, PublicAPI, object_value, read_json, write_json
from scripts.selftest.local_stack import StackBinding

from app.core.self_tests import SelfTestBinding, SelfTestPrincipal
from app.schemas.self_tests import (
    AgentArtifactUpload,
    AgentRegistrationRequest,
    AgentTaskResponse,
    ArtifactKind,
    ArtifactReference,
    LeaseClaim,
    LeaseRequest,
)


class AgentIdentity(Contract):
    principal: SelfTestPrincipal
    private_key_file: Path

    def token(self) -> str:
        path = self.private_key_file
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
            raise HarnessError("SELFTEST_AGENT_SIGNING_KEY_PERMISSIONS")
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "iss": self.principal.issuer,
                "sub": self.principal.subject,
                "aud": self.principal.audience,
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(seconds=900),
            },
            path.read_bytes(),
            algorithm=self.principal.algorithm,
        )


class AgentRuntime(Contract):
    role: Literal["harness", "observer"]
    installation: Installation
    issued_at: datetime
    expires_at: datetime
    fixture_management_token: str = Field(min_length=32, max_length=512, repr=False)
    writer_token: str = Field(default="", repr=False)
    mcp_token: str = Field(default="", repr=False)
    target_viewer_token: str = Field(default="", repr=False)
    target_cleanup_token: str = Field(default="", repr=False)

    def bootstrap_result(
        self, role: Literal["harness", "observer"], stack: StackBinding
    ) -> BootstrapResult:
        if (
            self.role != role
            or self.installation.binding_nonce != stack.nonce
            or self.expires_at <= datetime.now(UTC)
        ):
            raise HarnessError("SELFTEST_AGENT_RUNTIME_IDENTITY_OR_EXPIRY")
        if role == "observer" and (
            self.writer_token or self.mcp_token or self.target_cleanup_token
        ):
            raise HarnessError("SELFTEST_OBSERVER_WRITE_CREDENTIAL_FORBIDDEN")
        return BootstrapResult(
            self.installation,
            Credentials(
                "",
                self.writer_token,
                "",
                self.mcp_token,
                "",
                "",
                self.target_viewer_token,
                self.target_cleanup_token,
            ),
        )


class ProductAgentConfig(Contract):
    project_id: UUID
    binding: SelfTestBinding
    harness: AgentIdentity
    observer: AgentIdentity
    host_id: str = Field(min_length=1, max_length=200)

    def verify(self, stack: StackBinding, boot: BootstrapResult) -> None:
        from scripts.selftest.run import _verifier_digest

        installed = boot.installation
        if (
            self.project_id != installed.project_id
            or self.project_id not in self.binding.allowed_project_ids
        ):
            raise HarnessError("SELFTEST_AGENT_PROJECT_MAPPING_MISMATCH")
        actual = (
            self.binding.target_project_id,
            self.binding.target_user_id,
            self.binding.builds.runner,
            self.binding.builds.target,
            self.binding.builds.fixture,
        )
        expected = (
            installed.target_project_id,
            installed.target_user_id,
            stack.candidate_image_digest,
            stack.candidate_image_digest,
            stack.fixture_image_digest.removeprefix("sha256:"),
        )
        if (
            actual != expected
            or self.observer.principal.trusted_verifier
            or self.binding.builds.verifier != _verifier_digest(stack.runtime_profile)
        ):
            raise HarnessError("SELFTEST_AGENT_BUILD_OR_LOCAL_TRUST_MISMATCH")
        if (
            self.harness.principal.id != self.binding.agent_id
            or self.observer.principal.id != self.binding.observer_id
        ):
            raise HarnessError("SELFTEST_AGENT_BINDING_IDENTITY_MISMATCH")


def agent_api(stack: StackBinding, identity: AgentIdentity) -> PublicAPI:
    return PublicAPI(stack.runner_url, identity.token())


def agent_root(project_id: UUID) -> str:
    return f"/agent/projects/{project_id}/self-tests"


async def register(api: PublicAPI, config: ProductAgentConfig, *, observer: bool = False) -> None:
    identity = config.observer if observer else config.harness
    payload = AgentRegistrationRequest(
        binding_id=config.binding.id,
        binding_fingerprint=canonical_digest(config.binding.model_dump(mode="json")),
        environment_fingerprint=config.binding.environment_fingerprint,
        builds=config.binding.builds,
        capabilities=identity.principal.capabilities,
        host_id=config.host_id,
    )
    await api.object(
        "POST",
        agent_root(config.project_id) + "/register",
        object_value(payload.model_dump(mode="json")),
    )


def task_nonce(directory: Path, identifier: UUID) -> str:
    path = directory / str(identifier) / "nonce.json"
    if not path.exists():
        write_json(path, {"nonce": secrets.token_hex(32)})
    nonce = read_json(path).get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 64:
        raise HarnessError("SELFTEST_AGENT_NONCE_INVALID")
    return nonce


async def claim(
    api: PublicAPI,
    project: UUID,
    identifier: UUID,
    revision: int,
    directory: Path,
    *,
    installation: bool = False,
) -> AgentTaskResponse:
    payload = LeaseClaim(expected_revision=revision, nonce=task_nonce(directory, identifier))
    kind = "installations" if installation else "runs"
    result = await api.object(
        "POST",
        f"{agent_root(project)}/{kind}/{identifier}/claim",
        object_value(payload.model_dump(mode="json")),
    )
    task = AgentTaskResponse.model_validate(result)
    if task.task_id != identifier or task.project_id != project or task.nonce != payload.nonce:
        raise HarnessError("SELFTEST_AGENT_CLAIM_IDENTITY_MISMATCH")
    write_json(directory / str(identifier) / "private-lease.json", task)
    return task


def lease_body(task: AgentTaskResponse) -> LeaseRequest:
    return LeaseRequest(lease_token=task.lease_token, nonce=task.nonce)


@asynccontextmanager
async def keep_lease(api: PublicAPI, task: AgentTaskResponse) -> AsyncIterator[None]:
    stopped = asyncio.Event()

    async def renew() -> None:
        current = task
        while True:
            remaining = (current.lease_expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise HarnessError("SELFTEST_AGENT_LEASE_ALREADY_EXPIRED")
            try:
                await asyncio.wait_for(stopped.wait(), timeout=max(0.1, min(30.0, remaining / 3)))
                return
            except TimeoutError:
                kind = "installations" if task.task_kind == "installation" else "runs"
                result = await api.object(
                    "POST",
                    f"{agent_root(task.project_id)}/{kind}/{task.task_id}/lease",
                    object_value(lease_body(task).model_dump(mode="json")),
                )
                current = AgentTaskResponse.model_validate(result)

    async with asyncio.TaskGroup() as group:
        group.create_task(renew())
        try:
            yield
        finally:
            stopped.set()


async def upload(
    api: PublicAPI, task: AgentTaskResponse, *, kind: ArtifactKind, filename: str, content: bytes
) -> ArtifactReference:
    if not content or len(content) > 1024 * 1024:
        raise HarnessError("SELFTEST_AGENT_ARTIFACT_SIZE_LIMIT")
    request = AgentArtifactUpload(
        **lease_body(task).model_dump(),
        kind=kind,
        filename=filename,
        content_type="application/xml" if filename.endswith(".xml") else "application/json",
        content_base64=base64.b64encode(content).decode("ascii"),
    )
    result = await api.object(
        "POST",
        f"{agent_root(task.project_id)}/runs/{task.task_id}/artifacts",
        object_value(request.model_dump(mode="json")),
    )
    return ArtifactReference.model_validate(result)
