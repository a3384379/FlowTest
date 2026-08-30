import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.tenant import TenantContext
from app.models.access import User
from app.models.organizations import ServiceAccount
from app.repositories.organizations import OrganizationRepository
from app.services.audit import AuditService
from app.services.organizations import OrganizationService

SERVICE_ACCOUNT_PREFIX = "ftsa_"
SERVICE_ACCOUNT_SCOPES = frozenset(
    {
        "org:read",
        "project:read",
        "project:write",
        "execution:trigger",
        "artifact:read",
        "runner:read",
        "audit:read",
        "mcp:read",
        "mcp:write",
        "mcp:evidence:write",
        "mcp:flow:propose",
        "mcp:preview:execute",
        "org:governance",
        "org:audit",
        "org:key_rotate",
        "runner:manage",
    }
)


@dataclass(frozen=True, slots=True)
class IssuedServiceAccount:
    account: ServiceAccount
    token: str


class ServiceAccountService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)
        self._orgs = OrganizationService(session)
        self._audit = AuditService(session)

    async def create(
        self,
        *,
        actor: User,
        organization_id: UUID,
        name: str,
        account_key: str,
        scopes: list[str],
        expires_at: datetime | None,
        metadata: dict[str, str],
    ) -> IssuedServiceAccount:
        await self._authorize(actor, organization_id)
        normalized_name = name.strip()
        normalized_key = account_key.strip()
        if (
            await self._organizations.find_service_account_by_name(
                organization_id=organization_id,
                name=normalized_name,
            )
            is not None
        ):
            raise AppError(
                code="SERVICE_ACCOUNT_NAME_EXISTS", message="服务账号名称已存在", status_code=409
            )
        if (
            await self._organizations.find_service_account_by_key(
                organization_id=organization_id,
                account_key=normalized_key,
            )
            is not None
        ):
            raise AppError(
                code="SERVICE_ACCOUNT_KEY_EXISTS", message="服务账号标识已存在", status_code=409
            )
        normalized_scopes = _normalize_scopes(scopes)
        token = _new_token()
        account = ServiceAccount(
            organization_id=organization_id,
            name=normalized_name,
            account_key=normalized_key,
            token_prefix=token[:16],
            token_hash=_token_hash(token),
            scopes=normalized_scopes,
            enabled=True,
            created_by_id=actor.id,
            expires_at=_normalize_expiry(expires_at),
            metadata_json=dict(metadata),
        )
        self._organizations.add(account)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization_id,
            project_id=None,
            action="service_account.created",
            resource_type="service_account",
            resource_id=account.id,
            details={"account_key": account.account_key, "scopes": normalized_scopes},
        )
        await self._session.commit()
        await self._session.refresh(account)
        return IssuedServiceAccount(account=account, token=token)

    async def list(self, *, actor: User, organization_id: UUID) -> list[ServiceAccount]:
        await self._authorize(actor, organization_id, capability="read")
        return await self._organizations.list_service_accounts(organization_id)

    async def revoke(
        self, *, actor: User, organization_id: UUID, account_id: UUID
    ) -> ServiceAccount:
        await self._authorize(actor, organization_id)
        account = await self._get(organization_id, account_id)
        account.enabled = False
        account.revoked_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization_id,
            project_id=None,
            action="service_account.revoked",
            resource_type="service_account",
            resource_id=account.id,
        )
        await self._session.commit()
        await self._session.refresh(account)
        return account

    async def rotate(
        self, *, actor: User, organization_id: UUID, account_id: UUID
    ) -> IssuedServiceAccount:
        await self._authorize(actor, organization_id)
        account = await self._get(organization_id, account_id)
        if not account.enabled or account.revoked_at is not None:
            raise AppError(
                code="SERVICE_ACCOUNT_REVOKED", message="服务账号已撤销", status_code=409
            )
        token = _new_token()
        account.token_prefix = token[:16]
        account.token_hash = _token_hash(token)
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=organization_id,
            project_id=None,
            action="service_account.rotated",
            resource_type="service_account",
            resource_id=account.id,
        )
        await self._session.commit()
        await self._session.refresh(account)
        return IssuedServiceAccount(account=account, token=token)

    async def authenticate(
        self, token: str, *, touch_last_used: bool = True
    ) -> tuple[ServiceAccount, TenantContext]:
        if not token.startswith(SERVICE_ACCOUNT_PREFIX):
            raise AppError(
                code="INVALID_SERVICE_ACCOUNT_TOKEN", message="服务账号令牌无效", status_code=401
            )
        account = await self._organizations.find_service_account_by_token(_token_hash(token))
        now = datetime.now(UTC)
        if account is None or not account.enabled or account.revoked_at is not None:
            raise AppError(
                code="INVALID_SERVICE_ACCOUNT_TOKEN", message="服务账号令牌无效", status_code=401
            )
        if account.expires_at is not None and _as_utc(account.expires_at) <= now:
            raise AppError(
                code="SERVICE_ACCOUNT_EXPIRED", message="服务账号令牌已过期", status_code=401
            )
        if touch_last_used:
            account.last_used_at = now
            await self._session.commit()
        return account, TenantContext(
            organization_id=account.organization_id,
            actor_id=account.created_by_id,
            role=None,
            service_account_id=account.id,
            scopes=frozenset(account.scopes),
        )

    async def _authorize(
        self,
        actor: User,
        organization_id: UUID,
        capability: str = "manage_service_accounts",
    ) -> None:
        await self._orgs.authorize(
            actor=actor,
            organization_id=organization_id,
            capability=capability,
        )

    async def _get(self, organization_id: UUID, account_id: UUID) -> ServiceAccount:
        account = await self._organizations.get_service_account(account_id)
        if account is None or account.organization_id != organization_id:
            raise AppError(
                code="SERVICE_ACCOUNT_NOT_FOUND", message="服务账号不存在", status_code=404
            )
        return account


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted({scope.strip() for scope in scopes if scope.strip()})
    invalid = [scope for scope in normalized if scope not in SERVICE_ACCOUNT_SCOPES]
    if invalid:
        raise AppError(
            code="SERVICE_ACCOUNT_SCOPE_INVALID",
            message="服务账号包含不支持的权限范围",
            status_code=422,
            details={"scopes": invalid},
        )
    return normalized


def _new_token() -> str:
    return f"{SERVICE_ACCOUNT_PREFIX}{secrets.token_urlsafe(32)}"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalize_expiry(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    normalized = _as_utc(expires_at)
    if normalized <= datetime.now(UTC):
        raise AppError(
            code="SERVICE_ACCOUNT_EXPIRY_INVALID",
            message="过期时间必须晚于当前时间",
            status_code=422,
        )
    return normalized


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
