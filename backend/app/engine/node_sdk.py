from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from pydantic import JsonValue

from app.engine.contracts import NodeType, WorkflowNode
from app.engine.scheduler import ExecutionContext, NodeExecutionError

NodeHandler = Callable[[WorkflowNode, ExecutionContext], Awaitable[JsonValue]]


@dataclass(frozen=True, slots=True)
class NodeHandlerRegistration:
    node_type: NodeType
    handler: NodeHandler


class NodeHandlerRegistry:
    """Immutable per-run registry used by the V2 node execution SDK."""

    def __init__(self, registrations: list[NodeHandlerRegistration]) -> None:
        handlers: dict[NodeType, NodeHandler] = {}
        for registration in registrations:
            if registration.node_type in handlers:
                raise ValueError(f"Duplicate handler for {registration.node_type.value}")
            handlers[registration.node_type] = registration.handler
        self._handlers: Mapping[NodeType, NodeHandler] = handlers

    @property
    def supported_types(self) -> frozenset[NodeType]:
        return frozenset(self._handlers)

    async def execute(self, node: WorkflowNode, context: ExecutionContext) -> JsonValue:
        handler = self._handlers.get(node.type)
        if handler is None:
            raise NodeExecutionError(
                code="UNSUPPORTED_NODE_TYPE",
                message=f"当前执行器不支持 {node.type.value} 节点",
            )
        return await handler(node, context)
