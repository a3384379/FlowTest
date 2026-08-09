from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        *,
        actor_user_id: UUID | None,
        project_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                project_id=project_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details or {},
                created_at=datetime.now(UTC),
            )
        )
