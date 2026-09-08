"""S62 MCP adapters for analysis preparation, plan suggestions and Preview cancel."""

# Chinese product copy intentionally uses full-width punctuation.
from __future__ import annotations

import hashlib
import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_tenant_context, get_trace_id
from app.core.errors import AppError
from app.domain.mcp_planning import (
    MCP_REGRESSION_PREPARE_SCOPE,
    MCP_TEST_PLAN_PROPOSE_SCOPE,
)
from app.domain.test_assets import TestTargetType
from app.domain.test_contexts import first_sensitive_value
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.change_regression import ChangeRegressionRun
from app.models.tasking import TestPlan, TestPlanItem
from app.models.test_assets import TestCase, TestCaseVersion, TestSuite, TestSuiteVersion
from app.models.workflows import Workflow, WorkflowExecution, WorkflowVersion
from app.schemas.change_regression import ChangeRegressionRunCreate
from app.schemas.mcp_planning import (
    MCPCancelPreviewRequest,
    MCPCancelPreviewResponse,
    MCPPrepareChangeRegressionRequest,
    MCPPrepareChangeRegressionResponse,
    MCPTestPlanUpdateContent,
    MCPTestPlanUpdateRequest,
    MCPTestPlanUpdateResponse,
    MCPTestPlanUpdateTarget,
)
from app.schemas.regression_maintenance import RegressionContextBinding, maintenance_snapshot
from app.schemas.tasking import TestPlanItemInput
from app.services.audit import AuditService
from app.services.change_regression import ChangeRegressionService
from app.services.context_inspector import ContextInspectorService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.projects import ProjectService
from app.services.regression_maintenance import RegressionMaintenanceService
from app.services.workflows import WorkflowService


