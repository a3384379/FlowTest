"""Portable FlowSpec v1 contract and pure transformation helpers.

The FlowSpec contract deliberately sits above the persistence model.  A spec may
carry source-project metadata for traceability, but its semantic fingerprint is
portable and therefore excludes instance-specific identifiers and evidence URLs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.engine.contracts import (
    CapabilityBinding,
    FieldMapping,
    NodeType,
    Position,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowSettings,
    parse_node_config,
)

FLOW_SPEC_SCHEMA_VERSION = "flowtest-flow-spec-v1"
FLOW_SPEC_FINGERPRINT_VERSION = "flowtest-flow-spec-fingerprint-v1"


class FlowSpecParameterSource(StrEnum):
    SYNTHETIC_DATA = "synthetic_data"
    RUNTIME = "runtime"
    CONSTANT = "constant"
    SECRET_REF = "secret_ref"  # noqa: S105


class FlowSpecNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    position: Position = Field(default_factory=lambda: Position(x=0, y=0))
    config: dict[str, JsonValue] = Field(default_factory=dict)
    capability_id: str | None = None
    capability_version: str | None = None
    configuration: dict[str, JsonValue] | None = None
    bindings: list[CapabilityBinding] | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=128)
    operation_ref: str | None = Field(default=None, max_length=300)


class FlowSpecEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    condition: str | None = None
    mappings: list[FieldMapping] = Field(default_factory=list)


class FlowSpecParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    source: FlowSpecParameterSource
    value: str | None = Field(default=None, max_length=65536)
    secret_ref: str | None = Field(
        default=None,
        min_length=10,
        max_length=512,
        pattern=r"^secret://[A-Za-z0-9._:/-]+$",
    )
    description: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_source(self) -> FlowSpecParameter:
        if self.source is FlowSpecParameterSource.SECRET_REF:
            if self.secret_ref is None or self.value is not None:
                raise ValueError("secret_ref parameters must contain only a secret reference")
        elif self.secret_ref is not None:
            raise ValueError("secret_ref is only valid for secret_ref parameters")
        elif self.source is FlowSpecParameterSource.CONSTANT and self.value is None:
            raise ValueError("constant parameters require a value")
        return self


class FlowSpecAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    expected: JsonValue = None
    schema_ref: str | None = Field(default=None, max_length=512)
    query_ref: str | None = Field(default=None, max_length=512)


class FlowSpecCleanup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_ref: str = Field(min_length=1, max_length=300)
    best_effort: bool = False


class FlowSpecSecurityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_refs_only: bool = True
    max_requests: int = Field(default=20, ge=1, le=10_000)
    allow_private_network: bool = False


class FlowSpecConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: float = Field(default=1.0, ge=0, le=1)
    unresolved: list[str] = Field(default_factory=list, max_length=200)


class FlowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = FLOW_SPEC_SCHEMA_VERSION
    project_id: UUID | None = None
    name: str = Field(default="Imported Flow", min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    source_evidence: list[str] = Field(default_factory=list, max_length=200)
    nodes: list[FlowSpecNode] = Field(min_length=1, max_length=1000)
    edges: list[FlowSpecEdge] = Field(default_factory=list, max_length=2000)
    variables: dict[str, str] = Field(default_factory=dict)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    bindings: list[dict[str, str]] = Field(default_factory=list, max_length=2000)
    parameters: list[FlowSpecParameter] = Field(default_factory=list, max_length=1000)
    assertions: list[FlowSpecAssertion] = Field(default_factory=list, max_length=2000)
    cleanup: list[FlowSpecCleanup] = Field(default_factory=list, max_length=200)
    security_policy: FlowSpecSecurityPolicy = Field(default_factory=FlowSpecSecurityPolicy)
    confidence: FlowSpecConfidence = Field(default_factory=FlowSpecConfidence)

    @model_validator(mode="after")
    def validate_schema_version(self) -> FlowSpec:
        if self.schema_version != FLOW_SPEC_SCHEMA_VERSION:
            raise ValueError(f"Unsupported FlowSpec schema version: {self.schema_version}")
        return self


class FlowSpecIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    path: str = "$"


class FlowSpecValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[FlowSpecIssue] = Field(default_factory=list)
    warnings: list[FlowSpecIssue] = Field(default_factory=list)
    requires_review: bool = False


class FlowSpecCompatibilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compatible: bool
    source_schema_version: str
    target_schema_version: str = FLOW_SPEC_SCHEMA_VERSION
    blockers: list[FlowSpecIssue] = Field(default_factory=list)
    warnings: list[FlowSpecIssue] = Field(default_factory=list)
    requires_review: bool = False


class FlowSpecDiffItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    before: JsonValue
    after: JsonValue


_FLOW_NODE_TYPES: dict[str, NodeType] = {
    "start": NodeType.START,
    "flow.start": NodeType.START,
    "http": NodeType.API,
    "api": NodeType.API,
    "http.request": NodeType.API,
    "extract": NodeType.EXTRACT,
    "data.extract": NodeType.EXTRACT,
    "assert": NodeType.ASSERT,
    "assertion": NodeType.ASSERT,
    "assertion.evaluate": NodeType.ASSERT,
    "condition": NodeType.CONDITION,
    "flow.condition": NodeType.CONDITION,
    "delay": NodeType.DELAY,
    "flow.delay": NodeType.DELAY,
    "dataset": NodeType.DATASET,
    "data.dataset": NodeType.DATASET,
    "subflow": NodeType.SUBFLOW,
    "flow.subflow": NodeType.SUBFLOW,
    "for_each": NodeType.FOR_EACH,
    "flow.foreach": NodeType.FOR_EACH,
    "sql": NodeType.SQL,
    "sql.query": NodeType.SQL,
    "redis": NodeType.REDIS,
    "redis.read": NodeType.REDIS,
    "capability": NodeType.CAPABILITY,
    "end": NodeType.END,
    "flow.end": NodeType.END,
}

_FLOW_NODE_KIND: dict[NodeType, str] = {
    NodeType.START: "start",
    NodeType.API: "http",
    NodeType.EXTRACT: "extract",
    NodeType.ASSERT: "assert",
    NodeType.CONDITION: "condition",
    NodeType.DELAY: "delay",
    NodeType.DATASET: "dataset",
    NodeType.SUBFLOW: "subflow",
    NodeType.FOR_EACH: "for_each",
    NodeType.SQL: "sql",
    NodeType.REDIS: "redis",
    NodeType.CAPABILITY: "capability",
    NodeType.END: "end",
}

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:^|[_-])(authorization|cookie|password|passwd|secret|token|api[_-]?key|private[_-]?key)"
    r"(?:$|[_-])",
    re.IGNORECASE,
)
_TEMPLATE_PATTERN = re.compile(r"(?:\{\{[^{}]+\}\}|\$\{[^{}]+\})")
_RESOURCE_ID_KEYS = frozenset({"api_definition_id", "artifact_id", "credential_id", "workflow_id"})


def normalize_flow_spec(spec: FlowSpec | Mapping[str, object]) -> FlowSpec:
    """Return a deterministic, portable representation of a FlowSpec."""

    raw = (
        spec.model_dump(mode="json", by_alias=True, exclude_none=False)
        if isinstance(spec, FlowSpec)
        else dict(spec)
    )
    normalized = FlowSpec.model_validate(raw)
    nodes = [
        node.model_copy(update={"depends_on": sorted(set(node.depends_on))})
        for node in normalized.nodes
    ]
    nodes.sort(key=lambda item: item.id)
    edges = [
        edge.model_copy(
            update={
                "mappings": sorted(
                    edge.mappings,
                    key=lambda mapping: (
                        mapping.source.node_id,
                        mapping.source.path,
                        mapping.target.node_id,
                        mapping.target.location.value,
                        mapping.target.key,
                    ),
                )
            }
        )
        for edge in normalized.edges
    ]
    edges.sort(key=lambda item: item.id)
    return normalized.model_copy(
        update={
            "name": normalized.name.strip(),
            "description": normalized.description.strip(),
            "source_evidence": sorted(set(item.strip() for item in normalized.source_evidence)),
            "nodes": nodes,
            "edges": edges,
            "bindings": sorted(
                normalized.bindings,
                key=lambda item: (item.get("from", ""), item.get("to", "")),
            ),
            "parameters": sorted(normalized.parameters, key=lambda item: item.name),
            "assertions": sorted(
                normalized.assertions,
                key=lambda item: (
                    item.node_id,
                    item.kind,
                    item.schema_ref or "",
                    item.query_ref or "",
                ),
            ),
            "cleanup": sorted(normalized.cleanup, key=lambda item: item.operation_ref),
        }
    )


def flow_spec_fingerprint(spec: FlowSpec) -> str:
    """Calculate a cross-instance semantic fingerprint."""

    normalized = normalize_flow_spec(spec)
    payload = cast(dict[str, JsonValue], normalized.model_dump(mode="json", by_alias=True))
    payload.pop("project_id", None)
    payload.pop("source_evidence", None)
    payload.pop("confidence", None)
    canonical = json.dumps(
        {"version": FLOW_SPEC_FINGERPRINT_VERSION, "spec": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def diff_flow_specs(before: FlowSpec | None, after: FlowSpec) -> tuple[FlowSpecDiffItem, ...]:
    before_payload = (
        {}
        if before is None
        else cast(dict[str, JsonValue], normalize_flow_spec(before).model_dump(mode="json"))
    )
    after_payload = cast(dict[str, JsonValue], normalize_flow_spec(after).model_dump(mode="json"))
    return tuple(
        FlowSpecDiffItem(path=path, before=old, after=new)
        for path, old, new in _mapping_diff(before_payload, after_payload)
    )


def validate_flow_spec(spec: FlowSpec) -> FlowSpecValidationResult:
    """Run pure contract, graph, and secret-reference checks."""

    issues = _validate_graph_references(spec)
    issues.extend(_validate_semantic_references(spec))
    _collect_secret_issues(spec.model_dump(mode="json", by_alias=True), "$", issues)
    if not spec.security_policy.secret_refs_only:
        issues.append(
            FlowSpecIssue(
                code="SECRET_POLICY_DISABLED",
                message="FlowSpec 必须启用 secret_refs_only",
                path="$.security_policy.secret_refs_only",
            )
        )
    issues.extend(_validate_workflow_graph(spec))
    warnings = _confidence_warnings(spec)
    return FlowSpecValidationResult(
        valid=not issues,
        issues=issues,
        warnings=warnings,
        requires_review=bool(warnings) or bool(spec.confidence.unresolved),
    )


def _validate_graph_references(spec: FlowSpec) -> list[FlowSpecIssue]:
    issues: list[FlowSpecIssue] = []
    node_ids = {node.id for node in spec.nodes}
    if len(node_ids) != len(spec.nodes):
        issues.append(
            FlowSpecIssue(code="DUPLICATE_NODE_ID", message="节点 ID 必须唯一", path="$.nodes")
        )
    edge_ids = {edge.id for edge in spec.edges}
    if len(edge_ids) != len(spec.edges):
        issues.append(
            FlowSpecIssue(code="DUPLICATE_EDGE_ID", message="边 ID 必须唯一", path="$.edges")
        )
    for index, node in enumerate(spec.nodes):
        if node.kind not in _FLOW_NODE_TYPES:
            issues.append(
                FlowSpecIssue(
                    code="UNSUPPORTED_NODE_KIND",
                    message=f"节点类型 {node.kind} 未被当前 FlowSpec 版本支持",
                    path=f"$.nodes[{index}].kind",
                )
            )
        issues.extend(_unknown_node_issues(node.depends_on, node_ids, index))
    for index, edge in enumerate(spec.edges):
        if edge.source not in node_ids or edge.target not in node_ids:
            issues.append(
                FlowSpecIssue(
                    code="UNKNOWN_NODE_REFERENCE",
                    message="边引用了不存在的节点",
                    path=f"$.edges[{index}]",
                )
            )
    return issues


def _unknown_node_issues(
    dependencies: list[str], node_ids: set[str], node_index: int
) -> list[FlowSpecIssue]:
    return [
        FlowSpecIssue(
            code="UNKNOWN_NODE_REFERENCE",
            message=f"节点依赖 {dependency} 不存在",
            path=f"$.nodes[{node_index}].depends_on",
        )
        for dependency in dependencies
        if dependency not in node_ids
    ]


def _validate_semantic_references(spec: FlowSpec) -> list[FlowSpecIssue]:
    issues: list[FlowSpecIssue] = []
    node_ids = {node.id for node in spec.nodes}
    for index, binding in enumerate(spec.bindings):
        if not binding.get("from") or not binding.get("to"):
            issues.append(
                FlowSpecIssue(
                    code="INVALID_BINDING",
                    message="绑定必须同时声明 from 和 to",
                    path=f"$.bindings[{index}]",
                )
            )
    for index, assertion in enumerate(spec.assertions):
        if assertion.node_id not in node_ids:
            issues.append(
                FlowSpecIssue(
                    code="UNKNOWN_NODE_REFERENCE",
                    message=f"断言节点 {assertion.node_id} 不存在",
                    path=f"$.assertions[{index}].node_id",
                )
            )
    return issues


def _validate_workflow_graph(spec: FlowSpec) -> list[FlowSpecIssue]:
    try:
        definition = flow_spec_to_workflow_definition(spec)
        for node in definition.nodes:
            if node.type is not NodeType.CAPABILITY:
                parse_node_config(node)
    except (TypeError, ValueError) as error:
        return [FlowSpecIssue(code="INVALID_WORKFLOW_GRAPH", message=str(error))]
    return []


def _confidence_warnings(spec: FlowSpec) -> list[FlowSpecIssue]:
    warnings: list[FlowSpecIssue] = []
    if spec.confidence.overall < 0.8:
        warnings.append(
            FlowSpecIssue(
                code="LOW_CONFIDENCE",
                message="整体置信度低于 0.8,需要人工审核",
                path="$.confidence.overall",
            )
        )
    if spec.confidence.unresolved:
        warnings.append(
            FlowSpecIssue(
                code="UNRESOLVED_EVIDENCE",
                message="FlowSpec 包含未解决的推断",
                path="$.confidence.unresolved",
            )
        )
    return warnings


def assess_flow_spec_compatibility(spec: FlowSpec) -> FlowSpecCompatibilityResult:
    warnings: list[FlowSpecIssue] = []
    blockers: list[FlowSpecIssue] = []
    for index, node in enumerate(spec.nodes):
        _collect_resource_warnings(node.config, f"$.nodes[{index}].config", warnings)
        if node.configuration is not None:
            _collect_resource_warnings(
                node.configuration, f"$.nodes[{index}].configuration", warnings
            )
    if spec.project_id is not None:
        warnings.append(
            FlowSpecIssue(
                code="SOURCE_PROJECT_ID_IGNORED",
                message="导入时忽略来源项目 ID,以当前目标项目为准",
                path="$.project_id",
            )
        )
    if spec.confidence.overall < 0.8 or spec.confidence.unresolved:
        warnings.append(
            FlowSpecIssue(
                code="REVIEW_REQUIRED",
                message="低置信度或未解决证据必须经过人工审核",
                path="$.confidence",
            )
        )
    validation = validate_flow_spec(spec)
    blockers.extend(validation.issues)
    warnings.extend(validation.warnings)
    return FlowSpecCompatibilityResult(
        compatible=not blockers,
        source_schema_version=spec.schema_version,
        blockers=_unique_issues(blockers),
        warnings=_unique_issues(warnings),
        requires_review=True,
    )


def workflow_definition_to_flow_spec(
    definition: WorkflowDefinition,
    *,
    project_id: UUID | None = None,
    name: str = "Imported Flow",
    description: str = "",
    source_evidence: list[str] | None = None,
) -> FlowSpec:
    nodes = []
    for node in definition.nodes:
        if node.type is NodeType.CAPABILITY:
            config: dict[str, JsonValue] = {}
            capability_id = node.capability_id
            capability_version = (
                str(node.capability_version) if node.capability_version is not None else None
            )
            configuration = node.configuration
            bindings = node.bindings
            kind = "capability"
        else:
            config = node.config
            capability_id = None
            capability_version = None
            configuration = None
            bindings = None
            kind = _FLOW_NODE_KIND[node.type]
        nodes.append(
            FlowSpecNode(
                id=node.id,
                kind=kind,
                name=node.name,
                position=node.position,
                config=config,
                capability_id=capability_id,
                capability_version=capability_version,
                configuration=configuration,
                bindings=bindings,
            )
        )
    return normalize_flow_spec(
        FlowSpec(
            project_id=project_id,
            name=name,
            description=description,
            source_evidence=source_evidence or [],
            nodes=nodes,
            edges=[
                FlowSpecEdge.model_validate(edge.model_dump(mode="json"))
                for edge in definition.edges
            ],
            variables=dict(definition.variables),
            settings=definition.settings,
            parameters=[
                FlowSpecParameter(name=key, source=FlowSpecParameterSource.RUNTIME, value=value)
                for key, value in definition.variables.items()
            ],
        )
    )


def flow_spec_to_workflow_definition(spec: FlowSpec) -> WorkflowDefinition:
    nodes: list[WorkflowNode] = []
    for node in spec.nodes:
        node_type = _FLOW_NODE_TYPES.get(node.kind)
        if node_type is None:
            raise ValueError(f"Unsupported FlowSpec node kind: {node.kind}")
        nodes.append(
            WorkflowNode(
                id=node.id,
                type=node_type,
                name=node.name,
                position=node.position,
                config=node.config,
                capability_id=node.capability_id,
                capability_version=node.capability_version,
                configuration=node.configuration,
                bindings=node.bindings,
            )
        )
    edges = [WorkflowEdge.model_validate(edge.model_dump(mode="json")) for edge in spec.edges]
    return WorkflowDefinition(
        schema_version="1.0",
        variables=dict(spec.variables),
        nodes=nodes,
        edges=edges,
        settings=spec.settings,
    )


def _collect_secret_issues(value: JsonValue, path: str, issues: list[FlowSpecIssue]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "secret_ref":
                if not isinstance(child, str) or not child.startswith("secret://"):
                    issues.append(
                        FlowSpecIssue(
                            code="INVALID_SECRET_REF",
                            message="Secret 必须通过 secret:// 引用",
                            path=child_path,
                        )
                    )
                continue
            if _SENSITIVE_KEY_PATTERN.search(str(key)) and _is_literal_secret(child):
                issues.append(
                    FlowSpecIssue(
                        code="SECRET_LITERAL_FORBIDDEN",
                        message="FlowSpec 不得包含 Secret 明文,必须使用 secret_ref",
                        path=child_path,
                    )
                )
            _collect_secret_issues(child, child_path, issues)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_secret_issues(child, f"{path}[{index}]", issues)


def _collect_resource_warnings(
    value: dict[str, JsonValue], path: str, warnings: list[FlowSpecIssue]
) -> None:
    for key, child in value.items():
        if key in _RESOURCE_ID_KEYS and child is not None:
            warnings.append(
                FlowSpecIssue(
                    code="INSTANCE_RESOURCE_REFERENCE",
                    message="资源 ID 可能需要在目标实例重新映射",
                    path=f"{path}.{key}",
                )
            )
        if isinstance(child, dict):
            _collect_resource_warnings(child, f"{path}.{key}", warnings)


def _is_literal_secret(value: JsonValue) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (bool, int, float)):
        return False
    if isinstance(value, str):
        return not value.startswith("secret://") and _TEMPLATE_PATTERN.search(value) is None
    return True


def _unique_issues(items: list[FlowSpecIssue]) -> list[FlowSpecIssue]:
    seen: set[tuple[str, str, str]] = set()
    result: list[FlowSpecIssue] = []
    for item in items:
        key = (item.code, item.path, item.message)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _mapping_diff(
    before: JsonValue,
    after: JsonValue,
    path: str = "$",
) -> list[tuple[str, JsonValue, JsonValue]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return _diff_mapping_values(before, after, path)
    if isinstance(before, list) and isinstance(after, list):
        return _diff_sequence_values(before, after, path)
    return [(path, before, after)]


def _diff_mapping_values(
    before: dict[str, JsonValue], after: dict[str, JsonValue], path: str
) -> list[tuple[str, JsonValue, JsonValue]]:
    changes: list[tuple[str, JsonValue, JsonValue]] = []
    for key in sorted(before.keys() | after.keys()):
        child_path = f"{path}.{key}"
        if key not in before:
            changes.append((child_path, None, after[key]))
        elif key not in after:
            changes.append((child_path, before[key], None))
        else:
            changes.extend(_mapping_diff(before[key], after[key], child_path))
    return changes


def _diff_sequence_values(
    before: list[JsonValue], after: list[JsonValue], path: str
) -> list[tuple[str, JsonValue, JsonValue]]:
    if _has_unique_ids(before) and _has_unique_ids(after):
        return _diff_identity_sequence(before, after, path)
    return _diff_indexed_sequence(before, after, path)


def _diff_identity_sequence(
    before: list[JsonValue], after: list[JsonValue], path: str
) -> list[tuple[str, JsonValue, JsonValue]]:
    before_by_id = _sequence_by_id(before)
    after_by_id = _sequence_by_id(after)
    changes: list[tuple[str, JsonValue, JsonValue]] = []
    for item_id in sorted(before_by_id.keys() | after_by_id.keys()):
        child_path = f"{path}[id={item_id}]"
        if item_id not in before_by_id:
            changes.append((child_path, None, after_by_id[item_id]))
        elif item_id not in after_by_id:
            changes.append((child_path, before_by_id[item_id], None))
        else:
            changes.extend(_mapping_diff(before_by_id[item_id], after_by_id[item_id], child_path))
    return changes


def _diff_indexed_sequence(
    before: list[JsonValue], after: list[JsonValue], path: str
) -> list[tuple[str, JsonValue, JsonValue]]:
    changes: list[tuple[str, JsonValue, JsonValue]] = []
    for index in range(max(len(before), len(after))):
        child_path = f"{path}[{index}]"
        if index >= len(before):
            changes.append((child_path, None, after[index]))
        elif index >= len(after):
            changes.append((child_path, before[index], None))
        else:
            changes.extend(_mapping_diff(before[index], after[index], child_path))
    return changes


def _sequence_by_id(items: list[JsonValue]) -> dict[str, dict[str, JsonValue]]:
    return {str(item["id"]): item for item in items if isinstance(item, dict)}


def _has_unique_ids(items: list[JsonValue]) -> bool:
    ids = [item.get("id") for item in items if isinstance(item, dict) and item.get("id")]
    return len(ids) == len(items) and len(set(ids)) == len(ids)
