import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

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
from app.repositories.access import RefreshSessionRepository, UserRepository
from app.services.auth import AuthService, TokenPair

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


@pytest.mark.skipif(
    not os.environ.get("FLOWTEST_AUTH_TEST_DATABASE_URL"),
    reason="Requires PostgreSQL independent transaction snapshots",
)
@pytest.mark.asyncio
async def test_password_change_rejects_login_using_a_pre_change_credential_snapshot(
    session_context: tuple[async_sessionmaker[AsyncSession], User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, user = session_context
    credentials_read = asyncio.Event()
    password_changed = asyncio.Event()
    original_get = UserRepository.get_by_email

    async def paused_get(repository: UserRepository, email: str) -> User | None:
        result = await original_get(repository, email)
        credentials_read.set()
        await asyncio.wait_for(password_changed.wait(), timeout=5)
        return result

    monkeypatch.setattr(UserRepository, "get_by_email", paused_get)

    async def stale_login() -> str:
        async with factory() as session:
            try:
                await AuthService(session).login(email=user.email, password=PASSWORD)
                return "issued"
            except AppError as error:
                return error.code

    login_task = asyncio.create_task(stale_login())
    await asyncio.wait_for(credentials_read.wait(), timeout=5)
    async with factory() as session:
        current_user = await session.get(User, user.id)
        assert current_user is not None
        await AuthService(session).change_password(
            user=current_user,
            current_password=PASSWORD,
            new_password="replacement-password-123!",
        )
    password_changed.set()
    assert await login_task == "INVALID_CREDENTIALS"
    async with factory() as session:
        active = await session.scalar(
            select(func.count())
            .select_from(RefreshSession)
            .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        )
        assert active == 0


@pytest.mark.skipif(
    not os.environ.get("FLOWTEST_AUTH_TEST_DATABASE_URL"),
    reason="Requires PostgreSQL row lock serialization",
)
@pytest.mark.asyncio
async def test_password_change_revokes_login_that_already_holds_the_user_lock(
    session_context: tuple[async_sessionmaker[AsyncSession], User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, user = session_context
    login_locked = asyncio.Event()
    allow_issue = asyncio.Event()
    change_lock_requested = asyncio.Event()
    original_issue = AuthService._issue_pair
    original_lock = UserRepository.lock_session_changes

    async def paused_issue(service: AuthService, current_user: User) -> TokenPair:
        login_locked.set()
        await asyncio.wait_for(allow_issue.wait(), timeout=5)
        return await original_issue(service, current_user)

    async def observed_lock(repository: UserRepository, user_id: UUID) -> bool:
        if login_locked.is_set():
            change_lock_requested.set()
        return await original_lock(repository, user_id)

    monkeypatch.setattr(AuthService, "_issue_pair", paused_issue)
    monkeypatch.setattr(UserRepository, "lock_session_changes", observed_lock)

    async def login() -> None:
        async with factory() as session:
            await AuthService(session).login(email=user.email, password=PASSWORD)

    async def change() -> None:
        async with factory() as session:
            current_user = await session.get(User, user.id)
            assert current_user is not None
            await AuthService(session).change_password(
                user=current_user,
                current_password=PASSWORD,
                new_password="replacement-password-123!",
            )

    login_task = asyncio.create_task(login())
    await asyncio.wait_for(login_locked.wait(), timeout=5)
    change_task = asyncio.create_task(change())
    await asyncio.wait_for(change_lock_requested.wait(), timeout=5)
    assert not change_task.done()
    allow_issue.set()
    await asyncio.gather(login_task, change_task)
    async with factory() as session:
        active = await session.scalar(
            select(func.count())
            .select_from(RefreshSession)
            .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        )
        assert active == 0
