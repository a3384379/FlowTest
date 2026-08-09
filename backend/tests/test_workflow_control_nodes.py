from typing import Any

import pytest
from pydantic import JsonValue

from app.engine.contracts import NodeStatus, WorkflowDefinition, WorkflowNode
from app.engine.control_nodes import execute_control_node
from app.engine.mappings import resolve_field_mappings
from app.engine.scheduler import ExecutionContext, WorkflowScheduler


class ControlExecutor:
    def __init__(self, api_outputs: dict[str, JsonValue]) -> None:
        self._api_outputs = api_outputs

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        if node.type.value == "api":
            return self._api_outputs[node.id]
        return await execute_control_node(node, context)


@pytest.mark.asyncio
async def test_extract_and_assert_nodes_record_explainable_results() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node("start", "start", {}),
                _node("api", "api", _api_config()),
                _node(
                    "extract",
                    "extract",
                    {
                        "source_node_id": "api",
                        "expression": "body.data.token",
                        "variable": "auth.token",
                    },
                ),
                _node(
                    "assert",
                    "assert",
                    {
                        "source_node_id": "api",
                        "expression": "status_code",
                        "operator": "equals",
                        "expected": 200,
                    },
                ),
                _node("end", "end", {}),
            ],
            "edges": [
                _edge("start", "api"),
                _edge("api", "extract"),
                _edge("extract", "assert"),
                _edge("assert", "end"),
            ],
        }
    )

    result = await WorkflowScheduler(
        ControlExecutor({"api": {"status_code": 200, "body": {"data": {"token": "issued-token"}}}})
    ).run(definition)

    assert result.status == "passed"
    assert result.context["resolved_variables"]["auth.token"] == "issued-token"
    assert result.context["variable_sources"]["auth.token"] == {
        "scope": "workflow",
        "node_id": "api",
        "path": "body.data.token",
    }
    assert result.records[3].output["passed"] is True


@pytest.mark.asyncio
async def test_failed_assertion_stops_the_workflow_with_actual_value() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node("start", "start", {}),
                _node("api", "api", _api_config()),
                _node(
                    "assert",
                    "assert",
                    {
                        "source_node_id": "api",
                        "expression": "status_code",
                        "operator": "equals",
                        "expected": 201,
                    },
                ),
                _node("end", "end", {}),
            ],
            "edges": [_edge("start", "api"), _edge("api", "assert"), _edge("assert", "end")],
        }
    )

    result = await WorkflowScheduler(ControlExecutor({"api": {"status_code": 200}})).run(definition)

    assert result.status == "failed"
    assert result.records[2].error_code == "WORKFLOW_ASSERTION_FAILED"
    assert result.records[2].output["actual"] == 200
    assert result.records[3].status is NodeStatus.CANCELLED


@pytest.mark.asyncio
async def test_condition_runs_only_the_selected_branch_and_joins() -> None:
    definition = _condition_workflow()

    result = await WorkflowScheduler(ControlExecutor({"api": {"body": {"enabled": True}}})).run(
        definition
    )
    by_id = {record.node_id: record.status for record in result.records}

    assert result.status == "passed"
    assert by_id["enabled"] is NodeStatus.PASSED
    assert by_id["disabled"] is NodeStatus.SKIPPED
    assert by_id["end"] is NodeStatus.PASSED
    assert result.context["node_outputs"]["condition"]["matched"] is True


def test_field_mapping_preserves_types_and_tracks_its_source() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node("start", "start", {}),
                _node("api", "api", _api_config()),
                _node("target", "api", _api_config()),
                _node("end", "end", {}),
            ],
            "edges": [
                _edge("start", "api"),
                {
                    **_edge("api", "target"),
                    "mappings": [
                        {
                            "source": {"node_id": "api", "path": "body.user.id"},
                            "target": {
                                "node_id": "target",
                                "location": "body",
                                "key": "owner.id",
                            },
                        }
                    ],
                },
                _edge("target", "end"),
            ],
        }
    )
    context = ExecutionContext()
    context.record_output("api", {"body": {"user": {"id": 42}}})

    resolved = resolve_field_mappings(definition.edges[1].mappings, context)

    assert resolved[0].value == 42
    assert resolved[0].source_node_id == "api"
    assert resolved[0].source_path == "body.user.id"


def test_variable_precedence_is_workflow_dataset_runtime() -> None:
    context = ExecutionContext(
        workflow_variables={"value": "workflow", "workflow_only": 1},
        dataset_variables={"value": "dataset"},
        runtime_variables={"value": "runtime"},
    )

    assert context.variable("value") == "runtime"
    assert context.variable("workflow_only") == 1
    assert context.snapshot()["variable_sources"]["value"]["scope"] == "runtime"


def _condition_workflow() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "settings": {"fail_fast": False, "concurrency": 20, "default_timeout_seconds": 30},
            "nodes": [
                _node("start", "start", {}),
                _node("api", "api", _api_config()),
                _node(
                    "condition",
                    "condition",
                    {
                        "source_node_id": "api",
                        "expression": "body.enabled",
                        "operator": "equals",
                        "expected": True,
                    },
                ),
                _node("enabled", "delay", {"seconds": 0}),
                _node("disabled", "delay", {"seconds": 0}),
                _node("end", "end", {}),
            ],
            "edges": [
                _edge("start", "api"),
                _edge("api", "condition"),
                {**_edge("condition", "enabled"), "condition": "true"},
                {**_edge("condition", "disabled"), "condition": "false"},
                _edge("enabled", "end"),
                _edge("disabled", "end"),
            ],
        }
    )


def _node(node_id: str, node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": node_id,
        "position": {"x": 0, "y": 0},
        "config": config,
    }


def _edge(source: str, target: str) -> dict[str, Any]:
    return {
        "id": f"{source}-{target}",
        "source": source,
        "target": target,
        "condition": None,
        "mappings": [],
    }


def _api_config() -> dict[str, Any]:
    return {"api_definition_id": "00000000-0000-0000-0000-000000000001"}