class MCPPlanningService:
    """Keep S62 operations on existing ChangeRegression, AIChangeSet and Workflow services."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def prepare_change_regression(
        self,
        *,
        actor: User,
        account_id: UUID,
        payload: MCPPrepareChangeRegressionRequest,
        idempotency_key: str | None,
    ) -> MCPPrepareChangeRegressionResponse:
        self._require_scope(
            MCP_REGRESSION_PREPARE_SCOPE,
            "服务账号缺少 Change Regression 分析准备权限",
        )
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        if first_sensitive_value(payload.model_dump(mode="json")) is not None:
            raise AppError(
                code="MCP_SENSITIVE_INPUT",
                message="Change Regression 来源不能包含 Secret、凭据或 PII",
                status_code=422,
            )
        change_payload = ChangeRegressionRunCreate(
            title=payload.title,
            source_ref=payload.source_ref,
            candidate_ref=payload.candidate_ref,
            git_diff=payload.git_diff,
            openapi_diffs=payload.openapi_diffs,
            schema_diffs=payload.schema_diffs,
            test_plan_id=payload.test_plan_id,
            release_policy_id=payload.release_policy_id,
            release_risk_id=payload.release_risk_id,
            deployment_check_id=payload.deployment_check_id,
            generate_missing_tests=payload.generate_missing_tests,
        )
        await self._validate_regression_inputs(actor=actor, payload=payload)
        if payload.dry_run:
            comparison = await ContextInspectorService(self._session).compare_revisions(
                actor=actor,
                project_id=payload.project_id,
                context_id=payload.context_id,
                before_revision=payload.before_revision,
                after_revision=payload.after_revision,
            )
            reference = _context_reference(comparison.context_id, comparison)
            return MCPPrepareChangeRegressionResponse(
                project_id=payload.project_id,
                context_diff_ref=reference,
                knowledge_diff_ref=f"{reference}/knowledge",
                analysis_complete=None,
                dry_run=True,
                next_action="预检通过; 确认范围后以固定幂等键创建分析 Run",
                trace_id=get_trace_id(),
            )

        key = require_idempotency_key(idempotency_key)
        actor_key = f"service-account:{account_id}"
        operation = f"mcp.prepare_change_regression:{payload.project_id}"
        request_payload = payload.model_dump(mode="json")
        cached = await IdempotencyService(self._session).completed_response(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation=operation,
            request_payload=request_payload,
        )
        if cached is not None:
            cached["idempotency_replayed"] = True
            return MCPPrepareChangeRegressionResponse.model_validate(cached)

        async def action() -> MCPPrepareChangeRegressionResponse:
            # Revalidate mutable references after the idempotency claim.  The existing
            # services own all persistence, stage, audit and Context invariants.
            await self._validate_regression_inputs(actor=actor, payload=payload)
            bundle = await ChangeRegressionService(self._session).create(
                actor=actor,
                project_id=payload.project_id,
                payload=change_payload,
                commit=False,
            )
            bound = await RegressionMaintenanceService(self._session).bind(
                actor=actor,
                project_id=payload.project_id,
                run_id=bundle.run.id,
                payload=RegressionContextBinding(
                    context_id=payload.context_id,
                    before_revision=payload.before_revision,
                    after_revision=payload.after_revision,
                ),
                commit=False,
            )
            snapshot = maintenance_snapshot(bound.run.selection_summary)
            if snapshot is None:
                raise AppError(
                    code="CONTEXT_BIND_FAILED",
                    message="Change Regression Context 绑定未生成证据",
                    status_code=500,
                )
            self._audit.record(
                actor_user_id=actor.id,
                project_id=payload.project_id,
                action="mcp.change_regression_prepared",
                resource_type="change_regression_run",
                resource_id=bound.run.id,
                details={
                    "service_account_id": str(account_id),
                    "impact_run_id": str(bound.run.impact_run_id),
                    "context_id": str(payload.context_id),
                    "before_revision": payload.before_revision,
                    "after_revision": payload.after_revision,
                    "automatic_execute": False,
                },
            )
            return MCPPrepareChangeRegressionResponse(
                project_id=payload.project_id,
                run_id=bound.run.id,
                impact_run_id=bound.run.impact_run_id,
                context_diff_ref=snapshot.context_diff_ref,
                knowledge_diff_ref=snapshot.knowledge_diff_ref,
                analysis_complete=snapshot.affected.analysis_complete,
                dry_run=False,
                next_action="请在现有 Change Regression 页面检查分析和待审核建议",
                trace_id=get_trace_id(),
            )

        result = await IdempotencyService(self._session).run(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation=operation,
            request_payload=request_payload,
            action=action,
            atomic_action=True,
        )
        return MCPPrepareChangeRegressionResponse.model_validate(result)

    async def propose_test_plan_update(
        self,
        *,
        actor: User,
        account_id: UUID,
        payload: MCPTestPlanUpdateRequest,
        idempotency_key: str | None,
    ) -> MCPTestPlanUpdateResponse:
        self._require_scope(MCP_TEST_PLAN_PROPOSE_SCOPE, "服务账号缺少 Test Plan 建议权限")
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        plan = await self._project_plan(payload.project_id, payload.test_plan_id)
        if first_sensitive_value(payload.model_dump(mode="json")) is not None:
            raise AppError(
                code="MCP_SENSITIVE_INPUT",
                message="测试计划建议说明不能包含 Secret 或 PII",
                status_code=422,
            )
        targets, unpublished = await self._resolve_plan_targets(payload, plan)
        if payload.dry_run:
            return MCPTestPlanUpdateResponse(
                project_id=payload.project_id,
                test_plan_id=plan.id,
                proposed_item_count=len(targets),
                unpublished_dependencies=unpublished,
                dry_run=True,
                next_action="预检通过; 请在范围确认后创建待审核 Test Plan ChangeSet",
                trace_id=get_trace_id(),
            )

        key = require_idempotency_key(idempotency_key)
        actor_key = f"service-account:{account_id}"
        operation = f"mcp.propose_test_plan_update:{plan.id}"
        request_payload = payload.model_dump(mode="json")
        cached = await IdempotencyService(self._session).completed_response(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation=operation,
            request_payload=request_payload,
        )
        if cached is not None:
            cached["idempotency_replayed"] = True
            return MCPTestPlanUpdateResponse.model_validate(cached)

        async def action() -> MCPTestPlanUpdateResponse:
            current_plan = await self._project_plan(payload.project_id, payload.test_plan_id)
            current_targets, current_unpublished = await self._resolve_plan_targets(
                payload, current_plan
            )
            current_content = MCPTestPlanUpdateContent(
                test_plan_id=current_plan.id,
                targets=current_targets,
                unpublished_dependencies=current_unpublished,
                rationale=payload.rationale.strip(),
            )
            source_snapshot = {
                "schema_version": "s62-test-plan-update-v1",
                "test_plan_id": str(current_plan.id),
                "targets": current_content.model_dump(mode="json")["targets"],
                "unpublished_dependencies": current_unpublished,
                "rationale": current_content.rationale,
                "governance": {
                    "confidence": 0.9,
                    "risk_level": "medium",
                    "requires_review": True,
                    "manual_approval_required": False,
                    "reason_codes": ["plan_membership_requires_review"],
                },
            }
            change_set = AIChangeSet(
                project_id=payload.project_id,
                impact_run_id=await self._impact_id(payload.run_id, payload.project_id),
                release_risk_id=None,
                ai_job_id=None,
                title=payload.title.strip(),
                status="draft",
                source_snapshot=source_snapshot,
                source_fingerprint=_fingerprint(source_snapshot),
                source_type="mcp",
                source_ref=f"mcp://test-plan-updates/{current_plan.id}",
                actor_type="service_account",
                actor_id=actor.id,
                created_by_id=actor.id,
            )
            self._session.add(change_set)
            await self._session.flush()
            self._session.add(
                AIChangeItem(
                    change_set_id=change_set.id,
                    suggestion_id=None,
                    position=0,
                    item_type="test_plan_update",
                    action="update",
                    title=payload.title.strip(),
                    target_resource_id=current_plan.id,
                    target_snapshot_sha256=None,
                    proposed_content=current_content.model_dump(mode="json"),
                    review_status="pending",
                )
            )
            self._audit.record(
                actor_user_id=actor.id,
                project_id=payload.project_id,
                action="mcp.test_plan_update_proposed",
                resource_type="ai_change_set",
                resource_id=change_set.id,
                details={
                    "service_account_id": str(account_id),
                    "test_plan_id": str(current_plan.id),
                    "target_count": len(current_targets),
                    "unpublished_dependency_count": len(current_unpublished),
                    "automatic_publish": False,
                    "automatic_execute": False,
                },
            )
            await self._session.flush()
            return MCPTestPlanUpdateResponse(
                project_id=payload.project_id,
                test_plan_id=current_plan.id,
                change_set_id=change_set.id,
                proposed_item_count=len(current_targets),
                unpublished_dependencies=current_unpublished,
                dry_run=False,
                next_action="请在现有 ChangeSet Review 中审核, 接受后才可加入草稿计划",
                trace_id=get_trace_id(),
            )

        result = await IdempotencyService(self._session).run(
            key=key,
            project_id=payload.project_id,
            actor_key=actor_key,
            operation=operation,
            request_payload=request_payload,
            action=action,
            atomic_action=True,
        )
        return MCPTestPlanUpdateResponse.model_validate(result)

    async def cancel_preview(
        self,
        *,
        actor: User,
        payload: MCPCancelPreviewRequest,
    ) -> MCPCancelPreviewResponse:
        self._require_scope("mcp:preview:execute", "服务账号缺少 Sandbox Preview 执行权限")
        await self._projects.authorize(actor=actor, project_id=payload.project_id, editing=True)
        execution = (
            await self._session.execute(
                select(WorkflowExecution)
                .where(
                    WorkflowExecution.id == payload.execution_id,
                    WorkflowExecution.project_id == payload.project_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if execution is None:
            raise AppError(
                code="WORKFLOW_EXECUTION_NOT_FOUND",
                message="Preview 执行不存在",
                status_code=404,
            )
        if execution.run_purpose != "preview":
            raise AppError(
                code="PREVIEW_CANCEL_ONLY",
                message="只能取消 Preview 执行, 不能取消正式工作流运行",
                status_code=409,
            )
        already_requested = execution.cancel_requested_at is not None
        if execution.status in {"queued", "running"}:
            execution = await WorkflowService(self._session).request_cancel(
                actor=actor,
                project_id=payload.project_id,
                execution_id=payload.execution_id,
                force=False,
            )
        # A concurrently completed Preview is an idempotent no-op.  The existing
        # WorkflowService remains the only component allowed to request cancellation.
        # ``cleanup_status`` is nullable when the workflow has no cleanup phase.  A
        # terminal execution with a null cleanup status is therefore complete, while a
        # queued/running Preview remains pending until the runner records its outcome.
        cleanup_pending = execution.status in {"queued", "running"} or (
            execution.cleanup_status is not None
            and execution.cleanup_status not in {"passed", "failed", "cancelled"}
        )
        response = MCPCancelPreviewResponse(
            project_id=payload.project_id,
            execution_id=execution.id,
            status=cast(Any, execution.status),
            cancellation_requested=execution.cancel_requested_at is not None,
            cleanup_pending=cleanup_pending,
            idempotent=already_requested or execution.status in {"passed", "failed", "cancelled"},
            next_action=(
                "等待 Preview 完成 Graceful Cancel 并读取 Cleanup 结果"
                if cleanup_pending
                else "读取 Preview Main/Cleanup 结果"
            ),
            trace_id=get_trace_id(),
        )
        context = get_tenant_context()
        self._audit.record(
            actor_user_id=actor.id,
            organization_id=context.organization_id if context else None,
            project_id=payload.project_id,
            action="mcp.preview_cancel_requested",
            resource_type="workflow_execution",
            resource_id=execution.id,
            details={
                "already_requested": already_requested,
                "status": execution.status,
                "cleanup_pending": cleanup_pending,
            },
        )
        await self._session.commit()
        return response

    async def _validate_regression_inputs(
        self, *, actor: User, payload: MCPPrepareChangeRegressionRequest
    ) -> None:
        service = ChangeRegressionService(self._session)
        await service._project_plan(payload.project_id, payload.test_plan_id)
        await service._project_policy(payload.project_id, payload.release_policy_id)
        await service._optional_release_evidence(
            project_id=payload.project_id,
            release_risk_id=payload.release_risk_id,
            deployment_check_id=payload.deployment_check_id,
        )
        await ContextInspectorService(self._session).compare_revisions(
            actor=actor,
            project_id=payload.project_id,
            context_id=payload.context_id,
            before_revision=payload.before_revision,
            after_revision=payload.after_revision,
        )

    async def _project_plan(self, project_id: UUID, plan_id: UUID) -> TestPlan:
        plan = await self._session.get(TestPlan, plan_id)
        if plan is None or plan.project_id != project_id:
            raise AppError(code="TEST_PLAN_NOT_FOUND", message="测试计划不存在", status_code=404)
        return plan

    async def _resolve_plan_targets(
        self, payload: MCPTestPlanUpdateRequest, plan: TestPlan
    ) -> tuple[list[MCPTestPlanUpdateTarget], list[str]]:
        existing_items = list(
            (
                await self._session.scalars(
                    select(TestPlanItem).where(TestPlanItem.test_plan_id == plan.id)
                )
            ).all()
        )
        environment_by_workflow = {
            item.target_id: item.environment_id
            for item in existing_items
            if item.target_type == TestTargetType.WORKFLOW.value and item.environment_id is not None
        }
        targets: list[MCPTestPlanUpdateTarget] = []
        unpublished: list[str] = []
        for target_id in payload.workflow_ids:
            target, dependencies = await self._resolve_workflow_target(
                payload.project_id, target_id, environment_by_workflow
            )
            targets.append(target)
            unpublished.extend(dependencies)
        for target_id in payload.test_case_ids:
            target, dependencies = await self._resolve_case_target(payload.project_id, target_id)
            targets.append(target)
            unpublished.extend(dependencies)
        for target_id in payload.test_suite_ids:
            target, dependencies = await self._resolve_suite_target(payload.project_id, target_id)
            targets.append(target)
            unpublished.extend(dependencies)
        return targets, sorted(set(unpublished))

    async def _resolve_workflow_target(
        self,
        project_id: UUID,
        target_id: UUID,
        environment_by_workflow: dict[UUID, UUID],
    ) -> tuple[MCPTestPlanUpdateTarget, list[str]]:
        workflow = await self._session.get(Workflow, target_id)
        if workflow is None or workflow.project_id != project_id:
            raise AppError(code="WORKFLOW_NOT_FOUND", message="Workflow 不存在", status_code=404)
        version = workflow.current_version
        dependencies = (
            []
            if version is not None
            and await self._session.scalar(
                select(WorkflowVersion.id).where(
                    WorkflowVersion.workflow_id == workflow.id,
                    WorkflowVersion.version == version,
                )
            )
            else [f"workflow:{workflow.id}:published_version"]
        )
        environment_id = environment_by_workflow.get(workflow.id)
        if environment_id is None:
            dependencies.append(f"workflow:{workflow.id}:environment")
        return (
            MCPTestPlanUpdateTarget(
                target_type="workflow",
                target_id=workflow.id,
                target_version=version,
                workflow_version=version,
                environment_id=environment_id,
            ),
            dependencies,
        )

    async def _resolve_case_target(
        self, project_id: UUID, target_id: UUID
    ) -> tuple[MCPTestPlanUpdateTarget, list[str]]:
        case = await self._session.get(TestCase, target_id)
        if case is None or case.project_id != project_id:
            raise AppError(code="TEST_CASE_NOT_FOUND", message="测试用例不存在", status_code=404)
        version = case.current_version
        published = (
            version is not None
            and await self._session.scalar(
                select(TestCaseVersion.id).where(
                    TestCaseVersion.test_case_id == case.id,
                    TestCaseVersion.version == version,
                )
            )
            is not None
        )
        return (
            MCPTestPlanUpdateTarget(target_type="case", target_id=case.id, target_version=version),
            [] if published else [f"case:{case.id}:published_version"],
        )

    async def _resolve_suite_target(
        self, project_id: UUID, target_id: UUID
    ) -> tuple[MCPTestPlanUpdateTarget, list[str]]:
        suite = await self._session.get(TestSuite, target_id)
        if suite is None or suite.project_id != project_id:
            raise AppError(code="TEST_SUITE_NOT_FOUND", message="测试套件不存在", status_code=404)
        version = suite.current_version
        published = (
            version is not None
            and await self._session.scalar(
                select(TestSuiteVersion.id).where(
                    TestSuiteVersion.test_suite_id == suite.id,
                    TestSuiteVersion.version == version,
                )
            )
            is not None
        )
        return (
            MCPTestPlanUpdateTarget(
                target_type="suite", target_id=suite.id, target_version=version
            ),
            [] if published else [f"suite:{suite.id}:published_version"],
        )

    async def _impact_id(self, run_id: UUID | None, project_id: UUID) -> UUID | None:
        if run_id is None:
            return None
        run = await self._session.get(ChangeRegressionRun, run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND",
                message="变更回归不存在",
                status_code=404,
            )
        return run.impact_run_id

    @staticmethod
    def _require_scope(scope: str, message: str) -> UUID:
        context = get_tenant_context()
        if context is None or context.service_account_id is None or scope not in context.scopes:
            raise AppError(code="MCP_SCOPE_REQUIRED", message=message, status_code=403)
        return context.service_account_id


async def materialize_test_plan_update(
    *, session: AsyncSession, actor: User, change_set: AIChangeSet, content: object
) -> tuple[str, UUID]:
    """Apply a reviewed plan suggestion through the existing TestPlanService only."""

    from app.services.tasking import TestPlanService

    try:
        proposal = MCPTestPlanUpdateContent.model_validate(content)
    except (TypeError, ValueError) as error:
        raise AppError(
            code="MCP_TEST_PLAN_CONTENT_INVALID",
            message="测试计划建议内容无效",
            status_code=422,
        ) from error
    plan = await session.get(TestPlan, proposal.test_plan_id)
    if plan is None or plan.project_id != change_set.project_id:
        raise AppError(code="TEST_PLAN_NOT_FOUND", message="测试计划不存在", status_code=404)
    if proposal.unpublished_dependencies:
        raise AppError(
            code="MCP_TEST_PLAN_DEPENDENCY_UNPUBLISHED",
            message="测试计划建议包含尚未发布的依赖",
            status_code=409,
        )
    existing = list(
        (
            await session.scalars(select(TestPlanItem).where(TestPlanItem.test_plan_id == plan.id))
        ).all()
    )
    service = TestPlanService(session)
    for target in proposal.targets:
        if any(
            item.target_type == target.target_type and item.target_id == target.target_id
            for item in existing
        ):
            continue
        if target.target_version is None:
            raise AppError(
                code="MCP_TEST_PLAN_DEPENDENCY_UNPUBLISHED",
                message="测试资产尚未发布固定版本",
                status_code=409,
            )
        item = TestPlanItemInput(
            target_type=TestTargetType(target.target_type),
            target_id=target.target_id,
            target_version=target.target_version,
            workflow_id=target.target_id if target.target_type == "workflow" else None,
            workflow_version=target.workflow_version,
            environment_id=target.environment_id,
            max_retries=target.max_retries,
            runtime_variables=target.runtime_variables,
            runtime_headers=target.runtime_headers,
        )
        await service.add_item(
            actor=actor,
            project_id=change_set.project_id,
            plan_id=plan.id,
            item=item,
            commit=False,
        )
        existing.append(
            TestPlanItem(
                target_type=target.target_type,
                target_id=target.target_id,
                test_plan_id=plan.id,
                target_version=target.target_version,
                position=len(existing),
            )
        )
    return "test_plan", plan.id


def _context_reference(context_id: UUID, comparison: Any) -> str:
    return f"context-diff://{context_id}/{comparison.before_revision_id}/{comparison.after_revision_id}"


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
