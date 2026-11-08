"""Two separate ASGI apps/databases exercise native requests, not deployment acceptance."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_selftest_fixed_baseline import RunningAPI, _dependencies, _fixture_apps
from test_tasking_api import ADMIN_EMAIL, ADMIN_PASSWORD, TaskingTestContext, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.api.dependencies import get_session
from app.core.security import password_service
from app.main import app, create_app
from app.models.access import User
from app.models.base import Base

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.bootstrap import Installation  # noqa: E402
from scripts.selftest.contracts import Builds  # noqa: E402
from scripts.selftest.io import PublicAPI  # noqa: E402
from scripts.selftest.native_api_pack import execute_native_api_pack  # noqa: E402


@asynccontextmanager
async def isolated_target(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'target.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                display_name="隔离目标管理员",
                password_hash=password_service.hash(ADMIN_PASSWORD),
                is_active=True,
                is_system_admin=True,
                requires_password_change=False,
            )
        )
        await session.commit()
    target_app = create_app()

    async def get_target_session():
        async with sessions() as session:
            yield session

    target_app.dependency_overrides[get_session] = get_target_session
    async with httpx.AsyncClient(
        base_url="http://native-b.example",
        transport=httpx.ASGITransport(app=target_app, raise_app_exceptions=False),
    ) as client:
        login = await client.post(
            "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert login.status_code == 200, login.text
        api = PublicAPI(
            "http://native-b.example",
            login.json()["access_token"],
            transport=httpx.ASGITransport(app=target_app, raise_app_exceptions=False),
        )
        try:
            yield target_app, client, api
        finally:
            await api.close()
    await engine.dispose()


async def identity(
    api: PublicAPI,
    client: httpx.AsyncClient,
    *,
    email: str,
    project: str,
    organization: str,
    role: str = "viewer",
):
    initial, active = "initial-actor-password-123!", "active-actor-password-456!"
    user = await api.object(
        "POST", "/users", {"email": email, "password": initial, "display_name": "独立合成身份"}
    )
    await api.object(
        "PUT",
        f"/organizations/{organization}/members/{user['id']}",
        {"user_id": user["id"], "role": "admin" if role == "owner" else "member"},
    )
    await api.object(
        "PUT", f"/projects/{project}/members/{user['id']}", {"user_id": user["id"], "role": role}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": initial})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    if login.json()["user"]["requires_password_change"]:
        changed = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": initial, "new_password": active},
        )
        assert changed.status_code == 204, changed.text
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": active})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        active = initial
    return user, token, active


async def target_environment(api: PublicAPI, project: str):
    root = f"/projects/{project}"
    environment = await api.object(
        "POST",
        root + "/environments",
        {"name": "隔离B", "base_url": "http://native-b.example", "classification": "test"},
    )
    service = await api.object(
        "POST", root + "/services", {"name": "目标B", "service_key": "native_b"}
    )
    await api.object(
        "POST",
        root + f"/environments/{environment['id']}/service-endpoints",
        {"service_id": service["id"], "variant": "default", "base_url": "http://native-b.example"},
    )
    await api.object(
        "PATCH", root + f"/environments/{environment['id']}", {"default_service_id": service["id"]}
    )
    return environment, service


@pytest.mark.asyncio
async def test_native_api_pack_twelve_variants_keep_project_disposal_pending(
    tasking_context: TaskingTestContext, tmp_path: Path
) -> None:
    headers = await _login_headers(tasking_context.client)
    api = RunningAPI(tasking_context, headers["Authorization"].split(" ")[1])
    project, fixture_env, fixture_service = await _dependencies(api)
    a_project = await api.object("GET", f"/projects/{project}")
    capture, capture_token, _ = await identity(
        api,
        tasking_context.client,
        email="capture-viewer-native@example.com",
        project=project,
        organization=str(a_project["organization_id"]),
    )
    ci = await api.object(
        "POST",
        f"/projects/{project}/service-tokens",
        {"name": "只读证据", "scopes": ["read:execution"]},
    )
    reader = PublicAPI("http://test", str(ci["token"]), transport=httpx.ASGITransport(app=app))
    capture_reader = PublicAPI(
        "http://test",
        capture_token,
        str(a_project["organization_id"]),
        transport=httpx.ASGITransport(app=app),
    )
    business, management = _fixture_apps(tmp_path)
    observer = PublicAPI(
        "http://observer",
        "synthetic-observer-token-only-for-tests-0001",
        api_prefix="",
        transport=httpx.ASGITransport(app=management),
    )
    mock = httpx.AsyncClient(
        base_url="http://fixed-fixture.example", transport=httpx.ASGITransport(app=business)
    )
    async with isolated_target(tmp_path) as (_target_app, b_client, b):
        target_project = await b.object("POST", "/projects", {"name": "本轮独立B项目"})
        bp, bo = str(target_project["id"]), str(target_project["organization_id"])
        b.set_organization(bo)
        actor, _, actor_password = await identity(
            b,
            b_client,
            email="native-b-actor@example.com",
            project=bp,
            organization=bo,
            role="owner",
        )
        denied, _, denied_password = await identity(
            b, b_client, email="native-denied@example.com", project=bp, organization=bo
        )
        viewer, viewer_token, _ = await identity(
            b, b_client, email="native-observer@example.com", project=bp, organization=bo
        )
        await api.object(
            "PUT",
            f"/projects/{project}/secrets",
            {"name": "SELFTEST_B_PASSWORD", "value": actor_password},
        )
        await api.object(
            "PUT",
            f"/projects/{project}/secrets",
            {"name": "SELFTEST_B_DENIED_PASSWORD", "value": denied_password},
        )
        target_env, target_service = await target_environment(api, project)
        installation = Installation(
            binding_nonce="native-owned-binding-nonce",
            organization_id=UUID(str(a_project["organization_id"])),
            project_id=UUID(project),
            reviewer_id=UUID(capture["id"]),
            reviewer_email=capture["email"],
            mcp_account_id=UUID(capture["id"]),
            target_project_id=UUID(bp),
            target_organization_id=UUID(bo),
            target_user_id=UUID(actor["id"]),
            target_email=actor["email"],
            fixture_environment_id=UUID(fixture_env),
            target_environment_id=UUID(target_env["id"]),
            fixture_service_id=UUID(fixture_service),
            target_service_id=UUID(target_service["id"]),
            capture_viewer_id=UUID(capture["id"]),
            capture_viewer_email=capture["email"],
            target_viewer_id=UUID(viewer["id"]),
            target_viewer_email=viewer["email"],
            denied_user_id=UUID(denied["id"]),
            denied_email=denied["email"],
        )
        target_reader = PublicAPI(
            "http://native-b.example",
            viewer_token,
            bo,
            transport=httpx.ASGITransport(app=_target_app),
        )

        async def forward_mock(request: httpx.Request):
            result = await mock.request(
                request.method,
                request.url.raw_path.decode(),
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(
                result.status_code, content=result.content, headers=dict(result.headers)
            )

        async def forward_target(request: httpx.Request):
            result = await b_client.request(
                request.method,
                request.url.raw_path.decode(),
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(
                result.status_code, content=result.content, headers=dict(result.headers)
            )

        try:
            with respx.mock as routes:
                routes.route(host="fixed-fixture.example").mock(side_effect=forward_mock)
                routes.route(host="native-b.example").mock(side_effect=forward_target)
                result = await execute_native_api_pack(
                    api,
                    reader,
                    observer,
                    capture_reader=capture_reader,
                    target_reader=target_reader,
                    installation=installation,
                    batch_key="native-api-test",
                    nonce="native-api-test-nonce-001",
                    fixture_digest="a" * 64,
                    builds=Builds(
                        runner="candidate",
                        target="candidate",
                        fixture="a" * 64,
                        verifier="observer",
                    ),
                    output_dir=tmp_path / "native-api",
                )
            assert len(result.evidence.scenarios) == 12, result.report.model_dump_json(indent=2)
            findings = [
                (scenario.scenario_id, [item.code for item in scenario.findings])
                for scenario in result.report.scenarios
                if scenario.verification_status != "matched"
            ]
            assert findings == [("ST-API-003-project", ["DISPOSABLE_TARGET_CLEANUP_PENDING"])], (
                result.report.model_dump_json(indent=2)
            )
            assert result.report.exit_code != 0
            assert all(
                item.execution and item.execution.status == "passed"
                for item in result.evidence.scenarios
            )
            assert result.evidence.scenarios[-1].project_state.disposal_status == "pending"
            for path in (tmp_path / "native-api").rglob("*.json"):
                data = path.read_text()
                assert actor_password not in data and denied_password not in data
                assert viewer_token not in data and capture_token not in data
            assert not any(
                "/projects/" in str(call.request.url)
                and call.request.method == "DELETE"
                and str(call.request.url).endswith(
                    str(result.evidence.scenarios[-1].project_state.project_id)
                )
                for call in routes.calls
            )
        finally:
            await target_reader.close()
            await mock.aclose()
            await observer.close()
            await capture_reader.close()
            await reader.close()
            await api.close()
