from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import JsonValue

from app.core.errors import AppError
from app.domain.network import OutboundNetworkPolicy
from app.engine.contracts import (
    FieldMapping,
    NodeStatus,
    WorkflowDefinition,
    WorkflowNode,
    parse_node_config,
)
from app.engine.control_nodes import execute_control_node
from app.engine.mappings import MappingResolutionError, resolve_field_mappings
from app.engine.scheduler import ExecutionContext, NodeExecutionError, WorkflowScheduler
from app.services.workflow_runtime import PreparedSubflow, WorkflowNodeExecutor
from app.services.workflows import WorkflowService


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


def test_field_mapping_rejects_invalid_and_missing_sources() -> None:
    context = ExecutionContext()
    context.record_output("source", {"body": {"name": "FlowTest"}})

    with pytest.raises(MappingResolutionError, match="无效") as invalid:
        resolve_field_mappings([_mapping("[")], context)
    assert invalid.value.code == "INVALID_MAPPING_PATH"
    assert str(invalid.value) == invalid.value.message

    with pytest.raises(MappingResolutionError, match="未找到值") as missing:
        resolve_field_mappings([_mapping("body.missing")], context)
    assert missing.value.code == "MAPPING_SOURCE_MISSING"


@pytest.mark.parametrize(
    ("value", "template", "expected"),
    [
        (42, "{{value}}", 42),
        ("FlowTest", "name={{value}}", "name=FlowTest"),
        ([1, 2], "items={{value}}", "items=[1,2]"),
    ],
)
def test_field_mapping_template_transform_is_typed_and_deterministic(
    value: JsonValue,
    template: str,
    expected: JsonValue,
) -> None:
    context = ExecutionContext()
    context.record_output("source", {"value": value})

    resolved = resolve_field_mappings([_mapping("value", template=template)], context)

    assert resolved[0].value == expected


@pytest.mark.asyncio
async def test_control_node_handles_optional_extract_delay_dataset_and_boundaries() -> None:
    context = ExecutionContext(dataset_variables={"region": "cn"})
    context.record_output("source", {"body": {}})

    assert await execute_control_node(
        WorkflowNode.model_validate(_node("start", "start", {})), context
    ) == {"variables": {"region": "cn"}}
    extracted = await execute_control_node(
        WorkflowNode.model_validate(
            _node(
                "extract",
                "extract",
                {
                    "source_node_id": "source",
                    "expression": "body.optional",
                    "variable": "optional",
                    "required": False,
                },
            )
        ),
        context,
    )
    assert extracted["value"] is None
    assert context.variable("optional") is None
    assert await execute_control_node(
        WorkflowNode.model_validate(_node("delay", "delay", {"seconds": 0})), context
    ) == {"seconds": 0.0}
    assert await execute_control_node(
        WorkflowNode.model_validate(
            _node(
                "dataset",
                "dataset",
                {
                    "artifact_id": "00000000-0000-0000-0000-000000000001",
                    "format": "json",
                },
            )
        ),
        context,
    ) == {"row": {"region": "cn"}}


@pytest.mark.asyncio
async def test_control_node_reports_invalid_expression_and_unsupported_executor() -> None:
    context = ExecutionContext()
    context.record_output("source", {})
    invalid = WorkflowNode.model_validate(
        _node(
            "condition",
            "condition",
            {
                "source_node_id": "source",
                "expression": "[",
                "operator": "equals",
                "expected": True,
            },
        )
    )
    with pytest.raises(NodeExecutionError, match="JMESPath") as expression_error:
        await execute_control_node(invalid, context)
    assert expression_error.value.code == "INVALID_JMESPATH"

    api_node = WorkflowNode.model_validate(_node("api", "api", _api_config()))
    with pytest.raises(NodeExecutionError, match="不支持") as unsupported:
        await execute_control_node(api_node, context)
    assert unsupported.value.code == "UNSUPPORTED_NODE_TYPE"


def test_workflow_publish_validation_rejects_downstream_dynamic_expected_source() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node("start", "start", {}),
                _node("source", "api", _api_config()),
                _node(
                    "assert",
                    "assert",
                    {
                        "source_node_id": "source",
                        "expression": "body.id",
                        "expected_source_node_id": "later",
                        "expected_expression": "body.id",
                    },
                ),
                _node("later", "api", _api_config()),
                _node("end", "end", {}),
            ],
            "edges": [
                _edge("start", "source"),
                _edge("source", "assert"),
                _edge("assert", "later"),
                _edge("later", "end"),
            ],
        }
    )
    assertion = next(node for node in definition.nodes if node.id == "assert")
    service = WorkflowService.__new__(WorkflowService)

    with pytest.raises(AppError) as error_info:
        service._validate_control_node(
            definition,
            assertion,
            parse_node_config(assertion),
        )

    assert error_info.value.code == "INVALID_NODE_SOURCE"


