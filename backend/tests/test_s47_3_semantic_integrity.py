"""S47.3 final semantic-integrity golden tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

import app.domain.canonical_schemas as canonical_schema_module
from app.core.errors import AppError
from app.domain.canonical_contracts import (
    sanitize_contract_payload,
    semantic_schema_fingerprint,
)
from app.domain.canonical_schemas import (
    CanonicalSchemaValidationError,
    CanonicalSchemaValidator,
)
from app.domain.change_regression import (
    ChangeConstraintTarget,
    OperationIdentity,
    SemanticCoverageFact,
    oracle_set_fingerprint,
)
from app.domain.evidence import (
    EvidenceBundle,
    EvidenceFinding,
    PythonSourceEvidenceProvider,
    SourceFileSnapshot,
    SourceSnapshot,
)
from app.domain.test_engineering import OperationContract, TestEngineeringEngine
from app.migrations_support.canonical_contract_v2 import clean_historical_contract
from app.services.change_regression import (
    _active_waiver,
    _change_label,
    _coverage_operation_matches,
    _design_missing_values,
    _design_oracle_sources,
    _ensure_safe_content,
    _execution_assets,
    _find_gap,
    _has_partial_coverage,
    _json_int,
    _json_mapping,
    _missing_test_targets,
    _operation_from_scope,
    _recommended_assets,
    _review_status,
    _scope_requirements,
    _select_current_operation,
    _semantic_requirement,
    _semantic_target,
    _target_from_scope,
    _transition,
    _waiver_is_current,
)
from app.services.impact import _openapi_source_key
from app.services.test_engineering_proposals import _validate_change_regression_target


def _identity() -> OperationIdentity:
    return OperationIdentity(
        api_definition_id="00000000-0000-0000-0000-000000000001",
        api_version=2,
        portable_operation_ref="orders.create",
        service_key="orders",
        method="POST",
        normalized_path="/orders",
        contract_fingerprint="a" * 64,
    )


def _coverage_fact(*identities: str) -> SemanticCoverageFact:
    fingerprint = oracle_set_fingerprint(identities)
    assert fingerprint is not None
    return SemanticCoverageFact(
        operation_identity=_identity(),
        request_location="body",
        field_path="quantity",
        semantic_value="1000",
        scenario_kind="number_above_max",
        expected_category="invalid_request",
        oracle_identities=identities,
        oracle_set_fingerprint=fingerprint,
        source_asset_type="workflow",
        source_asset_id="workflow-1",
    )


def test_oracle_aware_coverage_distinguishes_status_and_schema_semantics() -> None:
    schema_v1 = semantic_schema_fingerprint(
        {"type": "object", "properties": {"id": {"type": "string"}}}
    )
    schema_v2 = semantic_schema_fingerprint(
        {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        }
    )
    status_400 = _coverage_fact("status:400")
    status_422 = _coverage_fact("status:422")
    response_v1 = _coverage_fact("status:201", f"schema:{schema_v1}")
    response_v2 = _coverage_fact("status:201", f"schema:{schema_v2}")

    assert status_400.coverage_token != status_422.coverage_token
    assert response_v1.coverage_token != response_v2.coverage_token
    assert _coverage_fact("status:422").coverage_token == status_422.coverage_token
    unknown = status_422.model_copy(
        update={"oracle_identities": (), "oracle_set_fingerprint": None}
    )
    assert not unknown.complete


def test_oracle_set_fingerprint_is_order_and_duplicate_independent() -> None:
    expected = oracle_set_fingerprint(("status:201", "schema:abc"))
    assert expected == oracle_set_fingerprint(("schema:abc", "status:201", "status:201"))


def test_multi_service_operation_resolution_never_picks_first_same_route() -> None:
    auth = _identity().model_copy(
        update={
            "api_definition_id": "00000000-0000-0000-0000-000000000010",
            "portable_operation_ref": "auth.login",
            "service_key": "auth-service",
            "normalized_path": "/login",
        }
    )
    gateway = auth.model_copy(
        update={
            "api_definition_id": "00000000-0000-0000-0000-000000000011",
            "portable_operation_ref": "gateway.login",
            "service_key": "gateway-service",
            "contract_fingerprint": "b" * 64,
        }
    )
    auth_contract = OperationContract.model_validate(
        {
            "operation": "auth.login",
            "service": "auth-service",
            "method": "POST",
            "path": "/login",
        }
    )
    gateway_contract = auth_contract.model_copy(
        update={"operation": "gateway.login", "service": "gateway-service"}
    )
    current = [(auth, auth_contract), (gateway, gateway_contract)]

    selected = _select_current_operation(
        current,
        {
            "service_key": "auth-service",
            "method": "POST",
            "normalized_path": "/login",
        },
    )
    assert selected is not None and selected[1] == auth
    assert (
        _select_current_operation(
            current,
            {"method": "POST", "normalized_path": "/login"},
        )
        is None
    )


def test_openapi_contract_metadata_matches_diff_source_key() -> None:
    assert (
        _openapi_source_key("POST", "/tenants/{{tenantId}}/orders")
        == "POST /tenants/{tenantId}/orders"
    )


def test_materialization_binding_rejects_stale_version_and_fingerprint() -> None:
    frozen = _identity()
    contract = OperationContract.model_validate(
        {
            "operation": frozen.portable_operation_ref,
            "service": frozen.service_key,
            "method": frozen.method,
            "path": frozen.normalized_path,
        }
    )
    definition = SimpleNamespace(id=UUID(str(frozen.api_definition_id)))

    with pytest.raises(AppError, match="版本已变化"):
        _validate_change_regression_target(
            frozen=frozen,
            definition=definition,
            api_version=3,
            contract=contract,
        )
    with pytest.raises(AppError, match="Fingerprint 已变化"):
        _validate_change_regression_target(
            frozen=frozen,
            definition=definition,
            api_version=2,
            contract=contract,
        )


def test_python_ast_control_flow_contexts_are_conservative() -> None:
    source = """
