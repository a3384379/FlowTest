from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.data_nodes import (
    CredentialKind,
    CredentialSecretProvider,
    DataNodeValidationError,
    validate_grpc_mtls_secret,
)
from app.models.access import User
from app.models.data_sources import Credential
from app.repositories.data_sources import DataSourceRepository
from app.services.audit import AuditService
from app.services.encryption_keys import active_key_reference_for_project
from app.services.projects import ProjectService


class ExternalCredentialSecretStore(Protocol):
    provider_name: CredentialSecretProvider

    async def write(self, *, reference: str, secret: str) -> None: ...

    async def read(self, *, reference: str) -> str: ...

    async def delete(self, *, reference: str) -> None: ...


@dataclass(frozen=True, slots=True)
class CredentialMaterial:
    id: UUID
    project_id: UUID
    name: str
    kind: CredentialKind
    host: str
    port: int
    database_name: str
    username: str
    secret: str
    tls_enabled: bool


class CredentialService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        secrets: SecretBox = secret_box,
        external_secrets: ExternalCredentialSecretStore | None = None,
    ) -> None:
        self._session = session
        self._repository = DataSourceRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._secrets = secrets
        self._external_secrets = external_secrets

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        name: str,
        kind: CredentialKind,
        host: str,
        port: int | None,
        database_name: str,
        username: str,
        secret: str,
        secret_provider: CredentialSecretProvider,
        tls_enabled: bool,
    ) -> Credential:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_name = name.strip()
        await self._ensure_unique_name(project_id, normalized_name)
        credential_id = uuid4()
        validated_secret = _validated_secret(kind, secret)
        ciphertext, nonce, provider_reference = await self._store_new_secret(
            credential_id=credential_id,
            project_id=project_id,
            provider=secret_provider,
            secret=validated_secret,
        )
        credential = Credential(
            id=credential_id,
            project_id=project_id,
            name=normalized_name,
            kind=kind.value,
            host=_normalize_host(host),
            port=port or _default_port(kind),
            database_name=_normalize_database_name(kind, database_name),
            username=username.strip(),
            secret_provider=secret_provider.value,
            provider_reference=provider_reference,
            ciphertext=ciphertext,
            nonce=nonce,
            tls_enabled=tls_enabled,
            created_by_id=actor.id,
        )
        self._repository.add(credential)
        self._record(actor, credential, "credential.created")
        await self._session.commit()
        await self._session.refresh(credential)
        return credential

    async def list(self, *, actor: User, project_id: UUID) -> list[Credential]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_credentials(project_id)

    async def update(
        self,
        *,
        actor: User,
        credential_id: UUID,
        name: str | None,
        host: str | None,
        port: int | None,
        database_name: str | None,
        username: str | None,
        secret: str | None,
        tls_enabled: bool | None,
    ) -> Credential:
        credential = await self._get(credential_id)
        await self._projects.authorize(
            actor=actor,
            project_id=credential.project_id,
            editing=True,
        )
        if name is not None:
            normalized_name = name.strip()
            await self._ensure_unique_name(
                credential.project_id,
                normalized_name,
                excluding_id=credential.id,
            )
            credential.name = normalized_name
        if host is not None:
            credential.host = _normalize_host(host)
        if port is not None:
            credential.port = port
        if database_name is not None:
            credential.database_name = _normalize_database_name(
                CredentialKind(credential.kind), database_name
            )
        if username is not None:
            credential.username = username.strip()
        if tls_enabled is not None:
            credential.tls_enabled = tls_enabled
        if secret is not None:
            await self._replace_secret(
                credential,
                _validated_secret(CredentialKind(credential.kind), secret),
            )
        self._record(actor, credential, "credential.updated")
        await self._session.commit()
        await self._session.refresh(credential)
        return credential

    async def delete(self, *, actor: User, credential_id: UUID) -> None:
        credential = await self._get(credential_id)
        await self._projects.authorize(
            actor=actor,
            project_id=credential.project_id,
            editing=True,
        )
        self._record(actor, credential, "credential.deleted")
        await self._delete_external_secret(credential)
        await self._repository.delete(credential)
        await self._session.commit()

    async def load_material(self, *, project_id: UUID, credential_id: UUID) -> CredentialMaterial:
        credential = await self._get(credential_id)
        if credential.project_id != project_id:
            raise AppError(
                code="CREDENTIAL_NOT_FOUND", message="Credential 不存在", status_code=404
            )
        secret = await self._load_secret(credential)
        return CredentialMaterial(
            id=credential.id,
            project_id=credential.project_id,
            name=credential.name,
            kind=CredentialKind(credential.kind),
            host=credential.host,
            port=credential.port,
            database_name=credential.database_name,
            username=credential.username,
            secret=secret,
            tls_enabled=credential.tls_enabled,
        )

    async def _get(self, credential_id: UUID) -> Credential:
        credential = await self._repository.get_credential(credential_id)
        if credential is None:
            raise AppError(
                code="CREDENTIAL_NOT_FOUND", message="Credential 不存在", status_code=404
            )
        return credential

    async def _store_new_secret(
        self,
        *,
        credential_id: UUID,
        project_id: UUID,
        provider: CredentialSecretProvider,
        secret: str,
    ) -> tuple[bytes | None, bytes | None, str | None]:
        if provider is CredentialSecretProvider.LOCAL:
            encrypted = self._secrets.encrypt(
                secret,
                associated_data=_associated_data(credential_id, project_id),
                key_reference=await active_key_reference_for_project(self._session, project_id),
            )
            return encrypted.ciphertext, encrypted.nonce, None
        external = self._require_external_store(provider)
        reference = _external_reference(project_id, credential_id)
        await external.write(reference=reference, secret=secret)
        return None, None, reference

    async def _replace_secret(self, credential: Credential, secret: str) -> None:
        if CredentialSecretProvider(credential.secret_provider) is CredentialSecretProvider.LOCAL:
            encrypted = self._secrets.encrypt(
                secret,
                associated_data=_associated_data(credential.id, credential.project_id),
                key_reference=await active_key_reference_for_project(
                    self._session, credential.project_id
                ),
            )
            credential.ciphertext = encrypted.ciphertext
            credential.nonce = encrypted.nonce
            return
        external = self._require_external_store(credential.secret_provider)
        if credential.provider_reference is None:
            raise _invalid_storage()
        await external.write(reference=credential.provider_reference, secret=secret)

    async def _load_secret(self, credential: Credential) -> str:
        if CredentialSecretProvider(credential.secret_provider) is CredentialSecretProvider.LOCAL:
            if credential.ciphertext is None or credential.nonce is None:
                raise _invalid_storage()
            return self._secrets.decrypt(
                EncryptedValue(credential.ciphertext, credential.nonce),
                associated_data=_associated_data(credential.id, credential.project_id),
            )
        external = self._require_external_store(credential.secret_provider)
        if credential.provider_reference is None:
            raise _invalid_storage()
        return await external.read(reference=credential.provider_reference)

    async def _delete_external_secret(self, credential: Credential) -> None:
        if CredentialSecretProvider(credential.secret_provider) is CredentialSecretProvider.LOCAL:
            return
        external = self._require_external_store(credential.secret_provider)
        if credential.provider_reference is None:
            raise _invalid_storage()
        await external.delete(reference=credential.provider_reference)

    def _require_external_store(
        self, provider: str | CredentialSecretProvider
    ) -> ExternalCredentialSecretStore:
        parsed_provider = CredentialSecretProvider(provider)
        if (
            self._external_secrets is None
            or self._external_secrets.provider_name is not parsed_provider
        ):
            raise AppError(
                code="CREDENTIAL_PROVIDER_UNAVAILABLE",
                message="Credential 外部存储尚未配置",
                status_code=503,
            )
        return self._external_secrets

    async def _ensure_unique_name(
        self,
        project_id: UUID,
        name: str,
        *,
        excluding_id: UUID | None = None,
    ) -> None:
        existing = await self._repository.find_credential_by_name(
            project_id=project_id,
            name=name,
            excluding_id=excluding_id,
        )
        if existing is not None:
            raise AppError(
                code="CREDENTIAL_NAME_EXISTS",
                message="Credential 名称已存在",
                status_code=409,
            )

    def _record(self, actor: User, credential: Credential, action: str) -> None:
        self._audit.record(
            actor_user_id=actor.id,
            project_id=credential.project_id,
            action=action,
            resource_type="credential",
            resource_id=credential.id,
            details={
                "kind": credential.kind,
                "host": credential.host,
                "port": credential.port,
                "secret_provider": credential.secret_provider,
            },
        )


