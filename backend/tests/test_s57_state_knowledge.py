from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.domain.evidence_adapters import (
    JavaEvidenceSubmission,
    JavaSourceSnapshot,
    JavaSpringPocProvider,
    MappingEvidenceInput,
    adapt_java_evidence,
)
from app.domain.state_knowledge import StateKnowledgeBudgetExceeded, derive_state_knowledge
from app.domain.test_contexts import (
    ContextKnowledgeFact,
    ContextKnowledgeNode,
    ContextKnowledgeSnapshot,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "v6_golden"
RUOYI_ROOT = FIXTURE_ROOT.parents[4] / "RuoYi"
SUBJECT_REF = "flowtest://projects/00000000-0000-0000-0000-000000000001/operations/users"


def test_state_knowledge_builds_traceable_spring_chain_and_preserves_initial_graph() -> None:
    initial = ContextKnowledgeSnapshot(
        nodes=[
            ContextKnowledgeNode(
                id="business.rule",
                kind="business_rule",
                label="User creation policy",
                facts=[
                    ContextKnowledgeFact(name="source", value="user_confirmed"),
                    ContextKnowledgeFact(name="origin", value="flowtest.state_knowledge"),
                ],
            )
        ]
    )

    knowledge = derive_state_knowledge(initial, _mapping_inputs(_ruoyi_style_submission()))

    assert knowledge.nodes[0] == initial.nodes[0]
    kinds = {node.kind for node in knowledge.nodes}
    assert kinds >= {
        "operation",
        "dto",
        "dto_field",
        "service",
        "repository",
        "entity",
        "table",
        "table_column",
        "validation",
        "state_candidate",
        "exception",
        "event",
    }
    _assert_user_chain(knowledge)
    generated = [node for node in knowledge.nodes if node.id != "business.rule"]
    assert all(
        {fact.name for fact in node.facts} >= {"origin", "reference", "evidence_ref"}
        for node in generated
    )
    assert (
        derive_state_knowledge(knowledge, _mapping_inputs(_ruoyi_style_submission())) == knowledge
    )


def test_state_knowledge_fails_closed_when_initial_graph_has_no_remaining_capacity() -> None:
    initial = ContextKnowledgeSnapshot(
        nodes=[
            ContextKnowledgeNode(id=f"N{index}", kind="initial", label=f"Node {index}")
            for index in range(500)
        ]
    )

    with pytest.raises(StateKnowledgeBudgetExceeded, match="graph budget"):
        derive_state_knowledge(initial, _mapping_inputs(_ruoyi_style_submission()))


def test_state_knowledge_does_not_infer_repository_when_service_name_is_ambiguous() -> None:
    payload = _ruoyi_style_submission().model_dump(mode="json")
    payload["claims"].append(
        {
            "id": "call-second-user-service",
            "kind": "service_call",
            "source_path": "SysUserController.java:146",
            "operation_ref": "operation://POST/system/user/add",
            "caller_ref": "java://SysUserController.addSave",
            "callee_ref": "java://SysUserService.insertUser",
            "confidence": 1,
            "deterministic": True,
        }
    )

    knowledge = derive_state_knowledge(
        ContextKnowledgeSnapshot(),
        _mapping_inputs(JavaEvidenceSubmission.model_validate(payload)),
    )

    assert all(edge.relation != "may_use_repository" for edge in knowledge.edges)


def test_state_knowledge_marks_conflicting_node_facts_for_review() -> None:
    payload = _ruoyi_style_submission().model_dump(mode="json")
    payload["claims"].append(
        {
            "id": "request-user-name-conflict",
            "kind": "dto_field",
            "source_path": "AlternateUser.java:45",
            "operation_ref": "operation://POST/system/user/add",
            "direction": "request",
            "dto_type": "SysUser",
            "field_name": "userName",
            "field_type": "Integer",
            "confidence": 0.7,
            "deterministic": False,
        }
    )

    knowledge = derive_state_knowledge(
        ContextKnowledgeSnapshot(),
        _mapping_inputs(JavaEvidenceSubmission.model_validate(payload)),
    )
    field = _node(knowledge, "dto_field", "SysUser.userName")

    assert ContextKnowledgeFact(name="requires_review", value="true") in field.facts


def test_ruoyi_golden_state_knowledge_chain_without_code_execution() -> None:
    target = cast(dict[str, Any], json.loads((FIXTURE_ROOT / "ruoyi-target.json").read_text()))
    if not RUOYI_ROOT.exists():
        pytest.skip("本地 RuoYi Golden Target 未提供; CI 使用固定结构化链路 Fixture")
    snapshot = JavaSourceSnapshot.model_validate(
        {
            "provider": {"name": "java-spring-poc", "version": "0.1.0"},
            "source": {
                "ref": str(target["source_ref"]),
                "revision": str(target["source_revision"]),
            },
            "subject_ref": SUBJECT_REF,
            "files": [
                {"path": path, "content": (RUOYI_ROOT / path).read_text()}
                for path in cast(list[str], target["poc_files"])
            ],
        }
    )

    submission = JavaSpringPocProvider().analyze(snapshot)
    knowledge = derive_state_knowledge(
        ContextKnowledgeSnapshot(),
        _mapping_inputs(submission),
    )

    assert snapshot.execute_analyzed_code is False
    _assert_user_chain(knowledge)


def _ruoyi_style_submission() -> JavaEvidenceSubmission:
    operation_ref = "operation://POST/system/user/add"
    common = {"confidence": 1, "deterministic": True}
    return JavaEvidenceSubmission.model_validate(
        {
            "provider": {"name": "java-spring-golden", "version": "1.0.0"},
            "source": {"ref": "repository://ruoyi", "revision": "fixture-v1"},
            "subject_ref": SUBJECT_REF,
            "claims": [
                {
                    **common,
                    "id": "route-add-user",
                    "kind": "controller_route",
                    "source_path": "SysUserController.java:130",
                    "operation_ref": operation_ref,
                    "controller_ref": "java://SysUserController",
                    "handler": "addSave",
                    "method": "POST",
                    "path": "/system/user/add",
                },
                {
                    **common,
                    "id": "request-user-name",
                    "kind": "dto_field",
                    "source_path": "SysUser.java:45",
                    "operation_ref": operation_ref,
                    "direction": "request",
                    "dto_type": "SysUser",
                    "field_name": "userName",
                    "field_type": "String",
                },
                {
                    **common,
                    "id": "validate-user-name",
                    "kind": "bean_validation",
                    "source_path": "SysUser.java:44",
                    "operation_ref": operation_ref,
                    "dto_type": "SysUser",
                    "field_name": "userName",
                    "annotation": "NotBlank",
                    "constraint": "not_blank=true",
                },
                {
                    **common,
                    "id": "call-user-service",
                    "kind": "service_call",
                    "source_path": "SysUserController.java:145",
                    "operation_ref": operation_ref,
                    "caller_ref": "java://SysUserController.addSave",
                    "callee_ref": "java://ISysUserService.insertUser",
                },
                {
                    **common,
                    "id": "user-mapper",
                    "kind": "mapper_repository",
                    "source_path": "SysUserMapper.java:13",
                    "repository_ref": "java://SysUserMapper",
                },
                {
                    **common,
                    "id": "user-entity",
                    "kind": "entity",
                    "source_path": "SysUser.java:22",
                    "entity_ref": "entity://SysUser",
                    "class_name": "SysUser",
                    "table_ref": "table://sys_user",
                },
                {
                    **common,
                    "id": "user-column",
                    "kind": "table_column",
                    "source_path": "SysUser.java:45",
                    "entity_ref": "entity://SysUser",
                    "table_ref": "table://sys_user",
                    "field_name": "userName",
                    "column_name": "user_name",
                },
                {
                    **common,
                    "id": "user-state",
                    "kind": "enum_state",
                    "source_path": "UserStatus.java:3",
                    "operation_ref": operation_ref,
                    "enum_ref": "java://UserStatus",
                    "direction": "request",
                    "dto_type": "SysUser",
                    "field_name": "userName",
                    "values": ["enabled", "disabled"],
                },
                {
                    **common,
                    "id": "user-exception",
                    "kind": "exception",
                    "source_path": "SysUserService.java:80",
                    "operation_ref": operation_ref,
                    "exception_type": "DuplicateUserException",
                    "outcome": "conflict",
                },
                {
                    **common,
                    "id": "user-event",
                    "kind": "kafka_event",
                    "source_path": "SysUserService.java:90",
                    "operation_ref": operation_ref,
                    "direction": "produce",
                    "topic_ref": "kafka://users.created",
                    "event_type": "UserCreated",
                },
            ],
            "confidence": 1,
            "deterministic": True,
        }
    )


def _mapping_inputs(submission: JavaEvidenceSubmission) -> list[MappingEvidenceInput]:
    envelope = adapt_java_evidence(submission)
    return [
        MappingEvidenceInput(
            evidence_ref=f"evidence://state-knowledge/{index}",
            finding=finding,
            confidence=finding.confidence,
            deterministic=finding.deterministic,
        )
        for index, finding in enumerate(envelope.findings)
    ]


def _assert_user_chain(knowledge: ContextKnowledgeSnapshot) -> None:
    operation = _node(knowledge, "operation", "POST /system/user/add")
    dto = _node(knowledge, "dto", "SysUser")
    service = _node(knowledge, "service", "ISysUserService")
    repository = _node_with_label(knowledge, "repository", "SysUserMapper")
    entity = _node(knowledge, "entity", "SysUser")
    table = _node(knowledge, "table", "sys_user")
    edges = {(edge.source, edge.target, edge.relation) for edge in knowledge.edges}
    assert (operation.id, dto.id, "accepts") in edges
    assert (dto.id, service.id, "handled_by") in edges
    assert (service.id, repository.id, "may_use_repository") in edges
    assert (repository.id, entity.id, "may_map_entity") in edges
    assert (entity.id, table.id, "maps_to") in edges


def _node(knowledge: ContextKnowledgeSnapshot, kind: str, label: str) -> ContextKnowledgeNode:
    return next(node for node in knowledge.nodes if node.kind == kind and node.label == label)


def _node_with_label(
    knowledge: ContextKnowledgeSnapshot,
    kind: str,
    label_fragment: str,
) -> ContextKnowledgeNode:
    return next(
        node for node in knowledge.nodes if node.kind == kind and label_fragment in node.label
    )
