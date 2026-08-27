from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.core.errors import AppError
from app.domain.evidence import (
    DataProfile,
    EvidenceBundle,
    EvidenceFinding,
    PythonSourceEvidenceProvider,
    SourceSnapshot,
    data_profile_evidence,
)
from app.domain.test_design import OracleSpec, fingerprint_design, sensitive_paths
from app.domain.test_engineering import (
    GenerationPolicy,
    OperationContract,
    TestEngineeringEngine,
    _constraint_conflicts,
    _mutation_location,
    _pattern_invalid_value,
    _pattern_sample,
    _profile_schema_type,
    _route_conflicts,
)
from app.schemas.test_engineering import (
    TestEngineeringGenerateRequest as GenerateRequestSchema,
)
from app.services.test_engineering_proposals import _scenario_workflow, _selected_scenarios


def _orders_contract() -> OperationContract:
    return OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "auth": {"required": True},
            "request": {
                "type": "object",
                "required": ["quantity", "type"],
                "properties": {
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 999,
                    },
                    "type": {
                        "type": "string",
                        "enum": ["NORMAL", "PRIORITY"],
                    },
                    "remark": {"type": "string", "maxLength": 20},
                },
            },
            "responses": {
                "200": {"description": "success"},
                "400": {"description": "invalid request"},
                "401": {"description": "unauthorized"},
            },
        }
    )


def test_golden_engine_generates_design_without_caller_authored_design() -> None:
    engine = TestEngineeringEngine()

    design = engine.generate(contract=_orders_contract())
    repeated = engine.generate(contract=_orders_contract())

    assert fingerprint_design(design) == fingerprint_design(repeated)
    semantics = {
        (scenario.kind, mutation.path, str(mutation.value))
        for scenario in design.scenarios
        for mutation in scenario.mutations
    }
    assert any(scenario.kind == "happy_path" for scenario in design.scenarios)
    assert {
        ("required_omitted", "body.quantity", "None"),
        ("required_null", "body.quantity", "None"),
        ("number_below_min", "body.quantity", "0"),
        ("number_at_min", "body.quantity", "1"),
        ("number_below_max", "body.quantity", "998"),
        ("number_at_max", "body.quantity", "999"),
        ("number_above_max", "body.quantity", "1000"),
        ("invalid_type", "body.quantity", "invalid"),
        ("enum_value", "body.type", "NORMAL"),
        ("enum_value", "body.type", "PRIORITY"),
        ("enum_invalid", "body.type", "__invalid__"),
        ("required_omitted", "body.type", "None"),
        ("optional_omitted", "body.remark", "None"),
        ("string_at_max_length", "body.remark", "x" * 20),
        ("string_above_max_length", "body.remark", "x" * 21),
        ("auth_missing", "auth", "None"),
    } <= semantics
    coverage = {
        (entry.target_ref, entry.requirement): entry.covered for entry in design.coverage.entries
    }
    assert coverage[("orders.create.body.quantity", "minimum")]
    assert coverage[("orders.create.body.quantity", "below minimum")]
    assert coverage[("orders.create.body.quantity", "maximum")]
    assert coverage[("orders.create.body.quantity", "above maximum")]
    assert coverage[("orders.create.body.type", "invalid enum")]
    assert coverage[("orders.create.body.remark", "maxLength")]
    assert coverage[("orders.create.body.remark", "above maxLength")]
    assert coverage[("orders.create.auth", "auth missing")]
    status_oracles = {oracle.expected for oracle in design.oracles if oracle.kind == "status"}
    assert {200, 400, 401} <= status_oracles
    assert design.evidence_refs
    assert sensitive_paths(design.model_dump(mode="json")) == ()


