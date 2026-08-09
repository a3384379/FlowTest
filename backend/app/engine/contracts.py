from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


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


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class MappingSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    path: str


class MappingTransform(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "template"
    template: str = "{{value}}"


class MappingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    location: str
    key: str


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


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
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

        known_nodes = set(node_ids)
        for edge in self.edges:
            if edge.source not in known_nodes or edge.target not in known_nodes:
                raise ValueError(f"Edge {edge.id} references an unknown node")
            if edge.source == edge.target:
                raise ValueError(f"Edge {edge.id} cannot connect a node to itself")
        self._validate_acyclic(known_nodes)
        return self

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
