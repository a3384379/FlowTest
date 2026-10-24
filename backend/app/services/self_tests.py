"""Product self-test orchestration over deployment bindings and existing native plans."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.self_tests import SelfTestBinding, SelfTestSettings
from app.domain.access import ProjectCapability
from app.domain.mcp_read import MCPCallType, MCPReadCall, input_schema_hash
from app.domain.self_tests import aware, document_digest
from app.models.access import User
from app.models.self_tests import SelfTestBatch, SelfTestInstallation, SelfTestScenarioResult
from app.models.workflows import WorkflowExecution
from app.schemas.self_tests import (
    Actions,
    BatchCreate,
    BatchResponse,
    BindingResponse,
    ExecuteMaterializedRequest,
    FrozenBatchManifest,
    GenerationBatchCreate,
    GenerationSummary,
    InstallationCreate,
    InstallationMapping,
    InstallationPreviewRequest,
    InstallationPreviewResponse,
    InstallationResponse,
    InstallationSummary,
    PlannedResource,
    PreflightCheck,
    ResourceSnapshot,
    ScenarioAssets,
    ScenarioExecutionRelation,
    ScenarioResultResponse,
    SelfTestPage,
    SourceReference,
    TemplateResponse,
    TemplateScenario,
)
from app.schemas.test_design import MCPControlledWriteCreate, MCPControlledWriteEnvelope
from app.services.artifacts import ArtifactContent, ArtifactService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.mcp_controlled_write import MCPControlledWriteService
from app.services.projects import ProjectService
from app.services.self_test_access import SelfTestAccess, self_test_error
from app.services.self_test_assets import SelfTestAssets
from app.services.self_test_assisted import SelfTestAssistedSources
from app.services.self_test_cancellation import SelfTestCancellation
from app.services.self_test_execution import SelfTestNativeExecution
from app.services.self_test_views import SelfTestViews
from app.tasking.dispatch import TestPlanDispatcher


class SelfTestService:
    def __init__(self, session: AsyncSession, config: SelfTestSettings) -> None:
        self.session, self.config = session, config
        self.access = SelfTestAccess(session, config)
        self.repository = self.access.repository
        self.views = SelfTestViews(session, config)
        self.assets = SelfTestAssets(session)

    async def authorize(self, actor: User, project_id: UUID, *, editing: bool = False) -> bool:
        access = await ProjectService(self.session).authorize(
            actor=actor, project_id=project_id, editing=editing
        )
        return access.role is None or access.role.allows(ProjectCapability.EDIT)

    async def templates(self, actor: User, project_id: UUID) -> SelfTestPage[TemplateResponse]:
        await self.authorize(actor, project_id)
        catalog = self.access.catalog()
        return SelfTestPage(items=catalog, total=len(catalog))

    async def bindings(self, actor: User, project_id: UUID) -> SelfTestPage[BindingResponse]:
        editing = await self.authorize(actor, project_id)
        values = []
        for binding in self.config.bindings:
            if project_id in binding.allowed_project_ids:
                values.append(await self._binding_view(project_id, binding, editing))
        return SelfTestPage(items=tuple(values), total=len(values))

    async def _binding_view(
        self, project_id: UUID, binding: SelfTestBinding, editing: bool
    ) -> BindingResponse:
        installations = await self.repository.installations(project_id, binding.id)
        registered = any(self.views.host_status(item) == "available" for item in installations)
        safe = (
            all(
                (
                    binding.enabled,
                    binding.non_production,
                    binding.isolated,
                    binding.outbound_authorized,
                )
            )
            and binding.runner_instance_id != binding.target_instance_id
            and self.config.fixture_run_depth == 0
        )
        reasons = (
            ("SELFTEST_RECURSION_LIMIT_REACHED",)
            if self.config.fixture_run_depth >= 1
            else ()
            if safe
            else ("SELFTEST_BINDING_UNSAFE",)
        )
        if binding.agent_id is None:
            reasons = (*reasons, "WAITING_FOR_HOST")
        return BindingResponse(
            id=binding.id,
            name=binding.name,
            fingerprint=document_digest(binding),
            environment_fingerprint=binding.environment_fingerprint,
            runner_instance_id=binding.runner_instance_id,
            target_instance_id=binding.target_instance_id,
            target_display=binding.target_display,
            fixture_display=binding.fixture_display,
            builds=binding.builds,
            runtime_profile=binding.runtime_profile,
            host_status="available" if registered else "not_registered",
            observer_status="available" if binding.observer_id is not None else "not_configured",
            readiness="ready" if safe else "blocked",
            reason_codes=reasons,
            installations=tuple(
                InstallationSummary.model_validate(
                    {"id": item.id, "pack_digest": item.pack_digest, "status": item.status}
                )
                for item in installations[:20]
            ),
            actions=Actions(
                can_initialize=editing and safe,
                can_execute=editing and safe,
                can_generate=editing and safe,
                reason_codes=reasons,
            ),
        )

    async def preview(
        self,
        actor: User,
        project_id: UUID,
        payload: InstallationPreviewRequest,
        *,
        expires_at: datetime | None = None,
    ) -> InstallationPreviewResponse:
        await self.authorize(actor, project_id, editing=True)
        binding = self.access.binding(project_id, payload.binding_id)
        template = self.access.template(payload.template_id, payload.template_version)
        expiry = expires_at or datetime.now(UTC) + timedelta(seconds=self.config.preview_seconds)
        existing = await self.repository.installed_pack(
            project_id, binding.id, template.pack_digest
        )
        checks = (
            *self._preflight(binding),
            *await self._mapping_preflight(project_id, binding, template, existing),
        )
        conflicts = tuple(check.code for check in checks if check.status == "blocked")
        if existing is not None and existing.binding_fingerprint != document_digest(binding):
            conflicts = (*conflicts, "SELFTEST_INSTALLATION_BINDING_CHANGED")
        fingerprint = self._preview_fingerprint(
            actor.id, project_id, payload, binding, template, expiry, conflicts
        )
        return InstallationPreviewResponse(
            fingerprint=fingerprint,
            expires_at=expiry,
            binding_id=binding.id,
            template=template,
            can_apply=not conflicts,
            checks=checks,
            conflicts=conflicts,
            resources=(
                PlannedResource(
                    kind="environment", action="reuse" if existing else "create", count=2
                ),
                PlannedResource(kind="service", action="reuse" if existing else "create", count=2),
            ),
            existing_installation_id=None if existing is None else existing.id,
        )

    async def _mapping_preflight(
        self,
        project_id: UUID,
        binding: SelfTestBinding,
        template: TemplateResponse,
        installation: SelfTestInstallation | None,
    ) -> tuple[PreflightCheck, ...]:
        if (
            installation is None
            or installation.status != "ready"
            or installation.resource_mapping is None
        ):
            return ()
        try:
            await self.assets.mapping(
                project_id,
                binding,
                template,
                InstallationMapping.model_validate(installation.resource_mapping),
            )
        except AppError as error:
            if error.code not in {
                "SELFTEST_REMOTE_MAPPING_MISMATCH",
                "SELFTEST_ENVIRONMENT_MAPPING_INVALID",
                "SELFTEST_SERVICE_MAPPING_INVALID",
                "SELFTEST_INSTALLATION_ASSET_SET_MISMATCH",
                "SELFTEST_ASSET_NOT_FOUND",
                "SELFTEST_ASSET_VERSION_CHANGED",
                "SELFTEST_CASE_TARGET_CHANGED",
            }:
                raise
            return (PreflightCheck(code=error.code, status="blocked", message=error.message),)
        return ()

    def _preflight(self, binding: SelfTestBinding) -> tuple[PreflightCheck, ...]:
        states = (
            ("SELFTEST_NON_PRODUCTION", binding.non_production, "目标为已登记的非生产环境"),
            (
                "SELFTEST_ISOLATED",
                binding.isolated and binding.runner_instance_id != binding.target_instance_id,
                "A/B 实例及数据域隔离",
            ),
            ("SELFTEST_OUTBOUND_AUTHORIZED", binding.outbound_authorized, "目标出站规则已授权"),
            ("SELFTEST_BINDING_ENABLED", binding.enabled, "部署绑定已启用"),
        )
        checks = tuple(
            PreflightCheck(code=code, status="passed" if enabled else "blocked", message=message)
            for code, enabled, message in states
        )
        if self.config.fixture_run_depth >= 1:
            checks = (
                *checks,
                PreflightCheck(
                    code="SELFTEST_RECURSION_LIMIT_REACHED",
                    status="blocked",
                    message="业务夹具实例不能继续发起系统自测",
                ),
            )
        if binding.observer_id is None:
            checks = (
                *checks,
                PreflightCheck(
                    code="SELFTEST_OBSERVER_NOT_CONFIGURED",
                    status="warning",
                    message="未配置独立 Observer, 原生执行不会自动获得独立核验",
                ),
            )
        return checks

    def _preview_fingerprint(
        self,
        actor_id: UUID,
        project_id: UUID,
        payload: InstallationPreviewRequest,
        binding: SelfTestBinding,
        template: TemplateResponse,
        expiry: datetime,
        conflicts: tuple[str, ...],
    ) -> str:
        document = {
            "actor": str(actor_id),
            "project": str(project_id),
            "request": payload.model_dump(mode="json"),
            "binding": document_digest(binding),
            "template": document_digest(template),
            "expiry": aware(expiry).isoformat(),
            "conflicts": list(conflicts),
        }
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(settings.secret_key.encode(), encoded, hashlib.sha256).hexdigest()

    async def install(
        self, actor: User, project_id: UUID, payload: InstallationCreate, key: str | None
    ) -> InstallationResponse:
        await self.authorize(actor, project_id, editing=True)
        key = require_idempotency_key(key)
        request = InstallationPreviewRequest.model_validate(
            payload.model_dump(exclude={"preview_fingerprint", "preview_expires_at"})
        )
        prior = await self.repository.installation_by_key(project_id, key)
        if prior is not None:
            if prior.request_digest != document_digest(request) or prior.created_by_id != actor.id:
                raise self_test_error("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他安装请求")
            return self.views.installation(prior, editing=True)
        now, expiry = datetime.now(UTC), aware(payload.preview_expires_at)
        if not now < expiry <= now + timedelta(seconds=self.config.preview_seconds):
            raise self_test_error("SELFTEST_PREVIEW_EXPIRED", "安装预览已失效, 请重新预检")
        preview = await self.preview(actor, project_id, request, expires_at=expiry)
        if not preview.can_apply or not hmac.compare_digest(
            preview.fingerprint, payload.preview_fingerprint
        ):
            raise self_test_error("SELFTEST_PREVIEW_CHANGED", "安装预览或目标已变化, 请重新预检")
        binding = self.access.binding(project_id, payload.binding_id)
        existing = await self.repository.installed_pack(
            project_id, binding.id, preview.template.pack_digest
        )
        if existing is not None:
            return self.views.installation(existing, editing=True)
        model = SelfTestInstallation(
            id=uuid4(),
            project_id=project_id,
            binding_id=binding.id,
            template_id=preview.template.id,
            template_version=preview.template.version,
            pack_digest=preview.template.pack_digest,
            status="needs_input",
            revision=0,
            reason_codes=["WAITING_FOR_HOST"],
            binding_fingerprint=document_digest(binding),
            environment_fingerprint=binding.environment_fingerprint,
            resource_mapping=None,
            idempotency_key=key,
            request_digest=document_digest(request),
            created_by_id=actor.id,
        )
        self.session.add(model)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise self_test_error(
                "SELFTEST_INSTALLATION_CONFLICT", "安装请求冲突, 请读取既有安装后核对"
            ) from error
        await self.session.refresh(model)
        return self.views.installation(model, editing=True)

    async def installation(
        self, actor: User, project_id: UUID, identifier: UUID
    ) -> InstallationResponse:
        editing = await self.authorize(actor, project_id)
        return self.views.installation(
            await self.access.installation(project_id, identifier), editing=editing
        )

    async def create_batch(
        self, actor: User, project_id: UUID, identifier: UUID, payload: BatchCreate, key: str | None
    ) -> BatchResponse:
        await self.authorize(actor, project_id, editing=True)
        installation = await self.access.installation(project_id, identifier)
        binding = self.access.frozen_binding(installation)
        if installation.status != "ready" or installation.resource_mapping is None:
            raise self_test_error("SELFTEST_INSTALLATION_NOT_READY", "请先完成本绑定的安装")
        template = self.access.template(installation.template_id, installation.template_version)
        generated = isinstance(payload, GenerationBatchCreate)
        if generated != (template.batch_kind == "mcp_generated"):
            raise self_test_error("SELFTEST_BATCH_KIND_MISMATCH", "模板类型与运行入口不匹配", 422)
        return await self._new_batch(
            actor, installation, binding, template, payload, require_idempotency_key(key)
        )

    async def _new_batch(
        self,
        actor: User,
        installation: SelfTestInstallation,
        binding: SelfTestBinding,
        template: TemplateResponse,
        payload: BatchCreate,
        key: str,
    ) -> BatchResponse:
        request_digest = document_digest(
            {"installation_id": str(installation.id), "payload": payload.model_dump(mode="json")}
        )
        existing = await self.repository.batch_by_key(installation.project_id, key)
        if existing is not None:
            if existing.request_digest != request_digest or existing.created_by_id != actor.id:
                raise self_test_error("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他自测请求")
            return await self.views.batch(existing, editing=True)
        await self.assets.mapping(
            installation.project_id,
            binding,
            template,
            InstallationMapping.model_validate(installation.resource_mapping),
        )
        scenarios = self._select_scenarios(template, payload)
        await self._fixed_budget(installation, template, scenarios, payload.budget.max_requests)
        mode = payload.generation_mode if isinstance(payload, GenerationBatchCreate) else None
        host_id = payload.host_id if isinstance(payload, GenerationBatchCreate) else None
        if host_id is not None and host_id != installation.host_id:
            raise self_test_error("SELFTEST_HOST_NOT_REGISTERED", "只能选择此绑定登记的宿主", 403)
        host_id = host_id or installation.host_id
        before_id = (
            payload.assisted_before_batch_id if isinstance(payload, GenerationBatchCreate) else None
        )
        if before_id is not None:
            if mode != "host_llm_mcp":
                raise self_test_error(
                    "SELFTEST_ASSISTED_MODE_INVALID", "辅助修订必须保留真实宿主来源"
                )
            await SelfTestAssistedSources(self.session, self.config).selection_sources(
                installation.project_id, installation.id, binding.id, before_id, scenarios
            )
        now, identifier = datetime.now(UTC), uuid4()
        manifest = FrozenBatchManifest(
            assisted_before_batch_id=before_id,
            batch_id=identifier,
            installation_id=installation.id,
            project_id=installation.project_id,
            binding_id=binding.id,
            template=template,
            scenarios=scenarios,
            batch_kind=template.batch_kind,
            generation_mode=mode,
            verification_scope=payload.verification_scope,
            budget=payload.budget,
            binding_fingerprint=document_digest(binding),
            environment_fingerprint=binding.environment_fingerprint,
            builds=binding.builds,
            created_at=now,
            deadline=now + timedelta(seconds=payload.budget.timeout_seconds),
        )
        keys: list[JsonValue] = [
            {"scenario_id": item.scenario_id, "variant_key": item.variant_key} for item in scenarios
        ]
        required = [key for key, item in zip(keys, scenarios, strict=True) if item.required]
        model = SelfTestBatch(
            id=identifier,
            project_id=installation.project_id,
            installation_id=installation.id,
            binding_id=binding.id,
            batch_key=f"selftest-{identifier.hex}",
            batch_kind=template.batch_kind,
            generation_mode=mode,
            generation_stage="discovering",
            readiness="needs_input",
            reason_codes=["WAITING_FOR_HOST"],
            phase="pending",
            verdict="pending",
            verification_scope=payload.verification_scope,
            expected_count=len(scenarios),
            frozen_manifest=manifest.model_dump(mode="json"),
            manifest_digest=document_digest(manifest),
            expected_set_digest=document_digest(keys),
            required_set_digest=document_digest(required),
            policy_digest=document_digest(
                {
                    "template": document_digest(template),
                    "required": required,
                    "scope": payload.verification_scope,
                }
            ),
            binding_fingerprint=document_digest(binding),
            environment_fingerprint=binding.environment_fingerprint,
            builds=binding.builds.model_dump(mode="json"),
            idempotency_key=key,
            request_digest=request_digest,
            created_by_id=actor.id,
            created_at=now,
            host_id=host_id,
            deadline=manifest.deadline,
            ci_run_id=binding.ci_run_id,
            ci_attempt=binding.ci_attempt,
        )
        self.session.add(model)
        mapping = InstallationMapping.model_validate(installation.resource_mapping)
        frozen_assets = {(item.scenario_id, item.variant_key): item for item in mapping.assets}
        for position, scenario in enumerate(scenarios):
            asset = frozen_assets.get((scenario.scenario_id, scenario.variant_key))
            self.session.add(
                SelfTestScenarioResult(
                    id=uuid4(),
                    batch_id=identifier,
                    scenario_id=scenario.scenario_id,
                    variant_key=scenario.variant_key,
                    position=position,
                    frozen_scenario=scenario.model_dump(mode="json"),
                    published_assets=None if asset is None else asset.model_dump(mode="json"),
                )
            )
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise self_test_error(
                "SELFTEST_BATCH_CONFLICT", "批次请求并发冲突, 请按幂等键核对"
            ) from error
        await self.session.refresh(model)
        return await self.views.batch(model, editing=True)

    async def _fixed_budget(
        self,
        installation: SelfTestInstallation,
        template: TemplateResponse,
        scenarios: tuple[TemplateScenario, ...],
        maximum: int,
    ) -> None:
        if template.batch_kind != "fixed_baseline":
            return
        selected = {(item.scenario_id, item.variant_key) for item in scenarios}
        mapping = InstallationMapping.model_validate(installation.resource_mapping)
        assets = tuple(
            item for item in mapping.assets if (item.scenario_id, item.variant_key) in selected
        )
        await self.assets.request_budget(assets, maximum)

    def _select_scenarios(
        self, template: TemplateResponse, payload: BatchCreate
    ) -> tuple[TemplateScenario, ...]:
        requested = set(payload.scenario_ids) or {item.scenario_id for item in template.scenarios}
        selected = tuple(item for item in template.scenarios if item.scenario_id in requested)
        if {item.scenario_id for item in selected} != requested or not any(
            item.required for item in selected
        ):
            raise self_test_error(
                "SELFTEST_SCENARIO_SELECTION_INVALID", "场景集合必须有效且包含必测项", 422
            )
        if payload.verification_scope == "full_pack" and len(selected) != len(template.scenarios):
            raise self_test_error(
                "SELFTEST_FULL_PACK_INCOMPLETE", "完整模板不能减少冻结场景集合", 422
            )
        return selected

    async def list_batches(
        self,
        actor: User,
        project_id: UUID,
        identifier: UUID,
        *,
        cursor: UUID | None,
        page_size: int,
    ) -> SelfTestPage[BatchResponse]:
        editing = await self.authorize(actor, project_id)
        await self.access.installation(project_id, identifier)
        rows, total = await self.repository.batches(
            project_id, identifier, cursor=cursor, limit=page_size
        )
        more = len(rows) > page_size
        return SelfTestPage(
            items=tuple([await self.views.batch(row, editing=editing) for row in rows[:page_size]]),
            total=total,
            has_more=more,
            next_cursor=rows[page_size - 1].id if more else None,
        )

    async def batch(self, actor: User, project_id: UUID, identifier: UUID) -> BatchResponse:
        editing = await self.authorize(actor, project_id)
        return await self.views.batch(
            await self.access.batch(project_id, identifier), editing=editing
        )

    async def generation(
        self, actor: User, project_id: UUID, identifier: UUID
    ) -> GenerationSummary:
        editing = await self.authorize(actor, project_id)
        batch = await self.access.batch(project_id, identifier)
        installation = await self.access.installation(project_id, batch.installation_id)
        return await self.views.generation(
            batch, installation, await self.repository.scenarios(batch.id), editing=editing
        )

    async def scenarios(
        self,
        actor: User,
        project_id: UUID,
        identifier: UUID,
        *,
        page: int,
        page_size: int,
        category: str | None,
        verification: str | None,
        scenario_id: str | None = None,
    ) -> SelfTestPage[ScenarioResultResponse]:
        await self.authorize(actor, project_id)
        batch = await self.access.batch(project_id, identifier)
        values = [
            await self.views.scenario(row) for row in await self.repository.scenarios(batch.id)
        ]
        filtered = [
            value
            for value in values
            if (category is None or value.category == category)
            and (verification is None or value.verification_status == verification)
            and (scenario_id is None or value.scenario_id == scenario_id)
        ]
        offset = (page - 1) * page_size
        return SelfTestPage(
            items=tuple(filtered[offset : offset + page_size]),
            total=len(filtered),
            has_more=offset + page_size < len(filtered),
        )

    async def relation(
        self, actor: User, project_id: UUID, batch_id: UUID, scenario_id: str, execution_id: UUID
    ) -> ScenarioExecutionRelation:
        batch = await self.batch(actor, project_id, batch_id)
        rows = await self.repository.scenarios(batch_id)
        execution = await self.session.get(WorkflowExecution, execution_id)
        if execution is None or execution.project_id != project_id:
            rows = []
        for found in rows:
            scenario = await self.views.scenario(found)
            if found.scenario_id == scenario_id and any(
                reference.execution_id == execution_id for reference in scenario.executions
            ):
                return ScenarioExecutionRelation(
                    batch=batch, scenario=scenario, execution_id=execution_id
                )
        raise self_test_error(
            "SELFTEST_EXECUTION_RELATION_NOT_FOUND", "该执行未关联此自测场景", 404
        )

    async def execute(
        self,
        actor: User,
        project_id: UUID,
        identifier: UUID,
        payload: ExecuteMaterializedRequest,
        key: str | None,
        dispatcher: TestPlanDispatcher,
    ) -> BatchResponse:
        await self.authorize(actor, project_id, editing=True)
        key = require_idempotency_key(key)

        cached = await IdempotencyService(self.session).completed_response(
            key=key,
            project_id=project_id,
            actor_key=f"user:{actor.id}",
            operation=f"selftest.execute:{identifier}",
            request_payload=payload.model_dump(mode="json"),
        )
        if cached is not None:
            batch = await self.access.batch(project_id, identifier)
            if "SELFTEST_DISPATCH_UNCONFIRMED" in batch.reason_codes:
                return await self.execute_native(actor, batch, payload, dispatcher)
            return await self.views.batch(batch, editing=True)

        async def action() -> BatchResponse:
            return await self.execute_native(
                actor, await self.access.batch(project_id, identifier), payload, dispatcher
            )

        response = await IdempotencyService(self.session).run(
            key=key,
            project_id=project_id,
            actor_key=f"user:{actor.id}",
            operation=f"selftest.execute:{identifier}",
            request_payload=payload.model_dump(mode="json"),
            action=action,
        )
        return BatchResponse.model_validate(response)

    async def assisted_case_proposal(
        self, actor: User, project_id: UUID, identifier: UUID, payload: MCPControlledWriteCreate
    ) -> MCPControlledWriteEnvelope:
        await self.authorize(actor, project_id, editing=True)
        batch = await self.access.batch(project_id, identifier)
        self.access.active_batch(batch)
        manifest = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        if (
            manifest.assisted_before_batch_id is None
            or batch.generation_mode != "host_llm_mcp"
            or batch.phase not in {"pending", "generating", "awaiting_review"}
        ):
            raise self_test_error(
                "SELFTEST_ASSISTED_TASK_REQUIRED", "仅当前辅助修订任务可提交人工用例提案"
            )
        if payload.project_id != project_id:
            raise self_test_error(
                "SELFTEST_ASSISTED_PROJECT_MISMATCH", "提案项目与当前任务不符", 422
            )
        await SelfTestAssistedSources(self.session, self.config).selection_sources(
            project_id,
            batch.installation_id,
            batch.binding_id,
            manifest.assisted_before_batch_id,
            manifest.scenarios,
        )
        call = MCPReadCall(
            operation="selftest_assisted_case_proposal",
            call_type=MCPCallType.TOOL,
            input_schema_hash=input_schema_hash("selftest:assisted_case_proposal"),
            client_version="flowtest-product",
        )
        return await MCPControlledWriteService(self.session).propose_for_user(
            actor=actor, payload=payload, call=call, batch_id=batch.id
        )

    async def execute_native(
        self,
        actor: User,
        batch: SelfTestBatch,
        payload: ExecuteMaterializedRequest,
        dispatcher: TestPlanDispatcher,
    ) -> BatchResponse:
        self.access.active_batch(batch)
        self.access.frozen_binding(batch)
        await self.authorize(actor, batch.project_id, editing=True)
        identity = (payload.resource_digest, payload.environment_fingerprint)
        if identity != (batch.resource_digest, batch.environment_fingerprint):
            raise self_test_error(
                "SELFTEST_EXECUTION_NOT_READY", "执行确认指纹不符合冻结资源或环境"
            )
        if batch.phase == "running" and "SELFTEST_DISPATCH_UNCONFIRMED" in batch.reason_codes:
            snapshot = ResourceSnapshot.model_validate(batch.resource_snapshot)
            await SelfTestNativeExecution(self.session).resume_dispatch(
                actor, batch, snapshot, dispatcher
            )
            return await self.views.batch(batch, editing=True)
        if (
            batch.phase != "ready"
            or batch.readiness != "ready"
            or payload.resource_digest != batch.resource_digest
            or payload.environment_fingerprint != batch.environment_fingerprint
        ):
            raise self_test_error("SELFTEST_EXECUTION_NOT_READY", "生成来源、发布版本或环境未就绪")
        installation = await self.access.installation(batch.project_id, batch.installation_id)
        mapping = InstallationMapping.model_validate(installation.resource_mapping)
        rows = await self.repository.scenarios(batch.id)
        assets = tuple(ScenarioAssets.model_validate(row.published_assets) for row in rows)
        manifest = FrozenBatchManifest.model_validate(batch.frozen_manifest)
        binding = self.access.binding(batch.project_id, batch.binding_id)
        await self.assets.mapping(batch.project_id, binding, manifest.template, mapping)
        await self.assets.assets(batch.project_id, mapping, assets)
        await self.assets.request_budget(assets, manifest.budget.max_requests)
        for row in rows:
            if row.source is not None:
                source = SourceReference.model_validate(row.source)
                await SelfTestAssistedSources(self.session, self.config).validate(batch, source)
                await self.assets.source(actor, batch.project_id, mapping, source)
        snapshot = ResourceSnapshot.model_validate(batch.resource_snapshot)
        native = SelfTestNativeExecution(self.session)
        await native.validate_plan(actor, batch, snapshot)
        if await self.repository.lock_batch(batch) is None:
            raise self_test_error("SELFTEST_BATCH_BUSY", "批次正在被其他任务修改")
        batch.phase, batch.lease_hash, batch.reason_codes = "running", None, []
        await native.queue(actor, batch, rows, snapshot, dispatcher)
        return await self.views.batch(batch, editing=True)

    async def cancel(self, actor: User, project_id: UUID, identifier: UUID) -> BatchResponse:
        await self.authorize(actor, project_id, editing=True)
        batch = await self.access.batch(project_id, identifier)
        return await SelfTestCancellation(self.session, self.config).cancel(actor, batch)

    async def download(
        self, actor: User, project_id: UUID, identifier: UUID, artifact_id: UUID
    ) -> ArtifactContent:
        await self.authorize(actor, project_id)
        batch = await self.access.batch(project_id, identifier)
        if artifact_id not in {UUID(str(reference["id"])) for reference in batch.artifact_refs}:
            raise self_test_error("SELFTEST_ARTIFACT_NOT_FOUND", "文件不属于此批次", 404)
        return await ArtifactService(self.session).download(
            actor=actor, project_id=project_id, artifact_id=artifact_id
        )
