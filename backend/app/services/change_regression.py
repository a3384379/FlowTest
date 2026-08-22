"""Application service for the S45 change-aware regression trace."""

# Product copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.change_regression import (
    ChangeRegressionStatus,
    missing_test_design,
    regression_fingerprint,
    transition_status,
)
from app.domain.tasking import TestPlanTrigger
from app.domain.test_design import TestDesignDocument, fingerprint_design, sensitive_paths
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.change_regression import ChangeRegressionRun, ChangeRegressionStage
from app.models.contracts import DeploymentCompatibilityCheck
from app.models.quality_intelligence import ReleaseRisk
from app.models.release_gate import ReleasePolicy
from app.models.tasking import TestPlan, TestPlanItem, TestPlanRun, TestPlanRunItem
from app.models.test_design import ChangeSetApproval, TestDesign
from app.repositories.ai_change_sets import AIChangeSetRepository
from app.repositories.change_regression import (
    ChangeRegressionBundle,
    ChangeRegressionRepository,
)
from app.repositories.impact import ImpactRunBundle
from app.schemas.change_regression import ChangeRegressionReview, ChangeRegressionRunCreate
from app.schemas.impact import ImpactRunCreate
from app.schemas.release_gate import ReleaseDecisionCreate
from app.services.audit import AuditService
from app.services.impact import ImpactService
from app.services.projects import ProjectService
from app.services.release_gate import ReleaseGateService
from app.services.tasking import TestPlanService
from app.tasking.dispatch import TestPlanDispatcher


class ChangeRegressionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ChangeRegressionRepository(session)
        self._change_sets = AIChangeSetRepository(session)
        self._projects = ProjectService(session)
        self._audit = AuditService(session)

    async def create(
        self,
        *,
        actor: User,
        project_id: UUID,
        payload: ChangeRegressionRunCreate,
    ) -> ChangeRegressionBundle:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        plan = await self._project_plan(project_id, payload.test_plan_id)
        await self._project_policy(project_id, payload.release_policy_id)
        await self._optional_release_evidence(
            project_id=project_id,
            release_risk_id=payload.release_risk_id,
            deployment_check_id=payload.deployment_check_id,
        )
        impact = await ImpactService(
            self._session, enabled=settings.feature_impact_engine_enabled
        ).create_run(
            actor=actor,
            project_id=project_id,
            payload=ImpactRunCreate(
                title=payload.title,
                source_ref=payload.source_ref,
                git_diff=payload.git_diff,
                openapi_diffs=payload.openapi_diffs,
                schema_diffs=payload.schema_diffs,
            ),
        )
        selected_assets = _selected_assets(impact)
        plan_items = list(
            (
                await self._session.scalars(
                    select(TestPlanItem).where(TestPlanItem.test_plan_id == plan.id)
                )
            ).all()
        )
        execution_assets = _execution_assets(selected_assets, plan_items)
        gaps = cast(list[dict[str, JsonValue]], impact.coverage.gaps)
        missing_tests: list[dict[str, JsonValue]] = (
            [
                {
                    "position": index,
                    "change_key": str(gap.get("change_key", index)),
                    "source_key": str(gap.get("source_key", "")),
                    "title": (
                        f"补齐覆盖：{str(gap.get('label') or gap.get('source_key') or index)[:160]}"
                    ),
                    "confidence": 0.65,
                    "content": missing_test_design(
                        gap=gap, source_ref=payload.source_ref, position=index
                    ),
                }
                for index, gap in enumerate(gaps, start=1)
            ]
            if payload.generate_missing_tests
            else []
        )
        selection_summary: dict[str, JsonValue] = {
            "strategy": "impact_selection_intersection_v1",
            "impact_selected_asset_count": len(selected_assets),
            "executable_asset_count": len(execution_assets),
            "plan_item_count": len(plan_items),
            "selected_asset_types": cast(
                JsonValue, sorted({str(item.get("target_type")) for item in selected_assets})
            ),
            "execution_assets": cast(JsonValue, execution_assets),
            "coverage_gap_count": len(gaps),
            "missing_test_generation": payload.generate_missing_tests,
        }
        fingerprint = regression_fingerprint(
            source_fingerprint=impact.run.source_fingerprint,
            candidate_ref=payload.candidate_ref.strip(),
            test_plan_id=str(plan.id),
            selected_assets=selected_assets,
            missing_tests=missing_tests,
        )
        run = ChangeRegressionRun(
            project_id=project_id,
            title=payload.title.strip(),
            source_ref=payload.source_ref.strip(),
            source_fingerprint=fingerprint,
            candidate_ref=payload.candidate_ref.strip(),
            status="review_required",
            impact_run_id=impact.run.id,
            test_plan_id=plan.id,
            test_plan_run_id=None,
            release_policy_id=payload.release_policy_id,
            release_risk_id=payload.release_risk_id,
            deployment_check_id=payload.deployment_check_id,
            change_set_id=None,
            release_decision_id=None,
            selected_assets=selected_assets,
            selection_summary=selection_summary,
            missing_tests=missing_tests,
            evidence={},
            failure_triage={},
            approved_by_id=None,
            approved_at=None,
            created_by_id=actor.id,
        )
        self._repository.add_run(run)
        await self._session.flush()
        if missing_tests:
            change_set = AIChangeSet(
                project_id=project_id,
                impact_run_id=impact.run.id,
                release_risk_id=payload.release_risk_id,
                ai_job_id=None,
                title=f"{payload.title.strip()} · 缺失测试草案"[:200],
                status="draft",
                source_snapshot={
                    "schema_version": "s45-change-regression-v1",
                    "regression_run_id": str(run.id),
                    "impact_run_id": str(impact.run.id),
                    "source_ref": payload.source_ref.strip(),
                    "source_fingerprint": impact.run.source_fingerprint,
                    "gaps": cast(JsonValue, gaps),
                    "generation_policy": {
                        "confidence": 0.65,
                        "review_required": True,
                        "automatic_execute": False,
                    },
                },
                source_fingerprint=hashlib.sha256(f"{run.id}:{fingerprint}".encode()).hexdigest(),
                source_type="change_regression",
                source_ref=f"change-regression://{run.id}",
                actor_type="user",
                actor_id=actor.id,
                created_by_id=actor.id,
            )
            self._change_sets.add_change_set(change_set)
            await self._session.flush()
            run.change_set_id = change_set.id
            self._change_sets.add_items(
                [
                    AIChangeItem(
                        change_set_id=change_set.id,
                        suggestion_id=None,
                        position=cast(int, item["position"]),
                        item_type="test_design",
                        action="create",
                        title=str(item["title"]),
                        target_resource_id=None,
                        target_snapshot_sha256=None,
                        proposed_content=cast(dict[str, Any], item["content"]),
                        review_status="pending",
                    )
                    for item in missing_tests
                ]
            )
        await self._stage(
            run,
            actor=actor,
            stage="change",
            status="completed",
            details={
                "source_ref": payload.source_ref.strip(),
                "candidate_ref": payload.candidate_ref.strip(),
                "fingerprint": impact.run.source_fingerprint,
            },
        )
        await self._stage(
            run,
            actor=actor,
            stage="impact",
            status="completed",
            details={
                "impact_run_id": str(impact.run.id),
                "change_count": impact.run.change_count,
                "coverage_percent": impact.coverage.coverage_percent,
                "gap_count": len(impact.coverage.gaps),
            },
        )
        await self._stage(
            run,
            actor=actor,
            stage="regression_selection",
            status="completed",
            details=selection_summary,
        )
        await self._stage(
            run,
            actor=actor,
            stage="missing_test",
            status="completed" if missing_tests else "skipped",
            details={
                "generated_count": len(missing_tests),
                "change_set_id": str(run.change_set_id) if run.change_set_id else None,
                "confidence": 0.65 if missing_tests else None,
            },
        )
        await self._stage(
            run,
            actor=actor,
            stage="review",
            status="pending",
            details={
                "required": True,
                "pending_item_count": len(missing_tests),
                "automatic_execute": False,
            },
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="change_regression.created",
            resource_type="change_regression_run",
            resource_id=run.id,
            details={
                "impact_run_id": str(run.impact_run_id),
                "change_set_id": str(run.change_set_id) if run.change_set_id else None,
                "test_plan_id": str(run.test_plan_id),
                "source_fingerprint": run.source_fingerprint,
                "missing_test_count": len(missing_tests),
            },
        )
        await self._session.commit()
        bundle = await self._repository.get_bundle(run.id)
        if bundle is None:
            raise AppError(
                code="CHANGE_REGRESSION_PERSISTENCE_FAILED",
                message="变更回归链路保存失败",
                status_code=500,
            )
        return bundle

    async def list(
        self, *, actor: User, project_id: UUID, page: int, page_size: int
    ) -> tuple[list[ChangeRegressionRun], int]:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        return await self._repository.list_runs(
            project_id=project_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def get(self, *, actor: User, project_id: UUID, run_id: UUID) -> ChangeRegressionBundle:
        bundle = await self._get_authorized_bundle(
            actor=actor, project_id=project_id, run_id=run_id
        )
        await self._sync_execution(bundle.run)
        refreshed = await self._repository.get_bundle(run_id)
        if refreshed is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        return refreshed

    async def review_item(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        item_id: UUID,
        decision: str,
        payload: ChangeRegressionReview,
    ) -> ChangeRegressionBundle:
        if decision not in {"accept", "reject"}:
            raise AppError(
                code="CHANGE_REGRESSION_REVIEW_INVALID", message="审核决定无效", status_code=422
            )
        bundle = await self._get_authorized_bundle(
            actor=actor, project_id=project_id, run_id=run_id
        )
        run = await self._repository.get_run_for_update(run_id)
        if run is None or run.status != "review_required" or run.change_set_id is None:
            raise AppError(
                code="CHANGE_REGRESSION_REVIEW_UNAVAILABLE",
                message="当前变更回归不处于缺失测试审核阶段",
                status_code=409,
            )
        item = await self._change_sets.get_item_for_update(item_id)
        if item is None or item.change_set_id != run.change_set_id:
            raise AppError(
                code="CHANGE_REGRESSION_ITEM_NOT_FOUND",
                message="缺失测试审核项不存在",
                status_code=404,
            )
        if item.review_status != "pending":
            raise AppError(
                code="CHANGE_REGRESSION_ITEM_ALREADY_REVIEWED",
                message="缺失测试审核项已经处理",
                status_code=409,
            )
        document = self._review_document(item=item, decision=decision, payload=payload)
        materialized_id: UUID | None = None
        if decision == "accept":
            materialized_id = await self._materialize_design(
                project_id=project_id,
                change_set_id=run.change_set_id,
                item=item,
                document=document,
                actor=actor,
            )
            item.materialized_resource_type = "test_design"
            item.materialized_resource_id = materialized_id
        item.proposed_content = document.model_dump(mode="json")
        item.review_status = "accepted" if decision == "accept" else "rejected"
        item.review_note = payload.note.strip()
        item.reviewed_by_id = actor.id
        item.reviewed_at = datetime.now(UTC)
        items = await self._change_sets.list_items(run.change_set_id)
        change_set = await self._change_sets.get_change_set_for_update(run.change_set_id)
        if change_set is not None:
            change_set.status = _review_status(items)
        await self._stage(
            run,
            actor=actor,
            stage="review",
            status="completed",
            details={
                "item_id": str(item.id),
                "decision": item.review_status,
                "materialized_resource_id": (
                    str(item.materialized_resource_id) if item.materialized_resource_id else None
                ),
            },
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action=f"change_regression.test_design_{item.review_status}",
            resource_type="change_regression_item",
            resource_id=item.id,
            details={"regression_run_id": str(run.id), "change_set_id": str(run.change_set_id)},
        )
        await self._session.commit()
        result = await self._repository.get_bundle(run.id)
        if result is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        del bundle
        return result

    def _review_document(
        self,
        *,
        item: AIChangeItem,
        decision: str,
        payload: ChangeRegressionReview,
    ) -> TestDesignDocument:
        if decision == "reject" and payload.content is not None:
            raise AppError(
                code="CHANGE_REGRESSION_REJECT_EDIT_FORBIDDEN",
                message="拒绝缺失测试时不能修改内容",
                status_code=422,
            )
        content = payload.content or cast(dict[str, JsonValue], item.proposed_content)
        _ensure_safe_content(content)
        try:
            return TestDesignDocument.model_validate(content)
        except (TypeError, ValueError) as error:
            raise AppError(
                code="CHANGE_REGRESSION_CONTENT_INVALID",
                message="缺失测试草案不符合 Test Design 契约",
                status_code=422,
            ) from error

    async def _materialize_design(
        self,
        *,
        project_id: UUID,
        change_set_id: UUID,
        item: AIChangeItem,
        document: TestDesignDocument,
        actor: User,
    ) -> UUID:
        duplicate = await self._session.scalar(
            select(TestDesign.id).where(
                TestDesign.project_id == project_id,
                TestDesign.name == item.title,
            )
        )
        if duplicate is not None:
            raise AppError(
                code="CHANGE_REGRESSION_TEST_DESIGN_EXISTS",
                message="同名 Test Design 已存在",
                status_code=409,
            )
        design_model = TestDesign(
            project_id=project_id,
            name=item.title,
            status="approved",
            intent=document.intent.model_dump(mode="json"),
            knowledge_graph=document.knowledge_graph.model_dump(mode="json"),
            state_model=document.state_model.model_dump(mode="json"),
            oracles=document.model_dump(mode="json")["oracles"],
            coverage=document.coverage.model_dump(mode="json"),
            test_case_refs=list(document.test_case_refs),
            fingerprint=fingerprint_design(document),
            source_change_set_id=change_set_id,
            created_by_id=actor.id,
            reviewed_by_id=actor.id,
            reviewed_at=datetime.now(UTC),
        )
        self._session.add(design_model)
        await self._session.flush()
        return design_model.id

    async def approve(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        note: str,
    ) -> ChangeRegressionBundle:
        bundle = await self._get_authorized_bundle(
            actor=actor, project_id=project_id, run_id=run_id
        )
        run = await self._repository.get_run_for_update(run_id)
        if run is None or run.status != "review_required":
            raise AppError(
                code="CHANGE_REGRESSION_APPROVAL_UNAVAILABLE",
                message="当前变更回归不处于审核阶段",
                status_code=409,
            )
        items = await self._change_sets.list_items(run.change_set_id) if run.change_set_id else []
        pending = [item for item in items if item.review_status == "pending"]
        if pending:
            raise AppError(
                code="CHANGE_REGRESSION_REVIEW_PENDING",
                message="仍有缺失测试草案未完成审核",
                status_code=409,
                details={"pending_count": len(pending)},
            )
        if run.change_set_id is not None:
            approval = await self._session.scalar(
                select(ChangeSetApproval).where(
                    ChangeSetApproval.change_set_id == run.change_set_id
                )
            )
            if approval is None:
                self._session.add(
                    ChangeSetApproval(
                        change_set_id=run.change_set_id,
                        decision="approved",
                        note=note.strip(),
                        approved_by_id=actor.id,
                        approved_at=datetime.now(UTC),
                    )
                )
        _transition(run, "approved")
        run.approved_by_id = actor.id
        run.approved_at = datetime.now(UTC)
        await self._stage(
            run,
            actor=actor,
            stage="review",
            status="approved",
            details={"note": note.strip(), "pending_item_count": 0},
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="change_regression.approved",
            resource_type="change_regression_run",
            resource_id=run.id,
            details={"change_set_id": str(run.change_set_id) if run.change_set_id else None},
        )
        await self._session.commit()
        result = await self._repository.get_bundle(run.id)
        if result is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        del bundle
        return result

    async def execute(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        dispatcher: TestPlanDispatcher,
    ) -> ChangeRegressionBundle:
        bundle = await self._get_authorized_bundle(
            actor=actor, project_id=project_id, run_id=run_id
        )
        if bundle.test_plan_run is not None and bundle.test_plan_run.status in {
            "queued",
            "running",
        }:
            return bundle
        run = await self._repository.get_run_for_update(run_id)
        if run is None or run.status != "approved":
            raise AppError(
                code="CHANGE_REGRESSION_EXECUTION_UNAVAILABLE",
                message="变更回归必须先完成人工审核",
                status_code=409,
            )
        plan = await self._project_plan(project_id, run.test_plan_id)
        queued = await TestPlanService(self._session).queue_external_run(
            plan=plan,
            requested_by_id=actor.id,
            trigger=TestPlanTrigger.CI,
        )
        run = await self._repository.get_run_for_update(run.id)
        if run is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        run.test_plan_run_id = queued.id
        _transition(run, "queued")
        await self._stage(
            run,
            actor=actor,
            stage="execution",
            status="queued",
            details={
                "test_plan_id": str(plan.id),
                "test_plan_run_id": str(queued.id),
                "trigger": TestPlanTrigger.CI.value,
            },
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="change_regression.execution_queued",
            resource_type="change_regression_run",
            resource_id=run.id,
            details={"test_plan_run_id": str(queued.id)},
        )
        await self._session.commit()
        try:
            dispatcher.start_test_plan(
                queued.id, queue_name=queued.queue_name, priority=queued.queue_priority
            )
        except Exception as error:
            failed = await self._repository.get_run_for_update(run.id)
            if failed is not None:
                _transition(failed, "failed")
                await self._stage(
                    failed,
                    actor=actor,
                    stage="execution",
                    status="failed",
                    details={"reason": "队列派发失败"},
                )
                await self._session.commit()
            raise AppError(
                code="CHANGE_REGRESSION_QUEUE_UNAVAILABLE",
                message="变更回归执行任务暂时无法派发",
                status_code=503,
            ) from error
        result = await self._repository.get_bundle(run.id)
        if result is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        del bundle
        return result

    async def evaluate_release(
        self, *, actor: User, project_id: UUID, run_id: UUID
    ) -> ChangeRegressionBundle:
        bundle = await self._get_authorized_bundle(
            actor=actor, project_id=project_id, run_id=run_id
        )
        if bundle.release_decision is not None:
            return bundle
        run = await self._repository.get_run_for_update(run_id)
        if run is None or run.test_plan_run_id is None:
            raise AppError(
                code="CHANGE_REGRESSION_EXECUTION_MISSING",
                message="变更回归尚未产生执行证据",
                status_code=409,
            )
        test_plan_run = await self._session.get(TestPlanRun, run.test_plan_run_id)
        if test_plan_run is None or test_plan_run.status not in {"passed", "failed", "cancelled"}:
            raise AppError(
                code="CHANGE_REGRESSION_EXECUTION_PENDING",
                message="测试计划仍在执行，完成后才能评估发布门禁",
                status_code=409,
            )
        decision = await ReleaseGateService(self._session).create_decision(
            actor=actor,
            project_id=project_id,
            payload=ReleaseDecisionCreate(
                release_policy_id=run.release_policy_id,
                candidate_ref=run.candidate_ref,
                test_plan_run_id=run.test_plan_run_id,
                deployment_check_id=run.deployment_check_id,
                impact_run_id=run.impact_run_id,
                release_risk_id=run.release_risk_id,
            ),
        )
        run = await self._repository.get_run_for_update(run_id)
        if run is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        _transition(run, "evidence_ready")
        run.evidence = cast(dict[str, Any], decision.evidence_snapshot)
        run.release_decision_id = decision.id
        if test_plan_run.status == "failed":
            run.failure_triage = await self._failure_triage(test_plan_run)
            await self._stage(
                run,
                actor=actor,
                stage="failure_triage",
                status="completed",
                details=run.failure_triage,
            )
        await self._stage(
            run,
            actor=actor,
            stage="evidence",
            status="completed",
            details={
                "test_plan_run_id": str(test_plan_run.id),
                "execution_status": test_plan_run.status,
                "release_decision_id": str(decision.id),
            },
        )
        run.status = "passed" if decision.status == "pass" else "blocked"
        await self._stage(
            run,
            actor=actor,
            stage="release_gate",
            status="passed" if decision.status == "pass" else "blocked",
            details={
                "decision_id": str(decision.id),
                "decision_status": decision.status,
                "fingerprint": decision.fingerprint,
            },
        )
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="change_regression.release_evaluated",
            resource_type="change_regression_run",
            resource_id=run.id,
            details={
                "release_decision_id": str(decision.id),
                "status": run.status,
                "test_plan_run_id": str(test_plan_run.id),
            },
        )
        await self._session.commit()
        result = await self._repository.get_bundle(run.id)
        if result is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        del bundle
        return result

    async def _get_authorized_bundle(
        self, *, actor: User, project_id: UUID, run_id: UUID
    ) -> ChangeRegressionBundle:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=False)
        bundle = await self._repository.get_bundle(run_id)
        if bundle is None or bundle.run.project_id != project_id:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        return bundle

    async def _project_plan(self, project_id: UUID, plan_id: UUID) -> TestPlan:
        plan = await self._session.get(TestPlan, plan_id)
        if plan is None or plan.project_id != project_id:
            raise AppError(code="TEST_PLAN_NOT_FOUND", message="测试计划不存在", status_code=404)
        return plan

    async def _project_policy(self, project_id: UUID, policy_id: UUID) -> ReleasePolicy:
        policy = await self._session.get(ReleasePolicy, policy_id)
        if policy is None or policy.project_id != project_id:
            raise AppError(
                code="RELEASE_POLICY_NOT_FOUND", message="发布策略不存在", status_code=404
            )
        if not policy.enabled:
            raise AppError(
                code="RELEASE_POLICY_DISABLED", message="发布策略已停用", status_code=409
            )
        return policy

    async def _optional_release_evidence(
        self,
        *,
        project_id: UUID,
        release_risk_id: UUID | None,
        deployment_check_id: UUID | None,
    ) -> None:
        if release_risk_id is not None:
            risk = await self._session.get(ReleaseRisk, release_risk_id)
            if risk is None or risk.project_id != project_id:
                raise AppError(
                    code="RELEASE_RISK_NOT_FOUND", message="发布风险证据不存在", status_code=404
                )
        if deployment_check_id is not None:
            check = await self._session.get(DeploymentCompatibilityCheck, deployment_check_id)
            if check is None or check.project_id != project_id:
                raise AppError(
                    code="CONTRACT_EVIDENCE_NOT_FOUND",
                    message="契约兼容证据不存在",
                    status_code=404,
                )

    async def _stage(
        self,
        run: ChangeRegressionRun,
        *,
        actor: User,
        stage: str,
        status: str,
        details: dict[str, JsonValue],
    ) -> None:
        self._repository.add_stage(
            ChangeRegressionStage(
                regression_run_id=run.id,
                sequence=await self._repository.next_stage_sequence(run.id),
                stage=stage,
                status=status,
                details=details,
                actor_id=actor.id,
            )
        )
        await self._session.flush()

    async def _sync_execution(self, run: ChangeRegressionRun) -> None:
        if run.test_plan_run_id is None or run.status not in {"queued", "running"}:
            return
        child = await self._session.get(TestPlanRun, run.test_plan_run_id)
        if child is None:
            return
        target: ChangeRegressionStatus | None = None
        if child.status == "running":
            target = "running"
        elif child.status in {"passed", "failed", "cancelled"}:
            target = "evidence_ready"
        if target is None or run.status == target:
            return
        _transition(run, target)
        await self._session.commit()

    async def _failure_triage(self, run: TestPlanRun) -> dict[str, JsonValue]:
        items = list(
            (
                await self._session.scalars(
                    select(TestPlanRunItem).where(TestPlanRunItem.test_plan_run_id == run.id)
                )
            ).all()
        )
        return {
            "algorithm_version": "s45-failure-triage-v1",
            "execution_status": run.status,
            "failed_item_count": sum(item.status == "failed" for item in items),
            "cancelled_item_count": sum(item.status == "cancelled" for item in items),
            "retry_attempt_count": sum(max(item.attempts - 1, 0) for item in items),
            "has_error_messages": any(bool(item.error_message) for item in items),
        }