def test_generation_budget_is_stable_and_keeps_explicit_gaps() -> None:
    policy = GenerationPolicy(max_scenarios=5, pairwise_enabled=True)

    design = TestEngineeringEngine().generate(contract=_orders_contract(), policy=policy)

    assert len(design.scenarios) == 5
    assert design.warnings
    assert design.coverage.gaps
    assert all(
        gap.recommended_scenario_kind
        for gap in design.coverage.gaps
        if gap.dimension != "response_status"
    )


def test_additional_evidence_has_aggregate_input_budget() -> None:
    bundles = [
        EvidenceBundle.model_validate(
            {
                "subject_ref": f"source://{index}",
                "findings": [
                    {
                        "id": f"finding-{index}",
                        "source_type": "source",
                        "source_ref": f"source://{index}",
                        "subject_ref": "operation://orders.create",
                        "kind": "documentation",
                        "structured_data": {"description": "x" * 450_000},
                        "confidence": 0.5,
                        "deterministic": False,
                        "revision": "1",
                    }
                ],
            }
        )
        for index in range(5)
    ]

    with pytest.raises(ValidationError, match="additional evidence byte budget exceeded"):
        GenerateRequestSchema.model_validate(
            {"api_definition_id": str(uuid4()), "additional_evidence": bundles}
        )


def test_python_source_provider_is_ast_only_bounded_and_referenced() -> None:
    snapshot = SourceSnapshot.model_validate(
        {
            "repository_url": "https://example.test/acme/orders.git",
            "commit": "abcdef1234567890",
            "allowlist_paths": ["app"],
            "files": [
                {
                    "path": "app/api.py",
                    "language": "python",
                    "content": """
from enum import Enum

class OrderType(Enum):
    NORMAL = "NORMAL"
    PRIORITY = "PRIORITY"

@router.post("/orders")
async def create_order():
    raise ValueError("invalid")
""",
                }
            ],
        }
    )

    evidence = PythonSourceEvidenceProvider().analyze(snapshot)

    assert {finding.kind for finding in evidence.findings} >= {"route", "enum", "error_branch"}
    assert all(finding.revision == snapshot.commit for finding in evidence.findings)
    assert "raise ValueError" not in str(evidence.model_dump(mode="json"))


def test_source_enum_and_validation_constraints_change_generated_design() -> None:
    snapshot = SourceSnapshot.model_validate(
        {
            "repository_url": "https://example.test/acme/orders.git",
            "commit": "abcdef1234567890",
            "allowlist_paths": ["app"],
            "files": [
                {
                    "path": "app/orders.py",
                    "language": "python",
                    "content": """
from enum import Enum

class OrderType(Enum):
    NORMAL = "NORMAL"
    PRIORITY = "PRIORITY"

def validate(quantity):
    return quantity <= 999
""",
                }
            ],
        }
    )
    evidence = PythonSourceEvidenceProvider().analyze(snapshot)
    contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "request": {
                "type": "object",
                "properties": {
                    "quantity": {"type": "integer"},
                    "type": {"type": "string"},
                },
            },
            "responses": {"201": {"description": "created"}},
        }
    )

    design = TestEngineeringEngine().generate(contract=contract, additional_evidence=[evidence])
    values = {
        (scenario.kind, mutation.path, mutation.value)
        for scenario in design.scenarios
        for mutation in scenario.mutations
    }

    assert ("number_above_max", "body.quantity", 1000) in values
    assert ("enum_value", "body.type", "PRIORITY") in values
    assert any(
        finding.id in scenario.evidence_refs
        for finding in evidence.findings
        for scenario in design.scenarios
    )


def test_auth_missing_design_materializes_by_explicitly_disabling_auth() -> None:
    design = TestEngineeringEngine().generate(contract=_orders_contract())
    auth_scenario = next(
        scenario for scenario in design.scenarios if scenario.kind == "auth_missing"
    )

    assert _selected_scenarios(design, [auth_scenario.id]) == [auth_scenario.id]
    workflow = _scenario_workflow(
        uuid4(),
        3,
        auth_scenario,
        401,
        [oracle for oracle in design.oracles if auth_scenario.id in oracle.applies_to],
        "default",
    )
    request = next(node for node in workflow.nodes if node.id == "request")
    assert request.config["api_version"] == 3
    assert request.config["request_overrides"]["auth_mode"] == "disabled"
    assert "auth_disabled" not in request.config["request_overrides"]