def validate_assert(x, y):
    assert x <= 999 and y >= 1

def validate_return(x):
    return 999 > x

def validate_raise(x):
    if x >= 999:
        raise ValueError()

def validate_false(x):
    if x <= 1:
        return False
    return True

def ordinary(x):
    if x > 999:
        send_alert()

def validate_complex(x, y):
    if x > 999 and y < 1:
        raise ValueError()
"""
    bundle = PythonSourceEvidenceProvider().analyze(
        SourceSnapshot.model_validate(
            {
                "repository_url": "https://example.test/validators.git",
                "commit": "abcdef1234567",
                "allowlist_paths": ["app"],
                "files": [{"path": "app/validators.py", "language": "python", "content": source}],
            }
        )
    )
    findings = [
        finding
        for finding in bundle.findings
        if finding.kind in {"validation_constraint", "supporting_condition"}
    ]
    by_context: dict[str, list[object]] = {}
    for finding in findings:
        context = str(finding.structured_data.get("context"))
        by_context.setdefault(context, []).append(finding)

    assert any(
        finding.structured_data.get("maximum") == 999
        and finding.deterministic
        and finding.confidence == 1
        for finding in by_context["assert"]
    )
    assert any(
        finding.structured_data.get("exclusiveMaximum") == 999 and finding.deterministic
        for finding in by_context["validator-return"]
    )
    assert any(
        finding.structured_data.get("exclusiveMaximum") == 999 and finding.deterministic
        for finding in by_context["guard-raise"]
    )
    assert any(
        finding.structured_data.get("exclusiveMinimum") == 1 and finding.deterministic
        for finding in by_context["guard-return-false"]
    )
    assert all(not finding.deterministic for finding in by_context["supporting-condition"])
    assert all(
        finding.structured_data.get("requires_review") is True
        for finding in by_context["complex-guard"]
    )


def test_python_ast_unsupported_comparisons_and_nested_control_flow_remain_conservative() -> None:
    source = """
@app.options('/ignored')
def validate_unsupported(x, y):
    if x > 1:
        pass
    return x < y

def validate_chain(x):
    return 1 < x < 3

def validate_constant():
    return 1 < 2

def validate_equality(x):
    return x == 1

def validate_nested(x):
    try:
        assert x <= 9
    except ValueError:
        assert x >= 1
