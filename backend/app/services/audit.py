from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context, get_trace_id
from app.core.logging import redact
from app.models.access import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        *,
        actor_user_id: UUID | None,
        organization_id: UUID | None = None,
        project_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                organization_id=organization_id or _context_organization_id(),
                project_id=project_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=cast(
                    dict[str, Any],
                    redact({"trace_id": get_trace_id(), **(details or {})}),
                ),
                created_at=datetime.now(UTC),
            )
        )


def _context_organization_id() -> UUID | None:
    context = get_tenant_context()
    return context.organization_id if context is not None else None