def test_json_path_oracle_materializes_as_real_assert_node() -> None:
    design = TestEngineeringEngine().generate(contract=_orders_contract())
    scenario = next(item for item in design.scenarios if item.kind == "happy_path")
    oracle = OracleSpec(
        id="oracle_response_code",
        kind="json_path",
        expression="body.code",
        operator="equals",
        expected=0,
        confidence=1,
        applies_to=[scenario.id],
    )

    workflow = _scenario_workflow(uuid4(), 1, scenario, 200, [*design.oracles, oracle], None)
    assert_node = next(node for node in workflow.nodes if node.id == "assert_expression_1")

    assert assert_node.config["expression"] == "body.code"
    assert assert_node.config["expected"] == 0


def test_source_enum_and_repository_identity_redact_values() -> None:
    snapshot = SourceSnapshot.model_validate(
        {
            "repository_url": "https://example.test/acme/orders.git",
            "commit": "abcdef1234567890",
            "allowlist_paths": ["app"],
            "files": [
                {
                    "path": "app/settings.py",
                    "language": "python",
                    "content": """
from enum import Enum

class UnsafeValues(Enum):
    ACCESS = "aaaabbbb.ccccdddd.eeeeffff"
    CONTACT = "user@example.test"
    HEADER = "Bearer opaque-test-value"
""",
                }
            ],
        }
    )

    finding = next(
        item
        for item in PythonSourceEvidenceProvider().analyze(snapshot).findings
        if item.kind == "enum"
    )

    assert finding.structured_data["values_redacted"] is True
    assert finding.structured_data["value_count"] == 3
    assert "value_hashes" not in finding.structured_data
    assert "user@" not in str(finding.model_dump(mode="json"))
    for repository_url in (
        "https://user:password@example.test/repo.git",
        "https://example.test/repo.git?token=redacted",
    ):
        with pytest.raises(ValidationError, match="credentials, query, or fragment"):
            SourceSnapshot.model_validate(
                {
                    "repository_url": repository_url,
                    "commit": "abcdef1",
                    "allowlist_paths": ["app"],
                    "files": [],
                }
            )


def test_generation_covers_nullable_format_nested_and_array_constraints() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "profiles.create",
            "method": "POST",
            "path": "/profiles",
            "request": {
                "type": "object",
                "required": ["email", "tags", "profile"],
                "properties": {
                    "email": {
                        "type": ["string", "null"],
                        "format": "email",
                        "minLength": 3,
                    },
                    "tags": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "uniqueItems": True,
                    },
                    "profile": {
                        "type": "object",
                        "required": ["display_name"],
                        "properties": {"display_name": {"type": "string", "minLength": 1}},
                    },
                },
            },
            "responses": {"201": {"description": "created"}},
        }
    )

    design = TestEngineeringEngine().generate(contract=contract)
    kinds = {scenario.kind for scenario in design.scenarios}

    assert {
        "required_null",
        "format_valid",
        "format_invalid",
        "array_below_min",
        "array_at_min",
        "array_at_max",
        "array_above_max",
        "array_duplicate",
    } <= kinds
    assert any(
        mutation.path == "body.profile.display_name"
        for scenario in design.scenarios
        for mutation in scenario.mutations
    )
    happy = next(scenario for scenario in design.scenarios if scenario.kind == "happy_path")
    Draft202012Validator(contract.body_schema).validate(happy.request.body)