"""
    bundle = PythonSourceEvidenceProvider().analyze(
        SourceSnapshot(
            repository_url="https://example.test/validators.git",
            commit="abcdef1234567",
            allowlist_paths=["app"],
            files=[{"path": "app/conservative.py", "language": "python", "content": source}],
        )
    )
    constraints = [item for item in bundle.findings if item.kind == "validation_constraint"]
    assert len(constraints) == 2
    assert {item.structured_data.get("name") for item in constraints} == {"x"}


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "Bearer secret"},
        {"type": "number", "minimum": "secret"},
        {"type": "object", "required": "not-list", "properties": {}},
        {"type": "number", "multipleOf": 0},
        {"type": "string", "minLength": -1},
        {"type": "object", "properties": []},
        {"oneOf": {}},
        {"additionalProperties": []},
        {"type": "string", "format": "Bearer opaque-secret"},
    ],
)
def test_strict_canonical_schema_rejects_invalid_keyword_values(
    schema: Mapping[str, object],
) -> None:
    with pytest.raises(CanonicalSchemaValidationError):
        sanitize_contract_payload(
            {
                "operation": "invalid.schema",
                "method": "POST",
                "path": "/invalid",
                "request": dict(schema),
            }
        )


@pytest.mark.parametrize(
    ("schema", "keyword"),
    [
        ({"unknown": True}, "unknown"),
        ({"type": []}, "type"),
        ({"type": ["string", "string"]}, "type"),
        ({"type": 1}, "type"),
        ({"minimum": True}, "minimum"),
        ({"maximum": float("inf")}, "maximum"),
        ({"minimum": 2, "exclusiveMaximum": 2}, "bounds"),
        ({"minItems": True}, "minItems"),
        ({"minLength": 2, "maxLength": 1}, "maxLength"),
        ({"uniqueItems": "yes"}, "uniqueItems"),
        ({"properties": {"": {}}}, "properties"),
        ({"properties": {"value": []}}, "properties"),
        ({"required": ["value", "value"], "properties": {"value": {}}}, "required"),
        ({"required": ["missing"], "properties": {}}, "required"),
        ({"required": ["bad\nname"], "properties": {}}, "required"),
        ({"items": []}, "items"),
        ({"additionalProperties": []}, "additionalProperties"),
        ({"oneOf": [{}, "invalid"]}, "oneOf"),
        ({"enum": []}, "enum"),
        ({"enum": ["a", "a"]}, "enum"),
        ({"type": "string", "enum": [1]}, "enum"),
        ({"type": "number", "exclusiveMaximum": 1, "enum": [1]}, "enum"),
        ({"type": [1], "enum": [1]}, "type"),
        ({"enum": [[[[[[1]]]]]]}, "enum"),
        ({"enum": [list(range(51))]}, "enum"),
        ({"type": "integer", "minimum": 2, "enum": [1]}, "enum"),
        ({"enum": [{"not": "a supported enum value"}]}, "enum"),
        (
            {
                "x-flowtest-redacted-enum": {
                    "values_redacted": True,
                    "value_count": 1,
                    "value_hashes": ["legacy"],
                }
            },
            "x-flowtest-redacted-enum",
        ),
        (
            {"x-flowtest-redacted-enum": {"values_redacted": False, "value_count": 0}},
            "x-flowtest-redacted-enum",
        ),
        ({"description": "bad\ntext"}, "description"),
        ({"format": ""}, "format"),
        ({"pattern": "(a+)+"}, "pattern"),
        ({"pattern": "["}, "pattern"),
        ({"discriminator": "kind"}, "discriminator"),
        (
            {
                "discriminator": {
                    "propertyName": "",
                    "mapping": {"safe": "https://user:password@example.test/schema"},
                    "extra": True,
                }
            },
            "discriminator",
        ),
        ({"discriminator": {"propertyName": "kind", "mapping": []}}, "discriminator"),
    ],
)
def test_canonical_schema_validator_reports_bounded_keyword_issues(
    schema: Mapping[str, object], keyword: str
) -> None:
    issues = CanonicalSchemaValidator().issues(schema)
    assert keyword in {issue.keyword for issue in issues}
    assert all(issue.as_json()["reason"] for issue in issues)


def test_canonical_schema_validator_enforces_complexity_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = CanonicalSchemaValidator()

    assert validator.issues({"default": {1, 2}})[0].keyword == "$schema"
    monkeypatch.setattr(canonical_schema_module, "MAX_SCHEMA_BYTES", 1)
    assert validator.issues({"type": "string"})[0].reason.endswith("byte budget")
    monkeypatch.setattr(canonical_schema_module, "MAX_SCHEMA_BYTES", 512 * 1024)
    monkeypatch.setattr(canonical_schema_module, "MAX_SCHEMA_NODES", 1)
    assert validator.issues({"properties": {"child": {"type": "string"}}})
    monkeypatch.setattr(canonical_schema_module, "MAX_SCHEMA_NODES", 10_000)
    monkeypatch.setattr(canonical_schema_module, "MAX_SCHEMA_DEPTH", 1)
    assert validator.issues({"items": {"type": "string"}})
    monkeypatch.setattr(canonical_schema_module, "MAX_SCHEMA_DEPTH", 24)
    monkeypatch.setattr(canonical_schema_module, "MAX_PROPERTIES", 1)
    issues = validator.issues({"properties": {"a": {}, "b": {}}})
    assert any(issue.reason.endswith("property budget") for issue in issues)
    monkeypatch.setattr(canonical_schema_module, "MAX_COMPOSITION_BRANCHES", 1)
    issues = validator.issues({"allOf": [{}, {}]})
    assert any(issue.reason.endswith("branch budget") for issue in issues)


def test_canonical_schema_validator_accepts_safe_nested_contract() -> None:
    CanonicalSchemaValidator().validate(
        {
            "type": ["object", "null"],
            "properties": {
                "kind": {"type": "string", "enum": ["one", "two"], "pattern": "^[a-z]+$"}
            },
            "required": ["kind"],
            "additionalProperties": {"type": "boolean"},
            "oneOf": [{"type": "object"}],
            "not": {"type": "array"},
            "discriminator": {"propertyName": "kind", "mapping": {"one": "#/one"}},
        }
    )
    CanonicalSchemaValidator().validate({"required": ["external"]}, allow_partial_required=True)
    CanonicalSchemaValidator().validate({"discriminator": {"propertyName": "kind"}})


def test_historical_contract_cleanup_removes_enum_hashes_and_invalid_keywords() -> None:
    old = {
        "operation": "orders.create",
        "method": "POST",
        "path": "/orders",
        "request": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "x-flowtest-redacted-enum": {
                        "values_redacted": True,
                        "value_count": 2,
                        "value_hashes": ["a" * 64, "b" * 64],
                    },
                },
                "quantity": {"type": "integer", "minimum": "invalid"},
            },
        },
        "completeness": "complete",
    }
    cleaned = clean_historical_contract(old)
    serialized = str(cleaned.payload)

    assert "value_hashes" not in serialized
    assert "'minimum': 'invalid'" not in serialized
    assert cleaned.completeness in {"redacted_partial", "invalid_history_cleaned"}
    assert len(cleaned.fingerprint) == 64


@pytest.mark.parametrize(
    ("schema", "expected_valid", "expected_invalid"),
    [
        (
            {"type": "number", "exclusiveMaximum": 1.05, "multipleOf": 0.1},
            1.0,
            1.05,
        ),
        ({"type": "number", "minimum": 0.3, "multipleOf": 0.1}, 0.3, None),
        (
            {"type": "number", "exclusiveMinimum": 0.3, "multipleOf": 0.1},
            0.4,
            0.3,
        ),
    ],
)
def test_multiple_of_adjacent_values_are_decimal_aligned(
    schema: dict[str, object], expected_valid: float, expected_invalid: float | None
) -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "numbers.check",
            "method": "POST",
            "path": "/numbers",
            "request": {
                "type": "object",
                "required": ["value"],
                "properties": {"value": schema},
            },
            "responses": {"200": {"description": "ok"}, "422": {"description": "bad"}},
        }
    )
    design = TestEngineeringEngine().generate(contract=contract)
    scenarios = {
        scenario.kind: mutation.value
        for scenario in design.scenarios
        for mutation in scenario.mutations
        if mutation.path == "body.value"
    }

    assert expected_valid in scenarios.values()
    if expected_invalid is not None:
        assert expected_invalid in scenarios.values()


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "integer", "maximum": 999, "exclusiveMinimum": 999},
        {"type": "integer", "minimum": 100, "maximum": 10},
        {"type": "integer", "minimum": 1, "enum": [0, 2]},
    ],
)
def test_unsatisfiable_constraints_block_scenario_generation(schema: dict[str, object]) -> None:
    contract = OperationContract.model_validate(
        {
            "operation": "constraints.check",
            "method": "POST",
            "path": "/constraints",
            "request": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            },
            "responses": {"200": {"description": "ok"}},
        }
    )
    evidence = EvidenceBundle.model_validate(
        {
            "subject_ref": "source://constraints",
            "findings": [
                {
                    "id": "constraint-source",
                    "source_type": "source",
                    "source_ref": "source://constraints/validator.py",
                    "subject_ref": "source-symbol://constraints/value",
                    "kind": "field_constraint",
                    "path": "body.value",
                    "structured_data": {"name": "value", **schema},
                    "confidence": 1,
                    "deterministic": True,
                    "revision": "abcdef1",
                }
            ],
        }
    )
    design = TestEngineeringEngine().generate(contract=contract, additional_evidence=[evidence])
    assert not design.scenarios
    assert "constraint_unsatisfiable" in design.review_requirements


def test_change_regression_gate_helpers_keep_unknown_partial_and_waived_distinct() -> None:
    identity = _identity()
    target = ChangeConstraintTarget(
        location="body",
        field_path=("quantity",),
        constraint="maximum",
        before=100,
        after=999,
    )
    fact = _coverage_fact("status:422")
    requirement = fact.coverage_token

    assert _scope_requirements({"current_test_plan_missing_values": [requirement]}) == [requirement]
    assert _operation_from_scope({}) is None
    assert _operation_from_scope({"operation": {"invalid": True}}) is None
    assert _target_from_scope({}) is None
    assert _target_from_scope({"target": {"location": "unknown"}}) is None
    assert _semantic_requirement("malformed") == {"token": "malformed"}
    assert (
        _semantic_requirement(f"not-json|invalid_request|{'a' * 64}")["semantic_value"]
        == "not-json"
    )
    assert _find_gap({}, "missing") is None
    assert _semantic_target({}, "change") is None
    assert _semantic_target({"semantic_targets": [{"change_key": "change"}]}, "change") == {
        "change_key": "change"
    }
    assert _json_mapping(None) == {}
    assert _json_int(True) == 0
    assert _recommended_assets([fact], None, target, requirement) == []
    assert not _has_partial_coverage(
        [fact], identity, target, "malformed", {("workflow", "workflow-1")}
    )

    wrong_target = target.model_copy(update={"field_path": ("other",)})
    assert not _has_partial_coverage(
        [fact], identity, wrong_target, requirement, {("workflow", "workflow-1")}
    )
    assert _has_partial_coverage(
        [fact], identity, target, requirement, {("workflow", "workflow-1")}
    )
    portable = identity.model_copy(update={"api_definition_id": None})
    assert _coverage_operation_matches(portable, portable)

    assert _design_oracle_sources({}) == []
    assert _design_oracle_sources(
        {
            "oracles": [
                {"source_type": "contract", "source_ref": "contract://orders"},
                {"source_type": None},
            ]
        }
    ) == [{"source_type": "contract", "source_ref": "contract://orders"}]
    assert _design_missing_values({"not": "a design"}) == []

    now = datetime.now(UTC)
    perpetual = SimpleNamespace(expires_at=None)
    expiring = SimpleNamespace(expires_at=(now + timedelta(minutes=1)).replace(tzinfo=None))
    assert _waiver_is_current(perpetual, now)
    assert _waiver_is_current(expiring, now)
    waiver = SimpleNamespace(
        gap_key="gap",
        requirement_fingerprint="fingerprint",
        expires_at=now + timedelta(minutes=1),
    )
    assert (
        _active_waiver([waiver], gap_key="gap", requirement_fingerprint="fingerprint", now=now)
        is waiver
    )


def test_change_regression_scope_and_safety_helpers_reject_unsafe_or_invalid_state() -> None:
    impact = SimpleNamespace(
        run=SimpleNamespace(
            changes=[
                {
                    "key": "quantity.maximum",
                    "source_kind": "openapi",
                    "semantic_type": "maximum_changed",
                }
            ]
        )
    )
    targets = _missing_test_targets(impact, [])
    assert targets[0]["change_key"] == "quantity.maximum"
    assert _change_label({}, 3) == "3"
    selected = [{"target_type": "workflow", "target_id": "workflow-1"}]
    plan_items = [SimpleNamespace(target_type="workflow", target_id="workflow-1")]
    assert _execution_assets(selected, plan_items) == selected
    with pytest.raises(AppError, match="Secret"):
        _ensure_safe_content({"authorization": "Bearer unsafe-value"})

    items = [
        SimpleNamespace(review_status="accepted"),
        SimpleNamespace(review_status="pending"),
    ]
    assert _review_status(items) == "partially_reviewed"
    run = SimpleNamespace(status="passed")
    with pytest.raises(AppError, match="状态不允许"):
        _transition(run, "approved")


def test_evidence_contract_rejects_unsafe_budgets_paths_and_duplicate_refs() -> None:
    base = {
        "id": "finding-1",
        "source_type": "existing_test",
        "source_ref": "workflow://one",
        "subject_ref": "operation://orders",
        "kind": "semantic_coverage",
        "path": "body.quantity",
        "structured_data": {},
        "confidence": 1,
        "deterministic": True,
        "revision": "v1",
    }
    finding = EvidenceFinding.model_validate(base)
    assert finding.as_ref().semantic_role == "coverage"
    assert (
        EvidenceFinding.model_validate({**base, "id": "runtime", "source_type": "runtime"})
        .as_ref()
        .semantic_role
        == "observed"
    )
    assert (
        EvidenceFinding.model_validate(
            {
                **base,
                "id": "profile",
                "source_type": "data_profile",
                "structured_data": {"minimum": 1, "observed_minimum": 1},
            }
        )
        .as_ref()
        .semantic_role
        == "mixed"
    )
    assert (
        EvidenceFinding.model_validate({**base, "id": "support", "source_type": "workflow"})
        .as_ref()
        .semantic_role
        == "supporting"
    )

    with pytest.raises(ValueError, match="schema version"):
        EvidenceBundle(subject_ref="operation://orders", schema_version="unsupported")
    with pytest.raises(ValueError, match="ids must be unique"):
        EvidenceBundle(subject_ref="operation://orders", findings=[finding, finding])
    with pytest.raises(ValueError, match="finding budget"):
        EvidenceBundle(
            subject_ref="operation://orders",
            findings=[finding],
            budget={"max_findings": 1, "max_bytes": 1024, "truncated": False},
        ).model_copy(
            update={"findings": [finding, finding.model_copy(update={"id": "finding-2"})]}
        ).validate_budget_and_refs()
    with pytest.raises(ValueError, match="byte budget"):
        EvidenceBundle(
            subject_ref="operation://orders",
            findings=[finding],
            budget={"max_findings": 2, "max_bytes": 1024, "truncated": False},
            warnings=["x" * 1_100],
        )

    with pytest.raises(ValueError, match="repository-relative"):
        SourceFileSnapshot(path="/absolute.py", language="python", content="")
    with pytest.raises(ValueError, match=r"only accepts \.py"):
        SourceFileSnapshot(path="app/validator.txt", language="python", content="")
    with pytest.raises(ValueError, match="outside the allowlist"):
        SourceSnapshot(
            repository_url="https://example.test/repository.git",
            commit="abcdef1",
            allowlist_paths=["app"],
            files=[{"path": "tests/outside.py", "language": "python", "content": ""}],
        )
    syntax = PythonSourceEvidenceProvider().analyze(
        SourceSnapshot(
            repository_url="https://example.test/repository.git",
            commit="abcdef1",
            allowlist_paths=["app"],
            files=[{"path": "app/broken.py", "language": "python", "content": "if"}],
        )
    )
    assert syntax.warnings == ["无法解析 app/broken.py"]


def test_canonical_sensitive_value_scan_handles_nested_arrays_and_url_identity() -> None:
    from app.domain.canonical_contracts import contains_sensitive_contract_value

    assert contains_sensitive_contract_value([{"safe": "value"}, "https://user:pass@example.test"])
    assert not contains_sensitive_contract_value([1, False, None])
