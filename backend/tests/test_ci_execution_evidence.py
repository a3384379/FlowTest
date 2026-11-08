"""Restricted execution evidence authenticates independently from execute permission."""

import hashlib
from typing import Any
from uuid import UUID, uuid4

import respx
from httpx import Response
from test_tasking_api import (
    TaskingTestContext,
    _create_published_workflow,
    _login_headers,
    _workflow_definition,
)
from test_tasking_api import tasking_context as tasking_context

from app.models.workflows import WorkflowControlRecord
from app.services.test_plan_runner import TestPlanRunCoordinator as PlanRunCoordinator


async def _finished_run(context: TaskingTestContext) -> dict[str, Any]:
    client = context.client
    headers = await _login_headers(client)
    project_id, environment_id, workflow_id = await _create_published_workflow(client, headers)
    root = f"/api/v1/projects/{project_id}"
    apis = (await client.get(f"{root}/apis", headers=headers)).json()
    api_id = apis["items"][0]["id"]
    definition = _workflow_definition(api_id)
    definition["nodes"].insert(
        2,
        {  # type: ignore[attr-defined]
            "id": "assert_canary",
            "type": "assert",
            "name": "验证响应",
            "position": {"x": 150, "y": 0},
            "config": {"source_node_id": "api", "expression": "body.actual", "expected": 2},
        },
    )
    definition["edges"] = [
        {"id": "a", "source": "start", "target": "api"},
        {"id": "b", "source": "api", "target": "assert_canary"},
        {"id": "c", "source": "assert_canary", "target": "end"},
    ]
    current = (await client.get(f"{root}/workflows/{workflow_id}", headers=headers)).json()
    changed = await client.patch(
        f"{root}/workflows/{workflow_id}",
        headers=headers,
        json={"definition": definition, "expected_revision": current["draft_revision"]},
    )
    assert changed.status_code == 200, changed.text
    published = await client.post(f"{root}/workflows/{workflow_id}/versions", headers=headers)
    assert published.status_code == 200, published.text
    plan = await client.post(
        f"{root}/test-plans",
        headers=headers,
        json={
            "name": "独立证据计划",
            "items": [
                {
                    "workflow_id": workflow_id,
                    "environment_id": environment_id,
                    "runtime_headers": {"Authorization": "Bearer synthetic-private-header"},
                    "runtime_variables": {"private_value": "synthetic-private-context"},
                }
            ],
        },
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]
    run = await client.post(f"{root}/test-plans/{plan_id}/runs", headers=headers)
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]
    with respx.mock:
        respx.get("http://workflow.example.com/users/v1").mock(
            return_value=Response(
                200,
                json={"actual": 1, "secret": "synthetic-private-body"},
                headers={"Set-Cookie": "synthetic-private-cookie"},
            )
        )
        await PlanRunCoordinator(context.session_maker, context.events).run(UUID(run_id))
    detail = (await client.get(f"{root}/test-plan-runs/{run_id}", headers=headers)).json()
    execution_id = detail["items"][0]["workflow_execution_id"]
    token = await client.post(
        f"{root}/service-tokens",
        headers=headers,
        json={
            "name": "只读证据",
            "scopes": ["read:execution"],
        },
    )
    assert token.status_code == 201, token.text
    return {
        "project": project_id,
        "plan": plan_id,
        "run": run_id,
        "execution": execution_id,
        "headers": headers,
        "token": token.json(),
        "detail": detail,
    }