def test_evidence_rejects_raw_sensitive_values_and_requires_masked_profiles() -> None:
    profile = DataProfile.model_validate(
        {
            "source_ref": "db://profiles/public",
            "revision": "schema-47",
            "entity": "profiles",
            "columns": [
                {
                    "name": "email",
                    "data_type": "varchar",
                    "nullable": False,
                    "unique": True,
                    "masked_example": "a***@example.test",
                }
            ],
        }
    )

    bundle = data_profile_evidence(profile)

    assert bundle.findings[0].structured_data["masked_example"] == "a***@example.test"
    assert bundle.refs[0].source_ref == "db://profiles/public"
    with pytest.raises(ValidationError, match="must be masked"):
        DataProfile.model_validate(
            {
                "source_ref": "db://profiles/public",
                "revision": "schema-47",
                "entity": "profiles",
                "columns": [
                    {
                        "name": "email",
                        "data_type": "varchar",
                        "nullable": False,
                        "masked_example": "alice@example.test",
                    }
                ],
            }
        )
    finding = EvidenceFinding.model_validate(
        {
            "id": "evidence-secret",
            "source_type": "source",
            "source_ref": "source://repo/file.py",
            "subject_ref": "source-symbol://file.py:1",
            "kind": "assignment",
            "structured_data": {
                "nested": [{"authorization": "Bearer secret"}],
                "values": ["alice@example.test", "aaaabbbb.ccccdddd.eeeeffff"],
            },
            "confidence": 1,
            "deterministic": True,
            "revision": "abcdef1",
        }
    )
    assert finding.structured_data == {
        "nested": [{"authorization": "***"}],
        "values": ["***", "***"],
    }
    assert finding.sensitive is True


def test_observed_data_profile_does_not_create_normative_boundaries() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "request": {
                "type": "object",
                "required": ["quantity"],
                "properties": {"quantity": {"type": "integer"}},
            },
            "responses": {"201": {"description": "created"}},
        }
    )
    evidence = data_profile_evidence(
        DataProfile.model_validate(
            {
                "source_ref": "db://orders/schema",
                "revision": "42",
                "entity": "orders",
                "columns": [
                    {
                        "name": "quantity",
                        "data_type": "integer",
                        "nullable": False,
                        "minimum": 1,
                        "maximum": 10,
                    }
                ],
            }
        )
    )

    design = TestEngineeringEngine().generate(contract=contract, additional_evidence=[evidence])
    assert not any(
        scenario.kind in {"number_at_max", "number_above_max"}
        and scenario.mutations[0].path == "body.quantity"
        for scenario in design.scenarios
    )
    assert "evidence_conflict" not in design.review_requirements


def test_explicit_data_profile_constraint_creates_boundary_with_exact_provenance() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "request": {
                "type": "object",
                "required": ["quantity"],
                "properties": {"quantity": {"type": "integer"}},
            },
            "responses": {"201": {"description": "created"}},
        }
    )
    evidence = data_profile_evidence(
        DataProfile.model_validate(
            {
                "source_ref": "db://orders/schema",
                "revision": "43",
                "entity": "orders",
                "columns": [
                    {
                        "name": "quantity",
                        "data_type": "integer",
                        "nullable": False,
                        "constraint_maximum": 10,
                    }
                ],
            }
        )
    )

    design = TestEngineeringEngine().generate(contract=contract, additional_evidence=[evidence])
    boundary = next(
        scenario
        for scenario in design.scenarios
        if scenario.kind == "number_above_max" and scenario.mutations[0].path == "body.quantity"
    )
    assert boundary.mutations[0].value == 11
    assert evidence.findings[0].id in boundary.evidence_refs
    assert len(boundary.evidence_refs) == 2
    assert boundary.evidence_refs != list(design.evidence_refs)


