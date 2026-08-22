"""Pure contracts for S45 change-aware regression orchestration."""

# Product copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
from typing import Final, Literal, cast

from pydantic import JsonValue

from app.domain.test_design import TestDesignDocument

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
    """Build a safe, low-confidence Test Design draft for an uncovered change."""

    raw_key = str(gap.get("change_key") or f"gap-{position}")
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
    source_key = str(gap.get("source_key") or raw_key)[:240]
    label = str(gap.get("label") or source_key)[:240]
    document = TestDesignDocument.model_validate(
        {
            "schema_version": "1.0",
            "intent": {
                "key": f"missing_{digest}",
                "objective": f"验证变更 {label} 的回归行为",
                "actors": ["regression-runner"],
                "preconditions": [f"变更来源：{source_ref[:200]}"],
                "acceptance_criteria": [f"变更 {source_key} 有可执行的回归证据"],
            },
            "knowledge_graph": {
                "nodes": [
                    {"id": f"change_{digest}", "kind": "change", "label": label},
                ],
                "edges": [],
            },
            "state_model": {
                "initial_state": "initial",
                "states": [
                    {"id": "initial", "name": "初始", "terminal": False},
                    {"id": "verified", "name": "已验证", "terminal": True},
                ],
                "transitions": [
                    {
                        "source": "initial",
                        "target": "verified",
                        "event": "regression_passed",
                    }
                ],
            },
            "oracles": [
                {
                    "id": f"oracle_{digest}",
                    "kind": "expression",
                    "expression": "execution.status",
                    "operator": "equals",
                    "expected": "passed",
                    "confidence": 0.65,
                    "source_ref": source_ref[:200],
                }
            ],
            "coverage": {
                "entries": [
                    {
                        "target_ref": source_key,
                        "requirement": "变更项必须有回归测试覆盖",
                        "covered": False,
                        "evidence_refs": [],
                    }
                ]
            },
            "test_case_refs": [],
        }
    )
    return cast(dict[str, JsonValue], document.model_dump(mode="json"))


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
