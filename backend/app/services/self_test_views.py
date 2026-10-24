"""Authorized read projections over frozen metadata and authoritative native runs."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_tests import SelfTestBinding, SelfTestSettings
from app.core.storage import ObjectAvailability
from app.domain.self_tests import aware, document_digest
from app.models.artifacts import Artifact
from app.models.self_tests import SelfTestBatch, SelfTestInstallation, SelfTestScenarioResult
from app.models.tasking import TestPlanRunItem
from app.models.workflows import WorkflowExecution
from app.schemas.self_tests import (
    Actions,
    ArtifactReference,
    BatchResponse,
    ExecutionReference,
    FrozenBatchManifest,
    GenerationState,
    GenerationSummary,
    InstallationResponse,
    ScenarioAssets,
    ScenarioResultResponse,
    SourceReference,
    TemplateScenario,
)
from app.services.artifacts import ArtifactService
from app.services.self_test_retention import SelfTestEvidenceAvailability


class SelfTestViews:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session, self.config = session, config
        self.availability = SelfTestEvidenceAvailability(ArtifactService(session))

    def binding(self, project_id: UUID, binding_id: UUID) -> SelfTestBinding | None:
        return next(
            (
                item
                for item in self.config.bindings
                if item.id == binding_id and project_id in item.allowed_project_ids
            ),
            None,
        )

    def host_status(self, model: SelfTestInstallation, mode: str | None = None) -> str:
        if model.registration_expires_at is None:
            return "not_registered"
        if mode is not None and not self._registered_mode(model, mode):
            return "not_registered"
        return (
            "available" if aware(model.registration_expires_at) > datetime.now(UTC) else "expired"
        )

    def _registered_mode(self, model: SelfTestInstallation, mode: str) -> bool:
        principal = next(
            (item for item in self.config.principals if item.id == model.agent_id), None
        )
        return (
            principal is not None
            and mode in principal.capabilities
            and mode in model.registered_capabilities
        )

    def _generated_template(self, model: SelfTestInstallation) -> bool:
        from app.services.self_test_catalog import templates

        return any(
            item.id == model.template_id and item.batch_kind == "mcp_generated"
            for item in (*templates(), *self.config.extra_templates)
        )

    def installation(self, model: SelfTestInstallation, *, editing: bool) -> InstallationResponse:
        reasons = list(model.reason_codes)
        ready = model.status == "ready"
        binding = self.binding(model.project_id, model.binding_id)
        if binding is None or not binding.enabled:
            reasons.append("SELFTEST_BINDING_UNAVAILABLE")
            ready = False
        if (
            model.lease_expires_at is not None
            and model.status == "installing"
            and aware(model.lease_expires_at) <= datetime.now(UTC)
        ):
            reasons.append("SELFTEST_LEASE_EXPIRED")
        return InstallationResponse.model_validate(
            {
                "id": model.id,
                "project_id": model.project_id,
                "binding_id": model.binding_id,
                "template_id": model.template_id,
                "template_version": model.template_version,
                "pack_digest": model.pack_digest,
                "status": model.status,
                "revision": model.revision,
                "readiness": "ready"
                if ready
                else "needs_input"
                if model.status in {"needs_input", "queued"}
                else "needs_review",
                "reason_codes": reasons,
                "environment_fingerprint": model.environment_fingerprint,
                "mapping": model.resource_mapping,
                "task_id": model.id,
                "created_at": aware(model.created_at),
                "updated_at": aware(model.updated_at),
                "actions": Actions(
                    can_generate=editing and ready and self._generated_template(model),
                    can_execute=editing and ready,
                    reason_codes=tuple(reasons),
                ),
            }
        )

    async def batch(self, model: SelfTestBatch, *, editing: bool) -> BatchResponse:
        await self.session.refresh(model, attribute_names=["updated_at"])
        manifest = FrozenBatchManifest.model_validate(model.frozen_manifest)
        refs = tuple(ArtifactReference.model_validate(item) for item in model.artifact_refs)
        integrity = model.evidence_integrity
        if any([await self.session.get(Artifact, item.id) is None for item in refs]):
            integrity = "expired"
        if model.plan_run_ids and await self._native_metadata_expired(model.id):
            integrity = "expired"
        if model.sealed_at is not None and integrity == "complete":
            availability = await self.availability.inspect(model.project_id, refs)
            if availability is ObjectAvailability.MISSING:
                integrity = "expired"
            elif availability is ObjectAvailability.UNAVAILABLE:
                integrity = "missing"
        if model.sealed_at is not None and integrity == "complete":
            integrity = await self._assisted_integrity(model)
        finished = (
            model.phase in {"completed", "cancelled", "expired"} or model.sealed_at is not None
        )

        reasons = list(model.reason_codes)
        evidence_unavailable = model.sealed_at is not None and integrity != "complete"
        if evidence_unavailable:
            reasons.append(
                "SELFTEST_EVIDENCE_EXPIRED"
                if integrity == "expired"
                else "SELFTEST_EVIDENCE_UNAVAILABLE"
            )
        expired = not finished and aware(model.deadline) <= datetime.now(UTC)
        if expired:
            reasons.append("SELFTEST_BATCH_EXPIRED")
        ready = not expired and (
            (model.readiness == "ready" and model.phase == "ready")
            or (model.phase == "running" and "SELFTEST_DISPATCH_UNCONFIRMED" in model.reason_codes)
        )
        keys = [
            {"scenario_id": item.scenario_id, "variant_key": item.variant_key}
            for item in manifest.scenarios
        ]
        required = [
            key for key, item in zip(keys, manifest.scenarios, strict=True) if item.required
        ]
        return BatchResponse.model_validate(
            {
                "id": model.id,
                "installation_id": model.installation_id,
                "project_id": model.project_id,
                "binding_id": model.binding_id,
                "batch_key": model.batch_key,
                "batch_kind": model.batch_kind,
                "generation_mode": model.generation_mode,
                "generation_stage": model.generation_stage,
                "readiness": "blocked" if expired or evidence_unavailable else model.readiness,
                "reason_codes": reasons,
                "phase": "expired" if expired else model.phase,
                "revision": model.revision,
                "verdict": "blocked" if expired or evidence_unavailable else model.verdict,
                "sealed_verdict": model.verdict if model.sealed_at is not None else None,
                "verification_scope": model.verification_scope,
                "provenance": model.provenance,
                "evidence_integrity": "expired" if expired else integrity,
                "cleanup_status": model.cleanup_status,
                "expected_count": model.expected_count,
                "expected_scenario_set": keys,
                "required_scenario_set": required,
                "manifest_digest": model.manifest_digest,
                "resource_digest": model.resource_digest,
                "policy_digest": model.policy_digest,
                "binding_fingerprint": model.binding_fingerprint,
                "environment_fingerprint": model.environment_fingerprint,
                "builds": model.builds,
                "deadline": aware(model.deadline),
                "created_at": aware(model.created_at),
                "updated_at": aware(model.updated_at),
                "sealed_at": None if model.sealed_at is None else aware(model.sealed_at),
                "plan_run_ids": model.plan_run_ids,
                "plan_id": model.execution_plan_id,
                "suite": model.suite_ref,
                "resource_snapshot": model.resource_snapshot,
                "artifacts": refs,
                "actions": Actions(
                    can_execute=editing and ready,
                    can_cancel=editing and not finished,
                    reason_codes=tuple(reasons),
                ),
            }
        )

    async def _assisted_integrity(self, model: SelfTestBatch) -> str:
        try:
            async with asyncio.timeout(5):
                return await self._ancestor_integrity(model)
        except TimeoutError:
            return "missing"

    async def _ancestor_integrity(self, model: SelfTestBatch) -> str:
        manifest = FrozenBatchManifest.model_validate(model.frozen_manifest)
        identifier = manifest.assisted_before_batch_id
        seen = {model.id}
        while identifier is not None:
            if identifier in seen or len(seen) > 20:
                return "missing"
            seen.add(identifier)
            before = await self.session.get(SelfTestBatch, identifier)
            if before is None or before.project_id != model.project_id:
                return "expired"
            if before.sealed_at is None or before.evidence_integrity != "complete":
                return "missing"
            integrity = await self._ancestor_assets(before)
            if integrity != "complete":
                return integrity
            identifier = FrozenBatchManifest.model_validate(
                before.frozen_manifest
            ).assisted_before_batch_id
        return "complete"

    async def _ancestor_assets(self, model: SelfTestBatch) -> str:
        refs = tuple(ArtifactReference.model_validate(item) for item in model.artifact_refs)
        if any([await self.session.get(Artifact, item.id) is None for item in refs]):
            return "expired"
        if model.plan_run_ids and await self._native_metadata_expired(model.id):
            return "expired"
        available = await self.availability.inspect(model.project_id, refs)
        if available is ObjectAvailability.MISSING:
            return "expired"
        if available is ObjectAvailability.UNAVAILABLE:
            return "missing"
        return "complete"

    async def _native_metadata_expired(self, batch_id: UUID) -> bool:
        rows = (
            await self.session.scalars(
                select(SelfTestScenarioResult).where(SelfTestScenarioResult.batch_id == batch_id)
            )
        ).all()
        for row in rows:
            for value in row.execution_refs:
                reference = ExecutionReference.model_validate(value)
                item = await self.session.get(TestPlanRunItem, reference.run_item_id)
                if item is None:
                    return True
                if item.workflow_execution_id is None and item.status in {
                    "passed",
                    "failed",
                    "cancelled",
                    "quarantined",
                }:
                    return True
                if (
                    reference.execution_id is not None
                    and await self.session.get(WorkflowExecution, reference.execution_id) is None
                ):
                    return True
        return False

    async def scenario(self, row: SelfTestScenarioResult) -> ScenarioResultResponse:
        scenario = TemplateScenario.model_validate(row.frozen_scenario)
        refs = tuple(ExecutionReference.model_validate(item) for item in row.execution_refs)
        archived_refs = refs
        observed = row.observed_status
        complete = True
        if row.run_item_id is not None:
            item = await self.session.get(TestPlanRunItem, row.run_item_id)
            if item is not None:
                observed = item.status
                refs = (
                    ExecutionReference(
                        test_plan_run_id=item.test_plan_run_id,
                        run_item_id=item.id,
                        execution_id=item.workflow_execution_id,
                        target_version=item.target_version,
                        target_snapshot_digest=document_digest(item.target_snapshot),
                    ),
                )
                if item.workflow_execution_id is not None:
                    execution = await self.session.get(
                        WorkflowExecution, item.workflow_execution_id
                    )
                    complete = execution is not None
                elif item.status in {"passed", "failed", "cancelled", "quarantined"}:
                    complete = False
                    refs = archived_refs or refs
            else:
                complete = False
        elif refs:
            complete = False
        return ScenarioResultResponse.model_validate(
            {
                "id": row.id,
                "batch_id": row.batch_id,
                "scenario_id": row.scenario_id,
                "variant_key": row.variant_key,
                "title": scenario.title,
                "category": scenario.category,
                "expected": scenario.expected,
                "observed_status": observed,
                "verification_status": row.verification_status,
                "reason_codes": row.reason_codes,
                "generation_attempt": row.generation_attempt,
                "source": None
                if row.source is None
                else SourceReference.model_validate(row.source),
                "published_assets": None
                if row.published_assets is None
                else ScenarioAssets.model_validate(row.published_assets),
                "executions": refs,
                "evidence_refs": row.evidence_refs,
                "attempts_complete": complete,
            }
        )

    async def generation(
        self,
        batch: SelfTestBatch,
        installation: SelfTestInstallation,
        rows: list[SelfTestScenarioResult],
        *,
        editing: bool,
    ) -> GenerationSummary:
        state = GenerationState.model_validate(batch.generation_summary or {})
        response = await self.batch(batch, editing=editing)
        return GenerationSummary.model_validate(
            {
                "batch_id": batch.id,
                "generation_mode": batch.generation_mode,
                "stage": batch.generation_stage,
                "readiness": response.readiness,
                "reason_codes": response.reason_codes,
                "host_status": self.host_status(installation, batch.generation_mode),
                "tool_call_count": state.tool_call_count,
                "proposals": state.proposals,
                "sources": [
                    SourceReference.model_validate(row.source)
                    for row in rows
                    if row.source is not None
                ],
                "manifest": state.manifest,
                "actions": response.actions,
            }
        )
