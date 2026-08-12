import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.reporting import NotificationEvent, classify_failure
from app.models.access import User
from app.models.reporting import NotificationDelivery, NotificationWebhook
from app.models.tasking import TestPlanRun
from app.models.workflows import WorkflowExecution
from app.repositories.reporting import ReportingRepository
from app.services.audit import AuditService
from app.services.outbound import OutboundRequestGuard, outbound_request_guard
from app.services.projects import ProjectService

DELIVERY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class CreatedNotificationWebhook:
    model: NotificationWebhook
    secret: str


class NotificationWebhookService:
    def __init__(self, session: AsyncSession, *, secrets_box: SecretBox = secret_box) -> None:
        self._session = session
        self._reports = ReportingRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._secrets = secrets_box

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        url: str,
        events: set[NotificationEvent],
    ) -> CreatedNotificationWebhook:
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        webhook = NotificationWebhook(
            id=uuid4(),
            project_id=project_id,
            name=name.strip(),
            url=url,
            secret_ciphertext=b"",
            secret_nonce=b"",
            events=sorted(event.value for event in events),
            enabled=True,
            created_by_id=actor.id,
        )
        secret = f"ftnotify_{secrets.token_urlsafe(32)}"
        encrypted = self._secrets.encrypt(
            secret,
            associated_data=_associated_data(webhook.id),
        )
        webhook.secret_ciphertext = encrypted.ciphertext
        webhook.secret_nonce = encrypted.nonce
        self._reports.add(webhook)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="notification_webhook.created",
            resource_type="notification_webhook",
            resource_id=webhook.id,
            details={"events": webhook.events},
        )
        await self._session.commit()
        await self._session.refresh(webhook)
        return CreatedNotificationWebhook(model=webhook, secret=secret)

    async def list_webhooks(self, *, actor: User, project_id: UUID) -> list[NotificationWebhook]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._reports.list_webhooks(project_id)

    async def update(
        self,
        *,
        actor: User,
        project_id: UUID,
        webhook_id: UUID,
        name: str | None,
        url: str | None,
        events: set[NotificationEvent] | None,
        enabled: bool | None,
    ) -> NotificationWebhook:
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        webhook = await self._webhook(project_id, webhook_id)
        if name is not None:
            webhook.name = name.strip()
        if url is not None:
            webhook.url = url
        if events is not None:
            webhook.events = sorted(event.value for event in events)
        if enabled is not None:
            webhook.enabled = enabled
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="notification_webhook.updated",
            resource_type="notification_webhook",
            resource_id=webhook.id,
            details={"enabled": webhook.enabled, "events": webhook.events},
        )
        await self._session.commit()
        await self._session.refresh(webhook)
        return webhook

    async def list_deliveries(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[NotificationDelivery], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._reports.list_deliveries(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def _webhook(self, project_id: UUID, webhook_id: UUID) -> NotificationWebhook:
        webhook = await self._reports.get_webhook(webhook_id)
        if webhook is None or webhook.project_id != project_id:
            raise AppError(
                code="NOTIFICATION_WEBHOOK_NOT_FOUND",
                message="通知 Webhook 不存在",
                status_code=404,
            )
        return webhook


class NotificationDeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        secrets_box: SecretBox = secret_box,
        outbound_guard: OutboundRequestGuard = outbound_request_guard,
    ) -> None:
        self._session = session
        self._reports = ReportingRepository(session)
        self._secrets = secrets_box
        self._outbound_guard = outbound_guard
        self._projects = ProjectService(session)

    async def deliver_workflow(self, execution_id: UUID) -> None:
        execution = await self._reports.get_execution(execution_id)
        if execution is None or execution.status in {"queued", "running"}:
            return
        await self._deliver(
            project_id=execution.project_id,
            event_type=NotificationEvent.WORKFLOW_COMPLETED,
            resource_id=execution.id,
            payload=_workflow_payload(execution),
        )

    async def deliver_test_plan(self, run_id: UUID) -> None:
        run = await self._session.get(TestPlanRun, run_id)
        if run is None or run.status in {"queued", "running"}:
            return
        await self._deliver(
            project_id=run.project_id,
            event_type=NotificationEvent.TEST_PLAN_COMPLETED,
            resource_id=run.id,
            payload=_test_plan_payload(run),
        )

    async def _deliver(
        self,
        *,
        project_id: UUID,
        event_type: NotificationEvent,
        resource_id: UUID,
        payload: dict[str, object],
    ) -> None:
        webhooks = await self._reports.list_enabled_webhooks(
            project_id=project_id,
            event_type=event_type.value,
        )
        for webhook in webhooks:
            await self._deliver_one(
                webhook=webhook,
                event_type=event_type,
                resource_id=resource_id,
                payload=payload,
            )

    async def _deliver_one(
        self,
        *,
        webhook: NotificationWebhook,
        event_type: NotificationEvent,
        resource_id: UUID,
        payload: dict[str, object],
    ) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(datetime.now(UTC).timestamp()))
        secret = self._secrets.decrypt(
            EncryptedValue(webhook.secret_ciphertext, webhook.secret_nonce),
            associated_data=_associated_data(webhook.id),
        )
        signature = (
            "sha256="
            + hmac.new(
                secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
        )
        delivery = NotificationDelivery(
            project_id=webhook.project_id,
            webhook_id=webhook.id,
            event_type=event_type.value,
            resource_id=resource_id,
            status="pending",
            attempt=1,
            response_status=None,
            error_message=None,
            delivered_at=None,
        )
        self._reports.add(delivery)
        await self._session.flush()
        try:
            policy = await self._projects.load_runtime_security_policy(webhook.project_id)
            await self._outbound_guard.enforce(webhook.url, policy)
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=DELIVERY_TIMEOUT_SECONDS,
            ) as client:
                response = await client.post(
                    webhook.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-FlowTest-Event": event_type.value,
                        "X-FlowTest-Timestamp": timestamp,
                        "X-FlowTest-Signature": signature,
                    },
                )
            delivery.response_status = response.status_code
            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                delivery.delivered_at = datetime.now(UTC)
            else:
                delivery.status = "failed"
                delivery.error_message = f"通知端点返回 HTTP {response.status_code}"
        except (httpx.HTTPError, AppError) as error:
            delivery.status = "failed"
            delivery.error_message = (
                error.code if isinstance(error, AppError) else type(error).__name__
            )
        await self._session.commit()


def _workflow_payload(execution: WorkflowExecution) -> dict[str, object]:
    return {
        "event": NotificationEvent.WORKFLOW_COMPLETED.value,
        "resource_id": str(execution.id),
        "project_id": str(execution.project_id),
        "status": execution.status,
        "failure_category": classify_failure(
            status=execution.status,
            error_code=execution.error_code,
        ).value,
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
    }


def _test_plan_payload(run: TestPlanRun) -> dict[str, object]:
    return {
        "event": NotificationEvent.TEST_PLAN_COMPLETED.value,
        "resource_id": str(run.id),
        "project_id": str(run.project_id),
        "test_plan_id": str(run.test_plan_id),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _associated_data(webhook_id: UUID) -> bytes:
    return f"notification-webhook:{webhook_id}".encode()
