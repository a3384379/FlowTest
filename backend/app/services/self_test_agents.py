"""External H/O task leases and immutable verification receipts; no local process launch."""

import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.self_tests import SelfTestPrincipal, SelfTestSettings
from app.domain.self_tests import aware, document_digest
from app.models.self_tests import SelfTestBatch, SelfTestInstallation, SelfTestScenarioResult
from app.models.tasking import TestPlanRun
from app.schemas.self_tests import (
    AgentArtifactUpload,
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    AgentTaskList,
    AgentTaskResponse,
    ArtifactReference,
    AssistedBeforeSource,
    BatchResponse,
    Budget,
    ExecuteMaterializedRequest,
    FrozenBatchManifest,
    GenerationProgress,
    GenerationState,
    InstallationMapping,
    InstallationReceipt,
    InstallationResponse,
    LeaseClaim,
    LeaseRequest,
    MaterializedReceipt,
    ScenarioAssets,
    SourceReference,
    VerificationReceipt,
)
from app.services.artifacts import ArtifactService
from app.services.self_test_access import SelfTestAccess, self_test_error, token_digest
from app.services.self_test_assets import SelfTestAssets
from app.services.self_test_assisted import SelfTestAssistedSources
from app.services.self_test_execution import SelfTestNativeExecution
from app.services.self_test_views import SelfTestViews
from app.services.self_tests import SelfTestService
from app.tasking.dispatch import TestPlanDispatcher


