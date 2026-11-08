"""Pure self-test identity helpers; execution remains with the native engine."""

import hashlib
import json
from datetime import UTC, datetime
from graphlib import CycleError, TopologicalSorter

from pydantic import BaseModel, JsonValue

from app.engine.contracts import ApiNodeConfig, NodeType, WorkflowDefinition, WorkflowPhase


def document_digest(value: BaseModel | JsonValue) -> str:
    document = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def aware(value: datetime) -> datetime:
    """SQLAlchemy SQLite DateTime values use the application's UTC database convention."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def request_upper_bound(definition: WorkflowDefinition) -> int | None:
    """Use enforced budgets, or a conservative bound for a finite plain native DAG."""
    policy = definition.run_policy
    cleanup = [node for node in definition.nodes if node.phase is WorkflowPhase.CLEANUP]
    if policy.request_budget is not None and (
        policy.cleanup_request_budget is not None or not cleanup
    ):
        return policy.request_budget + (policy.cleanup_request_budget or 0)
    counts = _plain_request_counts(definition)
    if counts is None:
        return None
    main, cleanup_count = counts
    return (policy.request_budget if policy.request_budget is not None else main) + (
        policy.cleanup_request_budget
        if policy.cleanup_request_budget is not None
        else cleanup_count
    )


def _plain_request_counts(definition: WorkflowDefinition) -> tuple[int, int] | None:
    allowed = {
        NodeType.START,
        NodeType.API,
        NodeType.ASSERT,
        NodeType.EXTRACT,
        NodeType.END,
    }
    if definition.regions or any(node.type not in allowed for node in definition.nodes):
        return None
    graph: dict[str, set[str]] = {node.id: set() for node in definition.nodes}
    for edge in definition.edges:
        graph[edge.target].add(edge.source)
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError:
        return None
    main, cleanup = 0, 0
    for node in definition.nodes:
        if node.type is NodeType.API:
            config = ApiNodeConfig.model_validate(node.config)
            if config.polling is not None:
                return None
            count = (1 + config.max_retries) * (1 + node.cleanup_retry_budget)
            if node.phase is WorkflowPhase.CLEANUP:
                cleanup += count
            else:
                main += count
    return main, cleanup
