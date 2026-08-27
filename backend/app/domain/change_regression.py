"""Pure contracts for S45 change-aware regression orchestration."""

# Product copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.canonical_contracts import (
    contains_sensitive_contract_value,
    semantic_schema_fingerprint,
)
from app.domain.test_design import (
    CoverageEntry,
    CoverageModel,
    OracleSpec,
    ScenarioCandidate,
    ScenarioMutation,
    ScenarioRequest,
    TestDesignDocument,
)
from app.domain.test_engineering import (
    ContractParameter,
    GenerationPolicy,
    OperationContract,
    TestEngineeringEngine,
)

ChangeRegressionStatus = Literal[
    "review_required",
    "approved",
    "queued",
    "running",
    "evidence_ready",
    "passed",
    "blocked",
    "failed",
]
StageName = Literal[
    "change",
    "impact",
    "regression_selection",
    "missing_test",
    "review",
    "execution",
    "evidence",
    "release_gate",
    "failure_triage",
]

STAGES: Final[tuple[StageName, ...]] = (
    "change",
    "impact",
    "regression_selection",
    "missing_test",
    "review",
    "execution",
    "evidence",
    "release_gate",
    "failure_triage",
)


class OperationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_definition_id: str | None = None
    api_version: int | None = Field(default=None, ge=1)
    portable_operation_ref: str = Field(min_length=1, max_length=240)
    service_key: str = Field(min_length=1, max_length=160)
    method: str = Field(pattern=r"^[A-Z]+$", max_length=16)
    normalized_path: str = Field(min_length=1, max_length=2048)
    contract_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def semantic_prefix(self) -> str:
        instance = self.api_definition_id or self.portable_operation_ref
        version = str(self.api_version) if self.api_definition_id is not None else "portable"
        return (
            f"{instance}|v={version}|contract={self.contract_fingerprint}"
            f"|service={self.service_key}|method={self.method}|path={self.normalized_path}"
            f"|operation={self.portable_operation_ref}"
        )


class SemanticCoverageFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_identity: OperationIdentity
    request_location: Literal["path", "query", "header", "cookie", "body"]
    field_path: str = Field(min_length=1, max_length=512)
    semantic_value: str = Field(min_length=1, max_length=65536)
    scenario_kind: str = Field(min_length=1, max_length=80)
    expected_category: Literal["success", "invalid_request", "unauthorized", "unknown"]
    oracle_identity: str | None = Field(default=None, max_length=240)
    oracle_identities: tuple[str, ...] = Field(default=(), max_length=100)
    oracle_set_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    oracle_reachability: tuple[
        Literal[
            "direct_oracle",
            "unconditional_assert",
            "conditional_assert",
            "disconnected_assert",
            "unknown_graph",
        ],
        ...,
    ] = ()
    source_asset_type: Literal["test_case", "workflow", "test_design"]
    source_asset_id: str = Field(min_length=1, max_length=160)
    source_asset_version: int = Field(ge=1)
    workflow_version: int = Field(ge=1)
    request_node_id: str | None = Field(default=None, min_length=1, max_length=128)
    request_path_template: str | None = Field(default=None, min_length=1, max_length=2048)
    oracle_node_ids: tuple[str, ...] = Field(default=(), max_length=100)
    test_plan_id: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def normalize_oracle_set(self) -> SemanticCoverageFact:
        identities = self.oracle_identities
        if not identities and self.oracle_identity is not None:
            identities = (self.oracle_identity,)
        fingerprint = self.oracle_set_fingerprint or oracle_set_fingerprint(identities)
        if identities == self.oracle_identities and fingerprint == self.oracle_set_fingerprint:
            return self
        return self.model_copy(
            update={
                "oracle_identities": tuple(sorted(set(identities))),
                "oracle_set_fingerprint": fingerprint,
            }
        )

    @property
    def complete(self) -> bool:
        return (
            self.expected_category != "unknown"
            and bool(self.oracle_identities)
            and self.oracle_set_fingerprint is not None
        )

    @property
    def target_key(self) -> str:
        return (
            f"{self.operation_identity.semantic_prefix}|{self.request_location}|{self.field_path}"
        )

    @property
    def coverage_token(self) -> str:
        fingerprint = self.oracle_set_fingerprint or "unknown-oracle"
        return f"{self.semantic_value}|{self.expected_category}|{fingerprint}"

    @property
    def asset_key(self) -> tuple[str, str, int, int]:
        """Return the immutable asset/version identity that produced this fact."""

        return (
            self.source_asset_type,
            self.source_asset_id,
            self.source_asset_version,
            self.workflow_version,
        )


