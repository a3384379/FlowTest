"""Conservative operation matching and bounded, revision-local knowledge impact."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.change_regression import OperationIdentity, same_operation_semantics
from app.domain.context_diff import diff_state_knowledge
from app.domain.test_contexts import ContextKnowledgeNode, ContextKnowledgeSnapshot

MatchStrength = Literal["instance", "portable", "candidate"]
_IDENTITY_FIELDS: Final = (
    "api_definition_id",
    "api_version",
    "service_key",
    "method",
    "normalized_path",
    "portable_operation_ref",
)
_EXPLICIT_RELATIONS: Final = frozenset(
    {
        "accepts",
        "returns",
        "contains",
        "enters",
        "invokes",
        "calls",
        "uses_repository",
        "maps_to",
        "has_field",
        "has_column",
        "handled_by",
        "produces",
        "maps_entity",
        "constrained_by",
        "allows_state",
    }
)


class OperationSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_definition_id: str | None = Field(default=None, min_length=1, max_length=160)
    api_version: int | None = Field(default=None, ge=1)
    portable_operation_ref: str | None = Field(default=None, min_length=1, max_length=240)
    service_key: str | None = Field(default=None, min_length=1, max_length=160)
    method: str | None = Field(default=None, pattern=r"^[A-Z]+$", max_length=16)
    normalized_path: str | None = Field(default=None, min_length=1, max_length=2048)
    contract_fingerprints: tuple[str, ...] = Field(default=(), max_length=2)

    @field_validator("normalized_path")
    @classmethod
    def normalize_path(cls, value: str | None) -> str | None:
        return re.sub(r"\{\{[^}]+\}\}|\{[^}]+\}", "{}", value) if value else value

    @field_validator("contract_fingerprints")
    @classmethod
    def validate_fingerprints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"[a-f0-9]{64}", value) is None for value in values):
            raise ValueError("invalid contract fingerprint")
        return tuple(sorted(set(values)))


def _identity_conflicts(selector: OperationSelector, identity: OperationIdentity) -> bool:
    for name in _IDENTITY_FIELDS:
        expected, actual = getattr(selector, name), getattr(identity, name)
        if expected is not None and actual is not None and expected != actual:
            return True
    return bool(
        selector.contract_fingerprints
        and identity.contract_fingerprint not in selector.contract_fingerprints
    )


def _portable_identity(selector: OperationSelector, fingerprint: str) -> OperationIdentity | None:
    if (
        selector.service_key is None
        or selector.portable_operation_ref is None
        or selector.method is None
        or selector.normalized_path is None
        or not selector.contract_fingerprints
    ):
        return None
    return OperationIdentity(
        api_definition_id=selector.api_definition_id if selector.api_version else None,
        api_version=selector.api_version,
        portable_operation_ref=selector.portable_operation_ref,
        service_key=selector.service_key,
        method=selector.method,
        normalized_path=selector.normalized_path,
        contract_fingerprint=fingerprint,
    )


def match_operation(
    selector: OperationSelector, identity: OperationIdentity
) -> MatchStrength | None:
    """Known conflicts never fall back to route equality; missing evidence stays weak."""
    if _identity_conflicts(selector, identity):
        return None
    if (
        selector.api_definition_id is not None
        and selector.api_version is not None
        and selector.api_definition_id == identity.api_definition_id
        and selector.api_version == identity.api_version
    ):
        return "instance"
    portable = _portable_identity(selector, identity.contract_fingerprint)
    if portable is not None and same_operation_semantics(portable, identity):
        return "portable"
    if selector.method == identity.method and selector.normalized_path == identity.normalized_path:
        return "candidate"
    return None


class KnowledgeOperationImpact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_side: Literal["before", "after"]
    operation_node_id: str
    selector: OperationSelector
    changed_node_ids: tuple[str, ...]
    heuristic: bool
    requires_review: Literal[True] = True
    automatic_patch_allowed: Literal[False] = False


class KnowledgeImpactResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impacts: list[KnowledgeOperationImpact]
    ambiguous_operation_node_ids: list[str]
    requires_review: Literal[True] = True
    automatic_patch_allowed: Literal[False] = False


def _facts(node: ContextKnowledgeNode) -> dict[str, set[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for fact in node.facts:
        values[fact.name].add(fact.value)
    return values


def _selector(node: ContextKnowledgeNode) -> OperationSelector | None:
    values = _facts(node)
    paths = values.get("path", set()) | values.get("normalized_path", set())
    if paths:
        values["normalized_path"] = {
            re.sub(r"\{\{[^}]+\}\}|\{[^}]+\}", "{}", path) for path in paths
        }
    names = (*_IDENTITY_FIELDS, "contract_fingerprint")
    if any(len(values.get(name, set())) > 1 for name in names):
        return None
    single = {name: next(iter(items)) for name, items in values.items() if len(items) == 1}
    try:
        return OperationSelector(
            api_definition_id=single.get("api_definition_id"),
            api_version=int(single["api_version"]) if "api_version" in single else None,
            portable_operation_ref=single.get("portable_operation_ref"),
            service_key=single.get("service_key"),
            method=single.get("method"),
            normalized_path=single.get("normalized_path", single.get("path")),
            contract_fingerprints=(single["contract_fingerprint"],)
            if "contract_fingerprint" in single
            else (),
        )
    except ValueError:
        return None


def _requires_review(node: ContextKnowledgeNode) -> bool:
    return any(value.lower() != "false" for value in _facts(node).get("requires_review", set()))


def _reachable_changes(
    operation_id: str, graph: ContextKnowledgeSnapshot, changed: set[str]
) -> tuple[set[str], set[str]]:
    nodes = {node.id: node for node in graph.nodes}
    edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in graph.edges:
        edges[edge.source].append((edge.target, edge.relation))
    pending = deque([(operation_id, False)])
    visited: set[tuple[str, bool]] = set()
    hits: dict[bool, set[str]] = {False: set(), True: set()}
    while pending:
        node_id, heuristic = pending.popleft()
        heuristic = heuristic or _requires_review(nodes[node_id])
        if (node_id, heuristic) in visited:
            continue
        visited.add((node_id, heuristic))
        if node_id in changed:
            hits[heuristic].add(node_id)
        pending.extend(
            (target, heuristic or relation not in _EXPLICIT_RELATIONS)
            for target, relation in edges.get(node_id, [])
        )
    return hits[False], hits[True] - hits[False]


def _graph_impacts(
    graph: ContextKnowledgeSnapshot, changed: set[str], side: Literal["before", "after"]
) -> KnowledgeImpactResult:
    impacts: list[KnowledgeOperationImpact] = []
    ambiguous: list[str] = []
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "operation":
            continue
        selector = _selector(node)
        if selector is None:
            ambiguous.append(node.id)
            continue
        explicit, heuristic = _reachable_changes(node.id, graph, changed)
        for uncertain, hits in ((False, explicit), (True, heuristic)):
            if hits:
                impacts.append(
                    KnowledgeOperationImpact(
                        revision_side=side,
                        operation_node_id=node.id,
                        selector=selector,
                        changed_node_ids=tuple(sorted(hits)),
                        heuristic=uncertain,
                    )
                )
    return KnowledgeImpactResult(impacts=impacts, ambiguous_operation_node_ids=ambiguous)


def affected_knowledge_operations(
    before: ContextKnowledgeSnapshot, after: ContextKnowledgeSnapshot
) -> KnowledgeImpactResult:
    """Walk each immutable graph separately; never splice edges across revisions."""
    difference = diff_state_knowledge(before, after)
    changed = {node.node_id for node in difference.nodes}
    for edge in (*difference.edges.added, *difference.edges.removed):
        changed.update((edge.source, edge.target))
    previous = _graph_impacts(before, changed, "before")
    current = _graph_impacts(after, changed, "after")
    return KnowledgeImpactResult(
        impacts=[*previous.impacts, *current.impacts],
        ambiguous_operation_node_ids=sorted(
            set(previous.ambiguous_operation_node_ids + current.ambiguous_operation_node_ids)
        ),
    )
