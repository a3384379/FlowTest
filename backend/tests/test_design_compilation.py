from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_mcp_read import mcp_context as mcp_context

from app.core.errors import AppError
from app.domain.flow_spec_v2 import flow_spec_v2_to_workflow_definition
from app.domain.integration_plans import IntegrationPlan, compile_integration_plan
from app.domain.test_design import OracleSpec, fingerprint_design
from app.domain.test_design_compilation import (
    CompilationContextBinding,
    CompileTestDesignRequest,
    FrozenGenerationOrigin,
    aggregate_readiness,
    compile_frozen_design,
    value_fingerprint,
)
from app.domain.test_engineering import (
    GenerationPolicy,
    OperationContract,
    fingerprint_contract,
)
from app.domain.test_engineering import (
    TestEngineeringEngine as DesignEngine,
)
from app.main import app
from app.mcp.client import MCPGatewayError, MCPReadGatewayClient
from app.mcp.server import _resolved_proposal_spec, create_mcp_server
from app.models.access import User
from app.models.ai import AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion
from app.models.workflows import Workflow, WorkflowExecution
from app.services.integration_plans import IntegrationPlanAssetService, OperationPlanSelection
from app.services.service_accounts import ServiceAccountService
from app.services.test_engineering import generator_build_identity


@pytest.fixture
def frozen_request() -> tuple[CompileTestDesignRequest, OperationContract]:
    contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "request": {
                "type": "object",
                "required": ["count"],
                "properties": {"count": {"type": "integer", "minimum": 1}},
            },
            "responses": {
                "201": {"description": "已创建", "schema": {"type": "object"}},
                "422": {"description": "输入无效"},
            },
        }
    )
    policy = GenerationPolicy(max_scenarios=20, include_auth=False)
    design = DesignEngine().generate(contract=contract, policy=policy)
    request = CompileTestDesignRequest(
        project_id=uuid4(),
        environment_id=uuid4(),
        design=design,
        design_fingerprint=fingerprint_design(design),
        origin=FrozenGenerationOrigin(
            api_definition_id=uuid4(),
            api_version=3,
            contract_fingerprint=fingerprint_contract(contract),
            generation_policy=policy,
            generator_build=generator_build_identity(),
        ),
        scenario_ids=[next(s.id for s in design.scenarios if s.kind == "happy_path")],
        context_binding=CompilationContextBinding(
            context_id=uuid4(), context_revision_id=uuid4(), context_fingerprint="a" * 64
        ),
    )
    return request, contract


def test_compiler_maps_every_oracle_and_pins_versions_without_persistence(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract],
) -> None:
    request, contract = frozen_request
    scenario_id = request.scenario_ids[0]
    expressions = [
        OracleSpec(
            id=f"business_{index}",
            kind="expression",
            expression=f"body.value{index}",
            expected=value,
            confidence=1,
            applies_to=[scenario_id],
        )
        for index, value in enumerate([0, False, "", None])
    ]
    request = request.model_copy(
        update={
            "design": request.design.model_copy(
                update={"oracles": [*request.design.oracles, *expressions]}
            )
        }
    )
    result = compile_frozen_design(request, contract)
    assert result.readiness == "ready", result.diagnostics
    assert result.persisted is False and result.execution_status == "not_run"
    scenario = result.scenarios[0]
    payload = scenario.executable_payload
    assert payload is not None and scenario.case_template is not None
    assert scenario.case_template.workflow_slot == f"scenario:{scenario_id}"
    assert not hasattr(scenario.case_template, "workflow_id")
    assert set(binding.oracle_id for binding in scenario.oracle_bindings) == {
        oracle.id for oracle in request.design.oracles if scenario_id in oracle.applies_to
    }
    assert list(payload.operation_version_mappings.values()) == [3]
    assert payload.spec.operations[0].source_version == 3
    assert payload.spec.run_policy.request_budget == 1
    assert payload.spec.run_policy.max_runtime_seconds == 300
    assert [
        node.config["expected"]
        for node in payload.native_definition.nodes
        if node.id.startswith("assert_expression_")
    ] == [0, False, "", None]
    assert result.model_dump(mode="json") == compile_frozen_design(request, contract).model_dump(
        mode="json"
    )


