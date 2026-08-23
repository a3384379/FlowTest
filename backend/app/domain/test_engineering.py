"""Deterministic evidence-driven test design generation."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.evidence import (
    EvidenceBundle,
    EvidenceFinding,
    EvidenceSourceType,
)
from app.domain.test_design import (
    CoverageEntry,
    CoverageModel,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    OracleSpec,
    ScenarioCandidate,
    ScenarioMutation,
    TestDesignDocument,
    TestIntent,
)


class ContractAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False


class ContractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    description: str = Field(default="", max_length=2000)
    schema_: dict[str, JsonValue] | None = Field(default=None, alias="schema")


class OperationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.:-]{0,239}$")
    method: str = Field(pattern=r"^[A-Z]+$", min_length=3, max_length=16)
    path: str = Field(min_length=1, max_length=2048)
    service: str | None = Field(default=None, max_length=160)
    auth: ContractAuth = Field(default_factory=ContractAuth)
    request: dict[str, JsonValue] = Field(default_factory=dict, max_length=500)
    responses: dict[str, ContractResponse] = Field(default_factory=dict, max_length=100)
    source_ref: str | None = Field(default=None, max_length=512)
    revision: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_responses(self) -> OperationContract:
        if any(re.fullmatch(r"[1-5][0-9]{2}|default", status) is None for status in self.responses):
            raise ValueError("contract response keys must be HTTP status codes or default")
        return self


class GenerationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_scenarios: int = Field(default=50, ge=1, le=1000)
    include_negative: bool = True
    include_auth: bool = True
    include_state: bool = True
    include_data_constraints: bool = True
    pairwise_enabled: bool = True


class TestEngineeringEngine:
    """Generate a design from contract evidence without caller-authored design objects."""

    def generate(
        self,
        *,
        contract: OperationContract,
        policy: GenerationPolicy | None = None,
        additional_evidence: list[EvidenceBundle] | None = None,
    ) -> TestDesignDocument:
        generation_policy = policy or GenerationPolicy()
        contract_bundle = contract_evidence(contract)
        bundles = [contract_bundle, *(additional_evidence or [])]
        evidence = _merge_evidence(contract, bundles)
        fields = _field_constraints(evidence)
        candidates = _scenario_candidates(contract, fields, generation_policy)
        scenarios = candidates[: generation_policy.max_scenarios]
        truncated = len(candidates) > len(scenarios)
        oracles, oracle_warnings = OracleInferenceEngine().infer(contract, evidence, scenarios)
        coverage = CoverageAnalyzer().analyze(
            contract=contract,
            fields=fields,
            scenarios=scenarios,
            oracles=oracles,
        )
        warnings = list(oracle_warnings)
        if truncated:
            warnings.append(
                f"场景预算为 {generation_policy.max_scenarios},已稳定截断,"
                "未覆盖项保留在 Coverage Gap"
            )
        review_requirements = sorted(
            {"oracle_conflict_or_inference" for oracle in oracles if oracle.requires_review}
        )
        refs = evidence.refs
        confidence = min(
            [finding.confidence for finding in evidence.findings]
            + [oracle.confidence for oracle in oracles]
        )
        return TestDesignDocument(
            intent=_intent(contract, evidence),
            knowledge_graph=_knowledge_graph(contract),
            state_model=None,
            scenarios=scenarios,
            oracles=oracles,
            coverage=coverage,
            evidence_refs=refs,
            warnings=warnings,
            confidence=confidence,
            review_requirements=review_requirements,
        )


class OracleInferenceEngine:
    def infer(
        self,
        contract: OperationContract,
        evidence: EvidenceBundle,
        scenarios: list[ScenarioCandidate],
    ) -> tuple[list[OracleSpec], list[str]]:
        statuses = {int(key) for key in contract.responses if key.isdigit()}
        evidence_ids = _evidence_ids(evidence, "operation_contract", "response_contract")
        grouped = {
            "success": [
                scenario.id for scenario in scenarios if scenario.expected_category == "success"
            ],
            "invalid_request": [
                scenario.id
                for scenario in scenarios
                if scenario.expected_category == "invalid_request"
            ],
            "unauthorized": [
                scenario.id
                for scenario in scenarios
                if scenario.expected_category == "unauthorized"
            ],
        }
        oracles = [self._success_oracle(statuses, evidence_ids, grouped["success"])]
        warnings: list[str] = []
        invalid_oracle = self._negative_oracle(
            category="invalid_request",
            explicit_status=400 if 400 in statuses else None,
            scenarios=grouped["invalid_request"],
            evidence_ids=evidence_ids,
        )
        if invalid_oracle is not None:
            oracles.append(invalid_oracle)
            if invalid_oracle.requires_review:
                warnings.append("Contract 未声明非法输入状态码,负面 Oracle 仅要求非成功响应")
        auth_oracle = self._negative_oracle(
            category="unauthorized",
            explicit_status=401 if 401 in statuses else None,
            scenarios=grouped["unauthorized"],
            evidence_ids=evidence_ids,
        )
        if auth_oracle is not None:
            oracles.append(auth_oracle)
            if auth_oracle.requires_review:
                warnings.append("Contract 未声明认证失败状态码,认证 Oracle 需要审核")
        oracles.extend(_response_schema_oracles(contract, evidence))
        return oracles, warnings

    def _success_oracle(
        self, statuses: set[int], evidence_ids: list[str], scenarios: list[str]
    ) -> OracleSpec:
        success = min((status for status in statuses if 200 <= status < 300), default=200)
        explicit = success in statuses
        return OracleSpec(
            id="oracle_success_status",
            kind="status",
            expression="$.status",
            expected=success,
            confidence=1 if explicit else 0.7,
            evidence_refs=evidence_ids,
            source_type=EvidenceSourceType.CONTRACT,
            deterministic=explicit,
            requires_review=not explicit,
            applies_to=scenarios,
        )

    def _negative_oracle(
        self,
        *,
        category: Literal["invalid_request", "unauthorized"],
        explicit_status: int | None,
        scenarios: list[str],
        evidence_ids: list[str],
    ) -> OracleSpec | None:
        if not scenarios:
            return None
        suffix = "invalid_request" if category == "invalid_request" else "missing_auth"
        return OracleSpec(
            id=f"oracle_{suffix}_status",
            kind="status",
            expression="$.status",
            operator="equals" if explicit_status is not None else "non_success",
            expected=explicit_status,
            confidence=1 if explicit_status is not None else 0.7,
            evidence_refs=evidence_ids,
            source_type=EvidenceSourceType.CONTRACT,
            deterministic=explicit_status is not None,
            requires_review=explicit_status is None,
            applies_to=scenarios,
        )


class CoverageAnalyzer:
    """Compute dimension-level coverage and reusable explicit gaps."""

    def analyze(
        self,
        *,
        contract: OperationContract,
        fields: list[EvidenceFinding],
        scenarios: list[ScenarioCandidate],
        oracles: list[OracleSpec],
    ) -> CoverageModel:
        entries = [
            _coverage_entry(
                dimension="endpoint",
                target_ref=contract.operation,
                requirement="happy path",
                scenario_kind="happy_path",
                scenarios=scenarios,
                evidence_refs=_evidence_ids_from(fields),
            )
        ]
        for field in fields:
            entries.extend(_field_coverage(contract.operation, field, scenarios))
        if contract.auth.required:
            entries.append(
                _coverage_entry(
                    dimension="authorization",
                    target_ref=f"{contract.operation}.auth",
                    requirement="auth missing",
                    scenario_kind="auth_missing",
                    scenarios=scenarios,
                    evidence_refs=_evidence_ids_from(fields),
                    priority="high",
                )
            )
        entries.extend(_oracle_coverage(contract, oracles))
        return CoverageModel(entries=entries)


def contract_evidence(contract: OperationContract) -> EvidenceBundle:
    source_ref = contract.source_ref or f"contract://{contract.operation}"
    revision = contract.revision or _contract_revision(contract)
    subject_ref = f"operation://{contract.operation}"
    statuses = sorted(contract.responses)
    findings = [
        _contract_finding(
            source_ref=source_ref,
            subject_ref=subject_ref,
            revision=revision,
            kind="operation_contract",
            path="$",
            data={
                "operation": contract.operation,
                "method": contract.method,
                "path": contract.path,
                "service": contract.service,
                "auth_required": contract.auth.required,
                "response_statuses": cast(list[JsonValue], statuses),
            },
        )
    ]
    findings.extend(_request_schema_findings(contract, source_ref, revision))
    findings.extend(_response_findings(contract, source_ref, revision))
    if contract.auth.required:
        findings.append(
            _contract_finding(
                source_ref=source_ref,
                subject_ref=subject_ref,
                revision=revision,
                kind="auth_requirement",
                path="auth",
                data={"required": True},
            )
        )
    return EvidenceBundle(subject_ref=subject_ref, findings=findings)


def _request_schema_findings(
    contract: OperationContract, source_ref: str, revision: str
) -> list[EvidenceFinding]:
    findings: list[EvidenceFinding] = []
    required = _string_set(contract.request.get("required"))
    properties = contract.request.get("properties")
    if not isinstance(properties, dict):
        return findings
    for name in sorted(properties):
        schema = properties[name]
        if not isinstance(schema, dict):
            continue
        findings.extend(
            _schema_findings(
                operation=contract.operation,
                source_ref=source_ref,
                revision=revision,
                name=name,
                path=f"body.{name}",
                schema=schema,
                required=name in required,
                depth=0,
            )
        )
    return findings


def _schema_findings(
    *,
    operation: str,
    source_ref: str,
    revision: str,
    name: str,
    path: str,
    schema: dict[str, JsonValue],
    required: bool,
    depth: int,
) -> list[EvidenceFinding]:
    data: dict[str, JsonValue] = {}
    for key in (
        "type",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
        "uniqueItems",
        "additionalProperties",
    ):
        if key in schema:
            data[key] = schema[key]
    data.update({"name": name, "required": required, "nullable": _nullable(schema)})
    finding = _contract_finding(
        source_ref=source_ref,
        subject_ref=f"operation://{operation}",
        revision=revision,
        kind="field_constraint",
        path=path,
        data=data,
    )
    if depth >= 3 or not isinstance(schema.get("properties"), dict):
        return [finding]
    nested_required = _string_set(schema.get("required"))
    nested: list[EvidenceFinding] = [finding]
    properties = cast(dict[str, JsonValue], schema["properties"])
    for child_name in sorted(properties):
        child = properties[child_name]
        if isinstance(child, dict):
            nested.extend(
                _schema_findings(
                    operation=operation,
                    source_ref=source_ref,
                    revision=revision,
                    name=child_name,
                    path=f"{path}.{child_name}",
                    schema=child,
                    required=child_name in nested_required,
                    depth=depth + 1,
                )
            )
    return nested


def _response_findings(
    contract: OperationContract, source_ref: str, revision: str
) -> list[EvidenceFinding]:
    findings: list[EvidenceFinding] = []
    for status, response in sorted(contract.responses.items()):
        data: dict[str, JsonValue] = {"status": status, "description": response.description}
        if response.schema_ is not None:
            data["schema"] = response.schema_
        findings.append(
            _contract_finding(
                source_ref=source_ref,
                subject_ref=f"operation://{contract.operation}",
                revision=revision,
                kind="response_contract",
                path=f"responses.{status}",
                data=data,
            )
        )
    return findings


def _scenario_candidates(
    contract: OperationContract,
    fields: list[EvidenceFinding],
    policy: GenerationPolicy,
) -> list[ScenarioCandidate]:
    base = _valid_request_body(fields)
    scenarios = [
        ScenarioCandidate(
            id="scenario_happy_path",
            kind="happy_path",
            title="有效请求",
            request_body=base,
            expected_category="success",
            evidence_refs=_evidence_ids_from(fields),
            tags=["generated", "positive"],
        )
    ]
    for field in fields:
        scenarios.extend(_field_scenarios(field, base, policy))
    if policy.include_auth and policy.include_negative and contract.auth.required:
        auth_refs = [
            finding.id
            for finding in contract_evidence(contract).findings
            if finding.kind == "auth_requirement"
        ]
        scenarios.append(
            _scenario(
                field_path="auth",
                kind="auth_missing",
                title="缺失认证",
                operation="omit",
                value=None,
                base=base,
                evidence_refs=auth_refs,
                expected="unauthorized",
            )
        )
    if policy.pairwise_enabled:
        scenarios.extend(_pairwise_scenarios(fields, base))
    return _deduplicate_scenarios(scenarios)


def _field_scenarios(
    field: EvidenceFinding, base: dict[str, JsonValue], policy: GenerationPolicy
) -> list[ScenarioCandidate]:
    data = field.structured_data
    path = field.path
    scenarios: list[ScenarioCandidate] = []
    if bool(data.get("required")):
        scenarios.append(
            _negative_scenario(field, base, "required_omitted", "省略必填字段", "omit")
        )
        if bool(data.get("nullable")):
            scenarios.append(
                _positive_scenario(field, base, "required_null", "必填字段为 null", "null")
            )
        else:
            scenarios.append(
                _negative_scenario(field, base, "required_null", "必填字段为 null", "null")
            )
    else:
        scenarios.append(
            _positive_scenario(field, base, "optional_omitted", "省略可选字段", "omit")
        )
    if not policy.include_data_constraints:
        return scenarios
    scenarios.extend(_numeric_scenarios(field, base))
    scenarios.extend(_string_scenarios(field, base))
    scenarios.extend(_array_scenarios(field, base))
    if policy.include_negative and _schema_type(data) in {
        "integer",
        "number",
        "boolean",
        "object",
        "array",
    }:
        scenarios.append(
            _negative_scenario(
                field,
                base,
                "invalid_type",
                f"{path} 类型错误",
                "invalid_type",
                _invalid_type_value(data.get("type")),
            )
        )
    return (
        scenarios if policy.include_negative else [item for item in scenarios if not item.negative]
    )


def _numeric_scenarios(
    field: EvidenceFinding, base: dict[str, JsonValue]
) -> list[ScenarioCandidate]:
    data = field.structured_data
    if _schema_type(data) not in {"integer", "number"}:
        return []
    scenarios: list[ScenarioCandidate] = []
    minimum = data.get("minimum")
    maximum = data.get("maximum")
    if isinstance(minimum, (int, float)):
        scenarios.extend(
            [
                _negative_scenario(
                    field, base, "number_below_min", "低于最小值", "set", minimum - 1
                ),
                _positive_scenario(field, base, "number_at_min", "等于最小值", "set", minimum),
            ]
        )
    if isinstance(maximum, (int, float)):
        scenarios.extend(
            [
                _positive_scenario(field, base, "number_at_max", "等于最大值", "set", maximum),
                _negative_scenario(
                    field, base, "number_above_max", "高于最大值", "set", maximum + 1
                ),
            ]
        )
    return scenarios


def _string_scenarios(
    field: EvidenceFinding, base: dict[str, JsonValue]
) -> list[ScenarioCandidate]:
    data = field.structured_data
    if _schema_type(data) != "string":
        return []
    scenarios: list[ScenarioCandidate] = []
    enum_values = data.get("enum")
    if isinstance(enum_values, list):
        scenarios.extend(
            _positive_scenario(field, base, "enum_value", f"枚举值 {value}", "set", value)
            for value in enum_values
        )
        scenarios.append(
            _negative_scenario(field, base, "enum_invalid", "无效枚举值", "set", "__invalid__")
        )
    minimum = data.get("minLength")
    maximum = data.get("maxLength")
    if isinstance(minimum, int):
        scenarios.extend(
            [
                _negative_scenario(
                    field,
                    base,
                    "string_below_min_length",
                    "低于最小长度",
                    "set",
                    "x" * max(0, minimum - 1),
                ),
                _positive_scenario(
                    field, base, "string_at_min_length", "等于最小长度", "set", "x" * minimum
                ),
            ]
        )
    if isinstance(maximum, int):
        scenarios.extend(
            [
                _positive_scenario(
                    field, base, "string_at_max_length", "等于最大长度", "set", "x" * maximum
                ),
                _negative_scenario(
                    field,
                    base,
                    "string_above_max_length",
                    "高于最大长度",
                    "set",
                    "x" * (maximum + 1),
                ),
            ]
        )
    if isinstance(data.get("format"), str):
        valid, invalid = _format_values(cast(str, data["format"]))
        scenarios.extend(
            [
                _positive_scenario(field, base, "format_valid", "有效格式", "set", valid),
                _negative_scenario(field, base, "format_invalid", "无效格式", "set", invalid),
            ]
        )
    return scenarios


def _array_scenarios(field: EvidenceFinding, base: dict[str, JsonValue]) -> list[ScenarioCandidate]:
    data = field.structured_data
    if _schema_type(data) != "array":
        return []
    scenarios: list[ScenarioCandidate] = []
    minimum = data.get("minItems")
    maximum = data.get("maxItems")
    if isinstance(minimum, int):
        scenarios.extend(
            [
                _negative_scenario(
                    field,
                    base,
                    "array_below_min",
                    "低于最少元素数",
                    "set",
                    ["x"] * max(0, minimum - 1),
                ),
                _positive_scenario(
                    field, base, "array_at_min", "等于最少元素数", "set", ["x"] * minimum
                ),
            ]
        )
    if isinstance(maximum, int):
        scenarios.extend(
            [
                _positive_scenario(
                    field, base, "array_at_max", "等于最多元素数", "set", ["x"] * maximum
                ),
                _negative_scenario(
                    field, base, "array_above_max", "高于最多元素数", "set", ["x"] * (maximum + 1)
                ),
            ]
        )
    if data.get("uniqueItems") is True:
        scenarios.append(
            _negative_scenario(
                field, base, "array_duplicate", "数组包含重复元素", "duplicate", ["x", "x"]
            )
        )
    return scenarios


def _positive_scenario(
    field: EvidenceFinding,
    base: dict[str, JsonValue],
    kind: str,
    title: str,
    operation: Literal["set", "omit", "null", "invalid_type", "duplicate"],
    value: JsonValue | None = None,
) -> ScenarioCandidate:
    return _scenario(
        field_path=field.path,
        kind=kind,
        title=title,
        operation=operation,
        value=value,
        base=base,
        evidence_refs=[field.id],
        expected="success",
    )


def _negative_scenario(
    field: EvidenceFinding,
    base: dict[str, JsonValue],
    kind: str,
    title: str,
    operation: Literal["set", "omit", "null", "invalid_type", "duplicate"],
    value: JsonValue | None = None,
) -> ScenarioCandidate:
    return _scenario(
        field_path=field.path,
        kind=kind,
        title=title,
        operation=operation,
        value=value,
        base=base,
        evidence_refs=[field.id],
        expected="invalid_request",
    )


def _scenario(
    *,
    field_path: str,
    kind: str,
    title: str,
    operation: Literal["set", "omit", "null", "invalid_type", "duplicate"],
    value: JsonValue | None,
    base: dict[str, JsonValue],
    evidence_refs: list[str],
    expected: Literal["success", "invalid_request", "unauthorized", "review"],
) -> ScenarioCandidate:
    body = deepcopy(base)
    if field_path.startswith("body."):
        _apply_mutation(body, field_path.removeprefix("body."), operation, value)
    suffix = sha256(f"{kind}:{field_path}:{operation}:{value}".encode()).hexdigest()[:10]
    return ScenarioCandidate(
        id=f"scenario_{kind}_{suffix}",
        kind=kind,
        title=f"{field_path}: {title}",
        request_body=body,
        mutations=[ScenarioMutation(path=field_path, operation=operation, value=value)],
        expected_category=expected,
        negative=expected != "success",
        evidence_refs=evidence_refs,
        tags=["generated", "negative" if expected != "success" else "positive"],
    )


def _pairwise_scenarios(
    fields: list[EvidenceFinding], base: dict[str, JsonValue]
) -> list[ScenarioCandidate]:
    representatives = [
        (field, _valid_value(field.structured_data))
        for field in fields
        if field.path.count(".") == 1
    ]
    scenarios: list[ScenarioCandidate] = []
    for index, (left, left_value) in enumerate(representatives):
        for right, right_value in representatives[index + 1 :]:
            body = deepcopy(base)
            _apply_mutation(body, left.path.removeprefix("body."), "set", left_value)
            _apply_mutation(body, right.path.removeprefix("body."), "set", right_value)
            suffix = sha256(f"{left.path}:{right.path}".encode()).hexdigest()[:10]
            scenarios.append(
                ScenarioCandidate(
                    id=f"scenario_pairwise_{suffix}",
                    kind="pairwise",
                    title=f"Pairwise: {left.path} + {right.path}",
                    request_body=body,
                    mutations=[
                        ScenarioMutation(path=left.path, operation="set", value=left_value),
                        ScenarioMutation(path=right.path, operation="set", value=right_value),
                    ],
                    expected_category="success",
                    evidence_refs=[left.id, right.id],
                    tags=["generated", "pairwise"],
                )
            )
    return scenarios


def _field_coverage(
    operation: str, field: EvidenceFinding, scenarios: list[ScenarioCandidate]
) -> list[CoverageEntry]:
    data = field.structured_data
    requirements: list[tuple[str, str, str, str]] = []
    if bool(data.get("required")):
        requirements.extend(
            [
                ("required_field", "required omitted", "required_omitted", "high"),
                ("required_field", "null", "required_null", "high"),
            ]
        )
    if "minimum" in data:
        requirements.extend(
            [
                ("boundary", "minimum", "number_at_min", "high"),
                ("boundary", "below minimum", "number_below_min", "high"),
            ]
        )
    if "maximum" in data:
        requirements.extend(
            [
                ("boundary", "maximum", "number_at_max", "high"),
                ("boundary", "above maximum", "number_above_max", "high"),
            ]
        )
    enum_values = data.get("enum")
    if isinstance(enum_values, list):
        requirements.extend(
            [("enum", f"enum value {value}", "enum_value", "medium") for value in enum_values]
        )
        requirements.append(("enum", "invalid enum", "enum_invalid", "high"))
    if "maxLength" in data:
        requirements.extend(
            [
                ("boundary", "maxLength", "string_at_max_length", "medium"),
                ("boundary", "above maxLength", "string_above_max_length", "high"),
            ]
        )
    if _schema_type(data) in {"integer", "number", "boolean", "object", "array"}:
        requirements.append(("type_negative", "invalid type", "invalid_type", "high"))
    if "format" in data:
        requirements.extend(
            [
                ("format", "valid format", "format_valid", "medium"),
                ("format", "invalid format", "format_invalid", "high"),
            ]
        )
    return [
        _coverage_entry(
            dimension=cast(CoverageDimension, dimension),
            target_ref=f"{operation}.{field.path}",
            requirement=requirement,
            scenario_kind=kind,
            scenarios=scenarios,
            evidence_refs=[field.id],
            priority=cast(CoveragePriority, priority),
            field_path=field.path,
            expected_value=(
                requirement.removeprefix("enum value ")
                if requirement.startswith("enum value ")
                else None
            ),
        )
        for dimension, requirement, kind, priority in requirements
    ]


CoverageDimension = Literal[
    "endpoint",
    "required_field",
    "parameter",
    "boundary",
    "enum",
    "type_negative",
    "format",
    "response_status",
    "schema",
    "authorization",
    "state",
    "transition",
    "database_constraint",
    "change_impact",
]
CoveragePriority = Literal["low", "medium", "high", "critical"]


def _coverage_entry(
    *,
    dimension: CoverageDimension,
    target_ref: str,
    requirement: str,
    scenario_kind: str,
    scenarios: list[ScenarioCandidate],
    evidence_refs: list[str],
    priority: CoveragePriority = "medium",
    field_path: str | None = None,
    expected_value: str | None = None,
) -> CoverageEntry:
    covered = any(
        scenario.kind == scenario_kind
        and (
            field_path is None
            or any(mutation.path == field_path for mutation in scenario.mutations)
        )
        and (
            expected_value is None
            or any(str(mutation.value) == expected_value for mutation in scenario.mutations)
        )
        for scenario in scenarios
    )
    return CoverageEntry(
        dimension=dimension,
        target_ref=target_ref,
        requirement=requirement,
        covered=covered,
        evidence_refs=evidence_refs,
        reason="" if covered else "场景预算或生成策略未覆盖此证据约束",
        recommended_scenario_kind=None if covered else scenario_kind,
        priority=priority,
    )


def _oracle_coverage(contract: OperationContract, oracles: list[OracleSpec]) -> list[CoverageEntry]:
    entries: list[CoverageEntry] = []
    for status in sorted(contract.responses):
        if not status.isdigit():
            continue
        covered = any(
            oracle.kind == "status" and oracle.expected == int(status) for oracle in oracles
        )
        entries.append(
            CoverageEntry(
                dimension="response_status",
                target_ref=f"{contract.operation}.responses.{status}",
                requirement=f"status {status}",
                covered=covered,
                reason="" if covered else "没有可绑定到场景的确定性状态码 Oracle",
                priority="high" if status.startswith(("4", "5")) else "medium",
            )
        )
    return entries


def _response_schema_oracles(
    contract: OperationContract, evidence: EvidenceBundle
) -> list[OracleSpec]:
    result: list[OracleSpec] = []
    for status, response in sorted(contract.responses.items()):
        if response.schema_ is None:
            continue
        evidence_ids = [
            finding.id
            for finding in evidence.findings
            if finding.kind == "response_contract" and finding.path == f"responses.{status}"
        ]
        result.append(
            OracleSpec(
                id=f"oracle_response_schema_{status}",
                kind="schema",
                expression="$.body",
                operator="validates",
                expected=response.schema_,
                confidence=1,
                evidence_refs=evidence_ids,
                source_type=EvidenceSourceType.CONTRACT,
                applies_to=[],
            )
        )
    return result


def _valid_request_body(fields: list[EvidenceFinding]) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {}
    for field in fields:
        if field.path.count(".") != 1:
            continue
        body[field.path.removeprefix("body.")] = _valid_value(field.structured_data)
    return body


def _valid_value(data: dict[str, JsonValue]) -> JsonValue:
    values = data.get("enum")
    if isinstance(values, list) and values:
        return values[0]
    value_type = _schema_type(data)
    if value_type in {"integer", "number"}:
        minimum = data.get("minimum")
        return minimum if isinstance(minimum, (int, float)) else 1
    if value_type == "boolean":
        return True
    if value_type == "array":
        minimum = data.get("minItems")
        return ["item"] * (minimum if isinstance(minimum, int) else 1)
    if value_type == "object":
        return {}
    if isinstance(data.get("format"), str):
        return _format_values(cast(str, data["format"]))[0]
    minimum_length = data.get("minLength")
    return "x" * max(1, minimum_length if isinstance(minimum_length, int) else 1)


def _invalid_type_value(value_type: JsonValue) -> JsonValue:
    if isinstance(value_type, str) and value_type in {"integer", "number", "boolean"}:
        return "invalid"
    if isinstance(value_type, str) and value_type in {"object", "array"}:
        return 1
    return None


def _format_values(format_name: str) -> tuple[str, str]:
    values = {
        "email": ("user@example.test", "not-an-email"),
        "uuid": ("00000000-0000-4000-8000-000000000000", "not-a-uuid"),
        "date": ("2026-01-02", "2026-99-99"),
        "date-time": ("2026-01-02T03:04:05Z", "not-a-date-time"),
        "uri": ("https://example.test/resource", "not a uri"),
        "hostname": ("api.example.test", "invalid_host!"),
        "ipv4": ("192.0.2.1", "999.0.0.1"),
        "ipv6": ("2001:db8::1", "not-ipv6"),
    }
    return values.get(format_name, ("valid", "invalid"))


def _apply_mutation(
    body: dict[str, JsonValue],
    path: str,
    operation: str,
    value: JsonValue | None,
) -> None:
    parts = path.split(".")
    target = body
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    if operation == "omit":
        target.pop(parts[-1], None)
    else:
        target[parts[-1]] = None if operation == "null" else value


def _field_constraints(evidence: EvidenceBundle) -> list[EvidenceFinding]:
    return sorted(
        (finding for finding in evidence.findings if finding.kind == "field_constraint"),
        key=lambda finding: (finding.path, finding.id),
    )


def _merge_evidence(contract: OperationContract, bundles: list[EvidenceBundle]) -> EvidenceBundle:
    findings = sorted(
        (finding for bundle in bundles for finding in bundle.findings),
        key=lambda finding: finding.id,
    )
    warnings = sorted({warning for bundle in bundles for warning in bundle.warnings})
    return EvidenceBundle(
        subject_ref=f"operation://{contract.operation}", findings=findings, warnings=warnings
    )


def _intent(contract: OperationContract, evidence: EvidenceBundle) -> TestIntent:
    evidence_ids = _evidence_ids(evidence, "operation_contract")
    return TestIntent(
        key=contract.operation,
        objective=f"验证 {contract.method} {contract.path} 的契约、边界与失败语义",
        actors=[contract.service] if contract.service else [],
        acceptance_criteria=["契约成功路径通过", "确定性边界与负面场景符合显式 Oracle"],
        evidence_refs=evidence_ids,
        confidence=1,
        deterministic=True,
    )


def _knowledge_graph(contract: OperationContract) -> KnowledgeGraph:
    operation_id = f"operation:{contract.operation}"
    request_id = f"schema:{contract.operation}:request"
    nodes = [
        KnowledgeNode(id=operation_id, kind="api", label=f"{contract.method} {contract.path}"),
        KnowledgeNode(id=request_id, kind="request_schema", label="Request Schema"),
    ]
    edges = [KnowledgeEdge(source=operation_id, target=request_id, relation="accepts")]
    if contract.service:
        service_id = f"service:{contract.service}"
        nodes.append(KnowledgeNode(id=service_id, kind="service", label=contract.service))
        edges.append(KnowledgeEdge(source=operation_id, target=service_id, relation="belongs_to"))
    return KnowledgeGraph(nodes=nodes, edges=edges)


def _contract_finding(
    *,
    source_ref: str,
    subject_ref: str,
    revision: str,
    kind: str,
    path: str,
    data: dict[str, JsonValue],
) -> EvidenceFinding:
    identity = f"contract:{source_ref}:{subject_ref}:{kind}:{path}"
    return EvidenceFinding(
        id=f"evidence-{sha256(identity.encode()).hexdigest()[:24]}",
        source_type=EvidenceSourceType.CONTRACT,
        source_ref=source_ref,
        subject_ref=subject_ref,
        kind=kind,
        path=path,
        structured_data=data,
        confidence=1,
        deterministic=True,
        revision=revision,
    )


def _contract_revision(contract: OperationContract) -> str:
    payload = contract.model_dump(mode="json", exclude={"revision"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def _nullable(schema: dict[str, JsonValue]) -> bool:
    if schema.get("nullable") is True:
        return True
    value_type = schema.get("type")
    return isinstance(value_type, list) and "null" in value_type


def _schema_type(data: dict[str, JsonValue]) -> str | None:
    value = data.get("type")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, str) and item != "null"), None)
    return None


def _string_set(value: JsonValue | None) -> set[str]:
    return {str(item) for item in value} if isinstance(value, list) else set()


def _evidence_ids(evidence: EvidenceBundle, *kinds: str) -> list[str]:
    return [finding.id for finding in evidence.findings if finding.kind in kinds]


def _evidence_ids_from(findings: list[EvidenceFinding]) -> list[str]:
    return [finding.id for finding in findings]


def _deduplicate_scenarios(items: list[ScenarioCandidate]) -> list[ScenarioCandidate]:
    seen: set[str] = set()
    result: list[ScenarioCandidate] = []
    for item in items:
        semantic = json.dumps(
            item.model_dump(mode="json", exclude={"id", "title"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if semantic not in seen:
            seen.add(semantic)
            result.append(item)
    return result
