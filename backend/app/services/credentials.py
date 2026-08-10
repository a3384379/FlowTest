from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.domain.data_nodes import CredentialKind
from app.models.access import User
from app.models.data_sources import Credential
from app.repositories.data_sources import DataSourceRepository
from app.services.audit import AuditService
from app.services.projects import ProjectService


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
    def __init__(self, session: AsyncSession, *, secrets: SecretBox = secret_box) -> None:
        self._session = session
        self._repository = DataSourceRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)
        self._secrets = secrets

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
        tls_enabled: bool,
    ) -> Credential:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        normalized_name = name.strip()
        await self._ensure_unique_name(project_id, normalized_name)
        credential_id = uuid4()
        encrypted = self._secrets.encrypt(
            secret,
            associated_data=_associated_data(credential_id, project_id),
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
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
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
            encrypted = self._secrets.encrypt(
                secret,
                associated_data=_associated_data(credential.id, credential.project_id),
            )
            credential.ciphertext = encrypted.ciphertext
            credential.nonce = encrypted.nonce
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
        await self._repository.delete(credential)
        await self._session.commit()

    async def load_material(self, *, project_id: UUID, credential_id: UUID) -> CredentialMaterial:
        credential = await self._get(credential_id)
        if credential.project_id != project_id:
            raise AppError(
                code="CREDENTIAL_NOT_FOUND", message="Credential 不存在", status_code=404
            )
        secret = self._secrets.decrypt(
            EncryptedValue(credential.ciphertext, credential.nonce),
            associated_data=_associated_data(credential.id, credential.project_id),
        )
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
            details={"kind": credential.kind, "host": credential.host, "port": credential.port},
        )


def _default_port(kind: CredentialKind) -> int:
    return {
        CredentialKind.POSTGRESQL: 5432,
        CredentialKind.MYSQL: 3306,
        CredentialKind.REDIS: 6379,
    }[kind]


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def _normalize_database_name(kind: CredentialKind, database_name: str) -> str:
    normalized = database_name.strip()
    if kind is not CredentialKind.REDIS and not normalized:
        raise AppError(
            code="INVALID_CREDENTIAL_DATABASE",
            message="PostgreSQL/MySQL Credential 必须配置数据库名",
            status_code=422,
        )
    return normalized


def _associated_data(credential_id: UUID, project_id: UUID) -> bytes:
    return f"flowtest:credential:{project_id}:{credential_id}".encode()