def test_compiler_preserves_negative_request_and_status(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract],
) -> None:
    request, contract = frozen_request
    negative = next(item for item in request.design.scenarios if item.kind == "required_omitted")
    request = request.model_copy(update={"scenario_ids": [negative.id]})
    result = compile_frozen_design(request, contract)
    assert result.readiness == "ready", result.diagnostics
    payload = result.scenarios[0].executable_payload
    assert payload is not None
    config = next(node.config for node in payload.native_definition.nodes if node.id == "request")
    assert config["expected_statuses"] == [422]
    assert "count" not in config["request_overrides"]["body"]["value"]


@pytest.mark.parametrize("variant", [None, "default", "selected-endpoint"])
def test_compiler_native_payload_exactly_matches_the_proposal_import_definition(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract], variant: str | None
) -> None:
    request, contract = frozen_request
    request = request.model_copy(update={"endpoint_variant": variant})
    result = compile_frozen_design(request, contract)
    assert result.readiness == "ready", result.diagnostics
    payload = result.scenarios[0].executable_payload
    assert payload is not None

    proposed = flow_spec_v2_to_workflow_definition(
        payload.spec,
        operation_mappings=payload.operation_mappings,
        operation_versions=payload.operation_version_mappings,
    )

    assert payload.native_definition.model_dump(mode="json") == proposed.model_dump(mode="json")
    assert result.scenarios[0].expected_raw_outcome.status == "passed"


@pytest.mark.parametrize(
    "change, readiness, code",
    [
        ({"scenario_ids": ["missing"]}, "blocked", "SCENARIO_INVALID"),
        ({"context_binding": None}, "needs_input", "CONTEXT_REQUIRED"),
        ({"route_preference": "quick"}, "unsupported", "ROUTE_UNSUPPORTED"),
        ({"auth_binding": {"kind": "disabled"}}, "blocked", "AUTH_BINDING_MISMATCH"),
        (
            {
                "fixture_bindings": [
                    {"field_path": "body.count", "fixture_ref": "fixture://unresolved"}
                ]
            },
            "unsupported",
            "BINDING_UNSUPPORTED",
        ),
        ({"budget": {"max_nodes": 1}}, "blocked", "BUDGET_EXCEEDED"),
    ],
)
def test_compiler_cannot_hide_missing_or_unsupported_selected_scenarios(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract],
    change: dict[str, Any],
    readiness: str,
    code: str,
) -> None:
    request, contract = frozen_request
    request = CompileTestDesignRequest.model_validate({**request.model_dump(mode="json"), **change})
    result = compile_frozen_design(request, contract)
    assert result.readiness == readiness
    assert [item.scenario_id for item in result.scenarios] == request.scenario_ids
    assert any(item.code == f"DESIGN_COMPILATION_{code}" for item in result.diagnostics)


def test_compiler_blocks_null_omission_and_unreviewed_oracles(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract],
) -> None:
    request, contract = frozen_request
    selected = next(item for item in request.design.scenarios if item.id == request.scenario_ids[0])
    null_body = selected.model_copy(
        update={"request": selected.request.model_copy(update={"body": None})}
    )
    request = request.model_copy(
        update={"design": request.design.model_copy(update={"scenarios": [null_body]})}
    )
    assert compile_frozen_design(request, contract).readiness == "unsupported"
    reviewed = null_body.model_copy(update={"requires_review": True})
    request = request.model_copy(
        update={"design": request.design.model_copy(update={"scenarios": [reviewed]})}
    )
    assert compile_frozen_design(request, contract).readiness == "needs_review"
    assert aggregate_readiness(["ready", "needs_input", "unsupported"]) == "unsupported"
    assert aggregate_readiness([]) == "blocked"


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": True},
        {"scenario_ids": []},
        {"budget": {"max_nodes": 501}},
        {"budget": {"max_nodes": True}},
    ],
)
def test_compile_schema_is_strict_and_bounded(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract], change: dict[str, Any]
) -> None:
    request, _ = frozen_request
    with pytest.raises(ValidationError):
        CompileTestDesignRequest.model_validate({**request.model_dump(mode="json"), **change})


async def _prepare_api(context: dict[str, Any]) -> None:
    async with context["sessions"]() as session:
        version = await session.scalar(
            select(APIVersion).where(
                APIVersion.api_definition_id == context["definition_id"], APIVersion.version == 1
            )
        )
        contract = OperationContract(
            operation="payments.create",
            method="POST",
            path="/payments",
            responses={"201": {"description": "已创建"}, "422": {"description": "无效输入"}},
        )
        version.canonical_contract = contract.model_dump(mode="json", by_alias=True)
        version.contract_fingerprint = fingerprint_contract(contract)
        version.contract_completeness = "complete"
        version.service_id = None
        version.path = contract.path
        version.method = contract.method
        version.body_kind = "none"
        version.body = None
        version.headers = {}
        version.query_parameters = []
        version.auth_kind = "none"
        version.auth_config = {}
        await session.commit()