def oracle_set_fingerprint(identities: list[str] | tuple[str, ...]) -> str | None:
    normalized = sorted({identity for identity in identities if identity})
    if not normalized:
        return None
    return hashlib.sha256("\n".join(normalized).encode()).hexdigest()


def oracle_semantic_identity(oracle: OracleSpec) -> str | None:
    """Project an executable Oracle without IDs, labels, provenance, or sensitive values."""

    if not oracle.deterministic or oracle.requires_review:
        return None
    if oracle.kind == "status":
        if isinstance(oracle.expected, int) and not isinstance(oracle.expected, bool):
            return f"status:{oracle.expected}"
        if oracle.operator == "in" and isinstance(oracle.expected, list):
            statuses = sorted(
                {
                    value
                    for value in oracle.expected
                    if isinstance(value, int) and not isinstance(value, bool)
                }
            )
            return "status_set:" + ",".join(str(value) for value in statuses) if statuses else None
        return None
    if oracle.kind == "schema" and isinstance(oracle.expected, dict):
        return f"schema:{semantic_schema_fingerprint(oracle.expected)}"
    if oracle.kind not in {"json_path", "expression"}:
        return None
    if contains_sensitive_contract_value(oracle.expected):
        return None
    canonical_expected = json.dumps(
        oracle.expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    prefix = "json_path" if oracle.kind == "json_path" else "expression"
    return f"{prefix}:{oracle.expression}|{oracle.operator}|{canonical_expected}"


def scenario_oracle_identities(
    scenario: ScenarioCandidate, oracles: list[OracleSpec]
) -> tuple[str, ...]:
    identities = {
        identity
        for oracle in oracles
        if scenario.id in oracle.applies_to
        and (identity := oracle_semantic_identity(oracle)) is not None
    }
    return tuple(sorted(identities))


class ChangeConstraintTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: Literal["path", "query", "header", "cookie", "body"]
    field_path: tuple[str, ...]
    constraint: Literal[
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "enum",
        "pattern",
        "format",
    ]
    before: JsonValue = None
    after: JsonValue = None

    @property
    def mutation_path(self) -> str:
        return f"{self.location}.{'.'.join(self.field_path)}"

    @property
    def parameter_name(self) -> str | None:
        return self.field_path[0] if self.location != "body" and len(self.field_path) == 1 else None


def regression_fingerprint(
    *,
    source_fingerprint: str,
    candidate_ref: str,
    test_plan_id: str,
    selected_assets: list[dict[str, JsonValue]],
    missing_tests: list[dict[str, JsonValue]],
) -> str:
    payload = {
        "source_fingerprint": source_fingerprint,
        "candidate_ref": candidate_ref,
        "test_plan_id": test_plan_id,
        "selected_assets": selected_assets,
        "missing_tests": missing_tests,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def missing_test_design(
    *,
    gap: dict[str, JsonValue],
    source_ref: str,
    position: int,
    current_contract: OperationContract | None = None,
    covered_values: set[str] | None = None,
) -> dict[str, JsonValue]:
    """Generate an evidence-backed Test Design draft for an uncovered change."""

    raw_key = str(gap.get("change_key") or f"gap-{position}")
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
    source_key = str(gap.get("source_key") or raw_key)[:240]
    label = str(gap.get("label") or source_key)[:240]
    contract = current_contract or _change_contract(gap=gap, digest=digest, source_ref=source_ref)
    target = change_constraint_target(gap)
    unresolved_target = current_contract is not None and not _exact_change_target_exists(
        current_contract, target
    )
    generation_contract = (
        _change_contract(gap=gap, digest=digest, source_ref=source_ref)
        if unresolved_target
        else _focused_change_contract(contract, gap)
        if current_contract
        else contract
    )
    generated = TestEngineeringEngine().generate(
        contract=generation_contract,
        policy=GenerationPolicy(max_scenarios=30, pairwise_enabled=False),
    )
    scenarios = _change_scenarios(generated, gap)
    candidate_oracles = _extend_oracle_scope(generated, scenarios)
    scenarios = _exclude_covered_scenarios(
        scenarios,
        candidate_oracles,
        covered_values or set(),
    )
    if unresolved_target:
        scenarios = [
            scenario.model_copy(
                update={
                    "expected_category": "review",
                    "deterministic": False,
                    "requires_review": True,
                    "confidence": min(scenario.confidence, 0.5),
                    "tags": sorted({*scenario.tags, "change-target-unresolved"}),
                }
            )
            for scenario in scenarios
        ]
    oracles = _extend_oracle_scope(generated, scenarios)
    coverage = _change_coverage(generated, gap, scenarios)
    document = generated.model_copy(
        update={
            "intent": generated.intent.model_copy(
                update={
                    "key": f"missing_{digest}",
                    "objective": f"验证变更 {label} 的边界与回归行为",
                    "preconditions": [f"变更来源：{source_ref[:200]}"],
                    "acceptance_criteria": [
                        f"变更 {source_key} 的新边界、历史边界与 Oracle 都有可审核证据"
                    ],
                    "confidence": 0.75,
                }
            ),
            "scenarios": scenarios,
            "oracles": oracles,
            "coverage": coverage,
            "warnings": [
                *generated.warnings,
                "变更回归草案需人工核对存量覆盖与业务前置条件",
                *(
                    ["当前契约无法唯一定位变更字段；草案仅可 Design 审核"]
                    if unresolved_target
                    else []
                ),
            ],
            "confidence": 0.5 if unresolved_target else 0.75,
            "review_requirements": sorted(
                {
                    *generated.review_requirements,
                    "change_impact_review",
                    *({"change_target_unresolved"} if unresolved_target else set()),
                }
            ),
        }
    )
    return cast(dict[str, JsonValue], document.model_dump(mode="json"))


def _focused_change_contract(
    contract: OperationContract, gap: dict[str, JsonValue]
) -> OperationContract:
    """Limit generation to the exact changed location while retaining response oracles."""

    target = change_constraint_target(gap)
    if target is None:
        return contract
    if target.location == "body":
        leaf = _schema_at_path(contract.body_schema, list(target.field_path))
        if leaf is None:
            return contract
        focused_schema = _nested_schema(list(target.field_path), leaf)
        request_body = contract.request_body
        if request_body is not None:
            request_body = request_body.model_copy(update={"schema_": focused_schema})
        return contract.model_copy(
            update={
                "parameters": [],
                "request_body": request_body,
                "request": focused_schema,
            }
        )
    parameter = _target_parameter(contract, target)
    if parameter is None:
        return contract
    return contract.model_copy(
        update={"parameters": [parameter], "request_body": None, "request": {}}
    )


def _target_parameter(
    contract: OperationContract, target: ChangeConstraintTarget
) -> ContractParameter | None:
    name = target.parameter_name
    if name is None:
        return None
    matches = [
        parameter
        for parameter in contract.parameters
        if parameter.location == target.location
        and (
            parameter.name.lower() == name.lower()
            if target.location == "header"
            else parameter.name == name
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _exact_change_target_exists(
    contract: OperationContract, target: ChangeConstraintTarget | None
) -> bool:
    if target is None:
        return False
    if target.location == "body":
        return _schema_at_path(contract.body_schema, list(target.field_path)) is not None
    return _target_parameter(contract, target) is not None


def _schema_at_path(
    schema: dict[str, JsonValue], field_path: list[str]
) -> dict[str, JsonValue] | None:
    current: JsonValue = schema
    for name in field_path:
        if not isinstance(current, dict):
            return None
        properties = current.get("properties")
        if not isinstance(properties, dict):
            return None
        current = properties.get(name)
    return current if isinstance(current, dict) else None


def _nested_schema(field_path: list[str], leaf: dict[str, JsonValue]) -> dict[str, JsonValue]:
    current = deepcopy(leaf)
    for name in reversed(field_path):
        current = {
            "type": "object",
            "required": [name],
            "properties": {name: current},
        }
    return current


def _change_contract(
    *, gap: dict[str, JsonValue], digest: str, source_ref: str
) -> OperationContract:
    source_key = str(gap.get("source_key") or "POST /change")
    method, path = _operation_target(source_key)
    target = change_constraint_target(gap)
    request = (
        _request_schema(list(target.field_path), target.constraint, gap.get("after"))
        if target is not None and target.location == "body"
        else {}
    )
    parameters = (
        [
            ContractParameter(
                name=target.parameter_name,
                location=target.location,
                required=target.location == "path",
                schema=_constraint_schema(target.constraint, gap.get("after")),
            )
        ]
        if target is not None and target.location != "body" and target.parameter_name is not None
        else []
    )
    return OperationContract.model_validate(
        {
            "operation": f"change_{digest}",
            "method": method,
            "path": path,
            "parameters": parameters,
            "request": request,
            "responses": {},
            "source_ref": source_ref[:512] or f"change://{digest}",
            "revision": str(gap.get("change_key") or digest)[:160],
        }
    )


def _operation_target(source_key: str) -> tuple[str, str]:
    parts = source_key.split(maxsplit=1)
    if len(parts) == 2 and parts[0].isalpha() and parts[1].startswith("/"):
        return parts[0].upper(), parts[1][:2048]
    return "POST", "/change-impact"


def change_constraint_target(gap: dict[str, JsonValue]) -> ChangeConstraintTarget | None:
    raw_path = str(gap.get("field_path") or "")
    parts = [part for part in raw_path.split(".") if part]
    if parts and parts[0] == "response":
        return None
    if parts and parts[0] == "request":
        parts.pop(0)
    if not parts or parts[0] not in {"path", "query", "header", "cookie", "body"}:
        return None
    location = parts.pop(0)
    constraint = parts.pop() if parts and parts[-1] in _CONSTRAINT_KEYS else None
    safe_parts = [part for part in parts if re.fullmatch(r"[A-Za-z0-9_-]+", part)]
    if constraint is None or not safe_parts:
        return None
    return ChangeConstraintTarget(
        location=cast(Literal["path", "query", "header", "cookie", "body"], location),
        field_path=tuple(safe_parts[:8]),
        constraint=cast(AnyConstraint, constraint),
        before=gap.get("before"),
        after=gap.get("after"),
    )


_CONSTRAINT_KEYS = frozenset(
    {
        "enum",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "format",
    }
)
AnyConstraint = Literal[
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "enum",
    "pattern",
    "format",
]


def _request_schema(
    field_path: list[str], constraint: str | None, after: JsonValue
) -> dict[str, JsonValue]:
    if not field_path or constraint is None:
        return {}
    leaf: dict[str, JsonValue] = {"type": _constraint_schema_type(constraint, after)}
    if after is not None:
        leaf[constraint] = after
    current: dict[str, JsonValue] = leaf
    for name in reversed(field_path):
        current = {"type": "object", "properties": {name: current}}
    return current


def _constraint_schema(constraint: str, after: JsonValue) -> dict[str, JsonValue]:
    schema: dict[str, JsonValue] = {"type": _constraint_schema_type(constraint, after)}
    if after is not None:
        schema[constraint] = after
    return schema


def _constraint_schema_type(constraint: str, value: JsonValue = None) -> str:
    if constraint in {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}:
        return "integer" if isinstance(value, int) and not isinstance(value, bool) else "number"
    if constraint in {"minItems", "maxItems"}:
        return "array"
    return "string"


def _change_scenarios(
    generated: TestDesignDocument, gap: dict[str, JsonValue]
) -> list[ScenarioCandidate]:
    target = change_constraint_target(gap)
    if target is None:
        return list(generated.scenarios)
    mutation_path = target.mutation_path
    scenarios = []
    for item in generated.scenarios:
        if not any(mutation.path == mutation_path for mutation in item.mutations):
            continue
        labeled = _label_generated_boundary(item, gap)
        if {"new_legal_boundary", "new_illegal_boundary"}.intersection(labeled.tags):
            scenarios.append(labeled)
    scenarios.extend(_historical_boundary_scenarios(generated, gap))
    by_id = {scenario.id: scenario for scenario in scenarios}
    return [by_id[key] for key in sorted(by_id)]


def _label_generated_boundary(
    scenario: ScenarioCandidate, gap: dict[str, JsonValue]
) -> ScenarioCandidate:
    semantic_type = str(gap.get("semantic_type") or "")
    mapping = _change_boundary_kinds(semantic_type)
    label = mapping.get(scenario.kind)
    if label is None:
        return scenario
    return scenario.model_copy(update={"tags": sorted({*scenario.tags, "change-impact", label})})


def _change_boundary_kinds(semantic_type: str) -> dict[str, str]:
    mappings = {
        "maximum_changed": ("number_at_max", "number_above_max"),
        "minimum_changed": ("number_at_min", "number_below_min"),
        "exclusiveMaximum_changed": (
            "number_below_exclusive_max",
            "number_at_exclusive_max",
        ),
        "exclusiveMinimum_changed": (
            "number_above_exclusive_min",
            "number_at_exclusive_min",
        ),
        "maxLength_changed": ("string_at_max_length", "string_above_max_length"),
        "minLength_changed": ("string_at_min_length", "string_below_min_length"),
        "maxItems_changed": ("array_at_max", "array_above_max"),
        "minItems_changed": ("array_at_min", "array_below_min"),
        "pattern_changed": ("pattern_valid", "pattern_invalid"),
        "format_changed": ("format_valid", "format_invalid"),
        "enum_changed": ("enum_value", "enum_invalid"),
    }
    kinds = mappings.get(semantic_type)
    return (
        {kinds[0]: "new_legal_boundary", kinds[1]: "new_illegal_boundary"}
        if kinds is not None
        else {}
    )


def _historical_boundary_scenarios(
    generated: TestDesignDocument, gap: dict[str, JsonValue]
) -> list[ScenarioCandidate]:
    before = gap.get("before")
    after = gap.get("after")
    semantic_type = str(gap.get("semantic_type") or "")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return []
    if semantic_type not in {"maximum_changed", "minimum_changed"}:
        return []
    direction: Literal["minimum", "maximum"] = (
        "maximum" if semantic_type == "maximum_changed" else "minimum"
    )
    base = _base_request(generated)
    target = change_constraint_target(gap)
    mutation_path = target.mutation_path if target is not None else _mutation_path(generated)
    adjacent = before + 1 if direction == "maximum" else before - 1
    return [
        _historical_scenario(base, mutation_path, before, after, direction, "historical_boundary"),
        _historical_scenario(
            base, mutation_path, adjacent, after, direction, "historical_adjacent"
        ),
    ]


def _historical_scenario(
    base: ScenarioRequest,
    path: str,
    value: int | float,
    current_boundary: int | float,
    direction: Literal["minimum", "maximum"],
    kind: str,
) -> ScenarioCandidate:
    request = deepcopy(base)
    _set_request_value(request, path, value)
    valid = value <= current_boundary if direction == "maximum" else value >= current_boundary
    validity_label = "合法" if valid else "非法"
    suffix = hashlib.sha256(f"{kind}:{path}:{value}".encode()).hexdigest()[:10]
    return ScenarioCandidate(
        id=f"scenario_change_{kind}_{suffix}",
        kind=f"change_{kind}",
        title=f"{path}: 历史边界值 {value} 在当前契约下应{validity_label}",
        request_body=request.body if isinstance(request.body, dict) else {},
        request=request,
        mutations=[
            ScenarioMutation(
                path=path,
                location=cast(
                    Literal["path", "query", "header", "cookie", "body", "auth"],
                    path.split(".", 1)[0],
                ),
                operation="set",
                value=value,
            )
        ],
        expected_category="success" if valid else "invalid_request",
        negative=not valid,
        tags=["generated", "change-impact", kind],
    )


def _base_request(document: TestDesignDocument) -> ScenarioRequest:
    happy = next((item for item in document.scenarios if item.kind == "happy_path"), None)
    return deepcopy(happy.request) if happy is not None else ScenarioRequest(body={})


def _mutation_path(document: TestDesignDocument) -> str:
    for scenario in document.scenarios:
        if scenario.mutations:
            return scenario.mutations[0].path
    return "body.value"


def _set_nested(target: dict[str, JsonValue], path: str, value: JsonValue) -> None:
    parts = [part for part in path.split(".") if part]
    cursor = target
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    if parts:
        cursor[parts[-1]] = value


def _set_request_value(request: ScenarioRequest, path: str, value: JsonValue) -> None:
    location, _, field_path = path.partition(".")
    if location == "body":
        body = request.body if isinstance(request.body, dict) else {}
        _set_nested(body, field_path, value)
        request.body = body
        return
    target = {
        "path": request.path_parameters,
        "query": request.query_parameters,
        "header": request.headers,
        "cookie": request.cookies,
    }.get(location)
    if target is not None:
        target[field_path] = value


def existing_semantic_values(documents: list[TestDesignDocument]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for document in documents:
        for scenario in document.scenarios:
            for mutation in scenario.mutations:
                if mutation.operation == "omit":
                    continue
                result.setdefault(mutation.path, set()).add(_semantic_value(mutation.value))
    return result


def gap_covered_values(gap: dict[str, JsonValue], coverage: dict[str, set[str]]) -> set[str]:
    target = change_constraint_target(gap)
    path = target.mutation_path if target is not None else "body.value"
    return set(coverage.get(path, set()))


def _exclude_covered_scenarios(
    scenarios: list[ScenarioCandidate],
    oracles: list[OracleSpec],
    covered_values: set[str],
) -> list[ScenarioCandidate]:
    return [
        scenario
        for scenario in scenarios
        if not scenario.mutations
        or (token := _scenario_coverage_token(scenario, oracles)) is None
        or token not in covered_values
    ]


def _semantic_value(value: JsonValue | None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _scenario_coverage_token(scenario: ScenarioCandidate, oracles: list[OracleSpec]) -> str | None:
    identities = scenario_oracle_identities(scenario, oracles)
    fingerprint = oracle_set_fingerprint(identities)
    if fingerprint is None or scenario.expected_category == "review":
        return None
    return (
        f"{_semantic_value(scenario.mutations[0].value)}|{scenario.expected_category}|{fingerprint}"
    )


def semantic_coverage_tokens(
    facts: list[SemanticCoverageFact],
    identity: OperationIdentity,
    target: ChangeConstraintTarget,
    *,
    asset_scope: set[tuple[str, str, int, int]] | None = None,
) -> set[str]:
    """Select complete coverage for one operation/location/field and optional asset scope."""

    field_path = ".".join(target.field_path)
    return {
        fact.coverage_token
        for fact in facts
        if fact.complete
        and same_operation_semantics(fact.operation_identity, identity)
        and fact.request_location == target.location
        and fact.field_path == field_path
        and (asset_scope is None or fact.asset_key in asset_scope)
    }


def same_operation_semantics(left: OperationIdentity, right: OperationIdentity) -> bool:
    """Compare instance-local or portable operation semantics without unsafe fallback."""

    if left.api_definition_id is not None and right.api_definition_id is not None:
        return (
            left.api_definition_id,
            left.api_version,
            left.contract_fingerprint,
            left.service_key,
            left.method,
            left.normalized_path,
            left.portable_operation_ref,
        ) == (
            right.api_definition_id,
            right.api_version,
            right.contract_fingerprint,
            right.service_key,
            right.method,
            right.normalized_path,
            right.portable_operation_ref,
        )
    return (
        left.service_key,
        left.method,
        left.normalized_path,
        left.portable_operation_ref,
        left.contract_fingerprint,
    ) == (
        right.service_key,
        right.method,
        right.normalized_path,
        right.portable_operation_ref,
        right.contract_fingerprint,
    )


def _same_operation(left: OperationIdentity, right: OperationIdentity) -> bool:
    """Compatibility alias for callers outside the coverage pipeline."""

    return same_operation_semantics(left, right)


def _extend_oracle_scope(
    generated: TestDesignDocument, scenarios: list[ScenarioCandidate]
) -> list[OracleSpec]:
    generated_categories = {
        scenario.id: scenario.expected_category for scenario in generated.scenarios
    }
    result: list[OracleSpec] = []
    for oracle in generated.oracles:
        categories = {
            generated_categories[scenario_id]
            for scenario_id in oracle.applies_to
            if scenario_id in generated_categories
        }
        applicable = [
            scenario.id
            for scenario in scenarios
            if not oracle.applies_to or scenario.expected_category in categories
        ]
        result.append(oracle.model_copy(update={"applies_to": applicable}))
    return result


def _change_coverage(
    generated: TestDesignDocument,
    gap: dict[str, JsonValue],
    scenarios: list[ScenarioCandidate],
) -> CoverageModel:
    field_path = str(gap.get("field_path") or gap.get("source_key") or "change")
    entries = list(generated.coverage.entries)
    entries.extend(
        CoverageEntry(
            target_ref=field_path[:240],
            dimension="change_impact",
            requirement=tag.replace("_", " "),
            covered=any(tag in scenario.tags for scenario in scenarios),
            reason="由结构化 Contract Diff 驱动",
            recommended_scenario_kind=tag,
            priority="high",
        )
        for tag in (
            "new_legal_boundary",
            "new_illegal_boundary",
            "historical_boundary",
            "historical_adjacent",
        )
    )
    return CoverageModel(entries=entries)


def transition_status(current: str, target: ChangeRegressionStatus) -> None:
    allowed: dict[str, frozenset[str]] = {
        "review_required": frozenset({"approved", "failed"}),
        "approved": frozenset({"queued", "failed"}),
        "queued": frozenset({"running", "evidence_ready", "failed"}),
        "running": frozenset({"evidence_ready", "failed"}),
        "evidence_ready": frozenset({"passed", "blocked", "failed"}),
        "passed": frozenset(),
        "blocked": frozenset(),
        "failed": frozenset(),
    }
    if current != target and target not in allowed.get(current, frozenset()):
        raise ValueError(f"invalid change regression transition: {current} -> {target}")
