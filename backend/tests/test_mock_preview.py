from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_data_nodes_and_mock import DataTestContext, _create_project, _login_headers
from test_data_nodes_and_mock import data_context as data_context

from app.domain.access import ProjectRole
from app.models.access import AuditLog, Project, ProjectMember, User
from app.models.data_sources import MockRequestLog, MockRoute
from app.models.organizations import OrganizationMember
from app.schemas.data_sources import MockRouteWrite


@dataclass(frozen=True, slots=True)
class PreviewFixture:
    project_id: str
    service_id: str
    route_id: str
    headers: dict[str, str]
    draft: MockRouteWrite

    @property
    def endpoint(self) -> str:
        return f"/api/v1/projects/{self.project_id}/mock-services/{self.service_id}/routes/preview"


async def _preview_fixture(context: DataTestContext) -> PreviewFixture:
    headers = await _login_headers(context.client)
    project_id = await _create_project(context.client, headers)
    service = await context.client.post(
        f"/api/v1/projects/{project_id}/mock-services",
        headers=headers,
        json={"name": "只读预览测试服务", "slug": "preview-runtime"},
    )
    assert service.status_code == 201, service.text
    service_id = service.json()["id"]
    draft = MockRouteWrite(
        name="订单成功场景",
        method="POST",
        path_pattern="/orders/{id}",
        query_conditions={"mode": "full"},
        header_conditions={"X-Team": "orders"},
        response_status=201,
        response_headers={"X-Mock": "FlowTest"},
        response_body={
            "id": "{{path.id}}",
            "name": "{{body.profile.name}}",
            "scenario": "{{query._scenario}}",
        },
        scenario="happy",
        priority=50,
    )
    created = await context.client.post(
        f"/api/v1/projects/{project_id}/mock-services/{service_id}/routes",
        headers=headers,
        json=draft.model_dump(mode="json"),
    )
    assert created.status_code == 201, created.text
    return PreviewFixture(project_id, service_id, created.json()["id"], headers, draft)


def _request_sample() -> dict[str, object]:
    return {
        "method": "POST",
        "path": "/orders/42",
        "query": {"mode": "full", "_scenario": "happy"},
        "headers": {"X-Team": "orders", "X-FlowTest-Scenario": "ignored-by-query"},
        "body": {"profile": {"name": "Alice"}},
    }


async def _capture_counts(context: DataTestContext) -> tuple[int, int]:
    async with context.sessions() as session:
        audit = await session.scalar(select(func.count()).select_from(AuditLog))
        requests = await session.scalar(select(func.count()).select_from(MockRequestLog))
        return int(audit or 0), int(requests or 0)


