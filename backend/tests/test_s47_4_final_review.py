"""S47.4 final-review semantic integrity golden tests."""

from __future__ import annotations

from app.domain.change_regression import (
    ChangeConstraintTarget,
    OperationIdentity,
    SemanticCoverageFact,
    oracle_set_fingerprint,
    same_operation_semantics,
    semantic_coverage_tokens,
)
from app.domain.evidence import PythonSourceEvidenceProvider, SourceSnapshot
from app.services.change_regression import (
    _change_item_binding,
    _coverage_identity_mismatch_status,
    _workflow_assert_reachability,
    _workflow_oracle_semantics,
)


def _identity(**updates: object) -> OperationIdentity:
    values: dict[str, object] = {
        "api_definition_id": "00000000-0000-0000-0000-000000000001",
        "api_version": 1,
        "portable_operation_ref": "orders.create",
        "service_key": "orders",
        "method": "POST",
        "normalized_path": "/orders",
        "contract_fingerprint": "a" * 64,
    }
    values.update(updates)
    return OperationIdentity.model_validate(values)


def test_instance_operation_coverage_requires_version_and_contract_identity() -> None:
    version_one = _identity()

    assert not same_operation_semantics(version_one, _identity(api_version=2))
    assert not same_operation_semantics(
        version_one,
        _identity(contract_fingerprint="b" * 64),
    )
    assert same_operation_semantics(version_one, _identity())


def test_portable_operation_coverage_requires_full_portable_semantics() -> None:
    source = _identity(api_definition_id=None, api_version=None)
    equivalent = _identity(
        api_definition_id="00000000-0000-0000-0000-000000000002",
        api_version=3,
    )

    assert same_operation_semantics(source, equivalent)
    assert not same_operation_semantics(
        source,
        equivalent.model_copy(update={"service_key": "billing"}),
    )
    assert not same_operation_semantics(
        source,
        equivalent.model_copy(update={"contract_fingerprint": "b" * 64}),
    )
    assert not same_operation_semantics(
        source,
        equivalent.model_copy(update={"portable_operation_ref": "orders.replace"}),
    )


def test_operation_coverage_key_freezes_version_and_fingerprint() -> None:
    version_one = _identity()
    version_two = _identity(api_version=2)
    changed_contract = _identity(contract_fingerprint="b" * 64)

    assert version_one.semantic_prefix != version_two.semantic_prefix
    assert version_one.semantic_prefix != changed_contract.semantic_prefix
    assert "v=1" in version_one.semantic_prefix
    assert f"contract={'a' * 64}" in version_one.semantic_prefix


def test_coverage_diagnostics_distinguish_version_and_contract_mismatch() -> None:
    oracle_fingerprint = oracle_set_fingerprint(["status:200"])
    fact = SemanticCoverageFact(
        operation_identity=_identity(),
        request_location="body",
        field_path="quantity",
        semantic_value="100",
        scenario_kind="number_at_max",
        expected_category="success",
        oracle_identities=("status:200",),
        oracle_set_fingerprint=oracle_fingerprint,
        source_asset_type="workflow",
        source_asset_id="workflow-v1",
        source_asset_version=1,
        workflow_version=1,
    )
    target = ChangeConstraintTarget(
        location="body",
        field_path=("quantity",),
        constraint="maximum",
        before=99,
        after=100,
    )

    assert (
        _coverage_identity_mismatch_status(
            [fact],
            _identity(api_version=2),
            target,
            fact.coverage_token,
            None,
        )
        == "VERSION_MISMATCH"
    )
    assert (
        _coverage_identity_mismatch_status(
            [fact],
            _identity(contract_fingerprint="b" * 64),
            target,
            fact.coverage_token,
            None,
        )
        == "CONTRACT_MISMATCH"
    )


def test_coverage_asset_scope_requires_pinned_asset_and_workflow_versions() -> None:
    target = ChangeConstraintTarget(
        location="body",
        field_path=("quantity",),
        constraint="maximum",
        before=99,
        after=100,
    )
    fact_v1 = SemanticCoverageFact(
        operation_identity=_identity(),
        request_location="body",
        field_path="quantity",
        semantic_value="100",
        scenario_kind="number_at_max",
        expected_category="success",
        oracle_identities=("status:200",),
        oracle_set_fingerprint=oracle_set_fingerprint(("status:200",)),
        source_asset_type="workflow",
        source_asset_id="workflow-pinned",
        source_asset_version=1,
        workflow_version=1,
    )
    fact_v2 = fact_v1.model_copy(
        update={
            "semantic_value": "999",
            "source_asset_version": 2,
            "workflow_version": 2,
        }
    )

    assert semantic_coverage_tokens(
        [fact_v1, fact_v2],
        _identity(),
        target,
        asset_scope={("workflow", "workflow-pinned", 1, 1)},
    ) == {fact_v1.coverage_token}
    assert semantic_coverage_tokens(
        [fact_v1, fact_v2],
        _identity(),
        target,
        asset_scope={("workflow", "workflow-pinned", 2, 2)},
    ) == {fact_v2.coverage_token}


