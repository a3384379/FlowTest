"""Independent wire and compiler regressions found during the path-binding review."""

import httpx
import pytest
from test_s50_integration_plans import _planner_request, _selected_operation
from test_workflow_control_nodes import AllowOutbound
from test_workflow_path_bindings import _definition, _prepared

from app.domain.api_assets import BodyKind, HttpMethod
from app.domain.integration_plans import build_integration_plan, compile_integration_plan
from app.domain.network import OutboundNetworkPolicy
from app.domain.test_engineering import ContractParameter, ContractResponse, OperationContract
from app.engine.scheduler import ExecutionContext, WorkflowScheduler
from app.services.api_assets import PreparedRequest
from app.services.workflow_runtime import PreparedWorkflowRequest, WorkflowNodeExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["runtime", "dataset", "workflow"])
async def test_target_path_binding_uses_its_selected_source_over_same_named_variables(
    scope: str,
) -> None:
    definition = _definition()
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/source":
            return httpx.Response(200, json={"id": "selected-source-value"})
        seen.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    source = PreparedRequest(HttpMethod.GET, "https://example.test/source", (), None, ())
    target = _prepared("https://example.test/resources/{resource_id}")
    requests = {
        "source": PreparedWorkflowRequest(source, source, BodyKind.NONE, None),
        "target": PreparedWorkflowRequest(target, target, BodyKind.NONE, None),
    }
    context = ExecutionContext(**{f"{scope}_variables": {"resource_id": "unrelated-old-value"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        executor = WorkflowNodeExecutor(
            client, requests, definition, OutboundNetworkPolicy(), outbound_guard=AllowOutbound()
        )
        result = await WorkflowScheduler(executor).run(definition, context=context)
    assert result.status.value == "passed"
    assert seen == ["/resources/selected-source-value"]


def test_path_compilation_preserves_the_declared_capture_variable() -> None:
    source = _selected_operation(
        ref="resources.create",
        status=201,
        contract=OperationContract(
            operation="resources.create",
            method="POST",
            path="/resources",
            responses={
                "201": ContractResponse(
                    description="已创建",
                    schema={"type": "object", "properties": {"resource_id": {"type": "string"}}},
                )
            },
        ),
    )
    target = _selected_operation(
        ref="resources.read",
        status=200,
        contract=OperationContract(
            operation="resources.read",
            method="GET",
            path="/resources/{resource_id}",
            parameters=[
                ContractParameter(
                    name="resource_id", location="path", required=True, schema={"type": "string"}
                )
            ],
            responses={"200": ContractResponse(description="成功")},
        ),
    )
    plan = build_integration_plan(_planner_request([source, target]))
    binding = next(item for item in plan.bindings if item.target.location == "path")
    assert binding.capture_variable is not None and binding.capture_variable != binding.target.key
    compiled = compile_integration_plan(plan)
    assert compiled.importable, compiled.diagnostics
    extract = next(node for node in compiled.flow_spec.nodes if node.id == f"extract-{binding.id}")
    assert extract.config["variable"] == binding.capture_variable
