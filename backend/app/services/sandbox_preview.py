import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import get_tenant_context
from app.core.errors import AppError
from app.domain.sandbox_preview import (
    MCP_PREVIEW_EXECUTE_SCOPE,
    EnvironmentClassification,
    PreviewBudget,
)
from app.models.access import User
from app.models.ai import AIChangeSet
from app.models.api_assets import Environment
from app.models.organizations import ServiceAccount
from app.models.sandbox_preview import SandboxPreviewApproval
from app.models.service_targets import ServiceEndpoint
from app.models.test_contexts import TestContextRevision
from app.models.workflows import Workflow, WorkflowExecution
from app.schemas.sandbox_preview import SandboxPreviewApprovalCreate, SandboxPreviewExecuteRequest
from app.services.audit import AuditService
from app.services.flow_spec import FlowSpecService, FlowSpecVisualProposal
from app.services.projects import ProjectService
from app.services.test_contexts import ProposableContext, TestContextService
from app.services.workflows import WorkflowExecutionPlan, WorkflowService


@dataclass(frozen=True, slots=True)
class PreviewableProposal:
    visual: FlowSpecVisualProposal
    context: ProposableContext


class SandboxPreviewService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        workflows: WorkflowService | None = None,
    ) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._flow_specs = FlowSpecService(session)
        self._contexts = TestContextService(session)
        self._audit = AuditService(session)
        self._workflows = workflows or WorkflowService(session)

    async def create_approval(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set_id: UUID,
        payload: SandboxPreviewApprovalCreate,
    ) -> SandboxPreviewApproval:
        access = await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        organization_id = access.project.organization_id
        if organization_id is None:
            raise AppError(
                code="PREVIEW_ORGANIZATION_REQUIRED",
                message="Sandbox Preview 要求项目属于明确的 Organization",
                status_code=409,
            )
        proposal = await self._previewable(
            actor=actor,
            project_id=project_id,
            change_set_id=change_set_id,
            lock=False,
        )
        environment = await self._preview_environment(project_id, payload.environment_id)
        environment_fingerprint = await self._environment_fingerprint(environment)
        executor_kind, executor_id = await self._approval_executor(
            actor=actor,
            project_id=project_id,
            organization_id=organization_id,
            service_account_id=payload.executor_service_account_id,
        )
        approval = SandboxPreviewApproval(
            organization_id=organization_id,
            project_id=project_id,
            change_set_id=change_set_id,
            environment_id=payload.environment_id,
            environment_fingerprint=environment_fingerprint,
            runtime_input_fingerprint=_runtime_input_fingerprint(
                payload.runtime_variables,
                payload.runtime_headers,
            ),
            executor_kind=executor_kind,
            executor_id=executor_id,
            proposal_fingerprint=proposal.visual.view.pipeline.fingerprint,
            context_revision_id=proposal.context.revision.id,
            context_fingerprint=proposal.context.revision.fingerprint,
            budget=payload.budget.model_dump(mode="json"),
            expires_at=datetime.now(UTC) + timedelta(seconds=payload.ttl_seconds),
            consumed_at=None,
            execution_id=None,
            created_by_id=actor.id,
        )
        self._session.add(approval)
        await self._session.flush()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=approval.organization_id,
            project_id=project_id,
            action="sandbox_preview.approval_created",
            resource_type="sandbox_preview_approval",
            resource_id=approval.id,
            details={
                "change_set_id": str(change_set_id),
                "environment_id": str(payload.environment_id),
                "executor_kind": executor_kind,
                "expires_at": approval.expires_at.isoformat(),
            },
        )
        await self._session.commit()
        await self._session.refresh(approval)
        return approval

    async def prepare_execution(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set_id: UUID,
        payload: SandboxPreviewExecuteRequest,
    ) -> tuple[WorkflowExecution, WorkflowExecutionPlan]:
        proposal = await self._previewable(
            actor=actor,
            project_id=project_id,
            change_set_id=change_set_id,
            lock=True,
        )
        environment = await self._preview_environment(project_id, payload.environment_id)
        environment_fingerprint = await self._environment_fingerprint(environment)
        approval = await self._approval_for_update(
            project_id=project_id,
            change_set_id=change_set_id,
            approval_id=payload.approval_id,
        )
        self._validate_approval(
            actor=actor,
            approval=approval,
            proposal=proposal,
            environment_id=payload.environment_id,
            environment_fingerprint=environment_fingerprint,
            runtime_input_fingerprint=_runtime_input_fingerprint(
                payload.runtime_variables,
                payload.runtime_headers,
            ),
        )
        budget = PreviewBudget.model_validate(approval.budget)
        execution, plan = await self._workflows.prepare_preview_execution(
            actor=actor,
            project_id=project_id,
            workflow_id=proposal.visual.view.item.target_resource_id,
            change_set_id=change_set_id,
            approval_id=approval.id,
            proposal_fingerprint=proposal.visual.view.pipeline.fingerprint,
            context_fingerprint=proposal.context.revision.fingerprint,
            definition=proposal.visual.proposed_definition,
            environment_id=payload.environment_id,
            runtime_variables=payload.runtime_variables,
            runtime_headers=payload.runtime_headers,
            budget=budget,
        )
        now = datetime.now(UTC)
        approval.consumed_at = now
        approval.execution_id = execution.id
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=approval.organization_id,
            project_id=project_id,
            action="sandbox_preview.started",
            resource_type="workflow_execution",
            resource_id=execution.id,
            details={
                "change_set_id": str(change_set_id),
                "approval_id": str(approval.id),
                "environment_id": str(payload.environment_id),
                "run_purpose": "preview",
            },
        )
        await self._session.commit()
        await self._session.refresh(execution)
        return execution, plan

    async def _previewable(
        self,
        *,
        actor: User,
        project_id: UUID,
        change_set_id: UUID,
        lock: bool,
    ) -> PreviewableProposal:
        visual = await self._flow_specs.get_visual_proposal(
            actor=actor,
            project_id=project_id,
            change_set_id=change_set_id,
        )
        if lock:
            await self._lock_change_set(change_set_id, project_id)
        self._require_accepted(visual)
        self._require_no_blockers(visual)
        await self._require_current_target(visual, project_id, lock=lock)
        context_id = _snapshot_uuid(visual, "context_revision_id")
        context_fingerprint = _snapshot_string(visual, "context_fingerprint")
        if context_id is None or context_fingerprint is None:
            raise AppError(
                code="PREVIEW_CONTEXT_REQUIRED",
                message="Sandbox Preview 仅接受绑定当前 Context Revision 的 Proposal",
                status_code=409,
            )
        revision = await self._session.get(TestContextRevision, context_id)
        if revision is None:
            raise AppError(
                code="PREVIEW_CONTEXT_REQUIRED",
                message="Sandbox Preview Proposal 的 Context Revision 不存在",
                status_code=409,
            )
        context = await self._contexts.require_proposable(
            actor=actor,
            project_id=project_id,
            context_id=revision.context_id,
            revision_id=context_id,
        )
        if context.revision.fingerprint != context_fingerprint:
            raise AppError(
                code="PREVIEW_CONTEXT_MISMATCH",
                message="Sandbox Preview Context Fingerprint 不匹配",
                status_code=409,
            )
        return PreviewableProposal(visual=visual, context=context)

    async def _approval_executor(
        self,
        *,
        actor: User,
        project_id: UUID,
        organization_id: UUID,
        service_account_id: UUID | None,
    ) -> tuple[str, UUID]:
        if service_account_id is None:
            return "user", actor.id
        await self._projects.authorize_owner(actor=actor, project_id=project_id)
        account = await self._session.get(ServiceAccount, service_account_id)
        if not _service_account_can_preview(account, organization_id):
            raise AppError(
                code="PREVIEW_EXECUTOR_INVALID",
                message="一次性 Approval 指定的服务账号不可用于 Sandbox Preview",
                status_code=422,
            )
        return "service_account", service_account_id

    async def _preview_environment(self, project_id: UUID, environment_id: UUID) -> Environment:
        environment = await self._session.scalar(
            select(Environment).where(
                Environment.id == environment_id,
                Environment.project_id == project_id,
            )
        )
        if environment is None:
            raise AppError(code="ENVIRONMENT_NOT_FOUND", message="环境不存在", status_code=404)
        classification = EnvironmentClassification(environment.classification)
        if classification is EnvironmentClassification.PRODUCTION:
            raise AppError(
                code="PRODUCTION_PREVIEW_FORBIDDEN",
                message="Production Environment 永久禁止 Sandbox Preview",
                status_code=403,
            )
        if not classification.allows_preview:
            raise AppError(
                code="PREVIEW_ENVIRONMENT_FORBIDDEN",
                message="Sandbox Preview 只允许 Test 或 Sandbox Environment",
                status_code=409,
                details={"classification": classification.value},
            )
        return environment

    async def _approval_for_update(
        self,
        *,
        project_id: UUID,
        change_set_id: UUID,
        approval_id: UUID,
    ) -> SandboxPreviewApproval:
        approval = await self._session.scalar(
            select(SandboxPreviewApproval)
            .where(
                SandboxPreviewApproval.id == approval_id,
                SandboxPreviewApproval.project_id == project_id,
                SandboxPreviewApproval.change_set_id == change_set_id,
            )
            .with_for_update()
        )
        if approval is None:
            raise AppError(
                code="PREVIEW_APPROVAL_NOT_FOUND",
                message="Sandbox Preview 一次性 Approval 不存在",
                status_code=404,
            )
        return approval

    async def _environment_fingerprint(self, environment: Environment) -> str:
        endpoints = list(
            (
                await self._session.scalars(
                    select(ServiceEndpoint)
                    .where(ServiceEndpoint.environment_id == environment.id)
                    .order_by(
                        ServiceEndpoint.service_id,
                        ServiceEndpoint.variant,
                        ServiceEndpoint.id,
                    )
                )
            ).all()
        )
        return _environment_target_fingerprint(environment, endpoints)

    def _validate_approval(
        self,
        *,
        actor: User,
        approval: SandboxPreviewApproval,
        proposal: PreviewableProposal,
        environment_id: UUID,
        environment_fingerprint: str,
        runtime_input_fingerprint: str,
    ) -> None:
        if approval.consumed_at is not None or approval.execution_id is not None:
            raise AppError(
                code="PREVIEW_APPROVAL_REPLAYED",
                message="Sandbox Preview 一次性 Approval 已被消费",
                status_code=409,
            )
        if _as_utc(approval.expires_at) <= datetime.now(UTC):
            raise AppError(
                code="PREVIEW_APPROVAL_EXPIRED",
                message="Sandbox Preview 一次性 Approval 已过期",
                status_code=409,
            )
        if approval.environment_fingerprint != environment_fingerprint:
            raise AppError(
                code="PREVIEW_APPROVAL_TARGET_CHANGED",
                message="Sandbox Preview 环境目标在审批后已变更, 请重新审批",
                status_code=409,
            )
        if not hmac.compare_digest(
            approval.runtime_input_fingerprint,
            runtime_input_fingerprint,
        ):
            raise AppError(
                code="PREVIEW_APPROVAL_INPUT_MISMATCH",
                message="Sandbox Preview 运行时输入与审批内容不匹配",
                status_code=409,
            )
        executor_kind, executor_id = _current_executor(actor)
        bindings_match = (
            approval.executor_kind == executor_kind
            and approval.executor_id == executor_id
            and approval.environment_id == environment_id
            and approval.proposal_fingerprint == proposal.visual.view.pipeline.fingerprint
            and approval.context_revision_id == proposal.context.revision.id
            and approval.context_fingerprint == proposal.context.revision.fingerprint
        )
        if not bindings_match:
            raise AppError(
                code="PREVIEW_APPROVAL_MISMATCH",
                message="Sandbox Preview Approval 与 Actor、环境或证据指纹不匹配",
                status_code=409,
            )

    async def _lock_change_set(self, change_set_id: UUID, project_id: UUID) -> None:
        change_set = await self._session.scalar(
            select(AIChangeSet)
            .where(AIChangeSet.id == change_set_id, AIChangeSet.project_id == project_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if change_set is None:
            raise AppError(
                code="FLOWSPEC_CHANGE_SET_NOT_FOUND",
                message="FlowSpec 变更集不存在",
                status_code=404,
            )

    @staticmethod
    def _require_accepted(visual: FlowSpecVisualProposal) -> None:
        view = visual.view
        if view.change_set.status != "accepted" or view.item.review_status != "accepted":
            raise AppError(
                code="PREVIEW_REVIEW_REQUIRED",
                message="FlowSpec Proposal 必须人工接受后才能 Sandbox Preview",
                status_code=409,
            )
        if view.change_set.applied_at is not None:
            raise AppError(
                code="PREVIEW_PROPOSAL_ALREADY_APPLIED",
                message="已应用的 FlowSpec Proposal 不能再创建 Sandbox Preview",
                status_code=409,
            )

    @staticmethod
    def _require_no_blockers(visual: FlowSpecVisualProposal) -> None:
        pipeline = visual.view.pipeline
        unresolved = [
            item.id
            for item in (
                visual.integration_plan.unresolved_items if visual.integration_plan else []
            )
            if item.severity == "blocker"
        ]
        if not pipeline.validation.valid or pipeline.compatibility.blockers or unresolved:
            raise AppError(
                code="PREVIEW_PROPOSAL_BLOCKED",
                message="FlowSpec Proposal 存在未解决 Blocker",
                status_code=422,
                details={"unresolved_items": unresolved},
            )
        if visual.compilation is not None and not visual.compilation.importable:
            raise AppError(
                code="PREVIEW_PROPOSAL_BLOCKED",
                message="FlowSpec Proposal 编译结果不可执行",
                status_code=422,
            )

    async def _require_current_target(
        self,
        visual: FlowSpecVisualProposal,
        project_id: UUID,
        *,
        lock: bool,
    ) -> None:
        target_id = visual.view.item.target_resource_id
        if target_id is None:
            return
        query = select(Workflow).where(
            Workflow.id == target_id,
            Workflow.project_id == project_id,
        )
        if lock:
            query = query.execution_options(populate_existing=True).with_for_update()
        workflow = await self._session.scalar(query)
        expected = visual.view.change_set.source_snapshot.get("target_revision")
        if workflow is None or workflow.draft_revision != expected:
            raise AppError(
                code="PREVIEW_PROPOSAL_STALE",
                message="FlowSpec Proposal 的目标草稿版本已过期",
                status_code=409,
            )


def _snapshot_uuid(visual: FlowSpecVisualProposal, key: str) -> UUID | None:
    value = visual.view.change_set.source_snapshot.get(key)
    try:
        return UUID(str(value)) if value is not None else None
    except ValueError:
        return None


def _environment_target_fingerprint(
    environment: Environment,
    endpoints: list[ServiceEndpoint],
) -> str:
    payload = {
        "environment": {
            "id": str(environment.id),
            "base_url": environment.base_url,
            "classification": environment.classification,
            "default_service_id": (
                str(environment.default_service_id)
                if environment.default_service_id is not None
                else None
            ),
            "variables": environment.variables,
            "headers": environment.headers,
        },
        "service_endpoints": [
            {
                "id": str(endpoint.id),
                "service_id": str(endpoint.service_id),
                "variant": endpoint.variant,
                "base_url": endpoint.base_url,
                "enabled": endpoint.enabled,
                "connect_timeout_ms": endpoint.connect_timeout_ms,
                "read_timeout_ms": endpoint.read_timeout_ms,
                "tls_verify": endpoint.tls_verify,
                "proxy_ref": endpoint.proxy_ref,
                "headers": endpoint.headers,
                "variables": endpoint.variables,
                "secret_refs": sorted(endpoint.secret_refs),
                "health_check_path": endpoint.health_check_path,
                "health_expected_status": endpoint.health_expected_status,
                "revision": endpoint.revision,
            }
            for endpoint in endpoints
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _runtime_input_fingerprint(
    runtime_variables: dict[str, str],
    runtime_headers: dict[str, str],
) -> str:
    canonical = json.dumps(
        {
            "runtime_variables": runtime_variables,
            "runtime_headers": runtime_headers,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hmac.new(
        settings.secret_key.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def _snapshot_string(visual: FlowSpecVisualProposal, key: str) -> str | None:
    value = visual.view.change_set.source_snapshot.get(key)
    return value if isinstance(value, str) and value else None


def _service_account_can_preview(
    account: ServiceAccount | None,
    organization_id: UUID,
) -> bool:
    if account is None or account.organization_id != organization_id:
        return False
    if not account.enabled or account.revoked_at is not None:
        return False
    if account.expires_at is not None and _as_utc(account.expires_at) <= datetime.now(UTC):
        return False
    return MCP_PREVIEW_EXECUTE_SCOPE in account.scopes


def _current_executor(actor: User) -> tuple[str, UUID]:
    tenant = get_tenant_context()
    if tenant is None or tenant.service_account_id is None:
        return "user", actor.id
    if MCP_PREVIEW_EXECUTE_SCOPE not in tenant.scopes:
        raise AppError(
            code="MCP_SCOPE_REQUIRED",
            message="服务账号缺少 Sandbox Preview 执行权限",
            status_code=403,
        )
    return "service_account", tenant.service_account_id


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
