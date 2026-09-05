"""Versioned, deterministic differences of immutable structured context evidence."""

from __future__ import annotations

import json
from collections.abc import Sequence
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.test_contexts import (
    ContextCompletenessSnapshot,
    ContextKnowledgeNode,
    ContextKnowledgeSnapshot,
    ContextRevisionSnapshot,
    EvidenceProviderType,
    RevisionReference,
    context_revision_fingerprint,
    normalize_revision_snapshot,
)


class Difference[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    added: list[T]
    removed: list[T]


class ProviderRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: EvidenceProviderType
    provider_name: str
    provider_version: str
    source_ref: str
    source_revision: str


class KnowledgeNodeChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    before_kind: str | None
    after_kind: str | None
    before_fingerprint: str | None
    after_fingerprint: str | None
    label_changed: bool
    changed_fact_names: list[str]


class KnowledgeEdgeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    target: str
    relation: str


class StateKnowledgeDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-state-knowledge-diff-v1"] = "flowtest-state-knowledge-diff-v1"
    nodes: list[KnowledgeNodeChange]
    edges: Difference[KnowledgeEdgeIdentity]
    changed: bool
    requires_review: Literal[True] = True


class ContextDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-context-diff-v1"] = "flowtest-context-diff-v1"
    before_fingerprint: str
    after_fingerprint: str
    evidence: Difference[str]
    providers: Difference[ProviderRevision]
    repositories: Difference[RevisionReference]
    contracts: Difference[RevisionReference]
    data_profiles: Difference[RevisionReference]
    existing_tests: Difference[RevisionReference]
    conflicts: Difference[str]
    before_completeness: ContextCompletenessSnapshot
    after_completeness: ContextCompletenessSnapshot
    knowledge: StateKnowledgeDiff
    changed: bool
    requires_review: Literal[True] = True
    automatic_patch_allowed: Literal[False] = False


def _digest(value: BaseModel) -> str:
    encoded = json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return sha256(encoded.encode()).hexdigest()


def _model_difference[T: BaseModel](before: Sequence[T], after: Sequence[T]) -> Difference[T]:
    previous = {item.model_dump_json(): item for item in before}
    current = {item.model_dump_json(): item for item in after}
    return Difference[T](
        added=[current[key] for key in sorted(current.keys() - previous.keys())],
        removed=[previous[key] for key in sorted(previous.keys() - current.keys())],
    )


def _string_difference(before: Sequence[str], after: Sequence[str]) -> Difference[str]:
    return Difference[str](
        added=sorted(set(after) - set(before)), removed=sorted(set(before) - set(after))
    )


def _normalized_node(node: ContextKnowledgeNode) -> ContextKnowledgeNode:
    return node.model_copy(
        update={"facts": sorted(node.facts, key=lambda fact: (fact.name, fact.value))}
    )


def _fact_values(node: ContextKnowledgeNode | None) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    if node is not None:
        for fact in node.facts:
            values.setdefault(fact.name, set()).add(fact.value)
    return values


def _node_change(
    node_id: str, before: ContextKnowledgeNode | None, after: ContextKnowledgeNode | None
) -> KnowledgeNodeChange:
    previous, current = _fact_values(before), _fact_values(after)
    return KnowledgeNodeChange(
        node_id=node_id,
        before_kind=before.kind if before else None,
        after_kind=after.kind if after else None,
        before_fingerprint=_digest(before) if before else None,
        after_fingerprint=_digest(after) if after else None,
        label_changed=(before.label if before else None) != (after.label if after else None),
        changed_fact_names=[
            name
            for name in sorted(previous.keys() | current.keys())
            if previous.get(name) != current.get(name)
        ],
    )


def diff_state_knowledge(
    before: ContextKnowledgeSnapshot, after: ContextKnowledgeSnapshot
) -> StateKnowledgeDiff:
    previous = {node.id: _normalized_node(node) for node in before.nodes}
    current = {node.id: _normalized_node(node) for node in after.nodes}
    changes = [
        _node_change(node_id, previous.get(node_id), current.get(node_id))
        for node_id in sorted(previous.keys() | current.keys())
        if previous.get(node_id) != current.get(node_id)
    ]
    edges = _model_difference(
        [KnowledgeEdgeIdentity(**edge.model_dump()) for edge in before.edges],
        [KnowledgeEdgeIdentity(**edge.model_dump()) for edge in after.edges],
    )
    return StateKnowledgeDiff(
        nodes=changes, edges=edges, changed=bool(changes or edges.added or edges.removed)
    )


def diff_context_revisions(
    before: ContextRevisionSnapshot,
    after: ContextRevisionSnapshot,
    *,
    before_providers: Sequence[ProviderRevision] = (),
    after_providers: Sequence[ProviderRevision] = (),
) -> ContextDiff:
    previous, current = normalize_revision_snapshot(before), normalize_revision_snapshot(after)
    providers = _model_difference(before_providers, after_providers)
    return ContextDiff(
        before_fingerprint=context_revision_fingerprint(previous),
        after_fingerprint=context_revision_fingerprint(current),
        evidence=_string_difference(previous.evidence_fingerprints, current.evidence_fingerprints),
        providers=providers,
        repositories=_model_difference(previous.repository_revisions, current.repository_revisions),
        contracts=_model_difference(previous.contract_revisions, current.contract_revisions),
        data_profiles=_model_difference(
            previous.data_profile_revisions, current.data_profile_revisions
        ),
        existing_tests=_model_difference(
            [previous.existing_test_revision] if previous.existing_test_revision else [],
            [current.existing_test_revision] if current.existing_test_revision else [],
        ),
        conflicts=_string_difference(
            [_digest(conflict) for conflict in previous.conflict_snapshot.conflicts],
            [_digest(conflict) for conflict in current.conflict_snapshot.conflicts],
        ),
        before_completeness=previous.completeness,
        after_completeness=current.completeness,
        knowledge=diff_state_knowledge(previous.knowledge_snapshot, current.knowledge_snapshot),
        changed=previous != current or bool(providers.added or providers.removed),
    )