async def test_read_scope_returns_exact_failure_and_safe_hashes(
    tasking_context: TaskingTestContext,
) -> None:
    state = await _finished_run(tasking_context)
    client = tasking_context.client
    headers = {"Authorization": f"Bearer {state['token']['token']}"}
    root = f"/api/v1/ci/projects/{state['project']}"
    plan = await client.get(f"{root}/test-plan-runs/{state['run']}", headers=headers)
    assert plan.status_code == 200, plan.text
    assert plan.json()["status"] == "failed"
    assert plan.json()["items"][0]["execution_ids"] == [state["execution"]]
    assert plan.json()["items"][0]["attempts_complete"] is True
    response = await client.get(
        f"{root}/workflow-executions/{state['execution']}/evidence", headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "WORKFLOW_ASSERTION_FAILED"
    assert data["source_plan_run_item_id"] == state["detail"]["items"][0]["id"]
    assertion = next(node for node in data["nodes"] if node["node_id"] == "assert_canary")
    assert assertion["phase"] == "main"
    assert assertion["assertions_complete"] is True
    assert assertion["assertions"] == [
        {
            "name": "workflow_assertion",
            "passed": False,
            "expected_digest": hashlib.sha256(b"2").hexdigest(),
            "actual_digest": hashlib.sha256(b"1").hexdigest(),
        }
    ]
    for private in (
        "synthetic-private-header",
        "synthetic-private-context",
        "synthetic-private-body",
        "synthetic-private-cookie",
    ):
        assert private not in plan.text + response.text
    assert "snapshot" not in data and "context" not in data and "output" not in assertion
    denied = await client.post(f"{root}/test-plans/{state['plan']}/runs", headers=headers)
    assert denied.status_code == 401
    assert denied.json()["error"]["trace_id"]


async def test_scope_project_revocation_and_missing_auth_are_enforced(
    tasking_context: TaskingTestContext,
) -> None:
    state = await _finished_run(tasking_context)
    client = tasking_context.client
    root = f"/api/v1/ci/projects/{state['project']}"
    path = f"{root}/workflow-executions/{state['execution']}/evidence"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=state["headers"])).status_code == 401
    execute = await client.post(
        f"/api/v1/projects/{state['project']}/service-tokens",
        headers=state["headers"],
        json={
            "name": "仅执行",
            "scopes": ["execute:test-plan"],
        },
    )
    assert (
        await client.get(path, headers={"Authorization": f"Bearer {execute.json()['token']}"})
    ).status_code == 401
    headers = {"Authorization": f"Bearer {state['token']['token']}"}
    cross = path.replace(state["project"], str(uuid4()))
    assert (await client.get(cross, headers=headers)).status_code == 401
    missing = path.replace(state["execution"], str(uuid4()))
    assert (await client.get(missing, headers=headers)).status_code == 404
    revoked = await client.delete(
        f"/api/v1/projects/{state['project']}/service-tokens/{state['token']['id']}",
        headers=state["headers"],
    )
    assert revoked.status_code == 200
    assert (await client.get(path, headers=headers)).status_code == 401


async def test_control_pages_are_bounded_and_never_return_payload(
    tasking_context: TaskingTestContext,
) -> None:
    state = await _finished_run(tasking_context)
    async with tasking_context.session_maker() as session:
        session.add_all(
            [
                WorkflowControlRecord(
                    workflow_execution_id=UUID(state["execution"]),
                    node_id="loop",
                    kind="iteration",
                    ordinal=ordinal,
                    status="passed",
                    test_verdict="passed",
                    payload={"secret": "synthetic-private-control"},
                )
                for ordinal in range(2)
            ]
        )
        await session.commit()
    path = (
        f"/api/v1/ci/projects/{state['project']}/workflow-executions/"
        f"{state['execution']}/evidence/control-records"
    )
    headers = {"Authorization": f"Bearer {state['token']['token']}"}
    client = tasking_context.client
    first = await client.get(path, headers=headers, params={"node_id": "loop", "page_size": 1})
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 2 and first.json()["has_more"] is True
    assert first.json()["items"] == [{"ordinal": 0, "status": "passed", "test_verdict": "passed"}]
    second = await client.get(
        path, headers=headers, params={"node_id": "loop", "page_size": 1, "page": 2}
    )
    assert second.json()["items"][0]["ordinal"] == 1
    assert second.json()["has_more"] is False
    assert "synthetic-private-control" not in first.text + second.text
    invalid = await client.get(path, headers=headers, params={"node_id": "loop", "page_size": 101})
    assert invalid.status_code == 422


