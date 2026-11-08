"""Characterize the declared denial Schema needed to detect synthetic response leakage."""

import pytest

from app.domain.test_design_lowering import scenario_oracles
from app.domain.test_engineering import GenerationPolicy, OperationContract, TestEngineeringEngine


def test_declared_auth_denial_schema_is_required_before_any_bad_target_run() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "badtargets.auth",
            "method": "GET",
            "path": "/synthetic-protected",
            "auth": {"required": True, "kind": "bearer"},
            "responses": {
                "200": {"schema": {"type": "object"}},
                "403": {
                    "schema": {
                        "type": "object",
                        "required": ["actual", "code", "value"],
                        "properties": {
                            "actual": {"const": 0},
                            "code": {"const": 403},
                            "value": {"type": "null"},
                        },
                    }
                },
            },
        }
    )
    design = TestEngineeringEngine().generate(
        contract=contract,
        policy=GenerationPolicy(
            include_negative=True,
            include_auth=True,
            include_data_constraints=False,
            pairwise_enabled=False,
        ),
    )
    scenario = next(item for item in design.scenarios if item.kind == "auth_missing")
    selected = scenario_oracles(design, scenario)
    assert any(
        oracle.id == "oracle_response_schema_403" and oracle.kind == "schema" for oracle in selected
    )
    assert next(oracle for oracle in selected if oracle.kind == "status").expected == 403


@pytest.mark.parametrize("status", [401, 403])
def test_declared_auth_denial_schema_matches_only_its_exact_status(status: int) -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "auth.denial",
            "method": "GET",
            "path": "/synthetic-protected",
            "auth": {"required": True, "kind": "bearer"},
            "responses": {
                "200": {"schema": {"type": "object"}},
                str(status): {
                    "schema": {"type": "object", "properties": {"code": {"const": status}}}
                },
            },
        }
    )
    design = TestEngineeringEngine().generate(contract=contract)
    auth = next(s for s in design.scenarios if s.kind == "auth_missing")
    happy = next(s for s in design.scenarios if s.kind == "happy_path")
    selected = next(o for o in design.oracles if o.id == f"oracle_response_schema_{status}")
    assert selected.applies_to == [auth.id]
    assert happy.id not in selected.applies_to
    assert next(o for o in scenario_oracles(design, auth) if o.kind == "status").expected == status


def test_declared_invalid_request_422_schema_binds_actual_generated_missing_input() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "validation.denial",
            "method": "POST",
            "path": "/synthetic-validation",
            "request": {
                "type": "object",
                "required": ["quantity"],
                "properties": {"quantity": {"type": "integer"}},
            },
            "responses": {
                "200": {"schema": {"type": "object"}},
                "422": {"schema": {"type": "object", "properties": {"code": {"const": 422}}}},
            },
        }
    )
    design = TestEngineeringEngine().generate(contract=contract)
    negative = [s for s in design.scenarios if s.expected_category == "invalid_request"]
    assert negative
    schema = next(o for o in design.oracles if o.id == "oracle_response_schema_422")
    assert set(schema.applies_to) == {s.id for s in negative}
    assert all(
        next(o for o in scenario_oracles(design, s) if o.kind == "status").expected == 422
        for s in negative
    )


def test_unknown_status_never_supplies_an_auth_schema_oracle() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "auth.unknown",
            "method": "GET",
            "path": "/synthetic-protected",
            "auth": {"required": True, "kind": "bearer"},
            "responses": {
                "200": {"schema": {"type": "object"}},
                "418": {"schema": {"type": "object"}},
            },
        }
    )
    design = TestEngineeringEngine().generate(contract=contract)
    assert next(o for o in design.oracles if o.id == "oracle_response_schema_418").applies_to == []
    auth = next(s for s in design.scenarios if s.kind == "auth_missing")
    assert all(auth.id not in o.applies_to for o in design.oracles if o.kind == "schema")


@pytest.mark.parametrize("mutation", ["review", "nondeterministic", "ambiguous", "non_success"])
def test_schema_binding_requires_one_deterministic_concrete_status(mutation: str) -> None:
    from app.domain.test_engineering import _schema_scenarios

    contract = OperationContract.model_validate(
        {
            "operation": "auth.guarded",
            "method": "GET",
            "path": "/synthetic-protected",
            "auth": {"required": True, "kind": "bearer"},
            "responses": {"200": {}, "403": {"schema": {"type": "object"}}},
        }
    )
    design = TestEngineeringEngine().generate(contract=contract)
    auth = next(s for s in design.scenarios if s.kind == "auth_missing")
    status = next(o for o in design.oracles if o.kind == "status" and auth.id in o.applies_to)
    if mutation == "review":
        candidates = [status.model_copy(update={"requires_review": True})]
    elif mutation == "nondeterministic":
        candidates = [status.model_copy(update={"deterministic": False})]
    elif mutation == "non_success":
        candidates = [status.model_copy(update={"operator": "non_success", "expected": None})]
    else:
        candidates = [status, status.model_copy(update={"id": "duplicate_status"})]
    assert _schema_scenarios("403", [auth], candidates) == []
