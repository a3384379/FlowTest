"""Real file-SQLite HTTP race: a proposal item may materialize only once."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select
from test_tasking_api import _create_published_workflow, _login_headers
from test_tasking_api import tasking_context as tasking_context

from app.models.test_design import TestDesign as DesignModel
from app.repositories.ai_change_sets import AIChangeSetRepository


@pytest.mark.asyncio
async def test_concurrent_accept_returns_one_success_one_conflict_and_one_design(
    tasking_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = tasking_context.client
    headers = await _login_headers(client)
    project, _, _ = await _create_published_workflow(client, headers)
    detail = await client.get(f"/api/v1/projects/{project}", headers=headers)
    organization = detail.json()["organization_id"]
    headers["X-Organization-ID"] = organization
    created = await client.post(
        f"/api/v1/organizations/{organization}/service-accounts",
        headers=headers,
        json={
            "name": "并发接受fixture",
            "account_key": "review-concurrent",
            "scopes": ["mcp:write"],
        },
    )
    assert created.status_code == 201
    proposed = await client.post(
        "/api/v1/mcp/write/change-sets",
        headers={"Authorization": "Bearer " + created.json()["token"]},
        json={
            "project_id": project,
            "idempotency_key": "concurrent-one-item",
            "dry_run": False,
            "title": "并发合成设计",
            "confidence": 1.0,
            "risk_level": "low",
            "test_cases": [],
            "design": {
                "intent": {
                    "key": "concurrent-design",
                    "objective": "只能物化一次",
                    "acceptance_criteria": ["只创建一个设计"],
                },
                "oracles": [
                    {
                        "id": "status",
                        "kind": "status",
                        "expression": "$.status",
                        "operator": "equals",
                        "expected": 200,
                        "confidence": 1.0,
                    }
                ],
            },
        },
    )
    assert proposed.status_code == 202
    data = proposed.json()["data"]
    original = AIChangeSetRepository.get_change_set_for_update
    arrived, both = 0, asyncio.Event()

    async def parent_read(repository: AIChangeSetRepository, identity: Any) -> Any:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 5)
        return await original(repository, identity)

    monkeypatch.setattr(AIChangeSetRepository, "get_change_set_for_update", parent_read)
    path = f"/api/v1/mcp/write/change-sets/{data['id']}/items/{data['items'][0]['id']}/accept"
    responses = await asyncio.gather(
        client.post(path, headers=headers, json={}), client.post(path, headers=headers, json={})
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "MCP_CHANGE_ITEM_ALREADY_REVIEWED"
    assert conflict.json()["error"]["trace_id"]
    async with tasking_context.session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(DesignModel)) == 1
