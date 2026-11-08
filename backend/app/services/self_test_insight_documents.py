"""Read only whitelisted synthetic fields from existing, batch-owned observer artifacts."""

import asyncio
import json
from datetime import datetime
from time import monotonic
from typing import Literal
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.test_design import TestDesignDocument
from app.models.artifacts import Artifact
from app.models.self_tests import SelfTestBatch
from app.schemas.self_tests import ArtifactReference, Digest, FrozenBatchManifest, Identity
from app.services.artifacts import ArtifactService
from app.services.self_test_access import self_test_error


class ObservationField(BaseModel):
    model_config = ConfigDict(extra="ignore")


class InsightNode(ObservationField):
    node_id: Identity
    phase: Literal["main", "cleanup"]
    status: Identity
    error_code: Identity | None = None
    attempts: int = Field(ge=0, le=10000)


class InsightExpected(ObservationField):
    execution_status: Identity
    error_code: Identity | None = None
    node_id: Identity | None = None
    phase: Identity | None = None
    request_count: int | None = Field(default=None, ge=0, le=10000)
    main_status: Identity | None = None
    cleanup_status: Identity | None = None
    top_nodes: tuple[InsightNode, ...] = Field(default=(), max_length=5000)
    nested_nodes: tuple[InsightNode, ...] = Field(default=(), max_length=1000)


class InsightExecution(ObservationField):
    id: UUID
    project_id: UUID
    workflow_id: UUID
    workflow_fingerprint: Identity
    status: Identity
    error_code: Identity | None = None
    main_status: Identity | None = None
    cleanup_status: Identity | None = None
    nodes: tuple[InsightNode, ...] = Field(default=(), max_length=5000)
    nested_nodes: tuple[InsightNode, ...] = Field(default=(), max_length=1000)


class InsightJournal(ObservationField):
    request_count: int = Field(ge=0, le=10000)
    truncated: bool = False
    expired: bool = False


class InsightArtifactScenario(ObservationField):
    scenario_id: Identity
    variant_key: Identity = "default"
    expected: InsightExpected | None = None
    execution: InsightExecution | None = None
    journal: InsightJournal | None = None
    required_oracle_ids: tuple[Identity, ...] = Field(default=(), max_length=500)
    cleanup_status: Identity | None = None


class InsightDocument(ObservationField):
    batch_key: Identity
    scenarios: tuple[InsightArtifactScenario, ...] = Field(max_length=100)


class InsightCall(ObservationField):
    call_id: Identity
    batch_key: Identity
    scenario_id: Identity
    phase: Identity
    tool_name: Identity
    transport: Literal["stdio", "streamable-http"]
    sdk_version: Identity
    protocol_version: Identity
    request_digest: Digest
    result_digest: Digest
    catalog_digest: Digest
    completed_at: datetime
    success: bool


class InsightGeneration(ObservationField):
    scenario_id: Identity
    variant_key: Identity
    design_fingerprint: Digest | None = None
    combined_design_fingerprint: Digest | None = None
    compilation_fingerprint: Digest
    calls: tuple[InsightCall, ...] = Field(min_length=1, max_length=100)
    design: TestDesignDocument | None = None
    combined_design: TestDesignDocument | None = None


class SelfTestInsightDocuments:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.remaining_bytes = 16 * 1024 * 1024
        self.deadline = monotonic() + 5

    async def generation(
        self, batch: SelfTestBatch, reference: ArtifactReference
    ) -> InsightGeneration:
        if reference.model_dump(mode="json") not in batch.artifact_refs:
            raise self_test_error("SELFTEST_ARTIFACT_NOT_OWNED", "来源工件不属于当前批次")
        try:
            loaded = await self._content(batch, reference)
            return InsightGeneration.model_validate_json(loaded)
        except (ValidationError, TimeoutError, AppError) as error:
            raise self_test_error(
                "SELFTEST_INSIGHT_GENERATION_UNAVAILABLE", "生成回执未能完整读取", 503
            ) from error

    async def _content(self, batch: SelfTestBatch, reference: ArtifactReference) -> bytes:
        model = await self.session.get(Artifact, reference.id)
        if model is None or model.project_id != batch.project_id:
            raise self_test_error("SELFTEST_EVIDENCE_UNAVAILABLE", "核验明细工件不可用", 404)
        if model.sha256 != reference.sha256 or model.size_bytes > self.remaining_bytes:
            raise self_test_error(
                "SELFTEST_INSIGHT_ARTIFACT_LIMIT", "核验明细摘要或大小不符合读取限制"
            )
        self.remaining_bytes -= model.size_bytes
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise self_test_error("SELFTEST_INSIGHT_READ_TIMEOUT", "本次明细读取已到有界期限", 503)
        try:
            async with asyncio.timeout(remaining):
                loaded = await ArtifactService(self.session).load(
                    project_id=batch.project_id, artifact_id=reference.id
                )
        except (BotoCoreError, ClientError, OSError) as error:
            raise self_test_error(
                "SELFTEST_EVIDENCE_UNAVAILABLE", "核验明细对象不可用", 503
            ) from error
        return loaded.content

    async def read(self, batch: SelfTestBatch, kind: str) -> InsightDocument | None:
        refs = [ArtifactReference.model_validate(item) for item in batch.artifact_refs]
        found = [item for item in refs if item.kind == kind]
        if not found:
            return None
        if len(found) != 1:
            raise self_test_error("SELFTEST_INSIGHT_ARTIFACT_AMBIGUOUS", "当前批次的观察工件不唯一")
        reference = found[0]
        try:
            document = InsightDocument.model_validate(
                json.loads(await self._content(batch, reference))
            )
        except (ValidationError, ValueError, TimeoutError, AppError) as error:
            raise self_test_error(
                "SELFTEST_INSIGHT_EVIDENCE_UNAVAILABLE",
                "核验明细未能完整读取, 请重试或查看原始证据",
                503,
            ) from error
        keys = [(item.scenario_id, item.variant_key) for item in document.scenarios]
        expected = {
            (item.scenario_id, item.variant_key)
            for item in FrozenBatchManifest.model_validate(batch.frozen_manifest).scenarios
        }
        if (
            document.batch_key != batch.batch_key
            or len(set(keys)) != len(keys)
            or set(keys) != expected
        ):
            raise self_test_error("SELFTEST_INSIGHT_SCOPE_MISMATCH", "核验明细批次或场景集合不符")
        return document
