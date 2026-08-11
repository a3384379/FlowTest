from base64 import urlsafe_b64encode
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_oidc_provider
from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.http.oidc import HttpOIDCProvider
from app.main import app
from app.models import Base
from app.models.access import OIDCLoginTransaction, User
from app.services.oidc import OIDCConfiguration, OIDCIdentity, validate_https_endpoint


class FakeOIDCProvider:
    def __init__(self) -> None:
        self.state = ""
        self.nonce = ""
        self.code_challenge = ""
        self.code_verifier = ""
        self.identity = OIDCIdentity(
            subject="subject-1",
            email="member@example.com",
            display_name="OIDC Member",
            email_verified=True,
            nonce="",
        )

    async def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        self.state = state
        self.nonce = nonce
        self.code_challenge = code_challenge
        return f"https://identity.example/authorize?state={state}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> OIDCIdentity:
        assert code == "authorization-code"
        self.code_verifier = code_verifier
        identity = self.identity
        return OIDCIdentity(
            subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
            email_verified=identity.email_verified,
            nonce=identity.nonce or self.nonce,
        )


@dataclass(slots=True)
class OIDCTestContext:
    client: AsyncClient
    provider: FakeOIDCProvider
    sessions: async_sessionmaker[AsyncSession]


@pytest.fixture
async def oidc_context(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[OIDCTestContext]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    provider = FakeOIDCProvider()
    monkeypatch.setattr(settings, "feature_oidc_enabled", True)
    monkeypatch.setattr(settings, "oidc_provider_name", "company")
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://identity.example")
    monkeypatch.setattr(settings, "oidc_client_id", "flowtest")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "http://test/api/v1/auth/oidc/callback")
    monkeypatch.setattr(settings, "oidc_frontend_success_url", "http://web.test/dashboard")
    monkeypatch.setattr(settings, "oidc_allowed_email_domains", ["example.com"])
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_oidc_provider] = lambda: provider
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        yield OIDCTestContext(client=client, provider=provider, sessions=sessions)
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_oidc_pkce_jit_login_refresh_and_replay_protection(
    oidc_context: OIDCTestContext,
) -> None:
    login = await oidc_context.client.get("/api/v1/auth/oidc/login")
    assert login.status_code == 307
    assert login.headers["location"].startswith("https://identity.example/authorize")
    assert oidc_context.provider.state not in login.headers.get("set-cookie", "")

    callback = await oidc_context.client.get(
        "/api/v1/auth/oidc/callback",
        params={"state": oidc_context.provider.state, "code": "authorization-code"},
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://web.test/dashboard"
    assert oidc_context.client.cookies.get("flowtest_refresh") is not None
    expected_challenge = (
        urlsafe_b64encode(sha256(oidc_context.provider.code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert oidc_context.provider.code_challenge == expected_challenge

    refreshed = await oidc_context.client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    me = await oidc_context.client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["oidc_provider"] == "company"
    assert me.json()["oidc_subject"] == "subject-1"
    assert me.json()["last_login_at"] is not None
    assert me.json()["is_system_admin"] is False
    assert me.json()["requires_password_change"] is False
    projects = await oidc_context.client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert projects.status_code == 200
    assert projects.json()["total"] == 0

    replay = await oidc_context.client.get(
        "/api/v1/auth/oidc/callback",
        params={"state": oidc_context.provider.state, "code": "authorization-code"},
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "OIDC_TRANSACTION_INVALID"


@pytest.mark.asyncio
async def test_oidc_rejects_expired_state_nonce_and_untrusted_email(
    oidc_context: OIDCTestContext,
) -> None:
    await oidc_context.client.get("/api/v1/auth/oidc/login")
    async with oidc_context.sessions() as session:
        transaction = await session.scalar(select(OIDCLoginTransaction))
        assert transaction is not None
        transaction.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    expired = await _callback(oidc_context)
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "OIDC_TRANSACTION_INVALID"

    await oidc_context.client.get("/api/v1/auth/oidc/login")
    oidc_context.provider.identity = OIDCIdentity(
        subject="subject-2",
        email="member@example.com",
        display_name="Member",
        email_verified=True,
        nonce="incorrect-nonce",
    )
    bad_nonce = await _callback(oidc_context)
    assert bad_nonce.status_code == 401
    assert bad_nonce.json()["error"]["code"] == "OIDC_NONCE_INVALID"

    await oidc_context.client.get("/api/v1/auth/oidc/login")
    oidc_context.provider.identity = OIDCIdentity(
        subject="subject-3",
        email="member@outside.example",
        display_name="Member",
        email_verified=True,
        nonce="",
    )
    bad_domain = await _callback(oidc_context)
    assert bad_domain.status_code == 403
    assert bad_domain.json()["error"]["code"] == "OIDC_EMAIL_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_oidc_links_existing_local_user_and_rejects_conflicting_identity(
    oidc_context: OIDCTestContext,
) -> None:
    async with oidc_context.sessions() as session:
        session.add(
            User(
                email="member@example.com",
                display_name="Local Member",
                password_hash=password_service.hash("local-password-123!"),
                is_active=True,
                is_system_admin=False,
                requires_password_change=False,
            )
        )
        await session.commit()
    await oidc_context.client.get("/api/v1/auth/oidc/login")
    linked = await _callback(oidc_context)
    assert linked.status_code == 303
    async with oidc_context.sessions() as session:
        user = await session.scalar(select(User).where(User.email == "member@example.com"))
        assert user is not None
        assert user.oidc_provider == "company"
        assert user.oidc_subject == "subject-1"

    oidc_context.provider.identity = OIDCIdentity(
        subject="different-subject",
        email="member@example.com",
        display_name="Member",
        email_verified=True,
        nonce="",
    )
    await oidc_context.client.get("/api/v1/auth/oidc/login")
    conflict = await _callback(oidc_context)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "OIDC_IDENTITY_CONFLICT"


@pytest.mark.asyncio
@respx.mock
async def test_http_oidc_provider_validates_signed_id_token_and_pkce() -> None:
    configuration = _http_configuration()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    discovery = {
        "issuer": configuration.issuer_url,
        "authorization_endpoint": "https://identity.example/authorize",
        "token_endpoint": "https://identity.example/token",
        "jwks_uri": "https://identity.example/jwks",
        "userinfo_endpoint": "https://identity.example/userinfo",
    }
    respx.get("https://identity.example/.well-known/openid-configuration").mock(
        return_value=Response(200, json=discovery)
    )
    now = datetime.now(UTC)
    id_token = jwt.encode(
        {
            "iss": configuration.issuer_url,
            "aud": configuration.client_id,
            "sub": "subject-1",
            "email": "member@example.com",
            "email_verified": True,
            "name": "Member",
            "nonce": "nonce-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )
    token_route = respx.post("https://identity.example/token").mock(
        return_value=Response(200, json={"id_token": id_token})
    )
    respx.get("https://identity.example/jwks").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )

    provider = HttpOIDCProvider(configuration)
    authorization_url = await provider.authorization_url(
        state="state-1",
        nonce="nonce-1",
        code_challenge="challenge-1",
    )
    query = parse_qs(urlsplit(authorization_url).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"] == ["nonce-1"]
    identity = await provider.exchange_code(code="code-1", code_verifier="verifier-1")
    assert identity.email == "member@example.com"
    assert identity.email_verified is True
    assert token_route.called
    assert b"code_verifier=verifier-1" in token_route.calls.last.request.content
    assert token_route.calls.last.request.headers["authorization"].startswith("Basic ")


@pytest.mark.asyncio
@respx.mock
async def test_http_oidc_provider_uses_verified_userinfo_for_public_client() -> None:
    configuration = replace(_http_configuration(), client_secret="")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    discovery = _discovery(configuration)
    respx.get("https://identity.example/.well-known/openid-configuration").mock(
        return_value=Response(200, json=discovery)
    )
    now = datetime.now(UTC)
    id_token = jwt.encode(
        {
            "iss": configuration.issuer_url,
            "aud": configuration.client_id,
            "sub": "subject-1",
            "nonce": "nonce-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )
    token_route = respx.post("https://identity.example/token").mock(
        return_value=Response(
            200,
            json={"id_token": id_token, "access_token": "provider-access-token"},
        )
    )
    respx.get("https://identity.example/jwks").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )
    userinfo_route = respx.get("https://identity.example/userinfo").mock(
        return_value=Response(
            200,
            json={
                "sub": "subject-1",
                "email": "member@example.com",
                "email_verified": True,
                "name": "Member",
            },
        )
    )

    identity = await HttpOIDCProvider(configuration).exchange_code(
        code="code-1",
        code_verifier="verifier-1",
    )

    assert identity.display_name == "Member"
    assert b"client_id=flowtest" in token_route.calls.last.request.content
    assert "authorization" not in token_route.calls.last.request.headers
    assert userinfo_route.calls.last.request.headers["authorization"] == (
        "Bearer provider-access-token"
    )

    userinfo_route.mock(
        return_value=Response(
            200,
            json={
                "sub": "different-subject",
                "email": "member@example.com",
                "email_verified": True,
            },
        )
    )
    with pytest.raises(AppError, match="OIDC 身份校验失败"):
        await HttpOIDCProvider(configuration).exchange_code(
            code="code-2",
            code_verifier="verifier-2",
        )


@pytest.mark.asyncio
@respx.mock
async def test_http_oidc_provider_rejects_untrusted_algorithm_and_provider_failure() -> None:
    configuration = _http_configuration()
    discovery = _discovery(configuration)
    discovery_route = respx.get("https://identity.example/.well-known/openid-configuration").mock(
        return_value=Response(200, json=discovery)
    )
    now = datetime.now(UTC)
    untrusted_token = jwt.encode(
        {
            "iss": configuration.issuer_url,
            "aud": configuration.client_id,
            "sub": "subject-1",
            "nonce": "nonce-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        "untrusted-key-with-at-least-32-bytes",
        algorithm="HS256",
    )
    respx.post("https://identity.example/token").mock(
        return_value=Response(200, json={"id_token": untrusted_token})
    )
    with pytest.raises(AppError, match="OIDC 身份校验失败") as invalid_identity:
        await HttpOIDCProvider(configuration).exchange_code(
            code="code-1",
            code_verifier="verifier-1",
        )
    assert invalid_identity.value.code == "OIDC_IDENTITY_INVALID"

    discovery_route.mock(return_value=Response(500))
    with pytest.raises(AppError, match="OIDC 服务暂时不可用") as unavailable:
        await HttpOIDCProvider(configuration).authorization_url(
            state="state",
            nonce="nonce",
            code_challenge="challenge",
        )
    assert unavailable.value.code == "OIDC_PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
@respx.mock
async def test_http_oidc_provider_rejects_malformed_and_wrongly_signed_tokens() -> None:
    configuration = _http_configuration()
    discovery = _discovery(configuration)
    respx.get("https://identity.example/.well-known/openid-configuration").mock(
        return_value=Response(200, json=discovery)
    )
    token_route = respx.post("https://identity.example/token").mock(
        return_value=Response(200, json={"id_token": "not-a-jwt"})
    )
    provider = HttpOIDCProvider(configuration)
    with pytest.raises(AppError, match="OIDC 身份校验失败"):
        await provider.exchange_code(code="code", code_verifier="verifier")

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    different_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    signed_token = jwt.encode(
        {
            "iss": configuration.issuer_url,
            "aud": configuration.client_id,
            "sub": "subject-1",
            "nonce": "nonce-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        signing_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )
    token_route.mock(return_value=Response(200, json={"id_token": signed_token}))
    wrong_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(different_key.public_key(), as_dict=True)
    wrong_jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    jwks_route = respx.get("https://identity.example/jwks").mock(
        return_value=Response(200, json={"keys": [wrong_jwk]})
    )
    with pytest.raises(AppError, match="OIDC 身份校验失败"):
        await provider.exchange_code(code="code", code_verifier="verifier")

    jwks_route.mock(return_value=Response(200, json={"keys": []}))
    with pytest.raises(AppError, match="OIDC 身份校验失败"):
        await provider.exchange_code(code="code", code_verifier="verifier")


@pytest.mark.asyncio
@respx.mock
async def test_http_oidc_provider_rejects_invalid_metadata_and_token_failure() -> None:
    configuration = _http_configuration()
    discovery_route = respx.get("https://identity.example/.well-known/openid-configuration").mock(
        return_value=Response(200, json=[])
    )
    provider = HttpOIDCProvider(configuration)
    with pytest.raises(AppError, match="OIDC 服务暂时不可用"):
        await provider.authorization_url(state="state", nonce="nonce", code_challenge="pkce")

    invalid_discovery = _discovery(configuration)
    invalid_discovery["issuer"] = "https://attacker.example"
    discovery_route.mock(return_value=Response(200, json=invalid_discovery))
    with pytest.raises(AppError, match="OIDC 服务配置无效"):
        await provider.authorization_url(state="state", nonce="nonce", code_challenge="pkce")

    discovery_route.mock(return_value=Response(200, json=_discovery(configuration)))
    respx.post("https://identity.example/token").mock(return_value=Response(500))
    with pytest.raises(AppError, match="OIDC 服务暂时不可用"):
        await provider.exchange_code(code="code", code_verifier="verifier")


def test_oidc_endpoint_validation_rejects_insecure_or_credentialed_urls() -> None:
    with pytest.raises(AppError, match="OIDC 服务配置无效"):
        validate_https_endpoint("http://identity.example/token", production=True)
    with pytest.raises(AppError, match="OIDC 服务配置无效"):
        validate_https_endpoint("https://user:password@identity.example/token", production=True)


async def _callback(context: OIDCTestContext) -> Response:
    return await context.client.get(
        "/api/v1/auth/oidc/callback",
        params={"state": context.provider.state, "code": "authorization-code"},
    )


def _http_configuration() -> OIDCConfiguration:
    return OIDCConfiguration(
        enabled=True,
        provider_name="company",
        issuer_url="https://identity.example",
        client_id="flowtest",
        client_secret="client-secret",
        redirect_uri="https://flowtest.example/api/v1/auth/oidc/callback",
        frontend_success_url="https://flowtest.example/dashboard",
        allowed_email_domains=frozenset({"example.com"}),
        scopes=("openid", "profile", "email"),
        allowed_algorithms=("RS256",),
        transaction_ttl_seconds=600,
        request_timeout_seconds=10,
        production=True,
    )


def _discovery(configuration: OIDCConfiguration) -> dict[str, str]:
    return {
        "issuer": configuration.issuer_url,
        "authorization_endpoint": "https://identity.example/authorize",
        "token_endpoint": "https://identity.example/token",
        "jwks_uri": "https://identity.example/jwks",
        "userinfo_endpoint": "https://identity.example/userinfo",
    }
