from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError

from app.domain.integration_plans import (
    IntegrationPlan,
    PlanDatabasePredicate,
    PlanDatabaseRead,
    PlanDataRecipe,
    PlanOracle,
    PlanOracleValueSource,
    PlanStep,
    compile_integration_plan,
    integration_plan_fingerprint,
    seal_integration_plan,
    validate_integration_plan,
)
from app.engine.contracts import NodeStatus, WorkflowDefinition, WorkflowNode
from app.engine.control_nodes import execute_control_node
from app.engine.scheduler import ExecutionContext, WorkflowScheduler

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "v6_golden" / "login-create-query.integration-plan-v1.json"
)


class _OutputExecutor:
    def __init__(self, outputs: dict[str, JsonValue]) -> None:
        self._outputs = outputs

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        if node.id in self._outputs:
            return self._outputs[node.id]
        return await execute_control_node(node, context)


@pytest.mark.asyncio
async def test_cross_api_assert_compares_two_runtime_node_outputs() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node("start", "start", {}),
                _node("create", "api", _api_config()),
                _node("query", "api", _api_config()),
                _node(
                    "assert-id",
                    "assert",
                    {
                        "source_node_id": "query",
                        "expression": "body.id",
                        "operator": "equals",
                        "expected_source_node_id": "create",
                        "expected_expression": "body.id",
                    },
                ),
                _node("end", "end", {}),
            ],
            "edges": [
                _edge("start", "create"),
                _edge("create", "query"),
                _edge("query", "assert-id"),
                _edge("assert-id", "end"),
            ],
        }
    )

    result = await WorkflowScheduler(
        _OutputExecutor(
            {
                "create": {"body": {"id": "order-53"}},
                "query": {"body": {"id": "order-53"}},
            }
        )
    ).run(definition)

    assertion = next(record for record in result.records if record.node_id == "assert-id")
    assert result.status == "passed"
    assert assertion.status is NodeStatus.PASSED
    assert assertion.output == {
        "passed": True,
        "actual": "order-53",
        "expected": "order-53",
        "operator": "equals",
        "source_node_id": "query",
        "expression": "body.id",
        "expected_source_node_id": "create",
        "expected_expression": "body.id",
    }


