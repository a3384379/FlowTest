"""Pure contracts for S45 change-aware regression orchestration."""

# Product copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Final, Literal, cast

from pydantic import JsonValue

from app.domain.test_design import (
    CoverageEntry,
    CoverageModel,
    OracleSpec,
    ScenarioCandidate,
    ScenarioMutation,
    ScenarioRequest,
    TestDesignDocument,
)
from app.domain.test_engineering import GenerationPolicy, OperationContract, TestEngineeringEngine

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
    generation_contract = _focused_change_contract(contract, gap) if current_contract else contract
    generated = TestEngineeringEngine().generate(
        contract=generation_contract,
        policy=GenerationPolicy(max_scenarios=30, pairwise_enabled=False),
    )
    scenarios = _change_scenarios(generated, gap)
    scenarios = _exclude_covered_scenarios(scenarios, covered_values or set())
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
            ],
            "confidence": 0.75,
            "review_requirements": sorted({*generated.review_requirements, "change_impact_review"}),
        }
    )
    return cast(dict[str, JsonValue], document.model_dump(mode="json"))


def _focused_change_contract(
    contract: OperationContract, gap: dict[str, JsonValue]
) -> OperationContract:
    """Limit generation to the changed body field while retaining actual response oracles."""

    field_path, constraint = _constraint_target(gap)
    if not field_path or constraint is None:
        return contract
    leaf = _schema_at_path(contract.body_schema, field_path)
    if leaf is None:
        return contract
    focused_schema = _nested_schema(field_path, leaf)
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
    field_path, constraint = _constraint_target(gap)
    request = _request_schema(field_path, constraint, gap.get("after"))
    return OperationContract.model_validate(
        {
            "operation": f"change_{digest}",
            "method": method,
            "path": path,
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


def _constraint_target(gap: dict[str, JsonValue]) -> tuple[list[str], str | None]:
    raw_path = str(gap.get("field_path") or "")
    parts = [part for part in raw_path.split(".") if part]
    if parts and parts[0] in {"request", "response"}:
        parts.pop(0)
    if parts and parts[0] == "body":
        parts.pop(0)
    constraint = parts.pop() if parts and parts[-1] in _CONSTRAINT_KEYS else None
    safe_parts = [part for part in parts if part.replace("_", "").isalnum()]
    return safe_parts[:8], constraint


_CONSTRAINT_KEYS = frozenset(
    {"enum", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}
)


def _request_schema(
    field_path: list[str], constraint: str | None, after: JsonValue
) -> dict[str, JsonValue]:
    if not field_path or constraint is None:
        return {}
    leaf: dict[str, JsonValue] = {"type": _constraint_schema_type(constraint)}
    if after is not None:
        leaf[constraint] = after
    current: dict[str, JsonValue] = leaf
    for name in reversed(field_path):
        current = {"type": "object", "properties": {name: current}}
    return current


def _constraint_schema_type(constraint: str) -> str:
    if constraint in {"minimum", "maximum"}:
        return "number"
    if constraint in {"minItems", "maxItems"}:
        return "array"
    return "string"


def _change_scenarios(
    generated: TestDesignDocument, gap: dict[str, JsonValue]
) -> list[ScenarioCandidate]:
    field_path, constraint = _constraint_target(gap)
    if constraint is None:
        return list(generated.scenarios)
    mutation_path = f"body.{'.'.join(field_path)}" if field_path else _mutation_path(generated)
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
    mapping = (
        {
            "number_at_max": "new_legal_boundary",
            "number_above_max": "new_illegal_boundary",
        }
        if semantic_type == "maximum_changed"
        else {
            "number_at_min": "new_legal_boundary",
            "number_below_min": "new_illegal_boundary",
        }
        if semantic_type == "minimum_changed"
        else {}
    )
    label = mapping.get(scenario.kind)
    if label is None:
        return scenario
    return scenario.model_copy(update={"tags": sorted({*scenario.tags, "change-impact", label})})


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
    field_path, _constraint = _constraint_target(gap)
    mutation_path = f"body.{'.'.join(field_path)}" if field_path else _mutation_path(generated)
    adjacent = before + 1 if direction == "maximum" else before - 1
    return [
        _historical_scenario(base, mutation_path, before, after, direction, "historical_boundary"),
        _historical_scenario(
            base, mutation_path, adjacent, after, direction, "historical_adjacent"
        ),
    ]


def _historical_scenario(
    base: dict[str, JsonValue],
    path: str,
    value: int | float,
    current_boundary: int | float,
    direction: Literal["minimum", "maximum"],
    kind: str,
) -> ScenarioCandidate:
    body = deepcopy(base)
    _set_nested(body, path.removeprefix("body."), value)
    valid = value <= current_boundary if direction == "maximum" else value >= current_boundary
    validity_label = "合法" if valid else "非法"
    suffix = hashlib.sha256(f"{kind}:{path}:{value}".encode()).hexdigest()[:10]
    return ScenarioCandidate(
        id=f"scenario_change_{kind}_{suffix}",
        kind=f"change_{kind}",
        title=f"{path}: 历史边界值 {value} 在当前契约下应{validity_label}",
        request_body=body,
        request=ScenarioRequest(body=body),
        mutations=[ScenarioMutation(path=path, location="body", operation="set", value=value)],
        expected_category="success" if valid else "invalid_request",
        negative=not valid,
        tags=["generated", "change-impact", kind],
    )


def _base_request(document: TestDesignDocument) -> dict[str, JsonValue]:
    happy = next((item for item in document.scenarios if item.kind == "happy_path"), None)
    return deepcopy(happy.request_body) if happy is not None else {}


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
    field_path, _constraint = _constraint_target(gap)
    path = f"body.{'.'.join(field_path)}" if field_path else "body.value"
    return set(coverage.get(path, set()))


def _exclude_covered_scenarios(
    scenarios: list[ScenarioCandidate], covered_values: set[str]
) -> list[ScenarioCandidate]:
    return [
        scenario
        for scenario in scenarios
        if not scenario.mutations
        or _semantic_value(scenario.mutations[0].value) not in covered_values
    ]


def _semantic_value(value: JsonValue | None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _extend_oracle_scope(
    generated: TestDesignDocument, scenarios: list[ScenarioCandidate]
) -> list[OracleSpec]:
    success_ids = [item.id for item in scenarios if item.expected_category == "success"]
    invalid_ids = [item.id for item in scenarios if item.expected_category == "invalid_request"]
    return [
        oracle.model_copy(
            update={
                "applies_to": (
                    success_ids
                    if oracle.id == "oracle_success_status"
                    else invalid_ids
                    if oracle.id == "oracle_invalid_request_status"
                    else oracle.applies_to
                )
            }
        )
        for oracle in generated.oracles
    ]


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
