import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.domain.evidence import (
    DataProfile,
    EvidenceFinding,
    PythonSourceEvidenceProvider,
    SourceSnapshot,
    data_profile_evidence,
)
from app.domain.test_design import fingerprint_design, sensitive_paths
from app.domain.test_engineering import (
    GenerationPolicy,
    OperationContract,
    TestEngineeringEngine,
)
from app.services.test_engineering_proposals import _selected_scenarios


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


def test_auth_missing_design_cannot_be_falsely_materialized() -> None:
    design = TestEngineeringEngine().generate(contract=_orders_contract())
    auth_scenario = next(
        scenario for scenario in design.scenarios if scenario.kind == "auth_missing"
    )

    with pytest.raises(AppError) as raised:
        _selected_scenarios(design, [auth_scenario.id])

    assert raised.value.code == "TEST_ENGINEERING_SCENARIO_NOT_MATERIALIZABLE"


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
    with pytest.raises(ValidationError, match="contains sensitive value"):
        EvidenceFinding.model_validate(
            {
                "id": "evidence-secret",
                "source_type": "source",
                "source_ref": "source://repo/file.py",
                "subject_ref": "source-symbol://file.py:1",
                "kind": "assignment",
                "structured_data": {"nested": [{"authorization": "Bearer secret"}]},
                "confidence": 1,
                "deterministic": True,
                "revision": "abcdef1",
            }
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
