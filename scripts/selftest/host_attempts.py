"""Private durable one-attempt reservation and monotonic review/phase transitions."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field
from scripts.selftest.contracts import Contract, Sha256
from scripts.selftest.host_contracts import ReviewedWorkflowBinding
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.io import HarnessError

State = Literal[
    "reserved",
    "workflow_running",
    "waiting_workflow_review",
    "case_ready",
    "case_running",
    "waiting_case_review",
    "sealed",
    "error",
]


class AttemptRecord(Contract):
    authorization_id: UUID
    authorization_digest: Sha256
    attempt_id: UUID
    state: State
    revision: int = Field(ge=1, strict=True)
    created_at: datetime
    updated_at: datetime
    workflow_proposal_ids: tuple[UUID, ...] = Field(default=(), max_length=3)
    case_proposal_ids: tuple[UUID, ...] = Field(default=(), max_length=3)
    reviewed_workflows: tuple[ReviewedWorkflowBinding, ...] = Field(default=(), max_length=3)
    reason_code: str | None = Field(default=None, max_length=100)
    source_manifest_digest: Sha256 | None = None


class AttemptStore:
    """The deployment-owned root is fixed by H; neither browser nor model chooses it."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise HarnessError("HOST_ATTEMPT_DIRECTORY_NOT_PRIVATE")
        self.directory = directory

    def path(self, authorization_id: UUID) -> Path:
        return self.directory / (str(authorization_id) + ".json")

    def reserve(self, grant: VerifiedGrant, attempt_id: UUID) -> AttemptRecord:
        now = datetime.now(UTC)
        if grant.authorization.expires_at <= now:
            raise HarnessError("HOST_AUTHORIZATION_EXPIRED")
        record = AttemptRecord(
            authorization_id=grant.authorization.authorization_id,
            authorization_digest=grant.digest,
            attempt_id=attempt_id,
            state="reserved",
            revision=1,
            created_at=now,
            updated_at=now,
        )
        self._create(self.path(record.authorization_id), record)
        return record

    def _create(self, path: Path, record: AttemptRecord) -> None:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise HarnessError("HOST_AUTHORIZATION_ATTEMPT_ALREADY_RESERVED") from None
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(record.model_dump_json().encode())
            stream.flush()
            os.fsync(stream.fileno())

    def read(self, grant: VerifiedGrant) -> AttemptRecord:
        path = self.path(grant.authorization.authorization_id)
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise HarnessError("HOST_ATTEMPT_OWNERSHIP_CHANGED")
        record = AttemptRecord.model_validate_json(path.read_bytes())
        if record.authorization_digest != grant.digest:
            raise HarnessError("HOST_ATTEMPT_AUTHORIZATION_CHANGED")
        return record

    @contextmanager
    def _lock(self, grant: VerifiedGrant) -> Iterator[None]:
        path = self.path(grant.authorization.authorization_id).with_suffix(".lock")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise HarnessError("HOST_ATTEMPT_TRANSITION_IN_PROGRESS") from None
        try:
            yield
        finally:
            os.close(descriptor)
            path.unlink()

    def transition(
        self,
        grant: VerifiedGrant,
        previous: AttemptRecord,
        state: State,
        *,
        proposal_ids: tuple[UUID, ...] = (),
        reviewed_workflows: tuple[ReviewedWorkflowBinding, ...] = (),
        reason_code: str | None = None,
        source_manifest_digest: Sha256 | None = None,
    ) -> AttemptRecord:
        with self._lock(grant):
            current = self.read(grant)
            if current != previous:
                raise HarnessError("HOST_ATTEMPT_REVISION_CHANGED")
            self._check_transition(current.state, state)
            update = current.model_dump(mode="json")
            update.update(
                state=state,
                revision=current.revision + 1,
                updated_at=datetime.now(UTC),
                reason_code=reason_code,
            )
            if source_manifest_digest is not None:
                update["source_manifest_digest"] = source_manifest_digest
            if state == "waiting_workflow_review":
                update["workflow_proposal_ids"] = proposal_ids
            elif state == "waiting_case_review":
                update["case_proposal_ids"] = proposal_ids
            elif state == "case_ready":
                update["reviewed_workflows"] = reviewed_workflows
            result = AttemptRecord.model_validate(update)
            temporary = self.path(current.authorization_id).with_suffix(".next")
            self._create(temporary, result)
            os.replace(temporary, self.path(current.authorization_id))
            return result

    @staticmethod
    def _check_transition(previous: State, following: State) -> None:
        allowed = {
            "reserved": {"workflow_running", "error"},
            "workflow_running": {"waiting_workflow_review", "error"},
            "waiting_workflow_review": {"case_ready", "error"},
            "case_ready": {"case_running", "error"},
            "case_running": {"waiting_case_review", "error"},
            "waiting_case_review": {"sealed", "error"},
        }
        if following not in allowed.get(previous, set()):
            raise HarnessError("HOST_ATTEMPT_TRANSITION_FORBIDDEN")


def export_record(record: AttemptRecord) -> bytes:
    return json.dumps(record.model_dump(mode="json"), sort_keys=True).encode()
