"""Explicit design summaries; values stay inside canonical digest computation."""

from uuid import UUID

from sqlalchemy import Text, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.self_tests import document_digest
from app.domain.test_design import TestDesignDocument, fingerprint_design
from app.models.ai import AIChangeItem
from app.models.test_design import TestDesign
from app.schemas.self_test_probes import (
    ProbeChangeItem,
    ProbeDesignSummary,
    ProbeOracle,
    ProbeResource,
)
from app.services.mcp_controlled_write import _materialized_design_document


def design_summary(design: TestDesignDocument) -> ProbeDesignSummary:
    return ProbeDesignSummary(
        document_digest=fingerprint_design(design),
        intent_key_digest=document_digest(design.intent.key),
        objective_digest=document_digest(design.intent.objective),
        oracles=tuple(
            ProbeOracle(
                id=oracle.id,
                kind=oracle.kind,
                expression_digest=document_digest(oracle.expression),
                operator=oracle.operator,
                expected_digest=document_digest(oracle.expected),
            )
            for oracle in design.oracles
        ),
    )


async def _content_bounded(
    session: AsyncSession, changes: tuple[UUID, ...], designs: tuple[UUID, ...]
) -> int | None:
    item_count, item_size = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(func.length(cast(AIChangeItem.proposed_content, Text))), 0),
            ).where(AIChangeItem.change_set_id.in_(changes))
        )
    ).one()
    design_size = await session.scalar(
        select(func.coalesce(func.sum(_design_length()), 0)).where(TestDesign.id.in_(designs))
    )
    # Character length is conservatively charged as four UTF-8 bytes before loading JSON.
    if int(item_count) > 500 or 4 * (int(item_size) + int(design_size or 0)) > 2097152:
        return None
    return int(item_count)


def _design_length() -> ColumnElement[int]:
    columns = (
        TestDesign.intent,
        TestDesign.knowledge_graph,
        TestDesign.state_model,
        TestDesign.scenarios,
        TestDesign.oracles,
        TestDesign.coverage,
        TestDesign.evidence_refs,
        TestDesign.warnings,
        TestDesign.review_requirements,
        TestDesign.test_case_refs,
    )
    total: ColumnElement[int] = literal(0)
    for column in columns:
        total = total + func.length(cast(column, Text))
    return total


def _item(item: AIChangeItem) -> ProbeChangeItem:
    summary = None
    content = item.proposed_content
    digest = document_digest(content)
    if item.item_type == "test_design":
        candidate = content.get("design", content)
        summary = design_summary(TestDesignDocument.model_validate(candidate))
        digest = summary.document_digest
    return ProbeChangeItem(
        id=item.id,
        item_type=item.item_type,
        action=item.action,
        review_status=item.review_status,
        reviewed_by_id=item.reviewed_by_id,
        materialized_resource_type=item.materialized_resource_type,
        materialized_resource_id=item.materialized_resource_id,
        proposed_document_digest=digest,
        design=summary,
    )


async def enrich_designs(
    session: AsyncSession, rows: tuple[ProbeResource, ...]
) -> tuple[ProbeResource, ...] | None:
    changes = tuple(row.id for row in rows if row.kind == "ai_change_set")
    designs = tuple(row.id for row in rows if row.kind == "test_design")
    count = await _content_bounded(session, changes, designs)
    if count is None:
        return None
    items = (
        await session.scalars(
            select(AIChangeItem)
            .where(
                AIChangeItem.change_set_id.in_(changes),
                func.length(cast(AIChangeItem.proposed_content, Text)) <= 262144,
            )
            .order_by(AIChangeItem.position, AIChangeItem.id)
            .limit(501)
        )
    ).all()
    if len(items) != count:
        return None
    by_change: dict[UUID, list[ProbeChangeItem]] = {}
    for item in items:
        by_change.setdefault(item.change_set_id, []).append(_item(item))
    models = (
        await session.scalars(
            select(TestDesign).where(TestDesign.id.in_(designs), _design_length() <= 262144)
        )
    ).all()
    by_design = {model.id: design_summary(_materialized_design_document(model)) for model in models}
    if set(by_design) != set(designs):
        return None
    return tuple(
        row.model_copy(
            update={"items": tuple(by_change.get(row.id, ())), "design": by_design.get(row.id)}
        )
        for row in rows
    )
