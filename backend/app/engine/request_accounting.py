"""Shared conservative request accounting for planning, execution and recovery."""

from typing import Protocol

from app.engine.contracts import (
    ApiNodeConfig,
    NodeType,
    WorkflowNode,
    WorkflowPhase,
    parse_node_config,
)
from app.engine.results import NodeResult


class RequestRecord(Protocol):
    @property
    def attempts(self) -> int: ...

    @property
    def result(self) -> NodeResult: ...


def node_type_consumes_request(node_type: NodeType) -> bool:
    return node_type in {NodeType.API, NodeType.SQL, NodeType.REDIS, NodeType.CAPABILITY}


def preview_node_request_attempts(node: WorkflowNode) -> int:
    if not node_type_consumes_request(node.effective_type):
        return 0
    config = parse_node_config(node)
    polling = (
        config.polling.max_attempts if isinstance(config, ApiNodeConfig) and config.polling else 1
    )
    retries = (
        node.cleanup_retry_budget
        if node.phase is WorkflowPhase.CLEANUP
        else config.max_retries
        if isinstance(config, ApiNodeConfig)
        else 0
    )
    return (retries + 1) * polling


def resumed_request_attempts(record: RequestRecord | None, reserved_attempts: int = 0) -> int:
    if record is None:
        return reserved_attempts
    return max(
        reserved_attempts,
        record.attempts,
        len(record.result.observations),
        record.result.request_attempts,
    )
