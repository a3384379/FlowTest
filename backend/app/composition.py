from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.http.vault import VaultKV2Configuration, VaultKV2CredentialSecretStore
from app.services.credentials import CredentialService, ExternalCredentialSecretStore
from app.services.workflows import WorkflowService


def build_credential_service(session: AsyncSession) -> CredentialService:
    return CredentialService(session, external_secrets=build_external_credential_store())


def build_workflow_service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session, external_secrets=build_external_credential_store())


def build_external_credential_store() -> ExternalCredentialSecretStore | None:
    if not settings.vault_kv2_enabled:
        return None
    configuration = VaultKV2Configuration.from_settings(settings)
    return VaultKV2CredentialSecretStore(configuration)