def _default_port(kind: CredentialKind) -> int:
    return {
        CredentialKind.POSTGRESQL: 5432,
        CredentialKind.MYSQL: 3306,
        CredentialKind.REDIS: 6379,
        CredentialKind.GRPC_MTLS: 443,
    }[kind]


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def _normalize_database_name(kind: CredentialKind, database_name: str) -> str:
    normalized = database_name.strip()
    if kind in {CredentialKind.POSTGRESQL, CredentialKind.MYSQL} and not normalized:
        raise AppError(
            code="INVALID_CREDENTIAL_DATABASE",
            message="PostgreSQL/MySQL Credential 必须配置数据库名",
            status_code=422,
        )
    return normalized


def _associated_data(credential_id: UUID, project_id: UUID) -> bytes:
    return f"flowtest:credential:{project_id}:{credential_id}".encode()


def _external_reference(project_id: UUID, credential_id: UUID) -> str:
    return f"projects/{project_id}/credentials/{credential_id}"


def _invalid_storage() -> AppError:
    return AppError(
        code="CREDENTIAL_STORAGE_INVALID",
        message="Credential 存储状态无效",
        status_code=500,
    )


def _validated_secret(kind: CredentialKind, secret: str) -> str:
    if kind is not CredentialKind.GRPC_MTLS:
        return secret
    try:
        return validate_grpc_mtls_secret(secret)
    except DataNodeValidationError as error:
        raise AppError(
            code="INVALID_GRPC_MTLS_CREDENTIAL",
            message=str(error),
            status_code=422,
        ) from error
