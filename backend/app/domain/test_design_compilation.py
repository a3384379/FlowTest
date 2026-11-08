"""Bounded, side-effect-free compilation of a frozen generated Test Design."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.canonical_schemas import CanonicalSchemaValidator
from app.domain.evidence import EvidenceBundle
from app.domain.expressions import validate_safe_expression
from app.domain.flow_spec import FlowSpecNodeTarget, FlowSpecOperation
from app.domain.flow_spec_v2 import (
    FlowSpecV2,
    flow_spec_v2_to_workflow_definition,
    validate_flow_spec_v2,
    workflow_definition_to_flow_spec_v2,
)
from app.domain.test_design import OracleSpec, ScenarioCandidate, TestDesignDocument
from app.domain.test_design_lowering import (
    ScenarioLoweringError,
    expected_status,
    scenario_oracles,
    scenario_workflow,
)
from app.domain.test_engineering import GenerationPolicy, OperationContract
from app.engine.contracts import WorkflowDefinition, WorkflowRunPolicy, parse_node_config

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Readiness = Literal["ready", "needs_input", "needs_review", "unsupported", "blocked"]


class CompilationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenGenerationOrigin(CompilationModel):
    api_definition_id: UUID
    api_version: int = Field(ge=1, strict=True)
    contract_fingerprint: Sha256
    generation_policy: GenerationPolicy
    evidence: list[EvidenceBundle] = Field(default_factory=list, max_length=10)
    evidence_fingerprints: list[Sha256] = Field(default_factory=list, max_length=10)
    generator_build: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CompilationContextBinding(CompilationModel):
    context_id: UUID
    context_revision_id: UUID
    context_fingerprint: Sha256


class CompilationFixtureBinding(CompilationModel):
    field_path: str = Field(min_length=1, max_length=512)
    fixture_ref: str = Field(pattern=r"^fixture://[A-Za-z0-9._/-]{1,400}$")


class InheritOperationAuth(CompilationModel):
    kind: Literal["inherit_operation"] = "inherit_operation"


class DisabledOperationAuth(CompilationModel):
    kind: Literal["disabled"]


class ExistingWorkflowAuth(CompilationModel):
    kind: Literal["existing_auth_workflow"]
    workflow_id: UUID
    workflow_version: int = Field(ge=1, strict=True)


class CompilationBudget(CompilationModel):
    max_scenarios: int = Field(default=50, ge=1, le=50, strict=True)
    max_nodes: int = Field(default=500, ge=1, le=500, strict=True)
    max_oracles: int = Field(default=200, ge=1, le=200, strict=True)
    max_body_bytes: int = Field(default=2 * 1024 * 1024, ge=1, le=2 * 1024 * 1024, strict=True)
    max_poll_attempts: int = Field(default=1, ge=1, le=100, strict=True)
    max_loop_iterations: int = Field(default=1, ge=1, le=1000, strict=True)
    max_total_duration: int = Field(default=300, ge=1, le=3600, strict=True)


class CompileTestDesignRequest(CompilationModel):
    project_id: UUID
    design: TestDesignDocument
    design_fingerprint: Sha256
    origin: FrozenGenerationOrigin
    scenario_ids: list[str] = Field(min_length=1, max_length=50)
    environment_id: UUID
    endpoint_variant: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,79}$")
    context_binding: CompilationContextBinding | None = None
    fixture_bindings: list[CompilationFixtureBinding] = Field(default_factory=list, max_length=100)
    auth_binding: Annotated[
        InheritOperationAuth | DisabledOperationAuth | ExistingWorkflowAuth,
        Field(discriminator="kind"),
    ] = Field(default_factory=InheritOperationAuth)
    route_preference: Literal["auto", "quick", "flowspec", "native_control"] = "auto"
    budget: CompilationBudget = Field(default_factory=CompilationBudget)

    @model_validator(mode="after")
    def validate_input_bounds(self) -> CompileTestDesignRequest:
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario_ids must be unique")
        if any(not value or len(value) > 120 for value in self.scenario_ids):
            raise ValueError("scenario_ids must be bounded nonempty identifiers")
        if len(canonical_json(self.origin.evidence)) > 2 * 1024 * 1024:
            raise ValueError("evidence byte budget exceeded")
        if len(canonical_json(self.design)) > 4 * 1024 * 1024:
            raise ValueError("design byte budget exceeded")
        return self


class CompilationDiagnostic(CompilationModel):
    code: str
    severity: Literal["blocker", "review", "input", "unsupported"]
    scenario_id: str | None = None
    oracle_id: str | None = None
    field_path: str | None = None
    repair_hint: str


class CompilationSources(CompilationModel):
    project_id: UUID
    api_definition_id: UUID
    api_version: int
    contract_fingerprint: Sha256
    environment_id: UUID
    endpoint_variant: str | None
    context_binding: CompilationContextBinding | None


class FlowSpecCompilationPayload(CompilationModel):
    kind: Literal["flow_spec"] = "flow_spec"
    spec: FlowSpecV2
    operation_mappings: dict[str, UUID]
    operation_version_mappings: dict[str, int]
    service_mappings: dict[str, UUID] = Field(default_factory=dict)
    native_definition: WorkflowDefinition


class CompilationCaseTemplate(CompilationModel):
    name: str
    description: str
    tags: list[str]
    workflow_slot: str
    environment_id: UUID
    runtime_variables: dict[str, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)


class CompilationOracleBinding(CompilationModel):
    oracle_id: str
    node_id: str
    assertion_kind: Literal["status", "json_schema", "expression"]
    source_node_id: Literal["request"] = "request"
    normalized_expression: str
    expected_value_fingerprint: Sha256


class CompilationRawOutcome(CompilationModel):
    status: Literal["passed"] = "passed"


class CompiledDesignScenario(CompilationModel):
    scenario_id: str
    readiness: Readiness
    proposal_route: Literal["flow_spec", "unsupported"] = "unsupported"
    executable_payload: FlowSpecCompilationPayload | None = None
    case_template: CompilationCaseTemplate | None = None
    oracle_bindings: list[CompilationOracleBinding] = Field(default_factory=list)
    expected_raw_outcome: CompilationRawOutcome | None = None
    source_binding_fingerprint: Sha256


class CompileTestDesignResponse(CompilationModel):
    schema_version: Literal["flowtest-design-compilation-v1"] = "flowtest-design-compilation-v1"
    design_fingerprint: Sha256
    resolved_sources: CompilationSources
    readiness: Readiness
    persisted: Literal[False] = False
    execution_status: Literal["not_run"] = "not_run"
    compilation_fingerprint: Sha256
    diagnostics: list[CompilationDiagnostic]
    scenarios: list[CompiledDesignScenario]


def canonical_json(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def value_fingerprint(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def compile_frozen_design(
    request: CompileTestDesignRequest,
    contract: OperationContract,
    *,
    service_id: UUID | None = None,
) -> CompileTestDesignResponse:
    sources = CompilationSources(
        project_id=request.project_id,
        api_definition_id=request.origin.api_definition_id,
        api_version=request.origin.api_version,
        contract_fingerprint=request.origin.contract_fingerprint,
        environment_id=request.environment_id,
        endpoint_variant=request.endpoint_variant,
        context_binding=request.context_binding,
    )
    diagnostics: list[CompilationDiagnostic] = []
    scenarios = [
        _compile_scenario(request, contract, scenario_id, diagnostics, service_id)
        for scenario_id in request.scenario_ids
    ]
    if _exceeds_budget(request, scenarios):
        diagnostics.append(
            _diagnostic("BUDGET_EXCEEDED", "blocker", "减少场景、节点、Oracle、请求体或总时长预算")
        )
        scenarios = [
            item.model_copy(update={"readiness": "blocked", "executable_payload": None})
            for item in scenarios
        ]
    readiness = aggregate_readiness([item.readiness for item in scenarios])
    content = {
        "design_fingerprint": request.design_fingerprint,
        "resolved_sources": sources.model_dump(mode="json"),
        "readiness": readiness,
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
        "scenarios": [item.model_dump(mode="json") for item in scenarios],
    }
    return CompileTestDesignResponse(**content, compilation_fingerprint=value_fingerprint(content))


def aggregate_readiness(values: list[Readiness]) -> Readiness:
    if not values:
        return "blocked"
    return next(
        value
        for value in ("blocked", "unsupported", "needs_review", "needs_input", "ready")
        if value in values
    )


def _diagnostic(
    code: str,
    severity: Literal["blocker", "review", "input", "unsupported"],
    hint: str,
    scenario_id: str | None = None,
    oracle_id: str | None = None,
) -> CompilationDiagnostic:
    return CompilationDiagnostic(
        code=f"DESIGN_COMPILATION_{code}",
        severity=severity,
        repair_hint=hint,
        scenario_id=scenario_id,
        oracle_id=oracle_id,
    )


def _compile_scenario(
    request: CompileTestDesignRequest,
    contract: OperationContract,
    scenario_id: str,
    diagnostics: list[CompilationDiagnostic],
    service_id: UUID | None,
) -> CompiledDesignScenario:
    source_fingerprint = value_fingerprint(
        {"request": request.model_dump(mode="json"), "scenario_id": scenario_id}
    )
    result = CompiledDesignScenario(
        scenario_id=scenario_id, readiness="blocked", source_binding_fingerprint=source_fingerprint
    )
    scenario = next((item for item in request.design.scenarios if item.id == scenario_id), None)
    issue = _scenario_issue(request, contract, scenario)
    if issue is not None:
        readiness, code, hint = issue
        diagnostics.append(
            _diagnostic(
                code,
                "review"
                if readiness == "needs_review"
                else "unsupported"
                if readiness == "unsupported"
                else "blocker",
                hint,
                scenario_id,
            )
        )
        return result.model_copy(update={"readiness": readiness})
    if scenario is None:
        return result
    try:
        oracles = scenario_oracles(request.design, scenario)
        status = expected_status(request.design, scenario)
        _validate_oracles(oracles)
        native = scenario_workflow(
            request.origin.api_definition_id,
            request.origin.api_version,
            scenario,
            status,
            oracles,
            request.endpoint_variant,
        )
        native.run_policy = WorkflowRunPolicy(
            request_budget=1,
            max_runtime_seconds=max(
                1, request.budget.max_total_duration // len(request.scenario_ids)
            ),
        )
        for node in native.nodes:
            parse_node_config(node)
        executable = _executable_payload(request, contract, native, service_id)
    except (ScenarioLoweringError, ValueError) as error:
        diagnostics.append(
            _diagnostic("UNSUPPORTED_ORACLE", "unsupported", str(error), scenario_id)
        )
        return result.model_copy(update={"readiness": "unsupported"})
    readiness = "ready" if request.context_binding is not None else "needs_input"
    if readiness == "needs_input":
        diagnostics.append(
            _diagnostic(
                "CONTEXT_REQUIRED",
                "input",
                "创建并绑定当前 Test Context 后再交现有 FlowSpec 提案工具",
                scenario_id,
            )
        )
    return result.model_copy(
        update={
            "readiness": readiness,
            "proposal_route": "flow_spec",
            "executable_payload": executable,
            "case_template": CompilationCaseTemplate(
                name=scenario.title[:200],
                description=f"由冻结 Test Design 场景 {scenario.id} 编译",
                tags=["generated", "test-engineering", scenario.kind],
                workflow_slot=f"scenario:{scenario.id}",
                environment_id=request.environment_id,
            ),
            "oracle_bindings": _oracle_bindings(oracles),
            "expected_raw_outcome": CompilationRawOutcome(),
        }
    )


def _scenario_issue(
    request: CompileTestDesignRequest,
    contract: OperationContract,
    scenario: ScenarioCandidate | None,
) -> tuple[Readiness, str, str] | None:
    if scenario is None:
        return "blocked", "SCENARIO_INVALID", "所选场景不属于冻结 Design"
    if scenario.requires_review or not scenario.deterministic:
        return "needs_review", "SCENARIO_REVIEW_REQUIRED", "先解决场景证据冲突或前置条件"
    if any(
        oracle.requires_review or not oracle.deterministic
        for oracle in request.design.oracles
        if scenario.id in oracle.applies_to
    ):
        return "needs_review", "ORACLE_REVIEW_REQUIRED", "先审核所有已选场景 Oracle"
    if request.route_preference in {"quick", "native_control"}:
        return "unsupported", "ROUTE_UNSUPPORTED", "当前固定 Design 适配仅支持无损 FlowSpec 路线"
    if request.fixture_bindings or request.auth_binding.kind == "existing_auth_workflow":
        return (
            "unsupported",
            "BINDING_UNSUPPORTED",
            "当前单场景适配不支持额外 fixture 或认证子流程绑定",
        )
    if request.auth_binding.kind == "disabled" and not scenario.request.auth_disabled:
        return "blocked", "AUTH_BINDING_MISMATCH", "不能改变冻结场景的认证语义"
    if _ambiguous_request(scenario, contract):
        return (
            "unsupported",
            "REQUEST_UNREPRESENTABLE",
            "当前 lowering 无法无损表示根 body null/缺失、重复参数或 path 请求变异",
        )
    return None


def _ambiguous_request(scenario: ScenarioCandidate, contract: OperationContract) -> bool:
    if scenario.request.body is None and (contract.request_body is not None or contract.request):
        return True
    return any(
        mutation.operation == "duplicate" or mutation.location == "path"
        for mutation in scenario.mutations
    )


def _validate_oracles(oracles: list[OracleSpec]) -> None:
    statuses = [oracle for oracle in oracles if oracle.kind == "status"]
    if (
        len(statuses) != 1
        or statuses[0].operator != "equals"
        or type(statuses[0].expected) is not int
    ):
        raise ValueError("状态 Oracle 必须是唯一的整数 equals")
    if not 100 <= statuses[0].expected <= 599:
        raise ValueError("状态 Oracle 超出 HTTP 状态码范围")
    for oracle in oracles:
        _validate_oracle_expression(oracle)


def _validate_oracle_expression(oracle: OracleSpec) -> None:
    if oracle.kind == "schema":
        if not isinstance(oracle.expected, dict) or oracle.operator not in {"equals", "validates"}:
            raise ValueError("Schema Oracle 必须使用 JSON Schema validates 语义")
        CanonicalSchemaValidator().validate(oracle.expected)
        return
    if oracle.kind in {"json_path", "expression"}:
        validate_safe_expression(oracle.expression)
    if oracle.operator == "matches":
        if not isinstance(oracle.expected, str):
            raise ValueError("Matches Oracle 必须使用正则字符串")
        try:
            re.compile(oracle.expected)
        except re.error as error:
            raise ValueError("Matches Oracle 正则无效") from error


def _executable_payload(
    request: CompileTestDesignRequest,
    contract: OperationContract,
    native: WorkflowDefinition,
    service_id: UUID | None,
) -> FlowSpecCompilationPayload:
    operation_ref = f"api:{request.origin.api_definition_id}"
    target = (
        FlowSpecNodeTarget(endpoint_variant=request.endpoint_variant)
        if request.endpoint_variant
        else None
    )
    spec = workflow_definition_to_flow_spec_v2(
        native,
        project_id=request.project_id,
        name=next(node.name for node in native.nodes if node.id == "request")[:200],
        source_evidence=[f"test-design://{request.design_fingerprint}"],
        operation_refs={"request": operation_ref},
        node_targets={"request": target} if target else {},
        operations=[
            FlowSpecOperation(
                ref=operation_ref,
                name=contract.operation[:200],
                method=contract.method,
                path=contract.path,
                version_strategy="pinned",
                source_version=request.origin.api_version,
                contract_fingerprint=request.origin.contract_fingerprint,
            )
        ],
    )
    validation = validate_flow_spec_v2(spec)
    if not validation.valid:
        raise ValueError("; ".join(issue.message for issue in validation.issues))
    mappings = {operation_ref: request.origin.api_definition_id}
    versions = {operation_ref: request.origin.api_version}
    restored = flow_spec_v2_to_workflow_definition(
        spec, operation_mappings=mappings, operation_versions=versions
    )
    _require_semantic_roundtrip(native, restored)
    return FlowSpecCompilationPayload(
        spec=spec,
        operation_mappings=mappings,
        operation_version_mappings=versions,
        native_definition=restored,
    )


def _require_semantic_roundtrip(before: WorkflowDefinition, after: WorkflowDefinition) -> None:
    for attribute in ("nodes", "edges"):
        if {item.id: item.model_dump(mode="json") for item in getattr(before, attribute)} != {
            item.id: item.model_dump(mode="json") for item in getattr(after, attribute)
        }:
            raise ValueError("原生图与 FlowSpec 往返语义不一致")
    if before.variables != after.variables or before.run_policy != after.run_policy:
        raise ValueError("变量或运行预算在 FlowSpec 转换中丢失")


def _oracle_bindings(oracles: list[OracleSpec]) -> list[CompilationOracleBinding]:
    bindings = []
    schema_index = expression_index = 0
    for oracle in oracles:
        kind: Literal["status", "json_schema", "expression"]
        if oracle.kind == "status":
            node_id, kind = "assert_status", "status"
        elif oracle.kind == "schema":
            schema_index += 1
            node_id, kind = f"assert_schema_{schema_index}", "json_schema"
        else:
            expression_index += 1
            node_id, kind = f"assert_expression_{expression_index}", "expression"
        bindings.append(
            CompilationOracleBinding(
                oracle_id=oracle.id,
                node_id=node_id,
                assertion_kind=kind,
                normalized_expression=(
                    "body"
                    if kind == "json_schema"
                    else "status_code"
                    if kind == "status"
                    else oracle.expression
                ),
                expected_value_fingerprint=value_fingerprint(oracle.expected),
            )
        )
    return bindings


def _exceeds_budget(
    request: CompileTestDesignRequest, scenarios: list[CompiledDesignScenario]
) -> bool:
    payloads = [
        item.executable_payload for item in scenarios if item.executable_payload is not None
    ]
    return (
        len(scenarios) > request.budget.max_scenarios
        or sum(len(payload.native_definition.nodes) for payload in payloads)
        > request.budget.max_nodes
        or sum(len(item.oracle_bindings) for item in scenarios) > request.budget.max_oracles
        or sum(
            len(canonical_json(scenario.request.body))
            for scenario in request.design.scenarios
            if scenario.id in request.scenario_ids
        )
        > request.budget.max_body_bytes
        or len(scenarios) > request.budget.max_total_duration
    )
