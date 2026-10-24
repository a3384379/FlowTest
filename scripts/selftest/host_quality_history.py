"""Private append-only benchmark attempts across separately authorized grants."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import jwt
from pydantic import Field, model_validator
from scripts.selftest.contracts import Contract, Sha256, canonical_digest
from scripts.selftest.host_launch import VerifiedGrant
from scripts.selftest.host_quality import (
    HostQualityReport,
    QualityAttempt,
    QualityTaskSet,
    quality_report,
)
from scripts.selftest.io import HarnessError, read_json, write_json
from scripts.selftest.product_agent_client import AgentIdentity

from app.core.self_tests import SelfTestPrincipal


class QualitySeries(Contract):
    project_id: UUID
    taskset: QualityTaskSet
    model: str
    provider: str
    skill_digest: Sha256
    cli_version: str
    verifier: SelfTestPrincipal

    @model_validator(mode="after")
    def independent_verifier(self) -> QualitySeries:
        if (
            set(self.verifier.capabilities) != {"verify"}
            or self.project_id not in self.verifier.allowed_project_ids
        ):
            raise ValueError(
                "quality history requires an independently configured project verifier"
            )
        return self

    @classmethod
    def frozen(
        cls, grant: VerifiedGrant, taskset: QualityTaskSet, verifier: SelfTestPrincipal
    ) -> QualitySeries:
        auth = grant.authorization
        return cls(
            project_id=auth.project_id,
            taskset=taskset,
            model=auth.model,
            provider=auth.provider,
            skill_digest=auth.skill_digest,
            cli_version=auth.cli_version,
            verifier=verifier,
        )


class QualityHistoryEvent(Contract):
    sequence: int = Field(ge=1, le=300)
    previous_digest: Sha256
    kind: Literal["reserved", "observed", "failed"]
    authorization_id: UUID
    authorization_digest: Sha256
    task_digest: Sha256
    batch_key: str
    attempt_id: UUID
    ordinal: int = Field(ge=1, le=100)
    recorded_at: datetime
    attempts: tuple[QualityAttempt, ...] = Field(min_length=1, max_length=100)
    observer_signature: str | None = Field(default=None, max_length=16384)


class QualityHistoryHead(Contract):
    series: QualitySeries
    sequence: int = Field(ge=0, le=300)
    digest: Sha256


class QualityHistory:
    def __init__(self, directory: Path, series: QualitySeries) -> None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise HarnessError("HOST_QUALITY_HISTORY_NOT_PRIVATE")
        self.directory = directory
        self.series = series
        self.head = directory / "head.json"

    @classmethod
    def for_task(
        cls,
        state_root: Path,
        grant: VerifiedGrant,
        taskset: QualityTaskSet,
        verifier: SelfTestPrincipal,
    ) -> QualityHistory:
        identity = canonical_digest(
            {
                "project": str(grant.authorization.project_id),
                "taskset": taskset.model_dump(mode="json"),
            }
        )
        return cls(
            state_root / "host-quality-history" / identity,
            QualitySeries.frozen(grant, taskset, verifier),
        )

    @contextmanager
    def _lock(self) -> Iterator[None]:
        try:
            descriptor = os.open(
                self.directory / ".lock",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
        except FileExistsError:
            raise HarnessError("HOST_QUALITY_HISTORY_BUSY") from None
        try:
            yield
        finally:
            os.close(descriptor)
            (self.directory / ".lock").unlink()

    def _read(self) -> tuple[QualityHistoryHead, tuple[QualityHistoryEvent, ...]]:
        zero = canonical_digest(self.series.model_dump(mode="json"))
        if not self.head.exists():
            if tuple(self.directory.glob("event-*.json")):
                raise HarnessError("HOST_QUALITY_HISTORY_HEAD_MISSING")
            return QualityHistoryHead(series=self.series, sequence=0, digest=zero), ()
        head = QualityHistoryHead.model_validate(read_json(self.head))
        if head.series != self.series:
            raise HarnessError("HOST_QUALITY_HISTORY_SCOPE_CHANGED")
        paths = sorted(self.directory.glob("event-*.json"))
        if len(paths) != head.sequence or len(paths) > 300:
            raise HarnessError("HOST_QUALITY_HISTORY_INCOMPLETE")
        events: list[QualityHistoryEvent] = []
        previous = zero
        for sequence, path in enumerate(paths, start=1):
            if path.name != f"event-{sequence:03}.json" or path.is_symlink():
                raise HarnessError("HOST_QUALITY_HISTORY_SEQUENCE_CHANGED")
            event = QualityHistoryEvent.model_validate(read_json(path))
            if event.sequence != sequence or event.previous_digest != previous:
                raise HarnessError("HOST_QUALITY_HISTORY_CHAIN_CHANGED")
            self._verify_event(event, tuple(events))
            events.append(event)
            previous = canonical_digest(event.model_dump(mode="json"))
        if previous != head.digest:
            raise HarnessError("HOST_QUALITY_HISTORY_HEAD_CHANGED")
        return head, tuple(events)

    def _append(self, head: QualityHistoryHead, event: QualityHistoryEvent) -> None:
        path = self.directory / f"event-{event.sequence:03}.json"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise HarnessError("HOST_QUALITY_HISTORY_EVENT_EXISTS") from None
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(event.model_dump_json().encode())
            stream.flush()
            os.fsync(stream.fileno())
        write_json(
            self.head,
            QualityHistoryHead(
                series=head.series,
                sequence=event.sequence,
                digest=canonical_digest(event.model_dump(mode="json")),
            ),
        )

    def reserve(self, grant: VerifiedGrant, attempt_id: UUID, *, assisted: bool = False) -> int:
        if QualitySeries.frozen(grant, self.series.taskset, self.series.verifier) != self.series:
            raise HarnessError("HOST_QUALITY_HISTORY_SCOPE_CHANGED")
        with self._lock():
            head, events = self._read()
            same = [
                item
                for item in events
                if item.authorization_id == grant.authorization.authorization_id
            ]
            if same:
                first = same[0]
                if first.authorization_digest != grant.digest or first.attempt_id != attempt_id:
                    raise HarnessError("HOST_QUALITY_HISTORY_GRANT_REUSED")
                return first.ordinal
            ordinal = 1 + sum(item.kind == "reserved" for item in events)
            attempts = tuple(
                QualityAttempt(
                    task_id=item.task_id,
                    variant_key=item.variant_key,
                    attempt_id=attempt_id,
                    ordinal=ordinal,
                    evidence_digest=grant.digest,
                    review_mode=grant.authorization.review_mode,
                    generation_kind="assisted" if assisted else "model",
                )
                for item in self.series.taskset.tasks
                if item.exclusion_reason is None
            )
            event = QualityHistoryEvent(
                sequence=head.sequence + 1,
                previous_digest=head.digest,
                kind="reserved",
                authorization_id=grant.authorization.authorization_id,
                authorization_digest=grant.digest,
                task_digest=grant.authorization.task_digest,
                batch_key=grant.authorization.batch_key,
                attempt_id=attempt_id,
                ordinal=ordinal,
                recorded_at=datetime.now(UTC),
                attempts=attempts,
            )
            self._append(head, event)
            return ordinal

    def finish(
        self,
        grant: VerifiedGrant,
        attempt_id: UUID,
        attempts: tuple[QualityAttempt, ...],
        *,
        failed: bool = False,
        signer: AgentIdentity | None = None,
    ) -> HostQualityReport:
        with self._lock():
            head, events = self._read()
            current = [item for item in events if item.attempt_id == attempt_id]
            if not current or current[0].authorization_digest != grant.digest:
                raise HarnessError("HOST_QUALITY_HISTORY_RESERVATION_MISSING")
            first = current[0]
            values = tuple(item.model_copy(update={"ordinal": first.ordinal}) for item in attempts)
            wanted = {(item.task_id, item.variant_key) for item in first.attempts}
            if (
                {(item.task_id, item.variant_key) for item in values} != wanted
                or any(item.attempt_id != attempt_id for item in values)
                or len(values) != len(wanted)
            ):
                raise HarnessError("HOST_QUALITY_HISTORY_TASK_SET_CHANGED")
            kinds = {
                (item.task_id, item.variant_key): item.generation_kind for item in first.attempts
            }
            if any(
                item.generation_kind != kinds[(item.task_id, item.variant_key)] for item in values
            ):
                raise HarnessError("HOST_QUALITY_HISTORY_GENERATION_KIND_CHANGED")
            kind: Literal["failed", "observed"] = "failed" if failed else "observed"
            if len(current) > 1:
                return self._existing(current[-1], kind, values, head, events, signer)
            event = first.model_copy(
                update={
                    "sequence": head.sequence + 1,
                    "previous_digest": head.digest,
                    "kind": kind,
                    "recorded_at": datetime.now(UTC),
                    "attempts": values,
                }
            )
            if not failed:
                if signer is None or signer.principal != self.series.verifier:
                    raise HarnessError("HOST_QUALITY_OBSERVER_SIGNATURE_REQUIRED")
                self._checkpoint(signer, head, events)
                event = event.model_copy(update={"observer_signature": self._sign(signer, event)})
            self._verify_event(event, events)
            self._append(head, event)
            if signer is not None:
                self._save_checkpoint(signer, (*events, event))
            return self._report((*events, event))

    def report(self, *, signer: AgentIdentity | None = None) -> HostQualityReport:
        head, events = self._read()
        if signer is not None:
            self._checkpoint(signer, head, events)
        return self._report(events)

    def _report(self, events: tuple[QualityHistoryEvent, ...]) -> HostQualityReport:
        latest = {item.attempt_id: item for item in events}
        ordered = sorted(latest.values(), key=lambda item: item.ordinal)
        return quality_report(
            self.series.taskset, tuple(attempt for item in ordered for attempt in item.attempts)
        )

    def _verify_event(
        self, event: QualityHistoryEvent, prior: tuple[QualityHistoryEvent, ...]
    ) -> None:
        if event.kind == "reserved":
            if event.ordinal != 1 + sum(item.kind == "reserved" for item in prior) or any(
                item.attempt_id == event.attempt_id
                or item.authorization_id == event.authorization_id
                for item in prior
            ):
                raise HarnessError("HOST_QUALITY_HISTORY_SEQUENCE_CHANGED")
        else:
            previous = [item for item in prior if item.attempt_id == event.attempt_id]
            if (
                len(previous) != 1
                or previous[0].kind != "reserved"
                or any(
                    getattr(event, field) != getattr(previous[0], field)
                    for field in (
                        "authorization_id",
                        "authorization_digest",
                        "task_digest",
                        "batch_key",
                        "ordinal",
                    )
                )
            ):
                raise HarnessError("HOST_QUALITY_HISTORY_TERMINAL_REWRITE")
        if event.kind != "observed":
            for item in event.attempts:
                flags = (
                    item.protocol_available,
                    item.design_valid,
                    item.executable_asset_generated,
                    item.independent_execution_match,
                    item.fixed_defect_detected,
                    item.source_complete,
                )
                if True in flags or item.landed_oracle_ids or item.assisted is not None:
                    raise HarnessError("HOST_QUALITY_UNSIGNED_MEASUREMENT_FORBIDDEN")
            return
        principal = self.series.verifier
        if event.observer_signature is None:
            raise HarnessError("HOST_QUALITY_OBSERVER_SIGNATURE_REQUIRED")
        claims = jwt.decode(
            event.observer_signature,
            principal.public_key,
            algorithms=[principal.algorithm],
            issuer=principal.issuer,
            audience=principal.audience + ":quality",
            options={"require": ["iss", "aud", "sub", "iat", "quality_digest"]},
        )
        if claims["sub"] != principal.subject or claims["quality_digest"] != self._event_digest(
            event
        ):
            raise HarnessError("HOST_QUALITY_OBSERVER_SIGNATURE_CHANGED")

    def _event_digest(self, event: QualityHistoryEvent) -> str:
        return canonical_digest(
            {
                "series": self.series.model_dump(mode="json"),
                "event": event.model_dump(mode="json", exclude={"observer_signature"}),
            }
        )

    def _sign(self, signer: AgentIdentity, event: QualityHistoryEvent) -> str:
        path = signer.private_key_file
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise HarnessError("HOST_QUALITY_OBSERVER_KEY_NOT_PRIVATE")
        principal = signer.principal
        return jwt.encode(
            {
                "iss": principal.issuer,
                "sub": principal.subject,
                "aud": principal.audience + ":quality",
                "iat": datetime.now(UTC),
                "quality_digest": self._event_digest(event),
            },
            path.read_bytes(),
            algorithm=principal.algorithm,
        )

    def _checkpoint_path(self, signer: AgentIdentity) -> Path:
        if signer.principal != self.series.verifier:
            raise HarnessError("HOST_QUALITY_OBSERVER_IDENTITY_CHANGED")
        root = signer.private_key_file.parent / "host-quality-checkpoints"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or root.stat().st_mode & 0o077:
            raise HarnessError("HOST_QUALITY_CHECKPOINT_NOT_PRIVATE")
        return root / (canonical_digest(self.series.model_dump(mode="json")) + ".json")

    def _checkpoint(
        self,
        signer: AgentIdentity,
        head: QualityHistoryHead,
        events: tuple[QualityHistoryEvent, ...],
    ) -> None:
        path = self._checkpoint_path(signer)
        if not path.exists():
            if any(item.kind == "observed" for item in events):
                raise HarnessError("HOST_QUALITY_CHECKPOINT_MISSING")
            return
        checkpoint = QualityHistoryHead.model_validate(read_json(path))
        if checkpoint.sequence < 1 or not events:
            raise HarnessError("HOST_QUALITY_CHECKPOINT_CORRUPT")
        if checkpoint.series != self.series or checkpoint.sequence > head.sequence:
            raise HarnessError("HOST_QUALITY_CHECKPOINT_ROLLBACK")
        digest = canonical_digest(events[checkpoint.sequence - 1].model_dump(mode="json"))
        if digest != checkpoint.digest:
            raise HarnessError("HOST_QUALITY_CHECKPOINT_FORK")

    def _save_checkpoint(
        self, signer: AgentIdentity, events: tuple[QualityHistoryEvent, ...]
    ) -> None:
        path = self._checkpoint_path(signer)
        write_json(
            path,
            QualityHistoryHead(
                series=self.series,
                sequence=len(events),
                digest=canonical_digest(events[-1].model_dump(mode="json")),
            ),
        )

    def _existing(
        self,
        last: QualityHistoryEvent,
        kind: Literal["failed", "observed"],
        values: tuple[QualityAttempt, ...],
        head: QualityHistoryHead,
        events: tuple[QualityHistoryEvent, ...],
        signer: AgentIdentity | None,
    ) -> HostQualityReport:
        if last.kind != kind or last.attempts != values:
            raise HarnessError("HOST_QUALITY_HISTORY_TERMINAL_REWRITE")
        if kind == "observed":
            if signer is None:
                raise HarnessError("HOST_QUALITY_OBSERVER_SIGNATURE_REQUIRED")
            self._checkpoint(signer, head, events)
        return self._report(events)
