"""Owned ASGI API/security regressions; no deployed-pack or all-matrix acceptance claim.

Production bootstrap is the only database initialization. Actors, tenancy, credentials,
assets and native runs are created through public APIs; only target HTTP is intercepted.
This module runs alone without imports from other test modules or sys.path mutation.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from uuid import UUID, uuid4

import jwt
import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_test_plan_dispatcher, get_workflow_coordinator
from app.core.config import settings
from app.core.database import get_session
from app.core.storage import LocalObjectStorage
from app.domain.runtime_profiles import RuntimeProfile
from app.main import app
from app.models import Base
from app.services.auth import bootstrap_administrator
from app.services.execution_events import InProcessExecutionEventBus
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunner
from app.services.workflow_coordinator import WorkflowRunCoordinator

PASSWORD = "Owned-characterization-password-17!"


def payload(response: Response, status: int) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def assert_error(response: Response, status: int, code: str) -> None:
    body = payload(response, status)
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert isinstance(body["error"]["trace_id"], str) and body["error"]["trace_id"]


class HeldPlanDispatcher:
    """Hold public dispatch until this test invokes the real native coordinator."""

    def __init__(self) -> None:
        self.run_ids: list[UUID] = []

    def start_test_plan(self, run_id: UUID, *, queue_name: str, priority: int) -> None:
        assert queue_name and 0 <= priority <= 9
        self.run_ids.append(run_id)


@dataclass(slots=True, repr=False)
class SecurityWorld:
    client: AsyncClient
    session_maker: async_sessionmaker[AsyncSession]
    events: InProcessExecutionEventBus
    queue: HeldPlanDispatcher
    owner: dict[str, str]
    viewer: dict[str, str]
    outsider: dict[str, str]
    owner_login: dict[str, str]
    project: str
    foreign_project: str
    organization: str
    foreign_organization: str


async def login(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": "Bearer " + payload(response, 200)["access_token"]}


async def create_actor(
    client: AsyncClient, admin: dict[str, str], name: str
) -> tuple[str, dict[str, str]]:
    email = f"{name}-{uuid4().hex}@example.com"
    user = payload(
        await client.post(
            "/api/v1/users",
            headers=admin,
            json={"email": email, "display_name": name, "password": PASSWORD},
        ),
        201,
    )
    return user["id"], {"email": email, "password": PASSWORD}


async def add_member(
    client: AsyncClient, headers: dict[str, str], organization: str, user: str
) -> None:
    payload(
        await client.put(
            f"/api/v1/organizations/{organization}/members/{user}",
            headers=headers,
            json={"user_id": user, "role": "member"},
        ),
        200,
    )


async def setup_world(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    events: InProcessExecutionEventBus,
    queue: HeldPlanDispatcher,
) -> SecurityWorld:
    admin = await login(client, settings.bootstrap_admin_email)
    owner_id, owner_login = await create_actor(client, admin, "owner")
    viewer_id, viewer_login = await create_actor(client, admin, "viewer")
    outsider_id, outsider_login = await create_actor(client, admin, "outsider")
    owner = await login(client, owner_login["email"])
    viewer = await login(client, viewer_login["email"])
    outsider = await login(client, outsider_login["email"])
    organizations = []
    for name, slug in (("隔离主组织", "security-primary"), ("隔离外组织", "security-foreign")):
        organizations.append(
            payload(
                await client.post(
                    "/api/v1/organizations", headers=admin, json={"name": name, "slug": slug}
                ),
                201,
            )["id"]
        )
    primary_org, foreign_org = organizations
    await add_member(client, admin, primary_org, owner_id)
    await add_member(client, admin, primary_org, viewer_id)
    await add_member(client, admin, foreign_org, owner_id)
    await add_member(client, admin, foreign_org, outsider_id)
    owner["X-Organization-ID"] = primary_org
    viewer["X-Organization-ID"] = primary_org
    outsider["X-Organization-ID"] = foreign_org
    primary = payload(
        await client.post(
            "/api/v1/projects",
            headers=owner,
            json={"name": "隔离主项目", "organization_id": primary_org},
        ),
        201,
    )
    foreign = payload(
        await client.post(
            "/api/v1/projects",
            headers=outsider,
            json={"name": "隔离外项目", "organization_id": foreign_org},
        ),
        201,
    )
    payload(
        await client.put(
            f"/api/v1/projects/{primary['id']}/members/{viewer_id}",
            headers=owner,
            json={"user_id": viewer_id, "role": "viewer"},
        ),
        200,
    )
    return SecurityWorld(
        client,
        factory,
        events,
        queue,
        owner,
        viewer,
        outsider,
        owner_login,
        primary["id"],
        foreign["id"],
        primary_org,
        foreign_org,
    )


@pytest.fixture
async def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SecurityWorld]:
    monkeypatch.setattr(settings, "runtime_profile", RuntimeProfile.STANDALONE)
    monkeypatch.setattr(settings, "bootstrap_admin_password", PASSWORD)
    monkeypatch.setattr(
        "app.services.artifacts.object_storage", LocalObjectStorage(tmp_path / "objects")
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'owned-api-security.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        await bootstrap_administrator(session)

    async def sessions() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    events = InProcessExecutionEventBus(retention_seconds=60)
    coordinator = WorkflowRunCoordinator(factory, events)
    queue = HeldPlanDispatcher()
    prior_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_workflow_coordinator] = lambda: coordinator
    app.dependency_overrides[get_test_plan_dispatcher] = lambda: queue
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://owned-security",
        ) as client:
            yield await setup_world(client, factory, events, queue)
    finally:
        await coordinator.shutdown()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior_overrides)
        await engine.dispose()


async def test_native_api001_invalid_credentials_and_invalid_access_token(
    world: SecurityWorld,
) -> None:
    assert_error(
        await world.client.post(
            "/api/v1/auth/login",
            json={**world.owner_login, "password": "deliberately-invalid"},
        ),
        401,
        "INVALID_CREDENTIALS",
    )
    assert_error(
        await world.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}),
        401,
        "INVALID_ACCESS_TOKEN",
    )


async def test_native_api001_refresh_rotation_logout_and_existing_access_semantics(
    world: SecurityWorld,
) -> None:
    client = world.client
    access = await login(client, world.owner_login["email"])
    first_refresh = client.cookies.get("flowtest_refresh")
    assert first_refresh
    refreshed = await client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "FlowTest"})
    assert refreshed.status_code == 200 and refreshed.headers["cache-control"] == "no-store"
    assert client.cookies.get("flowtest_refresh") != first_refresh
    logout = await client.post("/api/v1/auth/logout", headers={"X-Requested-With": "FlowTest"})
    assert logout.status_code == 204 and logout.headers["cache-control"] == "no-store"
    assert client.cookies.get("flowtest_refresh") is None
    assert_error(
        await client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "FlowTest"}),
        401,
        "INVALID_REFRESH_TOKEN",
    )
    # Current API revokes the refresh chain; existing signed access JWT keeps its TTL.
    payload(await client.get("/api/v1/auth/me", headers=access), 200)


async def test_native_api001_server_minted_access_expiry_has_exact_error_with_elapsed_clock(
    world: SecurityWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = await login(world.client, world.owner_login["email"])

    class ElapsedAccessClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return datetime.now(tz) + timedelta(minutes=61)

    # Keep the valid deployment TTL; advance only JWT validation's clock after public login.
    # This is an ASGI clock-controlled boundary check, not a natural deployment-expiry run.
    with monkeypatch.context() as elapsed:
        elapsed.setattr(jwt.api_jwt, "datetime", ElapsedAccessClock)
        assert_error(
            await world.client.get("/api/v1/auth/me", headers=issued), 401, "ACCESS_TOKEN_EXPIRED"
        )


async def test_native_api002_viewer_write_denied_without_resource_change(
    world: SecurityWorld,
) -> None:
    root = f"/api/v1/projects/{world.project}"
    before = payload(await world.client.get(root, headers=world.owner), 200)
    payload(await world.client.get(root, headers=world.viewer), 200)
    assert_error(
        await world.client.patch(root, headers=world.viewer, json={"name": "不得生效"}),
        403,
        "PROJECT_FORBIDDEN",
    )
    after = payload(await world.client.get(root, headers=world.owner), 200)
    assert after["name"] == before["name"] and after["updated_at"] == before["updated_at"]


async def test_native_api002_nonmember_and_cross_organization_are_hidden(
    world: SecurityWorld,
) -> None:
    root = f"/api/v1/projects/{world.project}"
    assert_error(await world.client.get(root, headers=world.outsider), 404, "PROJECT_NOT_FOUND")
    assert_error(
        await world.client.get(
            root, headers={**world.owner, "X-Organization-ID": world.foreign_organization}
        ),
        404,
        "PROJECT_NOT_FOUND",
    )
    payload(await world.client.get(root, headers=world.owner), 200)


async def read_token(world: SecurityWorld, **extra: object) -> dict:
    return payload(
        await world.client.post(
            f"/api/v1/projects/{world.project}/service-tokens",
            headers=world.owner,
            json={"name": "隔离只读令牌", "scopes": ["read:execution"], **extra},
        ),
        201,
    )


async def test_native_sec001_token_is_writeonly_cross_project_denied_and_revoked(
    world: SecurityWorld,
) -> None:
    root = f"/api/v1/projects/{world.project}"
    token = await read_token(world)
    listed = await world.client.get(root + "/service-tokens", headers=world.owner)
    assert token["token"] not in listed.text
    assert "token" not in next(item for item in payload(listed, 200) if item["id"] == token["id"])
    ci = f"/api/v1/ci/projects/{world.project}/test-plan-runs/{uuid4()}"
    reader = {"Authorization": "Bearer " + token["token"]}
    assert_error(await world.client.get(ci, headers=reader), 404, "TEST_PLAN_RUN_NOT_FOUND")
    assert_error(
        await world.client.get(ci.replace(world.project, world.foreign_project), headers=reader),
        401,
        "INVALID_SERVICE_TOKEN",
    )
    payload(
        await world.client.delete(root + "/service-tokens/" + token["id"], headers=world.owner), 200
    )
    assert_error(await world.client.get(ci, headers=reader), 401, "INVALID_SERVICE_TOKEN")


async def test_native_sec001_publicly_issued_service_token_naturally_expires(
    world: SecurityWorld,
) -> None:
    token = await read_token(
        world, expires_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    )
    await asyncio.sleep(1.1)
    assert_error(
        await world.client.get(
            f"/api/v1/ci/projects/{world.project}/test-plan-runs/{uuid4()}",
            headers={"Authorization": "Bearer " + token["token"]},
        ),
        401,
        "INVALID_SERVICE_TOKEN",
    )


async def test_native_sec002_owner_and_self_signed_tokens_cannot_be_deployment_agents(
    world: SecurityWorld,
) -> None:
    token = await read_token(world)
    forged = jwt.encode(
        {
            "sub": "owner",
            "iss": "owner-self-signed",
            "aud": "flowtest-selftest",
            "exp": (datetime.now(UTC) + timedelta(minutes=1)).timestamp(),
        },
        "project-owner-controlled-key-with-32-bytes",
        algorithm="HS256",
    )
    for authorization in (
        world.owner,
        {"Authorization": "Bearer " + token["token"]},
        {"Authorization": "Bearer " + forged},
    ):
        assert_error(
            await world.client.get(
                f"/api/v1/agent/projects/{world.project}/self-tests/tasks", headers=authorization
            ),
            401,
            "SELFTEST_AGENT_UNAUTHORIZED",
        )


async def test_native_sec002_secret_values_are_writeonly_at_public_api(
    world: SecurityWorld,
) -> None:
    root = f"/api/v1/projects/{world.project}"
    secret = "synthetic-owned-secret-never-in-response"
    written = await world.client.put(
        root + "/secrets", headers=world.owner, json={"name": "security_private", "value": secret}
    )
    body = payload(written, 200)
    assert secret not in written.text and "value" not in body and "ciphertext" not in body
    listed = await world.client.get(root + "/secrets", headers=world.owner)
    assert secret not in listed.text
    assert all("value" not in item and "ciphertext" not in item for item in payload(listed, 200))


async def test_native_sec002_project_owner_cannot_mint_trusted_verification_scope(
    world: SecurityWorld,
) -> None:
    denied = await world.client.post(
        f"/api/v1/projects/{world.project}/service-tokens",
        headers=world.owner,
        json={"name": "不能授权受信Observer", "scopes": ["write:trusted-verification"]},
    )
    assert_error(denied, 422, "VALIDATION_ERROR")


def graph(configs: list[dict]) -> dict:
    nodes = [{"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}}]
    for index, config in enumerate(configs):
        nodes.append(
            {
                "id": f"request_{index}",
                "type": "api",
                "name": f"请求{index}",
                "position": {"x": 100 + index * 100, "y": 0},
                "config": config,
            }
        )
    nodes.append({"id": "end", "type": "end", "name": "结束", "position": {"x": 900, "y": 0}})
    return {
        "nodes": nodes,
        "edges": [
            {"id": f"edge_{index}", "source": nodes[index]["id"], "target": nodes[index + 1]["id"]}
            for index in range(len(nodes) - 1)
        ],
    }


async def assets(
    world: SecurityWorld,
    request: dict,
    definition_configs: Callable[[str], list[dict]] | None = None,
) -> tuple[str, str, str]:
    root = f"/api/v1/projects/{world.project}"
    environment = payload(
        await world.client.post(
            root + "/environments",
            headers=world.owner,
            json={"name": "隔离目标-" + uuid4().hex, "base_url": "https://fixture.example.com"},
        ),
        201,
    )["id"]
    api = payload(
        await world.client.post(
            root + "/apis", headers=world.owner, json={"name": "隔离请求", "request": request}
        ),
        201,
    )["definition"]["id"]
    configs = (
        definition_configs(api)
        if definition_configs
        else [{"api_definition_id": api, "api_version": 1}]
    )
    workflow = payload(
        await world.client.post(
            root + "/workflows",
            headers=world.owner,
            json={"name": "隔离流程-" + uuid4().hex, "definition": graph(configs)},
        ),
        201,
    )["id"]
    payload(
        await world.client.post(root + f"/workflows/{workflow}/versions", headers=world.owner), 200
    )
    return environment, api, workflow


async def execute(world: SecurityWorld, workflow: str, environment: str, version: int = 1) -> dict:
    root = f"/api/v1/projects/{world.project}"
    started = payload(
        await world.client.post(
            root + f"/workflows/{workflow}/executions",
            headers=world.owner,
            json={"environment_id": environment, "version": version},
        ),
        202,
    )
    for _ in range(100):
        detail = payload(
            await world.client.get(
                root + f"/workflow-executions/{started['id']}", headers=world.owner
            ),
            200,
        )
        if detail["execution"]["status"] not in {"queued", "running"}:
            return detail
        await asyncio.sleep(0.02)
    raise AssertionError("Native execution did not become terminal within the bounded poll")


@respx.mock
async def test_native_api006_auth_suppression_is_node_local_and_no_duplicate_header(
    world: SecurityWorld,
) -> None:
    environment, _, workflow = await assets(
        world,
        {
            "method": "GET",
            "path": "/auth-suppression",
            "body_kind": "none",
            "auth": {"kind": "bearer", "values": {"token": "synthetic-API-bearer"}},
        },
        lambda api: [
            {"api_definition_id": api, "api_version": 1},
            {
                "api_definition_id": api,
                "api_version": 1,
                "request_overrides": {
                    "auth_mode": "disabled",
                    "suppressed_headers": ["Authorization"],
                },
            },
            {"api_definition_id": api, "api_version": 1},
        ],
    )
    route = respx.get("https://fixture.example.com/auth-suppression").mock(
        return_value=Response(200, json={"ok": True})
    )
    assert (await execute(world, workflow, environment))["execution"]["status"] == "passed"
    assert [call.request.headers.get_list("authorization") for call in route.calls] == [
        ["Bearer synthetic-API-bearer"],
        [],
        ["Bearer synthetic-API-bearer"],
    ]


@respx.mock
async def test_native_api007_nested_json_omitted_body_and_null_stay_distinct_on_wire(
    world: SecurityWorld,
) -> None:
    expected = {
        "zero": 0,
        "false": False,
        "empty": "",
        "null": None,
        "chinese": "中文",
        "nested": [{"value": 0, "flag": False, "null": None}],
    }
    environment, _, workflow = await assets(
        world,
        {
            "method": "POST",
            "path": "/nested",
            "body_kind": "json",
            "body": expected,
            "query_parameters": [{"name": "empty", "value": ""}, {"name": "中文", "value": "值"}],
        },
    )
    route = respx.post("https://fixture.example.com/nested").mock(
        return_value=Response(200, json={"ok": True})
    )
    assert (await execute(world, workflow, environment))["execution"]["status"] == "passed"
    assert len(route.calls) == 1
    wire = route.calls[0].request
    assert json.loads(wire.content) == expected
    assert "omitted" not in json.loads(wire.content) and json.loads(wire.content)["null"] is None
    assert wire.url.params.multi_items() == [("empty", ""), ("中文", "值")]
    empty_environment, _, empty_workflow = await assets(
        world, {"method": "POST", "path": "/omitted", "body_kind": "none"}
    )
    empty = respx.post("https://fixture.example.com/omitted").mock(
        return_value=Response(200, json={"ok": True})
    )
    assert (await execute(world, empty_workflow, empty_environment))["execution"][
        "status"
    ] == "passed"
    assert empty.calls[0].request.content == b"" and empty.calls[0].request.content != b"null"


@respx.mock
async def test_native_api009_historical_versions_ignore_draft_and_stale_write_is_exact_conflict(
    world: SecurityWorld,
) -> None:
    environment, _, workflow = await assets(
        world, {"method": "POST", "path": "/version", "body_kind": "json", "body": {"version": 1}}
    )
    root = f"/api/v1/projects/{world.project}/workflows/{workflow}"
    old = payload(await world.client.get(root, headers=world.owner), 200)
    definition = deepcopy(old["draft_definition"])
    definition["nodes"][1]["config"]["request_overrides"] = {
        "body": {"kind": "json", "value": {"version": 2}}
    }
    changed = payload(
        await world.client.patch(
            root,
            headers=world.owner,
            json={"expected_revision": old["draft_revision"], "definition": definition},
        ),
        200,
    )
    v2 = payload(await world.client.post(root + "/versions", headers=world.owner), 200)
    assert v2["version"] == 2
    assert_error(
        await world.client.patch(
            root,
            headers=world.owner,
            json={"expected_revision": old["draft_revision"], "name": "旧草稿不可覆盖"},
        ),
        409,
        "WORKFLOW_DRAFT_CONFLICT",
    )
    definition["nodes"][1]["config"]["request_overrides"]["body"]["value"] = {"version": 3}
    payload(
        await world.client.patch(
            root,
            headers=world.owner,
            json={"expected_revision": changed["draft_revision"], "definition": definition},
        ),
        200,
    )
    route = respx.post("https://fixture.example.com/version").mock(
        return_value=Response(200, json={"ok": True})
    )
    history = await execute(world, workflow, environment, 1)
    current = await execute(world, workflow, environment, 2)
    assert history["execution"]["status"] == current["execution"]["status"] == "passed"
    assert [json.loads(call.request.content) for call in route.calls] == [
        {"version": 1},
        {"version": 2},
    ]
    versions = payload(await world.client.get(root + "/versions", headers=world.owner), 200)
    assert history["execution"]["workflow_version_id"] == versions[-1]["id"]
    assert current["execution"]["workflow_version_id"] == v2["id"]
    frozen = history["execution"]["snapshot"]["workflow"]
    assert frozen["fingerprint"] == versions[-1]["fingerprint"] and frozen["version"] == 1
    # The execution snapshot omits optional nulls; compare all edge semantics.
    fields = ("id", "source", "target", "condition", "mappings")
    assert [tuple(edge.get(key) for key in fields) for edge in frozen["definition"]["edges"]] == [
        tuple(edge.get(key) for key in fields) for edge in versions[-1]["definition"]["edges"]
    ]


@respx.mock
async def test_native_sec001_real_terminal_run_pages_safe_fields_and_denied_mutations(
    world: SecurityWorld,
) -> None:
    environment, _, workflow = await assets(
        world, {"method": "GET", "path": "/readonly", "body_kind": "none"}
    )
    root = f"/api/v1/projects/{world.project}"
    another = payload(
        await world.client.post(
            root + "/workflows",
            headers=world.owner,
            json={"name": "分页第二流程", "definition": graph([])},
        ),
        201,
    )["id"]
    payload(
        await world.client.post(root + f"/workflows/{another}/versions", headers=world.owner), 200
    )
    plan = payload(
        await world.client.post(
            root + "/test-plans",
            headers=world.owner,
            json={
                "name": "实际分页计划",
                "items": [
                    {
                        "workflow_id": item,
                        "environment_id": environment,
                        "runtime_headers": {"Authorization": "synthetic-private-header"},
                        "runtime_variables": {"private": "synthetic-private-context"},
                    }
                    for item in (workflow, another)
                ],
            },
        ),
        201,
    )["id"]
    run = payload(
        await world.client.post(root + f"/test-plans/{plan}/runs", headers=world.owner), 202
    )["id"]
    assert UUID(run) in world.queue.run_ids
    respx.get("https://fixture.example.com/readonly").mock(
        return_value=Response(200, json={"private": "synthetic-private-body"})
    )
    await PlanRunner(world.session_maker, world.events).run(UUID(run))
    token = await read_token(world)
    reader = {"Authorization": "Bearer " + token["token"]}
    ci = f"/api/v1/ci/projects/{world.project}"
    path = ci + f"/test-plan-runs/{run}"
    first = payload(await world.client.get(path, headers=reader, params={"page_size": 1}), 200)
    second = payload(
        await world.client.get(path, headers=reader, params={"page_size": 1, "page": 2}), 200
    )
    assert first["status"] == "passed" and first["total"] == second["total"] == 2
    assert first["has_more"] and not second["has_more"]
    assert {x["id"] for x in first["items"]}.isdisjoint({x["id"] for x in second["items"]})
    execution = first["items"][0]["execution_id"]
    evidence = payload(
        await world.client.get(ci + f"/workflow-executions/{execution}/evidence", headers=reader),
        200,
    )
    assert evidence["source_plan_run_item_id"] == first["items"][0]["id"]
    assert evidence["project_id"] == world.project and evidence["status"] == "passed"
    serialized = json.dumps([first, second, evidence])
    for secret in (
        token["token"],
        "synthetic-private-header",
        "synthetic-private-context",
        "synthetic-private-body",
    ):
        assert secret not in serialized
    assert all(
        field not in evidence for field in ("snapshot", "context", "output", "headers", "body")
    )
    assert_error(
        await world.client.get(path, headers=reader, params={"page_size": 101}),
        422,
        "VALIDATION_ERROR",
    )
    for method, target, data in (
        ("POST", root + f"/test-plans/{plan}/runs", None),
        ("PATCH", root + f"/workflows/{workflow}", {"expected_revision": 1, "name": "禁止修改"}),
        ("POST", root + f"/workflow-executions/{execution}/cancel", {}),
        ("DELETE", root + f"/workflows/{workflow}", None),
    ):
        assert_error(
            await world.client.request(method, target, headers=reader, json=data),
            401,
            "INVALID_ACCESS_TOKEN",
        )
    after = payload(await world.client.get(path, headers=reader), 200)
    assert after["status"] == "passed" and len(after["items"]) == 2
