"""S47.2 correctness and security golden tests."""

import json
import math
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.domain.canonical_contracts import (
    looks_sensitive_contract_value,
    sanitize_contract_payload,
)
from app.domain.change_regression import (
    ChangeConstraintTarget,
    OperationIdentity,
    SemanticCoverageFact,
    change_constraint_target,
    existing_semantic_values,
    gap_covered_values,
    missing_test_design,
    semantic_coverage_tokens,
    transition_status,
)
from app.domain.evidence import (
    EvidenceBundle,
    PythonSourceEvidenceProvider,
    SourceSnapshot,
)
from app.domain.test_design import TestDesignDocument as DesignDocument
from app.domain.test_design import sensitive_paths
from app.domain.test_engineering import (
    OperationContract,
    TestEngineeringEngine,
    fingerprint_contract,
)
from app.importers.contracts import ImportSourceType
from app.importers.openapi import parse_openapi
from app.services.api_assets import _auth_suppressions
from app.services.workflow_snapshots import (
    _combined_suppression,
    _redacted_workflow_definition,
    _request_suppression,
    _without_suppressed_headers,
)


def test_canonical_contract_redacts_nested_hints_and_sensitive_enum() -> None:
    raw = _sensitive_contract("openapi://orders", "42")

    contract = OperationContract.model_validate(raw)
    serialized = json.dumps(contract.model_dump(mode="json", by_alias=True), ensure_ascii=False)
    design = TestEngineeringEngine().generate(contract=contract)

    for value in _sensitive_values():
        assert value not in serialized
        assert value not in json.dumps(design.model_dump(mode="json"), ensure_ascii=False)
    assert contract.completeness == "redacted_partial"
    assert contract.warnings == [
        "canonical schema example/default/const hints removed",
        "sensitive canonical contract values redacted",
        "sensitive enum values removed; only value count is retained",
    ]
    enum_schema = contract.body_schema["properties"]["status"]
    assert "enum" not in enum_schema
    redacted = enum_schema["x-flowtest-redacted-enum"]
    assert redacted["value_count"] == 2
    assert redacted["values_redacted"] is True
    assert "value_hashes" not in redacted
    assert sensitive_paths(design.model_dump(mode="json")) == ()


def test_contract_fingerprint_ignores_provenance_warnings_and_removed_hints() -> None:
    first = OperationContract.model_validate(_sensitive_contract("openapi://first", "1"))
    second_raw = _sensitive_contract("openapi://second", "99")
    second_raw["warnings"] = ["different safe warning"]
    second_raw["request_body"]["schema"]["properties"]["password"]["example"] = "another-password"
    second = OperationContract.model_validate(second_raw)

    assert fingerprint_contract(first) == fingerprint_contract(second)
    changed = second.model_copy(update={"path": "/orders-v2"})
    assert fingerprint_contract(first) != fingerprint_contract(changed)


@pytest.mark.parametrize(
    "value",
    [
        "Bearer abcdefghijklmnopqrstuvwxyz123456",
        "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
        "AKIAIOSFODNN7EXAMPLE",
        "+8613800138000",
        "-----BEGIN PRIVATE KEY-----",
        "https://user:password@example.test/orders",
        "https://example.test/orders?access_token=opaque",
        "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/==",
    ],
)
def test_contract_value_detector_covers_supported_sensitive_shapes(value: str) -> None:
    assert looks_sensitive_contract_value(value)


@pytest.mark.parametrize("value", ["", "***", "secret://orders/token", "{{secret.token}}"])
def test_contract_value_detector_accepts_safe_secret_references(value: str) -> None:
    assert not looks_sensitive_contract_value(value)


