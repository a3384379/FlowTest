"""Versioned FlowSpec v2 contract without persistence or execution side effects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.flow_spec import (
    FLOW_SPEC_FINGERPRINT_VERSION,
    FlowSpec,
    FlowSpecAssertion,
    FlowSpecConfidence,
    FlowSpecEdge,
    FlowSpecIssue,
    FlowSpecNode,
    FlowSpecOperation,
    FlowSpecParameter,
    FlowSpecSecurityPolicy,
    FlowSpecService,
    FlowSpecValidationResult,
    normalize_flow_spec,
    validate_flow_spec,
)
from app.engine.contracts import WorkflowSettings

FLOW_SPEC_V2_SCHEMA_VERSION = "flowtest-flow-spec-v2"
FLOW_SPEC_V2_FINGERPRINT_VERSION = "flowtest-flow-spec-v2-fingerprint-v1"


class FlowSpecPlanMetadata(BaseModel):
    """Traceability metadata excluded from the executable semantic fingerprint."""

    model_config = ConfigDict(extra="forbid")

    context_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    plan_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compiler_version: str | None = Field(default=None, min_length=1, max_length=80)


class FlowSpecRunPolicy(BaseModel):
    """Bounded runtime semantics that v1 cannot represent without schema drift."""

    model_config = ConfigDict(extra="forbid")

    request_budget: int | None = Field(default=None, ge=1, le=10_000)
    max_runtime_seconds: int | None = Field(default=None, ge=1, le=3600)
    cleanup_request_budget: int | None = Field(default=None, ge=1, le=1000)
    force_cancel_skips_cleanup: bool = False


class FlowSpecCleanupV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    phase: Literal["cleanup"] = "cleanup"
    operation_ref: str = Field(min_length=1, max_length=300)
    run_when: Literal["success", "failure", "cancel", "always"] = "always"
    cleanup_for: list[str] = Field(default_factory=list, max_length=200)
    best_effort: bool = False
    cleanup_timeout_seconds: int = Field(default=30, ge=1, le=300)
    cleanup_retry_budget: int = Field(default=0, ge=0, le=3)


class FlowSpecV2(BaseModel):
    """The same portable DSL with versioned cleanup and run-policy semantics."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-flow-spec-v2"] = "flowtest-flow-spec-v2"
    fingerprint_version: Literal["flowtest-flow-spec-v2-fingerprint-v1"] = (
        "flowtest-flow-spec-v2-fingerprint-v1"
    )
    project_id: UUID | None = None
    name: str = Field(default="Imported Flow", min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    source_evidence: list[str] = Field(default_factory=list, max_length=200)
    services: list[FlowSpecService] = Field(default_factory=list, max_length=500)
    operations: list[FlowSpecOperation] = Field(default_factory=list, max_length=1000)
    nodes: list[FlowSpecNode] = Field(min_length=1, max_length=1000)
    edges: list[FlowSpecEdge] = Field(default_factory=list, max_length=2000)
    variables: dict[str, str] = Field(default_factory=dict)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    bindings: list[dict[str, str]] = Field(default_factory=list, max_length=2000)
    parameters: list[FlowSpecParameter] = Field(default_factory=list, max_length=1000)
    assertions: list[FlowSpecAssertion] = Field(default_factory=list, max_length=2000)
    cleanup: list[FlowSpecCleanupV2] = Field(default_factory=list, max_length=200)
    security_policy: FlowSpecSecurityPolicy = Field(default_factory=FlowSpecSecurityPolicy)
    confidence: FlowSpecConfidence = Field(default_factory=FlowSpecConfidence)
    plan_metadata: FlowSpecPlanMetadata = Field(default_factory=FlowSpecPlanMetadata)
    run_policy: FlowSpecRunPolicy = Field(default_factory=FlowSpecRunPolicy)

    @model_validator(mode="after")
    def validate_cleanup_identity(self) -> FlowSpecV2:
        cleanup_ids = [item.id for item in self.cleanup]
        if len(cleanup_ids) != len(set(cleanup_ids)):
            raise ValueError("FlowSpec cleanup IDs must be unique")
        return self


def normalize_flow_spec_v2(spec: FlowSpecV2 | Mapping[str, object]) -> FlowSpecV2:
    raw = spec.model_dump(mode="json") if isinstance(spec, FlowSpecV2) else dict(spec)
    parsed = FlowSpecV2.model_validate(raw)
    normalized_v1 = normalize_flow_spec(_v1_projection(parsed))
    return parsed.model_copy(
        update={
            "name": parsed.name.strip(),
            "description": parsed.description.strip(),
            "source_evidence": sorted(set(item.strip() for item in parsed.source_evidence)),
            "services": normalized_v1.services,
            "operations": normalized_v1.operations,
            "nodes": normalized_v1.nodes,
            "edges": normalized_v1.edges,
            "bindings": normalized_v1.bindings,
            "parameters": normalized_v1.parameters,
            "assertions": normalized_v1.assertions,
            "cleanup": sorted(
                (
                    item.model_copy(update={"cleanup_for": sorted(set(item.cleanup_for))})
                    for item in parsed.cleanup
                ),
                key=lambda item: item.id,
            ),
        }
    )


def convert_flow_spec_v1_to_v2(spec: FlowSpec | Mapping[str, object]) -> FlowSpecV2:
    """Upgrade a v1 document deterministically without changing existing imports."""

    normalized = normalize_flow_spec(
        spec if isinstance(spec, FlowSpec) else FlowSpec.model_validate(spec)
    )
    payload = cast(dict[str, object], normalized.model_dump(mode="json"))
    payload["schema_version"] = FLOW_SPEC_V2_SCHEMA_VERSION
    payload["fingerprint_version"] = FLOW_SPEC_V2_FINGERPRINT_VERSION
    payload["cleanup"] = [
        {
            "id": f"cleanup-{index:03d}",
            "phase": "cleanup",
            "operation_ref": item.operation_ref,
            "run_when": "always",
            "cleanup_for": [],
            "best_effort": item.best_effort,
            "cleanup_timeout_seconds": 30,
            "cleanup_retry_budget": 0,
        }
        for index, item in enumerate(normalized.cleanup, start=1)
    ]
    payload["plan_metadata"] = {}
    payload["run_policy"] = {}
    return normalize_flow_spec_v2(payload)


def downgrade_flow_spec_v2_to_v1(spec: FlowSpecV2) -> FlowSpec:
    """Return a v1 document only when no v2-only executable semantics would be lost."""

    normalized = normalize_flow_spec_v2(spec)
    if _has_v2_only_runtime_semantics(normalized):
        raise ValueError("FlowSpec v2 contains runtime semantics that v1 cannot represent")
    return normalize_flow_spec(_v1_projection(normalized))


def flow_spec_v2_fingerprint(spec: FlowSpecV2) -> str:
    normalized = normalize_flow_spec_v2(spec)
    payload = cast(dict[str, JsonValue], normalized.model_dump(mode="json"))
    for excluded in (
        "project_id",
        "source_evidence",
        "confidence",
        "fingerprint_version",
        "plan_metadata",
    ):
        payload.pop(excluded, None)
    canonical = json.dumps(
        {"version": FLOW_SPEC_V2_FINGERPRINT_VERSION, "spec": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def validate_flow_spec_v2(spec: FlowSpecV2) -> FlowSpecValidationResult:
    normalized = normalize_flow_spec_v2(spec)
    base = validate_flow_spec(_v1_projection(normalized))
    issues = list(base.issues)
    known_nodes = {node.id for node in normalized.nodes}
    known_operations = {operation.ref for operation in normalized.operations}
    for index, cleanup in enumerate(normalized.cleanup):
        if cleanup.operation_ref not in known_operations:
            issues.append(
                FlowSpecIssue(
                    code="UNKNOWN_CLEANUP_OPERATION",
                    message="Cleanup 必须引用已声明 Operation",
                    path=f"$.cleanup[{index}].operation_ref",
                )
            )
        unknown = sorted(set(cleanup.cleanup_for) - known_nodes)
        if unknown:
            issues.append(
                FlowSpecIssue(
                    code="UNKNOWN_CLEANUP_TARGET",
                    message=f"Cleanup 引用了未知节点: {', '.join(unknown)}",
                    path=f"$.cleanup[{index}].cleanup_for",
                )
            )
    request_budget = normalized.run_policy.request_budget
    if request_budget is not None and request_budget > normalized.security_policy.max_requests:
        issues.append(
            FlowSpecIssue(
                code="REQUEST_BUDGET_EXCEEDS_SECURITY_POLICY",
                message="Run Policy 请求预算不能超过安全策略上限",
                path="$.run_policy.request_budget",
            )
        )
    cleanup_budget = normalized.run_policy.cleanup_request_budget
    if cleanup_budget is not None and cleanup_budget > normalized.security_policy.max_requests:
        issues.append(
            FlowSpecIssue(
                code="CLEANUP_REQUEST_BUDGET_EXCEEDS_SECURITY_POLICY",
                message="Cleanup 请求预算不能超过安全策略上限",
                path="$.run_policy.cleanup_request_budget",
            )
        )
    return FlowSpecValidationResult(
        valid=not issues,
        issues=issues,
        warnings=base.warnings,
        requires_review=base.requires_review,
    )


def _v1_projection(spec: FlowSpecV2) -> FlowSpec:
    payload = cast(dict[str, object], spec.model_dump(mode="json"))
    payload["schema_version"] = "flowtest-flow-spec-v1"
    payload["fingerprint_version"] = FLOW_SPEC_FINGERPRINT_VERSION
    payload["cleanup"] = [
        {"operation_ref": item.operation_ref, "best_effort": item.best_effort}
        for item in spec.cleanup
    ]
    payload.pop("plan_metadata", None)
    payload.pop("run_policy", None)
    return FlowSpec.model_validate(payload)


def _has_v2_only_runtime_semantics(spec: FlowSpecV2) -> bool:
    policy = spec.run_policy
    if (
        any(
            value is not None
            for value in (
                policy.request_budget,
                policy.max_runtime_seconds,
                policy.cleanup_request_budget,
            )
        )
        or policy.force_cancel_skips_cleanup
    ):
        return True
    return any(
        item.id != f"cleanup-{index:03d}"
        or item.run_when != "always"
        or bool(item.cleanup_for)
        or item.cleanup_timeout_seconds != 30
        or item.cleanup_retry_budget != 0
        for index, item in enumerate(spec.cleanup, start=1)
    )
