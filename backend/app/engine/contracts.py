from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.assertions import ComparisonOperator

VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]


class NodeType(StrEnum):
    START = "start"
    API = "api"
    EXTRACT = "extract"
    ASSERT = "assert"
    CONDITION = "condition"
    DELAY = "delay"
    DATASET = "dataset"
    END = "end"


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
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryCategory(StrEnum):
    NETWORK_ERROR = "network_error"
    SERVER_ERROR = "5xx"


class MappingTransformKind(StrEnum):
    IDENTITY = "identity"
    TEMPLATE = "template"


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


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    type: NodeType
    name: str = Field(min_length=1, max_length=200)
    position: Position
    config: dict[str, JsonValue] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    source: str
    target: str
    condition: str | None = None
    mappings: list[FieldMapping] = Field(default_factory=list)


class WorkflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fail_fast: bool = True
    concurrency: int = Field(default=20, ge=1, le=100)
    default_timeout_seconds: int = Field(default=30, ge=1, le=300)


class ApiNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_definition_id: UUID
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int = Field(default=0, ge=0, le=3)
    retry_on: tuple[RetryCategory, ...] = Field(
        default=(RetryCategory.NETWORK_ERROR, RetryCategory.SERVER_ERROR),
        min_length=1,
        max_length=2,
    )
    retry_delay_seconds: float = Field(default=0, ge=0, le=60)

    @model_validator(mode="after")
    def validate_retry_categories(self) -> "ApiNodeConfig":
        if len(self.retry_on) != len(set(self.retry_on)):
            raise ValueError("Retry categories must be unique")
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


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    variables: dict[VariableName, str] = Field(default_factory=dict)
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)

    @model_validator(mode="after")
    def validate_graph(self) -> "WorkflowDefinition":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Workflow node IDs must be unique")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Workflow edge IDs must be unique")

        starts = [node for node in self.nodes if node.type is NodeType.START]
        ends = [node for node in self.nodes if node.type is NodeType.END]
        if len(starts) != 1:
            raise ValueError("Workflow must contain exactly one start node")
        if not ends:
            raise ValueError("Workflow must contain at least one end node")
        datasets = [node for node in self.nodes if node.type is NodeType.DATASET]
        if len(datasets) > 1:
            raise ValueError("Workflow can contain at most one dataset node")

        known_nodes = set(node_ids)
        nodes_by_id = {node.id: node for node in self.nodes}
        for edge in self.edges:
            if edge.source not in known_nodes or edge.target not in known_nodes:
                raise ValueError(f"Edge {edge.id} references an unknown node")
            if edge.source == edge.target:
                raise ValueError(f"Edge {edge.id} cannot connect a node to itself")
            self._validate_edge(edge, nodes_by_id)
        self._validate_condition_branches(nodes_by_id)
        self._validate_acyclic(known_nodes)
        self._validate_endpoints(starts[0].id, {node.id for node in ends})
        self._validate_connected(starts[0].id, {node.id for node in ends}, known_nodes)
        return self

    @staticmethod
    def _validate_edge(edge: WorkflowEdge, nodes: dict[str, WorkflowNode]) -> None:
        source = nodes[edge.source]
        if edge.condition is not None:
            if source.type is not NodeType.CONDITION:
                raise ValueError(f"Edge {edge.id} condition requires a condition source node")
            if edge.condition not in {"true", "false"}:
                raise ValueError(f"Edge {edge.id} condition must be true or false")
        for mapping in edge.mappings:
            if mapping.source.node_id != edge.source or mapping.target.node_id != edge.target:
                raise ValueError(f"Edge {edge.id} mapping endpoints must match the edge")

    def _validate_condition_branches(self, nodes: dict[str, WorkflowNode]) -> None:
        for node in nodes.values():
            if node.type is not NodeType.CONDITION:
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
        if any(edge.target == start_id for edge in self.edges):
            raise ValueError("Start node cannot have incoming edges")
        if any(edge.source in end_ids for edge in self.edges):
            raise ValueError("End nodes cannot have outgoing edges")

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


def parse_api_node_config(node: WorkflowNode) -> ApiNodeConfig:
    if node.type is not NodeType.API:
        raise ValueError(f"Node {node.id} is not an API node")
    return ApiNodeConfig.model_validate(node.config)


NodeConfig = (
    ApiNodeConfig
    | ExtractNodeConfig
    | AssertNodeConfig
    | ConditionNodeConfig
    | DelayNodeConfig
    | DatasetNodeConfig
    | None
)


def parse_node_config(node: WorkflowNode) -> NodeConfig:
    if node.type is NodeType.API:
        return ApiNodeConfig.model_validate(node.config)
    if node.type is NodeType.EXTRACT:
        return ExtractNodeConfig.model_validate(node.config)
    if node.type is NodeType.ASSERT:
        return AssertNodeConfig.model_validate(node.config)
    if node.type is NodeType.CONDITION:
        return ConditionNodeConfig.model_validate(node.config)
    if node.type is NodeType.DELAY:
        return DelayNodeConfig.model_validate(node.config)
    if node.type is NodeType.DATASET:
        return DatasetNodeConfig.model_validate(node.config)
    if node.config:
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
