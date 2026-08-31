"""Read-only Context Inspector queries for project users."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.test_contexts import (
    ContextRevisionSnapshot,
    EvidenceProviderType,
    EvidenceSemanticRole,
    ExternalEvidenceFinding,
    ExternalEvidenceWarning,
    TestContextStatus,
)
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.test_contexts import ContextEvidenceItem, TestContext, TestContextRevision
from app.schemas.context_inspector import (
    ContextInspectorDetail,
    ContextInspectorEvidenceItem,
    ContextInspectorProposalSummary,
    ContextInspectorProviderSummary,
    ContextInspectorSummary,
)
from app.services.projects import ProjectService


class ContextInspectorService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)

    async def list_contexts(
        self,
        *,
        actor: User,
        project_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[ContextInspectorSummary], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        contexts = list(
            (
                await self._session.scalars(
                    select(TestContext)
                    .where(TestContext.project_id == project_id)
                    .order_by(TestContext.updated_at.desc(), TestContext.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(TestContext)
            .where(TestContext.project_id == project_id)
        )
        if not contexts:
            return [], int(total or 0)
        revisions = await self._current_revisions(contexts)
        evidence_rollups = await self._evidence_rollups(list(revisions.values()))
        proposals_by_revision = await self._proposals_by_revision(
            project_id=project_id,
            revisions=list(revisions.values()),
        )
        summaries: list[ContextInspectorSummary] = []
        for context in contexts:
            revision = _required_revision(context, revisions)
            rollup = evidence_rollups.get(revision.id, _EvidenceRollup())
            summaries.append(
                _summary(
                    context=context,
                    revision=revision,
                    evidence_count=rollup.evidence_count,
                    provider_count=rollup.provider_count,
                    proposals=proposals_by_revision.get(revision.id, []),
                )
            )
        return summaries, int(total or 0)

    async def get_context(
        self,
        *,
        actor: User,
        project_id: UUID,
        context_id: UUID,
    ) -> ContextInspectorDetail:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        context = (
            await self._session.execute(
                select(TestContext).where(
                    TestContext.id == context_id,
                    TestContext.project_id == project_id,
                )
            )
        ).scalar_one_or_none()
        if context is None:
            raise AppError(
                code="TEST_CONTEXT_NOT_FOUND",
                message="测试上下文不存在",
                status_code=404,
            )
        revision = await self._current_revision(context)
        evidence = await self._evidence_items(revision.id)
        proposals = await self._proposals_by_revision(
            project_id=project_id,
            revisions=[revision],
        )
        summary = _summary(
            context=context,
            revision=revision,
            evidence_count=len(evidence),
            provider_count=len(_provider_summaries(evidence)),
            proposals=proposals.get(revision.id, []),
        )
        return ContextInspectorDetail(
            **summary.model_dump(),
            organization_id=context.organization_id,
            target_environment_id=context.target_environment_id,
            created_by_type=cast(Literal["user", "service_account"], context.created_by_type),
            created_by_id=context.created_by_id,
            closed_at=context.closed_at,
            revision=_revision_snapshot(revision),
            providers=_provider_summaries(evidence),
            evidence_items=[_evidence_response(item) for item in evidence],
            proposals=proposals.get(revision.id, []),
        )

    async def _current_revisions(
        self, contexts: list[TestContext]
    ) -> dict[UUID, TestContextRevision]:
        revisions = list(
            (
                await self._session.scalars(
                    select(TestContextRevision)
                    .join(TestContext, TestContext.id == TestContextRevision.context_id)
                    .where(
                        TestContext.id.in_([context.id for context in contexts]),
                        TestContextRevision.revision == TestContext.current_revision,
                    )
                )
            ).all()
        )
        return {revision.context_id: revision for revision in revisions}

    async def _current_revision(self, context: TestContext) -> TestContextRevision:
        revision = (
            await self._session.execute(
                select(TestContextRevision).where(
                    TestContextRevision.context_id == context.id,
                    TestContextRevision.revision == context.current_revision,
                )
            )
        ).scalar_one_or_none()
        if revision is None:
            raise _invalid_revision()
        return revision

    async def _evidence_rollups(
        self, revisions: list[TestContextRevision]
    ) -> dict[UUID, _EvidenceRollup]:
        if not revisions:
            return {}
        rows = (
            await self._session.execute(
                select(
                    ContextEvidenceItem.context_revision_id,
                    ContextEvidenceItem.source_type,
                    ContextEvidenceItem.provider_name,
                    ContextEvidenceItem.provider_version,
                    func.count(ContextEvidenceItem.id),
                )
                .where(ContextEvidenceItem.context_revision_id.in_([item.id for item in revisions]))
                .group_by(
                    ContextEvidenceItem.context_revision_id,
                    ContextEvidenceItem.source_type,
                    ContextEvidenceItem.provider_name,
                    ContextEvidenceItem.provider_version,
                )
            )
        ).all()
        totals: dict[UUID, int] = defaultdict(int)
        providers: dict[UUID, int] = defaultdict(int)
        for revision_id, _source_type, _name, _version, count in rows:
            totals[revision_id] += int(count)
            providers[revision_id] += 1
        return {
            revision.id: _EvidenceRollup(
                evidence_count=totals[revision.id],
                provider_count=providers[revision.id],
            )
            for revision in revisions
        }

    async def _evidence_items(self, revision_id: UUID) -> list[ContextEvidenceItem]:
        return list(
            (
                await self._session.scalars(
                    select(ContextEvidenceItem)
                    .where(ContextEvidenceItem.context_revision_id == revision_id)
                    .order_by(ContextEvidenceItem.fingerprint)
                )
            ).all()
        )

    async def _proposals_by_revision(
        self,
        *,
        project_id: UUID,
        revisions: list[TestContextRevision],
    ) -> dict[UUID, list[ContextInspectorProposalSummary]]:
        if not revisions:
            return {}
        by_value = {str(revision.id): revision.id for revision in revisions}
        revision_value = AIChangeSet.source_snapshot["context_revision_id"].as_string()
        rows = (
            await self._session.execute(
                select(AIChangeSet, AIChangeItem)
                .join(AIChangeItem, AIChangeItem.change_set_id == AIChangeSet.id)
                .where(
                    AIChangeSet.project_id == project_id,
                    AIChangeSet.source_type == "flow_spec",
                    revision_value.in_(list(by_value)),
                )
                .order_by(AIChangeSet.created_at.desc(), AIChangeSet.id.desc())
            )
        ).all()
        grouped: dict[UUID, list[ContextInspectorProposalSummary]] = defaultdict(list)
        for change_set, item in rows:
            raw_revision_id = change_set.source_snapshot.get("context_revision_id")
            revision_id = (
                by_value.get(raw_revision_id) if isinstance(raw_revision_id, str) else None
            )
            if revision_id is not None:
                grouped[revision_id].append(_proposal_response(change_set, item))
        return dict(grouped)


@dataclass(frozen=True, slots=True)
class _EvidenceRollup:
    evidence_count: int = 0
    provider_count: int = 0


def _required_revision(
    context: TestContext, revisions: dict[UUID, TestContextRevision]
) -> TestContextRevision:
    revision = revisions.get(context.id)
    if revision is None:
        raise _invalid_revision()
    return revision


def _invalid_revision() -> AppError:
    return AppError(
        code="TEST_CONTEXT_REVISION_INVALID",
        message="测试上下文当前 Revision 不存在",
        status_code=409,
    )


def _summary(
    *,
    context: TestContext,
    revision: TestContextRevision,
    evidence_count: int,
    provider_count: int,
    proposals: list[ContextInspectorProposalSummary],
) -> ContextInspectorSummary:
    snapshot = _revision_snapshot(revision)
    return ContextInspectorSummary(
        id=context.id,
        project_id=context.project_id,
        name=context.name,
        objective=context.objective,
        status=_effective_status(context),
        current_revision=context.current_revision,
        revision_id=revision.id,
        revision_fingerprint=revision.fingerprint,
        completeness=snapshot.completeness,
        conflict_count=len(snapshot.conflict_snapshot.conflicts),
        evidence_count=evidence_count,
        provider_count=provider_count,
        proposal_count=len(proposals),
        expires_at=context.expires_at,
        created_at=context.created_at,
        updated_at=context.updated_at,
    )


def _revision_snapshot(revision: TestContextRevision) -> ContextRevisionSnapshot:
    return ContextRevisionSnapshot.model_validate(
        {
            "repository_revisions": revision.repository_revisions,
            "contract_revisions": revision.contract_revisions,
            "data_profile_revisions": revision.data_profile_revisions,
            "existing_test_revision": revision.existing_test_revision,
            "knowledge_snapshot": revision.knowledge_snapshot,
            "completeness": revision.completeness,
            "conflict_snapshot": revision.conflict_snapshot,
            "evidence_fingerprints": revision.evidence_fingerprints,
        }
    )


def _provider_summaries(
    evidence: list[ContextEvidenceItem],
) -> list[ContextInspectorProviderSummary]:
    grouped: dict[tuple[str, str, str], list[ContextEvidenceItem]] = defaultdict(list)
    for item in evidence:
        grouped[(item.source_type, item.provider_name, item.provider_version)].append(item)
    return [
        ContextInspectorProviderSummary(
            source_type=EvidenceProviderType(source_type),
            provider_name=name,
            provider_version=version,
            finding_count=len(items),
            deterministic_count=sum(item.deterministic for item in items),
            conflict_count=sum(
                item.semantic_role == EvidenceSemanticRole.CONFLICT.value for item in items
            ),
        )
        for (source_type, name, version), items in sorted(grouped.items())
    ]


def _evidence_response(item: ContextEvidenceItem) -> ContextInspectorEvidenceItem:
    return ContextInspectorEvidenceItem(
        id=item.id,
        source_type=EvidenceProviderType(item.source_type),
        provider_name=item.provider_name,
        provider_version=item.provider_version,
        source_ref=item.source_ref,
        source_revision=item.source_revision,
        subject_ref=item.subject_ref,
        finding=ExternalEvidenceFinding.model_validate(item.finding_payload),
        semantic_role=EvidenceSemanticRole(item.semantic_role),
        deterministic=item.deterministic,
        confidence=item.confidence,
        fingerprint=item.fingerprint,
        warnings=[ExternalEvidenceWarning.model_validate(value) for value in item.warnings],
        redaction_count=len(item.redactions),
        created_at=item.created_at,
        expires_at=item.expires_at,
    )


def _proposal_response(
    change_set: AIChangeSet, item: AIChangeItem
) -> ContextInspectorProposalSummary:
    snapshot = change_set.source_snapshot
    return ContextInspectorProposalSummary(
        id=change_set.id,
        title=change_set.title,
        status=change_set.status,
        review_status=cast(Literal["pending", "accepted", "rejected"], item.review_status),
        applied=change_set.applied_at is not None,
        target_workflow_id=_optional_uuid(snapshot.get("target_workflow_id")),
        target_revision=_optional_int(snapshot.get("target_revision")),
        source_ref=change_set.source_ref,
        created_at=change_set.created_at,
        updated_at=change_set.updated_at,
    )


def _effective_status(context: TestContext) -> TestContextStatus:
    status = TestContextStatus(context.status)
    if status in {TestContextStatus.EXPIRED, TestContextStatus.CLOSED}:
        return status
    expires_at = context.expires_at
    normalized = (
        expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC)
    )
    return TestContextStatus.EXPIRED if normalized <= datetime.now(UTC) else status


def _optional_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None