@pytest.mark.asyncio
async def test_subflow_inherits_variables_from_an_immutable_prepared_version() -> None:
    workflow_id = UUID("00000000-0000-0000-0000-000000000101")
    nested = _nested_workflow()
    node = WorkflowNode.model_validate(
        _node(
            "nested",
            "subflow",
            {"workflow_id": str(workflow_id), "workflow_version": 2},
        )
    )
    prepared = PreparedSubflow(
        workflow_id=workflow_id,
        workflow_version=2,
        fingerprint="f" * 64,
        definition=nested,
        requests={},
        subflows={},
        snapshot={"workflow": {"id": str(workflow_id), "version": 2}},
    )
    async with httpx.AsyncClient() as client:
        executor = WorkflowNodeExecutor(
            client,
            {},
            _wrapper_workflow(node),
            OutboundNetworkPolicy(),
            subflows={node.id: prepared},
        )
        output = await executor.execute(
            node,
            ExecutionContext(runtime_variables={"tenant": "flowtest"}),
        )

    assert output["status"] == "passed"
    assert output["workflow_version"] == 2
    assert output["nodes"][0]["output"] == {"variables": {"tenant": "flowtest"}}


@pytest.mark.asyncio
async def test_for_each_runs_bounded_subflows_and_exposes_item_variables() -> None:
    workflow_id = UUID("00000000-0000-0000-0000-000000000102")
    node = WorkflowNode.model_validate(
        _node(
            "loop",
            "for_each",
            {
                "workflow_id": str(workflow_id),
                "workflow_version": 1,
                "source_node_id": "source",
                "expression": "body.items",
                "item_variable": "current",
                "index_variable": "position",
                "concurrency": 2,
                "fail_fast": False,
            },
        )
    )
    prepared = PreparedSubflow(
        workflow_id=workflow_id,
        workflow_version=1,
        fingerprint="a" * 64,
        definition=_nested_workflow(),
        requests={},
        subflows={},
        snapshot={},
    )
    context = ExecutionContext(runtime_variables={"tenant": "flowtest"})
    context.record_output("source", {"body": {"items": ["a", "b", "c"]}})
    async with httpx.AsyncClient() as client:
        executor = WorkflowNodeExecutor(
            client,
            {},
            _wrapper_workflow(node),
            OutboundNetworkPolicy(),
            subflows={node.id: prepared},
        )
        output = await executor.execute(node, context)

    assert output["total"] == 3
    assert output["completed"] == 3
    assert [item["index"] for item in output["items"]] == [0, 1, 2]
    variables = output["items"][1]["result"]["nodes"][0]["output"]["variables"]
    assert variables == {"tenant": "flowtest", "current": "b", "position": 1}


@pytest.mark.asyncio
async def test_for_each_rejects_non_arrays_and_more_than_one_thousand_items() -> None:
    workflow_id = "00000000-0000-0000-0000-000000000103"
    node = WorkflowNode.model_validate(
        _node(
            "loop",
            "for_each",
            {
                "workflow_id": workflow_id,
                "workflow_version": 1,
                "source_node_id": "source",
                "expression": "items",
            },
        )
    )
    context = ExecutionContext()
    async with httpx.AsyncClient() as client:
        executor = WorkflowNodeExecutor(
            client,
            {},
            _wrapper_workflow(node),
            OutboundNetworkPolicy(),
        )
        context.record_output("source", {"items": "not-an-array"})
        with pytest.raises(NodeExecutionError) as wrong_type:
            await executor.execute(node, context)
        assert wrong_type.value.code == "FOR_EACH_SOURCE_NOT_ARRAY"

        context.record_output("source", {"items": list(range(1001))})
        with pytest.raises(NodeExecutionError) as over_limit:
            await executor.execute(node, context)
        assert over_limit.value.code == "FOR_EACH_LIMIT_EXCEEDED"


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


def _nested_workflow() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "2.0",
            "nodes": [_node("start", "start", {}), _node("end", "end", {})],
            "edges": [_edge("start", "end")],
        }
    )


def _wrapper_workflow(node: WorkflowNode) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "2.0",
            "nodes": [
                _node("start", "start", {}),
                node.model_dump(mode="json"),
                _node("end", "end", {}),
            ],
            "edges": [_edge("start", node.id), _edge(node.id, "end")],
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


def _mapping(path: str, *, template: str | None = None) -> FieldMapping:
    transform: dict[str, str] = {}
    if template is not None:
        transform = {"kind": "template", "template": template}
    return FieldMapping.model_validate(
        {
            "source": {"node_id": "source", "path": path},
            "transform": transform,
            "target": {"node_id": "target", "location": "body", "key": "value"},
        }
    )
