"""Private per-phase installation receipts; ambiguous creates never repeat blindly."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field
from scripts.selftest.contracts import Contract, canonical_digest
from scripts.selftest.io import (
    HarnessError,
    JsonObject,
    PublicAPI,
    read_json,
    text_value,
    write_json,
)


class CreatedResource(Contract):
    id: UUID
    organization_id: UUID | None = None


class BootstrapPhaseReceipt(Contract):
    phase: str = Field(min_length=1, max_length=100)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending", "completed"]
    resource: CreatedResource | None = None


class BootstrapJournalDocument(Contract):
    schema_version: Literal["flowtest-bootstrap-journal-v1"] = "flowtest-bootstrap-journal-v1"
    binding_nonce: str
    created_at: datetime
    phases: tuple[BootstrapPhaseReceipt, ...] = Field(default=(), max_length=50)


class BootstrapJournal:
    def __init__(self, directory: Path, nonce: str) -> None:
        self.path = directory / "bootstrap-journal.json"
        self.document = (
            BootstrapJournalDocument.model_validate(read_json(self.path))
            if self.path.exists()
            else BootstrapJournalDocument(binding_nonce=nonce, created_at=datetime.now(UTC))
        )
        if self.document.binding_nonce != nonce:
            raise HarnessError("SELFTEST_JOURNAL_BINDING_MISMATCH")

    def _save(self, receipt: BootstrapPhaseReceipt) -> None:
        remaining = tuple(item for item in self.document.phases if item.phase != receipt.phase)
        self.document = self.document.model_copy(update={"phases": (*remaining, receipt)})
        write_json(self.path, self.document)

    async def create(
        self,
        api: PublicAPI,
        phase: str,
        path: str,
        payload: JsonObject,
        *,
        read_prefix: str | None = None,
    ) -> JsonObject:
        fingerprint = canonical_digest({"method": "POST", "path": path, "payload": payload})
        previous = next((item for item in self.document.phases if item.phase == phase), None)
        if previous is not None:
            if previous.request_digest != fingerprint:
                raise HarnessError("SELFTEST_BOOTSTRAP_PHASE_CONFLICT")
            if previous.status != "completed" or previous.resource is None:
                raise HarnessError("SELFTEST_BOOTSTRAP_UNKNOWN_RESULT_NEEDS_REVIEW")
            if read_prefix is not None:
                response = await api.object("GET", f"{read_prefix}/{previous.resource.id}")
                if response.get("id") != str(previous.resource.id):
                    raise HarnessError("SELFTEST_BOOTSTRAP_RESOURCE_CHANGED")
            return previous.resource.model_dump(mode="json", exclude_none=True)
        self._save(BootstrapPhaseReceipt(phase=phase, request_digest=fingerprint, status="pending"))
        result = await api.object("POST", path, payload)
        resource = CreatedResource(
            id=UUID(text_value(result["id"])),
            organization_id=UUID(text_value(result["organization_id"]))
            if result.get("organization_id") is not None
            else None,
        )
        self._save(
            BootstrapPhaseReceipt(
                phase=phase,
                request_digest=fingerprint,
                status="completed",
                resource=resource,
            )
        )
        return resource.model_dump(mode="json", exclude_none=True)


@contextmanager
def bootstrap_lock(directory: Path, nonce: str) -> Iterator[None]:
    lock = directory / ".bootstrap.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as error:
        raise HarnessError("SELFTEST_BOOTSTRAP_IN_PROGRESS_OR_NEEDS_REVIEW") from error
    try:
        write_json(lock / "owner.json", {"binding_nonce": nonce})
        yield
    finally:
        (lock / "owner.json").unlink(missing_ok=True)
        lock.rmdir()
