"""A public name edit invalidates the semantic target before revision-only apply checks."""

import pytest
from test_s51_mcp_flow_proposals import _plan_chain, _proposal_payload
from test_s51_mcp_flow_proposals import s51_context as s51_context


@pytest.mark.asyncio
async def test_public_name_edit_preserved_and_stale_proposal_returns_target_conflict(s51_context):
    fixture = s51_context
    context, plan, compilation = await _plan_chain(fixture)
    client = fixture["client"]
    project, workflow = fixture["project_id"], fixture["workflow_id"]
    proposed = await client.post(
        "/api/v1/mcp/flow/proposals",
        headers={**fixture["mcp_headers"], "Idempotency-Key": "public-stale-draft"},
        json={
            **_proposal_payload(fixture, context, plan, compilation),
            "workflow_id": str(workflow),
            "expected_revision": 1,
            "dry_run": False,
        },
    )
    assert proposed.status_code == 202
    root = f"/api/v1/projects/{project}/flow-specs/change-sets/{proposed.json()['change_set_id']}"
    accepted = await client.post(
        root + "/review", headers=fixture["user_headers"], json={"accept": True}
    )
    assert accepted.status_code == 200
    changed = await client.patch(
        f"/api/v1/projects/{project}/workflows/{workflow}",
        headers=fixture["user_headers"],
        json={"expected_revision": 1, "name": "公开人工修改保留"},
    )
    assert changed.status_code == 200
    refused = await client.post(root + "/apply", headers=fixture["user_headers"])
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "FLOWSPEC_TARGET_CONFLICT"
    assert refused.json()["error"]["trace_id"]
    current = await client.get(
        f"/api/v1/projects/{project}/workflows/{workflow}", headers=fixture["user_headers"]
    )
    assert current.json()["name"] == "公开人工修改保留"
    assert current.json()["draft_revision"] == 2
    proposal = await client.get(root, headers=fixture["user_headers"])
    assert proposal.json()["applied_at"] is None
