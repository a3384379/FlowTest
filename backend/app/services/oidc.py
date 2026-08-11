from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.encryption import EncryptedValue, SecretBox, secret_box
from app.core.errors import AppError
from app.core.security import PasswordService, password_service
from app.models.access import OIDCLoginTransaction, User
from app.repositories.access import OIDCLoginTransactionRepository, UserRepository
from app.services.auth import AuthService, TokenPair


@dataclass(frozen=True, slots=True)
class OIDCConfiguration:
    enabled: bool
    provider_name: str
    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    frontend_success_url: str
    allowed_email_domains: frozenset[str]
    scopes: tuple[str, ...]
    allowed_algorithms: tuple[str, ...]
    transaction_ttl_seconds: int
    request_timeout_seconds: int
    production: bool

    @classmethod
    def from_settings(cls, configured: Settings) -> "OIDCConfiguration":
        return cls(
            enabled=configured.feature_oidc_enabled,
            provider_name=configured.oidc_provider_name.strip(),
            issuer_url=configured.oidc_issuer_url.rstrip("/"),
            client_id=configured.oidc_client_id,
            client_secret=configured.oidc_client_secret,
            redirect_uri=configured.oidc_redirect_uri,
            frontend_success_url=configured.oidc_frontend_success_url,
            allowed_email_domains=frozenset(
                domain.strip().lower().lstrip("@")
                for domain in configured.oidc_allowed_email_domains
                if domain.strip()
            ),
            scopes=tuple(configured.oidc_scopes),
            allowed_algorithms=tuple(configured.oidc_allowed_algorithms),
            transaction_ttl_seconds=configured.oidc_transaction_ttl_seconds,
            request_timeout_seconds=configured.oidc_request_timeout_seconds,
            production=configured.environment.lower() in {"production", "prod"},
        )


@dataclass(frozen=True, slots=True)
class OIDCIdentity:
    subject: str
    email: str
    display_name: str
    email_verified: bool
    nonce: str


class OIDCProvider(Protocol):
    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str: ...

    async def exchange_code(self, *, code: str, code_verifier: str) -> OIDCIdentity: ...


@dataclass(frozen=True, slots=True)
class OIDCLoginStart:
    authorization_url: str


class OIDCService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: OIDCProvider,
        configuration: OIDCConfiguration,
        passwords: PasswordService = password_service,
        secrets: SecretBox = secret_box,
    ) -> None:
        self._session = session
        self._provider = provider
        self._configuration = configuration
        self._passwords = passwords
        self._secrets = secrets
        self._transactions = OIDCLoginTransactionRepository(session)
        self._users = UserRepository(session)

    async def start_login(self) -> OIDCLoginStart:
        self._ensure_enabled()
        state = token_urlsafe(32)
        nonce = token_urlsafe(32)
        code_verifier = token_urlsafe(64)
        code_challenge = _base64url_digest(code_verifier)
        authorization_url = await self._provider.authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
        )
        transaction_id = uuid4()
        encrypted_verifier = self._secrets.encrypt(
            code_verifier,
            associated_data=transaction_id.bytes,
        )
        self._transactions.add(
            OIDCLoginTransaction(
                id=transaction_id,
                provider=self._configuration.provider_name,
                state_hash=_digest(state),
                nonce_hash=_digest(nonce),
                verifier_ciphertext=encrypted_verifier.ciphertext,
                verifier_nonce=encrypted_verifier.nonce,
                redirect_uri=self._configuration.redirect_uri,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=self._configuration.transaction_ttl_seconds),
                consumed_at=None,
            )
        )
        await self._session.commit()
        return OIDCLoginStart(authorization_url=authorization_url)

    async def complete_login(self, *, state: str, code: str) -> TokenPair:
        self._ensure_enabled()
        if not state or not code:
            raise _invalid_transaction()
        transaction = await self._transactions.get_for_update(_digest(state))
        now = datetime.now(UTC)
        if transaction is None or transaction.consumed_at is not None:
            raise _invalid_transaction()
        expires_at = transaction.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now or transaction.provider != self._configuration.provider_name:
            transaction.consumed_at = now
            await self._session.commit()
            raise _invalid_transaction()
        code_verifier = self._secrets.decrypt(
            EncryptedValue(
                ciphertext=transaction.verifier_ciphertext,
                nonce=transaction.verifier_nonce,
            ),
            associated_data=transaction.id.bytes,
        )
        nonce_hash = transaction.nonce_hash
        transaction.consumed_at = now
        await self._session.commit()

        identity = await self._provider.exchange_code(code=code, code_verifier=code_verifier)
        if not compare_digest(_digest(identity.nonce), nonce_hash):
            raise AppError(code="OIDC_NONCE_INVALID", message="OIDC 登录校验失败", status_code=401)
        user = await self._resolve_user(identity)
        return await AuthService(self._session).login_oidc(
            user=user,
            provider=self._configuration.provider_name,
        )

    async def _resolve_user(self, identity: OIDCIdentity) -> User:
        email = identity.email.strip().lower()
        if not identity.email_verified or not _has_allowed_domain(
            email, self._configuration.allowed_email_domains
        ):
            raise AppError(
                code="OIDC_EMAIL_NOT_ALLOWED",
                message="该邮箱未验证或不在允许的域名范围内",
                status_code=403,
            )
        if not identity.subject.strip():
            raise AppError(code="OIDC_IDENTITY_INVALID", message="OIDC 身份无效", status_code=401)
        user = await self._users.get_by_oidc_identity(
            provider=self._configuration.provider_name,
            subject=identity.subject,
        )
        if user is not None:
            return user
        user = await self._users.get_by_email(email)
        if user is not None:
            if user.oidc_provider is not None or user.oidc_subject is not None:
                raise AppError(
                    code="OIDC_IDENTITY_CONFLICT",
                    message="该邮箱已绑定其他 OIDC 身份",
                    status_code=409,
                )
            user.oidc_provider = self._configuration.provider_name
            user.oidc_subject = identity.subject
            return user
        user = User(
            email=email,
            display_name=identity.display_name.strip() or email.split("@", maxsplit=1)[0],
            password_hash=self._passwords.hash(token_urlsafe(64)),
            is_active=True,
            is_system_admin=False,
            requires_password_change=False,
            oidc_provider=self._configuration.provider_name,
            oidc_subject=identity.subject,
            last_login_at=None,
        )
        self._users.add(user)
        await self._session.flush()
        return user

    def _ensure_enabled(self) -> None:
        if not self._configuration.enabled:
            raise AppError(code="OIDC_DISABLED", message="OIDC 登录未启用", status_code=404)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _base64url_digest(value: str) -> str:
    from base64 import urlsafe_b64encode

    return urlsafe_b64encode(sha256(value.encode()).digest()).rstrip(b"=").decode()


def _has_allowed_domain(email: str, allowed_domains: frozenset[str]) -> bool:
    local, separator, domain = email.rpartition("@")
    return bool(local and separator and domain in allowed_domains)


def _invalid_transaction() -> AppError:
    return AppError(
        code="OIDC_TRANSACTION_INVALID",
        message="OIDC 登录请求已失效 请重新登录",
        status_code=401,
    )


def validate_https_endpoint(url: str, *, production: bool) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ({"https"} if production else {"http", "https"}):
        raise AppError(code="OIDC_PROVIDER_INVALID", message="OIDC 服务配置无效", status_code=503)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise AppError(code="OIDC_PROVIDER_INVALID", message="OIDC 服务配置无效", status_code=503)
    return url
