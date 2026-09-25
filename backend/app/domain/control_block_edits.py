"""Atomic graph edit for inserting one inline control block."""

import json
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from app.engine.contracts import (
    NodeType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPhase,
    WorkflowRegion,
)

_BLOCK_CAPABILITIES = frozenset(
    {
        "flow.control.foreach",
        "flow.control.repeat",
        "flow.control.if",
        "flow.control.switch",
        "flow.control.while",
        "flow.control.do_while",
        "flow.control.until",
        "flow.control.parallel",
        "flow.control.try",
        "flow.control.group",
        "flow.control.fail",
    }
)


class ControlBlockEditError(ValueError):
    """A control insertion cannot preserve the requested graph semantics."""


def insert_control_block(
    definition: WorkflowDefinition,
    *,
    edge_id: str,
    node: WorkflowNode,
    regions: list[WorkflowRegion],
    request_budget: int | None,
    cleanup_request_budget: int | None,
) -> WorkflowDefinition:
    """Split one safe main edge and validate the entire resulting definition."""

    edge = next((item for item in definition.edges if item.id == edge_id), None)
    if edge is None:
        raise ControlBlockEditError("目标连线不存在")
    if edge.condition is not None or edge.mappings:
        raise ControlBlockEditError("含条件或字段映射的连线不能直接插入控制块")
    source = next(item for item in definition.nodes if item.id == edge.source)
    if source.phase is not WorkflowPhase.MAIN or node.phase is not WorkflowPhase.MAIN:
        raise ControlBlockEditError("只能在主流程连线插入主流程控制块")
    if (
        node.type is not NodeType.CAPABILITY
        or node.capability_id not in _BLOCK_CAPABILITIES
        or node.capability_version != "1.0.0"
    ):
        raise ControlBlockEditError("只能插入当前支持的固定版本控制能力")
    if definition.schema_version != "4.0" and request_budget is None:
        raise ControlBlockEditError("升级到 schema 4.0 时必须显式指定主请求预算")
    if (
        request_budget is not None
        and definition.run_policy.request_budget is not None
        and request_budget != definition.run_policy.request_budget
    ):
        raise ControlBlockEditError("插入控制块不能修改已有的主请求预算")
    if cleanup_request_budget is not None and (
        definition.run_policy.cleanup_request_budget is not None
        and cleanup_request_budget != definition.run_policy.cleanup_request_budget
    ):
        raise ControlBlockEditError("插入控制块不能修改已有的清理请求预算")

    edge_key = json.dumps([edge.id, node.id], ensure_ascii=False, separators=(",", ":"))
    new_edge = WorkflowEdge(
        id=f"edge-{uuid5(NAMESPACE_URL, edge_key)}", source=node.id, target=edge.target
    )
    policy = definition.run_policy.model_copy(
        update={
            "request_budget": definition.run_policy.request_budget or request_budget,
            "cleanup_request_budget": (
                definition.run_policy.cleanup_request_budget or cleanup_request_budget
            ),
        }
    )
    candidate = definition.model_copy(
        update={
            "schema_version": "4.0",
            "nodes": [*definition.nodes, node],
            "edges": [
                *(
                    item.model_copy(update={"target": node.id}) if item.id == edge_id else item
                    for item in definition.edges
                ),
                new_edge,
            ],
            "regions": [*definition.regions, *regions],
            "run_policy": policy,
        }
    )
    try:
        return WorkflowDefinition.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as error:
        raise ControlBlockEditError("控制块或区域结构无效") from error
