from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.affected_flows import (
    OperationSelector,
    affected_knowledge_operations,
    match_operation,
)
from app.domain.change_regression import OperationIdentity
from app.domain.test_contexts import (
    ContextKnowledgeEdge,
    ContextKnowledgeFact,
    ContextKnowledgeNode,
    ContextKnowledgeSnapshot,
)


def test_affected_flow_golden_identity_cases() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/v6_golden/affected-flows.json").read_text()
    )
    assert fixture["schema_version"] == "flowtest-affected-flows-golden-v1"
    identity = OperationIdentity.model_validate(fixture["identity"])
    for case in fixture["cases"]:
        assert (
            match_operation(OperationSelector.model_validate(case["selector"]), identity)
            == case["expected"]
        ), case["name"]


def _identity(**changes: Any) -> OperationIdentity:
    return OperationIdentity.model_validate(
        {
            "api_definition_id": "api-orders",
            "api_version": 1,
            "portable_operation_ref": "orders.read",
            "service_key": "orders",
            "method": "GET",
            "normalized_path": "/orders/{}",
            "contract_fingerprint": "a" * 64,
            **changes,
        }
    )


def _node(node_id: str, kind: str = "entity", **facts: str) -> ContextKnowledgeNode:
    return ContextKnowledgeNode(
        id=node_id,
        kind=kind,
        label="PRIVATE_LABEL_DO_NOT_RETURN",
        facts=[ContextKnowledgeFact(name=name, value=value) for name, value in facts.items()],
    )


def _operation(**facts: str) -> ContextKnowledgeNode:
    return _node("op", "operation", method="GET", path="/orders/{id}", **facts)


def _graph(
    nodes: list[ContextKnowledgeNode], edges: list[tuple[str, str, str]]
) -> ContextKnowledgeSnapshot:
    return ContextKnowledgeSnapshot(
        nodes=nodes,
        edges=[ContextKnowledgeEdge(source=a, target=b, relation=r) for a, b, r in edges],
    )


def test_instance_match_and_route_only_candidate_are_distinct() -> None:
    assert (
        match_operation(
            OperationSelector(api_definition_id="api-orders", api_version=1), _identity()
        )
        == "instance"
    )
    assert (
        match_operation(
            OperationSelector(method="GET", normalized_path="/orders/{{orderId}}"), _identity()
        )
        == "candidate"
    )
    assert match_operation(OperationSelector(), _identity()) is None
    assert match_operation(OperationSelector(api_definition_id="api-orders"), _identity()) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_definition_id", "api-inventory"),
        ("api_version", 2),
        ("service_key", "inventory"),
        ("method", "POST"),
        ("normalized_path", "/inventory/{}"),
        ("portable_operation_ref", "inventory.read"),
        ("contract_fingerprints", ("b" * 64,)),
    ],
)
def test_known_conflict_never_falls_back_to_matching_route(field: str, value: Any) -> None:
    selector = OperationSelector.model_validate(
        {
            "api_definition_id": "api-orders",
            "api_version": 1,
            "method": "GET",
            "normalized_path": "/orders/{}",
            field: value,
        }
    )
    assert match_operation(selector, _identity()) is None


@pytest.mark.parametrize("fingerprint", ["a" * 64, "b" * 64])
def test_baseline_and_current_contracts_can_identify_affected_portable_operation(
    fingerprint: str,
) -> None:
    selector = OperationSelector(
        service_key="orders",
        portable_operation_ref="orders.read",
        method="GET",
        normalized_path="/orders/{orderId}",
        contract_fingerprints=("b" * 64, "a" * 64),
    )
    assert match_operation(selector, _identity(contract_fingerprint=fingerprint)) == "portable"
    assert selector.contract_fingerprints == ("a" * 64, "b" * 64)
    assert match_operation(selector, _identity(contract_fingerprint="c" * 64)) is None


def test_fingerprint_contract_is_validated_and_deduplicated() -> None:
    assert OperationSelector(contract_fingerprints=("a" * 64,) * 2).contract_fingerprints == (
        "a" * 64,
    )
    with pytest.raises(ValidationError):
        OperationSelector(contract_fingerprints=("not-a-fingerprint",))


