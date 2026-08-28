"""Versioned integration plans and deterministic FlowSpec compilation.

The plan is an evidence-bearing review contract.  It may describe intent that the
current workflow runtime cannot execute.  The compiler therefore fails closed:
it never guesses a binding and never emits lossy top-level FlowSpec semantics.
All functions in this module are pure and perform no I/O or persistence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from hashlib import sha256
from itertools import pairwise
from typing import Annotated, Literal, cast
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.expressions import SafeExpressionError, validate_safe_expression
from app.domain.flow_spec import (
    FLOW_SPEC_FINGERPRINT_VERSION,
    FlowSpec,
    FlowSpecCompatibilityResult,
    FlowSpecDiffItem,
    FlowSpecEdge,
    FlowSpecNode,
    FlowSpecNodeTarget,
    FlowSpecOperation,
    FlowSpecParameter,
    FlowSpecParameterSource,
    FlowSpecService,
    FlowSpecValidationResult,
    assess_flow_spec_compatibility,
    diff_flow_specs,
    flow_spec_fingerprint,
    normalize_flow_spec,
    validate_flow_spec,
)
from app.domain.test_design import OracleSpec, ScenarioCandidate
from app.domain.test_engineering import OperationContract, fingerprint_contract
from app.engine.contracts import (
    FieldMapping,
    MappingSource,
    MappingTarget,
    MappingTargetLocation,
    MappingTransform,
    MappingTransformKind,
    Position,
    WorkflowSettings,
)

INTEGRATION_PLAN_SCHEMA_VERSION = "flowtest-integration-plan-v1"
INTEGRATION_PLAN_FINGERPRINT_VERSION = "flowtest-integration-plan-fingerprint-v1"
INTEGRATION_PLAN_COMPILER_VERSION = "flowtest-integration-plan-compiler-v1"

_ZERO_FINGERPRINT = "0" * 64
_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_.:-]{0,119}$"
_SECRET_REF = r"^secret://[A-Za-z0-9._:/-]{1,480}$"  # noqa: S105
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(authorization|cookie|password|passwd|secret|token|api[_-]?key)"
    r"(?:$|[_-])",
    re.IGNORECASE,
)
_COMPILER_PASSES = (
    "normalize",
    "resolve_operations",
    "resolve_services",
    "build_graph",
    "compile_edge_mapping",
    "compile_assert_nodes",
    "compile_variables_data",
    "validate",
    "fingerprint",
    "diff",
)

PlanValueType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "object",
    "array",
    "null",
    "unknown",
]
PlanDiagnosticSeverity = Literal["blocker", "review", "warning", "info"]
EvidenceRef = Annotated[str, Field(min_length=1, max_length=512)]


class PlanActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    role: str = Field(min_length=1, max_length=160)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=100)


class PlanPrecondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    description: str = Field(min_length=1, max_length=1000)
    required: bool = True
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=100)


class PlanTargetEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,159}$")
    source_ref: str = Field(min_length=1, max_length=512)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=100)


class PlanRequestValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    value: JsonValue


class PlanRequestTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_parameters: list[PlanRequestValue] = Field(default_factory=list, max_length=200)
    headers: list[PlanRequestValue] = Field(default_factory=list, max_length=200)
    body: JsonValue = None
    body_kind: Literal["none", "json", "raw", "form"] = "none"
    auth_mode: Literal["inherit", "disabled"] = "inherit"

    @model_validator(mode="after")
    def validate_unique_names(self) -> PlanRequestTemplate:
        for values in (self.query_parameters, self.headers):
            names = [item.name.lower() for item in values]
            if len(names) != len(set(names)):
                raise ValueError("request template names must be unique")
        if self.body_kind == "none" and self.body is not None:
            raise ValueError("none request bodies must be null")
        for item in self.query_parameters:
            if _has_control_characters(item.name):
                raise ValueError("query parameter names cannot contain control characters")
        for item in self.headers:
            if _HEADER_NAME.fullmatch(item.name) is None:
                raise ValueError("request header names must use the HTTP token grammar")
            if isinstance(item.value, str) and _has_line_break(item.value):
                raise ValueError("request header values cannot contain line breaks")
        return self


class PlanOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(pattern=_IDENTIFIER)
    service_ref: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,159}$")
    service_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    method: str = Field(pattern=r"^[A-Z]+$", min_length=3, max_length=16)
    path: str = Field(min_length=1, max_length=2048)
    version_strategy: Literal["pinned", "current"] = "pinned"
    source_version: int = Field(ge=1)
    contract_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_by_user: bool = True
    expected_statuses: list[int] = Field(min_length=1, max_length=20)
    request: PlanRequestTemplate = Field(default_factory=PlanRequestTemplate)
    credential_refs: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_statuses(self) -> PlanOperation:
        if len(self.expected_statuses) != len(set(self.expected_statuses)):
            raise ValueError("expected statuses must be unique")
        if any(status < 100 or status > 599 for status in self.expected_statuses):
            raise ValueError("expected statuses must be valid HTTP status codes")
        if any(re.fullmatch(_SECRET_REF, ref) is None for ref in self.credential_refs):
            raise ValueError("credential references must use secret:// references")
        if self.credential_refs and self.request.auth_mode != "inherit":
            raise ValueError("credential references require inherited operation auth")
        return self


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    kind: Literal["operation", "subflow", "dataset"]
    name: str = Field(min_length=1, max_length=200)
    operation_ref: str | None = Field(default=None, pattern=_IDENTIFIER)
    workflow_id: UUID | None = None
    workflow_version: int | None = Field(default=None, ge=1)
    data_recipe_ref: str | None = Field(default=None, pattern=_IDENTIFIER)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_kind_fields(self) -> PlanStep:
        present = {
            "operation": self.operation_ref is not None,
            "subflow": self.workflow_id is not None and self.workflow_version is not None,
            "dataset": self.data_recipe_ref is not None,
        }
        if not present[self.kind] or sum(present.values()) != 1:
            raise ValueError("step kind must declare exactly its matching reference")
        return self


class PlanBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    source_step_id: str = Field(pattern=_IDENTIFIER)
    expression: str = Field(min_length=1, max_length=500)
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "exists",
        "less_than",
        "less_than_or_equal",
        "greater_than",
        "greater_than_or_equal",
        "matches",
    ] = "equals"
    expected: JsonValue = None
    true_step_id: str = Field(pattern=_IDENTIFIER)
    false_step_id: str = Field(pattern=_IDENTIFIER)
    join_step_id: str = Field(pattern=_IDENTIFIER)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)


class PlanBindingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    source_kind: Literal[
        "previous_response",
        "runtime_variable",
        "environment_variable",
        "dataset",
        "secret_ref",
        "setup_api",
        "external_evidence",
    ]
    source_step_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    source_recipe_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    variable_name: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,159}$",
    )
    secret_ref: str | None = Field(default=None, pattern=_SECRET_REF)
    path: str = Field(min_length=1, max_length=500)
    value_type: PlanValueType
    transform: Literal["identity", "template", "string_to_number", "number_to_string"] = "identity"
    template: str | None = Field(default=None, max_length=4000)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_source(self) -> PlanBindingCandidate:
        needs_step = self.source_kind in {"previous_response", "setup_api"}
        needs_recipe = self.source_kind == "dataset"
        needs_variable = self.source_kind in {"runtime_variable", "environment_variable"}
        needs_secret = self.source_kind == "secret_ref"
        if needs_step != (self.source_step_id is not None):
            raise ValueError("binding source step reference does not match its source kind")
        if needs_recipe != (self.source_recipe_id is not None):
            raise ValueError("binding source recipe reference does not match its source kind")
        if needs_variable != (self.variable_name is not None):
            raise ValueError("binding variable name does not match its source kind")
        if needs_secret != (self.secret_ref is not None):
            raise ValueError("binding secret reference does not match its source kind")
        if self.transform == "template" and self.template is None:
            raise ValueError("template transforms require a template")
        if self.transform != "template" and self.template is not None:
            raise ValueError("templates are only valid for template transforms")
        if self.template is not None and self.template.count("{{value}}") != 1:
            raise ValueError("binding templates require exactly one {{value}} placeholder")
        return self


class PlanBindingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(pattern=_IDENTIFIER)
    location: Literal["path", "query", "header", "cookie", "body", "workflow_variable"]
    key: str = Field(min_length=1, max_length=500)
    value_type: PlanValueType

    @model_validator(mode="after")
    def validate_target_key(self) -> PlanBindingTarget:
        if _has_control_characters(self.key):
            raise ValueError("binding target keys cannot contain control characters")
        if self.location == "header" and _HEADER_NAME.fullmatch(self.key) is None:
            raise ValueError("binding header targets must use the HTTP token grammar")
        return self


class PlanBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    candidates: list[PlanBindingCandidate] = Field(min_length=1, max_length=100)
    selected_candidate_id: str | None = Field(default=None, pattern=_IDENTIFIER)
    target: PlanBindingTarget
    capture_variable: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,159}$",
    )
    confidence: float = Field(ge=0, le=1)
    requires_review: bool = False
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_candidate_selection(self) -> PlanBinding:
        candidate_ids = [candidate.id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("binding candidate ids must be unique")
        if self.selected_candidate_id is not None and self.selected_candidate_id not in set(
            candidate_ids
        ):
            raise ValueError("selected binding candidate must exist")
        return self


class PlanDataRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    kind: Literal["dataset", "runtime", "environment", "constant", "setup_api"]
    name: str = Field(min_length=1, max_length=160)
    artifact_id: UUID | None = None
    value: str | None = Field(default=None, max_length=65536)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_recipe_value(self) -> PlanDataRecipe:
        if (self.kind == "dataset") != (self.artifact_id is not None):
            raise ValueError("dataset recipes require only an artifact id")
        if self.kind == "constant" and self.value is None:
            raise ValueError("constant recipes require a value")
        if self.kind not in {"constant"} and self.value is not None:
            raise ValueError("only constant recipes may contain a value")
        return self


class PlanOracle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    step_id: str = Field(pattern=_IDENTIFIER)
    kind: Literal["status", "schema", "field"]
    expression: str = Field(min_length=1, max_length=500)
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "exists",
        "less_than",
        "less_than_or_equal",
        "greater_than",
        "greater_than_or_equal",
        "matches",
    ] = "equals"
    expected: JsonValue = None
    confidence: float = Field(ge=0, le=1)
    requires_review: bool = False
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)


class PlanCleanupRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    operation_ref: str = Field(pattern=_IDENTIFIER)
    cleanup_for_step_ids: list[str] = Field(min_length=1, max_length=100)
    best_effort: bool = False
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)


class PlanCoverageTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    dimension: Literal[
        "operation",
        "binding",
        "status",
        "schema",
        "field",
        "branch",
        "cleanup",
    ]
    target_ref: str = Field(min_length=1, max_length=300)
    covered_by: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)


class PlanUnresolvedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER)
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,79}$")
    severity: Literal["blocker", "review"]
    message: str = Field(min_length=1, max_length=1000)
    candidate_refs: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=100)


class PlanConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: float = Field(ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)
    deterministic: bool = True


class PlanDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,79}$")
    severity: PlanDiagnosticSeverity
    message: str = Field(min_length=1, max_length=1000)
    path: str = Field(default="$", min_length=1, max_length=1000)
    compiler_pass: str | None = Field(default=None, max_length=80)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=100)


class IntegrationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-integration-plan-v1"] = "flowtest-integration-plan-v1"
    fingerprint_version: Literal["flowtest-integration-plan-fingerprint-v1"] = (
        "flowtest-integration-plan-fingerprint-v1"
    )
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_revision_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    objective: str = Field(min_length=1, max_length=2000)
    actors: list[PlanActor] = Field(min_length=1, max_length=50)
    preconditions: list[PlanPrecondition] = Field(default_factory=list, max_length=100)
    target_environment: PlanTargetEnvironment
    operations: list[PlanOperation] = Field(min_length=1, max_length=1000)
    steps: list[PlanStep] = Field(min_length=1, max_length=1000)
    branches: list[PlanBranch] = Field(default_factory=list, max_length=100)
    bindings: list[PlanBinding] = Field(default_factory=list, max_length=2000)
    data_recipes: list[PlanDataRecipe] = Field(default_factory=list, max_length=500)
    oracles: list[PlanOracle] = Field(default_factory=list, max_length=2000)
    cleanup_requirements: list[PlanCleanupRequirement] = Field(default_factory=list, max_length=200)
    coverage_targets: list[PlanCoverageTarget] = Field(default_factory=list, max_length=2000)
    unresolved_items: list[PlanUnresolvedItem] = Field(default_factory=list, max_length=500)
    review_requirements: list[str] = Field(default_factory=list, max_length=200)
    confidence: PlanConfidence
    diagnostics: list[PlanDiagnostic] = Field(default_factory=list, max_length=500)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=500)


class PlanValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    diagnostics: list[PlanDiagnostic] = Field(default_factory=list)
    requires_review: bool = False


class CompilerPassRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["completed", "blocked", "skipped"]
    diagnostic_codes: list[str] = Field(default_factory=list)


class CompilerEvidenceTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1, max_length=128)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=500)


class IntegrationPlanCompilation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compiler_version: str = INTEGRATION_PLAN_COMPILER_VERSION
    plan_fingerprint: str
    flow_spec: FlowSpec | None = None
    flow_spec_fingerprint: str | None = None
    validation: FlowSpecValidationResult | None = None
    compatibility: FlowSpecCompatibilityResult | None = None
    importable: bool = False
    diagnostics: list[PlanDiagnostic] = Field(default_factory=list)
    passes: list[CompilerPassRecord] = Field(default_factory=list)
    node_evidence: list[CompilerEvidenceTrace] = Field(default_factory=list)
    edge_evidence: list[CompilerEvidenceTrace] = Field(default_factory=list)
    diff: list[FlowSpecDiffItem] = Field(default_factory=list)


class ReusableAuthSubflowEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(pattern=_IDENTIFIER)
    name: str = Field(min_length=1, max_length=200)
    workflow_id: UUID
    workflow_version: int = Field(ge=1)
    token_path: str = Field(min_length=1, max_length=500)
    token_type: PlanValueType = "string"  # noqa: S105
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)


class SelectedOperationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_ref: str = Field(pattern=_IDENTIFIER)
    service_name: str = Field(min_length=1, max_length=200)
    source_version: int = Field(ge=1)
    contract: OperationContract
    scenario: ScenarioCandidate | None = None
    oracles: list[OracleSpec] = Field(default_factory=list, max_length=100)
    credential_refs: list[str] = Field(default_factory=list, max_length=100)
    selected_by_user: bool = True
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_credential_refs(self) -> SelectedOperationEvidence:
        if any(re.fullmatch(_SECRET_REF, ref) is None for ref in self.credential_refs):
            raise ValueError("credential references must use secret:// references")
        return self


class IntegrationPlannerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_revision_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    objective: str = Field(min_length=1, max_length=2000)
    actors: list[PlanActor] = Field(min_length=1, max_length=50)
    preconditions: list[PlanPrecondition] = Field(default_factory=list, max_length=100)
    target_environment: PlanTargetEnvironment
    selected_operations: list[SelectedOperationEvidence] = Field(min_length=1, max_length=100)
    reusable_auth_subflow: ReusableAuthSubflowEvidence | None = None
    cleanup_requirements: list[PlanCleanupRequirement] = Field(default_factory=list)


class _RequiredInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    location: Literal["path", "query", "header", "cookie", "body"]
    path: str
    value_type: PlanValueType
    evidence_refs: list[EvidenceRef]
    auth_template: str | None = None


class _ResponseField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    step_id: str
    path: str
    value_type: PlanValueType
    evidence_refs: list[EvidenceRef]
    confidence: float = 1


def normalize_integration_plan(plan: IntegrationPlan | Mapping[str, object]) -> IntegrationPlan:
    """Return the canonical representation used for fingerprints and snapshots."""

    normalized = (
        plan if isinstance(plan, IntegrationPlan) else IntegrationPlan.model_validate(dict(plan))
    )
    return normalized.model_copy(
        update={
            "objective": normalized.objective.strip(),
            "actors": sorted(
                (
                    item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
                    for item in normalized.actors
                ),
                key=lambda item: item.id,
            ),
            "preconditions": sorted(
                (
                    item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
                    for item in normalized.preconditions
                ),
                key=lambda item: item.id,
            ),
            "target_environment": normalized.target_environment.model_copy(
                update={"evidence_refs": _sorted_refs(normalized.target_environment.evidence_refs)}
            ),
            "operations": sorted(
                (_normalize_operation(item) for item in normalized.operations),
                key=lambda item: item.ref,
            ),
            "steps": [
                item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
                for item in normalized.steps
            ],
            "branches": sorted(
                (
                    item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
                    for item in normalized.branches
                ),
                key=lambda item: item.id,
            ),
            "bindings": sorted(
                (_normalize_binding(item) for item in normalized.bindings),
                key=lambda item: item.id,
            ),
            "data_recipes": sorted(
                (
                    item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
                    for item in normalized.data_recipes
                ),
                key=lambda item: item.id,
            ),
            "oracles": sorted(
                (
                    item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
                    for item in normalized.oracles
                ),
                key=lambda item: item.id,
            ),
            "cleanup_requirements": sorted(
                (
                    item.model_copy(
                        update={
                            "cleanup_for_step_ids": sorted(set(item.cleanup_for_step_ids)),
                            "evidence_refs": _sorted_refs(item.evidence_refs),
                        }
                    )
                    for item in normalized.cleanup_requirements
                ),
                key=lambda item: item.id,
            ),
            "coverage_targets": sorted(
                (
                    item.model_copy(
                        update={
                            "covered_by": sorted(set(item.covered_by)),
                            "evidence_refs": _sorted_refs(item.evidence_refs),
                        }
                    )
                    for item in normalized.coverage_targets
                ),
                key=lambda item: item.id,
            ),
            "unresolved_items": sorted(
                (
                    item.model_copy(
                        update={
                            "candidate_refs": sorted(set(item.candidate_refs)),
                            "evidence_refs": _sorted_refs(item.evidence_refs),
                        }
                    )
                    for item in normalized.unresolved_items
                ),
                key=lambda item: item.id,
            ),
            "review_requirements": sorted(set(normalized.review_requirements)),
            "diagnostics": sorted(
                (
                    item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
                    for item in normalized.diagnostics
                ),
                key=lambda item: (item.severity, item.code, item.path),
            ),
            "evidence_refs": _sorted_refs(normalized.evidence_refs),
        }
    )


def _normalize_operation(operation: PlanOperation) -> PlanOperation:
    request = operation.request.model_copy(
        update={
            "query_parameters": sorted(
                operation.request.query_parameters,
                key=lambda item: item.name,
            ),
            "headers": sorted(
                operation.request.headers,
                key=lambda item: item.name.lower(),
            ),
        }
    )
    return operation.model_copy(
        update={
            "expected_statuses": sorted(set(operation.expected_statuses)),
            "request": request,
            "credential_refs": sorted(set(operation.credential_refs)),
            "evidence_refs": _sorted_refs(operation.evidence_refs),
        }
    )


def _normalize_binding(binding: PlanBinding) -> PlanBinding:
    candidates = [
        item.model_copy(update={"evidence_refs": _sorted_refs(item.evidence_refs)})
        for item in binding.candidates
    ]
    return binding.model_copy(
        update={
            "candidates": sorted(candidates, key=lambda item: item.id),
            "evidence_refs": _sorted_refs(binding.evidence_refs),
        }
    )


def _sorted_refs(refs: Iterable[str]) -> list[str]:
    return sorted(set(refs))


def integration_plan_fingerprint(plan: IntegrationPlan) -> str:
    normalized = normalize_integration_plan(plan)
    payload = normalized.model_dump(mode="json")
    payload.pop("plan_fingerprint", None)
    canonical = json.dumps(
        {"version": normalized.fingerprint_version, "plan": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


def seal_integration_plan(plan: IntegrationPlan) -> IntegrationPlan:
    normalized = normalize_integration_plan(plan)
    return normalized.model_copy(
        update={"plan_fingerprint": integration_plan_fingerprint(normalized)}
    )


def validate_integration_plan(plan: IntegrationPlan) -> PlanValidationResult:
    normalized = normalize_integration_plan(plan)
    diagnostics: list[PlanDiagnostic] = []
    if normalized.plan_fingerprint != integration_plan_fingerprint(normalized):
        diagnostics.append(
            _diagnostic(
                "PLAN_FINGERPRINT_MISMATCH",
                "blocker",
                "Integration Plan fingerprint 与规范化内容不一致",
                "$.plan_fingerprint",
            )
        )
    diagnostics.extend(_identity_diagnostics(normalized))
    diagnostics.extend(_reference_diagnostics(normalized))
    diagnostics.extend(_binding_diagnostics(normalized))
    diagnostics.extend(_branch_diagnostics(normalized))
    diagnostics.extend(_expression_diagnostics(normalized))
    diagnostics.extend(_secret_literal_diagnostics(normalized))
    diagnostics.extend(_review_diagnostics(normalized))
    diagnostics.extend(normalized.diagnostics)
    diagnostics.extend(
        _diagnostic(
            item.code,
            item.severity,
            item.message,
            f"$.unresolved_items[{index}]",
            evidence_refs=item.evidence_refs,
        )
        for index, item in enumerate(normalized.unresolved_items)
    )
    diagnostics = _unique_diagnostics(diagnostics)
    return PlanValidationResult(
        valid=not any(item.severity == "blocker" for item in diagnostics),
        diagnostics=diagnostics,
        requires_review=any(item.severity == "review" for item in diagnostics),
    )


def build_integration_plan(request: IntegrationPlannerRequest) -> IntegrationPlan:
    """Build a deterministic plan from user-selected canonical operation evidence."""

    operations = [_planned_operation(item) for item in request.selected_operations]
    steps = _planned_steps(request)
    bindings, unresolved = _planned_bindings(request, steps)
    oracles, oracle_unresolved = _planned_oracles(request, steps)
    unresolved.extend(oracle_unresolved)
    evidence_refs = _all_planner_evidence(request)
    evidence_items = max(1, len(request.selected_operations) + len(bindings) + len(oracles))
    unresolved_count = len(unresolved)
    plan = IntegrationPlan(
        plan_fingerprint=_ZERO_FINGERPRINT,
        context_revision_id=request.context_revision_id,
        context_fingerprint=request.context_fingerprint,
        objective=request.objective,
        actors=request.actors,
        preconditions=request.preconditions,
        target_environment=request.target_environment,
        operations=operations,
        steps=steps,
        bindings=bindings,
        data_recipes=[],
        oracles=oracles,
        cleanup_requirements=request.cleanup_requirements,
        coverage_targets=_planned_coverage(steps, bindings, oracles),
        unresolved_items=unresolved,
        review_requirements=sorted({item.code for item in unresolved if item.severity == "review"}),
        confidence=PlanConfidence(
            overall=min(
                [candidate.confidence for binding in bindings for candidate in binding.candidates]
                or [1]
            ),
            evidence_coverage=max(0, (evidence_items - unresolved_count) / evidence_items),
            deterministic=True,
        ),
        diagnostics=[],
        evidence_refs=evidence_refs,
    )
    return seal_integration_plan(plan)


def compile_integration_plan(plan: IntegrationPlan) -> IntegrationPlanCompilation:
    """Compile a reviewed Integration Plan to the currently executable FlowSpec v1."""

    normalized = normalize_integration_plan(plan)
    plan_validation = validate_integration_plan(normalized)
    diagnostics = list(plan_validation.diagnostics)
    diagnostics.extend(_runtime_compatibility_diagnostics(normalized))
    diagnostics = _unique_diagnostics(diagnostics)
    if any(item.severity in {"blocker", "review"} for item in diagnostics):
        return _blocked_compilation(normalized, diagnostics)

    nodes, node_evidence = _compile_step_nodes(normalized)
    edges, edge_evidence = _compile_base_edges(normalized)
    _compile_branches(normalized, nodes, edges, node_evidence, edge_evidence)
    _compile_bindings(normalized, nodes, edges, node_evidence, edge_evidence)
    _compile_oracles(normalized, nodes, edges, node_evidence, edge_evidence)
    parameters = _compile_data_parameters(normalized)
    spec = normalize_flow_spec(
        FlowSpec(
            fingerprint_version=FLOW_SPEC_FINGERPRINT_VERSION,
            name=_flow_name(normalized.objective),
            description="由 flowtest-integration-plan-v1 确定性编译",
            source_evidence=normalized.evidence_refs,
            services=_compile_services(normalized),
            operations=_compile_operations(normalized),
            nodes=nodes,
            edges=list(edges.values()),
            variables={parameter.name: parameter.value or "" for parameter in parameters},
            parameters=parameters,
            settings=WorkflowSettings(fail_fast=True, concurrency=5),
        )
    )
    validation = validate_flow_spec(spec)
    compatibility = assess_flow_spec_compatibility(spec)
    diagnostics.extend(_flow_spec_diagnostics(validation, compatibility))
    diagnostics.extend(_cleanup_diagnostics(normalized))
    diagnostics = _unique_diagnostics(diagnostics)
    importable = validation.valid and compatibility.compatible
    fingerprint = flow_spec_fingerprint(spec) if importable else None
    return IntegrationPlanCompilation(
        plan_fingerprint=normalized.plan_fingerprint,
        flow_spec=spec,
        flow_spec_fingerprint=fingerprint,
        validation=validation,
        compatibility=compatibility,
        importable=importable,
        diagnostics=diagnostics,
        passes=_pass_records(diagnostics, completed=importable),
        node_evidence=_evidence_traces(node_evidence),
        edge_evidence=_evidence_traces(edge_evidence),
        diff=list(diff_flow_specs(None, spec)),
    )


def _planned_operation(item: SelectedOperationEvidence) -> PlanOperation:
    contract = item.contract
    statuses = sorted(
        int(status) for status in contract.responses if status.isdigit() and status.startswith("2")
    )
    return PlanOperation(
        ref=item.operation_ref,
        service_ref=contract.service or "default",
        service_name=item.service_name,
        name=item.operation_ref,
        method=contract.method,
        path=contract.path,
        source_version=item.source_version,
        contract_fingerprint=fingerprint_contract(contract),
        selected_by_user=item.selected_by_user,
        expected_statuses=statuses or [200],
        request=_scenario_request(item.scenario),
        credential_refs=sorted(set(item.credential_refs)),
        evidence_refs=sorted(
            set(
                [
                    *item.evidence_refs,
                    *([contract.source_ref] if contract.source_ref else []),
                ]
            )
        ),
    )


def _scenario_request(scenario: ScenarioCandidate | None) -> PlanRequestTemplate:
    if scenario is None:
        return PlanRequestTemplate()
    request = scenario.request
    body = request.body if request.body is not None else scenario.request_body or None
    return PlanRequestTemplate(
        query_parameters=[
            PlanRequestValue(name=name, value=value)
            for name, value in sorted(request.query_parameters.items())
        ],
        headers=[
            PlanRequestValue(name=name, value=value)
            for name, value in sorted(request.headers.items())
        ],
        body=body,
        body_kind="json" if body is not None else "none",
        auth_mode="disabled" if request.auth_disabled else "inherit",
    )


def _planned_steps(request: IntegrationPlannerRequest) -> list[PlanStep]:
    steps: list[PlanStep] = []
    auth = request.reusable_auth_subflow
    if auth is not None:
        steps.append(
            PlanStep(
                id=auth.step_id,
                kind="subflow",
                name=auth.name,
                workflow_id=auth.workflow_id,
                workflow_version=auth.workflow_version,
                evidence_refs=auth.evidence_refs,
            )
        )
    steps.extend(
        PlanStep(
            id=_step_id(item.operation_ref),
            kind="operation",
            name=item.operation_ref,
            operation_ref=item.operation_ref,
            evidence_refs=item.evidence_refs,
        )
        for item in request.selected_operations
    )
    return steps


def _planned_bindings(
    request: IntegrationPlannerRequest,
    steps: list[PlanStep],
) -> tuple[list[PlanBinding], list[PlanUnresolvedItem]]:
    bindings: list[PlanBinding] = []
    unresolved: list[PlanUnresolvedItem] = []
    response_fields: list[_ResponseField] = []
    auth = request.reusable_auth_subflow
    if auth is not None:
        response_fields.append(
            _ResponseField(
                name="token",
                step_id=auth.step_id,
                path=auth.token_path,
                value_type=auth.token_type,
                evidence_refs=auth.evidence_refs,
                confidence=auth.confidence,
            )
        )
    step_by_ref = {step.operation_ref: step.id for step in steps if step.operation_ref is not None}
    for selected in request.selected_operations:
        target_step = step_by_ref[selected.operation_ref]
        for required in _required_inputs(selected):
            candidates = _binding_candidates(required, response_fields)
            binding, item = _binding_from_candidates(required, target_step, candidates)
            if binding is not None:
                bindings.append(binding)
            if item is not None:
                unresolved.append(item)
        response_fields.extend(_response_fields(selected, target_step))
    return bindings, unresolved


def _required_inputs(selected: SelectedOperationEvidence) -> list[_RequiredInput]:
    contract = selected.contract
    supplied_query = {item.name for item in _scenario_request(selected.scenario).query_parameters}
    supplied_headers = {item.name.lower() for item in _scenario_request(selected.scenario).headers}
    supplied_body = (
        set(cast(dict[str, JsonValue], _scenario_request(selected.scenario).body))
        if isinstance(_scenario_request(selected.scenario).body, dict)
        else set()
    )
    required: list[_RequiredInput] = []
    if (
        contract.auth.required
        and contract.auth.location is not None
        and not selected.credential_refs
    ):
        name = contract.auth.name or ("Authorization" if contract.auth.kind == "bearer" else "auth")
        if name.lower() not in supplied_headers:
            required.append(
                _RequiredInput(
                    name="token" if contract.auth.kind == "bearer" else name,
                    location=contract.auth.location,
                    path=name,
                    value_type="string",
                    evidence_refs=[contract.auth.source_ref or selected.evidence_refs[0]],
                    auth_template="Bearer {{value}}" if contract.auth.kind == "bearer" else None,
                )
            )
    for parameter in contract.parameters:
        supplied = parameter.name in supplied_query or parameter.name.lower() in supplied_headers
        if parameter.required and not supplied:
            required.append(
                _RequiredInput(
                    name=parameter.name,
                    location=parameter.location,
                    path=parameter.name,
                    value_type=_schema_type(parameter.schema_),
                    evidence_refs=[parameter.source_ref or selected.evidence_refs[0]],
                )
            )
    schema = contract.body_schema
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required_names = schema.get("required") if isinstance(schema, dict) else None
    if isinstance(properties, dict) and isinstance(required_names, list):
        for name in sorted(str(item) for item in required_names if str(item) not in supplied_body):
            field_schema = properties.get(name)
            required.append(
                _RequiredInput(
                    name=name,
                    location="body",
                    path=name,
                    value_type=_schema_type(field_schema if isinstance(field_schema, dict) else {}),
                    evidence_refs=[selected.contract.source_ref or selected.evidence_refs[0]],
                )
            )
    return required


def _response_fields(selected: SelectedOperationEvidence, step_id: str) -> list[_ResponseField]:
    fields: dict[tuple[str, str, PlanValueType], _ResponseField] = {}
    for status, response in sorted(selected.contract.responses.items()):
        if not status.startswith("2") or not isinstance(response.schema_, dict):
            continue
        properties = response.schema_.get("properties")
        if not isinstance(properties, dict):
            continue
        for name, raw_schema in sorted(properties.items()):
            field = _ResponseField(
                name=str(name),
                step_id=step_id,
                path=f"body.{name}",
                value_type=_schema_type(raw_schema if isinstance(raw_schema, dict) else {}),
                evidence_refs=[selected.contract.source_ref or selected.evidence_refs[0]],
            )
            fields.setdefault((field.name, field.path, field.value_type), field)
    return list(fields.values())


def _binding_candidates(
    required: _RequiredInput,
    fields: list[_ResponseField],
) -> list[PlanBindingCandidate]:
    matches = [field for field in fields if field.name.lower() == required.name.lower()]
    return [
        PlanBindingCandidate(
            id=_candidate_id(required, field),
            source_kind=("setup_api" if field.step_id.startswith("setup") else "previous_response"),
            source_step_id=field.step_id,
            path=field.path,
            value_type=field.value_type,
            transform="template" if required.auth_template is not None else "identity",
            template=required.auth_template,
            confidence=field.confidence,
            evidence_refs=sorted(set([*required.evidence_refs, *field.evidence_refs])),
        )
        for field in matches
    ]


def _binding_from_candidates(
    required: _RequiredInput,
    target_step: str,
    candidates: list[PlanBindingCandidate],
) -> tuple[PlanBinding | None, PlanUnresolvedItem | None]:
    binding_id = _slug_id(f"bind-{target_step}-{required.location}-{required.path}")
    if not candidates:
        return None, PlanUnresolvedItem(
            id=_slug_id(f"missing-{binding_id}"),
            code="BINDING_EVIDENCE_MISSING",
            severity="blocker",
            message=f"字段 {required.path} 缺少可证明的上游 Evidence",
            evidence_refs=required.evidence_refs,
        )
    compatible = [
        candidate
        for candidate in candidates
        if candidate.value_type == required.value_type and candidate.value_type != "unknown"
    ]
    selected = compatible[0].id if len(candidates) == 1 and len(compatible) == 1 else None
    needs_review = selected is None and len(compatible) > 0
    severity: Literal["blocker", "review"] = "review" if needs_review else "blocker"
    unresolved = None
    if selected is None:
        unresolved = PlanUnresolvedItem(
            id=_slug_id(f"unresolved-{binding_id}"),
            code=(
                "MULTIPLE_BINDING_CANDIDATES" if len(candidates) > 1 else "BINDING_TYPE_CONFLICT"
            ),
            severity=severity,
            message=(
                f"字段 {required.path} 存在多个同型候选,禁止自动猜测"
                if len(candidates) > 1
                else f"字段 {required.path} 的候选类型不兼容"
            ),
            candidate_refs=[candidate.id for candidate in candidates],
            evidence_refs=sorted({ref for item in candidates for ref in item.evidence_refs}),
        )
    binding = PlanBinding(
        id=binding_id,
        candidates=candidates,
        selected_candidate_id=selected,
        target=PlanBindingTarget(
            step_id=target_step,
            location=required.location,
            key=required.path,
            value_type=required.value_type,
        ),
        capture_variable=(
            _slug_id(f"{candidates[0].source_step_id}-{required.name}")
            if selected is not None
            and required.location in {"path", "query", "body"}
            and candidates[0].source_kind == "previous_response"
            else None
        ),
        confidence=max(candidate.confidence for candidate in candidates),
        requires_review=needs_review,
        evidence_refs=sorted({ref for item in candidates for ref in item.evidence_refs}),
    )
    return binding, unresolved


def _planned_oracles(
    request: IntegrationPlannerRequest,
    steps: list[PlanStep],
) -> tuple[list[PlanOracle], list[PlanUnresolvedItem]]:
    step_by_ref = {step.operation_ref: step.id for step in steps if step.operation_ref is not None}
    planned: list[PlanOracle] = []
    unresolved: list[PlanUnresolvedItem] = []
    for selected in request.selected_operations:
        for oracle in selected.oracles:
            converted = _planned_oracle(oracle, step_by_ref[selected.operation_ref])
            if converted is None:
                missing_evidence = not oracle.evidence_refs and not oracle.source_ref
                unresolved.append(
                    PlanUnresolvedItem(
                        id=_slug_id(f"oracle-{selected.operation_ref}-{oracle.id}"),
                        code=(
                            "ORACLE_EVIDENCE_MISSING"
                            if missing_evidence
                            else "ORACLE_RUNTIME_UNSUPPORTED"
                        ),
                        severity="blocker",
                        message=(
                            f"Oracle {oracle.id} 缺少必要 Evidence"
                            if missing_evidence
                            else f"Oracle {oracle.id} 无法由当前 Assert Node 无损表达"
                        ),
                        evidence_refs=oracle.evidence_refs,
                    )
                )
            else:
                planned.append(converted)
    return planned, unresolved


def _planned_oracle(oracle: OracleSpec, step_id: str) -> PlanOracle | None:
    if oracle.requires_review or not oracle.deterministic:
        return None
    evidence_refs = oracle.evidence_refs or ([oracle.source_ref] if oracle.source_ref else [])
    if not evidence_refs:
        return None
    if oracle.kind == "status" and oracle.operator == "equals":
        expression = "status_code"
        kind: Literal["status", "schema", "field"] = "status"
        operator = "equals"
    elif oracle.kind == "schema" and isinstance(oracle.expected, dict):
        expression = "body"
        kind = "schema"
        operator = "equals"
    elif oracle.kind in {"json_path", "expression"} and oracle.operator in {
        "equals",
        "not_equals",
        "contains",
        "exists",
        "matches",
    }:
        expression = oracle.expression.removeprefix("$.")
        kind = "field"
        operator = oracle.operator
    else:
        return None
    return PlanOracle(
        id=_slug_id(f"{step_id}-{oracle.id}"),
        step_id=step_id,
        kind=kind,
        expression=expression,
        operator=operator,
        expected=oracle.expected,
        confidence=oracle.confidence,
        evidence_refs=evidence_refs,
    )


def _planned_coverage(
    steps: list[PlanStep], bindings: list[PlanBinding], oracles: list[PlanOracle]
) -> list[PlanCoverageTarget]:
    coverage = [
        PlanCoverageTarget(
            id=_slug_id(f"coverage-operation-{step.id}"),
            dimension="operation",
            target_ref=step.operation_ref or step.id,
            covered_by=[step.id],
            evidence_refs=step.evidence_refs,
        )
        for step in steps
        if step.operation_ref is not None
    ]
    coverage.extend(
        PlanCoverageTarget(
            id=_slug_id(f"coverage-binding-{binding.id}"),
            dimension="binding",
            target_ref=binding.id,
            covered_by=[binding.id],
            evidence_refs=binding.evidence_refs,
        )
        for binding in bindings
    )
    coverage.extend(
        PlanCoverageTarget(
            id=_slug_id(f"coverage-oracle-{oracle.id}"),
            dimension=oracle.kind,
            target_ref=oracle.id,
            covered_by=[oracle.id],
            evidence_refs=oracle.evidence_refs,
        )
        for oracle in oracles
    )
    return coverage


def _all_planner_evidence(request: IntegrationPlannerRequest) -> list[str]:
    refs = [request.target_environment.source_ref, *request.target_environment.evidence_refs]
    refs.extend(ref for actor in request.actors for ref in actor.evidence_refs)
    refs.extend(ref for item in request.preconditions for ref in item.evidence_refs)
    refs.extend(ref for item in request.selected_operations for ref in item.evidence_refs)
    refs.extend(ref for item in request.selected_operations for ref in item.credential_refs)
    if request.reusable_auth_subflow is not None:
        refs.extend(request.reusable_auth_subflow.evidence_refs)
    return sorted(set(refs))


def _identity_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    groups: tuple[tuple[str, Iterable[str]], ...] = (
        ("actor", (item.id for item in plan.actors)),
        ("precondition", (item.id for item in plan.preconditions)),
        ("operation", (item.ref for item in plan.operations)),
        ("step", (item.id for item in plan.steps)),
        ("branch", (item.id for item in plan.branches)),
        ("binding", (item.id for item in plan.bindings)),
        ("data recipe", (item.id for item in plan.data_recipes)),
        ("oracle", (item.id for item in plan.oracles)),
        ("cleanup", (item.id for item in plan.cleanup_requirements)),
        ("coverage", (item.id for item in plan.coverage_targets)),
        ("unresolved item", (item.id for item in plan.unresolved_items)),
    )
    for label, values in groups:
        items = list(values)
        if len(items) != len(set(items)):
            diagnostics.append(
                _diagnostic(
                    "DUPLICATE_PLAN_IDENTITY",
                    "blocker",
                    f"{label} identity 必须唯一",
                )
            )
    diagnostics.extend(
        _diagnostic(
            "OPERATION_NOT_USER_SELECTED",
            "blocker",
            f"Operation {operation.ref} 未记录用户显式选择证据",
            f"$.operations[{index}].selected_by_user",
            evidence_refs=operation.evidence_refs,
        )
        for index, operation in enumerate(plan.operations)
        if not operation.selected_by_user
    )
    service_names: dict[str, set[str]] = {}
    for operation in plan.operations:
        service_names.setdefault(operation.service_ref, set()).add(operation.service_name)
    diagnostics.extend(
        _diagnostic(
            "SERVICE_IDENTITY_CONFLICT",
            "blocker",
            f"Service {service_ref} 存在不一致的名称证据",
            "$.operations",
        )
        for service_ref, names in sorted(service_names.items())
        if len(names) > 1
    )
    recipe_names = [item.name for item in plan.data_recipes]
    if len(recipe_names) != len(set(recipe_names)):
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_DATA_RECIPE_NAME",
                "blocker",
                "Data Recipe name 必须唯一",
                "$.data_recipes",
            )
        )
    return diagnostics


def _reference_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    return [
        *_step_reference_diagnostics(plan),
        *_binding_reference_diagnostics(plan),
        *_cleanup_reference_diagnostics(plan),
        *_coverage_reference_diagnostics(plan),
    ]


def _step_reference_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    operations = {item.ref for item in plan.operations}
    recipes = {item.id: item for item in plan.data_recipes}
    for index, step in enumerate(plan.steps):
        if step.operation_ref is not None and step.operation_ref not in operations:
            diagnostics.append(
                _unknown_ref("UNKNOWN_OPERATION_REF", step.operation_ref, f"$.steps[{index}]")
            )
        if step.data_recipe_ref is not None and step.data_recipe_ref not in recipes:
            diagnostics.append(
                _unknown_ref("UNKNOWN_DATA_RECIPE_REF", step.data_recipe_ref, f"$.steps[{index}]")
            )
        if (
            step.data_recipe_ref is not None
            and step.data_recipe_ref in recipes
            and recipes[step.data_recipe_ref].kind != "dataset"
        ):
            diagnostics.append(
                _diagnostic(
                    "DATASET_STEP_RECIPE_KIND_INVALID",
                    "blocker",
                    "Dataset Step 必须引用 Dataset Data Recipe",
                    f"$.steps[{index}].data_recipe_ref",
                )
            )
    operation_steps = {item.operation_ref for item in plan.steps if item.operation_ref is not None}
    diagnostics.extend(
        _unknown_ref("UNPLANNED_OPERATION", ref, "$.operations")
        for ref in sorted(operations - operation_steps)
    )
    dataset_step_refs = {
        item.data_recipe_ref for item in plan.steps if item.data_recipe_ref is not None
    }
    diagnostics.extend(
        _unknown_ref("DATASET_STEP_REQUIRED", recipe.id, "$.data_recipes")
        for recipe in plan.data_recipes
        if recipe.kind == "dataset" and recipe.id not in dataset_step_refs
    )
    steps = {item.id for item in plan.steps}
    diagnostics.extend(
        _unknown_ref("UNKNOWN_ORACLE_STEP", item.step_id, f"$.oracles[{index}].step_id")
        for index, item in enumerate(plan.oracles)
        if item.step_id not in steps
    )
    diagnostics.extend(
        _unknown_ref(
            "UNKNOWN_BINDING_TARGET",
            item.target.step_id,
            f"$.bindings[{index}].target.step_id",
        )
        for index, item in enumerate(plan.bindings)
        if item.target.step_id not in steps
    )
    return diagnostics


def _binding_reference_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    steps = {item.id for item in plan.steps}
    recipes = {item.id for item in plan.data_recipes}
    for binding_index, binding in enumerate(plan.bindings):
        for candidate_index, candidate in enumerate(binding.candidates):
            if candidate.source_step_id is not None and candidate.source_step_id not in steps:
                diagnostics.append(
                    _unknown_ref(
                        "UNKNOWN_BINDING_SOURCE",
                        candidate.source_step_id,
                        f"$.bindings[{binding_index}].candidates[{candidate_index}]",
                    )
                )
            if candidate.source_recipe_id is not None and candidate.source_recipe_id not in recipes:
                diagnostics.append(
                    _unknown_ref(
                        "UNKNOWN_BINDING_RECIPE",
                        candidate.source_recipe_id,
                        f"$.bindings[{binding_index}].candidates[{candidate_index}]",
                    )
                )
    return diagnostics


def _cleanup_reference_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    operations = {item.ref for item in plan.operations}
    steps = {item.id for item in plan.steps}
    for index, requirement in enumerate(plan.cleanup_requirements):
        if requirement.operation_ref not in operations:
            diagnostics.append(
                _unknown_ref(
                    "UNKNOWN_CLEANUP_OPERATION",
                    requirement.operation_ref,
                    f"$.cleanup_requirements[{index}].operation_ref",
                )
            )
        diagnostics.extend(
            _unknown_ref(
                "UNKNOWN_CLEANUP_STEP",
                step_id,
                f"$.cleanup_requirements[{index}].cleanup_for_step_ids",
            )
            for step_id in requirement.cleanup_for_step_ids
            if step_id not in steps
        )
    return diagnostics


def _coverage_reference_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    steps = {item.id for item in plan.steps}
    bindings = {item.id for item in plan.bindings}
    branches = {item.id for item in plan.branches}
    cleanup = {item.id for item in plan.cleanup_requirements}
    oracles = {item.id for item in plan.oracles}
    coverage_refs: dict[str, set[str]] = {
        "operation": {item.ref for item in plan.operations},
        "binding": bindings,
        "status": oracles,
        "schema": oracles,
        "field": oracles,
        "branch": branches,
        "cleanup": cleanup,
    }
    diagnostics = [
        _unknown_ref(
            "UNKNOWN_COVERAGE_TARGET",
            target.target_ref,
            f"$.coverage_targets[{index}].target_ref",
        )
        for index, target in enumerate(plan.coverage_targets)
        if target.target_ref not in coverage_refs[target.dimension]
    ]
    known_coverage_items = steps | bindings | oracles | branches | cleanup
    for index, target in enumerate(plan.coverage_targets):
        diagnostics.extend(
            _unknown_ref(
                "UNKNOWN_COVERAGE_SOURCE",
                ref,
                f"$.coverage_targets[{index}].covered_by",
            )
            for ref in target.covered_by
            if ref not in known_coverage_items
        )
    return diagnostics


def _binding_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    steps = {item.id: item for item in plan.steps}
    order = {item.id: index for index, item in enumerate(plan.steps)}
    recipe_steps = {
        item.data_recipe_ref: item.id for item in plan.steps if item.data_recipe_ref is not None
    }
    variable_recipes = {
        item.name for item in plan.data_recipes if item.kind in {"runtime", "environment"}
    }
    for index, binding in enumerate(plan.bindings):
        if binding.requires_review:
            diagnostics.append(
                _diagnostic(
                    "BINDING_REVIEW_REQUIRED",
                    "review",
                    "Binding 必须完成人工审核后才能编译",
                    f"$.bindings[{index}].requires_review",
                    evidence_refs=binding.evidence_refs,
                )
            )
        selected = next(
            (item for item in binding.candidates if item.id == binding.selected_candidate_id),
            None,
        )
        if selected is None:
            diagnostics.append(
                _diagnostic(
                    "BINDING_SELECTION_REQUIRED",
                    "review" if len(binding.candidates) > 1 else "blocker",
                    "字段绑定没有已审核的唯一候选",
                    f"$.bindings[{index}].selected_candidate_id",
                    evidence_refs=binding.evidence_refs,
                )
            )
            continue
        diagnostics.extend(_selected_binding_diagnostics(binding, selected, index))
        target_step = steps.get(binding.target.step_id)
        if target_step is not None and target_step.kind != "operation":
            diagnostics.append(
                _diagnostic(
                    "BINDING_TARGET_NOT_OPERATION",
                    "blocker",
                    "WorkflowEdge Mapping 只能写入 API Operation Step",
                    f"$.bindings[{index}].target.step_id",
                    evidence_refs=binding.evidence_refs,
                )
            )
        if (
            selected.source_step_id is not None
            and selected.source_step_id in order
            and binding.target.step_id in order
            and order[selected.source_step_id] >= order[binding.target.step_id]
        ):
            diagnostics.append(
                _diagnostic(
                    "BINDING_SOURCE_ORDER_INVALID",
                    "blocker",
                    "Binding 来源步骤必须早于目标步骤",
                    f"$.bindings[{index}]",
                    evidence_refs=binding.evidence_refs,
                )
            )
        if selected.source_recipe_id is not None and selected.source_recipe_id not in recipe_steps:
            diagnostics.append(
                _diagnostic(
                    "BINDING_DATASET_STEP_MISSING",
                    "blocker",
                    "Dataset Binding 必须引用显式 Dataset Step",
                    f"$.bindings[{index}].selected_candidate_id",
                    evidence_refs=binding.evidence_refs,
                )
            )
        if (
            selected.source_kind in {"runtime_variable", "environment_variable"}
            and selected.variable_name not in variable_recipes
        ):
            diagnostics.append(
                _diagnostic(
                    "BINDING_VARIABLE_RECIPE_MISSING",
                    "blocker",
                    "Runtime/Environment Binding 必须有同名 Data Recipe",
                    f"$.bindings[{index}].selected_candidate_id",
                    evidence_refs=binding.evidence_refs,
                )
            )
    return diagnostics


def _selected_binding_diagnostics(
    binding: PlanBinding,
    selected: PlanBindingCandidate,
    index: int,
) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    scalar_types = {"string", "integer", "number", "boolean"}
    source_scalar = selected.value_type in scalar_types
    target_scalar = binding.target.value_type in scalar_types
    if "unknown" in {selected.value_type, binding.target.value_type}:
        diagnostics.append(
            _diagnostic(
                "BINDING_TYPE_UNKNOWN",
                "blocker",
                "Binding 来源与目标必须有可证明的明确类型",
                f"$.bindings[{index}]",
                evidence_refs=binding.evidence_refs,
            )
        )
    elif source_scalar != target_scalar:
        diagnostics.append(
            _diagnostic(
                "BINDING_OBJECT_SCALAR_CONFLICT",
                "blocker",
                "Object/Scalar 绑定禁止自动转换",
                f"$.bindings[{index}]",
                evidence_refs=binding.evidence_refs,
            )
        )
    elif {selected.value_type, binding.target.value_type} <= {"string", "integer", "number"}:
        if selected.value_type != binding.target.value_type:
            diagnostics.append(
                _diagnostic(
                    "BINDING_NUMERIC_STRING_REVIEW_REQUIRED",
                    "review",
                    "String/Number 转换必须人工审核",
                    f"$.bindings[{index}]",
                    evidence_refs=binding.evidence_refs,
                )
            )
    elif selected.value_type != binding.target.value_type:
        diagnostics.append(
            _diagnostic(
                "BINDING_TYPE_CONFLICT",
                "blocker",
                "绑定来源与目标类型不一致",
                f"$.bindings[{index}]",
                evidence_refs=binding.evidence_refs,
            )
        )
    if selected.transform in {"string_to_number", "number_to_string"}:
        diagnostics.append(
            _diagnostic(
                "BINDING_CONVERSION_REVIEW_REQUIRED",
                "review",
                "显式 String/Number 转换必须人工审核",
                f"$.bindings[{index}].candidates",
                evidence_refs=binding.evidence_refs,
            )
        )
    return diagnostics


def _branch_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    if not plan.branches:
        return []
    if len(plan.branches) > 1:
        return [
            _diagnostic(
                "NESTED_BRANCH_RUNTIME_UNSUPPORTED",
                "blocker",
                "Integration Plan v1 compiler 当前仅支持一个显式二分支",
                "$.branches",
            )
        ]
    branch = plan.branches[0]
    ids = [item.id for item in plan.steps]
    refs = {
        branch.source_step_id,
        branch.true_step_id,
        branch.false_step_id,
        branch.join_step_id,
    }
    diagnostics = [
        _unknown_ref("UNKNOWN_BRANCH_STEP", ref, "$.branches[0]") for ref in sorted(refs - set(ids))
    ]
    if diagnostics:
        return diagnostics
    if len(refs) != 4:
        diagnostics.append(
            _diagnostic(
                "BRANCH_STEP_IDENTITY_CONFLICT",
                "blocker",
                "Branch source/true/false/join 必须引用四个不同步骤",
                "$.branches[0]",
            )
        )
        return diagnostics
    source = ids.index(branch.source_step_id)
    true = ids.index(branch.true_step_id)
    false = ids.index(branch.false_step_id)
    join = ids.index(branch.join_step_id)
    if not (source < true < join and source < false < join):
        diagnostics.append(
            _diagnostic(
                "BRANCH_ORDER_INVALID",
                "blocker",
                "分支步骤必须位于 source 与 join 之间",
                "$.branches[0]",
            )
        )
    between = set(ids[source + 1 : join])
    if between != {branch.true_step_id, branch.false_step_id}:
        diagnostics.append(
            _diagnostic(
                "BRANCH_SHAPE_RUNTIME_UNSUPPORTED",
                "blocker",
                "首版编译器要求 true/false 分支各包含一个步骤",
                "$.branches[0]",
            )
        )
    return diagnostics


def _expression_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    expressions: list[tuple[str, str, list[str]]] = []
    expressions.extend(
        (branch.expression, f"$.branches[{index}].expression", branch.evidence_refs)
        for index, branch in enumerate(plan.branches)
    )
    expressions.extend(
        (oracle.expression, f"$.oracles[{index}].expression", oracle.evidence_refs)
        for index, oracle in enumerate(plan.oracles)
    )
    expressions.extend(
        (
            candidate.path,
            f"$.bindings[{binding_index}].candidates[{candidate_index}].path",
            candidate.evidence_refs,
        )
        for binding_index, binding in enumerate(plan.bindings)
        for candidate_index, candidate in enumerate(binding.candidates)
    )
    for expression, path, evidence_refs in expressions:
        try:
            validate_safe_expression(expression)
        except SafeExpressionError:
            diagnostics.append(
                _diagnostic(
                    "INVALID_PLAN_EXPRESSION",
                    "blocker",
                    "Integration Plan 表达式必须是有效 JMESPath",
                    path,
                    stage="validate",
                    evidence_refs=evidence_refs,
                )
            )
    for index, oracle in enumerate(plan.oracles):
        if oracle.kind == "schema":
            diagnostics.extend(_schema_diagnostics(oracle, index))
        if oracle.operator == "matches" and not isinstance(oracle.expected, str):
            diagnostics.append(
                _diagnostic(
                    "ORACLE_PATTERN_REQUIRED",
                    "blocker",
                    "Matches Oracle expected 必须是字符串",
                    f"$.oracles[{index}].expected",
                    stage="validate",
                    evidence_refs=oracle.evidence_refs,
                )
            )
        elif oracle.operator == "matches":
            try:
                re.compile(cast(str, oracle.expected))
            except re.error:
                diagnostics.append(
                    _diagnostic(
                        "INVALID_ORACLE_PATTERN",
                        "blocker",
                        "Matches Oracle 必须使用有效正则表达式",
                        f"$.oracles[{index}].expected",
                        stage="validate",
                        evidence_refs=oracle.evidence_refs,
                    )
                )
    return diagnostics


def _schema_diagnostics(oracle: PlanOracle, index: int) -> list[PlanDiagnostic]:
    if not isinstance(oracle.expected, dict):
        return [
            _diagnostic(
                "ORACLE_SCHEMA_REQUIRED",
                "blocker",
                "Schema Oracle expected 必须是 JSON Schema 对象",
                f"$.oracles[{index}].expected",
                stage="validate",
                evidence_refs=oracle.evidence_refs,
            )
        ]
    try:
        Draft202012Validator.check_schema(oracle.expected)
    except SchemaError:
        return [
            _diagnostic(
                "INVALID_ORACLE_SCHEMA",
                "blocker",
                "Schema Oracle expected 必须是有效 JSON Schema",
                f"$.oracles[{index}].expected",
                stage="validate",
                evidence_refs=oracle.evidence_refs,
            )
        ]
    external_refs = _external_schema_refs(oracle.expected)
    if external_refs:
        return [
            _diagnostic(
                "EXTERNAL_SCHEMA_REF_FORBIDDEN",
                "blocker",
                "Schema Oracle 禁止外部 $ref,避免运行时网络解析",
                f"$.oracles[{index}].expected",
                stage="validate",
                evidence_refs=oracle.evidence_refs,
            )
        ]
    return []


def _external_schema_refs(value: JsonValue) -> list[str]:
    if isinstance(value, dict):
        refs = [
            child
            for key, child in value.items()
            if key == "$ref" and isinstance(child, str) and not child.startswith("#")
        ]
        for child in value.values():
            refs.extend(_external_schema_refs(child))
        return refs
    if isinstance(value, list):
        return [ref for child in value for ref in _external_schema_refs(child)]
    return []


def _review_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics = [
        _diagnostic(
            "PLAN_REVIEW_REQUIREMENT_OPEN",
            "review",
            f"待审核项 {requirement} 未关闭",
            "$.review_requirements",
        )
        for requirement in plan.review_requirements
    ]
    diagnostics.extend(
        _diagnostic(
            "ORACLE_REVIEW_REQUIRED",
            "review",
            f"Oracle {oracle.id} 必须完成人工审核后才能编译",
            f"$.oracles[{index}].requires_review",
            evidence_refs=oracle.evidence_refs,
        )
        for index, oracle in enumerate(plan.oracles)
        if oracle.requires_review
    )
    if not plan.confidence.deterministic:
        diagnostics.append(
            _diagnostic(
                "PLAN_NON_DETERMINISTIC",
                "blocker",
                "S50 Compiler 仅接受 deterministic Integration Plan",
                "$.confidence.deterministic",
            )
        )
    return diagnostics


def _secret_literal_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    for operation_index, operation in enumerate(plan.operations):
        for group_name, values in (
            ("headers", operation.request.headers),
            ("query_parameters", operation.request.query_parameters),
        ):
            for value_index, item in enumerate(values):
                if _is_sensitive_key(item.name) and not _is_secret_reference(item.value):
                    diagnostics.append(
                        _diagnostic(
                            "SECRET_LITERAL_FORBIDDEN",
                            "blocker",
                            "敏感请求值必须使用 Secret Reference 或已审核 Auth SubFlow",
                            f"$.operations[{operation_index}].request.{group_name}[{value_index}]",
                        )
                    )
        diagnostics.extend(
            _body_secret_diagnostics(
                operation.request.body,
                f"$.operations[{operation_index}].request.body",
            )
        )
    diagnostics.extend(
        _diagnostic(
            "SECRET_LITERAL_FORBIDDEN",
            "blocker",
            "敏感 Data Recipe 不能在 Integration Plan Snapshot 中保存字面值",
            f"$.data_recipes[{index}].value",
            evidence_refs=recipe.evidence_refs,
        )
        for index, recipe in enumerate(plan.data_recipes)
        if recipe.value is not None
        and _is_sensitive_key(recipe.name)
        and not _is_secret_reference(recipe.value)
    )
    return diagnostics


def _body_secret_diagnostics(value: JsonValue, path: str) -> list[PlanDiagnostic]:
    if not isinstance(value, dict):
        return []
    diagnostics: list[PlanDiagnostic] = []
    for key, item in value.items():
        item_path = f"{path}.{key}"
        if _is_sensitive_key(key) and not _is_secret_reference(item):
            diagnostics.append(
                _diagnostic(
                    "SECRET_LITERAL_FORBIDDEN",
                    "blocker",
                    "敏感请求值不能进入 Integration Plan Snapshot",
                    item_path,
                )
            )
        else:
            diagnostics.extend(_body_secret_diagnostics(item, item_path))
    return diagnostics


def _secret_reference_runtime_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    for operation_index, operation in enumerate(plan.operations):
        request = operation.request
        for group_name, values in (
            ("headers", request.headers),
            ("query_parameters", request.query_parameters),
        ):
            diagnostics.extend(
                _diagnostic(
                    "SECRET_REFERENCE_RUNTIME_UNSUPPORTED",
                    "blocker",
                    "Secret Reference 只作为 Plan 意图证据,不得编译为请求字面值",
                    f"$.operations[{operation_index}].request.{group_name}[{value_index}]",
                    stage="compile_variables_data",
                )
                for value_index, item in enumerate(values)
                if _contains_secret_reference(item.value)
            )
        if _contains_secret_reference(request.body):
            diagnostics.append(
                _diagnostic(
                    "SECRET_REFERENCE_RUNTIME_UNSUPPORTED",
                    "blocker",
                    "Secret Reference 只作为 Plan 意图证据,不得编译为请求字面值",
                    f"$.operations[{operation_index}].request.body",
                    stage="compile_variables_data",
                )
            )
    diagnostics.extend(
        _diagnostic(
            "SECRET_REFERENCE_RUNTIME_UNSUPPORTED",
            "blocker",
            "Secret Reference Data Recipe 不能被降级为 Constant Runtime Value",
            f"$.data_recipes[{index}].value",
            stage="compile_variables_data",
            evidence_refs=recipe.evidence_refs,
        )
        for index, recipe in enumerate(plan.data_recipes)
        if recipe.value is not None and _is_secret_reference(recipe.value)
    )
    return diagnostics


def _runtime_compatibility_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    diagnostics: list[PlanDiagnostic] = []
    branch_targets = {
        step_id
        for branch in plan.branches
        for step_id in (branch.true_step_id, branch.false_step_id)
    }
    branch_sources = {
        step_id
        for branch in plan.branches
        for step_id in (branch.true_step_id, branch.false_step_id)
    }
    for index, binding in enumerate(plan.bindings):
        if binding.target.location in {"path", "cookie"}:
            diagnostics.append(
                _diagnostic(
                    "BINDING_TARGET_RUNTIME_UNSUPPORTED",
                    "blocker",
                    f"当前 WorkflowEdge mapping 不支持 {binding.target.location} target",
                    f"$.bindings[{index}].target.location",
                    stage="compile_edge_mapping",
                    evidence_refs=binding.evidence_refs,
                )
            )
        if binding.target.step_id in branch_targets:
            diagnostics.append(
                _diagnostic(
                    "BRANCH_INPUT_MAPPING_RUNTIME_UNSUPPORTED",
                    "blocker",
                    "当前 Edge Mapping 不能在不改变条件语义的前提下写入分支首节点",
                    f"$.bindings[{index}].target.step_id",
                    stage="compile_edge_mapping",
                    evidence_refs=binding.evidence_refs,
                )
            )
        selected = next(
            (item for item in binding.candidates if item.id == binding.selected_candidate_id),
            None,
        )
        if selected is not None and selected.source_kind in {"secret_ref", "external_evidence"}:
            diagnostics.append(
                _diagnostic(
                    "BINDING_SOURCE_RUNTIME_UNSUPPORTED",
                    "blocker",
                    "Secret/External Evidence 不能被当作运行时字面值读取",
                    f"$.bindings[{index}].selected_candidate_id",
                    stage="compile_variables_data",
                    evidence_refs=binding.evidence_refs,
                )
            )
        if selected is not None and selected.source_step_id in branch_sources:
            diagnostics.append(
                _diagnostic(
                    "BRANCH_OUTPUT_MAPPING_RUNTIME_UNSUPPORTED",
                    "blocker",
                    "当前 Edge Mapping 不能安全读取可能被跳过的分支步骤",
                    f"$.bindings[{index}].selected_candidate_id",
                    stage="compile_edge_mapping",
                    evidence_refs=binding.evidence_refs,
                )
            )
        if selected is not None and binding.target.location == "header":
            template = selected.template or ""
            if _has_line_break(template):
                diagnostics.append(
                    _diagnostic(
                        "REQUEST_HEADER_VALUE_INVALID",
                        "blocker",
                        "Header Mapping Template 不能包含换行符",
                        f"$.bindings[{index}].selected_candidate_id",
                        stage="compile_edge_mapping",
                        evidence_refs=binding.evidence_refs,
                    )
                )
    dataset_steps = sum(step.kind == "dataset" for step in plan.steps)
    if dataset_steps > 1:
        diagnostics.append(
            _diagnostic(
                "MULTIPLE_DATASETS_RUNTIME_UNSUPPORTED",
                "blocker",
                "当前 WorkflowDefinition 最多支持一个 Dataset Node",
                "$.steps",
                stage="compile_variables_data",
            )
        )
    diagnostics.extend(
        _diagnostic(
            "SETUP_API_RECIPE_RUNTIME_UNSUPPORTED",
            "blocker",
            "Setup API 必须解析为显式 Operation Step 后才能编译",
            f"$.data_recipes[{index}]",
            stage="compile_variables_data",
            evidence_refs=recipe.evidence_refs,
        )
        for index, recipe in enumerate(plan.data_recipes)
        if recipe.kind == "setup_api"
    )
    diagnostics.extend(_secret_reference_runtime_diagnostics(plan))
    return diagnostics


def _compile_step_nodes(
    plan: IntegrationPlan,
) -> tuple[list[FlowSpecNode], dict[str, list[str]]]:
    operations = {item.ref: item for item in plan.operations}
    recipes = {item.id: item for item in plan.data_recipes}
    nodes = [FlowSpecNode(id="start", kind="start", name="Start", position=Position(x=0, y=0))]
    evidence = {"start": list(plan.evidence_refs)}
    for index, step in enumerate(plan.steps, start=1):
        config: dict[str, JsonValue] = {}
        operation_ref = None
        target = None
        if step.kind == "operation":
            operation = operations[cast(str, step.operation_ref)]
            config = _operation_config(operation)
            operation_ref = operation.ref
            target = FlowSpecNodeTarget(service_ref=operation.service_ref)
            kind = "http"
        elif step.kind == "subflow":
            config = {
                "workflow_id": str(step.workflow_id),
                "workflow_version": step.workflow_version,
            }
            kind = "subflow"
        else:
            recipe = recipes[cast(str, step.data_recipe_ref)]
            config = {"artifact_id": str(recipe.artifact_id), "format": "auto"}
            kind = "dataset"
        nodes.append(
            FlowSpecNode(
                id=step.id,
                kind=kind,
                name=step.name,
                position=Position(x=index * 180, y=0),
                config=config,
                operation_ref=operation_ref,
                target=target,
            )
        )
        evidence[step.id] = list(step.evidence_refs)
    nodes.append(
        FlowSpecNode(
            id="end",
            kind="end",
            name="End",
            position=Position(x=(len(plan.steps) + 1) * 180, y=0),
        )
    )
    evidence["end"] = list(plan.evidence_refs)
    return nodes, evidence


def _operation_config(operation: PlanOperation) -> dict[str, JsonValue]:
    request = operation.request
    overrides: dict[str, JsonValue] = {"auth_mode": request.auth_mode}
    if request.query_parameters:
        overrides["query_parameters"] = cast(
            JsonValue,
            [
                {"name": item.name, "value": _request_string(item.value), "enabled": True}
                for item in request.query_parameters
            ],
        )
    if request.headers:
        overrides["headers"] = cast(
            JsonValue,
            {item.name: _request_string(item.value) for item in request.headers},
        )
    if request.body_kind != "none":
        overrides["body"] = {"kind": request.body_kind, "value": request.body}
    return {
        "expected_statuses": cast(JsonValue, operation.expected_statuses),
        "request_overrides": overrides,
    }


def _compile_base_edges(
    plan: IntegrationPlan,
) -> tuple[dict[tuple[str, str, str | None], FlowSpecEdge], dict[str, list[str]]]:
    chain = ["start", *(item.id for item in plan.steps), "end"]
    edges: dict[tuple[str, str, str | None], FlowSpecEdge] = {}
    evidence: dict[str, list[str]] = {}
    for source, target in pairwise(chain):
        edge = _new_edge(source, target)
        edges[(source, target, None)] = edge
        evidence[edge.id] = _refs_for_nodes(plan, source, target)
    return edges, evidence


def _compile_branches(
    plan: IntegrationPlan,
    nodes: list[FlowSpecNode],
    edges: dict[tuple[str, str, str | None], FlowSpecEdge],
    node_evidence: dict[str, list[str]],
    edge_evidence: dict[str, list[str]],
) -> None:
    if not plan.branches:
        return
    branch = plan.branches[0]
    ordered = [item.id for item in plan.steps]
    source_index = ordered.index(branch.source_step_id)
    join_index = ordered.index(branch.join_step_id)
    for source, target in zip(
        ordered[source_index:join_index],
        ordered[source_index + 1 : join_index + 1],
        strict=True,
    ):
        removed = edges.pop((source, target, None), None)
        if removed is not None:
            edge_evidence.pop(removed.id, None)
    condition_id = _slug_id(f"condition-{branch.id}")
    nodes.append(
        FlowSpecNode(
            id=condition_id,
            kind="condition",
            name=f"Condition {branch.id}",
            position=Position(x=(source_index + 1.5) * 180, y=120),
            config={
                "source_node_id": branch.source_step_id,
                "expression": branch.expression,
                "operator": branch.operator,
                "expected": branch.expected,
            },
        )
    )
    node_evidence[condition_id] = list(branch.evidence_refs)
    pairs = (
        (branch.source_step_id, condition_id, None),
        (condition_id, branch.true_step_id, "true"),
        (condition_id, branch.false_step_id, "false"),
        (branch.true_step_id, branch.join_step_id, None),
        (branch.false_step_id, branch.join_step_id, None),
    )
    for source, target, condition in pairs:
        edge = _new_edge(source, target, condition=condition)
        edges[(source, target, condition)] = edge
        edge_evidence[edge.id] = list(branch.evidence_refs)


def _compile_bindings(
    plan: IntegrationPlan,
    nodes: list[FlowSpecNode],
    edges: dict[tuple[str, str, str | None], FlowSpecEdge],
    node_evidence: dict[str, list[str]],
    edge_evidence: dict[str, list[str]],
) -> None:
    recipe_steps = {
        step.data_recipe_ref: step.id for step in plan.steps if step.data_recipe_ref is not None
    }
    for index, binding in enumerate(plan.bindings):
        selected = next(
            item for item in binding.candidates if item.id == binding.selected_candidate_id
        )
        source_id, source_path = _mapping_source(selected, recipe_steps)
        if binding.capture_variable is not None:
            source_id, source_path = _compile_extract_node(
                binding,
                selected,
                source_id,
                source_path,
                index,
                nodes,
                edges,
                node_evidence,
                edge_evidence,
            )
        mapping = FieldMapping(
            source=MappingSource(node_id=source_id, path=source_path),
            transform=MappingTransform(
                kind=(
                    MappingTransformKind.TEMPLATE
                    if selected.transform == "template"
                    else MappingTransformKind.IDENTITY
                ),
                template=selected.template or "{{value}}",
            ),
            target=MappingTarget(
                node_id=binding.target.step_id,
                location=_mapping_location(binding.target.location),
                key=binding.target.key,
            ),
        )
        edge = _edge_with_mapping(edges, source_id, binding.target.step_id, mapping)
        edge_evidence.setdefault(edge.id, []).extend(binding.evidence_refs)


def _compile_extract_node(
    binding: PlanBinding,
    selected: PlanBindingCandidate,
    source_id: str,
    source_path: str,
    index: int,
    nodes: list[FlowSpecNode],
    edges: dict[tuple[str, str, str | None], FlowSpecEdge],
    node_evidence: dict[str, list[str]],
    edge_evidence: dict[str, list[str]],
) -> tuple[str, str]:
    extract_id = _slug_id(f"extract-{binding.id}")
    nodes.append(
        FlowSpecNode(
            id=extract_id,
            kind="extract",
            name=f"Extract {binding.target.key}",
            position=Position(x=(index + 1) * 180, y=120),
            config={
                "source_node_id": source_id,
                "expression": source_path,
                "variable": binding.capture_variable,
                "required": True,
            },
        )
    )
    node_evidence[extract_id] = list(binding.evidence_refs)
    edge = _new_edge(source_id, extract_id)
    edges[(source_id, extract_id, None)] = edge
    edge_evidence[edge.id] = list(selected.evidence_refs)
    return extract_id, "value"


def _compile_oracles(
    plan: IntegrationPlan,
    nodes: list[FlowSpecNode],
    edges: dict[tuple[str, str, str | None], FlowSpecEdge],
    node_evidence: dict[str, list[str]],
    edge_evidence: dict[str, list[str]],
) -> None:
    by_step: dict[str, list[PlanOracle]] = {}
    for oracle in plan.oracles:
        by_step.setdefault(oracle.step_id, []).append(oracle)
    for step_id, oracles in by_step.items():
        outgoing = [edge for edge in tuple(edges.values()) if edge.source == step_id]
        previous = step_id
        for index, oracle in enumerate(oracles):
            assert_id = _slug_id(f"assert-{oracle.id}")
            nodes.append(
                FlowSpecNode(
                    id=assert_id,
                    kind="assert",
                    name=f"Assert {oracle.id}",
                    position=Position(x=(index + 1) * 180, y=-120),
                    config={
                        "source_node_id": step_id,
                        "expression": oracle.expression,
                        "operator": oracle.operator,
                        "expected": oracle.expected,
                        "assertion_type": (
                            "json_schema" if oracle.kind == "schema" else "comparison"
                        ),
                    },
                )
            )
            node_evidence[assert_id] = list(oracle.evidence_refs)
            inbound = _new_edge(previous, assert_id)
            edges[(previous, assert_id, None)] = inbound
            edge_evidence[inbound.id] = list(oracle.evidence_refs)
            previous = assert_id
        oracle_refs = sorted({ref for oracle in oracles for ref in oracle.evidence_refs})
        for outgoing_edge in outgoing:
            original_refs = edge_evidence.get(outgoing_edge.id, [])
            if not outgoing_edge.mappings:
                edges.pop((outgoing_edge.source, outgoing_edge.target, outgoing_edge.condition))
                edge_evidence.pop(outgoing_edge.id, None)
            linked = _new_edge(previous, outgoing_edge.target)
            edges[(previous, outgoing_edge.target, None)] = linked
            edge_evidence[linked.id] = sorted(set([*original_refs, *oracle_refs]))


def _compile_data_parameters(plan: IntegrationPlan) -> list[FlowSpecParameter]:
    parameters: list[FlowSpecParameter] = []
    for recipe in plan.data_recipes:
        if recipe.kind not in {"runtime", "environment", "constant"}:
            continue
        parameters.append(
            FlowSpecParameter(
                name=recipe.name,
                source=(
                    FlowSpecParameterSource.CONSTANT
                    if recipe.kind == "constant"
                    else FlowSpecParameterSource.RUNTIME
                ),
                value=recipe.value,
                description="",
            )
        )
    return parameters


def _compile_services(plan: IntegrationPlan) -> list[FlowSpecService]:
    services: dict[str, FlowSpecService] = {}
    for operation in plan.operations:
        services.setdefault(
            operation.service_ref,
            FlowSpecService(ref=operation.service_ref, name=operation.service_name),
        )
    return list(services.values())


def _compile_operations(plan: IntegrationPlan) -> list[FlowSpecOperation]:
    return [
        FlowSpecOperation(
            ref=operation.ref,
            service_ref=operation.service_ref,
            name=operation.name,
            method=operation.method,
            path=operation.path,
            version_strategy=operation.version_strategy,
            source_version=operation.source_version,
            contract_fingerprint=operation.contract_fingerprint,
        )
        for operation in plan.operations
    ]


def _mapping_source(
    selected: PlanBindingCandidate,
    recipe_steps: Mapping[str, str],
) -> tuple[str, str]:
    if selected.source_step_id is not None:
        return selected.source_step_id, selected.path
    if selected.source_recipe_id is not None:
        return recipe_steps[selected.source_recipe_id], selected.path
    if selected.variable_name is not None:
        name = json.dumps(selected.variable_name, ensure_ascii=False)
        return "start", f"variables.{name}"
    raise ValueError("reviewed binding source is not executable")


def _mapping_location(
    location: Literal["path", "query", "header", "cookie", "body", "workflow_variable"],
) -> MappingTargetLocation:
    return {
        "query": MappingTargetLocation.QUERY,
        "header": MappingTargetLocation.HEADER,
        "body": MappingTargetLocation.BODY,
        "workflow_variable": MappingTargetLocation.VARIABLE,
    }[location]


def _edge_with_mapping(
    edges: dict[tuple[str, str, str | None], FlowSpecEdge],
    source: str,
    target: str,
    mapping: FieldMapping,
) -> FlowSpecEdge:
    key = (source, target, None)
    current = edges.get(key)
    if current is None:
        current = _new_edge(source, target)
    updated = current.model_copy(update={"mappings": [*current.mappings, mapping]})
    edges[key] = updated
    return updated


def _new_edge(source: str, target: str, *, condition: str | None = None) -> FlowSpecEdge:
    suffix = f"-{condition}" if condition is not None else ""
    return FlowSpecEdge(
        id=_slug_id(f"edge-{source}-{target}{suffix}"),
        source=source,
        target=target,
        condition=condition,
    )


def _refs_for_nodes(plan: IntegrationPlan, source: str, target: str) -> list[str]:
    refs: list[str] = []
    by_id = {step.id: step for step in plan.steps}
    for node_id in (source, target):
        if node_id in by_id:
            refs.extend(by_id[node_id].evidence_refs)
    return sorted(set(refs or plan.evidence_refs))


def _flow_spec_diagnostics(
    validation: FlowSpecValidationResult,
    compatibility: FlowSpecCompatibilityResult,
) -> list[PlanDiagnostic]:
    diagnostics = [
        _diagnostic(
            issue.code,
            "blocker",
            issue.message,
            issue.path,
            stage="validate",
        )
        for issue in validation.issues
    ]
    diagnostics.extend(
        _diagnostic(
            issue.code,
            "blocker",
            issue.message,
            issue.path,
            stage="validate",
        )
        for issue in compatibility.blockers
    )
    diagnostics.extend(
        _diagnostic(
            issue.code,
            "warning",
            issue.message,
            issue.path,
            stage="validate",
        )
        for issue in compatibility.warnings
    )
    return diagnostics


def _cleanup_diagnostics(plan: IntegrationPlan) -> list[PlanDiagnostic]:
    if not plan.cleanup_requirements:
        return []
    return [
        _diagnostic(
            "CLEANUP_RUNTIME_DEFERRED",
            "warning",
            "Cleanup Requirement 保留在 Plan Snapshot;运行时编译在 S54 实现",
            "$.cleanup_requirements",
            stage="compile_variables_data",
            evidence_refs=sorted(
                {ref for item in plan.cleanup_requirements for ref in item.evidence_refs}
            ),
        )
    ]


def _blocked_compilation(
    plan: IntegrationPlan,
    diagnostics: list[PlanDiagnostic],
) -> IntegrationPlanCompilation:
    return IntegrationPlanCompilation(
        plan_fingerprint=plan.plan_fingerprint,
        diagnostics=diagnostics,
        passes=_pass_records(diagnostics, completed=False),
    )


def _pass_records(
    diagnostics: list[PlanDiagnostic], *, completed: bool
) -> list[CompilerPassRecord]:
    blocking_stages = {
        item.compiler_pass or "normalize"
        for item in diagnostics
        if item.severity in {"blocker", "review"}
    }
    blocked_pass = next((name for name in _COMPILER_PASSES if name in blocking_stages), None)
    records: list[CompilerPassRecord] = []
    blocked_seen = False
    for name in _COMPILER_PASSES:
        codes = sorted(
            {item.code for item in diagnostics if (item.compiler_pass or "normalize") == name}
        )
        if blocked_pass == name:
            status: Literal["completed", "blocked", "skipped"] = "blocked"
            blocked_seen = True
        elif blocked_seen or (not completed and blocked_pass is None):
            status = "skipped"
        else:
            status = "completed"
        records.append(CompilerPassRecord(name=name, status=status, diagnostic_codes=codes))
    return records


def _schema_type(schema: Mapping[str, object]) -> PlanValueType:
    value = schema.get("type")
    if value in {"string", "integer", "number", "boolean", "object", "array", "null"}:
        return value
    return "unknown"


def _step_id(operation_ref: str) -> str:
    return _slug_id(operation_ref.replace(".", "-"))


def _candidate_id(required: _RequiredInput, field: _ResponseField) -> str:
    return _slug_id(
        f"candidate-{field.step_id}-{field.name}-{field.value_type}-{required.location}"
    )


def _slug_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-") or "item"
    if not (slug[0].isalpha() or slug[0] == "_"):
        slug = f"item-{slug}"
    if len(slug) <= 120:
        return slug
    digest = sha256(slug.encode()).hexdigest()[:12]
    return f"{slug[:107]}-{digest}"


def _flow_name(objective: str) -> str:
    name = " ".join(objective.split())
    return name[:200]


def _request_string(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _has_line_break(value: str) -> bool:
    return "\r" in value or "\n" in value


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _is_sensitive_key(value: str) -> bool:
    if _SENSITIVE_KEY.search(value):
        return True
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    suffixes = (
        "authorization",
        "cookie",
        "password",
        "passwd",
        "secret",
        "token",
        "apikey",
        "accesskey",
        "privatekey",
        "credential",
    )
    return normalized.startswith(("authorization", "cookie")) or normalized.endswith(suffixes)


def _contains_secret_reference(value: JsonValue) -> bool:
    if _is_secret_reference(value):
        return True
    if isinstance(value, dict):
        return any(_contains_secret_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret_reference(item) for item in value)
    return False


def _is_secret_reference(value: JsonValue) -> bool:
    return isinstance(value, str) and re.fullmatch(_SECRET_REF, value) is not None


def _unknown_ref(code: str, ref: str, path: str) -> PlanDiagnostic:
    return _diagnostic(code, "blocker", f"引用 {ref} 不存在", path)


def _diagnostic(
    code: str,
    severity: PlanDiagnosticSeverity,
    message: str,
    path: str = "$",
    *,
    stage: str | None = None,
    evidence_refs: list[str] | None = None,
) -> PlanDiagnostic:
    return PlanDiagnostic(
        code=code,
        severity=severity,
        message=message,
        path=path,
        compiler_pass=stage,
        evidence_refs=evidence_refs or [],
    )


def _unique_diagnostics(diagnostics: Iterable[PlanDiagnostic]) -> list[PlanDiagnostic]:
    unique: dict[tuple[str, str, str, str], PlanDiagnostic] = {}
    for item in diagnostics:
        unique[(item.code, item.severity, item.path, item.message)] = item
    return sorted(
        unique.values(),
        key=lambda item: (item.severity, item.code, item.path, item.message),
    )


def _evidence_traces(values: Mapping[str, list[str]]) -> list[CompilerEvidenceTrace]:
    return [
        CompilerEvidenceTrace(resource_id=resource_id, evidence_refs=sorted(set(refs)))
        for resource_id, refs in sorted(values.items())
        if refs
    ]
