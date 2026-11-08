"""Observe path-bound output values on the actual HTTP request object."""

from uuid import uuid4

import httpx
import pytest
from test_workflow_control_nodes import AllowOutbound, _api_config, _edge, _node

from app.domain.api_assets import BodyKind, HttpMethod
from app.domain.network import OutboundNetworkPolicy
from app.domain.scopes import VariableScope
from app.engine.contracts import WorkflowDefinition
from app.engine.scheduler import NodeExecutionError, WorkflowScheduler
from app.engine.structured_control import control_placeholder
from app.services.api_assets import PreparedRequest, PreparedVariable
from app.services.workflow_runtime import (
    PreparedWorkflowRequest,
    WorkflowNodeExecutor,
    _apply_bound_path_templates,
)
from app.services.workflow_snapshots import _control_template_variables


def _definition() -> WorkflowDefinition:
    edge = _edge("extract", "target")
    edge["mappings"] = [
        {
            "source": {"node_id": "extract", "path": "value"},
            "target": {"node_id": "target", "location": "variable", "key": "resource_id"},
        }
    ]
    return WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node("start", "start", {}),
                _node("source", "api", _api_config()),
                _node(
                    "extract",
                    "extract",
                    {
                        "source_node_id": "source",
                        "expression": "body.id",
                        "variable": "resource_id",
                    },
                ),
                _node("target", "api", _api_config()),
                _node("end", "end", {}),
            ],
            "edges": [
                _edge("start", "source"),
                _edge("source", "extract"),
                edge,
                _edge("target", "end"),
            ],
        }
    )


def _prepared(url: str) -> PreparedRequest:
    return PreparedRequest(
        HttpMethod.GET,
        url,
        (),
        None,
        (
            PreparedVariable(
                "resource_id",
                control_placeholder("target", "resource_id"),
                VariableScope.RUNTIME,
                False,
            ),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path_kind", ["runtime_marker", "openapi_parameter"])
@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        ("resource-73", "resource-73"),
        ("../?/#", "..%2F%3F%2F%23"),
        ("..", "%2E%2E"),
        ("中文", "%E4%B8%AD%E6%96%87"),
        ("%2f", "%252f"),
    ],
)
async def test_extracted_path_value_reaches_wire_as_one_encoded_segment(
    value: str, encoded: str, path_kind: str
) -> None:
    definition = _definition()
    target_node = next(node for node in definition.nodes if node.id == "target")
    variables = _control_template_variables(
        definition, target_node, api_path="/resources/{resource_id}"
    )
    marker = variables["resource_id"]
    seen: list[httpx.URL] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/source":
            return httpx.Response(200, json={"id": value})
        seen.append(request.url)
        return httpx.Response(200, json={"ok": True})

    source = PreparedRequest(HttpMethod.GET, "https://example.test/source", (), None, ())
    parameter = marker if path_kind == "runtime_marker" else "{resource_id}"
    target = _prepared(f"https://example.test/resources/{parameter}?fixed=1")
    requests = {
        "source": PreparedWorkflowRequest(source, source, BodyKind.NONE, None),
        "target": PreparedWorkflowRequest(target, target, BodyKind.NONE, None),
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        executor = WorkflowNodeExecutor(
            client, requests, definition, OutboundNetworkPolicy(), outbound_guard=AllowOutbound()
        )
        result = await WorkflowScheduler(executor).run(definition)

    assert result.status.value == "passed"
    assert len(seen) == 1
    assert seen[0].host == "example.test"
    assert seen[0].raw_path == f"/resources/{encoded}?fixed=1".encode()


@pytest.mark.parametrize("api_path", [None, "/resources/fixed", "/resources/{other_id}"])
def test_non_path_variable_mappings_keep_existing_snapshot_behavior(api_path: str | None) -> None:
    definition = _definition()
    target = next(node for node in definition.nodes if node.id == "target")
    assert _control_template_variables(definition, target, api_path=api_path) == {}


@pytest.mark.parametrize("value", [None, {}, []])
def test_missing_or_structured_path_input_is_rejected_before_a_request(value: object) -> None:
    marker = control_placeholder("target", "resource_id")
    request = _prepared(f"https://example.test/resources/{marker}")
    inputs = {"resource_id": value} if isinstance(value, (dict, list)) else {}
    with pytest.raises(NodeExecutionError) as missing:
        _apply_bound_path_templates(request, "target", inputs)
    assert missing.value.code == "PATH_BINDING_INPUT_MISSING"


@pytest.mark.parametrize("location", ["authority", "query", "fragment", "missing-path"])
def test_bound_path_markers_cannot_change_authority_query_or_fragment(location: str) -> None:
    marker = control_placeholder("target", "resource_id")
    urls = {
        "authority": f"https://{marker}.test/resources/{marker}",
        "query": f"https://example.test/resources/{marker}?input={marker}",
        "fragment": f"https://example.test/resources/{marker}#{marker}",
        "missing-path": "https://example.test/resources/fixed",
    }
    inputs = {"resource_id": str(uuid4())}
    with pytest.raises(NodeExecutionError) as invalid:
        _apply_bound_path_templates(_prepared(urls[location]), "target", inputs)
    expected = (
        "PATH_BINDING_PARAMETER_MISSING"
        if location == "missing-path"
        else "PATH_BINDING_CONTEXT_INVALID"
    )
    assert invalid.value.code == expected