@pytest.mark.parametrize(
    ("relation", "heuristic"),
    [
        ("contains", False),
        ("uses_repository", False),
        ("maps_entity", False),
        ("may_use_repository", True),
        ("may_map_entity", True),
        ("custom_link", True),
    ],
)
def test_relation_strength_never_grants_patch_permission(relation: str, heuristic: bool) -> None:
    edges = [("op", "entity", relation)]
    before = _graph([_operation(), _node("entity", state="before")], edges)
    after = _graph([_operation(), _node("entity", state="PRIVATE_FACT_DO_NOT_RETURN")], edges)
    result = affected_knowledge_operations(before, after)
    assert len(result.impacts) == 2
    assert all(item.heuristic == heuristic for item in result.impacts)
    assert all(item.changed_node_ids == ("entity",) for item in result.impacts)
    assert all(item.requires_review and not item.automatic_patch_allowed for item in result.impacts)
    assert not result.automatic_patch_allowed
    assert "PRIVATE_LABEL" not in result.model_dump_json()
    assert "PRIVATE_FACT" not in result.model_dump_json()


def test_removed_edges_and_nodes_remain_impact_evidence() -> None:
    before = _graph([_operation(), _node("entity")], [("op", "entity", "returns")])
    after = _graph([_operation()], [])
    result = affected_knowledge_operations(before, after)
    assert any(
        item.revision_side == "before" and "entity" in item.changed_node_ids
        for item in result.impacts
    )


def test_paths_are_not_spliced_across_revisions() -> None:
    nodes = [_operation(), _node("entity"), _node("table")]
    before = _graph(nodes, [("op", "entity", "contains")])
    after = _graph(nodes, [("entity", "table", "maps_to")])
    result = affected_knowledge_operations(before, after)
    assert any("entity" in item.changed_node_ids for item in result.impacts)
    assert all("table" not in item.changed_node_ids for item in result.impacts)


@pytest.mark.parametrize(
    "facts",
    [
        [("service_key", "orders"), ("service_key", "inventory")],
        [("path", "/different/{}")],
        [("api_version", "invalid")],
    ],
)
def test_ambiguous_or_invalid_identity_is_reported_without_overwriting(
    facts: list[tuple[str, str]],
) -> None:
    operation = _operation()
    operation.facts.extend(ContextKnowledgeFact(name=name, value=value) for name, value in facts)
    graph = _graph([operation], [])
    result = affected_knowledge_operations(ContextKnowledgeSnapshot(), graph)
    assert result.ambiguous_operation_node_ids == ["op"]
    assert result.impacts == []


def test_equivalent_path_aliases_are_not_ambiguous() -> None:
    operation = _operation(normalized_path="/orders/{}")
    graph = _graph([operation], [])
    result = affected_knowledge_operations(ContextKnowledgeSnapshot(), graph)
    assert result.ambiguous_operation_node_ids == []
    assert result.impacts[0].selector.normalized_path == "/orders/{}"


def test_review_flag_downgrades_an_explicit_path() -> None:
    operation = _operation(requires_review="true")
    edges = [("op", "entity", "contains")]
    result = affected_knowledge_operations(
        _graph([operation, _node("entity", state="before")], edges),
        _graph([operation, _node("entity", state="after")], edges),
    )
    assert all(item.heuristic for item in result.impacts)


def test_maximum_size_cycle_is_bounded_and_order_independent() -> None:
    nodes = [_operation(), *(_node(f"n{i}") for i in range(499))]
    edges = [(nodes[i].id, nodes[(i + 1) % 500].id, "contains") for i in range(500)]
    before = _graph(nodes, edges)
    after = _graph([*nodes[:-1], _node("n498", state="changed")], edges)
    expected = affected_knowledge_operations(before, after)
    assert len(expected.impacts) == 2
    assert all(item.changed_node_ids == ("n498",) for item in expected.impacts)
    assert expected == affected_knowledge_operations(
        _graph(list(reversed(before.nodes)), list(reversed(edges))),
        _graph(list(reversed(after.nodes)), list(reversed(edges))),
    )
    assert affected_knowledge_operations(before, before).impacts == []
