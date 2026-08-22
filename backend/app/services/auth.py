from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import PasswordService, TokenService, password_service, token_service
from app.domain.runtime_profiles import RuntimeProfile
from app.models.access import RefreshSession, User
from app.repositories.access import RefreshSessionRepository, UserRepository
from app.services.audit import AuditService


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    user: User


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        passwords: PasswordService = password_service,
        tokens: TokenService = token_service,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_sessions = RefreshSessionRepository(session)
        self._audit = AuditService(session)
        self._passwords = passwords
        self._tokens = tokens

    async def login(self, *, email: str, password: str) -> TokenPair:
        user = await self._users.get_by_email(_normalize_login_identifier(email))
        if (
            user is None
            or not user.is_active
            or not self._passwords.verify(user.password_hash, password)
        ):
            raise AppError(code="INVALID_CREDENTIALS", message="账号或密码错误", status_code=401)
        if self._passwords.needs_rehash(user.password_hash):
            user.password_hash = self._passwords.hash(password)
        pair = await self._issue_pair(user)
        self._audit.record(
            actor_user_id=user.id,
            project_id=None,
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
        )
        await self._session.commit()
        return pair

    async def login_oidc(self, *, user: User, provider: str) -> TokenPair:
        if not user.is_active:
            raise AppError(code="OIDC_USER_DISABLED", message="用户已停用", status_code=403)
        user.last_login_at = datetime.now(UTC)
        pair = await self._issue_pair(user)
        self._audit.record(
            actor_user_id=user.id,
            project_id=None,
            action="auth.oidc_login",
            resource_type="user",
            resource_id=user.id,
            details={"provider": provider},
        )
        await self._session.commit()
        return pair

    async def rotate(self, refresh_token: str) -> TokenPair:
        token_hash = self._tokens.digest_refresh_token(refresh_token)
        current = await self._refresh_sessions.get_by_hash(token_hash)
        now = datetime.now(UTC)
        if current is None or current.revoked_at is not None:
            raise AppError(code="INVALID_REFRESH_TOKEN", message="登录状态已失效", status_code=401)
        expires_at = current.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            raise AppError(code="INVALID_REFRESH_TOKEN", message="登录状态已失效", status_code=401)
        user = await self._users.get(current.user_id)
        if user is None or not user.is_active:
            raise AppError(code="INVALID_REFRESH_TOKEN", message="登录状态已失效", status_code=401)
        pair = await self._issue_pair(user)
        current.revoked_at = now
        await self._session.flush()
        replacement = await self._refresh_sessions.get_by_hash(
            self._tokens.digest_refresh_token(pair.refresh_token)
        )
        current.replaced_by_id = replacement.id if replacement is not None else None
        await self._session.commit()
        return pair

    async def logout(self, refresh_token: str | None, *, actor_user_id: UUID | None) -> None:
        if refresh_token:
            stored = await self._refresh_sessions.get_by_hash(
                self._tokens.digest_refresh_token(refresh_token)
            )
            if stored is not None and stored.revoked_at is None:
                stored.revoked_at = datetime.now(UTC)
        self._audit.record(
            actor_user_id=actor_user_id,
            project_id=None,
            action="auth.logout",
            resource_type="user",
            resource_id=actor_user_id,
        )
        await self._session.commit()

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        if not self._passwords.verify(user.password_hash, current_password):
            raise AppError(code="INVALID_PASSWORD", message="当前密码错误", status_code=400)
        if current_password == new_password:
            raise AppError(code="PASSWORD_REUSED", message="新密码不能与当前密码相同")
        user.password_hash = self._passwords.hash(new_password)
        user.requires_password_change = False
        await self._refresh_sessions.revoke_all(user_id=user.id, revoked_at=datetime.now(UTC))
        self._audit.record(
            actor_user_id=user.id,
            project_id=None,
            action="user.password_changed",
            resource_type="user",
            resource_id=user.id,
        )
        await self._session.commit()

    async def _issue_pair(self, user: User) -> TokenPair:
        refresh_token = self._tokens.create_refresh_token()
        self._refresh_sessions.add(
            RefreshSession(
                user_id=user.id,
                token_hash=self._tokens.digest_refresh_token(refresh_token),
                expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
                revoked_at=None,
                replaced_by_id=None,
            )
        )
        await self._session.flush()
        return TokenPair(
            access_token=self._tokens.create_access_token(user.id),
            refresh_token=refresh_token,
            user=user,
        )


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._audit = AuditService(session)

    async def list(self, *, page: int, page_size: int) -> tuple[list[User], int]:
        return await self._users.list(offset=(page - 1) * page_size, limit=page_size)

    async def create(
        self,
        *,
        actor: User,
        email: str,
        display_name: str,
        password: str,
        is_system_admin: bool,
    ) -> User:
        normalized_email = _normalize_email(email)
        if await self._users.get_by_email(normalized_email) is not None:
            raise AppError(code="EMAIL_EXISTS", message="邮箱已存在", status_code=409)
        user = User(
            email=normalized_email,
            display_name=display_name.strip(),
            password_hash=password_service.hash(password),
            is_active=True,
            is_system_admin=is_system_admin,
            requires_password_change=True,
        )
        self._users.add(user)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action="user.created",
            resource_type="user",
            resource_id=user.id,
            details={"is_system_admin": is_system_admin},
        )
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def update(
        self,
        *,
        actor: User,
        user_id: UUID,
        display_name: str | None,
        is_active: bool | None,
        is_system_admin: bool | None,
    ) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise AppError(code="USER_NOT_FOUND", message="用户不存在", status_code=404)
        if display_name is not None:
            user.display_name = display_name.strip()
        if is_active is not None:
            user.is_active = is_active
        if is_system_admin is not None:
            user.is_system_admin = is_system_admin
        self._audit.record(
            actor_user_id=actor.id,
            project_id=None,
            action="user.updated",
            resource_type="user",
            resource_id=user.id,
        )
        await self._session.commit()
        await self._session.refresh(user)
        return user


async def bootstrap_administrator(session: AsyncSession) -> None:
    users = UserRepository(session)
    email = _normalize_email(settings.bootstrap_admin_email)
    if await users.get_by_email(email) is not None:
        return
    administrator = User(
        email=email,
        display_name="系统管理员",
        password_hash=password_service.hash(settings.bootstrap_admin_password),
        is_active=True,
        is_system_admin=True,
        requires_password_change=settings.runtime_profile is not RuntimeProfile.STANDALONE,
    )
    users.add(administrator)
    await session.commit()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_login_identifier(identifier: str) -> str:
    normalized = _normalize_email(identifier)
    if normalized == "admin":
        return _normalize_email(settings.bootstrap_admin_email)
    return normalized