@pytest.mark.asyncio
async def test_preview_uses_real_scenario_and_template_semantics_without_capture_writes(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    counts = await _capture_counts(data_context)
    response = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={
            "draft": fixture.draft.model_dump(mode="json"),
            "route_id": fixture.route_id,
            "request": _request_sample(),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["draft_matches"] and body["service_enabled"]
    assert body["selected"]["is_draft"] and body["selected"]["route_id"] == fixture.route_id
    assert body["selected"]["scenario"] == "happy"
    assert body["response"]["body"] == {"id": "42", "name": "Alice", "scenario": "happy"}
    assert await _capture_counts(data_context) == counts
    actual = await data_context.client.post(
        "/api/v1/mock/preview-runtime/orders/42",
        params={"mode": "full", "_scenario": "happy"},
        headers={"X-Team": "orders", "X-FlowTest-Scenario": "ignored-by-query"},
        json={"profile": {"name": "Alice"}},
    )
    assert actual.status_code == body["response"]["status_code"] == 201
    assert actual.json() == body["response"]["body"]
    assert actual.headers["x-mock"] == body["response"]["headers"]["X-Mock"]


@pytest.mark.asyncio
async def test_disabling_the_edited_rule_selects_the_real_same_scenario_fallback(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    fallback = fixture.draft.model_copy(
        update={
            "name": "订单后备规则",
            "priority": 10,
            "response_status": 202,
            "response_body": {"fallback": True},
        }
    )
    routes = f"/api/v1/projects/{fixture.project_id}/mock-services/{fixture.service_id}/routes"
    created = await data_context.client.post(
        routes, headers=fixture.headers, json=fallback.model_dump(mode="json")
    )
    assert created.status_code == 201
    disabled = fixture.draft.model_copy(update={"is_enabled": False})
    preview = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={
            "draft": disabled.model_dump(mode="json"),
            "route_id": fixture.route_id,
            "request": _request_sample(),
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert not body["draft_matches"] and not body["selected"]["is_draft"]
    assert body["selected"]["route_id"] == created.json()["id"]
    assert body["response"]["body"] == {"fallback": True}
    stored = await data_context.client.get(routes, headers=fixture.headers)
    assert next(row for row in stored.json() if row["id"] == fixture.route_id)["is_enabled"]
    saved = await data_context.client.put(
        f"{routes}/{fixture.route_id}",
        headers=fixture.headers,
        json=disabled.model_dump(mode="json"),
    )
    assert saved.status_code == 200 and saved.json()["id"] == fixture.route_id
    actual = await data_context.client.post(
        "/api/v1/mock/preview-runtime/orders/42",
        params={"mode": "full", "_scenario": "happy"},
        headers={"X-Team": "orders"},
        json={"profile": {"name": "Alice"}},
    )
    assert actual.status_code == 202 and actual.json() == body["response"]["body"]


@pytest.mark.asyncio
async def test_preview_returns_field_locations_and_standard_trace_for_invalid_inputs(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    invalid = fixture.draft.model_dump(mode="json")
    invalid["header_conditions"] = {"X-Team": 4}
    response = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={"draft": invalid, "request": _request_sample()},
    )
    assert response.status_code == 422 and response.json()["error"]["trace_id"]
    assert "header_conditions" in response.text
    missing = fixture.draft.model_copy(update={"response_body": {"nested": ["{{body.missing}}"]}})
    response = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={"draft": missing.model_dump(mode="json"), "request": _request_sample()},
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["trace_id"] and error["details"]["field"] == "response_body"
    assert error["details"]["pointer"] == "/nested/0"
    assert "body.missing" in error["message"]


@pytest.mark.asyncio
async def test_preview_is_read_only_for_viewers_and_scoped_to_project_service_and_route(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    async with data_context.sessions() as session:
        admin = await session.scalar(select(User).where(User.is_system_admin.is_(True)))
        project = await session.get(Project, UUID(fixture.project_id))
        assert admin is not None and project is not None
        viewer = User(
            email="mock-viewer@example.com",
            display_name="Mock只读成员",
            password_hash=admin.password_hash,
            is_active=True,
            requires_password_change=False,
        )
        session.add(viewer)
        await session.flush()
        session.add(
            OrganizationMember(
                organization_id=project.organization_id, user_id=viewer.id, role="member"
            )
        )
        session.add(
            ProjectMember(project_id=project.id, user_id=viewer.id, role=ProjectRole.VIEWER)
        )
        await session.commit()
    login = await data_context.client.post(
        "/api/v1/auth/login",
        json={"email": "mock-viewer@example.com", "password": "data-password-123!"},
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    payload = {
        "draft": fixture.draft.model_dump(mode="json"),
        "route_id": fixture.route_id,
        "request": _request_sample(),
    }
    before = await _capture_counts(data_context)
    preview = await data_context.client.post(fixture.endpoint, headers=viewer_headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert await _capture_counts(data_context) == before
    denied = await data_context.client.put(
        fixture.endpoint.removesuffix("preview") + fixture.route_id,
        headers=viewer_headers,
        json=payload["draft"],
    )
    assert denied.status_code == 403 and denied.json()["error"]["trace_id"]
    other_project = await _create_project(data_context.client, fixture.headers)
    for endpoint, request_body in [
        (fixture.endpoint.replace(fixture.project_id, other_project), payload),
        (fixture.endpoint.replace(fixture.service_id, str(uuid4())), payload),
        (fixture.endpoint, {**payload, "route_id": str(uuid4())}),
    ]:
        response = await data_context.client.post(
            endpoint, headers=fixture.headers, json=request_body
        )
        assert response.status_code == 404 and response.json()["error"]["trace_id"]
    inaccessible = await data_context.client.post(
        fixture.endpoint.replace(fixture.project_id, other_project),
        headers=viewer_headers,
        json=payload,
    )
    assert inaccessible.status_code in {403, 404}
    assert inaccessible.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_preview_matches_header_scenario_and_edited_priority_creation_order(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    routes = fixture.endpoint.removesuffix("/preview")
    newer = fixture.draft.model_copy(
        update={"name": "较新高优先级规则", "priority": 60, "response_body": {"newer": True}}
    )
    created = await data_context.client.post(
        routes, headers=fixture.headers, json=newer.model_dump(mode="json")
    )
    assert created.status_code == 201
    async with data_context.sessions() as session:
        older_row = await session.get(MockRoute, UUID(fixture.route_id))
        newer_row = await session.get(MockRoute, UUID(created.json()["id"]))
        assert older_row is not None and newer_row is not None
        older_row.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        older_row.response_body = {"id": "{{path.id}}", "name": "{{body.profile.name}}"}
        newer_row.created_at = datetime(2026, 1, 2, tzinfo=UTC)
        await session.commit()
    request = _request_sample()
    request["query"] = {"mode": "full"}
    request["headers"] = {"x-team": "orders", "X-FlowTest-Scenario": "happy"}
    edited = newer.model_copy(update={"priority": 50})
    preview = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={
            "draft": edited.model_dump(mode="json"),
            "route_id": created.json()["id"],
            "request": request,
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["selected"]["route_id"] == fixture.route_id
    assert preview.json()["response"]["body"] == {"id": "42", "name": "Alice"}
    saved = await data_context.client.put(
        f"{routes}/{created.json()['id']}",
        headers=fixture.headers,
        json=edited.model_dump(mode="json"),
    )
    assert saved.status_code == 200
    actual = await data_context.client.post(
        "/api/v1/mock/preview-runtime/orders/42",
        params={"mode": "full"},
        headers={"x-team": "orders", "X-FlowTest-Scenario": "happy"},
        json={"profile": {"name": "Alice"}},
    )
    assert actual.status_code == 201 and actual.json() == preview.json()["response"]["body"]


@pytest.mark.asyncio
async def test_preview_does_not_load_oversized_selected_saved_templates_or_truncate_catalogs(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    async with data_context.sessions() as session:
        stored = await session.get(MockRoute, UUID(fixture.route_id))
        assert stored is not None
        stored.response_body = "x" * 400_000
        await session.commit()
    preview = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={"draft": fixture.draft.model_dump(mode="json"), "request": _request_sample()},
    )
    assert preview.status_code == 422, preview.text
    error = preview.json()["error"]
    assert error["code"] == "MOCK_PREVIEW_LIMIT_EXCEEDED" and error["trace_id"]
    assert error["details"]["route_id"] == fixture.route_id
    async with data_context.sessions() as session:
        stored = await session.get(MockRoute, UUID(fixture.route_id))
        assert stored is not None
        session.add_all(
            [
                MockRoute(
                    mock_service_id=stored.mock_service_id,
                    created_by_id=stored.created_by_id,
                    name=f"有界规则{index}",
                    method="GET",
                    path_pattern=f"/catalog/{index}",
                    response_body=None,
                )
                for index in range(500)
            ]
        )
        await session.commit()
    preview = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={
            "draft": fixture.draft.model_dump(mode="json"),
            "route_id": fixture.route_id,
            "request": _request_sample(),
        },
    )
    assert (
        preview.status_code == 422
        and preview.json()["error"]["code"] == "MOCK_PREVIEW_LIMIT_EXCEEDED"
    )
    assert "未进行局部匹配" in preview.json()["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("path_pattern", "/orders/{id}/{id}"),
        ("response_headers", {"Content-Length": "42"}),
    ],
)
async def test_preview_reports_existing_draft_field_context(
    data_context: DataTestContext,
    field: str,
    value: object,
) -> None:
    fixture = await _preview_fixture(data_context)
    draft = fixture.draft.model_dump(mode="json")
    draft[field] = value
    response = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={"draft": draft, "route_id": fixture.route_id, "request": _request_sample()},
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["trace_id"]
    assert error["details"] == {"field": field, "pointer": "", "route_id": fixture.route_id}


@pytest.mark.asyncio
async def test_preview_rejects_an_oversized_saved_catalog_before_loading_metadata(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    async with data_context.sessions() as session:
        stored = await session.get(MockRoute, UUID(fixture.route_id))
        assert stored is not None
        stored.header_conditions = {"X-Large": "x" * (6 * 512 * 1024)}
        await session.commit()
    response = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={
            "draft": fixture.draft.model_dump(mode="json"),
            "route_id": fixture.route_id,
            "request": _request_sample(),
        },
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "MOCK_PREVIEW_LIMIT_EXCEEDED"
    assert error["trace_id"] and error["details"]["field"] == "request"


@pytest.mark.asyncio
async def test_preview_budgets_stored_unicode_by_utf8_instead_of_database_json_escapes(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    template = "中" * 20_000
    async with data_context.sessions() as session:
        stored = await session.get(MockRoute, UUID(fixture.route_id))
        assert stored is not None
        stored.response_body = template
        await session.commit()
    response = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={"draft": fixture.draft.model_dump(mode="json"), "request": _request_sample()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["selected"]["route_id"] == fixture.route_id
    assert response.json()["response"]["body"] == template


@pytest.mark.asyncio
async def test_preview_accepts_unicode_catalog_metadata_within_its_actual_utf8_budget(
    data_context: DataTestContext,
) -> None:
    fixture = await _preview_fixture(data_context)
    async with data_context.sessions() as session:
        stored = await session.get(MockRoute, UUID(fixture.route_id))
        assert stored is not None
        session.add_all(
            [
                MockRoute(
                    mock_service_id=stored.mock_service_id,
                    created_by_id=stored.created_by_id,
                    name=f"Unicode目录规则{index}",
                    method="GET",
                    path_pattern=f"/unicode/{index}",
                    query_conditions={"unicode": "中" * 5_000},
                    response_body=None,
                )
                for index in range(18)
            ]
        )
        await session.commit()
    response = await data_context.client.post(
        fixture.endpoint,
        headers=fixture.headers,
        json={
            "draft": fixture.draft.model_dump(mode="json"),
            "route_id": fixture.route_id,
            "request": _request_sample(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["selected"]["route_id"] == fixture.route_id
