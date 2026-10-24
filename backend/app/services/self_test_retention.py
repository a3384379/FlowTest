"""Request-local bounded availability checks; sealed historical verdicts stay immutable."""

import asyncio
from time import monotonic
from uuid import UUID

from app.core.storage import ObjectAvailability
from app.schemas.self_tests import ArtifactReference
from app.services.artifacts import ArtifactService


class SelfTestEvidenceAvailability:
    def __init__(self, artifacts: ArtifactService) -> None:
        self.artifacts = artifacts
        self.remaining = 100
        self.deadline: float | None = None
        self.cache: dict[tuple[UUID, UUID, str], ObjectAvailability] = {}

    async def _probe(self, project: UUID, reference: ArtifactReference) -> ObjectAvailability:
        key = (project, reference.id, reference.sha256)
        if key in self.cache:
            return self.cache[key]
        if self.deadline is None:
            self.deadline = monotonic() + 5.0
        remaining_seconds = self.deadline - monotonic()
        if self.remaining <= 0 or remaining_seconds <= 0:
            return ObjectAvailability.UNAVAILABLE
        self.remaining -= 1
        try:
            async with asyncio.timeout(remaining_seconds):
                result = await self.artifacts.availability(
                    project_id=project,
                    artifact_id=reference.id,
                    expected_sha256=reference.sha256,
                )
        except TimeoutError:
            result = ObjectAvailability.UNAVAILABLE
        self.cache[key] = result
        return result

    async def inspect(
        self, project: UUID, references: tuple[ArtifactReference, ...]
    ) -> ObjectAvailability:
        if not references:
            return ObjectAvailability.UNAVAILABLE
        result = ObjectAvailability.AVAILABLE
        for reference in references:
            current = await self._probe(project, reference)
            if current is ObjectAvailability.MISSING:
                return current
            if current is ObjectAvailability.UNAVAILABLE:
                result = current
        return result
