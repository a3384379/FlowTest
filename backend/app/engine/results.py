from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.engine.contracts import NodeStatus


class NodeResultError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    retryable: bool = False


class NodeAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=200)
    passed: bool
    expected: JsonValue = None
    actual: JsonValue = None
    message: str = Field(default="", max_length=1000)


class NodeMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    value: float
    unit: str = Field(default="count", min_length=1, max_length=32)
    labels: dict[str, str] = Field(default_factory=dict)


class NodeArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    content_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NodeTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")


class NodeResult(BaseModel):
    """Protocol-neutral result envelope persisted for every V3 capability attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: NodeStatus
    output: JsonValue = None
    assertions: tuple[NodeAssertion, ...] = ()
    metrics: tuple[NodeMetric, ...] = ()
    artifacts: tuple[NodeArtifact, ...] = ()
    trace: NodeTrace | None = None
    redacted_paths: tuple[str, ...] = ()
    error: NodeResultError | None = None

    @model_validator(mode="after")
    def validate_terminal_result(self) -> "NodeResult":
        if self.status in {NodeStatus.PENDING, NodeStatus.RUNNING}:
            raise ValueError("NodeResult must describe a terminal node state")
        if self.status is NodeStatus.FAILED and self.error is None:
            raise ValueError("Failed NodeResult must include an error")
        if self.status is NodeStatus.PASSED and self.error is not None:
            raise ValueError("Passed NodeResult cannot include an error")
        return self

    @classmethod
    def passed(cls, output: JsonValue) -> "NodeResult":
        return cls(status=NodeStatus.PASSED, output=output)

    @classmethod
    def failed(
        cls,
        *,
        code: str,
        message: str,
        output: JsonValue = None,
        retryable: bool = False,
    ) -> "NodeResult":
        return cls(
            status=NodeStatus.FAILED,
            output=output,
            error=NodeResultError(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )


def normalize_node_result(value: NodeResult | JsonValue) -> NodeResult:
    return value if isinstance(value, NodeResult) else NodeResult.passed(value)
