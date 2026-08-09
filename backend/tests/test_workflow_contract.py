import pytest
from pydantic import ValidationError

from app.engine.contracts import WorkflowDefinition


def workflow_payload() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}},
            {"id": "api", "type": "api", "name": "登录", "position": {"x": 100, "y": 0}},
            {"id": "end", "type": "end", "name": "结束", "position": {"x": 200, "y": 0}},
        ],
        "edges": [
            {"id": "start-api", "source": "start", "target": "api"},
            {"id": "api-end", "source": "api", "target": "end"},
        ],
    }


def test_valid_workflow_contract() -> None:
    workflow = WorkflowDefinition.model_validate(workflow_payload())

    assert workflow.schema_version == "1.0"
    assert workflow.settings.concurrency == 20


def test_workflow_rejects_cycles() -> None:
    payload = workflow_payload()
    edges = payload["edges"]
    assert isinstance(edges, list)
    edges.append({"id": "end-api", "source": "end", "target": "api"})

    with pytest.raises(ValidationError, match="directed acyclic graph"):
        WorkflowDefinition.model_validate(payload)


def test_workflow_rejects_unknown_nodes() -> None:
    payload = workflow_payload()
    edges = payload["edges"]
    assert isinstance(edges, list)
    edges.append({"id": "unknown", "source": "api", "target": "missing"})

    with pytest.raises(ValidationError, match="unknown node"):
        WorkflowDefinition.model_validate(payload)
