from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.context_diff import ProviderRevision, diff_context_revisions, diff_state_knowledge
from app.domain.test_contexts import (
    ContextCompletenessSnapshot,
    ContextKnowledgeSnapshot,
    ContextRevisionSnapshot,
    EvidenceProviderType,
    RevisionReference,
)


def _snapshot() -> ContextRevisionSnapshot:
    return ContextRevisionSnapshot(
        completeness=ContextCompletenessSnapshot(
            required=[EvidenceProviderType.REPOSITORY],
            present=[],
            missing=[EvidenceProviderType.REPOSITORY],
            complete=False,
        )
    )


def test_context_diff_golden_tracks_evidence_conflicts_completeness_and_knowledge() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/v6_golden/context-diff.json").read_text()
    )
    before = ContextRevisionSnapshot.model_validate(fixture["before"])
    after = ContextRevisionSnapshot.model_validate(fixture["after"])
    result = diff_context_revisions(before, after)

    assert result.evidence.added == ["b" * 64]
    assert result.evidence.removed == ["a" * 64]
    assert result.repositories.added[0].revision == "v2"
    assert result.repositories.removed[0].revision == "v1"
    assert not result.before_completeness.complete
    assert result.after_completeness.complete
    assert len(result.conflicts.removed) == 1
    assert not result.conflicts.added
    changes = {change.node_id: change for change in result.knowledge.nodes}
    assert changes["state.order"].changed_fact_names == ["state"]
    assert changes["table.order"].before_kind is None
    assert result.knowledge.edges.added[0].relation == "may_map_entity"
    assert result.requires_review
    assert result.knowledge.requires_review
    assert not result.automatic_patch_allowed
    assert "PRIVATE_FIXTURE_VALUE" not in result.model_dump_json()
    assert "PRIVATE_CONFLICT_SUMMARY" not in result.model_dump_json()
    assert result.before_fingerprint != result.after_fingerprint

    reverse = diff_context_revisions(after, before)
    assert reverse.evidence.added == result.evidence.removed
    assert reverse.knowledge.edges.removed == result.knowledge.edges.added
    assert reverse.before_fingerprint == result.after_fingerprint


def test_context_diff_ignores_order_without_mutating_inputs() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/v6_golden/context-diff.json").read_text()
    )
    snapshot = ContextRevisionSnapshot.model_validate(fixture["after"])
    reordered = snapshot.model_copy(deep=True)
    reordered.knowledge_snapshot.nodes.reverse()
    for node in reordered.knowledge_snapshot.nodes:
        node.facts.reverse()
    original_json = reordered.model_dump_json()

    result = diff_context_revisions(snapshot, reordered)

    assert not result.changed
    assert not result.knowledge.changed
    assert not result.knowledge.nodes
    assert result.before_fingerprint == result.after_fingerprint
    assert reordered.model_dump_json() == original_json


def test_provider_version_change_is_reported_even_when_snapshot_is_unchanged() -> None:
    provider = ProviderRevision(
        source_type=EvidenceProviderType.REPOSITORY,
        provider_name="spring",
        provider_version="1.0.0",
        source_ref="repository://sample",
        source_revision="v1",
    )
    updated = provider.model_copy(update={"provider_version": "2.0.0"})
    result = diff_context_revisions(
        _snapshot(), _snapshot(), before_providers=[provider, provider], after_providers=[updated]
    )
    assert result.changed
    assert result.providers.added == [updated]
    assert result.providers.removed == [provider]
    assert result.before_fingerprint == result.after_fingerprint


@pytest.mark.parametrize("kind", ["operation", "dto", "entity", "table", "state_candidate"])
def test_knowledge_diff_reports_node_removal_and_kind_change(kind: str) -> None:
    before = ContextKnowledgeSnapshot.model_validate(
        {"nodes": [{"id": "subject", "kind": kind, "label": "private label"}]}
    )
    removed = diff_state_knowledge(before, ContextKnowledgeSnapshot())
    assert removed.nodes[0].after_fingerprint is None
    assert removed.nodes[0].before_kind == kind
    assert "private label" not in removed.model_dump_json()
    after = before.model_copy(deep=True)
    after.nodes[0].kind = "changed_kind"
    changed = diff_state_knowledge(before, after)
    assert changed.nodes[0].after_kind == "changed_kind"
    assert not changed.nodes[0].label_changed


def test_fact_comparison_preserves_multiple_values_with_the_same_name() -> None:
    before = ContextKnowledgeSnapshot.model_validate(
        {
            "nodes": [
                {
                    "id": "state",
                    "kind": "state_candidate",
                    "label": "State",
                    "facts": [
                        {"name": "value", "value": "new"},
                        {"name": "value", "value": "accepted"},
                    ],
                }
            ]
        }
    )
    after = before.model_copy(deep=True)
    after.nodes[0].facts.pop(0)
    assert diff_state_knowledge(before, after).nodes[0].changed_fact_names == ["value"]


def test_context_diff_preserves_multiple_revisions_for_a_source_and_test_version() -> None:
    before = _snapshot()
    before.contract_revisions = [
        RevisionReference(source_ref="contract://orders", revision="v1"),
        RevisionReference(source_ref="contract://orders", revision="v2"),
    ]
    before.existing_test_revision = RevisionReference(source_ref="tests://orders", revision="v1")
    after = before.model_copy(deep=True)
    after.contract_revisions.pop(0)
    after.data_profile_revisions = [
        RevisionReference(source_ref="database://orders", revision="v3")
    ]
    after.existing_test_revision = None
    result = diff_context_revisions(before, after)
    assert result.contracts.removed == [before.contract_revisions[0]]
    assert result.contracts.added == []
    assert result.data_profiles.added == after.data_profile_revisions
    assert result.existing_tests.removed == [before.existing_test_revision]


def test_maximum_size_disjoint_knowledge_graphs_are_not_silently_truncated() -> None:
    def graph(prefix: str) -> ContextKnowledgeSnapshot:
        return ContextKnowledgeSnapshot.model_validate(
            {
                "nodes": [
                    {"id": f"{prefix}.{index}", "kind": "operation", "label": "Operation"}
                    for index in range(500)
                ],
                "edges": [
                    {
                        "source": f"{prefix}.{index}",
                        "target": f"{prefix}.{(index + 1) % 500}",
                        "relation": relation,
                    }
                    for index in range(500)
                    for relation in ["uses", "may_use"]
                ],
            }
        )

    result = diff_state_knowledge(graph("previous"), graph("current"))
    assert len(result.nodes) == 1000
    assert len(result.edges.added) == 1000
    assert len(result.edges.removed) == 1000