def _selected_assets(impact: ImpactRunBundle) -> list[dict[str, JsonValue]]:
    return cast(list[dict[str, JsonValue]], impact.selection.selected_assets)


def _execution_assets(
    selected_assets: list[dict[str, JsonValue]], plan_items: list[TestPlanItem]
) -> list[dict[str, JsonValue]]:
    plan_targets = {
        ("test_case" if item.target_type == "case" else item.target_type, str(item.target_id))
        for item in plan_items
        if item.target_type in {"case", "workflow"}
    }
    return [
        asset
        for asset in selected_assets
        if (str(asset.get("target_type")), str(asset.get("target_id"))) in plan_targets
    ]


def _ensure_safe_content(content: dict[str, JsonValue]) -> None:
    paths = sensitive_paths(content)
    if paths:
        raise AppError(
            code="CHANGE_REGRESSION_SENSITIVE_CONTENT",
            message="缺失测试草案不能包含 Secret、凭据或 PII",
            status_code=422,
            details={"paths": list(paths[:20])},
        )


def _review_status(items: list[AIChangeItem]) -> str:
    accepted = sum(item.review_status == "accepted" for item in items)
    rejected = sum(item.review_status == "rejected" for item in items)
    pending = len(items) - accepted - rejected
    if pending:
        return "partially_reviewed" if accepted or rejected else "draft"
    return "accepted" if accepted else "rejected"


def _transition(run: ChangeRegressionRun, target: ChangeRegressionStatus) -> None:
    try:
        transition_status(run.status, target)
    except ValueError as error:
        raise AppError(
            code="CHANGE_REGRESSION_INVALID_TRANSITION",
            message="变更回归状态不允许当前操作",
            status_code=409,
        ) from error
    run.status = target
