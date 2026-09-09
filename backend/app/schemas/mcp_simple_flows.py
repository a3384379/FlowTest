"""Small, typed contracts for quick MCP flow proposals.

The quick contract deliberately describes user intent rather than the internal
FlowSpec graph.  The server resolves API IDs and versions and creates the
reviewable FlowSpec draft after the same structural checks used by deep flows.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

SimpleInputType = Literal["string", "number", "integer", "boolean", "object", "array"]
SimpleBindingKind = Literal["input", "previous_output", "constant"]
SimpleAssertionOperator = Literal["equals", "not_equals", "contains", "exists", "status_code"]


class SimpleFlowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,159}$")
    type: SimpleInputType
    required: bool = True
    default: JsonValue = None
    description: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_default_type(self) -> "SimpleFlowInput":
        if self.default is None:
            return self
        valid = {
            "string": isinstance(self.default, str),
            "number": isinstance(self.default, (int, float)) and not isinstance(self.default, bool),
            "integer": isinstance(self.default, int) and not isinstance(self.default, bool),
            "boolean": isinstance(self.default, bool),
            "object": isinstance(self.default, dict),
            "array": isinstance(self.default, list),
        }[self.type]
        if not valid:
            raise ValueError("input default does not match declared type")
        return self


class SimpleApiReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_definition_id: UUID
    version: int = Field(ge=1)


class SimpleBindingSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SimpleBindingKind
    name: str | None = Field(default=None, min_length=1, max_length=500)
    value: JsonValue = None

    @model_validator(mode="after")
    def validate_source(self) -> "SimpleBindingSource":
        if self.kind in {"input", "previous_output"} and not self.name:
            raise ValueError("input and previous_output bindings require name")
        if self.kind == "constant" and "value" not in self.model_fields_set:
            raise ValueError("constant bindings require value")
        if self.kind != "constant" and self.value is not None:
            raise ValueError("only constant bindings may contain value")
        return self


class SimpleBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(pattern=r"^(?:query|header|body|variable)\.[A-Za-z_][A-Za-z0-9_.-]{0,159}$")
    source: SimpleBindingSource


class SimpleAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, max_length=500)
    operator: SimpleAssertionOperator
    expected: JsonValue = None


class SimplePolling(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=20)
    interval_seconds: float = Field(default=0, ge=0, le=60)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class SimpleFlowOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,159}$")
    source: str = Field(min_length=1, max_length=500)


class SimpleFlowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.:-]{0,119}$")
    name: str = Field(min_length=1, max_length=200)
    api: SimpleApiReference
    bindings: list[SimpleBinding] = Field(default_factory=list, max_length=200)
    assertions: list[SimpleAssertion] = Field(default_factory=list, max_length=20)
    polling: SimplePolling | None = None
    outputs: list[SimpleFlowOutput] = Field(default_factory=list, max_length=20)


class SimpleFlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-simple-flow-v1"] = "flowtest-simple-flow-v1"
    project_id: UUID
    environment_id: UUID
    name: str = Field(min_length=1, max_length=200)
    task_ref: str = Field(pattern=r"^\S{1,160}$")
    scenario_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,159}$")
    inputs: list[SimpleFlowInput] = Field(default_factory=list, max_length=100)
    steps: list[SimpleFlowStep] = Field(min_length=1, max_length=10)
    workflow_id: UUID | None = None
    proposal_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    source_ref: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_unique_names(self) -> "SimpleFlowRequest":
        input_names = [item.name for item in self.inputs]
        if len(input_names) != len(set(input_names)):
            raise ValueError("quick flow input names must be unique")
        step_keys = [item.key for item in self.steps]
        if len(step_keys) != len(set(step_keys)):
            raise ValueError("quick flow step keys must be unique")
        if self.proposal_id is not None and self.expected_revision is None:
            raise ValueError("proposal revisions require proposal_id and expected_revision")
        if (
            self.proposal_id is None
            and self.workflow_id is None
            and self.expected_revision is not None
        ):
            raise ValueError("expected_revision requires workflow_id when creating a proposal")
        return self


class SimpleFlowDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    node_key: str | None = Field(default=None, max_length=120)
    field_path: str = Field(min_length=1, max_length=500)
    expected: str | None = Field(default=None, max_length=500)
    actual: str | None = Field(default=None, max_length=500)
    repair_hint: str = Field(default="", max_length=1000)
    retryable: bool = False


class SimpleFlowProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flowtest-simple-flow-proposal-v1"] = "flowtest-simple-flow-proposal-v1"
    project_id: UUID
    environment_id: UUID
    proposal_id: UUID
    proposal_revision: int = Field(ge=1)
    generation_mode: Literal["quick"] = "quick"
    status: Literal["draft_created", "incomplete", "invalid"]
    static_validation: Literal["passed", "failed"]
    readiness: Literal["ready", "needs_input"]
    missing_inputs: list[str] = Field(default_factory=list, max_length=100)
    execution_status: Literal["not_run"] = "not_run"
    review_url: str = Field(max_length=1024)
    diagnostics: list[SimpleFlowDiagnostic] = Field(default_factory=list, max_length=500)
    timings_ms: dict[str, int] = Field(default_factory=dict, max_length=20)
    flow_spec_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_workflow_id: UUID | None = None
    target_revision: int | None = None
    source_ref: str = Field(max_length=512)
    idempotency_replayed: bool = False