def test_nested_source_constraints_are_conditional_review_evidence() -> None:
    source = """
def validate_top(x):
    assert x <= 999

def validate_conditional(mode, x):
    if mode == "special":
        assert x <= 10

def validate_try(x):
    try:
        assert x <= 9
    except ValueError:
        assert x >= 1

def validate_nested_guard(mode, x):
    if mode == "special":
        if x > 10:
            raise ValueError()

def validate_loop(values):
    for item in values:
        assert item <= 10

def validate_match(mode, x):
    match mode:
        case "special":
            assert x <= 10

def validate_with(lock, x):
    with lock:
        assert x <= 10
"""
    bundle = PythonSourceEvidenceProvider().analyze(
        SourceSnapshot.model_validate(
            {
                "repository_url": "https://example.test/conditional.git",
                "commit": "abcdef1234567",
                "allowlist_paths": ["app"],
                "files": [{"path": "app/conditional.py", "language": "python", "content": source}],
            }
        )
    )
    top_level = [
        finding for finding in bundle.findings if finding.structured_data.get("context") == "assert"
    ]
    conditional = [
        finding for finding in bundle.findings if finding.structured_data.get("conditional") is True
    ]

    assert len(top_level) == 1
    assert top_level[0].kind == "validation_constraint"
    assert top_level[0].deterministic and top_level[0].confidence == 1
    assert {finding.structured_data.get("context") for finding in conditional} >= {
        "conditional-assert",
        "conditional-guard-raise",
    }
    assert {finding.structured_data.get("branch_kind") for finding in conditional} >= {
        "if-body",
        "try-body",
        "except-body",
        "loop-body",
        "match-case",
        "with-body",
    }
    assert all(finding.kind == "supporting_condition" for finding in conditional)
    assert all(not finding.deterministic for finding in conditional)
    assert all(finding.confidence <= 0.5 for finding in conditional)
    assert all(finding.structured_data.get("requires_review") is True for finding in conditional)
    assert not any(
        finding.kind == "validation_constraint" and finding.structured_data.get("maximum") == 10
        for finding in bundle.findings
    )


def _workflow_graph(edges: list[tuple[str, str]]) -> dict[str, object]:
    node_ids = {node_id for edge in edges for node_id in edge}
    node_types = {
        "request": "api",
        "assert": "assert",
        "end": "end",
        "end-alt": "end",
    }
    return {
        "nodes": [
            {
                "id": node_id,
                "type": node_types.get(node_id, "condition"),
                "config": (
                    {
                        "source_node_id": "request",
                        "expression": "status_code",
                        "operator": "equals",
                        "expected": 422,
                    }
                    if node_id == "assert"
                    else {}
                ),
            }
            for node_id in sorted(node_ids)
        ],
        "edges": [
            {"id": f"{source}-{target}", "source": source, "target": target}
            for source, target in edges
        ],
    }


def test_workflow_assert_reachability_is_post_dominator_aware() -> None:
    linear = _workflow_graph([("request", "assert"), ("assert", "end")])
    disconnected = _workflow_graph([("request", "end"), ("assert", "end-alt")])
    conditional = _workflow_graph(
        [("request", "assert"), ("assert", "end"), ("request", "end-alt")]
    )
    post_join = _workflow_graph(
        [
            ("request", "left"),
            ("request", "right"),
            ("left", "join"),
            ("right", "join"),
            ("join", "assert"),
            ("assert", "end"),
        ]
    )
    cycle = _workflow_graph(
        [
            ("request", "loop"),
            ("loop", "request"),
            ("loop", "assert"),
            ("assert", "end"),
        ]
    )

    assert _workflow_assert_reachability(linear, "request", "assert") == ("unconditional_assert")
    assert _workflow_assert_reachability(disconnected, "request", "assert") == (
        "disconnected_assert"
    )
    assert _workflow_assert_reachability(conditional, "request", "assert") == ("conditional_assert")
    assert _workflow_assert_reachability(post_join, "request", "assert") == ("unconditional_assert")
    assert _workflow_assert_reachability(cycle, "request", "assert") == "unknown_graph"


def test_only_unconditional_workflow_asserts_form_coverage_oracles() -> None:
    linear = _workflow_graph([("request", "assert"), ("assert", "end")])
    conditional = _workflow_graph(
        [("request", "assert"), ("assert", "end"), ("request", "end-alt")]
    )

    category, identities, conflict, reachability = _workflow_oracle_semantics(
        linear,
        "request",
        {},
    )
    assert category == "invalid_request"
    assert identities == ("status:422",)
    assert not conflict
    assert reachability == ("unconditional_assert",)

    category, identities, conflict, reachability = _workflow_oracle_semantics(
        conditional,
        "request",
        {},
    )
    assert category == "unknown"
    assert identities == ()
    assert not conflict
    assert reachability == ("conditional_assert",)


def test_operation_selection_binding_does_not_depend_on_array_index() -> None:
    bindings = [
        {"change_key": "first", "item_id": "item-1", "position": 1},
        {"change_key": "target", "item_id": "item-3", "position": 3},
        {"change_key": "last", "item_id": "item-7", "position": 7},
    ]

    selected = _change_item_binding({"item_bindings": bindings}, [], "target")

    assert selected == bindings[1]
    assert selected["item_id"] == "item-3"
