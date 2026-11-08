"""Pure native lowering shared by reviewed materialization and read-only compilation."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from app.domain.test_design import OracleSpec, ScenarioCandidate, TestDesignDocument
from app.engine.contracts import WorkflowDefinition


class ScenarioLoweringError(Exception):
    def __init__(
        self, *, code: str, message: str, status_code: int = 422, details: object = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def expected_status(design: TestDesignDocument, scenario: ScenarioCandidate) -> int:
    matches = [
        oracle
        for oracle in design.oracles
        if oracle.kind == "status"
        and scenario.id in oracle.applies_to
        and isinstance(oracle.expected, int)
        and oracle.deterministic
        and not oracle.requires_review
        and oracle.operator == "equals"
    ]
    if len(matches) != 1:
        raise ScenarioLoweringError(
            code="TEST_ENGINEERING_ORACLE_NOT_EXECUTABLE",
            message=f"Scenario {scenario.id} 缺少唯一的确定性状态码 Oracle",
            status_code=422,
        )
    return cast(int, matches[0].expected)


def scenario_oracles(design: TestDesignDocument, scenario: ScenarioCandidate) -> list[OracleSpec]:
    result = [oracle for oracle in design.oracles if scenario.id in oracle.applies_to]
    comparison_operators = {
        "equals",
        "not_equals",
        "contains",
        "exists",
        "matches",
    }
    unsupported = [
        oracle.id
        for oracle in result
        if oracle.kind not in {"status", "schema", "json_path", "expression"}
        or (
            oracle.kind in {"json_path", "expression"}
            and oracle.operator not in comparison_operators
        )
        or oracle.requires_review
        or not oracle.deterministic
    ]
    if unsupported:
        raise ScenarioLoweringError(
            code="TEST_ENGINEERING_ORACLE_NOT_EXECUTABLE",
            message=f"Scenario {scenario.id} 包含不可执行 Oracle",
            status_code=422,
            details={"oracle_ids": sorted(unsupported)},
        )
    return result


def scenario_workflow(
    api_definition_id: UUID,
    api_version: int,
    scenario: ScenarioCandidate,
    expected_status: int,
    oracles: list[OracleSpec],
    endpoint_variant: str | None,
) -> WorkflowDefinition:
    if scenario.requires_review or not scenario.deterministic:
        raise ScenarioLoweringError(
            code="TEST_ENGINEERING_SCENARIO_NOT_MATERIALIZABLE",
            message="Scenario 包含未解决证据冲突或前置条件,仅可保留为 Design",
            status_code=422,
            details={"scenario_id": scenario.id},
        )
    if any(
        mutation.location == "path" and mutation.operation == "omit"
        for mutation in scenario.mutations
    ):
        raise ScenarioLoweringError(
            code="TEST_ENGINEERING_SCENARIO_NOT_MATERIALIZABLE",
            message="必填 path 参数 omission 无法表示为真实 HTTP 请求",
            status_code=422,
            details={"scenario_id": scenario.id, "location": "path"},
        )
    overrides = request_overrides(scenario)
    request_config: dict[str, Any] = {
        "api_definition_id": str(api_definition_id),
        "api_version": api_version,
        "expected_statuses": [expected_status],
        "request_overrides": overrides,
    }
    if endpoint_variant is not None:
        request_config["endpoint_variant"] = endpoint_variant
    nodes = [
        _workflow_node("start", "start", "Start", 0, {}),
        _workflow_node("request", "api", scenario.title, 200, request_config),
        _workflow_node(
            "assert_status",
            "assert",
            "Status Oracle",
            400,
            {
                "source_node_id": "request",
                "expression": "status_code",
                "operator": "equals",
                "expected": expected_status,
            },
        ),
    ]
    edges: list[dict[str, str]] = [
        {"id": "start-request", "source": "start", "target": "request"},
        {"id": "request-assert", "source": "request", "target": "assert_status"},
    ]
    previous = "assert_status"
    schema_oracles = [oracle for oracle in oracles if oracle.kind == "schema"]
    for index, oracle in enumerate(schema_oracles, start=1):
        node_id = f"assert_schema_{index}"
        nodes.append(
            _workflow_node(
                node_id,
                "assert",
                "Response Schema Oracle",
                400 + index * 150,
                {
                    "source_node_id": "request",
                    "expression": "body",
                    "operator": "equals",
                    "expected": oracle.expected,
                    "assertion_type": "json_schema",
                },
            )
        )
        edges.append({"id": f"{previous}-{node_id}", "source": previous, "target": node_id})
        previous = node_id
    comparison_oracles = [
        oracle for oracle in oracles if oracle.kind in {"json_path", "expression"}
    ]
    for index, oracle in enumerate(comparison_oracles, start=1):
        node_id = f"assert_expression_{index}"
        nodes.append(
            _workflow_node(
                node_id,
                "assert",
                "Response Expression Oracle",
                550 + index * 150,
                {
                    "source_node_id": "request",
                    "expression": oracle.expression,
                    "operator": oracle.operator,
                    "expected": oracle.expected,
                },
            )
        )
        edges.append({"id": f"{previous}-{node_id}", "source": previous, "target": node_id})
        previous = node_id
    nodes.append(_workflow_node("end", "end", "End", 700, {}))
    edges.append({"id": f"{previous}-end", "source": previous, "target": "end"})
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "1.0",
            "variables": {
                name: _request_value(value)
                for name, value in scenario.request.path_parameters.items()
            },
            "nodes": nodes,
            "edges": edges,
            "settings": {},
        }
    )


def request_overrides(scenario: ScenarioCandidate) -> dict[str, Any]:
    headers = {name: _request_value(value) for name, value in scenario.request.headers.items()}
    if scenario.request.cookies:
        headers["Cookie"] = "; ".join(
            f"{name}={_request_value(value)}"
            for name, value in sorted(scenario.request.cookies.items())
        )
    overrides: dict[str, Any] = {
        "query_parameters": [
            {"name": name, "value": _request_value(value), "enabled": True}
            for name, value in scenario.request.query_parameters.items()
        ],
        "headers": headers,
        "replace_headers": True,
        "auth_mode": "disabled" if scenario.request.auth_disabled else "inherit",
        "suppressed_headers": sorted(
            {
                mutation.path.split(".", 1)[1]
                for mutation in scenario.mutations
                if mutation.location == "header"
                and mutation.operation == "omit"
                and "." in mutation.path
            }
        ),
        "suppressed_query_parameters": sorted(
            {
                mutation.path.split(".", 1)[1]
                for mutation in scenario.mutations
                if mutation.location == "query"
                and mutation.operation == "omit"
                and "." in mutation.path
            }
        ),
        "suppressed_cookies": sorted(
            {
                mutation.path.split(".", 1)[1]
                for mutation in scenario.mutations
                if mutation.location == "cookie"
                and mutation.operation == "omit"
                and "." in mutation.path
            }
        ),
    }
    if scenario.request.body is not None:
        overrides["body"] = {"kind": "json", "value": scenario.request.body}
    return overrides


def _request_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _workflow_node(
    node_id: str, node_type: str, name: str, x: int, config: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": 0},
        "config": config,
    }
