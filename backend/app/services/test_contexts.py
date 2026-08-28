"""Application service for revisioned test contexts and external evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.evidence_adapters import (
    EntityMappingBudgetExceeded,
    EntityMappingResult,
    MappingEvidenceInput,
    derive_entity_mapping,
    with_mapping_conflict_findings,
)
from app.domain.test_contexts import (
    MAX_CONTEXT_CONFLICTS,
    MAX_CONTEXT_EVIDENCE_ITEMS,
    MAX_CONTEXT_REVISION_REFERENCES,
    ContextConflict,
    ContextConflictSnapshot,
    ContextRevisionSnapshot,
    EvidenceProviderType,
    EvidenceSemanticRole,
    ExternalEvidenceEnvelope,
    ExternalEvidenceFinding,
    RevisionReference,
    TestContextStatus,
    completeness_snapshot,
    context_revision_fingerprint,
    external_evidence_fingerprint,
    external_evidence_item_fingerprint,
    first_sensitive_value,
    normalize_revision_snapshot,
    referenced_project_id,
)
from app.models.access import User
from app.models.api_assets import Environment
from app.models.test_contexts import ContextEvidenceItem, TestContext, TestContextRevision
from app.schemas.test_contexts import (
    BeginTestContextRequest,
    ContextEvidenceItemResponse,
    ContextRequirementsResponse,
    TestContextResponse,
    TestContextRevisionResponse,
)
from app.services.audit import AuditService
from app.services.projects import ProjectService

MCP_EVIDENCE_WRITE_SCOPE = "mcp:evidence:write"


@dataclass(frozen=True, slots=True)
class ProposableContext:
    context: TestContext
    revision: TestContextRevision
    snapshot: ContextRevisionSnapshot


@dataclass(frozen=True, slots=True)
class _ActorIdentity:
    type: str
    id: UUID


class TestContextService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def begin(self, *, actor: User, payload: BeginTestContextRequest) -> TestContextResponse:
        self._require_evidence_scope()
        access = await self._projects.authorize(
            actor=actor, project_id=payload.project_id, editing=True
        )
        tenant = get_tenant_context()
        if tenant is None or access.project.organization_id != tenant.organization_id:
            raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)
        await self._validate_environment(
            project_id=payload.project_id,
            environment_id=payload.target_environment_id,
        )
        _require_initial_references_same_project(payload.project_id, payload)
        _require_safe_initial_context(payload)
        now = datetime.now(UTC)
        actor_identity = _actor_identity(actor.id)
        present = _initial_present_types(payload)
        completeness = completeness_snapshot(payload.required_evidence, present)
        snapshot = normalize_revision_snapshot(
            ContextRevisionSnapshot(
                repository_revisions=payload.repository_revisions,
                contract_revisions=payload.contract_revisions,
                data_profile_revisions=payload.data_profile_revisions,
                existing_test_revision=payload.existing_test_revision,
                knowledge_snapshot=payload.knowledge_snapshot,
                completeness=completeness,
            )
        )
        context = TestContext(
            organization_id=tenant.organization_id,
            project_id=payload.project_id,
            name=payload.name.strip(),
            objective=payload.objective.strip(),
            target_environment_id=payload.target_environment_id,
            status=(
                TestContextStatus.READY.value
                if completeness.complete
                else TestContextStatus.COLLECTING.value
            ),
            current_revision=1,
            created_by_type=actor_identity.type,
            created_by_id=actor_identity.id,
            expires_at=now + timedelta(seconds=payload.ttl_seconds),
            closed_at=None,
        )
        self._session.add(context)
        await self._session.flush()
        revision = _new_revision(
            context=context,
            revision=1,
            snapshot=snapshot,
            actor=actor_identity,
            now=now,
        )
        self._session.add(revision)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=tenant.organization_id,
            project_id=context.project_id,
            action="test_context.created",
            resource_type="test_context",
            resource_id=context.id,
            details={
                "revision": 1,
                "fingerprint": revision.fingerprint,
                "required_evidence": [value.value for value in completeness.required],
                "status": context.status,
            },
        )
        await self._session.commit()
        await self._session.refresh(context)
        await self._session.refresh(revision)
        return await self._response(context, revision)

    async def inspect(self, *, actor: User, context_id: UUID) -> TestContextResponse:
        self._require_evidence_scope()
        context = await self._load_context(actor=actor, context_id=context_id)
        await self._mark_expired(actor=actor, context=context)
        revision = await self._current_revision(context)
        return await self._response(context, revision)

    async def requirements(self, *, actor: User, context_id: UUID) -> ContextRequirementsResponse:
        response = await self.inspect(actor=actor, context_id=context_id)
        completeness = response.revision.snapshot.completeness
        return ContextRequirementsResponse(
            context_id=response.id,
            context_revision_id=response.revision.id,
            context_fingerprint=response.revision.fingerprint,
            status=response.status,
            required=completeness.required,
            present=completeness.present,
            missing=completeness.missing,
            complete=completeness.complete,
            conflict_count=len(response.revision.snapshot.conflict_snapshot.conflicts),
            expires_at=response.expires_at,
        )

    async def ingest(
        self,
        *,
        actor: User,
        context_id: UUID,
        envelope: ExternalEvidenceEnvelope,
    ) -> TestContextResponse:
        response, _mapping = await self._ingest(
            actor=actor,
            context_id=context_id,
            envelope=envelope,
            include_mapping_conflicts=False,
        )
        return response

    async def ingest_adapted(
        self,
        *,
        actor: User,
        context_id: UUID,
        envelope: ExternalEvidenceEnvelope,
    ) -> tuple[TestContextResponse, EntityMappingResult]:
        response, mapping = await self._ingest(
            actor=actor,
            context_id=context_id,
            envelope=envelope,
            include_mapping_conflicts=True,
        )
        if mapping is None:
            raise RuntimeError("adapted evidence ingestion must produce entity mapping")
        return response, mapping

    async def inspect_entity_mapping(self, *, actor: User, context_id: UUID) -> EntityMappingResult:
        self._require_evidence_scope()
        context = await self._load_context(actor=actor, context_id=context_id)
        await self._mark_expired(actor=actor, context=context)
        revision = await self._current_revision(context)
        evidence = await self._evidence_items(revision.id)
        return _derive_entity_mapping(_mapping_evidence_inputs(evidence))

    async def _ingest(
        self,
        *,
        actor: User,
        context_id: UUID,
        envelope: ExternalEvidenceEnvelope,
        include_mapping_conflicts: bool,
    ) -> tuple[TestContextResponse, EntityMappingResult | None]:
        self._require_evidence_scope()
        context = await self._load_context(
            actor=actor, context_id=context_id, editing=True, for_update=True
        )
        await self._require_accepting_evidence(actor=actor, context=context)
        _require_same_project(context.project_id, envelope)
        current = await self._current_revision(context, for_update=True)
        existing = await self._evidence_items(current.id)
        if include_mapping_conflicts:
            try:
                envelope = with_mapping_conflict_findings(
                    envelope,
                    _mapping_evidence_inputs(existing),
                )
            except EntityMappingBudgetExceeded as exc:
                raise _mapping_budget_exceeded() from exc
        additions = _new_evidence_items(
            context=context,
            envelope=envelope,
            existing_fingerprints={item.fingerprint for item in existing},
        )
        current_snapshot = _revision_snapshot(current)
        _require_revision_capacity(
            current=current_snapshot,
            envelope=envelope,
            evidence_count=len(existing) + len(additions),
        )
        snapshot = _next_snapshot(
            current=current_snapshot,
            envelope=envelope,
            evidence_fingerprints=[item.fingerprint for item in existing]
            + [item.fingerprint for item in additions],
        )
        now = datetime.now(UTC)
        actor_identity = _actor_identity(actor.id)
        revision = _new_revision(
            context=context,
            revision=context.current_revision + 1,
            snapshot=snapshot,
            actor=actor_identity,
            now=now,
        )
        self._session.add(revision)
        await self._session.flush()
        for item in existing:
            self._session.add(_copy_evidence_item(item, revision.id))
        for item in additions:
            item.context_revision_id = revision.id
            self._session.add(item)
        context.current_revision = revision.revision
        context.status = _context_status(
            snapshot, evidence_count=len(existing) + len(additions)
        ).value
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=context.organization_id,
            project_id=context.project_id,
            action="test_context.evidence_ingested",
            resource_type="test_context_revision",
            resource_id=revision.id,
            details={
                "context_id": str(context.id),
                "revision": revision.revision,
                "context_fingerprint": revision.fingerprint,
                "envelope_fingerprint": external_evidence_fingerprint(envelope),
                "new_finding_count": len(additions),
                "status": context.status,
            },
        )
        await self._session.commit()
        await self._session.refresh(context)
        await self._session.refresh(revision)
        response = await self._response(context, revision)
        mapping = (
            _derive_entity_mapping(_mapping_evidence_inputs([*existing, *additions]))
            if include_mapping_conflicts
            else None
        )
        return response, mapping

    async def close(self, *, actor: User, context_id: UUID) -> TestContextResponse:
        self._require_evidence_scope()
        context = await self._load_context(
            actor=actor, context_id=context_id, editing=True, for_update=True
        )
        await self._mark_expired(actor=actor, context=context)
        if context.status == TestContextStatus.EXPIRED.value:
            raise _context_inactive("TEST_CONTEXT_EXPIRED", "测试上下文已过期")
        if context.status != TestContextStatus.CLOSED.value:
            context.status = TestContextStatus.CLOSED.value
            context.closed_at = datetime.now(UTC)
            self._audit.record(
                actor_user_id=actor.id,
                organization_id=context.organization_id,
                project_id=context.project_id,
                action="test_context.closed",
                resource_type="test_context",
                resource_id=context.id,
                details={"revision": context.current_revision},
            )
            await self._session.commit()
            await self._session.refresh(context)
        revision = await self._current_revision(context)
        return await self._response(context, revision)

    async def require_proposable(
        self,
        *,
        actor: User,
        project_id: UUID,
        context_id: UUID,
        revision_id: UUID,
    ) -> ProposableContext:
        context = await self._load_context(
            actor=actor, context_id=context_id, editing=True, for_update=True
        )
        if context.project_id != project_id:
            raise AppError(
                code="TEST_CONTEXT_NOT_FOUND", message="测试上下文不存在", status_code=404
            )
        await self._mark_expired(actor=actor, context=context)
        if context.status == TestContextStatus.EXPIRED.value:
            raise _context_inactive("TEST_CONTEXT_EXPIRED", "测试上下文已过期")
        if context.status == TestContextStatus.CLOSED.value:
            raise _context_inactive("TEST_CONTEXT_CLOSED", "测试上下文已关闭")
        if context.status != TestContextStatus.READY.value:
            raise AppError(
                code="TEST_CONTEXT_NOT_READY",
                message="测试上下文证据不完整或存在冲突",
                status_code=409,
                details={"status": context.status},
            )
        revision = await self._current_revision(context, for_update=True)
        if revision.id != revision_id:
            raise AppError(
                code="TEST_CONTEXT_REVISION_STALE",
                message="测试上下文 Revision 已不是当前版本",
                status_code=409,
                details={"current_revision": context.current_revision},
            )
        return ProposableContext(
            context=context,
            revision=revision,
            snapshot=_revision_snapshot(revision),
        )

    async def _load_context(
        self,
        *,
        actor: User,
        context_id: UUID,
        editing: bool = False,
        for_update: bool = False,
    ) -> TestContext:
        tenant = get_tenant_context()
        if tenant is None:
            raise AppError(
                code="MCP_AUTHENTICATION_REQUIRED",
                message="MCP 需要服务账号令牌",
                status_code=401,
            )
        query = select(TestContext).where(
            TestContext.id == context_id,
            TestContext.organization_id == tenant.organization_id,
        )
        if for_update:
            query = query.with_for_update()
        context = (await self._session.execute(query)).scalar_one_or_none()
        if context is None:
            raise AppError(
                code="TEST_CONTEXT_NOT_FOUND", message="测试上下文不存在", status_code=404
            )
        await self._projects.authorize(actor=actor, project_id=context.project_id, editing=editing)
        return context

    async def _current_revision(
        self, context: TestContext, *, for_update: bool = False
    ) -> TestContextRevision:
        query = select(TestContextRevision).where(
            TestContextRevision.context_id == context.id,
            TestContextRevision.revision == context.current_revision,
        )
        if for_update:
            query = query.with_for_update()
        revision = (await self._session.execute(query)).scalar_one_or_none()
        if revision is None:
            raise AppError(
                code="TEST_CONTEXT_REVISION_INVALID",
                message="测试上下文当前 Revision 不存在",
                status_code=409,
            )
        return revision

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

    async def _response(
        self, context: TestContext, revision: TestContextRevision
    ) -> TestContextResponse:
        items = await self._evidence_items(revision.id)
        return TestContextResponse(
            id=context.id,
            organization_id=context.organization_id,
            project_id=context.project_id,
            name=context.name,
            objective=context.objective,
            target_environment_id=context.target_environment_id,
            status=TestContextStatus(context.status),
            current_revision=context.current_revision,
            created_by_type=context.created_by_type,
            created_by_id=context.created_by_id,
            expires_at=context.expires_at,
            closed_at=context.closed_at,
            created_at=context.created_at,
            updated_at=context.updated_at,
            revision=_revision_response(revision),
            evidence_items=[_evidence_response(item) for item in items],
        )

    async def _validate_environment(self, *, project_id: UUID, environment_id: UUID | None) -> None:
        if environment_id is None:
            return
        environment = await self._session.get(Environment, environment_id)
        if environment is None or environment.project_id != project_id:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)

    async def _require_accepting_evidence(self, *, actor: User, context: TestContext) -> None:
        await self._mark_expired(actor=actor, context=context)
        if context.status == TestContextStatus.EXPIRED.value:
            raise _context_inactive("TEST_CONTEXT_EXPIRED", "测试上下文已过期")
        if context.status == TestContextStatus.CLOSED.value:
            raise _context_inactive("TEST_CONTEXT_CLOSED", "测试上下文已关闭")

    async def _mark_expired(self, *, actor: User, context: TestContext) -> None:
        if context.status in {
            TestContextStatus.EXPIRED.value,
            TestContextStatus.CLOSED.value,
        } or _as_utc(context.expires_at) > datetime.now(UTC):
            return
        context.status = TestContextStatus.EXPIRED.value
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=context.organization_id,
            project_id=context.project_id,
            action="test_context.expired",
            resource_type="test_context",
            resource_id=context.id,
            details={"revision": context.current_revision},
        )
        await self._session.commit()
        await self._session.refresh(context)

    def _require_evidence_scope(self) -> None:
        tenant = get_tenant_context()
        if tenant is None or MCP_EVIDENCE_WRITE_SCOPE not in tenant.scopes:
            raise AppError(
                code="MCP_SCOPE_REQUIRED",
                message="MCP 需要外部证据写入权限范围",
                status_code=403,
            )


def _actor_identity(user_id: UUID) -> _ActorIdentity:
    tenant = get_tenant_context()
    if tenant is not None and tenant.service_account_id is not None:
        return _ActorIdentity(type="service_account", id=tenant.service_account_id)
    return _ActorIdentity(type="user", id=user_id)


def _new_revision(
    *,
    context: TestContext,
    revision: int,
    snapshot: ContextRevisionSnapshot,
    actor: _ActorIdentity,
    now: datetime,
) -> TestContextRevision:
    normalized = normalize_revision_snapshot(snapshot)
    return TestContextRevision(
        context_id=context.id,
        revision=revision,
        repository_revisions=[
            item.model_dump(mode="json") for item in normalized.repository_revisions
        ],
        contract_revisions=[item.model_dump(mode="json") for item in normalized.contract_revisions],
        data_profile_revisions=[
            item.model_dump(mode="json") for item in normalized.data_profile_revisions
        ],
        existing_test_revision=(
            normalized.existing_test_revision.model_dump(mode="json")
            if normalized.existing_test_revision is not None
            else None
        ),
        knowledge_snapshot=normalized.knowledge_snapshot.model_dump(mode="json"),
        completeness=normalized.completeness.model_dump(mode="json"),
        conflict_snapshot=normalized.conflict_snapshot.model_dump(mode="json"),
        evidence_fingerprints=list(normalized.evidence_fingerprints),
        fingerprint=context_revision_fingerprint(normalized),
        created_by_type=actor.type,
        created_by_id=actor.id,
        created_at=now,
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


def _revision_response(revision: TestContextRevision) -> TestContextRevisionResponse:
    return TestContextRevisionResponse(
        id=revision.id,
        context_id=revision.context_id,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        snapshot=_revision_snapshot(revision),
        created_at=revision.created_at,
    )


def _evidence_response(item: ContextEvidenceItem) -> ContextEvidenceItemResponse:
    return ContextEvidenceItemResponse(
        id=item.id,
        source_type=EvidenceProviderType(item.source_type),
        provider_name=item.provider_name,
        provider_version=item.provider_version,
        source_ref=item.source_ref,
        source_revision=item.source_revision,
        subject_ref=item.subject_ref,
        semantic_role=EvidenceSemanticRole(item.semantic_role),
        deterministic=item.deterministic,
        confidence=item.confidence,
        fingerprint=item.fingerprint,
        data_classification="internal_redacted",
        created_at=item.created_at,
        expires_at=item.expires_at,
    )


def _mapping_evidence_inputs(
    items: list[ContextEvidenceItem],
) -> list[MappingEvidenceInput]:
    return [
        MappingEvidenceInput(
            evidence_ref=f"evidence://context/{item.fingerprint}",
            finding=ExternalEvidenceFinding.model_validate(item.finding_payload),
        )
        for item in items
    ]


def _derive_entity_mapping(evidence: list[MappingEvidenceInput]) -> EntityMappingResult:
    try:
        return derive_entity_mapping(evidence)
    except EntityMappingBudgetExceeded as exc:
        raise _mapping_budget_exceeded() from exc


def _mapping_budget_exceeded() -> AppError:
    return AppError(
        code="ENTITY_MAPPING_BUDGET_EXCEEDED",
        message="实体映射证据或候选数量超过安全上限",
        status_code=422,
    )


def _initial_present_types(payload: BeginTestContextRequest) -> list[EvidenceProviderType]:
    present: list[EvidenceProviderType] = []
    if payload.repository_revisions:
        present.append(EvidenceProviderType.REPOSITORY)
    if payload.contract_revisions:
        present.append(EvidenceProviderType.CONTRACT)
    if payload.data_profile_revisions:
        present.append(EvidenceProviderType.DATA_PROFILE)
    if payload.existing_test_revision is not None:
        present.append(EvidenceProviderType.EXISTING_TEST)
    return present


def _new_evidence_items(
    *,
    context: TestContext,
    envelope: ExternalEvidenceEnvelope,
    existing_fingerprints: set[str],
) -> list[ContextEvidenceItem]:
    now = datetime.now(UTC)
    items: list[ContextEvidenceItem] = []
    for finding in envelope.findings:
        fingerprint = external_evidence_item_fingerprint(envelope, finding)
        if fingerprint in existing_fingerprints:
            raise AppError(
                code="EXTERNAL_EVIDENCE_ALREADY_INGESTED",
                message="外部证据已存在于当前 Revision",
                status_code=409,
                details={"fingerprint": fingerprint},
            )
        existing_fingerprints.add(fingerprint)
        items.append(
            ContextEvidenceItem(
                source_type=envelope.provider.type.value,
                provider_name=envelope.provider.name,
                provider_version=envelope.provider.version,
                source_ref=envelope.source.ref,
                source_revision=envelope.source.revision,
                subject_ref=envelope.subject_ref,
                finding_payload=finding.model_dump(mode="json"),
                semantic_role=finding.semantic_role.value,
                deterministic=finding.deterministic and envelope.deterministic,
                confidence=min(finding.confidence, envelope.confidence),
                fingerprint=fingerprint,
                redactions=[item.model_dump(mode="json") for item in envelope.redactions],
                warnings=[item.model_dump(mode="json") for item in envelope.warnings],
                data_classification="internal_redacted",
                created_at=now,
                expires_at=context.expires_at,
            )
        )
    return items


def _copy_evidence_item(item: ContextEvidenceItem, revision_id: UUID) -> ContextEvidenceItem:
    return ContextEvidenceItem(
        context_revision_id=revision_id,
        source_type=item.source_type,
        provider_name=item.provider_name,
        provider_version=item.provider_version,
        source_ref=item.source_ref,
        source_revision=item.source_revision,
        subject_ref=item.subject_ref,
        finding_payload=dict(item.finding_payload),
        semantic_role=item.semantic_role,
        deterministic=item.deterministic,
        confidence=item.confidence,
        fingerprint=item.fingerprint,
        redactions=list(item.redactions),
        warnings=list(item.warnings),
        data_classification=item.data_classification,
        created_at=item.created_at,
        expires_at=item.expires_at,
    )


def _next_snapshot(
    *,
    current: ContextRevisionSnapshot,
    envelope: ExternalEvidenceEnvelope,
    evidence_fingerprints: list[str],
) -> ContextRevisionSnapshot:
    repository = list(current.repository_revisions)
    contracts = list(current.contract_revisions)
    profiles = list(current.data_profile_revisions)
    existing_test = current.existing_test_revision
    reference = RevisionReference(
        source_ref=envelope.source.ref,
        revision=envelope.source.revision,
    )
    if envelope.provider.type is EvidenceProviderType.REPOSITORY:
        repository = _with_reference(repository, reference)
    elif envelope.provider.type is EvidenceProviderType.CONTRACT:
        contracts = _with_reference(contracts, reference)
    elif envelope.provider.type in {
        EvidenceProviderType.DATA_PROFILE,
        EvidenceProviderType.DATABASE,
    }:
        profiles = _with_reference(profiles, reference)
    elif envelope.provider.type is EvidenceProviderType.EXISTING_TEST:
        existing_test = reference
    present = list(current.completeness.present)
    present.append(envelope.provider.type)
    if envelope.provider.type is EvidenceProviderType.DATABASE:
        present.append(EvidenceProviderType.DATA_PROFILE)
    completeness = completeness_snapshot(current.completeness.required, present)
    conflicts = list(current.conflict_snapshot.conflicts)
    conflicts.extend(_envelope_conflicts(envelope))
    return normalize_revision_snapshot(
        ContextRevisionSnapshot(
            repository_revisions=repository,
            contract_revisions=contracts,
            data_profile_revisions=profiles,
            existing_test_revision=existing_test,
            knowledge_snapshot=current.knowledge_snapshot,
            conflict_snapshot=ContextConflictSnapshot(conflicts=conflicts),
            completeness=completeness,
            evidence_fingerprints=evidence_fingerprints,
        )
    )


def _envelope_conflicts(envelope: ExternalEvidenceEnvelope) -> list[ContextConflict]:
    return [
        ContextConflict(
            subject_ref=finding.subject_ref,
            finding_fingerprints=[external_evidence_item_fingerprint(envelope, finding)],
            summary="外部证据存在冲突",
        )
        for finding in envelope.findings
        if finding.semantic_role is EvidenceSemanticRole.CONFLICT
    ]


def _with_reference(
    values: list[RevisionReference], new_value: RevisionReference
) -> list[RevisionReference]:
    identities = {(item.source_ref, item.revision) for item in values}
    if (new_value.source_ref, new_value.revision) not in identities:
        values.append(new_value)
    return values


def _context_status(snapshot: ContextRevisionSnapshot, *, evidence_count: int) -> TestContextStatus:
    if snapshot.conflict_snapshot.conflicts:
        return TestContextStatus.CONFLICTED
    if snapshot.completeness.complete:
        return TestContextStatus.READY
    return TestContextStatus.INCOMPLETE if evidence_count else TestContextStatus.COLLECTING


def _require_same_project(project_id: UUID, envelope: ExternalEvidenceEnvelope) -> None:
    _require_project_references(project_id, (envelope.source.ref, envelope.subject_ref))


def _require_initial_references_same_project(
    project_id: UUID, payload: BeginTestContextRequest
) -> None:
    references = [
        *payload.repository_revisions,
        *payload.contract_revisions,
        *payload.data_profile_revisions,
    ]
    if payload.existing_test_revision is not None:
        references.append(payload.existing_test_revision)
    _require_project_references(project_id, (item.source_ref for item in references))


def _require_safe_initial_context(payload: BeginTestContextRequest) -> None:
    if first_sensitive_value(payload.model_dump(mode="json")) is not None:
        raise AppError(
            code="TEST_CONTEXT_SENSITIVE_INPUT",
            message="测试上下文包含敏感信息, 请先脱敏后重试",
            status_code=422,
        )


def _require_revision_capacity(
    *,
    current: ContextRevisionSnapshot,
    envelope: ExternalEvidenceEnvelope,
    evidence_count: int,
) -> None:
    if evidence_count > MAX_CONTEXT_EVIDENCE_ITEMS:
        raise _context_capacity_exceeded()
    new_conflicts = sum(
        finding.semantic_role is EvidenceSemanticRole.CONFLICT for finding in envelope.findings
    )
    if len(current.conflict_snapshot.conflicts) + new_conflicts > MAX_CONTEXT_CONFLICTS:
        raise _context_capacity_exceeded()
    references = _revision_references_for_provider(current, envelope.provider.type)
    if references is None:
        return
    identity = (envelope.source.ref, envelope.source.revision)
    identities = {(item.source_ref, item.revision) for item in references}
    if identity not in identities and len(references) >= MAX_CONTEXT_REVISION_REFERENCES:
        raise _context_capacity_exceeded()


def _revision_references_for_provider(
    current: ContextRevisionSnapshot,
    provider_type: EvidenceProviderType,
) -> list[RevisionReference] | None:
    if provider_type is EvidenceProviderType.REPOSITORY:
        return current.repository_revisions
    if provider_type is EvidenceProviderType.CONTRACT:
        return current.contract_revisions
    if provider_type in {
        EvidenceProviderType.DATA_PROFILE,
        EvidenceProviderType.DATABASE,
    }:
        return current.data_profile_revisions
    return None


def _context_capacity_exceeded() -> AppError:
    return AppError(
        code="TEST_CONTEXT_CAPACITY_EXCEEDED",
        message="测试上下文 Revision 已达到容量上限",
        status_code=409,
    )


def _require_project_references(project_id: UUID, values: Iterable[str]) -> None:
    for value in values:
        referenced = referenced_project_id(value)
        if referenced is not None and referenced != str(project_id):
            raise AppError(
                code="EXTERNAL_EVIDENCE_CROSS_TENANT",
                message="外部证据引用不属于当前项目",
                status_code=404,
            )


def _context_inactive(code: str, message: str) -> AppError:
    return AppError(code=code, message=message, status_code=409)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
