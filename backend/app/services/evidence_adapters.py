"""Application service for typed external evidence adapters."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.evidence_adapters import (
    DatabaseEvidenceSubmission,
    EntityMappingResult,
    JavaEvidenceSubmission,
    adapt_database_evidence,
    adapt_java_evidence,
)
from app.models.access import User
from app.schemas.test_contexts import EvidenceAdapterIngestionResponse
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
