import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import password_service
from app.main import app
from app.models import Base
from app.models.access import RefreshSession, User
from app.repositories.access import RefreshSessionRepository
from app.services.auth import AuthService

PASSWORD = "session-test-password-123!"
AUTH_HEADERS = {"X-Requested-With": "FlowTest"}


@pytest.fixture
async def session_context(
    tmp_path: Path,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], User]]:
    postgres_url = os.environ.get("FLOWTEST_AUTH_TEST_DATABASE_URL")
    schema = f"auth_session_{uuid4().hex}" if postgres_url else None
    engine = (
        create_async_engine(
            postgres_url,
            connect_args={"server_settings": {"search_path": schema}},
        )
        if postgres_url
        else create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path}/auth-session.db",
            connect_args={"timeout": 30},
        )
    )
    async with engine.begin() as connection:
        if schema:
            await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = User(
            email="session@example.com",
            display_name="Session user",
            password_hash=password_service.hash(PASSWORD),
            is_active=True,
            is_system_admin=True,
            requires_password_change=False,
        )
        session.add(user)
        await session.commit()
    yield factory, user
    if schema:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_access_token_has_distinct_envelope_and_logout_still_works(
    session_context: tuple[async_sessionmaker[AsyncSession], User],
) -> None:
    factory, user = session_context

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": PASSWORD},
                headers=AUTH_HEADERS,
            )
            assert login.status_code == 200, login.text
            old_cookie = client.cookies.get("flowtest_refresh")
            assert old_cookie
            assert (await client.post("/api/v1/auth/refresh")).status_code == 403
            rejected_origin = await client.post(
                "/api/v1/auth/refresh", headers={"Origin": "null", **AUTH_HEADERS}
            )
            assert rejected_origin.status_code == 403
            assert rejected_origin.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"
            expired = jwt.encode(
                {
                    "sub": str(user.id),
                    "jti": str(uuid4()),
                    "type": "access",
                    "iat": datetime.now(UTC) - timedelta(minutes=5),
                    "exp": datetime.now(UTC) - timedelta(minutes=1),
                },
                settings.secret_key,
                algorithm="HS256",
            )
            denied = await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
            )
            assert denied.status_code == 401
            assert denied.json()["error"]["code"] == "ACCESS_TOKEN_EXPIRED"
            assert denied.json()["error"]["trace_id"]
            rotated = await client.post("/api/v1/auth/refresh", headers=AUTH_HEADERS)
            assert rotated.status_code == 200, rotated.text
            new_cookie = client.cookies.get("flowtest_refresh")
            assert new_cookie and new_cookie != old_cookie
            client.cookies.clear()
            client.cookies.set(
                "flowtest_refresh", old_cookie, domain="test.local", path="/api/v1/auth"
            )
            logout = await client.post(
                "/api/v1/auth/logout",
                headers={**AUTH_HEADERS, "Authorization": f"Bearer {expired}"},
            )
            assert logout.status_code == 204, logout.text
            client.cookies.clear()
            client.cookies.set(
                "flowtest_refresh", new_cookie, domain="test.local", path="/api/v1/auth"
            )
            denied_refresh = await client.post("/api/v1/auth/refresh", headers=AUTH_HEADERS)
            assert denied_refresh.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_two_independent_transactions_cannot_rotate_one_token_twice(
    session_context: tuple[async_sessionmaker[AsyncSession], User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, user = session_context
    async with factory() as session:
        pair = await AuthService(session).login(email=user.email, password=PASSWORD)
    original_get = RefreshSessionRepository.get_by_hash
    first_reads = 0
    both_read = asyncio.Event()

    async def interleaved_get(
        repository: RefreshSessionRepository, token_hash: str
    ) -> RefreshSession | None:
        nonlocal first_reads
        result = await original_get(repository, token_hash)
        if first_reads < 2:
            first_reads += 1
            if first_reads == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), timeout=5)
        return result

    monkeypatch.setattr(RefreshSessionRepository, "get_by_hash", interleaved_get)

    async def rotate() -> str:
        async with factory() as session:
            try:
                return (await AuthService(session).rotate(pair.refresh_token)).refresh_token
            except AppError as error:
                return error.code

    results = await asyncio.gather(rotate(), rotate())
    assert sum(result == "REFRESH_ROTATION_CONFLICT" for result in results) == 1
    async with factory() as session:
        active = await session.scalar(
            select(func.count())
            .select_from(RefreshSession)
            .where(
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
        assert active == 1


@pytest.mark.asyncio
async def test_rotation_rollback_keeps_old_session_usable(
    session_context: tuple[async_sessionmaker[AsyncSession], User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, user = session_context
    async with factory() as session:
        pair = await AuthService(session).login(email=user.email, password=PASSWORD)
    async with factory() as session:
        service = AuthService(session)

        async def fail_issue(_user: User) -> None:
            raise RuntimeError("failed to create successor")

        monkeypatch.setattr(service, "_issue_pair", fail_issue)
        with pytest.raises(RuntimeError, match="failed to create successor"):
            await service.rotate(pair.refresh_token)
        await session.rollback()
    async with factory() as session:
        replacement = await AuthService(session).rotate(pair.refresh_token)
    assert replacement.refresh_token != pair.refresh_token


@pytest.mark.asyncio
async def test_password_change_cannot_leave_a_concurrent_refresh_active(
    session_context: tuple[async_sessionmaker[AsyncSession], User],
) -> None:
    factory, user = session_context
    async with factory() as session:
        pair = await AuthService(session).login(email=user.email, password=PASSWORD)

    async def rotate() -> None:
        async with factory() as session:
            try:
                await AuthService(session).rotate(pair.refresh_token)
            except AppError as error:
                assert error.code == "INVALID_REFRESH_TOKEN"

    async def change_password() -> None:
        async with factory() as session:
            current_user = await session.get(User, user.id)
            assert current_user is not None
            await AuthService(session).change_password(
                user=current_user,
                current_password=PASSWORD,
                new_password="replacement-password-123!",
            )

    await asyncio.gather(rotate(), change_password())
    async with factory() as session:
        active = await session.scalar(
            select(func.count())
            .select_from(RefreshSession)
            .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        )
        assert active == 0