class SelfTestAgentService:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session, self.config = session, config
        self.access = SelfTestAccess(session, config)
        self.repository, self.views = self.access.repository, SelfTestViews(session, config)
        self.assets = SelfTestAssets(session)
        self.assisted = SelfTestAssistedSources(session, config)

    async def register(
        self, principal: SelfTestPrincipal, project_id: UUID, payload: AgentRegistrationRequest
    ) -> AgentRegistrationResponse:
        capability = (
            "verify"
            if "verify" in principal.capabilities
            else "install"
            if "install" in principal.capabilities
            else "deterministic_mcp"
        )
        binding = self.access.agent_binding(principal, project_id, payload.binding_id, capability)
        identity = (
            payload.binding_fingerprint == document_digest(binding)
            and payload.environment_fingerprint == binding.environment_fingerprint
            and payload.builds == binding.builds
        )
        if not identity or not set(payload.capabilities) <= set(principal.capabilities):
            raise self_test_error(
                "SELFTEST_AGENT_ATTESTATION_MISMATCH", "外部执行方身份或构建证明不匹配", 403
            )
        rows = await self.repository.installations(project_id, binding.id)
        expiry = datetime.now(UTC) + timedelta(seconds=self.config.registration_seconds)
        if capability != "verify":
            for row in rows:
                row.agent_id, row.host_id, row.registration_expires_at = (
                    principal.id,
                    payload.host_id,
                    expiry,
                )
                row.registered_capabilities = list(payload.capabilities)
                if row.status == "needs_input":
                    row.status, row.reason_codes = "queued", []
                    row.revision += 1
        await self.session.commit()
        batches = await self._batches(project_id, binding.id)
        return AgentRegistrationResponse(
            agent_id=principal.id,
            binding_id=binding.id,
            expires_at=expiry,
            installation_ids=tuple(row.id for row in rows),
            batch_ids=tuple(row.id for row in batches),
        )

    async def tasks(self, principal: SelfTestPrincipal, project_id: UUID) -> AgentTaskList:
        if project_id not in principal.allowed_project_ids:
            raise self_test_error("SELFTEST_AGENT_FORBIDDEN", "外部身份没有项目权限", 403)
        installations = await self.repository.installations(project_id)
        permitted = [
            row for row in installations if row.binding_id in principal.allowed_binding_ids
        ]
        batches = []
        for installation in permitted:
            batches.extend(await self._batches(project_id, installation.binding_id))
        unique = {batch.id: batch for batch in batches}
        registrations = {row.id: row.registered_capabilities for row in permitted}
        permitted_batches = [
            batch
            for batch in unique.values()
            if "verify" in principal.capabilities
            or (
                (batch.generation_mode or "install") in principal.capabilities
                and (
                    batch.generation_mode is None
                    or batch.generation_mode in registrations.get(batch.installation_id, [])
                )
            )
        ]
        return AgentTaskList(
            installations=tuple(self.views.installation(row, editing=False) for row in permitted),
            batches=tuple(
                [await self.views.batch(row, editing=False) for row in permitted_batches[:100]]
            ),
        )

    async def _batches(self, project_id: UUID, binding_id: UUID) -> list[SelfTestBatch]:
        query = (
            select(SelfTestBatch)
            .where(
                SelfTestBatch.project_id == project_id,
                SelfTestBatch.binding_id == binding_id,
                SelfTestBatch.sealed_at.is_(None),
            )
            .order_by(SelfTestBatch.created_at.desc())
            .limit(100)
        )
        return list((await self.session.scalars(query)).all())

    async def claim_installation(
        self, principal: SelfTestPrincipal, project_id: UUID, identifier: UUID, payload: LeaseClaim
    ) -> AgentTaskResponse:
        model = await self.access.installation(project_id, identifier)
        self.access.agent_binding(principal, project_id, model.binding_id, "install")
        self.access.frozen_binding(model)
        await self.access.actor(model.created_by_id, project_id, editing=True)
        if model.agent_id != principal.id or self.views.host_status(model) != "available":
            raise self_test_error(
                "SELFTEST_AGENT_NOT_REGISTERED", "请先登记此绑定的真实执行方", 403
            )
        token = token_urlsafe(48)
        expiry = datetime.now(UTC) + timedelta(seconds=self.config.lease_seconds)
        claimed = await self.repository.claim_installation(
            model,
            expected_revision=payload.expected_revision,
            owner=principal.id,
            lease_hash=token_digest(token),
            nonce_hash=token_digest(payload.nonce),
            expiry=expiry,
        )
        if claimed is None:
            raise self_test_error("SELFTEST_TASK_CLAIM_CONFLICT", "任务已领取或状态版本改变")
        await self.session.commit()
        return await self._task(principal, model, None, token, payload.nonce, "installation")

    async def _task(
        self,
        principal: SelfTestPrincipal,
        installation: SelfTestInstallation,
        batch: SelfTestBatch | None,
        token: str,
        nonce: str,
        kind: str,
    ) -> AgentTaskResponse:
        binding = self.access.frozen_binding(installation)
        model = installation if batch is None else batch
        manifest = (
            None if batch is None else FrozenBatchManifest.model_validate(batch.frozen_manifest)
        )
        if model.lease_expires_at is None:
            raise self_test_error("SELFTEST_LEASE_MISSING", "任务缺少有效租约")
        before_sources: tuple[AssistedBeforeSource, ...] = ()
        if manifest is not None and manifest.assisted_before_batch_id is not None:
            before_sources = await self.assisted.selection_sources(
                model.project_id,
                installation.id,
                binding.id,
                manifest.assisted_before_batch_id,
                manifest.scenarios,
            )
        return AgentTaskResponse.model_validate(
            {
                "task_kind": kind,
                "task_id": model.id,
                "project_id": model.project_id,
                "binding_id": model.binding_id,
                "agent_id": principal.id,
                "revision": model.revision,
                "lease_token": token,
                "lease_expires_at": aware(model.lease_expires_at),
                "nonce": nonce,
                "binding_fingerprint": model.binding_fingerprint,
                "environment_fingerprint": model.environment_fingerprint,
                "builds": binding.builds,
                "installation": self.views.installation(installation, editing=False),
                "batch": None if batch is None else await self.views.batch(batch, editing=False),
                "budget": Budget() if manifest is None else manifest.budget,
                "frozen_manifest": manifest,
                "before_sources": before_sources,
                "sources": ()
                if batch is None
                else tuple(
                    SourceReference.model_validate(row.source)
                    for row in await self.repository.scenarios(batch.id)
                    if row.source is not None
                ),
            }
        )

    async def installed(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: InstallationReceipt,
    ) -> InstallationResponse:
        model = await self.access.installation(project_id, identifier)
        binding = self.access.agent_binding(principal, project_id, model.binding_id, "install")
        self.access.frozen_binding(model)
        digest = document_digest(payload.model_dump(mode="json", exclude={"lease_token"}))
        self.access.lease(model, principal, payload, allow_sealed=model.receipt_digest == digest)
        if model.receipt_digest is not None:
            if model.receipt_digest != digest:
                raise self_test_error(
                    "SELFTEST_INSTALLATION_RECEIPT_CONFLICT", "安装结果已封存为其他内容"
                )
            return self.views.installation(model, editing=False)
        if (
            model.status != "installing"
            or payload.environment_fingerprint != model.environment_fingerprint
        ):
            raise self_test_error(
                "SELFTEST_INSTALLATION_STATE_CONFLICT", "安装状态或环境指纹不匹配"
            )
        await self.access.actor(model.created_by_id, project_id, editing=True)
        template = self.access.template(model.template_id, model.template_version)
        await self.assets.mapping(project_id, binding, template, payload.mapping)
        if await self.repository.lock_installation(model) is None:
            raise self_test_error("SELFTEST_INSTALLATION_BUSY", "安装正在被其他任务修改")
        model.resource_mapping = payload.mapping.model_dump(mode="json")
        model.status, model.reason_codes, model.receipt_digest = "ready", [], digest
        await self.session.commit()
        await self.session.refresh(model)
        return self.views.installation(model, editing=False)

    async def renew_installation(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: LeaseRequest,
    ) -> AgentTaskResponse:
        model = await self.access.installation(project_id, identifier)
        self.access.agent_binding(principal, project_id, model.binding_id, "install")
        self.access.frozen_binding(model)
        self.access.lease(model, principal, payload)
        if model.status != "installing" or await self.repository.lock_installation(model) is None:
            raise self_test_error("SELFTEST_INSTALLATION_STATE_CONFLICT", "安装已结束或正在修改")
        model.lease_expires_at = datetime.now(UTC) + timedelta(seconds=self.config.lease_seconds)
        model.registration_expires_at = datetime.now(UTC) + timedelta(
            seconds=self.config.registration_seconds
        )
        await self.session.commit()
        await self.session.refresh(model)
        return await self._task(
            principal, model, None, payload.lease_token, payload.nonce, "installation"
        )

    async def claim_batch(
        self, principal: SelfTestPrincipal, project_id: UUID, identifier: UUID, payload: LeaseClaim
    ) -> AgentTaskResponse:
        batch = await self.access.batch(project_id, identifier)
        self.access.active_batch(batch)
        await self.access.actor(batch.created_by_id, project_id, editing=True)
        installation = await self.access.installation(project_id, batch.installation_id)
        observation = "verify" in principal.capabilities
        capability = "verify" if observation else batch.generation_mode or "install"
        self.access.agent_binding(principal, project_id, batch.binding_id, capability)
        self.access.frozen_binding(batch)
        kind, phase = await self._claim_kind(batch, installation, principal, observation)
        token = token_urlsafe(48)
        expiry = min(
            aware(batch.deadline), datetime.now(UTC) + timedelta(seconds=self.config.lease_seconds)
        )
        claimed = await self.repository.claim_batch(
            batch,
            expected_revision=payload.expected_revision,
            owner=principal.id,
            lease_hash=token_digest(token),
            nonce_hash=token_digest(payload.nonce),
            expiry=expiry,
            now=datetime.now(UTC),
            phase=phase,
        )
        if claimed is None:
            raise self_test_error(
                "SELFTEST_TASK_CLAIM_CONFLICT", "任务已领取、nonce不符或状态版本改变"
            )
        batch.reason_codes = []
        await self.session.commit()
        return await self._task(principal, installation, batch, token, payload.nonce, kind)

    async def _claim_kind(
        self,
        batch: SelfTestBatch,
        installation: SelfTestInstallation,
        principal: SelfTestPrincipal,
        observation: bool,
    ) -> tuple[str, str]:
        if observation:
            if batch.plan_run_ids:
                await self._observation_runs(batch)
            elif batch.readiness != "blocked":
                raise self_test_error(
                    "SELFTEST_OBSERVATION_NOT_READY", "尚无正式运行或明确阻断结果"
                )
            return "observation", "collecting"
        if (
            installation.agent_id != principal.id
            or self.views.host_status(installation, batch.generation_mode) != "available"
        ):
            raise self_test_error("SELFTEST_AGENT_NOT_REGISTERED", "真实宿主登记缺失或已过期", 403)
        if batch.phase != "pending":
            raise self_test_error(
                "SELFTEST_GENERATION_STATE_CONFLICT", "当前批次不接受新的生成领取"
            )
        return (
            ("generation", "generating")
            if batch.batch_kind == "mcp_generated"
            else ("preparation", "pending")
        )

    async def _observation_runs(self, batch: SelfTestBatch) -> None:
        if batch.phase not in {"running", "collecting"}:
            raise self_test_error("SELFTEST_OBSERVATION_NOT_READY", "尚未提交正式原生运行")
        for value in batch.plan_run_ids:
            run = await self.session.get(TestPlanRun, UUID(value))
            if run is None or run.project_id != batch.project_id:
                raise self_test_error(
                    "SELFTEST_NATIVE_RUN_NOT_FOUND", "本批正式原生运行不存在", 404
                )

    async def _terminal_runs(self, batch: SelfTestBatch) -> None:
        if not batch.plan_run_ids:
            return
        for value in batch.plan_run_ids:
            run = await self.session.get(TestPlanRun, UUID(value))
            if (
                run is None
                or run.project_id != batch.project_id
                or run.status not in {"passed", "failed", "cancelled"}
            ):
                raise self_test_error(
                    "SELFTEST_NATIVE_RUN_NOT_TERMINAL", "原生计划尚未全部终态或证据已到期"
                )
        for row in await self.repository.scenarios(batch.id):
            execution = await self.assets.sync_execution(batch, row)
            if execution is None or execution.status not in {"passed", "failed", "cancelled"}:
                raise self_test_error(
                    "SELFTEST_NATIVE_EXECUTION_NOT_TERMINAL", "子项或正式执行尚未终态"
                )

    async def _writable(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: LeaseRequest,
        capability: str,
    ) -> SelfTestBatch:
        batch = await self.access.batch(project_id, identifier)
        self.access.agent_binding(principal, project_id, batch.binding_id, capability)
        self.access.active_batch(batch)
        self.access.frozen_binding(batch)
        self.access.lease(batch, principal, payload)
        if await self.repository.lock_batch(batch) is None:
            raise self_test_error("SELFTEST_BATCH_BUSY", "批次正在被其他任务修改")
        return batch

    async def renew(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: LeaseRequest,
    ) -> AgentTaskResponse:
        batch = await self.access.batch(project_id, identifier)
        capability = (
            "verify" if "verify" in principal.capabilities else batch.generation_mode or "install"
        )
        batch = await self._writable(principal, project_id, identifier, payload, capability)
        batch.lease_expires_at = min(
            aware(batch.deadline), datetime.now(UTC) + timedelta(seconds=self.config.lease_seconds)
        )
        await self.session.commit()
        installation = await self.access.installation(project_id, batch.installation_id)
        if installation.agent_id == principal.id and capability != "verify":
            installation.registration_expires_at = datetime.now(UTC) + timedelta(
                seconds=self.config.registration_seconds
            )
            await self.session.commit()
            await self.session.refresh(installation)
        kind = (
            "observation"
            if capability == "verify"
            else "generation"
            if batch.batch_kind == "mcp_generated"
            else "preparation"
        )
        return await self._task(
            principal, installation, batch, payload.lease_token, payload.nonce, kind
        )

    async def progress(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: GenerationProgress,
    ) -> BatchResponse:
        initial = await self.access.batch(project_id, identifier)
        batch = await self._writable(
            principal,
            project_id,
            identifier,
            payload,
            initial.generation_mode or "deterministic_mcp",
        )
        if (
            batch.batch_kind != "mcp_generated"
            or batch.phase not in {"generating", "awaiting_review"}
            or payload.stage == "ready"
            or payload.readiness == "ready"
        ):
            raise self_test_error(
                "SELFTEST_GENERATION_STATE_CONFLICT",
                "仅真实生成任务可上报提案阶段; ready由发布校验产生",
            )
        previous = GenerationState.model_validate(batch.generation_summary or {})
        stages = (
            "discovering",
            "reading_contract",
            "designing",
            "compiling",
            "proposing",
            "awaiting_review",
            "publishing",
            "blocked",
        )
        if payload.stage not in stages or stages.index(payload.stage) < stages.index(
            batch.generation_stage
        ):
            raise self_test_error(
                "SELFTEST_GENERATION_STAGE_REGRESSED", "生成阶段不能倒退或绕过正式发布"
            )
        manifest = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        if manifest.assisted_before_batch_id is not None and payload.tool_call_count != 0:
            raise self_test_error(
                "SELFTEST_ASSISTED_MODEL_CALL_UNEXPECTED", "辅助重跑不能计入新的模型调用"
            )
        if (
            not previous.tool_call_count
            <= payload.tool_call_count
            <= manifest.budget.max_tool_calls
        ):
            raise self_test_error(
                "SELFTEST_TOOL_BUDGET_EXCEEDED", "真实工具次数必须递增且不超过冻结预算"
            )
        for proposal in payload.proposals:
            await self.assets.proposal(project_id, proposal, accepted=False)
        if payload.manifest is not None:
            await self._owned_artifact(batch, payload.manifest)
        batch.generation_summary = GenerationState(
            tool_call_count=payload.tool_call_count,
            proposals=payload.proposals,
            manifest=payload.manifest,
        ).model_dump(mode="json")
        batch.generation_stage, batch.readiness, batch.reason_codes = (
            payload.stage,
            payload.readiness,
            list(payload.reason_codes),
        )
        batch.phase = (
            "awaiting_review"
            if payload.stage in {"awaiting_review", "publishing", "blocked"}
            else "generating"
        )
        if payload.stage == "blocked":
            batch.readiness = "blocked"
            batch.lease_hash = None
        await self.session.commit()
        return await self.views.batch(batch, editing=False)

    async def materialized(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: MaterializedReceipt,
    ) -> BatchResponse:
        initial = await self.access.batch(project_id, identifier)
        batch = await self._writable(
            principal,
            project_id,
            identifier,
            payload,
            initial.generation_mode or "deterministic_mcp",
        )
        if batch.batch_kind != "mcp_generated" or batch.phase not in {
            "generating",
            "awaiting_review",
        }:
            raise self_test_error("SELFTEST_GENERATION_STATE_CONFLICT", "当前批次不接受物化结果")
        rows = await self.repository.scenarios(batch.id)
        expected = {(row.scenario_id, row.variant_key): row for row in rows}
        actual = [(item.scenario_id, item.variant_key) for item in payload.sources]
        if len(actual) != len(set(actual)) or set(actual) != set(expected):
            raise self_test_error(
                "SELFTEST_MATERIALIZED_SET_MISMATCH", "生成资产必须与全部冻结场景精确一致"
            )
        actor = await self.access.actor(batch.created_by_id, project_id, editing=True)
        installation = await self.access.installation(project_id, batch.installation_id)
        mapping = InstallationMapping.model_validate(installation.resource_mapping)
        self._host_sources(principal, batch, payload)
        await self._owned_artifact(batch, payload.manifest)
        for source in payload.sources:
            await self.assisted.validate(batch, source)
            await self._owned_artifact(batch, source.generation_manifest)
            await self.assets.source(actor, project_id, mapping, source)
            row = expected[(source.scenario_id, source.variant_key)]
            row.source, row.published_assets = (
                source.model_dump(mode="json"),
                ScenarioAssets.model_validate(
                    source.model_dump(include={"scenario_id", "variant_key", "workflow", "case"})
                ).model_dump(mode="json"),
            )
            row.generation_attempt += 1
        await self._ready(batch, rows)
        await self.session.commit()
        return await self.views.batch(batch, editing=False)

    def _host_sources(
        self, principal: SelfTestPrincipal, batch: SelfTestBatch, payload: MaterializedReceipt
    ) -> None:
        if batch.generation_mode != "host_llm_mcp":
            if any(source.host_evidence is not None for source in payload.sources):
                raise self_test_error(
                    "SELFTEST_HOST_EVIDENCE_UNEXPECTED", "确定性协议生成不接受模型来源声明"
                )
            return
        manifest = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        if manifest.assisted_before_batch_id is not None:
            self._assisted_authorization(principal, batch, payload)
            return
        evidence = tuple(
            source.host_evidence for source in payload.sources if source.host_evidence is not None
        )
        if len(evidence) != len(payload.sources):
            raise self_test_error(
                "SELFTEST_HOST_EVIDENCE_MISSING", "真实宿主生成必须附带模型和预算证据"
            )
        if any(
            (
                value.host != batch.host_id
                or value.authorized_budget_digest not in principal.authorized_host_budget_digests
            )
            for value in evidence
        ):
            raise self_test_error(
                "SELFTEST_HOST_EVIDENCE_UNAUTHORIZED", "宿主身份或显式模型预算未获部署授权", 403
            )
        shared = evidence[0]
        if any(value != shared for value in evidence):
            raise self_test_error(
                "SELFTEST_HOST_EVIDENCE_INCONSISTENT", "同一批次来源必须引用同一宿主调用记录"
            )
        manifest = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        if shared.actual_tool_calls > manifest.budget.max_tool_calls:
            raise self_test_error("SELFTEST_TOOL_BUDGET_EXCEEDED", "真实宿主工具次数超过冻结预算")

    @staticmethod
    def _assisted_authorization(
        principal: SelfTestPrincipal, batch: SelfTestBatch, payload: MaterializedReceipt
    ) -> None:
        lineages = tuple(source.assisted for source in payload.sources)
        if any(item is None for item in lineages):
            raise self_test_error(
                "SELFTEST_ASSISTED_LINEAGE_MISSING", "辅助批次的每项来源必须保留修订链"
            )
        grants = {item.authorization_digest for item in lineages if item is not None}
        if len(grants) != 1 or not grants <= set(principal.authorized_host_budget_digests):
            raise self_test_error(
                "SELFTEST_HOST_EVIDENCE_UNAUTHORIZED", "当前辅助任务未获独立签名授权", 403
            )
        if GenerationState.model_validate(batch.generation_summary or {}).tool_call_count != 0:
            raise self_test_error(
                "SELFTEST_ASSISTED_MODEL_CALL_UNEXPECTED", "辅助重跑不能冒充新的模型生成"
            )

    async def _ready(self, batch: SelfTestBatch, rows: list[SelfTestScenarioResult]) -> None:
        actor = await self.access.actor(batch.created_by_id, batch.project_id, editing=True)
        manifest = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        installation = await self.access.installation(batch.project_id, batch.installation_id)
        mapping = InstallationMapping.model_validate(installation.resource_mapping)
        binding = self.access.binding(batch.project_id, batch.binding_id)
        await self.assets.mapping(batch.project_id, binding, manifest.template, mapping)
        await self.assets.request_budget(
            tuple(ScenarioAssets.model_validate(row.published_assets) for row in rows),
            manifest.budget.max_requests,
        )
        snapshot = await SelfTestNativeExecution(self.session).freeze(actor, batch, rows)
        resources: list[JsonValue] = [
            {
                "scenario_id": row.scenario_id,
                "variant_key": row.variant_key,
                "assets": row.published_assets,
                "source_digest": None if row.source is None else document_digest(row.source),
            }
            for row in rows
        ]
        batch.resource_digest = document_digest(
            {
                "binding_fingerprint": batch.binding_fingerprint,
                "environment_fingerprint": batch.environment_fingerprint,
                "resources": resources,
                "snapshot": snapshot.model_dump(mode="json"),
            }
        )
        batch.generation_stage, batch.readiness, batch.phase = "ready", "ready", "ready"
        batch.reason_codes, batch.lease_hash = [], None

    async def prepared(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: LeaseRequest,
        dispatcher: TestPlanDispatcher,
    ) -> BatchResponse:
        batch = await self._writable(principal, project_id, identifier, payload, "install")
        if batch.batch_kind != "fixed_baseline" or batch.phase != "pending":
            raise self_test_error(
                "SELFTEST_PREPARATION_STATE_CONFLICT", "此批次不是待准备的固定基准"
            )
        rows = await self.repository.scenarios(batch.id)
        if any(row.published_assets is None for row in rows):
            raise self_test_error("SELFTEST_FIXED_ASSETS_MISSING", "固定包发布映射不完整")
        await self._ready(batch, rows)
        await self.session.commit()
        actor = await self.access.actor(batch.created_by_id, project_id, editing=True)
        request = ExecuteMaterializedRequest(
            resource_digest=batch.resource_digest,
            environment_fingerprint=batch.environment_fingerprint,
            confirmed=True,
        )
        return await SelfTestService(self.session, self.config).execute_native(
            actor, batch, request, dispatcher
        )

    async def upload(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: AgentArtifactUpload,
    ) -> ArtifactReference:
        initial = await self.access.batch(project_id, identifier)
        capability = (
            "verify" if "verify" in principal.capabilities else initial.generation_mode or "install"
        )
        batch = await self._writable(principal, project_id, identifier, payload, capability)
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
        except (ValueError, binascii.Error) as error:
            raise self_test_error(
                "SELFTEST_ARTIFACT_ENCODING_INVALID", "文件编码无效", 422
            ) from error
        if not content or len(content) > self.config.artifact_limit_bytes:
            raise self_test_error("SELFTEST_ARTIFACT_TOO_LARGE", "证据文件必须为有界非空内容", 413)
        if payload.content_type == "application/json":
            try:
                json.loads(content)
            except (ValueError, UnicodeError) as error:
                raise self_test_error(
                    "SELFTEST_ARTIFACT_JSON_INVALID", "证据 JSON 无效", 422
                ) from error
        actor = await self.access.actor(batch.created_by_id, project_id, editing=False)
        artifact = await ArtifactService(self.session).store_response(
            actor=actor,
            project_id=project_id,
            filename=payload.filename,
            content_type=payload.content_type,
            content=content,
        )
        reference = ArtifactReference(id=artifact.id, sha256=artifact.sha256, kind=payload.kind)
        batch.artifact_refs = [*batch.artifact_refs, reference.model_dump(mode="json")]
        if len(batch.artifact_refs) > 100:
            raise self_test_error(
                "SELFTEST_ARTIFACT_LIMIT_EXCEEDED", "批次文件数量超过冻结上限", 422
            )
        await self.session.commit()
        return reference

    async def _owned_artifact(self, batch: SelfTestBatch, reference: ArtifactReference) -> None:
        if reference.model_dump(mode="json") not in batch.artifact_refs:
            raise self_test_error("SELFTEST_ARTIFACT_NOT_OWNED", "文件不是通过本批任务上传")
        await self.assets.artifact(batch.project_id, reference)
        await ArtifactService(self.session).load(
            project_id=batch.project_id, artifact_id=reference.id
        )

    async def verification(
        self,
        principal: SelfTestPrincipal,
        project_id: UUID,
        identifier: UUID,
        payload: VerificationReceipt,
    ) -> BatchResponse:
        batch = await self.access.batch(project_id, identifier)
        self.access.agent_binding(principal, project_id, batch.binding_id, "verify")
        digest = document_digest(payload.model_dump(mode="json", exclude={"lease_token"}))
        if batch.receipt_digest is not None:
            self.access.lease(batch, principal, payload, allow_sealed=True)
            if batch.receipt_digest != digest:
                raise self_test_error("SELFTEST_RECEIPT_CONFLICT", "此批次已经封存为不同核验内容")
            return await self.views.batch(batch, editing=False)
        batch = await self._writable(principal, project_id, identifier, payload, "verify")
        await self._terminal_runs(batch)
        self._verification_identity(batch, payload)
        for reference in payload.artifacts:
            await self._owned_artifact(batch, reference)
        rows = await self.repository.scenarios(batch.id)
        actual = {(value.scenario_id, value.variant_key): value for value in payload.scenarios}
        if len(actual) != len(payload.scenarios) or set(actual) != {
            (row.scenario_id, row.variant_key) for row in rows
        }:
            raise self_test_error(
                "SELFTEST_VERIFICATION_SET_MISMATCH", "核验结果必须覆盖全部冻结场景且无重复"
            )
        for row in rows:
            value = actual[(row.scenario_id, row.variant_key)]
            execution = await self.assets.sync_execution(batch, row)
            if value.verification_status == "matched":
                await self._matched_execution(row.frozen_scenario, value.observed_status, execution)
                if not value.evidence_refs:
                    raise self_test_error(
                        "SELFTEST_SCENARIO_EVIDENCE_MISSING", "matched 场景必须具有本批独立证据"
                    )
            for reference in value.evidence_refs:
                await self._owned_artifact(batch, reference)
            row.observed_status, row.verification_status = (
                value.observed_status,
                value.verification_status,
            )
            row.reason_codes, row.evidence_refs = (
                list(value.reason_codes),
                [item.model_dump(mode="json") for item in value.evidence_refs],
            )
        matched = all(value.verification_status == "matched" for value in payload.scenarios)
        complete = payload.evidence_integrity == "complete"
        batch.verdict = (
            "passed"
            if matched
            and complete
            and payload.cleanup_status == "completed"
            and payload.batch_verdict == "passed"
            else "failed"
            if payload.batch_verdict == "failed"
            or any(value.verification_status == "mismatched" for value in payload.scenarios)
            else "blocked"
        )
        batch.evidence_integrity = payload.evidence_integrity
        batch.reason_codes = list(payload.batch_reason_codes)
        if principal.trusted_verifier and batch.ci_run_id is None:
            raise self_test_error(
                "SELFTEST_CI_IDENTITY_REQUIRED", "受信结果必须绑定部署冻结的 CI run"
            )
        batch.provenance = "trusted_ci" if principal.trusted_verifier else "local_untrusted"
        batch.cleanup_status, batch.phase = payload.cleanup_status, "completed"
        batch.receipt_digest, batch.sealed_at = digest, datetime.now(UTC)
        await self.session.commit()
        return await self.views.batch(batch, editing=False)

    def _verification_identity(self, batch: SelfTestBatch, payload: VerificationReceipt) -> None:
        identity = (
            payload.manifest_digest,
            payload.resource_digest,
            payload.policy_digest,
            payload.builds.model_dump(mode="json"),
        )
        expected = (batch.manifest_digest, batch.resource_digest, batch.policy_digest, batch.builds)
        if identity != expected:
            raise self_test_error(
                "SELFTEST_VERIFICATION_IDENTITY_MISMATCH", "核验构建、清单或资源集合不匹配"
            )
        if (payload.ci_run_id is None) != (payload.ci_attempt is None):
            raise self_test_error(
                "SELFTEST_CI_IDENTITY_INCOMPLETE", "CI run 与 attempt 必须同时提供", 422
            )
        if (payload.ci_run_id, payload.ci_attempt) != (batch.ci_run_id, batch.ci_attempt):
            raise self_test_error("SELFTEST_CI_IDENTITY_MISMATCH", "核验 CI 身份不是批次冻结身份")

    async def _matched_execution(
        self, frozen: dict[str, JsonValue], observed: str | None, execution: object
    ) -> None:
        from app.models.workflows import WorkflowExecution, WorkflowNodeExecution
        from app.schemas.self_tests import TemplateScenario

        expected = TemplateScenario.model_validate(frozen).expected
        if (
            not isinstance(execution, WorkflowExecution)
            or execution.status != observed
            or execution.status != expected.status
            or execution.status in {"queued", "running"}
        ):
            raise self_test_error(
                "SELFTEST_NATIVE_RESULT_MISMATCH", "独立 matched 与原始正式执行终态不一致"
            )
        if expected.error_code is not None and execution.error_code != expected.error_code:
            raise self_test_error("SELFTEST_NATIVE_ERROR_MISMATCH", "原始失败错误码不符合冻结期望")
        if expected.phase is not None:
            node = await self.session.scalar(
                select(WorkflowNodeExecution.id)
                .where(
                    WorkflowNodeExecution.workflow_execution_id == execution.id,
                    WorkflowNodeExecution.phase == expected.phase,
                    WorkflowNodeExecution.status == "failed",
                    WorkflowNodeExecution.error_code == expected.error_code,
                )
                .limit(1)
            )
            if node is None:
                raise self_test_error(
                    "SELFTEST_NATIVE_PHASE_MISMATCH", "原生失败阶段与冻结期望不符"
                )
