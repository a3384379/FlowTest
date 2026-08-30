"""Transactional re-encryption for organization-scoped ciphertexts."""

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox
from app.domain.data_nodes import CredentialSecretProvider
from app.models.access import Project
from app.models.api_assets import Secret
from app.models.data_sources import Credential
from app.models.imports import ImportRun
from app.models.reporting import NotificationWebhook
from app.models.tasking import TestPlan
from app.models.workflows import WorkflowExecution


@dataclass(frozen=True, slots=True)
class KeyRotationEvidence:
    total: int
    verified: int
    resource_counts: dict[str, int]
    ciphertext_digest: str


class _Digest(Protocol):
    def update(self, value: bytes) -> object: ...


class _EncryptedRow(Protocol):
    id: UUID


async def reencrypt_organization_ciphertexts(
    session: AsyncSession,
    *,
    organization_id: UUID,
    target_key_reference: str,
    secrets: SecretBox,
) -> KeyRotationEvidence:
    digest = sha256()
    resource_counts: dict[str, int] = {}
    verified = 0

    secrets_rows = list(
        (
            await session.scalars(
                select(Secret)
                .join(Project, Project.id == Secret.project_id)
                .where(Project.organization_id == organization_id)
                .order_by(Secret.id)
                .with_for_update()
            )
        ).all()
    )
    for secret_item in secrets_rows:
        verified += _reencrypt(
            item=secret_item,
            resource_type="secret",
            ciphertext_attribute="ciphertext",
            nonce_attribute="nonce",
            associated_data=_secret_associated_data(
                secret_item.project_id,
                secret_item.environment_id,
                secret_item.name,
            ),
            target_key_reference=target_key_reference,
            secrets=secrets,
            digest=digest,
        )
    resource_counts["secret"] = len(secrets_rows)

    credentials = list(
        (
            await session.scalars(
                select(Credential)
                .join(Project, Project.id == Credential.project_id)
                .where(
                    Project.organization_id == organization_id,
                    Credential.secret_provider == CredentialSecretProvider.LOCAL.value,
                    Credential.ciphertext.is_not(None),
                    Credential.nonce.is_not(None),
                )
                .order_by(Credential.id)
                .with_for_update()
            )
        ).all()
    )
    for credential in credentials:
        verified += _reencrypt(
            item=credential,
            resource_type="credential",
            ciphertext_attribute="ciphertext",
            nonce_attribute="nonce",
            associated_data=(
                f"flowtest:credential:{credential.project_id}:{credential.id}".encode()
            ),
            target_key_reference=target_key_reference,
            secrets=secrets,
            digest=digest,
        )
    resource_counts["credential"] = len(credentials)

    import_runs = list(
        (
            await session.scalars(
                select(ImportRun)
                .join(Project, Project.id == ImportRun.project_id)
                .where(
                    Project.organization_id == organization_id,
                    ImportRun.payload_ciphertext.is_not(None),
                    ImportRun.payload_nonce.is_not(None),
                )
                .order_by(ImportRun.id)
                .with_for_update()
            )
        ).all()
    )
    for import_run in import_runs:
        verified += _reencrypt(
            item=import_run,
            resource_type="import_preview",
            ciphertext_attribute="payload_ciphertext",
            nonce_attribute="payload_nonce",
            associated_data=f"flowtest:import-preview:{import_run.id}".encode(),
            target_key_reference=target_key_reference,
            secrets=secrets,
            digest=digest,
        )
    resource_counts["import_preview"] = len(import_runs)

    execution_plans = list(
        (
            await session.scalars(
                select(WorkflowExecution)
                .join(Project, Project.id == WorkflowExecution.project_id)
                .where(
                    Project.organization_id == organization_id,
                    WorkflowExecution.run_payload_ciphertext.is_not(None),
                    WorkflowExecution.run_payload_nonce.is_not(None),
                )
                .order_by(WorkflowExecution.id)
                .with_for_update()
            )
        ).all()
    )
    for execution in execution_plans:
        verified += _reencrypt(
            item=execution,
            resource_type="execution_plan",
            ciphertext_attribute="run_payload_ciphertext",
            nonce_attribute="run_payload_nonce",
            associated_data=f"workflow-execution:{execution.id}:run-plan".encode(),
            target_key_reference=target_key_reference,
            secrets=secrets,
            digest=digest,
        )
    resource_counts["execution_plan"] = len(execution_plans)

    plans = list(
        (
            await session.scalars(
                select(TestPlan)
                .join(Project, Project.id == TestPlan.project_id)
                .where(Project.organization_id == organization_id)
                .order_by(TestPlan.id)
                .with_for_update()
            )
        ).all()
    )
    for plan in plans:
        verified += _reencrypt(
            item=plan,
            resource_type="test_plan_webhook",
            ciphertext_attribute="webhook_secret_ciphertext",
            nonce_attribute="webhook_secret_nonce",
            associated_data=f"test-plan:{plan.id}:webhook-secret".encode(),
            target_key_reference=target_key_reference,
            secrets=secrets,
            digest=digest,
        )
    resource_counts["test_plan_webhook"] = len(plans)

    webhooks = list(
        (
            await session.scalars(
                select(NotificationWebhook)
                .join(Project, Project.id == NotificationWebhook.project_id)
                .where(Project.organization_id == organization_id)
                .order_by(NotificationWebhook.id)
                .with_for_update()
            )
        ).all()
    )
    for webhook in webhooks:
        verified += _reencrypt(
            item=webhook,
            resource_type="notification_webhook",
            ciphertext_attribute="secret_ciphertext",
            nonce_attribute="secret_nonce",
            associated_data=f"notification-webhook:{webhook.id}".encode(),
            target_key_reference=target_key_reference,
            secrets=secrets,
            digest=digest,
        )
    resource_counts["notification_webhook"] = len(webhooks)

    total = sum(resource_counts.values())
    if verified != total:
        raise ValueError("Key rotation verification count does not match the migrated total")
    return KeyRotationEvidence(
        total=total,
        verified=verified,
        resource_counts=resource_counts,
        ciphertext_digest=digest.hexdigest(),
    )


def _reencrypt(
    *,
    item: _EncryptedRow,
    resource_type: str,
    ciphertext_attribute: str,
    nonce_attribute: str,
    associated_data: bytes,
    target_key_reference: str,
    secrets: SecretBox,
    digest: _Digest,
) -> int:
    ciphertext = getattr(item, ciphertext_attribute)
    nonce = getattr(item, nonce_attribute)
    if not isinstance(ciphertext, bytes) or not isinstance(nonce, bytes):
        raise ValueError(f"{resource_type} ciphertext is incomplete")
    plaintext = secrets.decrypt(
        EncryptedValue(ciphertext=ciphertext, nonce=nonce),
        associated_data=associated_data,
    )
    encrypted = secrets.encrypt(
        plaintext,
        associated_data=associated_data,
        key_reference=target_key_reference,
    )
    verified = secrets.decrypt(encrypted, associated_data=associated_data)
    if not compare_digest(plaintext, verified):
        raise ValueError(f"{resource_type} ciphertext verification failed")
    setattr(item, ciphertext_attribute, encrypted.ciphertext)
    setattr(item, nonce_attribute, encrypted.nonce)
    digest.update(resource_type.encode())
    digest.update(str(item.id).encode())
    digest.update(encrypted.ciphertext)
    digest.update(encrypted.nonce)
    return 1


def _secret_associated_data(
    project_id: UUID,
    environment_id: UUID | None,
    name: str,
) -> bytes:
    environment = str(environment_id) if environment_id is not None else "project"
    return f"{project_id}:{environment}:{name}".encode()
