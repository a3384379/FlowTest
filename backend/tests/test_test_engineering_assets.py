from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_flow_spec import ADMIN_EMAIL, ADMIN_PASSWORD, _create_portable_assets
from test_flow_spec import flow_spec_client as flow_spec_client

from app.core.database import get_session
from app.domain.access import ProjectRole
from app.main import app
from app.models.access import Project, ProjectMember, User
from app.models.organizations import OrganizationMember
from app.models.test_design import TestDesign as DesignModel


@asynccontextmanager
async def _database_session() -> AsyncIterator[AsyncSession]:
    sessions: AsyncIterator[AsyncSession] = app.dependency_overrides[get_session]()
    async with aclosing(sessions):
        yield await anext(sessions)


async def _proposal(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    logged_in = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert logged_in.status_code == 200
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    project_id, service_id, _ = await _create_portable_assets(client, headers, "Asset receipts")
    root = f"/api/v1/projects/{project_id}"
    api = await client.post(
        f"{root}/apis",
        headers=headers,
        json={
            "name": "Generated receipt source",
            "service_id": service_id,
            "request": {"method": "POST", "path": "/owned-orders"},
        },
    )
    environment = await client.post(
        f"{root}/environments",
        headers=headers,
        json={"name": "Receipt environment", "base_url": "https://example.test"},
    )
    assert api.status_code == environment.status_code == 201
    endpoint = await client.post(
        f"{root}/environments/{environment.json()['id']}/service-endpoints",
        headers=headers,
        json={"service_id": service_id, "variant": "default", "base_url": "https://example.test"},
    )
    assert endpoint.status_code == 201
    contract = {
        "operation": "owned.orders.create",
        "method": "POST",
        "path": "/owned-orders",
        "request": {
            "type": "object",
            "required": ["quantity"],
            "properties": {"quantity": {"type": "integer", "minimum": 1, "maximum": 2}},
        },
        "responses": {"200": {"description": "ok"}, "400": {"description": "invalid"}},
    }
    generated = await client.post(
        f"{root}/test-engineering/generate", headers=headers, json={"contract": contract}
    )
    assert generated.status_code == 200, generated.text
    evidence = generated.json()["evidence_details"]
    assert any(value["path"] == "body.quantity" for value in evidence)
    references = generated.json()["design"]["evidence_refs"]
    assert all(
        any(
            (value["id"], value["source_ref"], value["revision"])
            == (reference["id"], reference["source_ref"], reference["revision"])
            for reference in references
        )
        for value in evidence
    )
    candidates = generated.json()["design"]["scenarios"]
    ids = [value["id"] for value in candidates[:2]]
    proposed = await client.post(
        f"{root}/test-engineering/proposals",
        headers=headers,
        json={
            "title": "Two original generated assets",
            "api_definition_id": api.json()["definition"]["id"],
            "environment_id": environment.json()["id"],
            "contract": contract,
            "scenario_ids": ids,
        },
    )
    assert proposed.status_code == 201, proposed.text
    path = f"{root}/test-engineering/proposals/{proposed.json()['change_set_id']}"
    reviewed = await client.post(f"{path}/review", headers=headers, json={"accept": True})
    assert reviewed.status_code == 200, reviewed.text
    return headers, project_id, path


@pytest.mark.asyncio
async def test_materialized_asset_receipt_survives_refresh_and_mutable_case_edits(
    flow_spec_client: AsyncClient,
) -> None:
    client = flow_spec_client
    headers, project_id, path = await _proposal(client)
    before = await client.get(path, headers=headers)
    assert before.json()["materialization"] is None
    applied = await client.post(f"{path}/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    assert receipt["references_complete"] is True
    assert (
        len(receipt["assets"]) == len(receipt["workflow_ids"]) == len(receipt["test_case_ids"]) == 2
    )
    assert [asset["workflow_id"] for asset in receipt["assets"]] == receipt["workflow_ids"]
    refreshed = await client.get(path, headers=headers)
    assert refreshed.status_code == 200 and refreshed.json()["materialization"] == receipt
    assert refreshed.json()["design"] == before.json()["design"]
    assert refreshed.json()["fingerprint"] == before.json()["fingerprint"]
    case_id = receipt["test_case_ids"][0]
    case_path = f"/api/v1/projects/{project_id}/test-cases/{case_id}"
    case = await client.get(case_path, headers=headers)
    edited = await client.patch(
        case_path,
        headers=headers,
        json={
            "definition": {
                **case.json()["draft_definition"],
                "workflow_id": receipt["workflow_ids"][1],
            }
        },
    )
    assert edited.status_code == 200, edited.text
    again = await client.get(path, headers=headers)
    assert again.json()["materialization"] == receipt
    duplicate = await client.post(f"{path}/apply", headers=headers)
    assert duplicate.status_code == 409 and duplicate.json()["error"]["trace_id"]
    foreign = await client.post(
        "/api/v1/projects", headers=headers, json={"name": "Foreign receipt scope"}
    )
    hidden = await client.get(path.replace(project_id, foreign.json()["id"]), headers=headers)
    assert hidden.status_code == 404 and hidden.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_legacy_materialization_keeps_saved_cases_without_guessing_workflows(
    flow_spec_client: AsyncClient,
) -> None:
    client = flow_spec_client
    headers, _, path = await _proposal(client)
    applied = await client.post(f"{path}/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    async with _database_session() as session:
        model = await session.scalar(
            select(DesignModel).where(DesignModel.id == UUID(receipt["test_design_id"]))
        )
        assert model is not None
        model.materialized_assets = []
        await session.commit()
    restored = await client.get(path, headers=headers)
    assert restored.status_code == 200, restored.text
    result = restored.json()["materialization"]
    assert result["test_case_ids"] == receipt["test_case_ids"]
    assert result["workflow_ids"] == result["assets"] == []
    assert result["references_complete"] is False


@pytest.mark.asyncio
async def test_viewer_can_recover_receipts_but_cannot_review_or_materialize(
    flow_spec_client: AsyncClient,
) -> None:
    client = flow_spec_client
    headers, project_id, path = await _proposal(client)
    applied = await client.post(f"{path}/apply", headers=headers)
    assert applied.status_code == 200
    async with _database_session() as session:
        project = await session.get(Project, UUID(project_id))
        admin = await session.scalar(select(User).where(User.is_system_admin.is_(True)))
        assert project is not None and admin is not None
        viewer = User(
            email="design-viewer@example.test",
            display_name="设计只读成员",
            password_hash=admin.password_hash,
            is_active=True,
            is_system_admin=False,
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
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={"email": "design-viewer@example.test", "password": ADMIN_PASSWORD},
    )
    assert logged_in.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    restored = await client.get(path, headers=viewer_headers)
    assert restored.status_code == 200
    assert restored.json()["materialization"] == applied.json()
    for action, payload in (("apply", None), ("review", {"accept": True})):
        denied = await client.post(f"{path}/{action}", headers=viewer_headers, json=payload)
        assert denied.status_code == 403 and denied.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_foreign_persisted_asset_reference_is_not_exposed_as_an_owned_receipt(
    flow_spec_client: AsyncClient,
) -> None:
    client = flow_spec_client
    headers, project_id, path = await _proposal(client)
    applied = await client.post(f"{path}/apply", headers=headers)
    foreign_headers, foreign_project_id, foreign_path = await _proposal(client)
    assert foreign_project_id != project_id
    foreign = await client.post(f"{foreign_path}/apply", headers=foreign_headers)
    assert applied.status_code == foreign.status_code == 200
    foreign_workflow = foreign.json()["workflow_ids"][0]
    async with _database_session() as session:
        model = await session.get(DesignModel, UUID(applied.json()["test_design_id"]))
        assert model is not None
        model.materialized_assets = [
            {**model.materialized_assets[0], "workflow_id": foreign_workflow},
            model.materialized_assets[1],
        ]
        await session.commit()
    restored = await client.get(path, headers=headers)
    assert restored.status_code == 200
    result = restored.json()["materialization"]
    assert result["references_complete"] is False and len(result["assets"]) == 1
    assert foreign_workflow not in result["workflow_ids"]