def test_evidence_conflict_marks_scenarios_review_only_and_blocks_materialization() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "request": {
                "type": "object",
                "required": ["quantity"],
                "properties": {"quantity": {"type": "integer", "maximum": 100}},
            },
            "responses": {"201": {"description": "created"}},
        }
    )
    evidence = data_profile_evidence(
        DataProfile.model_validate(
            {
                "source_ref": "db://orders/schema",
                "revision": "43",
                "entity": "orders",
                "columns": [
                    {
                        "name": "quantity",
                        "data_type": "integer",
                        "nullable": False,
                        "constraint_maximum": 999,
                    }
                ],
            }
        )
    )

    design = TestEngineeringEngine().generate(contract=contract, additional_evidence=[evidence])
    conflict = next(
        scenario
        for scenario in design.scenarios
        if scenario.mutations
        and scenario.mutations[0].path == "body.quantity"
        and "evidence-conflict" in scenario.tags
    )

    assert "evidence_conflict" in design.review_requirements
    assert conflict.requires_review is True
    assert conflict.deterministic is False
    assert evidence.findings[0].id in conflict.evidence_refs
    with pytest.raises(AppError, match="未解决证据冲突"):
        _scenario_workflow(
            uuid4(),
            1,
            conflict,
            201,
            [oracle for oracle in design.oracles if conflict.id in oracle.applies_to],
            None,
        )


def test_source_evidence_reports_syntax_errors_without_execution() -> None:
    snapshot = SourceSnapshot.model_validate(
        {
            "repository_url": "https://example.test/acme/orders.git",
            "commit": "abcdef1234567890",
            "allowlist_paths": ["app"],
            "files": [
                {
                    "path": "app/broken.py",
                    "language": "python",
                    "content": "def broken(:\n    pass",
                }
            ],
        }
    )

    bundle = PythonSourceEvidenceProvider().analyze(snapshot)

    assert bundle.findings == []
    assert bundle.warnings == ["无法解析 app/broken.py"]


def test_generation_helper_edges_are_explicit_and_reviewable() -> None:
    assert _pattern_sample(r"^\d+$") == "1"
    assert _pattern_sample(r"^ORDER-1$") == "ORDER-1"
    assert _pattern_sample(r"^(ORDER|RETURN)$") is None
    assert _pattern_invalid_value("[") is None
    with pytest.raises(ValueError, match="unsupported mutation location"):
        _mutation_location("unknown.value")

    assert _profile_schema_type("bigint") == "integer"
    assert _profile_schema_type("decimal") == "number"
    assert _profile_schema_type("boolean") == "boolean"
    assert _profile_schema_type("jsonb") == "object"
    assert _profile_schema_type("text[] array") == "array"
    assert _profile_schema_type("varchar") == "string"
    assert _constraint_conflicts("required", True, False) is True
    assert _constraint_conflicts("enum", ["A"], ["A", "B"]) is True
    assert _constraint_conflicts("minimum", 10, 1) is True
    assert _constraint_conflicts("maximum", 10, 20) is True
    assert _constraint_conflicts("pattern", "a", "b") is True

    route_evidence = EvidenceBundle.model_validate(
        {
            "subject_ref": "source://orders",
            "findings": [
                {
                    "id": "route-mismatch",
                    "source_type": "source",
                    "source_ref": "source://orders/routes.py",
                    "subject_ref": "source-symbol://orders/routes.py:create",
                    "kind": "route",
                    "structured_data": {"method": "GET", "path": "/users/{user_id}"},
                    "confidence": 1,
                    "deterministic": True,
                    "revision": "abcdef1",
                },
                {
                    "id": "unrelated",
                    "source_type": "source",
                    "source_ref": "source://orders/routes.py",
                    "subject_ref": "source-symbol://orders/routes.py:helper",
                    "kind": "documentation",
                    "confidence": 0.5,
                    "deterministic": False,
                    "revision": "abcdef1",
                },
            ],
        }
    )
    assert _route_conflicts(_orders_contract(), route_evidence) == [
        "源代码路由方法 GET 与 Contract POST 冲突",
        "源代码路由路径 /users/{user_id} 与 Contract /orders 冲突",
    ]
