"""Independent readiness rubric; Design/preview success cannot stand in for Cases."""

from typing import Literal

from pydantic import Field, StrictBool
from scripts.selftest.contracts import Contract
from scripts.selftest.io import JsonObject, object_value, objects_value, text_value


class QualityRubric(Contract):
    required_kinds: tuple[str, ...] = Field(min_length=1)
    required_cases: int = Field(ge=1, le=50)
    require_complete_coverage: StrictBool = True


class QualityDecision(Contract):
    readiness: Literal["ready", "blocked", "needs_review", "incomplete"]
    required_count: int
    selected_count: int
    executable_count: int
    reason_codes: tuple[str, ...]


def review_design_quality(
    design: JsonObject,
    compiled: JsonObject | None,
    rubric: QualityRubric,
    *,
    proposed_case_count: int | None = None,
) -> QualityDecision:
    scenarios = objects_value(design.get("scenarios", []))
    selected = {text_value(item["kind"]) for item in scenarios}
    reasons: list[str] = []
    if not scenarios:
        reasons.append("REQUIRED_SCENARIO_SET_EMPTY")
    if not set(rubric.required_kinds) <= selected:
        reasons.append("REQUIRED_SCENARIO_COVERAGE_MISSING")
    if _needs_review(design, scenarios):
        reasons.append("SOURCE_REQUIRES_REVIEW")
    entries = objects_value(object_value(design.get("coverage", {})).get("entries", []))
    if rubric.require_complete_coverage and (
        not entries or any(item["covered"] is not True for item in entries)
    ):
        reasons.append("SOURCE_COVERAGE_INCOMPLETE")
    executable = _executable_count(compiled)
    if proposed_case_count is not None:
        executable = proposed_case_count
    if executable < rubric.required_cases:
        reasons.append("REQUIRED_EXECUTABLE_CASE_MISSING")
    readiness: Literal["ready", "blocked", "needs_review", "incomplete"] = "ready"
    if "SOURCE_REQUIRES_REVIEW" in reasons:
        readiness = "needs_review"
    elif reasons:
        readiness = "incomplete" if scenarios else "blocked"
    return QualityDecision(
        readiness=readiness,
        required_count=len(rubric.required_kinds),
        selected_count=len(scenarios),
        executable_count=executable,
        reason_codes=tuple(reasons),
    )


def _needs_review(design: JsonObject, scenarios: list[JsonObject]) -> bool:
    return bool(design.get("review_requirements")) or any(
        item.get("requires_review") is True or item.get("deterministic") is False
        for item in [*scenarios, *objects_value(design.get("oracles", []))]
    )


def _executable_count(compiled: JsonObject | None) -> int:
    if compiled is None or compiled.get("readiness") != "ready":
        return 0
    return sum(
        item.get("readiness") == "ready"
        and item.get("executable_payload") is not None
        and item.get("case_template") is not None
        for item in objects_value(compiled.get("scenarios", []))
    )