async def test_separate_project_viewer_can_read_existing_capture_but_cannot_execute_or_write(
    tasking_context: TaskingTestContext,
) -> None:
    state = await _finished_run(tasking_context)
    client = tasking_context.client
    root = f"/api/v1/projects/{state['project']}"
    project = (await client.get(root, headers=state["headers"])).json()
    organization = project["organization_id"]
    user = await client.post(
        "/api/v1/users",
        headers=state["headers"],
        json={
            "email": "independent-capture@example.com",
            "password": "initial-viewer-password-123!",
            "display_name": "只读合成响应观察者",
            "is_system_admin": False,
        },
    )
    assert user.status_code == 201, user.text
    user_id = user.json()["id"]
    assert (
        await client.put(
            f"/api/v1/organizations/{organization}/members/{user_id}",
            headers=state["headers"],
            json={"user_id": user_id, "role": "member"},
        )
    ).status_code == 200
    assert (
        await client.put(
            f"{root}/members/{user_id}",
            headers=state["headers"],
            json={"user_id": user_id, "role": "viewer"},
        )
    ).status_code == 200
    authenticated = await client.post(
        "/api/v1/auth/login",
        json={"email": user.json()["email"], "password": "initial-viewer-password-123!"},
    )
    assert authenticated.status_code == 200
    token = authenticated.json()["access_token"]
    if authenticated.json()["user"]["requires_password_change"]:
        changed = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "initial-viewer-password-123!",
                "new_password": "active-viewer-password-123!",
            },
        )
        assert changed.status_code == 204, changed.text
        authenticated = await client.post(
            "/api/v1/auth/login",
            json={"email": user.json()["email"], "password": "active-viewer-password-123!"},
        )
        assert authenticated.status_code == 200
        token = authenticated.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": organization}
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["id"] == user_id and me["is_system_admin"] is False
    permissions = await client.get(f"{root}/permissions", headers=headers)
    assert permissions.status_code == 200
    assert permissions.json()["effective_role"] == "viewer"
    captured = await client.get(f"{root}/workflow-executions/{state['execution']}", headers=headers)
    assert captured.status_code == 200, captured.text
    assert captured.json()["execution"]["id"] == state["execution"]
    api = next(item for item in captured.json()["nodes"] if item["node_type"] == "api")
    assert api["output"]["body"]["actual"] == 1
    assert (await client.get(f"{root}/environments", headers=headers)).status_code == 200
    assert (
        await client.post(
            f"{root}/environments",
            headers=headers,
            json={"name": "forbidden", "base_url": "https://example.invalid"},
        )
    ).status_code == 403
    assert (
        await client.post(f"{root}/test-plans/{state['plan']}/runs", headers=headers)
    ).status_code == 403
    ci = f"/api/v1/ci/projects/{state['project']}/workflow-executions/{state['execution']}/evidence"
    assert (await client.get(ci, headers=headers)).status_code == 401


async def test_nested_checkpoint_projection_keeps_exact_error_and_only_assertion_digests(
    tasking_context: TaskingTestContext,
) -> None:
    from datetime import UTC, datetime

    from app.models.durable_execution import ExecutionCheckpoint

    state = await _finished_run(tasking_context)
    nested_id = "__nested_request__:" + "a" * 64
    async with tasking_context.session_maker() as session:
        session.add(
            ExecutionCheckpoint(
                project_id=UUID(state["project"]),
                execution_id=UUID(state["execution"]),
                node_id=nested_id,
                node_type="assert",
                node_name="合成内部断言",
                phase="main",
                best_effort=False,
                attempt=1,
                input_hash="b" * 64,
                status="failed",
                output_digest="c" * 64,
                output={"Authorization": "synthetic-nested-secret"},
                result={
                    "assertions": [
                        {"name": "workflow_assertion", "passed": False, "expected": 2, "actual": 1}
                    ],
                    "error": {
                        "code": "WORKFLOW_ASSERTION_FAILED",
                        "message": "synthetic-nested-secret",
                    },
                    "observations": [{"headers": {"Cookie": "synthetic-nested-secret"}}],
                },
                extracted_variables={"password": "synthetic-nested-secret"},
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()
    response = await tasking_context.client.get(
        f"/api/v1/ci/projects/{state['project']}/workflow-executions/{state['execution']}/evidence",
        headers={"Authorization": f"Bearer {state['token']['token']}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["nested_node_total"] == 1 and data["nested_nodes_complete"] is True
    node = data["nested_nodes"][0]
    assert node["node_id"] == nested_id and node["status"] == "failed"
    assert node["error_code"] == "WORKFLOW_ASSERTION_FAILED"
    assert node["assertions"][0]["actual_digest"] == hashlib.sha256(b"1").hexdigest()
    assert "synthetic-nested-secret" not in response.text
    assert set(node) == {
        "node_id",
        "node_type",
        "phase",
        "status",
        "attempts",
        "error_code",
        "assertions",
        "assertions_complete",
    }
