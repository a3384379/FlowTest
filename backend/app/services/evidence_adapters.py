"""Application service for typed external evidence adapters."""

from uuid import UUID

from anyio import to_thread
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.evidence_adapters import (
    BUILT_IN_JAVA_SPRING_PROVIDER_NAME,
    BUILT_IN_JAVA_SPRING_PROVIDER_VERSION,
    BuiltInJavaSpringProvider,
    DatabaseEvidenceSubmission,
    EntityMappingResult,
    EvidenceAdapterProvider,
    JavaEvidenceSubmission,
    JavaSourceAnalysisError,
    JavaSourceInput,
    JavaSourceSnapshot,
    adapt_database_evidence,
    adapt_java_evidence,
)
from app.models.access import User
from app.schemas.test_contexts import (
    EvidenceAdapterIngestionResponse,
    JavaSourceSnapshotIngestionResponse,
)
from app.services.test_contexts import TestContextService


class EvidenceAdapterService:
    def __init__(self, session: AsyncSession) -> None:
        self._contexts = TestContextService(session)

    async def ingest_java(
        self,
        *,
        actor: User,
        context_id: UUID,
        evidence: JavaEvidenceSubmission,
    ) -> EvidenceAdapterIngestionResponse:
        context, mapping = await self._contexts.ingest_adapted(
            actor=actor,
            context_id=context_id,
            envelope=adapt_java_evidence(evidence),
        )
        return EvidenceAdapterIngestionResponse(context=context, entity_mapping=mapping)

    async def ingest_java_source_snapshot(
        self,
        *,
        actor: User,
        context_id: UUID,
        source: JavaSourceInput,
    ) -> JavaSourceSnapshotIngestionResponse:
        await self._contexts.require_accepting_evidence_target(
            actor=actor,
            context_id=context_id,
        )
        snapshot = JavaSourceSnapshot(
            **source.model_dump(mode="python"),
            provider=EvidenceAdapterProvider(
                name=BUILT_IN_JAVA_SPRING_PROVIDER_NAME,
                version=BUILT_IN_JAVA_SPRING_PROVIDER_VERSION,
            ),
        )
        try:
            analysis = await to_thread.run_sync(
                BuiltInJavaSpringProvider().analyze,
                snapshot,
                limiter=to_thread.current_default_thread_limiter(),
            )
        except JavaSourceAnalysisError as exc:
            raise AppError(
                code="JAVA_SOURCE_EVIDENCE_NOT_FOUND",
                message="Java/Spring 源码中没有可安全提取的受支持证据",
                status_code=422,
            ) from exc
        except ValidationError as exc:
            raise AppError(
                code="JAVA_SOURCE_EVIDENCE_INVALID",
                message="Java/Spring 静态分析结果未通过安全证据校验",
                status_code=422,
            ) from exc
        context, mapping = await self._contexts.ingest_adapted(
            actor=actor,
            context_id=context_id,
            envelope=adapt_java_evidence(analysis),
        )
        return JavaSourceSnapshotIngestionResponse(
            context=context,
            entity_mapping=mapping,
            analysis=analysis,
        )

    async def ingest_database(
        self,
        *,
        actor: User,
        context_id: UUID,
        evidence: DatabaseEvidenceSubmission,
    ) -> EvidenceAdapterIngestionResponse:
        context, mapping = await self._contexts.ingest_adapted(
            actor=actor,
            context_id=context_id,
            envelope=adapt_database_evidence(evidence),
        )
        return EvidenceAdapterIngestionResponse(context=context, entity_mapping=mapping)

    async def inspect_mapping(self, *, actor: User, context_id: UUID) -> EntityMappingResult:
        return await self._contexts.inspect_entity_mapping(actor=actor, context_id=context_id)
