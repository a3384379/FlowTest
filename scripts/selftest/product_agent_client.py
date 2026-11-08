"""Deployment JWT identities and leased API transport for external H/O processes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import jwt
from pydantic import Field
from scripts.selftest.bootstrap import BootstrapResult, Credentials, Installation
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    object_value,
    read_json,
    write_json,
)
from scripts.selftest.local_stack import StackBinding

from app.core.self_tests import SelfTestBinding, SelfTestPrincipal
from app.schemas.self_tests import (
    AgentArtifactUpload,
    AgentRegistrationRequest,
    AgentTaskResponse,
    ArtifactKind,
    ArtifactReference,
    BatchResponse,
    LeaseClaim,
    LeaseRequest,
    MaterializedReceipt,
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
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, candidate = tempfile.mkstemp(prefix=".nonce-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(json.dumps({"nonce": secrets.token_hex(32)}).encode())
            output.flush()
            os.fsync(output.fileno())
        # Publish the complete inode exclusively; readers never observe a partial file.
        with suppress(FileExistsError):
            os.link(candidate, path)
        _sync_task_directory(path.parent)
        return _read_task_nonce(path)
    finally:
        Path(candidate).unlink(missing_ok=True)


def _read_task_nonce(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise HarnessError("SELFTEST_AGENT_NONCE_INVALID")
        nonce = read_json(path).get("nonce")
    except (OSError, ValueError) as error:
        raise HarnessError("SELFTEST_AGENT_NONCE_INVALID") from error
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
                try:
                    result = await post_task_receipt(
                        api,
                        f"{agent_root(task.project_id)}/{kind}/{task.task_id}/lease",
                        object_value(lease_body(task).model_dump(mode="json")),
                    )
                except HarnessError as error:
                    if str(error).startswith("SELFTEST_HTTP_409:SELFTEST_LEASE_RELEASED:"):
                        return
                    raise
                current = AgentTaskResponse.model_validate(result)

    async with asyncio.TaskGroup() as group:
        group.create_task(renew())
        try:
            yield
        finally:
            stopped.set()


async def upload(
    api: PublicAPI,
    task: AgentTaskResponse,
    *,
    kind: ArtifactKind,
    filename: str,
    content: bytes,
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


def staged_receipt(task: AgentTaskResponse, directory: Path) -> MaterializedReceipt | None:
    path = directory / "materialized-receipt.json"
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise HarnessError("SELFTEST_MATERIALIZED_LOCAL_RECEIPT_CHANGED")
    receipt = MaterializedReceipt.model_validate(read_json(path))
    if (
        receipt.stage != "stage"
        or receipt.nonce != task.nonce
        or receipt.lease_token != task.lease_token
    ):
        raise HarnessError("SELFTEST_MATERIALIZED_LOCAL_RECEIPT_CHANGED")
    return receipt


async def stage_materialization(
    api: PublicAPI,
    task: AgentTaskResponse,
    receipt: MaterializedReceipt,
    directory: Path,
) -> BatchResponse:
    previous = staged_receipt(task, directory)
    if previous is not None and previous != receipt:
        raise HarnessError("SELFTEST_MATERIALIZED_LOCAL_RECEIPT_CHANGED")
    write_json(directory / "materialized-receipt.json", receipt)
    _sync_task_directory(directory)
    return BatchResponse.model_validate(
        await post_task_receipt(
            api,
            f"{agent_root(task.project_id)}/runs/{task.task_id}/materialized",
            object_value(receipt.model_dump(mode="json")),
        )
    )


async def finalize_materialization(
    api: PublicAPI, task: AgentTaskResponse, directory: Path
) -> BatchResponse:
    receipt = staged_receipt(task, directory)
    if receipt is None:
        raise HarnessError("SELFTEST_MATERIALIZED_LOCAL_RECEIPT_MISSING")
    manifest, selection = directory / "manifest.json", directory / "selection.json"
    for path in (manifest, selection):
        if not path.is_file() or path.is_symlink():
            raise HarnessError("SELFTEST_OBSERVER_MANIFEST_NOT_FROZEN")
    finalization = MaterializedReceipt.model_validate(
        {
            **receipt.model_dump(mode="json"),
            "stage": "finalize",
            "observer_manifest_digest": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "observer_selection_digest": hashlib.sha256(selection.read_bytes()).hexdigest(),
        }
    )
    path = directory / "materialized-finalization.json"
    if path.exists() and MaterializedReceipt.model_validate(read_json(path)) != finalization:
        raise HarnessError("SELFTEST_OBSERVER_MANIFEST_CHANGED")
    write_json(path, finalization)
    _sync_task_directory(directory)
    result = BatchResponse.model_validate(
        await post_task_receipt(
            api,
            f"{agent_root(task.project_id)}/runs/{task.task_id}/materialized",
            object_value(finalization.model_dump(mode="json")),
        )
    )
    write_json(
        directory / "materialized-acknowledged.json",
        {
            "batch_id": str(task.task_id),
            "resource_digest": result.resource_digest,
            "finalization_digest": canonical_digest(
                finalization.model_dump(mode="json", exclude={"lease_token"})
            ),
        },
    )
    _sync_task_directory(directory)
    return result


async def post_task_receipt(api: PublicAPI, path: str, payload: JsonObject) -> JsonObject:
    for attempt in range(3):
        try:
            return await api.object("POST", path, payload)
        except HarnessError as error:
            conflict = any(
                str(error).startswith(f"SELFTEST_HTTP_409:{code}:")
                for code in (
                    "SELFTEST_BATCH_BUSY",
                    "SELFTEST_INSTALLATION_BUSY",
                )
            )
            if not conflict or attempt == 2:
                raise
            await asyncio.sleep(0)
    raise HarnessError("SELFTEST_TASK_RECEIPT_RETRY_EXHAUSTED")


def _sync_task_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
