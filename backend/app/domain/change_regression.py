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
    *, gap: dict[str, JsonValue], source_ref: str, position: int
) -> dict[str, JsonValue]:
    """Generate an evidence-backed Test Design draft for an uncovered change."""

    raw_key = str(gap.get("change_key") or f"gap-{position}")
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
    source_key = str(gap.get("source_key") or raw_key)[:240]
    label = str(gap.get("label") or source_key)[:240]
    contract = _change_contract(gap=gap, digest=digest, source_ref=source_ref)
    generated = TestEngineeringEngine().generate(
        contract=contract,
        policy=GenerationPolicy(max_scenarios=30, pairwise_enabled=False),
    )
    scenarios = _change_scenarios(generated, gap)
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
            "responses": {
                "200": {"description": "回归行为符合当前契约"},
                "400": {"description": "输入超出当前契约边界"},
            },
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
    scenarios = [_label_generated_boundary(item, gap) for item in generated.scenarios]
    scenarios.extend(_historical_boundary_scenarios(generated, gap))
    by_id = {scenario.id: scenario for scenario in scenarios}
    return [by_id[key] for key in sorted(by_id)]


def _label_generated_boundary(
    scenario: ScenarioCandidate, gap: dict[str, JsonValue]
) -> ScenarioCandidate:
    semantic_type = str(gap.get("semantic_type") or "")
    mapping = {
        "number_at_max": "new_legal_boundary",
        "number_above_max": "new_illegal_boundary",
        "number_at_min": "new_legal_boundary",
        "number_below_min": "new_illegal_boundary",
    }
    label = mapping.get(scenario.kind)
    if label is None or not semantic_type.endswith("_changed"):
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
    mutation_path = _mutation_path(generated)
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
        mutations=[ScenarioMutation(path=path, operation="set", value=value)],
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