@pytest.mark.asyncio
async def test_synthetic_recipe_materializes_a_new_value_for_each_run() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "nodes": [
                _node(
                    "start",
                    "start",
                    {"synthetic_variables": {"order.external_id": "uuid"}},
                ),
                _node("end", "end", {}),
            ],
            "edges": [_edge("start", "end")],
        }
    )

    first = await WorkflowScheduler(_OutputExecutor({})).run(definition)
    second = await WorkflowScheduler(_OutputExecutor({})).run(definition)
    first_value = first.context["resolved_variables"]["order.external_id"]
    second_value = second.context["resolved_variables"]["order.external_id"]

    assert UUID(str(first_value))
    assert UUID(str(second_value))
    assert first_value != second_value

    plan = _golden_plan()
    recipe = PlanDataRecipe(
        id="synthetic-order-id",
        kind="synthetic",
        name="Synthetic order ID",
        source_ref="context://s53/data/synthetic-order-id",
        variable_name="order.external_id",
        generator="uuid",
        evidence_refs=["context://s53/data/synthetic-order-id"],
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "data_recipes": [recipe],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    compilation = compile_integration_plan(changed)

    assert compilation.importable is True
    assert compilation.flow_spec is not None
    start = next(node for node in compilation.flow_spec.nodes if node.kind == "start")
    assert start.config == {"synthetic_variables": {"order.external_id": "uuid"}}


def test_low_confidence_or_non_deterministic_oracle_requires_review() -> None:
    common = {
        "id": "query-create-id",
        "step_id": "orders-query",
        "kind": "cross_api",
        "expression": "body.id",
        "operator": "equals",
        "expected_source": {
            "step_id": "orders-create",
            "expression": "body.id",
        },
        "source_ref": "context://s53/oracle/create-query-id",
        "applies_to": ["orders-create", "orders-query"],
        "evidence_refs": ["context://s53/oracle/create-query-id"],
    }

    with pytest.raises(ValidationError, match="requires_review"):
        PlanOracle.model_validate(
            {**common, "confidence": 0.79, "deterministic": True, "requires_review": False}
        )
    with pytest.raises(ValidationError, match="requires_review"):
        PlanOracle.model_validate(
            {**common, "confidence": 1, "deterministic": False, "requires_review": False}
        )
    with pytest.raises(ValidationError, match="literal expected"):
        PlanOracle.model_validate(
            {**common, "confidence": 1, "deterministic": True, "expected": "fixed-id"}
        )


@pytest.mark.parametrize(
    "strength",
    [
        {"deterministic": False, "requires_review": True},
        {"requires_review": True},
        {"confidence": 0.9},
    ],
)
def test_v1_recipe_strength_fields_require_v2(strength: dict[str, object]) -> None:
    plan = _golden_plan()
    safe_recipe = PlanDataRecipe(
        id="legacy-runtime-input",
        kind="runtime",
        name="Legacy runtime input",
        evidence_refs=["context://s50/data/runtime-input"],
    )
    sealed = seal_integration_plan(
        plan.model_copy(update={"data_recipes": [safe_recipe], "plan_fingerprint": "0" * 64})
    )
    tampered = sealed.model_copy(update={"data_recipes": [safe_recipe.model_copy(update=strength)]})

    assert integration_plan_fingerprint(tampered) == sealed.plan_fingerprint
    assert "S53_PLAN_VERSION_REQUIRED" in {
        item.code for item in validate_integration_plan(tampered).diagnostics
    }
    assert compile_integration_plan(tampered).importable is False


def test_side_effecting_setup_recipe_requires_cleanup_and_secret_is_reference_only() -> None:
    with pytest.raises(ValidationError, match="cleanup"):
        PlanDataRecipe(
            id="create-order",
            kind="setup_api",
            name="Create order",
            source_ref="contract://orders/create",
            source_step_id="orders-create",
            side_effecting=True,
            evidence_refs=["contract://orders/create"],
        )

    secret = PlanDataRecipe(
        id="login-secret",
        kind="secret_reference",
        name="login.password",
        source_ref="secret://login/password",
        secret_ref="secret://login/password",
        evidence_refs=["environment://test/secret/login-password"],
    )
    dumped = secret.model_dump(mode="json")
    assert dumped["secret_ref"] == "secret://login/password"
    assert "password-value" not in json.dumps(dumped)

    with pytest.raises(ValidationError, match="PII"):
        PlanDataRecipe(
            id="unsafe-record",
            kind="existing_safe_record",
            name="customer.email",
            value="person@example.com",
            source_ref="user-confirmed://safe-record/53",
            evidence_refs=["user-confirmed://safe-record/53"],
        )


def test_structured_db_read_and_cross_system_oracles_compile_without_raw_sql_input() -> None:
    plan = _golden_plan()
    database_read = PlanDatabaseRead(
        id="orders-db-read",
        name="Read created order",
        credential_id=UUID("00000000-0000-0000-0000-000000000053"),
        dialect="postgresql",
        table="public.orders",
        columns=["id", "status", "amount"],
        predicates=[
            PlanDatabasePredicate(
                column="id",
                parameter="order_id",
                variable_name="orders-create-id",
            )
        ],
        source_ref="database://orders/schema/revision/53",
        deterministic=True,
        requires_review=False,
        confidence=1,
        applies_to=["orders-create", "orders-query"],
        evidence_refs=["database://orders/schema/revision/53"],
    )
    db_step = PlanStep(
        id="orders-db-read",
        kind="db_read",
        name="Read created order",
        db_read_ref=database_read.id,
        evidence_refs=database_read.evidence_refs,
    )
    cross_api = PlanOracle(
        id="query-create-id",
        step_id="orders-query",
        kind="cross_api",
        expression="body.id",
        expected_source=PlanOracleValueSource(
            step_id="orders-create",
            expression="body.id",
        ),
        confidence=1,
        deterministic=True,
        requires_review=False,
        source_ref="context://s53/oracle/create-query-id",
        applies_to=["orders-create", "orders-query"],
        evidence_refs=["context://s53/oracle/create-query-id"],
    )
    row_exists = PlanOracle(
        id="db-row-exists",
        step_id="orders-db-read",
        kind="db_read",
        expression="rows[0]",
        operator="exists",
        confidence=1,
        deterministic=True,
        requires_review=False,
        source_ref="database://orders/schema/revision/53",
        applies_to=["orders-db-read"],
        evidence_refs=["database://orders/schema/revision/53"],
    )
    db_matches_query = PlanOracle(
        id="db-query-id",
        step_id="orders-db-read",
        kind="db_read",
        expression="rows[0].id",
        expected_source=PlanOracleValueSource(
            step_id="orders-query",
            expression="body.id",
        ),
        confidence=1,
        deterministic=True,
        requires_review=False,
        source_ref="context://s53/oracle/query-db-id",
        applies_to=["orders-query", "orders-db-read"],
        evidence_refs=[
            "context://s53/oracle/query-db-id",
            "database://orders/schema/revision/53",
        ],
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "steps": [*plan.steps, db_step],
                "database_reads": [database_read],
                "oracles": [*plan.oracles, cross_api, row_exists, db_matches_query],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    result = compile_integration_plan(changed)

    assert result.importable is True
    assert result.flow_spec is not None
    sql_node = next(node for node in result.flow_spec.nodes if node.kind == "sql")
    assert sql_node.config == {
        "credential_id": "00000000-0000-0000-0000-000000000053",
        "query": (
            'SELECT "id", "status", "amount" FROM "public"."orders" WHERE "id" = :order_id LIMIT 2'
        ),
        "parameters": {"order_id": "{{orders-create-id}}"},
        "timeout_seconds": 30,
    }
    cross_assert = next(
        node for node in result.flow_spec.nodes if node.id == "assert-query-create-id"
    )
    assert cross_assert.config["expected_source_node_id"] == "orders-create"
    assert cross_assert.config["expected_expression"] == "body.id"
    db_assert = next(node for node in result.flow_spec.nodes if node.id == "assert-db-query-id")
    assert db_assert.config["source_node_id"] == "orders-db-read"
    assert db_assert.config["expected_source_node_id"] == "orders-query"
    assert all("raw_sql" not in node.config for node in result.flow_spec.nodes)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlanDatabaseRead.model_validate(
            {
                **database_read.model_dump(mode="json"),
                "query": "DELETE FROM orders",
            }
        )


def test_sensitive_dynamic_oracle_source_is_a_design_blocker() -> None:
    plan = _golden_plan()
    oracle = PlanOracle(
        id="compare-token",
        step_id="orders-query",
        kind="cross_api",
        expression="body.token",
        expected_source=PlanOracleValueSource(
            step_id="orders-create",
            expression="body.token",
        ),
        confidence=1,
        source_ref="context://s53/oracle/token",
        applies_to=["orders-create", "orders-query"],
        evidence_refs=["context://s53/oracle/token"],
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "oracles": [*plan.oracles, oracle],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    validation = validate_integration_plan(changed)

    assert {item.code for item in validation.diagnostics} >= {"SENSITIVE_ORACLE_SOURCE_FORBIDDEN"}


def test_database_observation_recipe_is_design_only_blocker() -> None:
    plan = _golden_plan()
    recipe = PlanDataRecipe(
        id="observed-order",
        kind="database_observation",
        name="Observed order shape",
        source_ref="database://orders/observation/revision/53",
        deterministic=True,
        requires_review=False,
        confidence=1,
        evidence_refs=["database://orders/observation/revision/53"],
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "data_recipes": [recipe],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    result = compile_integration_plan(changed)

    assert result.flow_spec is None
    assert {item.code for item in result.diagnostics} >= {"DESIGN_ONLY_DATA_RECIPE"}


def test_database_read_input_must_be_captured_by_an_earlier_step() -> None:
    plan = _golden_plan()
    database_read = _database_read()
    db_step = PlanStep(
        id=database_read.id,
        kind="db_read",
        name=database_read.name,
        db_read_ref=database_read.id,
        evidence_refs=database_read.evidence_refs,
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "steps": [plan.steps[0], db_step, *plan.steps[1:]],
                "database_reads": [database_read],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    validation = validate_integration_plan(changed)

    assert {item.code for item in validation.diagnostics} >= {
        "DATABASE_READ_VARIABLE_ORDER_INVALID"
    }


def test_cross_api_expected_source_must_be_an_earlier_step() -> None:
    plan = _golden_plan()
    oracle = PlanOracle(
        id="create-query-id-backwards",
        step_id="orders-create",
        kind="cross_api",
        expression="body.id",
        expected_source=PlanOracleValueSource(
            step_id="orders-query",
            expression="body.id",
        ),
        confidence=1,
        source_ref="context://s53/oracle/backwards",
        applies_to=["orders-create", "orders-query"],
        evidence_refs=["context://s53/oracle/backwards"],
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "oracles": [*plan.oracles, oracle],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    validation = validate_integration_plan(changed)

    assert {item.code for item in validation.diagnostics} >= {
        "ORACLE_EXPECTED_SOURCE_ORDER_INVALID"
    }


def test_conflicting_oracle_expectations_require_review() -> None:
    plan = _golden_plan()
    conflict = PlanOracle(
        id="orders-query-conflicting-status",
        step_id="orders-query",
        kind="status",
        expression="status_code",
        expected=201,
        confidence=1,
        source_ref="user-confirmed://s53/orders-query-status",
        applies_to=["orders-query"],
        evidence_refs=["user-confirmed://s53/orders-query-status"],
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "oracles": [*plan.oracles, conflict],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    validation = validate_integration_plan(changed)

    assert validation.requires_review is True
    assert {item.code for item in validation.diagnostics} >= {"ORACLE_CONFLICT_REVIEW_REQUIRED"}


def test_previous_step_recipe_must_match_the_captured_source() -> None:
    plan = _golden_plan()
    recipe = PlanDataRecipe(
        id="captured-order-id",
        kind="previous_step",
        name="Captured order ID",
        source_ref="context://s53/data/captured-order-id",
        source_step_id="auth-login",
        expression="body.user_id",
        variable_name="orders-create-id",
        applies_to=["orders-query"],
        evidence_refs=["context://s53/data/captured-order-id"],
    )
    changed = seal_integration_plan(
        plan.model_copy(
            update={
                "schema_version": "flowtest-integration-plan-v2",
                "fingerprint_version": "flowtest-integration-plan-fingerprint-v2",
                "data_recipes": [recipe],
                "plan_fingerprint": "0" * 64,
            }
        )
    )

    validation = validate_integration_plan(changed)

    assert {item.code for item in validation.diagnostics} >= {
        "PREVIOUS_STEP_RECIPE_SOURCE_MISMATCH"
    }

    corrected = seal_integration_plan(
        changed.model_copy(
            update={
                "data_recipes": [
                    recipe.model_copy(
                        update={"source_step_id": "orders-create", "expression": "body.id"}
                    )
                ],
                "plan_fingerprint": "0" * 64,
            }
        )
    )
    corrected_codes = {item.code for item in validate_integration_plan(corrected).diagnostics}
    assert "PREVIOUS_STEP_RECIPE_SOURCE_MISMATCH" not in corrected_codes


def _golden_plan() -> IntegrationPlan:
    return IntegrationPlan.model_validate(json.loads(_FIXTURE.read_text()))


def _database_read() -> PlanDatabaseRead:
    return PlanDatabaseRead(
        id="orders-db-read",
        name="Read created order",
        credential_id=UUID("00000000-0000-0000-0000-000000000053"),
        dialect="postgresql",
        table="public.orders",
        columns=["id"],
        predicates=[
            PlanDatabasePredicate(
                column="id",
                parameter="order_id",
                variable_name="orders-create-id",
            )
        ],
        source_ref="database://orders/schema/revision/53",
        applies_to=["orders-create", "orders-query"],
        evidence_refs=["database://orders/schema/revision/53"],
    )


def _node(identifier: str, kind: str, config: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "id": identifier,
        "type": kind,
        "name": identifier,
        "position": {"x": 0, "y": 0},
        "config": config,
    }


def _edge(source: str, target: str) -> dict[str, JsonValue]:
    return {"id": f"{source}-{target}", "source": source, "target": target}


def _api_config() -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue],
        {
            "api_definition_id": "00000000-0000-0000-0000-000000000053",
        },
    )
