import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.governance import IdempotencyRecord, OrganizationIdempotencyRecord

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,128}$")
IDEMPOTENCY_RETENTION_HOURS = 24


def require_idempotency_key(key: str | None) -> str:
    if key is None:
        raise AppError(
            code="IDEMPOTENCY_KEY_REQUIRED",
            message="必须提供 Idempotency-Key",
            status_code=422,
        )
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise AppError(
            code="INVALID_IDEMPOTENCY_KEY",
            message="Idempotency-Key 必须为 1-128 个可见 ASCII 字符",
            status_code=422,
        )
    return key


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def completed_response(
        self,
        *,
        key: str,
        project_id: UUID,
        actor_key: str,
        operation: str,
        request_payload: object,
    ) -> dict[str, Any] | None:
        """Read a receipt without claiming; callers must authorize access first."""
        require_idempotency_key(key)
        record = await self._find(
            project_id=project_id, actor_key=actor_key, operation=operation, key=key
        )
        if record is None:
            return None
        _, response = await self._existing(record, _request_hash(request_payload))
        return response

    async def run(
        self,
        *,
        key: str | None,
        project_id: UUID,
        actor_key: str,
        operation: str,
        request_payload: object,
        action: Callable[[], Awaitable[BaseModel]],
        atomic_action: bool = False,
        capture_server_timings: bool = False,
    ) -> dict[str, Any]:
        run_started = perf_counter()
        if key is None:
            return (await action()).model_dump(mode="json")
        require_idempotency_key(key)
        request_hash = _request_hash(request_payload)
        record, cached = await self._claim(
            key=key,
            project_id=project_id,
            actor_key=actor_key,
            operation=operation,
            request_hash=request_hash,
        )
        if cached is not None:
            return cached
        record_id = record.id
        try:
            response = (await action()).model_dump(mode="json")
            record.status = "completed"
            record.response_status = 200
            record.response_body = response
            commit_started = perf_counter()
            await self._session.commit()
            if capture_server_timings:
                timings = response.get("timings_ms")
                if isinstance(timings, dict):
                    timings["transaction"] = _elapsed_ms(commit_started)
                    timings["total"] = _elapsed_ms(run_started)
                    record.response_body = response
                    await self._session.commit()
        except Exception:
            await self._session.rollback()
            # Legacy actions can commit or send requests before failing. Their outcome
            # is uncertain, so retaining the claim prevents automatic effect replay.
            if atomic_action:
                await self._abandon(record_id)
            raise
        return response

    async def _claim(
        self,
        *,
        key: str,
        project_id: UUID,
        actor_key: str,
        operation: str,
        request_hash: str,
    ) -> tuple[IdempotencyRecord, dict[str, Any] | None]:
        existing = await self._find(
            project_id=project_id,
            actor_key=actor_key,
            operation=operation,
            key=key,
        )
        if existing is not None:
            return await self._existing(existing, request_hash)
        record = IdempotencyRecord(
            project_id=project_id,
            actor_key=actor_key,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            status="pending",
            response_status=None,
            response_body=None,
            expires_at=datetime.now(UTC) + timedelta(hours=IDEMPOTENCY_RETENTION_HOURS),
        )
        self._session.add(record)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            concurrent = await self._find(
                project_id=project_id,
                actor_key=actor_key,
                operation=operation,
                key=key,
            )
            if concurrent is None:
                raise
            return await self._existing(concurrent, request_hash)
        await self._session.refresh(record)
        return record, None

    async def _existing(
        self, record: IdempotencyRecord, request_hash: str
    ) -> tuple[IdempotencyRecord, dict[str, Any] | None]:
        if record.request_hash != request_hash:
            raise AppError(
                code="IDEMPOTENCY_KEY_REUSED",
                message="同一 Idempotency-Key 不能用于不同请求",
                status_code=409,
            )
        if record.status == "pending":
            raise AppError(
                code="IDEMPOTENCY_IN_PROGRESS",
                message="相同操作正在处理中",
                status_code=409,
            )
        if record.response_body is None:
            raise RuntimeError("Completed idempotency record has no response")
        return record, dict(record.response_body)

    async def _find(
        self,
        *,
        project_id: UUID,
        actor_key: str,
        operation: str,
        key: str,
    ) -> IdempotencyRecord | None:
        return (
            await self._session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.project_id == project_id,
                    IdempotencyRecord.actor_key == actor_key,
                    IdempotencyRecord.operation == operation,
                    IdempotencyRecord.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()

    async def _abandon(self, record_id: UUID) -> None:
        record = await self._session.get(IdempotencyRecord, record_id)
        if record is not None and record.status == "pending":
            await self._session.delete(record)
            await self._session.commit()


class OrganizationIdempotencyService:
    """Idempotency receipts for operations that do not have a project yet."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def completed_response(
        self,
        *,
        key: str,
        organization_id: UUID,
        actor_key: str,
        operation: str,
        request_payload: object,
    ) -> dict[str, Any] | None:
        """Read a completed receipt after current identity authorization.

        Callers deliberately perform this lookup before re-validating mutable
        business state.  A completed receipt is a historical operation result;
        it must not be lost merely because a later state change made the
        original resource unavailable or different.
        """

        require_idempotency_key(key)
        record = await self._find(
            organization_id=organization_id,
            actor_key=actor_key,
            operation=operation,
            key=key,
        )
        if record is None:
            return None
        _, response = await self._existing(record, _request_hash(request_payload))
        if response is None:
            return None
        response["idempotency_replayed"] = True
        return response

    async def run(
        self,
        *,
        key: str | None,
        organization_id: UUID,
        actor_key: str,
        operation: str,
        request_payload: object,
        action: Callable[[], Awaitable[BaseModel]],
        atomic_action: bool = False,
    ) -> dict[str, Any]:
        if key is None:
            return (await action()).model_dump(mode="json")
        require_idempotency_key(key)
        request_hash = _request_hash(request_payload)
        record, cached = await self._claim(
            key=key,
            organization_id=organization_id,
            actor_key=actor_key,
            operation=operation,
            request_hash=request_hash,
        )
        if cached is not None:
            cached["idempotency_replayed"] = True
            return cached
        record_id = record.id
        try:
            response = (await action()).model_dump(mode="json")
            record.status = "completed"
            record.response_status = 200
            record.response_body = response
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            if atomic_action:
                await self._abandon(record_id)
            raise
        return response

    async def _claim(
        self,
        *,
        key: str,
        organization_id: UUID,
        actor_key: str,
        operation: str,
        request_hash: str,
    ) -> tuple[OrganizationIdempotencyRecord, dict[str, Any] | None]:
        existing = await self._find(
            organization_id=organization_id,
            actor_key=actor_key,
            operation=operation,
            key=key,
        )
        if existing is not None:
            return await self._existing(existing, request_hash)
        record = OrganizationIdempotencyRecord(
            organization_id=organization_id,
            actor_key=actor_key,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            status="pending",
            response_status=None,
            response_body=None,
            expires_at=datetime.now(UTC) + timedelta(hours=IDEMPOTENCY_RETENTION_HOURS),
        )
        self._session.add(record)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            concurrent = await self._find(
                organization_id=organization_id,
                actor_key=actor_key,
                operation=operation,
                key=key,
            )
            if concurrent is None:
                raise
            return await self._existing(concurrent, request_hash)
        await self._session.refresh(record)
        return record, None

    async def _existing(
        self,
        record: OrganizationIdempotencyRecord,
        request_hash: str,
    ) -> tuple[OrganizationIdempotencyRecord, dict[str, Any] | None]:
        if record.request_hash != request_hash:
            raise AppError(
                code="IDEMPOTENCY_KEY_REUSED",
                message="同一 Idempotency-Key 不能用于不同请求",
                status_code=409,
            )
        if record.status == "pending":
            raise AppError(
                code="IDEMPOTENCY_IN_PROGRESS",
                message="相同操作正在处理中",
                status_code=409,
            )
        if record.response_body is None:
            raise RuntimeError("Completed organization idempotency record has no response")
        return record, dict(record.response_body)

    async def _find(
        self,
        *,
        organization_id: UUID,
        actor_key: str,
        operation: str,
        key: str,
    ) -> OrganizationIdempotencyRecord | None:
        return (
            await self._session.execute(
                select(OrganizationIdempotencyRecord).where(
                    OrganizationIdempotencyRecord.organization_id == organization_id,
                    OrganizationIdempotencyRecord.actor_key == actor_key,
                    OrganizationIdempotencyRecord.operation == operation,
                    OrganizationIdempotencyRecord.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()

    async def _abandon(self, record_id: UUID) -> None:
        record = await self._session.get(OrganizationIdempotencyRecord, record_id)
        if record is not None and record.status == "pending":
            await self._session.delete(record)
            await self._session.commit()


def _request_hash(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()
