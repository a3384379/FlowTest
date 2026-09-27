from enum import StrEnum
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    field_validator,
    model_validator,
)

from app.domain.api_assets import BodyKind
from app.domain.assertions import ComparisonOperator
from app.domain.capabilities import CapabilityId, SemanticVersion

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]
CONTROL_MAX_REGION_DEPTH = 4


class RuntimeInputDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: VariableName
    value_type: Literal["string", "number", "integer", "boolean", "object", "array"]
    required: bool = True
    nullable: bool = False
    description: str = Field(default="", max_length=1000)


class ApiPollingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=500)
    operator: ComparisonOperator = ComparisonOperator.EQUALS
    expected: JsonValue = None
    terminal_failure_values: tuple[JsonValue, ...] = Field(default=(), max_length=20)
    max_attempts: int = Field(default=1, ge=1, le=20)
    interval_seconds: float = Field(default=0, ge=0, le=60)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class NodeType(StrEnum):
    START = "start"
    API = "api"
    EXTRACT = "extract"
    ASSERT = "assert"
    CONDITION = "condition"
    DELAY = "delay"
    DATASET = "dataset"
    SUBFLOW = "subflow"
    FOR_EACH = "for_each"
    SQL = "sql"
    REDIS = "redis"
    CAPABILITY = "capability"
    END = "end"


CAPABILITY_LEGACY_NODE_TYPES: dict[tuple[str, str], NodeType] = {
    ("flow.start", "2.0.0"): NodeType.START,
    ("http.request", "2.0.0"): NodeType.API,
    ("data.extract", "2.0.0"): NodeType.EXTRACT,
    ("assertion.evaluate", "2.0.0"): NodeType.ASSERT,
    ("flow.condition", "2.0.0"): NodeType.CONDITION,
    ("flow.delay", "2.0.0"): NodeType.DELAY,
    ("data.dataset", "2.0.0"): NodeType.DATASET,
    ("flow.subflow", "2.0.0"): NodeType.SUBFLOW,
    ("flow.foreach", "2.0.0"): NodeType.FOR_EACH,
    ("sql.query", "2.0.0"): NodeType.SQL,
    ("redis.read", "2.0.0"): NodeType.REDIS,
    ("flow.end", "2.0.0"): NodeType.END,
}


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self is not NodeStatus.PENDING and self is not NodeStatus.RUNNING


class WorkflowRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowPhase(StrEnum):
    MAIN = "main"
    CLEANUP = "cleanup"


class CleanupRunWhen(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCEL = "cancel"
    ALWAYS = "always"


class RetryCategory(StrEnum):
    NETWORK_ERROR = "network_error"
    SERVER_ERROR = "5xx"


class MappingTransformKind(StrEnum):
    IDENTITY = "identity"
    TEMPLATE = "template"
    JSON_PARSE = "json_parse"


class MappingTargetLocation(StrEnum):
    QUERY = "query"
    HEADER = "header"
    BODY = "body"
    VARIABLE = "variable"


class DatasetFormat(StrEnum):
    AUTO = "auto"
    CSV = "csv"
    JSON = "json"
    EXCEL = "excel"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class MappingSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=500)


class MappingTransform(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MappingTransformKind = MappingTransformKind.IDENTITY
    template: str = Field(default="{{value}}", max_length=4000)


class MappingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    location: MappingTargetLocation
    key: str = Field(min_length=1, max_length=500)


class FieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: MappingSource
    transform: MappingTransform = Field(default_factory=MappingTransform)
    target: MappingTarget


class CapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)
    expression: str = Field(min_length=1, max_length=2000)


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    type: NodeType
    name: str = Field(min_length=1, max_length=200)
    position: Position
    config: dict[str, JsonValue] = Field(default_factory=dict)
    capability_id: CapabilityId | None = None
    capability_version: SemanticVersion | None = None
    configuration: dict[str, JsonValue] | None = None
    bindings: list[CapabilityBinding] | None = None
    phase: WorkflowPhase = WorkflowPhase.MAIN
    run_when: CleanupRunWhen = CleanupRunWhen.ALWAYS
    cleanup_for: list[str] = Field(default_factory=list, max_length=200)
    best_effort: bool = False
    cleanup_timeout_seconds: int = Field(default=30, ge=1, le=300)
    cleanup_retry_budget: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def validate_capability_contract(self) -> "WorkflowNode":
        capability_fields = (
            self.capability_id,
            self.capability_version,
            self.configuration,
            self.bindings,
        )
        if self.type is NodeType.CAPABILITY:
            if self.capability_id is None or self.capability_version is None:
                raise ValueError("Capability node must pin capability ID and version")
            if self.configuration is None or self.bindings is None:
                raise ValueError("Capability node must declare configuration and bindings")
            if self.config:
                raise ValueError("Capability node cannot use the legacy config field")
            inputs = [binding.input for binding in self.bindings]
            if len(inputs) != len(set(inputs)):
                raise ValueError("Capability binding inputs must be unique")
        elif any(value is not None for value in capability_fields):
            raise ValueError("Legacy node cannot declare V3 capability fields")
        if self.phase is WorkflowPhase.MAIN and (
            self.run_when is not CleanupRunWhen.ALWAYS
            or self.cleanup_for
            or self.best_effort
            or self.cleanup_timeout_seconds != 30
            or self.cleanup_retry_budget != 0
        ):
            raise ValueError("Main nodes cannot declare cleanup execution metadata")
        if self.phase is WorkflowPhase.CLEANUP and self.effective_type in {
            NodeType.START,
            NodeType.END,
            NodeType.DATASET,
        }:
            raise ValueError("Cleanup nodes cannot use workflow boundary or dataset types")
        return self

    @property
    def effective_type(self) -> NodeType:
        if self.type is not NodeType.CAPABILITY:
            return self.type
        if self.capability_id is None or self.capability_version is None:
            return NodeType.CAPABILITY
        return CAPABILITY_LEGACY_NODE_TYPES.get(
            (self.capability_id, self.capability_version),
            NodeType.CAPABILITY,
        )

    @property
    def effective_config(self) -> dict[str, JsonValue]:
        return self.config if self.type is not NodeType.CAPABILITY else self.configuration or {}


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    source: str
    target: str
    condition: str | None = None
    mappings: list[FieldMapping] = Field(default_factory=list)


class LiteralValueSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["literal"]
    value: JsonValue


class VariableValueSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["variable"]
    scope: Literal["runtime", "workflow", "input", "local", "loop", "state", "error"]
    path: tuple[str | StrictInt, ...] = Field(min_length=1, max_length=32)


class NodeOutputValueSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["node_output"]
    node_id: str = Field(min_length=1, max_length=128)
    path: tuple[str | StrictInt, ...] = Field(default=(), max_length=32)


ValueSource = Annotated[
    LiteralValueSource | VariableValueSource | NodeOutputValueSource,
    Field(discriminator="kind"),
]


class InlineControlBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["inline"]
    region_id: str = Field(min_length=1, max_length=128)


class ReferencedControlBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["workflow_ref"]
    workflow_id: UUID
    workflow_version: int = Field(ge=1)


ControlBody = Annotated[
    InlineControlBody | ReferencedControlBody,
    Field(discriminator="kind"),
]


class ControlLoopPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=1, ge=1, le=20)
    max_iterations: int = Field(default=1000, ge=1, le=1000)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    on_error: Literal["stop", "continue_collect"] = "stop"


class ForEachControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: ValueSource
    body: ControlBody
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ControlLoopPolicy = Field(default_factory=ControlLoopPolicy)
    min_items: int = Field(default=0, ge=0, le=1000)
    collect: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)


class RepeatControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: StrictInt = Field(default=3, ge=1, le=1000)
    body: ControlBody
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ControlLoopPolicy = Field(default_factory=ControlLoopPolicy)
    collect: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)


class StateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["set", "add", "append"]
    value: ValueSource


class ConditionLoopPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: Literal[1] = 1
    max_iterations: int = Field(default=100, ge=1, le=1000)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    on_error: Literal["stop"] = "stop"


class ConditionLoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: "ConditionExpression"
    body: ControlBody
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    state: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    update: dict[VariableName, StateUpdate] = Field(default_factory=dict, max_length=100)
    collect: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ConditionLoopPolicy = Field(default_factory=ConditionLoopPolicy)

    @model_validator(mode="after")
    def validate_condition_loop(self) -> "ConditionLoopConfig":
        self.condition.validate_budget()
        if set(self.update) - set(self.state):
            raise ValueError("State updates must target declared state")
        return self


class ControlSignalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParallelBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)
    body: ControlBody


class ParallelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=2, ge=1, le=20)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    on_error: Literal["stop_on_error", "collect_all"] = "stop_on_error"


class ParallelControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branches: list[ParallelBranch] = Field(min_length=2, max_length=20)
    join: Literal["all"] = "all"
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ParallelPolicy = Field(default_factory=ParallelPolicy)

    @model_validator(mode="after")
    def validate_branch_ids(self) -> "ParallelControlConfig":
        ids = [branch.id for branch in self.branches]
        if len(ids) != len(set(ids)):
            raise ValueError("Parallel branch IDs must be unique")
        return self


class ControlBlockPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(default=120, ge=1, le=3600)


class TryCatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)
    error_codes: list[str] = Field(min_length=1, max_length=20)
    body: ControlBody

    @field_validator("error_codes")
    @classmethod
    def validate_error_codes(cls, codes: list[str]) -> list[str]:
        if any(not code.strip() or code != code.strip() or len(code) > 100 for code in codes):
            raise ValueError("Catch error codes must be trimmed and at most 100 characters")
        if len(codes) != len(set(codes)):
            raise ValueError("Catch error codes must be unique")
        return codes


class TryControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    try_body: ControlBody
    catches: list[TryCatch] = Field(default_factory=list, max_length=20)
    finally_body: ControlBody | None = None
    expected_error_codes: list[str] = Field(default_factory=list, max_length=20)
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ControlBlockPolicy = Field(default_factory=ControlBlockPolicy)

    @field_validator("expected_error_codes")
    @classmethod
    def validate_expected_error_codes(cls, codes: list[str]) -> list[str]:
        if any(not code.strip() or code != code.strip() or len(code) > 100 for code in codes):
            raise ValueError("Expected error codes must be trimmed and at most 100 characters")
        if len(codes) != len(set(codes)):
            raise ValueError("Expected error codes must be unique")
        return codes

    @model_validator(mode="after")
    def validate_catches(self) -> "TryControlConfig":
        if not self.catches and self.finally_body is None:
            raise ValueError("Try requires Catch or Finally")
        ids = [item.id for item in self.catches]
        if len(ids) != len(set(ids)):
            raise ValueError("Catch IDs must be unique")
        return self


class StepGroupControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: ControlBody
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ControlBlockPolicy = Field(default_factory=ControlBlockPolicy)


class FailControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)


class ReturnControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)


class ConditionExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["compare", "all", "any", "not"]
    left: ValueSource | None = None
    operator: (
        Literal[
            "equals",
            "not_equals",
            "gt",
            "gte",
            "lt",
            "lte",
            "contains",
            "in",
            "exists",
            "not_exists",
            "is_null",
            "not_null",
            "is_empty",
            "not_empty",
            "length_equals",
            "length_gt",
            "length_lt",
        ]
        | None
    ) = None
    right: ValueSource | None = None
    conditions: list["ConditionExpression"] | None = Field(default=None, max_length=100)
    condition: "ConditionExpression | None" = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ConditionExpression":
        if self.kind == "compare":
            if self.left is None or self.operator is None:
                raise ValueError("Compare condition requires left and operator")
            requires_right = self.operator not in {
                "exists",
                "not_exists",
                "is_null",
                "not_null",
                "is_empty",
                "not_empty",
            }
            if (self.right is None) != (not requires_right):
                raise ValueError("Compare condition has an invalid right operand")
            if self.conditions is not None or self.condition is not None:
                raise ValueError("Compare condition cannot contain child conditions")
        elif self.kind in {"all", "any"}:
            if not self.conditions or self.left or self.right or self.operator or self.condition:
                raise ValueError("Condition group requires only non-empty conditions")
        elif self.condition is None or self.left or self.right or self.operator or self.conditions:
            raise ValueError("Not condition requires one child")
        return self

    def validate_budget(self) -> None:
        pending = [(self, 1)]
        leaves = 0
        while pending:
            item, depth = pending.pop()
            if depth > 8:
                raise ValueError("Condition expression exceeds maximum depth")
            if item.kind == "compare":
                leaves += 1
            else:
                children = item.conditions or ([item.condition] if item.condition else [])
                pending.extend((child, depth + 1) for child in children)
        if leaves > 100:
            raise ValueError("Condition expression exceeds maximum comparisons")


class IfControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: ConditionExpression
    true_body: ControlBody
    false_body: ControlBody
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ControlBlockPolicy = Field(default_factory=ControlBlockPolicy)

    @model_validator(mode="after")
    def validate_expression(self) -> "IfControlConfig":
        self.condition.validate_budget()
        return self


class SwitchBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)
    body: ControlBody
    match: ValueSource | None = None
    condition: ConditionExpression | None = None


class SwitchDefault(BaseModel):
    model_config = ConfigDict(extra="forbid")

    behavior: Literal["run", "skip", "fail"] = "run"
    body: ControlBody | None = None

    @model_validator(mode="after")
    def validate_body(self) -> "SwitchDefault":
        if (self.body is not None) != (self.behavior == "run"):
            raise ValueError("Switch default body must match behavior")
        return self


class SwitchControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["value", "rules"]
    value: ValueSource | None = None
    match_policy: Literal["first_match"] = "first_match"
    branches: list[SwitchBranch] = Field(min_length=1, max_length=100)
    default: SwitchDefault
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    policy: ControlBlockPolicy = Field(default_factory=ControlBlockPolicy)

    @model_validator(mode="after")
    def validate_branches(self) -> "SwitchControlConfig":
        if (self.value is not None) != (self.mode == "value"):
            raise ValueError("Switch value must match mode")
        ids = [branch.id for branch in self.branches]
        if len(ids) != len(set(ids)):
            raise ValueError("Switch branch IDs must be unique")
        matches: set[str] = set()
        for branch in self.branches:
            if (branch.match is not None) != (self.mode == "value") or (
                (branch.condition is not None) != (self.mode == "rules")
            ):
                raise ValueError("Switch branch match must match mode")
            if branch.condition is not None:
                branch.condition.validate_budget()
            if isinstance(branch.match, LiteralValueSource):
                key = branch.match.model_dump_json()
                if key in matches:
                    raise ValueError("Switch contains duplicate literal matches")
                matches.add(key)
        return self


CONTROL_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "flow.control.foreach": ForEachControlConfig,
    "flow.control.repeat": RepeatControlConfig,
    "flow.control.if": IfControlConfig,
    "flow.control.switch": SwitchControlConfig,
    "flow.control.while": ConditionLoopConfig,
    "flow.control.do_while": ConditionLoopConfig,
    "flow.control.until": ConditionLoopConfig,
    "flow.control.break": ControlSignalConfig,
    "flow.control.continue": ControlSignalConfig,
    "flow.control.parallel": ParallelControlConfig,
    "flow.control.try": TryControlConfig,
    "flow.control.group": StepGroupControlConfig,
    "flow.control.fail": FailControlConfig,
    "flow.control.return": ReturnControlConfig,
}


class WorkflowRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    owner_node_id: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=80)
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=1000)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=2000)
    entry_node_id: str | None = Field(default=None, max_length=128)
    exit_node_ids: list[str] = Field(default_factory=list, max_length=100)
    inputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)
    outputs: dict[VariableName, ValueSource] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def validate_region_graph(self) -> "WorkflowRegion":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError(f"Region {self.id} contains duplicate node IDs")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError(f"Region {self.id} contains duplicate edge IDs")
        known = set(node_ids)
        if not known:
            if self.entry_node_id is not None or self.exit_node_ids or self.edges:
                raise ValueError(f"Empty region {self.id} cannot declare graph boundaries")
            return self
        if self.entry_node_id not in known or not self.exit_node_ids:
            raise ValueError(f"Region {self.id} requires an entry and exits")
        if set(self.exit_node_ids) - known:
            raise ValueError(f"Region {self.id} references unknown exits")
        incoming, outgoing = _region_adjacency(self, known)
        _validate_region_paths(self, known, incoming, outgoing)
        if any(node.phase is not WorkflowPhase.MAIN for node in self.nodes):
            raise ValueError(f"Region {self.id} cannot contain cleanup-phase nodes")
        return self


def _region_adjacency(
    region: WorkflowRegion, known: set[str]
) -> tuple[dict[str, int], dict[str, set[str]]]:
    incoming = dict.fromkeys(known, 0)
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in known}
    for edge in region.edges:
        if edge.source not in known or edge.target not in known:
            raise ValueError(f"Edge {edge.id} points outside region {region.id}")
        if edge.condition is not None or any(
            mapping.source.node_id != edge.source or mapping.target.node_id != edge.target
            for mapping in edge.mappings
        ):
            raise ValueError(f"Region {region.id} has an invalid edge {edge.id}")
        incoming[edge.target] += 1
        outgoing[edge.source].add(edge.target)
        if len(outgoing[edge.source]) > 1:
            raise ValueError(f"Region {region.id} has an implicit branch at {edge.source}")
    return incoming, outgoing


def _validate_region_paths(
    region: WorkflowRegion,
    known: set[str],
    incoming: dict[str, int],
    outgoing: dict[str, set[str]],
) -> None:
    entry = cast(str, region.entry_node_id)
    if incoming[entry] != 0:
        raise ValueError(f"Region {region.id} entry has incoming edges")
    ready = [node_id for node_id, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for target in outgoing[current]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(known):
        raise ValueError(f"Region {region.id} contains a cycle")
    if _walk(entry, outgoing) != known:
        raise ValueError(f"Region {region.id} contains unreachable nodes")
    reverse: dict[str, set[str]] = {node_id: set() for node_id in known}
    for edge in region.edges:
        reverse[edge.target].add(edge.source)
    reaches_exit: set[str] = set()
    for exit_id in region.exit_node_ids:
        reaches_exit.update(_walk(exit_id, reverse))
    if reaches_exit != known:
        raise ValueError(f"Region {region.id} contains nodes without an exit")


class WorkflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fail_fast: bool = True
    concurrency: int = Field(default=20, ge=1, le=100)
    default_timeout_seconds: int = Field(default=30, ge=1, le=300)


class WorkflowRunPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_budget: int | None = Field(default=None, ge=1, le=10_000)
    max_runtime_seconds: int | None = Field(default=None, ge=1, le=3600)
    cleanup_request_budget: int | None = Field(default=None, ge=1, le=1000)
    force_cancel_skips_cleanup: bool = False


class StartNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic_variables: dict[
        VariableName,
        Literal["uuid", "unique_string", "positive_integer"],
    ] = Field(default_factory=dict, max_length=100)


class ApiNodeRequestParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    value: str = Field(default="", max_length=65536)
    enabled: bool = True


class ApiNodeBodyOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: BodyKind
    value: JsonValue = None

    @model_validator(mode="after")
    def validate_body_shape(self) -> "ApiNodeBodyOverride":
        if self.kind is BodyKind.MULTIPART:
            ApiNodeMultipartBody.model_validate(self.value)
        if self.kind is BodyKind.NONE and self.value is not None:
            raise ValueError("A none body override must use a null value")
        return self


class ApiNodeMultipartFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=160)
    artifact_id: UUID


class ApiNodeMultipartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, str] = Field(default_factory=dict)
    files: tuple[ApiNodeMultipartFile, ...] = Field(default=(), max_length=20)


class ApiNodeRequestOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_parameters: tuple[ApiNodeRequestParameter, ...] | None = Field(
        default=None,
        max_length=200,
    )
    headers: dict[str, str] | None = None
    body: ApiNodeBodyOverride | None = None
    replace_headers: bool = False
    auth_disabled: bool = False
    auth_mode: Literal["inherit", "disabled"] | None = None
    suppressed_headers: tuple[str, ...] = Field(default=(), max_length=200)
    suppressed_query_parameters: tuple[str, ...] = Field(default=(), max_length=200)
    suppressed_cookies: tuple[str, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def validate_suppression_names(self) -> "ApiNodeRequestOverrides":
        groups = (
            (self.suppressed_headers, True),
            (self.suppressed_query_parameters, False),
            (self.suppressed_cookies, False),
        )
        for names, case_insensitive in groups:
            if any(not name.strip() or any(char in name for char in "\r\n:;") for name in names):
                raise ValueError("request suppression names must be valid HTTP token names")
            normalized = [name.lower() if case_insensitive else name for name in names]
            if len(normalized) != len(set(normalized)):
                raise ValueError("request suppression names must be unique")
        return self

    @property
    def effective_auth_mode(self) -> Literal["inherit", "disabled"]:
        if self.auth_mode is not None:
            return self.auth_mode
        return "disabled" if self.auth_disabled else "inherit"


class ApiNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_definition_id: UUID
    api_version: int | None = Field(default=None, ge=1)
    service_override: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$",
        max_length=160,
    )
    endpoint_variant: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$",
        max_length=80,
    )
    expected_statuses: tuple[int, ...] | None = Field(default=None, min_length=1, max_length=20)
    request_overrides: ApiNodeRequestOverrides = Field(default_factory=ApiNodeRequestOverrides)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int = Field(default=0, ge=0, le=3)
    retry_on: tuple[RetryCategory, ...] = Field(
        default=(RetryCategory.NETWORK_ERROR, RetryCategory.SERVER_ERROR),
        min_length=1,
        max_length=2,
    )
    retry_delay_seconds: float = Field(default=0, ge=0, le=60)
    polling: ApiPollingConfig | None = None

    @model_validator(mode="after")
    def validate_retry_categories(self) -> "ApiNodeConfig":
        if len(self.retry_on) != len(set(self.retry_on)):
            raise ValueError("Retry categories must be unique")
        if self.expected_statuses is not None:
            if len(self.expected_statuses) != len(set(self.expected_statuses)):
                raise ValueError("Expected statuses must be unique")
            if any(status < 100 or status > 599 for status in self.expected_statuses):
                raise ValueError("Expected statuses must be valid HTTP status codes")
        return self


class ExtractNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: str = Field(min_length=1, max_length=128)
    expression: str = Field(min_length=1, max_length=500)
    variable: VariableName
    required: bool = True


class AssertNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: str = Field(min_length=1, max_length=128)
    expression: str = Field(min_length=1, max_length=500)
    operator: ComparisonOperator = ComparisonOperator.EQUALS
    expected: JsonValue = None
    expected_source_node_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_expression: str | None = Field(default=None, min_length=1, max_length=500)
    assertion_type: Literal["comparison", "json_schema"] = "comparison"

    @model_validator(mode="after")
    def validate_expected_source(self) -> "AssertNodeConfig":
        has_node = self.expected_source_node_id is not None
        has_expression = self.expected_expression is not None
        if has_node != has_expression:
            raise ValueError("dynamic assertions require both expected source fields")
        if has_node and self.assertion_type != "comparison":
            raise ValueError("dynamic expected values only support comparison assertions")
        return self


class ConditionNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: str = Field(min_length=1, max_length=128)
    expression: str = Field(min_length=1, max_length=500)
    operator: ComparisonOperator = ComparisonOperator.EQUALS
    expected: JsonValue = None


class DelayNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(ge=0, le=300)


class DatasetNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    format: DatasetFormat = DatasetFormat.AUTO
    sheet_name: str | None = Field(default=None, min_length=1, max_length=128)


class SubFlowNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    workflow_version: int = Field(ge=1)


class ForEachNodeConfig(SubFlowNodeConfig):
    source_node_id: str = Field(min_length=1, max_length=128)
    expression: str = Field(min_length=1, max_length=500)
    item_variable: VariableName = "item"
    index_variable: VariableName = "index"
    concurrency: int = Field(default=5, ge=1, le=20)
    fail_fast: bool = True


class SqlNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: UUID
    query: str = Field(min_length=1, max_length=100_000)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=30)


class RedisNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: UUID
    command: str = Field(min_length=3, max_length=16)
    arguments: list[str] = Field(min_length=1, max_length=100)
    timeout_seconds: int = Field(default=30, ge=1, le=30)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "2.0", "3.0", "4.0"] = "1.0"
    variables: dict[VariableName, str] = Field(default_factory=dict)
    runtime_inputs: list[RuntimeInputDefinition] = Field(default_factory=list, max_length=1000)
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    regions: list[WorkflowRegion] = Field(default_factory=list, max_length=500)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    run_policy: WorkflowRunPolicy = Field(default_factory=WorkflowRunPolicy)

    def all_nodes(self) -> tuple[WorkflowNode, ...]:
        return (*self.nodes, *(node for region in self.regions for node in region.nodes))

    @model_validator(mode="after")
    def validate_graph(self) -> "WorkflowDefinition":
        self._validate_runtime_inputs()
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Workflow node IDs must be unique")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Workflow edge IDs must be unique")

        main_nodes = [node for node in self.nodes if node.phase is WorkflowPhase.MAIN]
        cleanup_nodes = [node for node in self.nodes if node.phase is WorkflowPhase.CLEANUP]
        starts = [node for node in main_nodes if node.effective_type is NodeType.START]
        ends = [node for node in main_nodes if node.effective_type is NodeType.END]
        if len(starts) != 1:
            raise ValueError("Workflow must contain exactly one start node")
        if not ends:
            raise ValueError("Workflow must contain at least one end node")
        datasets = [node for node in main_nodes if node.effective_type is NodeType.DATASET]
        if len(datasets) > 1:
            raise ValueError("Workflow can contain at most one dataset node")

        known_nodes = set(node_ids)
        nodes_by_id = {node.id: node for node in self.nodes}
        for edge in self.edges:
            if edge.source not in known_nodes or edge.target not in known_nodes:
                raise ValueError(f"Edge {edge.id} references an unknown node")
            if edge.source == edge.target:
                raise ValueError(f"Edge {edge.id} cannot connect a node to itself")
            if nodes_by_id[edge.source].phase is not nodes_by_id[edge.target].phase:
                raise ValueError(f"Edge {edge.id} cannot cross workflow phases")
            self._validate_edge(edge, nodes_by_id)
        self._validate_condition_branches(nodes_by_id)
        self._validate_acyclic(known_nodes)
        main_node_ids = {node.id for node in main_nodes}
        self._validate_endpoints(starts[0].id, {node.id for node in ends})
        self._validate_connected(starts[0].id, {node.id for node in ends}, main_node_ids)
        self._validate_cleanup_targets(cleanup_nodes, main_node_ids)
        self._validate_cleanup_request_budget(cleanup_nodes)
        self._validate_control_regions()
        return self

    def _validate_control_regions(self) -> None:
        control_nodes = [
            node
            for node in (*self.nodes, *(item for region in self.regions for item in region.nodes))
            if (node.capability_id or "").startswith("flow.control.")
        ]
        if self.schema_version != "4.0" and (self.regions or control_nodes):
            raise ValueError("Inline control requires workflow schema 4.0")
        if self.schema_version == "4.0" and self.run_policy.request_budget is None:
            raise ValueError("Workflow schema 4.0 requires a main request budget")
        if any(node.capability_id == "flow.control.try" for node in control_nodes) and (
            self.run_policy.cleanup_request_budget is None
        ):
            raise ValueError("Try/Finally requires a separate cleanup request budget")
        node_ids = [node.id for node in self.nodes]
        node_ids.extend(node.id for region in self.regions for node in region.nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Node IDs must be unique across all regions")
        region_ids = [region.id for region in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("Region IDs must be unique")
        owners = self._validate_control_owners(control_nodes)
        for region in self.regions:
            if region.id not in owners.get(region.owner_node_id, set()):
                raise ValueError(f"Region {region.id} has no unique control owner")
        self._validate_control_depth(control_nodes)
        self._validate_control_signals(control_nodes)

    def _validate_control_owners(self, control_nodes: list[WorkflowNode]) -> dict[str, set[str]]:
        regions = {region.id: region for region in self.regions}
        owners: dict[str, set[str]] = {}
        for node in control_nodes:
            if node.type is not NodeType.CAPABILITY:
                raise ValueError(f"Control node {node.id} must use a pinned capability")
            config = parse_control_config(node)
            if isinstance(config, (ControlSignalConfig, FailControlConfig, ReturnControlConfig)):
                continue
            for role, body in control_bodies(config):
                if not isinstance(body, InlineControlBody):
                    continue
                region = regions.get(body.region_id)
                if region is None or region.owner_node_id != node.id or region.role != role:
                    raise ValueError(f"Control node {node.id} has a mismatched {role} region")
                if not region.nodes and isinstance(
                    config, (ForEachControlConfig, RepeatControlConfig, ConditionLoopConfig)
                ):
                    raise ValueError(f"Loop node {node.id} has an empty body region")
                if set(config.inputs) & set(region.inputs):
                    raise ValueError(f"Control node {node.id} declares duplicate region inputs")
                if isinstance(
                    config, (ForEachControlConfig, RepeatControlConfig, ConditionLoopConfig)
                ) and set(config.collect) & set(region.outputs):
                    raise ValueError(f"Control node {node.id} declares duplicate region outputs")
                _validate_region_sources(node, config, region)
                owners.setdefault(node.id, set()).add(region.id)
        return owners

    def _validate_control_depth(self, control_nodes: list[WorkflowNode]) -> None:
        owner_by_node = {
            node.id: region.owner_node_id for region in self.regions for node in region.nodes
        }
        for node in control_nodes:
            current = node.id
            depth = 0
            seen: set[str] = set()
            while current in owner_by_node:
                current = owner_by_node[current]
                depth += 1
                if current in seen or depth > CONTROL_MAX_REGION_DEPTH:
                    raise ValueError("Control region nesting exceeds the supported depth")
                seen.add(current)

    def _validate_control_signals(self, control_nodes: list[WorkflowNode]) -> None:
        parents = {
            node.id: region.owner_node_id for region in self.regions for node in region.nodes
        }
        regions = {node.id: region for region in self.regions for node in region.nodes}
        controls = {node.id: node for node in control_nodes}
        loops = {
            "flow.control.foreach",
            "flow.control.repeat",
            "flow.control.while",
            "flow.control.do_while",
            "flow.control.until",
        }
        for node in control_nodes:
            if node.capability_id not in {
                "flow.control.break",
                "flow.control.continue",
                "flow.control.return",
            }:
                continue
            current = node.id
            while current in parents:
                if regions[current].role == "finally":
                    raise ValueError(f"Control signal {node.id} cannot leave a Finally region")
                current = parents[current]
                if controls[current].capability_id == "flow.control.parallel":
                    raise ValueError(f"Control signal {node.id} cannot cross a parallel branch")
                if node.capability_id == "flow.control.return":
                    continue
                if controls[current].capability_id in loops:
                    loop_config = parse_control_config(controls[current])
                    if (
                        isinstance(loop_config, (ForEachControlConfig, RepeatControlConfig))
                        and loop_config.policy.concurrency > 1
                    ):
                        raise ValueError(f"Control signal {node.id} requires a serial loop")
                    break
            else:
                if node.capability_id == "flow.control.return":
                    continue
                raise ValueError(f"Control signal {node.id} must be inside a serial loop")

    def _validate_runtime_inputs(self) -> None:
        input_names = [item.name for item in self.runtime_inputs]
        if len(input_names) != len(set(input_names)):
            raise ValueError("Workflow runtime input names must be unique")

    @staticmethod
    def _validate_cleanup_targets(
        cleanup_nodes: list[WorkflowNode], main_node_ids: set[str]
    ) -> None:
        for node in cleanup_nodes:
            unknown = sorted(set(node.cleanup_for) - main_node_ids)
            if unknown:
                raise ValueError(f"Cleanup node {node.id} references unknown main nodes: {unknown}")

    def _validate_cleanup_request_budget(self, cleanup_nodes: list[WorkflowNode]) -> None:
        structural = [
            node.id
            for node in cleanup_nodes
            if node.effective_type in {NodeType.SUBFLOW, NodeType.FOR_EACH}
        ]
        if structural and self.run_policy.cleanup_request_budget is None:
            raise ValueError(
                "Cleanup subflow and for-each nodes require an explicit cleanup request budget: "
                f"{structural}"
            )

    @staticmethod
    def _validate_edge(edge: WorkflowEdge, nodes: dict[str, WorkflowNode]) -> None:
        source = nodes[edge.source]
        if edge.condition is not None:
            if source.effective_type is not NodeType.CONDITION:
                raise ValueError(f"Edge {edge.id} condition requires a condition source node")
            if edge.condition not in {"true", "false"}:
                raise ValueError(f"Edge {edge.id} condition must be true or false")
        for mapping in edge.mappings:
            if mapping.source.node_id != edge.source or mapping.target.node_id != edge.target:
                raise ValueError(f"Edge {edge.id} mapping endpoints must match the edge")

    def _validate_condition_branches(self, nodes: dict[str, WorkflowNode]) -> None:
        for node in nodes.values():
            if node.effective_type is not NodeType.CONDITION:
                continue
            outgoing = [edge for edge in self.edges if edge.source == node.id]
            conditions = [edge.condition for edge in outgoing]
            if (
                len(conditions) != 2
                or conditions.count("true") != 1
                or conditions.count("false") != 1
            ):
                raise ValueError(
                    f"Condition node {node.id} must have exactly one true and one false edge"
                )

    def _validate_endpoints(self, start_id: str, end_ids: set[str]) -> None:
        main_edges = [
            edge
            for edge in self.edges
            if edge.source == start_id
            or edge.target == start_id
            or edge.source in end_ids
            or edge.target in end_ids
            or self._node_phase(edge.source) is WorkflowPhase.MAIN
        ]
        if any(edge.target == start_id for edge in main_edges):
            raise ValueError("Start node cannot have incoming edges")
        if any(edge.source in end_ids for edge in main_edges):
            raise ValueError("End nodes cannot have outgoing edges")

    def _node_phase(self, node_id: str) -> WorkflowPhase:
        return next(node.phase for node in self.nodes if node.id == node_id)

    def _validate_acyclic(self, node_ids: set[str]) -> None:
        incoming = dict.fromkeys(node_ids, 0)
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        for edge in self.edges:
            incoming[edge.target] += 1
            outgoing[edge.source].append(edge.target)

        ready = [node_id for node_id, count in incoming.items() if count == 0]
        visited = 0
        while ready:
            node_id = ready.pop()
            visited += 1
            for target in outgoing[node_id]:
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)
        if visited != len(node_ids):
            raise ValueError("Workflow must be a directed acyclic graph")

    def _validate_connected(self, start_id: str, end_ids: set[str], node_ids: set[str]) -> None:
        outgoing: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                continue
            outgoing[edge.source].add(edge.target)
            incoming[edge.target].add(edge.source)

        reachable = _walk(start_id, outgoing)
        if unreachable := node_ids - reachable:
            raise ValueError(
                f"Workflow contains nodes unreachable from start: {sorted(unreachable)}"
            )

        reaches_end: set[str] = set()
        for end_id in end_ids:
            reaches_end.update(_walk(end_id, incoming))
        if dangling := node_ids - reaches_end:
            raise ValueError(f"Workflow contains nodes without a path to end: {sorted(dangling)}")


ControlConfig = (
    ForEachControlConfig
    | RepeatControlConfig
    | ConditionLoopConfig
    | IfControlConfig
    | SwitchControlConfig
    | ParallelControlConfig
    | TryControlConfig
    | StepGroupControlConfig
    | FailControlConfig
    | ReturnControlConfig
    | ControlSignalConfig
)


def parse_control_config(node: WorkflowNode) -> ControlConfig:
    model = CONTROL_CONFIG_MODELS.get(node.capability_id or "")
    if model is None or node.capability_version != "1.0.0":
        raise ValueError(
            f"Unsupported control capability {node.capability_id}@{node.capability_version}"
        )
    return cast(ControlConfig, model.model_validate(node.configuration))


def control_bodies(config: ControlConfig) -> list[tuple[str, ControlBody]]:
    if isinstance(config, (ForEachControlConfig, RepeatControlConfig, ConditionLoopConfig)):
        return [("body", config.body)]
    if isinstance(config, StepGroupControlConfig):
        return [("body", config.body)]
    if isinstance(config, (ControlSignalConfig, FailControlConfig, ReturnControlConfig)):
        return []
    if isinstance(config, IfControlConfig):
        return [("true", config.true_body), ("false", config.false_body)]
    if isinstance(config, ParallelControlConfig):
        return [(f"branch:{branch.id}", branch.body) for branch in config.branches]
    if isinstance(config, TryControlConfig):
        bodies = [("try", config.try_body)]
        bodies.extend((f"catch:{item.id}", item.body) for item in config.catches)
        if config.finally_body is not None:
            bodies.append(("finally", config.finally_body))
        return bodies
    bodies = [(f"case:{branch.id}", branch.body) for branch in config.branches]
    if config.default.body is not None:
        bodies.append(("default", config.default.body))
    return bodies


def control_external_sources(config: ControlConfig) -> list[ValueSource]:
    if isinstance(config, (ControlSignalConfig, FailControlConfig)):
        return []
    if isinstance(config, ReturnControlConfig):
        return list(config.outputs.values())
    sources: list[ValueSource] = list(config.inputs.values())
    if isinstance(config, ForEachControlConfig):
        sources.append(config.collection)
    elif isinstance(config, ConditionLoopConfig):
        sources.extend(config.state.values())
        sources.extend(_condition_sources(config.condition))
    elif isinstance(config, IfControlConfig):
        sources.extend(_condition_sources(config.condition))
    elif isinstance(config, SwitchControlConfig):
        sources.extend(_switch_external_sources(config))
    return sources


def _switch_external_sources(config: SwitchControlConfig) -> list[ValueSource]:
    sources = [config.value] if config.value is not None else []
    for branch in config.branches:
        if branch.match is not None:
            sources.append(branch.match)
        if branch.condition is not None:
            sources.extend(_condition_sources(branch.condition))
    return sources


def _condition_sources(expression: ConditionExpression) -> list[ValueSource]:
    if expression.kind == "compare":
        return [item for item in (expression.left, expression.right) if item is not None]
    children = expression.conditions or ([expression.condition] if expression.condition else [])
    return [source for child in children for source in _condition_sources(child)]


def condition_sources(expression: ConditionExpression) -> list[ValueSource]:
    return _condition_sources(expression)


def _validate_region_sources(
    node: WorkflowNode, config: ControlConfig, region: WorkflowRegion
) -> None:
    internal = {item.id for item in region.nodes}
    exports = list(region.outputs.values())
    if isinstance(config, (ForEachControlConfig, RepeatControlConfig, ConditionLoopConfig)):
        exports.extend(config.collect.values())
    if any(
        isinstance(source, NodeOutputValueSource) and source.node_id not in internal
        for source in exports
    ):
        raise ValueError(f"Control region {region.id} exports a node outside its scope")
    if not isinstance(config, ConditionLoopConfig):
        return
    condition_nodes = {
        source.node_id
        for source in condition_sources(config.condition)
        if isinstance(source, NodeOutputValueSource)
    }
    if node.capability_id == "flow.control.while" and condition_nodes & internal:
        raise ValueError("While condition cannot read its body before an iteration")
    if node.capability_id != "flow.control.while" and condition_nodes - internal:
        raise ValueError("Post condition must read body outputs through its own scope")
    update_nodes = {
        update.value.node_id
        for update in config.update.values()
        if isinstance(update.value, NodeOutputValueSource)
    }
    if update_nodes - internal:
        raise ValueError("State update must use body outputs or typed variables")
    outgoing: dict[str, set[str]] = {item.id: set() for item in region.nodes}
    for edge in region.edges:
        outgoing[edge.source].add(edge.target)
    for signal in region.nodes:
        if signal.capability_id == "flow.control.continue" and (
            update_nodes & (_walk(signal.id, outgoing) - {signal.id})
        ):
            raise ValueError("Continue state update references a skipped node")


def parse_api_node_config(node: WorkflowNode) -> ApiNodeConfig:
    if node.effective_type is not NodeType.API:
        raise ValueError(f"Node {node.id} is not an API node")
    return ApiNodeConfig.model_validate(node.effective_config)


NodeConfig = (
    StartNodeConfig
    | ApiNodeConfig
    | ExtractNodeConfig
    | AssertNodeConfig
    | ConditionNodeConfig
    | DelayNodeConfig
    | DatasetNodeConfig
    | SubFlowNodeConfig
    | ForEachNodeConfig
    | SqlNodeConfig
    | RedisNodeConfig
    | None
)


_NODE_CONFIG_MODELS: dict[NodeType, type[BaseModel]] = {
    NodeType.START: StartNodeConfig,
    NodeType.API: ApiNodeConfig,
    NodeType.EXTRACT: ExtractNodeConfig,
    NodeType.ASSERT: AssertNodeConfig,
    NodeType.CONDITION: ConditionNodeConfig,
    NodeType.DELAY: DelayNodeConfig,
    NodeType.DATASET: DatasetNodeConfig,
    NodeType.SUBFLOW: SubFlowNodeConfig,
    NodeType.FOR_EACH: ForEachNodeConfig,
    NodeType.SQL: SqlNodeConfig,
    NodeType.REDIS: RedisNodeConfig,
}


def parse_node_config(node: WorkflowNode) -> NodeConfig:
    model = _NODE_CONFIG_MODELS.get(node.effective_type)
    if model is not None:
        return cast(NodeConfig, model.model_validate(node.effective_config))
    if node.effective_config:
        raise ValueError(f"Node {node.id} does not accept configuration")
    return None


def _walk(origin: str, adjacency: dict[str, set[str]]) -> set[str]:
    visited: set[str] = set()
    pending = [origin]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency[current] - visited)
    return visited