def test_canonical_sanitizer_handles_generic_schema_and_invalid_fragments() -> None:
    result = sanitize_contract_payload(
        {
            "operation": "profiles.create",
            "method": "POST",
            "path": "/profiles",
            "auth": {
                "required": True,
                "kind": "api_key",
                "location": "query",
                "name": "https://user:password@example.test/key",
            },
            "parameters": [
                {
                    "name": "valid",
                    "location": "query",
                    "example": {"password": ["nested-secret"]},
                    "schema": {"type": "string", "title": "Safe title"},
                },
                {"name": 42, "location": "body", "example": "ignored"},
            ],
            "request_body": {
                "required": True,
                "content_type": "application/json",
                "schema": {
                    "type": "object",
                    "description": "user@example.test",
                    "properties": {
                        "labels": {
                            "type": "object",
                            "additionalProperties": {
                                "type": "string",
                                "not": {"const": "4111111111111111"},
                            },
                        },
                        "choice": {
                            "type": "string",
                            "minimum": 1,
                            "exclusiveMinimum": False,
                            "maximum": 10,
                            "exclusiveMaximum": True,
                            "unsupported": "ignored",
                            "enum": ["ACTIVE", "PAUSED"],
                            "discriminator": {
                                "mapping": [
                                    "safe",
                                    "https://user:password@example.test/schema",
                                    42,
                                ]
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "ok",
                    "content_type": "application/json",
                    "schema": "not-a-schema",
                }
            },
        },
        strict=False,
    )

    serialized = json.dumps(result.payload, ensure_ascii=False)
    assert "user@example.test" not in serialized
    assert "4111111111111111" not in serialized
    assert "user:password" not in serialized
    assert result.payload["auth"]["name"] is None
    assert result.payload["parameters"] == [
        {
            "name": "valid",
            "location": "query",
            "required": False,
            "schema": {"type": "string", "title": "Safe title"},
            "style": None,
            "explode": None,
            "source_ref": None,
        }
    ]
    assert result.payload["responses"]["200"]["schema"] is None
    assert result.payload["completeness"] == "redacted_partial"


def test_snapshot_suppression_helpers_remove_values_but_keep_auditable_names() -> None:
    suppression_payload = {
        "target": {
            "request_suppression": {
                "auth_mode": "disabled",
                "suppressed_header_names": ["Authorization", "X-Tenant-Id", 42],
                "suppressed_query_parameter_names": ["api_key"],
                "suppressed_cookie_names": ["auth_session"],
            }
        }
    }
    apis = {"api": suppression_payload, "invalid": "not-a-snapshot"}
    suppression = _combined_suppression(apis)

    assert suppression.auth_disabled is True
    assert suppression.headers == frozenset({"authorization", "x-tenant-id"})
    assert suppression.query_parameters == frozenset({"api_key"})
    assert suppression.cookies == frozenset({"auth_session"})
    assert _without_suppressed_headers(
        {
            "Authorization": "credential",
            "X-Tenant-Id": "tenant",
            "Cookie": "auth_session=credential; keep=safe",
            "X-Safe": "safe",
        },
        suppression,
    ) == {"X-Safe": "safe"}

    definition = {
        "nodes": [
            None,
            {"id": 1, "config": {}},
            {"id": "start", "config": {}},
            {
                "id": "api",
                "config": {
                    "request_overrides": {
                        "headers": {
                            "Authorization": "credential",
                            "X-Safe": "safe",
                        },
                        "query_parameters": [
                            {"name": "api_key", "value": "credential"},
                            {"name": "page", "value": "1"},
                            "legacy-fragment",
                        ],
                    }
                },
            },
        ]
    }
    sanitized = _redacted_workflow_definition(definition, apis)
    overrides = sanitized["nodes"][3]["config"]["request_overrides"]
    assert overrides["headers"] == {"X-Safe": "safe"}
    assert overrides["query_parameters"] == [
        {"name": "page", "value": "1"},
        "legacy-fragment",
    ]
    assert (
        definition["nodes"][3]["config"]["request_overrides"]["headers"]["Authorization"]
        == "credential"
    )
    assert _redacted_workflow_definition({"nodes": "invalid"}, apis) == {"nodes": "invalid"}
    assert _request_suppression(None).auth_disabled is False
    assert _request_suppression({"target": "invalid"}).auth_disabled is False
    assert _request_suppression({"target": {}}).auth_disabled is False


def test_unknown_auth_carrier_blocks_materialization() -> None:
    version = SimpleNamespace(
        auth_kind="none",
        auth_config={},
        canonical_contract={
            "operation": "custom.secure",
            "method": "GET",
            "path": "/secure",
            "auth": {"required": True, "kind": "other"},
            "responses": {"200": {"description": "ok"}},
        },
    )

    with pytest.raises(AppError, match="无法确定认证载体") as raised:
        _auth_suppressions(version)
    assert raised.value.code == "AUTH_SUPPRESSION_UNSUPPORTED"


@pytest.mark.parametrize(
    ("auth_kind", "auth_config", "expected"),
    [
        ("none", {}, ((), (), ())),
        ("bearer", {}, (("Authorization",), (), ())),
        ("api_key", {"name": "X-Key"}, (("Authorization", "X-Key"), (), ())),
    ],
)
def test_auth_suppression_carriers_are_explicit(
    auth_kind: str,
    auth_config: dict[str, str],
    expected: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
) -> None:
    version = SimpleNamespace(
        auth_kind=auth_kind,
        auth_config=auth_config,
        canonical_contract=None,
    )
    assert _auth_suppressions(version) == expected


def test_change_regression_helper_edges_preserve_scope_and_transition_truth() -> None:
    identity = OperationIdentity(
        api_definition_id=None,
        portable_operation_ref="orders.create",
        service_key="orders",
        method="POST",
        normalized_path="/orders",
        contract_fingerprint="a" * 64,
    )
    different_operation = identity.model_copy(
        update={
            "portable_operation_ref": "orders.create.alias",
            "contract_fingerprint": "b" * 64,
        }
    )
    target = ChangeConstraintTarget(
        location="body",
        field_path=("quantity",),
        constraint="maximum",
        before=100,
        after=999,
    )
    fact = _coverage_fact(identity, "999", "invalid_request", "status:422")
    fact = fact.model_copy(update={"operation_identity": identity, "test_plan_id": "plan-1"})

    assert identity.semantic_prefix.startswith("orders.create|v=portable|contract=")
    assert fact.target_key.endswith("|body|quantity")
    assert fact.coverage_token.startswith("999|invalid_request|")
    assert semantic_coverage_tokens([fact], identity, target) == {fact.coverage_token}
    assert (
        semantic_coverage_tokens(
            [fact.model_copy(update={"operation_identity": different_operation})],
            identity,
            target,
        )
        == set()
    )
    assert change_constraint_target({"field_path": "response.200.maximum"}) is None
    assert change_constraint_target({"field_path": "request.query.page"}) is None

    document = TestEngineeringEngine().generate(contract=_location_contract())
    coverage = existing_semantic_values([document])
    gap = {"field_path": "request.query.page.maximum", "after": 999}
    assert gap_covered_values(gap, coverage) == coverage.get("query.page", set())
    transition_status("review_required", "approved")
    with pytest.raises(ValueError, match="invalid change regression transition"):
        transition_status("passed", "running")


def test_openapi_and_swagger_contracts_sanitize_nested_combinators_and_exclusive_bounds() -> None:
    openapi_document = {
        "openapi": "3.1.0",
        "info": {"title": "Security", "version": "1"},
        "components": {
            "schemas": {
                "Credential": {
                    "type": "object",
                    "properties": {"token": {"type": "string", "default": "component-token"}},
                }
            }
        },
        "paths": {
            "/secure": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "value": {
                                            "type": "number",
                                            "exclusiveMinimum": 1.5,
                                            "exclusiveMaximum": 9.5,
                                        },
                                        "choices": {
                                            "oneOf": [
                                                {"$ref": "#/components/schemas/Credential"},
                                                {
                                                    "type": "array",
                                                    "items": {
                                                        "type": "string",
                                                        "example": "array-secret",
                                                    },
                                                },
                                            ]
                                        },
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "anyOf": [{"$ref": "#/components/schemas/Credential"}]
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    swagger_document = {
        "swagger": "2.0",
        "info": {"title": "Bounds", "version": "1"},
        "paths": {
            "/bounded": {
                "get": {
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "type": "integer",
                            "minimum": 1,
                            "exclusiveMinimum": True,
                            "maximum": 999,
                            "exclusiveMaximum": True,
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }

    openapi_contract = parse_openapi(openapi_document, ImportSourceType.OPENAPI3)[
        0
    ].canonical_contract
    swagger_contract = parse_openapi(swagger_document, ImportSourceType.SWAGGER2)[
        0
    ].canonical_contract
    assert openapi_contract is not None
    assert swagger_contract is not None
    serialized = json.dumps(openapi_contract.model_dump(mode="json"), ensure_ascii=False)
    assert "component-token" not in serialized
    assert "array-secret" not in serialized
    value_schema = openapi_contract.body_schema["properties"]["value"]
    assert value_schema["exclusiveMinimum"] == 1.5
    assert value_schema["exclusiveMaximum"] == 9.5
    limit_schema = swagger_contract.parameters[0].schema_
    assert limit_schema == {"type": "integer", "exclusiveMinimum": 1, "exclusiveMaximum": 999}


def test_exclusive_boundaries_and_source_ast_preserve_operator_semantics() -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "limits.check",
            "method": "POST",
            "path": "/limits",
            "request": {
                "type": "object",
                "required": ["upper", "lower", "ratio"],
                "properties": {
                    "upper": {"type": "integer", "exclusiveMaximum": 999},
                    "lower": {"type": "integer", "exclusiveMinimum": 1},
                    "ratio": {
                        "type": "number",
                        "exclusiveMaximum": 1.0,
                        "multipleOf": 0.1,
                    },
                },
            },
            "responses": {"200": {"description": "ok"}, "400": {"description": "bad"}},
        }
    )
    design = TestEngineeringEngine().generate(contract=contract)
    values = {
        (scenario.kind, mutation.path): mutation.value
        for scenario in design.scenarios
        for mutation in scenario.mutations
    }
    assert values[("number_below_exclusive_max", "body.upper")] == 998
    assert values[("number_at_exclusive_max", "body.upper")] == 999
    assert values[("number_at_exclusive_min", "body.lower")] == 1
    assert values[("number_above_exclusive_min", "body.lower")] == 2
    assert math.isclose(values[("number_below_exclusive_max", "body.ratio")], 0.9)
    assert values[("number_at_exclusive_max", "body.ratio")] == 1.0
    assert all(
        entry.covered for entry in design.coverage.entries if "exclusive" in entry.requirement
    )

    evidence = PythonSourceEvidenceProvider().analyze(
        SourceSnapshot.model_validate(
            {
                "repository_url": "https://example.test/limits.git",
                "commit": "abcdef1234567",
                "allowlist_paths": ["app"],
                "files": [
                    {
                        "path": "app/limits.py",
                        "language": "python",
                        "content": (
                            "def validate(a, b, c, d):\n"
                            "    return a < 999 and b <= 999 and c > 1 and d >= 1\n"
                        ),
                    }
                ],
            }
        )
    )
    comparisons = {
        str(finding.structured_data["name"]): {
            key: value
            for key, value in finding.structured_data.items()
            if key not in {"context", "requires_review"}
        }
        for finding in evidence.findings
        if finding.kind == "validation_constraint"
    }
    assert comparisons == {
        "a": {"name": "a", "exclusiveMaximum": 999},
        "b": {"name": "b", "maximum": 999},
        "c": {"name": "c", "exclusiveMinimum": 1},
        "d": {"name": "d", "minimum": 1},
    }


@pytest.mark.parametrize(
    ("constraint", "current", "candidate"),
    [
        ("maximum", 100, 50),
        ("maximum", 100, 999),
        ("minimum", 1, 5),
        ("enum", ["A", "B"], ["A"]),
        ("enum", ["A"], ["A", "B"]),
    ],
)
def test_normative_evidence_conflicts_are_symmetric_with_exact_provenance(
    constraint: str,
    current: object,
    candidate: object,
) -> None:
    schema = {"type": "string" if constraint == "enum" else "integer", constraint: current}
    contract = OperationContract.model_validate(
        {
            "operation": "orders.create",
            "method": "POST",
            "path": "/orders",
            "request": {
                "type": "object",
                "required": ["value"],
                "properties": {"value": schema},
            },
            "responses": {"200": {"description": "ok"}},
        }
    )
    source = EvidenceBundle.model_validate(
        {
            "subject_ref": "source://orders",
            "findings": [
                {
                    "id": "source-constraint",
                    "source_type": "source",
                    "source_ref": "source://orders/validator.py",
                    "subject_ref": "source-symbol://orders/value",
                    "kind": "field_constraint",
                    "path": "body.value",
                    "structured_data": {
                        "name": "value",
                        "location": "body",
                        "type": schema["type"],
                        constraint: candidate,
                    },
                    "confidence": 1,
                    "deterministic": True,
                    "revision": "abcdef1",
                }
            ],
        }
    )

    design = TestEngineeringEngine().generate(contract=contract, additional_evidence=[source])
    conflicted = [scenario for scenario in design.scenarios if "evidence-conflict" in scenario.tags]
    assert "evidence_conflict" in design.review_requirements
    assert conflicted
    assert any("source-constraint" in scenario.evidence_refs for scenario in conflicted)
    assert all(scenario.requires_review and not scenario.deterministic for scenario in conflicted)


def test_semantic_coverage_is_operation_scoped_and_requires_an_oracle() -> None:
    orders = _identity("orders", "/orders")
    inventory = _identity("inventory", "/inventory")
    target = ChangeConstraintTarget(
        location="body",
        field_path=("quantity",),
        constraint="maximum",
        before=100,
        after=999,
    )
    facts = [
        _coverage_fact(inventory, "999", "invalid_request", "status:422"),
        _coverage_fact(orders, "999", "unknown", None),
    ]

    assert semantic_coverage_tokens(facts, orders, target) == set()
    covered = _coverage_fact(orders, "999", "invalid_request", "status:422")
    facts.append(covered)
    assert semantic_coverage_tokens(facts, orders, target) == {covered.coverage_token}


@pytest.mark.parametrize(
    ("field_path", "semantic_type", "location", "scenario_kinds"),
    [
        (
            "request.query.page.maximum",
            "maximum_changed",
            "query",
            {"number_at_max", "number_above_max"},
        ),
        (
            "request.header.X-Batch-Size.maxLength",
            "maxLength_changed",
            "header",
            {"string_at_max_length", "string_above_max_length"},
        ),
        (
            "request.path.tenantId.pattern",
            "pattern_changed",
            "path",
            {"pattern_valid", "pattern_invalid"},
        ),
        (
            "request.cookie.session.enum",
            "enum_changed",
            "cookie",
            {"enum_value", "enum_invalid"},
        ),
    ],
)
def test_change_regression_targets_request_location_and_materializable_request(
    field_path: str,
    semantic_type: str,
    location: str,
    scenario_kinds: set[str],
) -> None:
    contract = _location_contract()
    target = change_constraint_target(
        {
            "field_path": field_path,
            "before": 3,
            "after": (
                999
                if semantic_type == "maximum_changed"
                else 5
                if semantic_type == "maxLength_changed"
                else r"^[A-Z]+$"
                if semantic_type == "pattern_changed"
                else ["ACTIVE", "PAUSED"]
            ),
        }
    )
    assert target is not None and target.location == location
    document = DesignDocument.model_validate(
        missing_test_design(
            gap={
                "change_key": f"location-{location}",
                "source_key": "GET /tenants/{tenantId}/orders",
                "label": f"{location} constraint changed",
                "semantic_type": semantic_type,
                "field_path": field_path,
                "before": 3,
                "after": target.after,
            },
            source_ref="openapi://location-change",
            position=1,
            current_contract=contract,
        )
    )
    selected = [scenario for scenario in document.scenarios if scenario.kind in scenario_kinds]
    assert {scenario.kind for scenario in selected} == scenario_kinds
    assert all(scenario.mutations[0].location == location for scenario in selected)
    request_field = {
        "path": "path_parameters",
        "query": "query_parameters",
        "header": "headers",
        "cookie": "cookies",
    }[location]
    assert all(getattr(scenario.request, request_field) for scenario in selected)


def _sensitive_contract(source_ref: str, revision: str) -> dict[str, object]:
    password, token, email, card, jwt = _sensitive_values()
    return {
        "operation": "orders.create",
        "method": "POST",
        "path": "/orders/{tenantId}",
        "source_ref": source_ref,
        "revision": revision,
        "parameters": [
            {
                "name": "tenantId",
                "location": "path",
                "required": True,
                "schema": {"type": "string", "example": email},
            }
        ],
        "request_body": {
            "required": True,
            "schema": {
                "type": "object",
                "properties": {
                    "password": {"type": "string", "example": password},
                    "token": {"type": "string", "default": token},
                    "card": {"type": "string", "const": card},
                    "status": {"type": "string", "enum": ["NORMAL", jwt]},
                    "nested": {
                        "type": "array",
                        "items": {
                            "anyOf": [
                                {"type": "string", "example": token},
                                {"type": "string", "default": email},
                            ]
                        },
                    },
                },
            },
        },
        "responses": {
            "200": {
                "description": "ok",
                "schema": {
                    "oneOf": [
                        {"type": "string", "example": email},
                        {"type": "string", "const": card},
                    ]
                },
            }
        },
    }


def _sensitive_values() -> tuple[str, str, str, str, str]:
    return (
        "real-password",
        "real-token-value-A1B2C3D4E5F6G7H8",
        "user@example.test",
        "4111111111111111",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123",
    )


def _identity(service: str, path: str) -> OperationIdentity:
    return OperationIdentity(
        api_definition_id=str(uuid4()),
        portable_operation_ref=f"{service}.create",
        service_key=service,
        method="POST",
        normalized_path=path,
        contract_fingerprint="a" * 64,
    )


def _coverage_fact(
    identity: OperationIdentity,
    value: str,
    category: str,
    oracle: str | None,
) -> SemanticCoverageFact:
    return SemanticCoverageFact.model_validate(
        {
            "operation_identity": identity,
            "request_location": "body",
            "field_path": "quantity",
            "semantic_value": value,
            "scenario_kind": "boundary",
            "expected_category": category,
            "oracle_identity": oracle,
            "source_asset_type": "workflow",
            "source_asset_id": str(uuid4()),
            "source_asset_version": 1,
            "workflow_version": 1,
        }
    )


def _location_contract() -> OperationContract:
    return OperationContract.model_validate(
        {
            "operation": "orders.list",
            "method": "GET",
            "path": "/tenants/{tenantId}/orders",
            "parameters": [
                {
                    "name": "page",
                    "location": "query",
                    "schema": {"type": "integer", "maximum": 999},
                },
                {
                    "name": "X-Batch-Size",
                    "location": "header",
                    "schema": {"type": "string", "maxLength": 5},
                },
                {
                    "name": "tenantId",
                    "location": "path",
                    "required": True,
                    "schema": {"type": "string", "pattern": r"^[A-Z]+$"},
                },
                {
                    "name": "session",
                    "location": "cookie",
                    "schema": {"type": "string", "enum": ["ACTIVE", "PAUSED"]},
                },
            ],
            "responses": {"200": {"description": "ok"}, "400": {"description": "bad"}},
        }
    )
