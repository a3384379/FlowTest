"""Freeze existing REST lowering semantics before sharing the implementation."""

from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.domain.flow_spec import flow_spec_to_workflow_definition, workflow_definition_to_flow_spec
from app.domain.test_design import OracleSpec, ScenarioCandidate
from app.domain.test_design_lowering import request_overrides as _request_overrides
from app.services.test_engineering_proposals import _scenario_workflow


def _scenario() -> ScenarioCandidate:
    return ScenarioCandidate.model_validate(
        {
            "id": "negative",
            "kind": "invalid_request",
            "title": "无效请求",
            "expected_category": "invalid_request",
            "negative": True,
            "request": {
                "query_parameters": {"zero": 0, "false": False, "empty": "", "null": None},
                "headers": {"X-Marker": "fixture"},
                "cookies": {"marker": "fixture"},
                "body": {"zero": 0, "false": False, "empty": "", "null": None},
                "auth_disabled": True,
            },
            "mutations": [
                {"path": "header.X-Required", "location": "header", "operation": "omit"},
                {"path": "query.required", "location": "query", "operation": "omit"},
                {"path": "cookie.required", "location": "cookie", "operation": "omit"},
            ],
        }
    )


def test_negative_request_and_oracles_survive_existing_flowspec_round_trip() -> None:
    scenario = _scenario()
    oracles = [
        OracleSpec(
            id="status",
            kind="status",
            expression="status_code",
            expected=422,
            confidence=1,
            applies_to=[scenario.id],
        ),
        OracleSpec(
            id="schema",
            kind="schema",
            expression="body",
            expected={"type": "object"},
            confidence=1,
            applies_to=[scenario.id],
        ),
        *[
            OracleSpec(
                id=f"value_{index}",
                kind="expression",
                expression=f"body.{name}",
                expected=value,
                confidence=1,
                applies_to=[scenario.id],
            )
            for index, (name, value) in enumerate(scenario.request.body.items())
        ],
    ]
    original = _scenario_workflow(uuid4(), 3, scenario, 422, oracles, "blue")
    restored = flow_spec_to_workflow_definition(workflow_definition_to_flow_spec(original))
    assert {node.id: node.model_dump(mode="json") for node in restored.nodes} == {
        node.id: node.model_dump(mode="json") for node in original.nodes
    }
    assert {edge.id: edge.model_dump(mode="json") for edge in restored.edges} == {
        edge.id: edge.model_dump(mode="json") for edge in original.edges
    }
    request = next(node for node in restored.nodes if node.id == "request")
    assert request.config["expected_statuses"] == [422]
    assert request.config["api_version"] == 3
    overrides = request.config["request_overrides"]
    assert overrides["auth_mode"] == "disabled"
    assert overrides["suppressed_headers"] == ["X-Required"]
    assert overrides["suppressed_query_parameters"] == ["required"]
    assert overrides["suppressed_cookies"] == ["required"]
    assert [item["value"] for item in overrides["query_parameters"]] == ["0", "false", "", "null"]
    assert overrides["body"]["value"] == {"zero": 0, "false": False, "empty": "", "null": None}
    assert [
        node.config["expected"]
        for node in sorted(restored.nodes, key=lambda node: node.id)
        if node.id.startswith("assert_expression_")
    ] == [0, False, "", None]


def test_existing_lowering_does_not_distinguish_null_body_from_absent_body() -> None:
    scenario = _scenario()
    absent = scenario.model_copy(
        update={"request": scenario.request.model_copy(update={"body": None})}
    )
    assert "body" not in _request_overrides(absent)


@pytest.mark.parametrize("review", [False, True])
def test_existing_lowering_rejects_unrepresentable_scenarios(review: bool) -> None:
    scenario = _scenario().model_copy(update={"requires_review": review})
    if not review:
        scenario = ScenarioCandidate.model_validate(
            {
                **scenario.model_dump(mode="json"),
                "mutations": [{"path": "path.id", "location": "path", "operation": "omit"}],
            }
        )
    with pytest.raises(AppError) as error:
        _scenario_workflow(uuid4(), 1, scenario, 422, [], None)
    assert error.value.code == "TEST_ENGINEERING_SCENARIO_NOT_MATERIALIZABLE"
