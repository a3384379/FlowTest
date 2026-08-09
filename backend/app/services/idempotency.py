import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.governance import IdempotencyRecord

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,128}$")
IDEMPOTENCY_RETENTION_HOURS = 24


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(
        self,
        *,
        key: str | None,
        project_id: UUID,
        actor_key: str,
        operation: str,
        request_payload: object,
        action: Callable[[], Awaitable[BaseModel]],
    ) -> dict[str, Any]:
        if key is None:
            return (await action()).model_dump(mode="json")
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise AppError(
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key 必须为 1-128 个可见 ASCII 字符",
                status_code=422,
            )
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
        try:
            response = (await action()).model_dump(mode="json")
        except Exception:
            await self._abandon(record.id)
            raise
        record.status = "completed"
        record.response_status = 200
        record.response_body = response
        await self._session.commit()
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
        if record is not None:
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