async def _issue(context: dict[str, Any], scopes: list[str]) -> str:
    async with context["sessions"]() as session:
        actor = await session.scalar(select(User).where(User.email == "mcp-admin@example.com"))
        issued = await ServiceAccountService(session).create(
            actor=actor,
            organization_id=context["organization_id"],
            name="Compile tester",
            account_key=f"compile-{uuid4().hex[:10]}",
            scopes=scopes,
            expires_at=None,
            metadata={"purpose": "frozen compile test"},
        )
        await session.commit()
        return issued.token


async def _compile_input(context: dict[str, Any]) -> dict[str, Any]:
    await _prepare_api(context)
    generated = await context["client"].post(
        f"/api/v1/mcp/read/projects/{context['project_id']}/test-design/generate",
        headers={"Authorization": f"Bearer {context['token']}"},
        json={"api_definition_id": str(context["definition_id"]), "api_version": 1},
    )
    assert generated.status_code == 200, generated.text
    data = generated.json()["data"]
    return {
        "project_id": str(context["project_id"]),
        "environment_id": str(context["environment_id"]),
        "design": data["design"],
        "design_fingerprint": data["fingerprint"],
        "origin": data["origin"],
        "scenario_ids": [data["design"]["scenarios"][0]["id"]],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scopes, status",
    [
        ([], 403),
        (["mcp:read"], 403),
        (["mcp:flow:propose"], 403),
        (["mcp:read", "mcp:flow:propose"], 200),
    ],
)
async def test_compilation_requires_both_scopes_even_for_admin_creator(
    mcp_context: dict[str, Any], scopes: list[str], status: int
) -> None:
    payload = await _compile_input(mcp_context)
    token = await _issue(mcp_context, scopes)
    response = await mcp_context["client"].post(
        "/api/v1/mcp/flow/designs/compile",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == status, response.text
    if status == 403:
        assert response.json()["error"]["code"] == "MCP_SCOPE_REQUIRED"
        assert response.json()["error"]["trace_id"]


@pytest.mark.asyncio
async def test_compile_route_has_no_writes_and_rejects_source_drift(
    mcp_context: dict[str, Any],
) -> None:
    payload = await _compile_input(mcp_context)
    token = await _issue(mcp_context, ["mcp:read", "mcp:flow:propose"])
    headers = {"Authorization": f"Bearer {token}"}
    async with mcp_context["sessions"]() as session:
        before = [
            await session.scalar(select(func.count()).select_from(model))
            for model in [Workflow, AIChangeSet, WorkflowExecution]
        ]
    endpoint = "/api/v1/mcp/flow/designs/compile"
    response = await mcp_context["client"].post(endpoint, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["persisted"] is False
    assert response.json()["readiness"] == "needs_input"
    altered = json.loads(json.dumps(payload))
    altered["design"]["scenarios"][0]["title"] = "被修改的设计"
    stale = await mcp_context["client"].post(endpoint, headers=headers, json=altered)
    assert (
        stale.status_code == 409
        and stale.json()["error"]["code"] == "DESIGN_COMPILATION_SOURCE_MISMATCH"
    )
    foreign = await mcp_context["client"].post(
        endpoint,
        headers=headers,
        json={**payload, "project_id": str(mcp_context["other_project_id"])},
    )
    assert foreign.status_code == 404
    missing_version = await mcp_context["client"].post(
        endpoint,
        headers=headers,
        json={**payload, "origin": {**payload["origin"], "api_version": 99}},
    )
    assert (
        missing_version.status_code == 404
        and missing_version.json()["error"]["code"] == "API_VERSION_NOT_FOUND"
    )
    async with mcp_context["sessions"]() as session:
        after = [
            await session.scalar(select(func.count()).select_from(model))
            for model in [Workflow, AIChangeSet, WorkflowExecution]
        ]
    assert before == after


@pytest.mark.asyncio
async def test_explicit_generation_version_and_context_are_fixed(
    mcp_context: dict[str, Any],
) -> None:
    payload = await _compile_input(mcp_context)
    token = await _issue(mcp_context, ["mcp:read", "mcp:flow:propose", "mcp:evidence:write"])
    async with mcp_context["sessions"]() as session:
        actor = await session.scalar(select(User).where(User.email == "mcp-admin@example.com"))
        definition = await session.get(APIDefinition, mcp_context["definition_id"])
        definition.current_version = 2
        session.add(
            APIVersion(
                api_definition_id=definition.id,
                version=2,
                method="GET",
                path="/different",
                query_parameters=[],
                headers={},
                variables={},
                body_kind="none",
                body=None,
                auth_kind="none",
                auth_config={},
                extraction_rules=[],
                assertions=[],
                created_by_id=actor.id,
            )
        )
        await session.commit()
    begun = await mcp_context["client"].post(
        "/api/v1/mcp/evidence/contexts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "project_id": payload["project_id"],
            "name": "编译上下文",
            "objective": "冻结版本",
            "target_environment_id": payload["environment_id"],
            "required_evidence": ["contract"],
            "contract_revisions": [
                {
                    "source_ref": f"api-definition://{payload['origin']['api_definition_id']}/version/1",
                    "revision": payload["origin"]["contract_fingerprint"],
                }
            ],
        },
    )
    assert begun.status_code == 201, begun.text
    context = begun.json()
    payload["context_binding"] = {
        "context_id": context["id"],
        "context_revision_id": context["revision"]["id"],
        "context_fingerprint": context["revision"]["fingerprint"],
    }
    response = await mcp_context["client"].post(
        "/api/v1/mcp/flow/designs/compile",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 200, response.text
    assert response.json()["readiness"] == "ready", response.text
    assert response.json()["resolved_sources"]["api_version"] == 1
    executable = response.json()["scenarios"][0]["executable_payload"]
    async with MCPReadGatewayClient(
        base_url="http://test",
        token=token,
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
    ) as gateway:
        proposed = await create_mcp_server(client=gateway).call_tool(
            "flowtest.propose_flow_draft",
            {
                "project_id": payload["project_id"],
                "context_id": payload["context_binding"]["context_id"],
                "context_revision_id": payload["context_binding"]["context_revision_id"],
                "spec": executable["spec"],
                "operation_mappings": executable["operation_mappings"],
                "operation_version_mappings": executable["operation_version_mappings"],
                "idempotency_key": "frozen-design-standalone-spec",
                "dry_run": True,
            },
        )
    assert proposed.structured_content.get("status") == "preview", proposed.structured_content
    explicit = await mcp_context["client"].post(
        f"/api/v1/mcp/read/projects/{mcp_context['project_id']}/test-design/generate",
        headers={"Authorization": f"Bearer {mcp_context['token']}"},
        json={"api_definition_id": str(mcp_context["definition_id"]), "api_version": 1},
    )
    assert explicit.json()["data"]["fingerprint"] == payload["design_fingerprint"]
    assert explicit.json()["data"]["origin"]["api_version"] == 1
    payload["context_binding"]["context_fingerprint"] = "c" * 64
    stale = await mcp_context["client"].post(
        "/api/v1/mcp/flow/designs/compile",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "TEST_CONTEXT_REVISION_STALE"


@pytest.mark.asyncio
async def test_sdk_compile_contract_and_version_forwarding(
    frozen_request: tuple[CompileTestDesignRequest, OperationContract],
) -> None:
    request, contract = frozen_request
    expected = compile_frozen_design(request, contract)
    calls: list[httpx.Request] = []

    def handler(call: httpx.Request) -> httpx.Response:
        calls.append(call)
        if call.url.path.endswith("test-design/generate"):
            return httpx.Response(
                200, json={"data": {}, "trace_id": "version-forwarded", "confidence": 1.0}
            )
        return httpx.Response(200, json=expected.model_dump(mode="json"))

    async with MCPReadGatewayClient(
        base_url="http://gateway", token="ftsa_test", transport=httpx.MockTransport(handler)
    ) as gateway:
        server = create_mcp_server(client=gateway)
        tool = next(
            tool
            for tool in await server.list_tools()
            if tool.name == "flowtest.compile_test_design"
        )
        assert tool.annotations.read_only_hint is True
        assert "flowtest-design-compilation-v1" in json.dumps(tool.output_schema)
        result = await server.call_tool(
            "flowtest.compile_test_design", {"request": request.model_dump(mode="json")}
        )
    assert result.is_error is False
    assert result.structured_content["compilation_fingerprint"] == expected.compilation_fingerprint
    assert calls[0].url.path == "/api/v1/mcp/flow/designs/compile"
    assert json.loads(calls[0].content)["origin"]["api_version"] == 3
    async with MCPReadGatewayClient(
        base_url="http://gateway", token="ftsa_test", transport=httpx.MockTransport(handler)
    ) as gateway:
        server = create_mcp_server(client=gateway)
        await server.call_tool(
            "flowtest.generate_test_design",
            {
                "project_id": str(request.project_id),
                "api_definition_id": str(request.origin.api_definition_id),
                "api_version": 3,
            },
        )
    assert json.loads(calls[-1].content)["api_version"] == 3


@pytest.mark.asyncio
async def test_actual_mcp_catalog_matches_frozen_schema_fingerprints() -> None:
    expected = json.loads(
        (Path(__file__).parent / "fixtures/v6_golden/mcp-schema-fingerprints.json").read_text()
    )
    async with MCPReadGatewayClient(base_url="http://gateway") as gateway:
        tools = await create_mcp_server(client=gateway).list_tools()
    schemas = {
        tool.name: {
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "annotations": tool.annotations.model_dump(mode="json") if tool.annotations else None,
        }
        for tool in tools
    }
    assert {name: value_fingerprint(schema) for name, schema in schemas.items()} == expected[
        "tools"
    ]
    assert value_fingerprint(schemas) == expected["catalog_fingerprint"]


@pytest.mark.asyncio
async def test_integration_plan_selection_honors_explicit_version_and_contract(
    mcp_context: dict[str, Any],
) -> None:
    payload = await _compile_input(mcp_context)
    async with mcp_context["sessions"]() as session:
        definition = await session.get(APIDefinition, mcp_context["definition_id"])
        definition.current_version = 2
        await session.commit()
        service = IntegrationPlanAssetService(session)
        selection = OperationPlanSelection(
            definition_id=definition.id,
            api_version=1,
            contract_fingerprint=payload["origin"]["contract_fingerprint"],
        )
        operation = await service._selected_operation(
            project_id=definition.project_id, selection=selection
        )
        assert operation.source_version == 1
        with pytest.raises(AppError) as error:
            await service._selected_operation(
                project_id=definition.project_id,
                selection=OperationPlanSelection(
                    definition_id=definition.id, api_version=1, contract_fingerprint="f" * 64
                ),
            )
        assert error.value.code == "DESIGN_COMPILATION_SOURCE_MISMATCH"


@pytest.mark.asyncio
async def test_rest_generation_exposes_exact_version_origin_and_validates_version_type(
    mcp_context: dict[str, Any],
) -> None:
    await _prepare_api(mcp_context)
    headers = {
        "Authorization": f"Bearer {mcp_context['human_token']}",
        "X-Organization-Id": str(mcp_context["organization_id"]),
    }
    path = f"/api/v1/projects/{mcp_context['project_id']}/test-engineering/generate"
    response = await mcp_context["client"].post(
        path,
        headers=headers,
        json={"api_definition_id": str(mcp_context["definition_id"]), "api_version": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["origin"]["api_version"] == 1
    assert (
        response.json()["origin"]["contract_fingerprint"] == response.json()["contract_fingerprint"]
    )
    invalid = await mcp_context["client"].post(
        path,
        headers=headers,
        json={"api_definition_id": str(mcp_context["definition_id"]), "api_version": True},
    )
    assert invalid.status_code == 422


def test_proposal_spec_handoff_preserves_plan_contract_and_rejects_conflicts() -> None:
    plan = IntegrationPlan.model_validate_json(
        (
            Path(__file__).parent / "fixtures/v6_golden/login-create-query.integration-plan-v1.json"
        ).read_text()
    )
    compilation = compile_integration_plan(plan)
    spec = compilation.flow_spec
    assert spec is not None
    assert _resolved_proposal_spec(plan, compilation, None) == spec
    assert _resolved_proposal_spec(None, None, spec) == spec
    assert _resolved_proposal_spec(plan, compilation, spec) == spec
    for inputs, code in [
        ((plan, None, spec), "INTEGRATION_PLAN_COMPILATION_REQUIRED"),
        ((None, compilation, spec), "INTEGRATION_PLAN_COMPILATION_REQUIRED"),
        ((None, None, None), "FLOWSPEC_REQUIRED"),
        (
            (plan, compilation.model_copy(update={"flow_spec": None}), None),
            "INTEGRATION_PLAN_NOT_IMPORTABLE",
        ),
        (
            (plan, compilation, spec.model_copy(update={"name": "冲突版本"})),
            "FLOWSPEC_COMPILATION_MISMATCH",
        ),
    ]:
        with pytest.raises(MCPGatewayError) as error:
            _resolved_proposal_spec(*inputs)
        assert error.value.code == code
