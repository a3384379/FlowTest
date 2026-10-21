"""M23 exact materialized design reads preserve review and project boundaries."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_mcp_read import _controlled_write_payload
from test_mcp_read import mcp_context as mcp_context

from app.core.security import password_service, token_service
from app.domain.access import ProjectRole
from app.models.access import AuditLog, ProjectMember, User
from app.models.ai import AIChangeItem
from app.models.organizations import OrganizationMember
from app.models.test_design import TestDesign as DesignModel


async def _accepted_design(context: dict[str, Any]) -> tuple[str, str, str, dict[str, str]]:
    client = context["client"]
    headers = {
        "Authorization": f"Bearer {context['human_token']}",
        "X-Organization-ID": str(context["organization_id"]),
    }
    payload = _controlled_write_payload(context, objective="核对已授权设计 alice@example.com")
    proposed = await client.post(
        "/api/v1/mcp/write/change-sets",
        headers={"Authorization": f"Bearer {context['write_token']}"},
        json=payload,
    )
    assert proposed.status_code == 202, proposed.text
    change_set = proposed.json()["data"]
    root = f"/api/v1/mcp/write/change-sets/{change_set['id']}"
    item = change_set["items"][0]
    pending = await client.get(f"{root}/items/{item['id']}/materialized-design", headers=headers)
    assert pending.status_code == 404
    approval = await client.post(f"{root}/approve", headers=headers, json={})
    assert approval.status_code == 200, approval.text
    accepted = await client.post(
        f"{root}/items/{item['id']}/accept",
        headers=headers,
        json={"approval_id": approval.json()["data"]["approval"]["id"]},
    )
    assert accepted.status_code == 200, accepted.text
    design_id = accepted.json()["data"]["items"][0]["materialized_resource_id"]
    return change_set["id"], item["id"], design_id, headers


@pytest.mark.asyncio
async def test_exact_materialized_design_reads_saved_asset_without_scanning_or_writes(
    mcp_context: dict[str, Any],
) -> None:
    change_id, item_id, design_id, headers = await _accepted_design(mcp_context)
    async with mcp_context["sessions"]() as session:
        item = await session.get(AIChangeItem, UUID(item_id))
        assert item is not None
        content = dict(item.proposed_content)
        content["intent"] = {**content["intent"], "objective": "后续变更提案不能冒充资产"}
        item.proposed_content = content
        await session.commit()
        before = await session.scalar(select(func.count()).select_from(AuditLog))
    root = f"/api/v1/mcp/write/change-sets/{change_id}/items/{item_id}/materialized-design"
    response = await mcp_context["client"].get(root, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == design_id and body["source_change_set_id"] == change_id
    assert body["project_id"] == str(mcp_context["project_id"])
    assert body["design"]["intent"]["objective"] == "核对已授权设计 alice@example.com"
    assert body["status"] == "approved" and body["reviewed_at"]
    async with mcp_context["sessions"]() as session:
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == before
    wrong_org = await mcp_context["client"].get(
        root, headers={**headers, "X-Organization-ID": str(uuid4())}
    )
    assert wrong_org.status_code in (403, 404)
    assert wrong_org.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_materialized_design_allows_project_viewer_and_rejects_foreign_asset_or_item(
    mcp_context: dict[str, Any],
) -> None:
    change_id, item_id, design_id, headers = await _accepted_design(mcp_context)
    async with mcp_context["sessions"]() as session:
        viewer = User(
            email="design-viewer@example.com",
            display_name="设计只读者",
            password_hash=password_service.hash("unused-viewer-password"),
            is_active=True,
            is_system_admin=False,
            requires_password_change=False,
        )
        session.add(viewer)
        await session.flush()
        session.add(
            ProjectMember(
                project_id=mcp_context["project_id"], user_id=viewer.id, role=ProjectRole.VIEWER
            )
        )
        session.add(
            OrganizationMember(
                organization_id=mcp_context["organization_id"], user_id=viewer.id, role="member"
            )
        )
        await session.commit()
        viewer_headers = {
            **headers,
            "Authorization": f"Bearer {token_service.create_access_token(viewer.id)}",
        }
    root = f"/api/v1/mcp/write/change-sets/{change_id}/items"
    allowed = await mcp_context["client"].get(
        f"{root}/{item_id}/materialized-design", headers=viewer_headers
    )
    assert allowed.status_code == 200, allowed.text
    missing = await mcp_context["client"].get(
        f"{root}/{uuid4()}/materialized-design", headers=headers
    )
    assert missing.status_code == 404 and missing.json()["error"]["trace_id"]
    async with mcp_context["sessions"]() as session:
        design = await session.get(DesignModel, UUID(design_id))
        assert design is not None
        design.project_id = mcp_context["other_project_id"]
        await session.commit()
    foreign = await mcp_context["client"].get(
        f"{root}/{item_id}/materialized-design", headers=headers
    )
    assert foreign.status_code == 404 and foreign.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_materialized_design_rejects_invalid_review_and_resource_associations(
    mcp_context: dict[str, Any],
) -> None:
    change_id, item_id, design_id, headers = await _accepted_design(mcp_context)
    root = f"/api/v1/mcp/write/change-sets/{change_id}/items/{item_id}/materialized-design"
    async with mcp_context["sessions"]() as session:
        item = await session.get(AIChangeItem, UUID(item_id))
        design = await session.get(DesignModel, UUID(design_id))
        assert item is not None and design is not None
        for field, invalid, original in (
            ("review_status", "pending", "accepted"),
            ("materialized_resource_type", "workflow", "test_design"),
            ("item_type", "test_case", "test_design"),
            ("change_set_id", uuid4(), UUID(change_id)),
        ):
            setattr(item, field, invalid)
            await session.commit()
            rejected = await mcp_context["client"].get(root, headers=headers)
            assert rejected.status_code == 404 and rejected.json()["error"]["trace_id"]
            setattr(item, field, original)
            await session.commit()
        design.source_change_set_id = uuid4()
        await session.commit()
        rejected = await mcp_context["client"].get(root, headers=headers)
        assert rejected.status_code == 404 and rejected.json()["error"]["trace_id"]
