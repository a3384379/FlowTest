"""Public API characterizations for frozen proposal approval boundaries."""

from copy import deepcopy
from typing import Any

import pytest
from test_mcp_read import (
    _controlled_write_payload,
    mcp_context,  # noqa: F401 - imported pytest fixture
)


@pytest.mark.asyncio
@pytest.mark.parametrize("item_type", ["test_design", "test_case"])
async def test_high_risk_approval_cannot_authorize_changed_oracle_content(
    mcp_context: dict[str, Any],  # noqa: F811
    item_type: str,
) -> None:
    client = mcp_context["client"]
    payload = _controlled_write_payload(mcp_context, objective="冻结审批绑定的合成设计")
    proposed = await client.post(
        "/api/v1/mcp/write/change-sets",
        headers={"Authorization": f"Bearer {mcp_context['write_token']}"},
        json=payload,
    )
    assert proposed.status_code == 202
    data = proposed.json()["data"]
    base = f"/api/v1/mcp/write/change-sets/{data['id']}"
    headers = {
        "Authorization": f"Bearer {mcp_context['human_token']}",
        "X-Organization-ID": str(mcp_context["organization_id"]),
    }
    approved = await client.post(base + "/approve", headers=headers, json={"note": "批准冻结原文"})
    assert approved.status_code == 200
    original_item = next(item for item in data["items"] if item["item_type"] == item_type)
    changed = deepcopy(original_item["proposed_content"])
    if item_type == "test_design":
        changed["oracles"][0]["expected"] = 201
    else:
        changed["name"] = "未被批准的新用例名"
    reviewed = await client.post(
        base + f"/items/{original_item['id']}/accept",
        headers=headers,
        json={"approval_id": approved.json()["data"]["approval"]["id"], "content": changed},
    )
    assert reviewed.status_code == 409, (
        "Changed oracle was accepted under an approval for different frozen content; "
        f"HTTP {reviewed.status_code}"
    )
    assert reviewed.json()["error"]["code"] == "MCP_APPROVAL_CONTENT_CHANGED"
    assert reviewed.json()["error"]["trace_id"]
    unchanged = await client.get(base, headers=headers)
    actual = next(
        item for item in unchanged.json()["data"]["items"] if item["id"] == original_item["id"]
    )
    assert actual["review_status"] == "pending"
    assert actual["materialized_resource_id"] is None
    assert actual["proposed_content"] == original_item["proposed_content"]
    accepted = await client.post(
        base + f"/items/{original_item['id']}/accept",
        headers=headers,
        json={
            "approval_id": approved.json()["data"]["approval"]["id"],
            "content": original_item["proposed_content"],
        },
    )
    assert accepted.status_code == 200
    saved = next(
        item for item in accepted.json()["data"]["items"] if item["id"] == original_item["id"]
    )
    assert saved["review_status"] == "accepted"
    assert saved["materialized_resource_id"] is not None


@pytest.mark.asyncio
async def test_low_risk_human_review_preserves_explicit_edit_behavior(
    mcp_context: dict[str, Any],  # noqa: F811
) -> None:
    client = mcp_context["client"]
    payload = _controlled_write_payload(mcp_context, objective="低风险人工编辑兼容")
    payload.update(confidence=1.0, risk_level="low", test_cases=[])
    payload["design"]["oracles"][0]["confidence"] = 1.0
    proposed = await client.post(
        "/api/v1/mcp/write/change-sets",
        headers={"Authorization": f"Bearer {mcp_context['write_token']}"},
        json=payload,
    )
    assert proposed.status_code == 202
    data = proposed.json()["data"]
    assert data["governance"]["manual_approval_required"] is False
    item = data["items"][0]
    changed = deepcopy(item["proposed_content"])
    changed["oracles"][0]["expected"] = 201
    reviewed = await client.post(
        f"/api/v1/mcp/write/change-sets/{data['id']}/items/{item['id']}/accept",
        headers={
            "Authorization": f"Bearer {mcp_context['human_token']}",
            "X-Organization-ID": str(mcp_context["organization_id"]),
        },
        json={"content": changed},
    )
    assert reviewed.status_code == 200
    accepted = reviewed.json()["data"]["items"][0]
    assert accepted["review_status"] == "accepted"
    assert accepted["proposed_content"]["oracles"][0]["expected"] == 201
