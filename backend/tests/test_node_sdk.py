import pytest
from pydantic import JsonValue

from app.engine.contracts import NodeType, WorkflowNode
from app.engine.node_sdk import NodeHandlerRegistration, NodeHandlerRegistry
from app.engine.scheduler import ExecutionContext, NodeExecutionError


async def _handler(node: WorkflowNode, context: ExecutionContext) -> JsonValue:
    return {"node": node.id, "variables": context.resolved_variables()}


def _start_node() -> WorkflowNode:
    return WorkflowNode.model_validate(
        {
            "id": "start",
            "type": "start",
            "name": "开始",
            "position": {"x": 0, "y": 0},
            "config": {},
        }
    )


@pytest.mark.asyncio
async def test_node_sdk_dispatches_registered_typed_handlers() -> None:
    registry = NodeHandlerRegistry([NodeHandlerRegistration(NodeType.START, _handler)])

    output = await registry.execute(
        _start_node(),
        ExecutionContext(runtime_variables={"region": "cn"}),
    )

    assert registry.supported_types == frozenset({NodeType.START})
    assert output == {"node": "start", "variables": {"region": "cn"}}


@pytest.mark.asyncio
async def test_node_sdk_rejects_duplicate_and_unregistered_handlers() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        NodeHandlerRegistry(
            [
                NodeHandlerRegistration(NodeType.START, _handler),
                NodeHandlerRegistration(NodeType.START, _handler),
            ]
        )

    registry = NodeHandlerRegistry([])
    with pytest.raises(NodeExecutionError) as unsupported:
        await registry.execute(_start_node(), ExecutionContext())
    assert unsupported.value.code == "UNSUPPORTED_NODE_TYPE"
