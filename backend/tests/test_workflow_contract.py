from typing import Any

import pytest
from pydantic import ValidationError

from app.engine.contracts import (
    ConditionNodeConfig,
    DatasetNodeConfig,
    ExtractNodeConfig,
    MappingTargetLocation,
    NodeType,
    WorkflowDefinition,
    WorkflowNode,
    parse_node_config,
)


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


def test_condition_requires_explicit_true_and_false_branches() -> None:
    payload = workflow_payload()
    nodes = payload["nodes"]
    edges = payload["edges"]
    assert isinstance(nodes, list)
    assert isinstance(edges, list)
    nodes.insert(
        2,
        {
            "id": "condition",
            "type": "condition",
            "name": "是否成功",
            "position": {"x": 150, "y": 0},
            "config": {
                "source_node_id": "api",
                "expression": "body.ok",
                "operator": "equals",
                "expected": True,
            },
        },
    )
    nodes.append(
        {"id": "fallback", "type": "end", "name": "失败结束", "position": {"x": 220, "y": 100}}
    )
    edges[:] = [
        {"id": "start-api", "source": "start", "target": "api"},
        {"id": "api-condition", "source": "api", "target": "condition"},
        {"id": "condition-end", "source": "condition", "target": "end", "condition": "true"},
    ]

    with pytest.raises(ValidationError, match="exactly one true and one false"):
        WorkflowDefinition.model_validate(payload)

    edges.append(
        {
            "id": "condition-fallback",
            "source": "condition",
            "target": "fallback",
            "condition": "false",
        }
    )
    workflow = WorkflowDefinition.model_validate(payload)

    assert workflow.edges[-1].condition == "false"


def test_mapping_endpoints_must_match_its_edge() -> None:
    payload = workflow_payload()
    edges = payload["edges"]
    assert isinstance(edges, list)
    edges[1] = {
        "id": "api-end",
        "source": "api",
        "target": "end",
        "mappings": [
            {
                "source": {"node_id": "start", "path": "body.id"},
                "target": {"node_id": "end", "location": "body", "key": "user.id"},
            }
        ],
    }

    with pytest.raises(ValidationError, match="mapping endpoints"):
        WorkflowDefinition.model_validate(payload)


def test_node_configs_are_strictly_typed() -> None:
    extract = parse_node_config(
        _node(
            NodeType.EXTRACT,
            {
                "source_node_id": "api",
                "expression": "body.data.token",
                "variable": "auth.token",
            },
        )
    )
    dataset = parse_node_config(
        _node(
            NodeType.DATASET,
            {
                "artifact_id": "00000000-0000-0000-0000-000000000001",
                "format": "csv",
            },
        )
    )
    condition = ConditionNodeConfig.model_validate(
        {
            "source_node_id": "api",
            "expression": "status_code",
            "operator": "equals",
            "expected": 200,
        }
    )

    assert isinstance(extract, ExtractNodeConfig)
    assert isinstance(dataset, DatasetNodeConfig)
    assert condition.expected == 200
    assert MappingTargetLocation.BODY == "body"


def _node(node_type: NodeType, config: dict[str, Any]) -> WorkflowNode:
    return WorkflowNode(
        id=f"{node_type.value}-node",
        type=node_type,
        name="测试节点",
        position={"x": 0, "y": 0},
        config=config,
    )
