"""Restricted dependency projection cannot export foreign or drifting sources."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from test_ci_execution_evidence import _finished_run
from test_tasking_api import TaskingTestContext, _create_published_workflow
from test_tasking_api import tasking_context as tasking_context

from app.models.workflows import WorkflowExecution


@pytest.mark.parametrize("tamper", ["foreign_project", "version", "fingerprint"])
async def test_subflow_projection_rejects_foreign_or_changed_source_without_payload_export(
    tasking_context: TaskingTestContext, tamper: str
) -> None:
    state = await _finished_run(tasking_context)
    _project, _environment, foreign = await _create_published_workflow(
        tasking_context.client, state["headers"]
    )
    async with tasking_context.session_maker() as session:
        execution = await session.get(WorkflowExecution, UUID(state["execution"]))
        snapshot = deepcopy(execution.snapshot)
        workflow = deepcopy(snapshot["workflow"])
        if tamper == "foreign_project":
            workflow["id"] = foreign
        elif tamper == "version":
            workflow["version"] += 1
        else:
            workflow["fingerprint"] = "0" * 64
        snapshot["subflows"] = {
            "slot": {
                "workflow": workflow,
                "apis": {},
                "subflows": {},
                "request": {"Authorization": "synthetic-private-subflow-header"},
                "body": "synthetic-private-subflow-response",
                "context": "synthetic-private-subflow-context",
            }
        }
        execution.snapshot = snapshot
        await session.commit()
    response = await tasking_context.client.get(
        f"/api/v1/ci/projects/{state['project']}/workflow-executions/{state['execution']}/evidence",
        headers={"Authorization": f"Bearer {state['token']['token']}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["subflows"] == []
    assert response.json()["subflows_complete"] is False
    for sentinel in (
        foreign,
        "synthetic-private-subflow-header",
        "synthetic-private-subflow-response",
        "synthetic-private-subflow-context",
    ):
        assert sentinel not in response.text
    denied = await tasking_context.client.get(
        f"/api/v1/ci/projects/{uuid4()}/workflow-executions/{state['execution']}/evidence",
        headers={"Authorization": f"Bearer {state['token']['token']}"},
    )
    assert denied.status_code == 401 and denied.json()["error"]["trace_id"]
