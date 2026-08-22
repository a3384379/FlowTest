from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.test_design import (
    KnowledgeGraph,
    StateModel,
    evaluate_governance,
    fingerprint_design,
    sensitive_paths,
)
from app.domain.test_design import (
    TestDesignDocument as DesignDocument,
)


def _design(*, confidence: float = 0.95) -> DesignDocument:
    return DesignDocument.model_validate(
        {
            "intent": {
                "key": "payment_happy_path",
                "objective": "验证支付请求在有效订单状态下可以完成",
                "acceptance_criteria": ["返回成功状态"],
            },
            "knowledge_graph": {
                "nodes": [
                    {"id": "order", "kind": "entity", "label": "订单"},
                    {"id": "payment", "kind": "entity", "label": "支付"},
                ],
                "edges": [{"source": "order", "target": "payment", "relation": "owns"}],
            },
            "state_model": {
                "initial_state": "created",
                "states": [
                    {"id": "created", "name": "已创建"},
                    {"id": "paid", "name": "已支付", "terminal": True},
                ],
                "transitions": [{"source": "created", "target": "paid", "event": "pay"}],
            },
            "oracles": [
                {
                    "id": "status",
                    "kind": "status",
                    "expression": "$.status",
                    "expected": 200,
                    "confidence": confidence,
                }
            ],
            "coverage": {
                "entries": [
                    {
                        "target_ref": "order:create",
                        "requirement": "覆盖创建订单",
                        "covered": True,
                        "evidence_refs": ["flowtest://runs/run-1/evidence"],
                    }
                ]
            },
        }
    )


def test_test_design_validates_graph_state_and_coverage() -> None:
    design = _design()

    assert design.coverage.coverage_percent == 100.0
    assert design.knowledge_graph.edges[0].source == "order"
    assert fingerprint_design(design) == fingerprint_design(
        DesignDocument.model_validate(design.model_dump(mode="json"))
    )


def test_test_design_rejects_unknown_graph_or_state_references() -> None:
    with pytest.raises(ValidationError, match="knowledge graph edges"):
        KnowledgeGraph.model_validate(
            {
                "nodes": [{"id": "known", "kind": "entity", "label": "Known"}],
                "edges": [{"source": "known", "target": "missing", "relation": "uses"}],
            }
        )
    with pytest.raises(ValidationError, match="initial state"):
        StateModel.model_validate(
            {
                "initial_state": "missing",
                "states": [{"id": "created", "name": "Created"}],
            }
        )


def test_governance_requires_review_for_low_confidence_and_approval_for_high_risk() -> None:
    decision = evaluate_governance(
        confidence=0.72,
        risk_level="high",
        design=_design(confidence=0.6),
    )

    assert decision.requires_review is True
    assert decision.manual_approval_required is True
    assert "low_confidence_assertion_review" in decision.reason_codes
    assert "manual_approval_required" in decision.reason_codes


def test_sensitive_input_returns_paths_without_values() -> None:
    payload: dict[str, Any] = {
        "runtime_headers": {"Authorization": "plain-token"},
        "customer": {"email": "alice@example.com"},
        "secret_ref": "secret://payments/token",
    }

    paths = sensitive_paths(payload)

    assert "$.runtime_headers.Authorization" in paths
    assert "$.customer.email" in paths
    assert "plain-token" not in str(paths)
    assert "alice@example.com" not in str(paths)
