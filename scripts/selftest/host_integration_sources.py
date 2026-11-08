"""Consume a model's actual MCP IntegrationPlan/Compilation pair without lowering again."""

from __future__ import annotations

from pydantic import Field
from scripts.selftest.contracts import ApiSource, Contract, OracleBinding, Sha256
from scripts.selftest.generation_lifecycle import (
    OperationGeneration,
    _oracle_bindings,
    _purpose,
    combine_generated_designs,
)
from scripts.selftest.host_contracts import HostGeneratedDesign
from scripts.selftest.host_gateway import BoundedGateway, ToolExchange, business_success
from scripts.selftest.io import HarnessError, JsonObject, object_value

from app.domain.integration_plans import IntegrationPlan, IntegrationPlanCompilation
from app.domain.test_design import TestDesignDocument, fingerprint_design
from app.schemas.flow_spec import FlowSpecVisualProposalResponse


class HostIntegrationSource(Contract):
    operations: tuple[OperationGeneration, ...] = Field(min_length=2, max_length=100)
    plan: IntegrationPlan
    compilation: IntegrationPlanCompilation
    combined_design: TestDesignDocument
    design_composition: JsonObject
    combined_design_fingerprint: Sha256
    context: JsonObject


def _data(exchange: ToolExchange) -> JsonObject:
    structured = object_value(exchange.result.structured_content)
    return object_value(structured.get("data", structured))


def _pair(
    gateway: BoundedGateway, visual: FlowSpecVisualProposalResponse
) -> tuple[IntegrationPlan, IntegrationPlanCompilation]:
    plan, compilation = visual.integration_plan, visual.compilation
    if (
        plan is None
        or compilation is None
        or not compilation.importable
        or compilation.flow_spec is None
    ):
        raise HarnessError("HOST_INTEGRATION_COMPILED_PAIR_MISSING")
    matching = [
        exchange
        for exchange in gateway.exchanges
        if exchange.name == "flowtest.compile_integration_flowspec"
        and business_success(exchange.result)
        and IntegrationPlanCompilation.model_validate(_data(exchange)) == compilation
        and IntegrationPlan.model_validate(exchange.arguments.get("plan")) == plan
    ]
    if not matching:
        raise HarnessError("HOST_INTEGRATION_COMPILE_CALL_MISSING")
    originals = [
        IntegrationPlan.model_validate(_data(exchange))
        for exchange in gateway.exchanges
        if exchange.name == "flowtest.plan_integration_test"
        and business_success(exchange.result)
        and _data(exchange).get("context_revision_id") == str(plan.context_revision_id)
    ]
    if len(originals) != 1:
        raise HarnessError("HOST_INTEGRATION_PLANNER_SOURCE_AMBIGUOUS")
    original = originals[0]
    actual = {operation.ref: operation for operation in plan.operations}
    if set(actual) != {operation.ref for operation in original.operations}:
        raise HarnessError("HOST_INTEGRATION_OPERATION_SET_CHANGED")
    for operation in original.operations:
        left = operation.model_dump(exclude={"request", "credential_refs"})
        if actual[operation.ref].model_dump(exclude={"request", "credential_refs"}) != left:
            raise HarnessError("HOST_INTEGRATION_OPERATION_ORIGIN_CHANGED")
    final_oracles = {oracle.id: oracle for oracle in plan.oracles}
    if any(final_oracles.get(oracle.id) != oracle for oracle in original.oracles):
        raise HarnessError("HOST_INTEGRATION_GENERATED_ORACLE_CHANGED")
    return plan, compilation


def integration_source(
    gateway: BoundedGateway, visual: FlowSpecVisualProposalResponse
) -> tuple[HostIntegrationSource, tuple[OracleBinding, ...]]:
    plan, compilation = _pair(gateway, visual)
    generated = [
        HostGeneratedDesign.model_validate(_data(exchange))
        for exchange in gateway.exchanges
        if exchange.name == "flowtest.generate_test_design" and business_success(exchange.result)
    ]
    operations = []
    for operation in plan.operations:
        designs = [
            item
            for item in generated
            if item.design.intent.key == operation.ref
            and item.origin.api_version == operation.source_version
            and item.origin.contract_fingerprint == operation.contract_fingerprint
        ]
        if not designs or any(item != designs[0] for item in designs):
            raise HarnessError("HOST_INTEGRATION_DESIGN_ORIGIN_MISSING")
        design = designs[0]
        mapped = visual.operation_mappings.get(operation.ref)
        if (
            mapped != design.origin.api_definition_id
            or visual.operation_version_mappings.get(operation.ref) != operation.source_version
        ):
            raise HarnessError("HOST_INTEGRATION_EXACT_API_BINDING_CHANGED")
        scenarios = [item for item in design.design.scenarios if item.kind == "happy_path"]
        if len(scenarios) != 1:
            raise HarnessError("HOST_INTEGRATION_DESIGN_SCENARIO_AMBIGUOUS")
        purpose = _purpose({"method": operation.method, "path": operation.path})
        operations.append(
            OperationGeneration(
                purpose=purpose,
                api_source=ApiSource(
                    project_id=gateway.authorization.project_id,
                    api_definition_id=mapped,
                    api_version=operation.source_version,
                    contract_fingerprint=operation.contract_fingerprint,
                ),
                operation_ref=operation.ref,
                design=design.design.model_dump(mode="json"),
                design_fingerprint=design.fingerprint,
                scenario_id=scenarios[0].id,
            )
        )
    if {item.purpose for item in operations} != {
        "login",
        "create",
        "list",
        "patch",
        "delete",
    } or len(operations) != 5:
        raise HarnessError("HOST_INTEGRATION_LIFECYCLE_PURPOSE_SET_UNSUPPORTED")
    ordered = tuple(
        sorted(
            operations,
            key=lambda item: ("login", "create", "list", "patch", "delete").index(item.purpose),
        )
    )
    combined, composition = combine_generated_designs(ordered)
    proposal_calls = [
        exchange
        for exchange in gateway.exchanges
        if exchange.name == "flowtest.propose_flow_draft"
        and _data(exchange).get("change_set_id") == str(visual.proposal.id)
    ]
    if len(proposal_calls) != 1:
        raise HarnessError("HOST_INTEGRATION_PROPOSAL_BINDING_AMBIGUOUS")
    args = proposal_calls[0].arguments
    context = {
        "context_id": args["context_id"],
        "context_revision_id": args["context_revision_id"],
        "context_fingerprint": plan.context_fingerprint,
    }
    return HostIntegrationSource(
        operations=ordered,
        plan=plan,
        compilation=compilation,
        combined_design=combined,
        design_composition=composition,
        combined_design_fingerprint=fingerprint_design(combined),
        context=context,
    ), _oracle_bindings(compilation.model_dump(mode="json"))
