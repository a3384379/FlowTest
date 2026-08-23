"""Application service for the S45 change-aware regression trace."""

# Product copy intentionally uses Chinese punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import re
from builtins import list as list_type
from datetime import UTC, datetime
from http.cookies import CookieError, SimpleCookie
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.domain.canonical_contracts import (
    contains_sensitive_contract_value,
    semantic_schema_fingerprint,
)
from app.domain.change_regression import (
    ChangeConstraintTarget,
    ChangeRegressionStatus,
    OperationIdentity,
    SemanticCoverageFact,
    change_constraint_target,
    missing_test_design,
    oracle_set_fingerprint,
    regression_fingerprint,
    scenario_oracle_identities,
    semantic_coverage_tokens,
    transition_status,
)
from app.domain.failure_triage import FailureSignal, triage_failures
from app.domain.tasking import TestPlanTrigger
from app.domain.test_design import TestDesignDocument, fingerprint_design, sensitive_paths
from app.domain.test_engineering import ContractParameter, OperationContract, fingerprint_contract
from app.engine.results import NodeResult
from app.models.access import User
from app.models.ai import AIChangeItem, AIChangeSet
from app.models.api_assets import APIDefinition, APIVersion
from app.models.change_regression import (
    ChangeRegressionRun,
    ChangeRegressionStage,
    SemanticGapWaiver,
)
from app.models.contracts import DeploymentCompatibilityCheck
from app.models.quality_intelligence import ReleaseRisk
from app.models.release_gate import ReleasePolicy
from app.models.service_targets import Service
from app.models.tasking import TestPlan, TestPlanItem, TestPlanRun, TestPlanRunItem
from app.models.test_assets import TestCase, TestCaseVersion
from app.models.test_design import ChangeSetApproval, TestDesign
from app.models.workflows import Workflow, WorkflowNodeExecution, WorkflowVersion
from app.repositories.ai_change_sets import AIChangeSetRepository
from app.repositories.change_regression import (
    ChangeRegressionBundle,
    ChangeRegressionRepository,
)
from app.repositories.impact import ImpactRunBundle
from app.schemas.change_regression import (
    ChangeRegressionAddToPlanInput,
    ChangeRegressionOperationSelection,
    ChangeRegressionReview,
    ChangeRegressionRunCreate,
    SemanticGapWaiverCreate,
)
from app.schemas.impact import ImpactRunCreate
from app.schemas.release_gate import ReleaseDecisionCreate
from app.services.audit import AuditService
from app.services.impact import ImpactService
from app.services.projects import ProjectService
from app.services.release_gate import ReleaseGateService
from app.services.tasking import TestPlanService
from app.services.test_engineering import TestEngineeringService
from app.services.test_engineering_proposals import TestEngineeringProposalService
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
        asset_gaps = cast(list[dict[str, JsonValue]], impact.coverage.gaps)
        gaps = _missing_test_targets(impact, asset_gaps)
        semantic_coverage = await self._existing_semantic_coverage(project_id)
        current_plan_scope = await self._current_plan_scope(
            selected_assets=selected_assets,
            plan_items=plan_items,
            project_id=project_id,
        )
        missing_tests: list[dict[str, JsonValue]] = []
        semantic_scope_results: list[dict[str, JsonValue]] = []
        plan_recommendations: list[dict[str, JsonValue]] = []
        if payload.generate_missing_tests:
            for index, gap in enumerate(gaps, start=1):
                resolved = await self._current_contract_for_gap(
                    project_id, gap, selected_assets=selected_assets
                )
                contract, identity = resolved if resolved is not None else (None, None)
                target = change_constraint_target(gap)
                project_values = (
                    semantic_coverage_tokens(semantic_coverage, identity, target)
                    if identity is not None and target is not None
                    else set()
                )
                current_plan_values = (
                    semantic_coverage_tokens(
                        semantic_coverage,
                        identity,
                        target,
                        asset_scope=current_plan_scope,
                    )
                    if identity is not None and target is not None
                    else set()
                )
                content = missing_test_design(
                    gap=gap,
                    source_ref=payload.source_ref,
                    position=index,
                    current_contract=contract,
                    covered_values=project_values,
                )
                plan_content = missing_test_design(
                    gap=gap,
                    source_ref=payload.source_ref,
                    position=index,
                    current_contract=contract,
                    covered_values=current_plan_values,
                )
                semantic_scope_results.append(
                    _semantic_scope_result(
                        gap=gap,
                        identity=identity,
                        target=target,
                        project_content=content,
                        current_plan_content=plan_content,
                        project_values=project_values,
                        current_plan_values=current_plan_values,
                    )
                )
                if not content.get("scenarios"):
                    review_requirements = content.get("review_requirements")
                    if (
                        isinstance(review_requirements, list)
                        and "change_target_unresolved" in review_requirements
                    ):
                        missing_tests.append(
                            {
                                "position": index,
                                "change_key": str(gap.get("change_key", index)),
                                "source_key": str(gap.get("source_key", "")),
                                "title": f"待定位变更：{_change_label(gap, index)}",
                                "confidence": 0.5,
                                "content": content,
                            }
                        )
                        continue
                    if plan_content.get("scenarios"):
                        plan_recommendations.append(
                            {
                                "change_key": str(gap.get("change_key") or index),
                                "action": "add_project_known_test_to_current_plan",
                                "operation": identity.model_dump(mode="json") if identity else None,
                                "target": target.model_dump(mode="json") if target else None,
                            }
                        )
                    continue
                missing_tests.append(
                    {
                        "position": index,
                        "change_key": str(gap.get("change_key", index)),
                        "source_key": str(gap.get("source_key", "")),
                        "title": (
                            "补齐覆盖："
                            f"{str(gap.get('label') or gap.get('source_key') or index)[:160]}"
                        ),
                        "confidence": 0.65 if contract is None else 0.9,
                        "content": content,
                    }
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
            "asset_coverage_gap_count": len(asset_gaps),
            "semantic_change_target_count": len(gaps),
            "coverage_gap_count": len(asset_gaps),
            "missing_test_generation": payload.generate_missing_tests,
            "semantic_coverage_fact_count": len(semantic_coverage),
            # Backward-compatible field: number of proposal groups, not semantic tokens.
            "semantic_gap_count": len(missing_tests),
            "asset_mapping_gap_count": len(asset_gaps),
            "project_semantic_gap_count": _scope_gap_count(
                semantic_scope_results, "project_missing_values"
            ),
            "current_test_plan_semantic_gap_count": _scope_gap_count(
                semantic_scope_results, "current_test_plan_missing_values"
            ),
            "waived_current_plan_gap_count": 0,
            "unresolved_current_plan_gap_count": _scope_gap_count(
                semantic_scope_results, "current_test_plan_missing_values"
            ),
            "semantic_coverage_scopes": cast(JsonValue, semantic_scope_results),
            "semantic_targets": cast(JsonValue, gaps),
            "current_plan_recommendations": cast(JsonValue, plan_recommendations),
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
                    "schema_version": "s47.3-change-regression-v2",
                    "regression_run_id": str(run.id),
                    "impact_run_id": str(impact.run.id),
                    "source_ref": payload.source_ref.strip(),
                    "source_fingerprint": impact.run.source_fingerprint,
                    "gaps": cast(JsonValue, gaps),
                    "frozen_operations": cast(
                        JsonValue,
                        [
                            {
                                "change_key": scope.get("change_key"),
                                "operation": scope.get("operation"),
                                "target": scope.get("target"),
                            }
                            for scope in semantic_scope_results
                        ],
                    ),
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
        await self._recalculate_plan_gaps(run)
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

    async def add_project_known_test_to_current_plan(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        payload: ChangeRegressionAddToPlanInput,
    ) -> ChangeRegressionBundle:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        run = await self._repository.get_run_for_update(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        gap_state = await self._recalculate_plan_gaps(run)
        gap = _find_gap(gap_state, payload.gap_key)
        if gap is None or gap.get("coverage_status") not in {"MISSING", "PARTIAL"}:
            raise AppError(
                code="CHANGE_REGRESSION_PLAN_GAP_NOT_FOUND",
                message="当前计划中不存在可由已有测试补齐的语义缺口",
                status_code=409,
            )
        target_id = payload.item.target_id or payload.item.workflow_id
        target_type = payload.item.target_type.value
        requested = (
            "test_case" if target_type == "case" else target_type,
            str(target_id),
        )
        recommendations = gap.get("recommended_existing_assets")
        allowed = (
            {
                (str(item.get("target_type")), str(item.get("target_id")))
                for item in recommendations
                if isinstance(item, dict)
            }
            if isinstance(recommendations, list)
            else set()
        )
        selected = {
            (str(item.get("target_type")), str(item.get("target_id")))
            for item in run.selected_assets
            if isinstance(item, dict)
        }
        if requested not in allowed or requested not in selected:
            raise AppError(
                code="CHANGE_REGRESSION_PLAN_ASSET_MISMATCH",
                message="所选测试不属于当前影响范围，或不能覆盖指定语义缺口",
                status_code=409,
            )
        await TestPlanService(self._session).add_item(
            actor=actor,
            project_id=project_id,
            plan_id=run.test_plan_id,
            item=payload.item,
        )
        run = await self._repository.get_run_for_update(run_id)
        if run is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        await self._recalculate_plan_gaps(run)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="change_regression.plan_gap_asset_added",
            resource_type="change_regression_run",
            resource_id=run.id,
            details={
                "gap_key": payload.gap_key,
                "target_type": requested[0],
                "target_id": requested[1],
                "automatic_execute": False,
            },
        )
        await self._session.commit()
        return await self._required_bundle(run.id)

    async def select_operation(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        payload: ChangeRegressionOperationSelection,
    ) -> ChangeRegressionBundle:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        run = await self._repository.get_run_for_update(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        if run.status != "review_required":
            raise AppError(
                code="CHANGE_REGRESSION_OPERATION_SELECTION_UNAVAILABLE",
                message="Operation 只能在审核阶段选择",
                status_code=409,
            )
        target_gap = _semantic_target(run.selection_summary, payload.change_key)
        resolved = await self._operation_identity(
            project_id=project_id,
            definition_id=payload.api_definition_id,
            version_number=payload.api_version,
        )
        if target_gap is None or not _resolved_matches_gap(resolved, target_gap):
            raise AppError(
                code="CHANGE_REGRESSION_TARGET_MISMATCH",
                message="所选 API 与变更 Operation Identity 不一致",
                status_code=409,
            )
        identity, _ = cast(tuple[OperationIdentity, OperationContract], resolved)
        summary = cast(dict[str, JsonValue], dict(run.selection_summary))
        scopes = summary.get("semantic_coverage_scopes")
        updated_scopes = (
            [
                {
                    **scope,
                    "operation": identity.model_dump(mode="json"),
                    "requires_review": scope.get("target") is None,
                }
                if isinstance(scope, dict) and scope.get("change_key") == payload.change_key
                else scope
                for scope in scopes
            ]
            if isinstance(scopes, list)
            else []
        )
        summary["semantic_coverage_scopes"] = cast(JsonValue, updated_scopes)
        run.selection_summary = summary
        await self._freeze_selected_operation(run, payload.change_key, identity)
        await self._recalculate_plan_gaps(run)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="change_regression.operation_selected",
            resource_type="change_regression_run",
            resource_id=run.id,
            details={
                "change_key": payload.change_key,
                "api_definition_id": str(payload.api_definition_id),
                "api_version": payload.api_version,
                "contract_fingerprint": identity.contract_fingerprint,
            },
        )
        await self._session.commit()
        return await self._required_bundle(run.id)

    async def _freeze_selected_operation(
        self,
        run: ChangeRegressionRun,
        change_key: str,
        identity: OperationIdentity,
    ) -> None:
        if run.change_set_id is None:
            return
        change_set = await self._change_sets.get_change_set_for_update(run.change_set_id)
        if change_set is None:
            return
        snapshot = dict(change_set.source_snapshot)
        frozen = snapshot.get("frozen_operations")
        entries = (
            [dict(item) for item in frozen if isinstance(item, dict)]
            if isinstance(frozen, list)
            else []
        )
        for entry in entries:
            if entry.get("change_key") == change_key:
                entry["operation"] = identity.model_dump(mode="json")
        snapshot["frozen_operations"] = entries
        change_set.source_snapshot = snapshot

    async def waive_semantic_gap(
        self,
        *,
        actor: User,
        project_id: UUID,
        run_id: UUID,
        payload: SemanticGapWaiverCreate,
    ) -> ChangeRegressionBundle:
        await self._projects.authorize(actor=actor, project_id=project_id, editing=True)
        run = await self._repository.get_run_for_update(run_id)
        if run is None or run.project_id != project_id:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        gap_state = await self._recalculate_plan_gaps(run)
        gap = _find_gap(gap_state, payload.gap_key)
        if gap is None or gap.get("coverage_status") == "COVERED":
            raise AppError(
                code="CHANGE_REGRESSION_PLAN_GAP_NOT_FOUND",
                message="指定的当前计划语义缺口不存在",
                status_code=409,
            )
        if await self._repository.find_waiver(run.id, payload.gap_key) is not None:
            raise AppError(
                code="CHANGE_REGRESSION_PLAN_GAP_ALREADY_WAIVED",
                message="该语义缺口已存在豁免记录",
                status_code=409,
            )
        operation = _json_mapping(gap.get("operation"))
        requirement = _json_mapping(gap.get("semantic_requirement"))
        requirement_fingerprint = str(gap.get("requirement_fingerprint") or "")
        now = datetime.now(UTC)
        waiver = SemanticGapWaiver(
            regression_run_id=run.id,
            project_id=project_id,
            gap_key=payload.gap_key,
            reason=payload.reason.strip(),
            approved_by_id=actor.id,
            approved_at=now,
            expires_at=payload.expires_at,
            operation_identity=operation,
            semantic_requirement=requirement,
            requirement_fingerprint=requirement_fingerprint,
        )
        self._repository.add_waiver(waiver)
        await self._session.flush()
        await self._recalculate_plan_gaps(run)
        self._audit.record(
            actor_user_id=actor.id,
            project_id=project_id,
            action="change_regression.semantic_gap_waived",
            resource_type="semantic_gap_waiver",
            resource_id=waiver.id,
            details={
                "regression_run_id": str(run.id),
                "gap_key": payload.gap_key,
                "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
                "coverage_status": "WAIVED",
            },
        )
        await self._session.commit()
        return await self._required_bundle(run.id)

    async def _recalculate_plan_gaps(self, run: ChangeRegressionRun) -> dict[str, JsonValue]:
        summary = cast(dict[str, JsonValue], dict(run.selection_summary))
        raw_scopes = summary.get("semantic_coverage_scopes")
        scopes = (
            [item for item in raw_scopes if isinstance(item, dict)]
            if isinstance(raw_scopes, list)
            else []
        )
        facts = await self._existing_semantic_coverage(run.project_id)
        plan_items = list(
            (
                await self._session.scalars(
                    select(TestPlanItem).where(TestPlanItem.test_plan_id == run.test_plan_id)
                )
            ).all()
        )
        plan_scope = await self._current_plan_scope(
            selected_assets=cast(list_type[dict[str, JsonValue]], run.selected_assets),
            plan_items=plan_items,
            project_id=run.project_id,
        )
        waivers = await self._repository.list_waivers(run.id)
        now = datetime.now(UTC)
        gap_details: list[dict[str, JsonValue]] = []
        project_gap_count = 0
        current_gap_count = 0
        waived_count = 0
        unresolved_count = 0
        for raw_scope in scopes:
            scope = raw_scope
            identity = _operation_from_scope(scope)
            target = _target_from_scope(scope)
            requirements = _scope_requirements(scope)
            semantic_target = scope.get("semantic_target") is True
            if not requirements and not semantic_target:
                continue
            if not requirements and (identity is None or target is None):
                requirements = ["unresolved-operation|unknown|unknown-oracle"]
            project_tokens = (
                semantic_coverage_tokens(facts, identity, target)
                if identity is not None and target is not None
                else set()
            )
            plan_tokens = (
                semantic_coverage_tokens(facts, identity, target, asset_scope=plan_scope)
                if identity is not None and target is not None
                else set()
            )
            for requirement in requirements:
                requirement_fingerprint = _semantic_requirement_fingerprint(
                    identity, target, requirement
                )
                gap_key = _semantic_gap_key(
                    str(scope.get("change_key") or ""), requirement_fingerprint
                )
                matching_waiver = _active_waiver(
                    waivers,
                    gap_key=gap_key,
                    requirement_fingerprint=requirement_fingerprint,
                    now=now,
                )
                covered = requirement in plan_tokens
                project_covered = requirement in project_tokens
                if not project_covered:
                    project_gap_count += 1
                if covered:
                    status = "COVERED"
                else:
                    current_gap_count += 1
                    if matching_waiver is not None:
                        status = "WAIVED"
                        waived_count += 1
                    elif identity is None or target is None or "unknown-oracle" in requirement:
                        status = "UNKNOWN"
                        unresolved_count += 1
                    elif _has_partial_coverage(facts, identity, target, requirement, plan_scope):
                        status = "PARTIAL"
                        unresolved_count += 1
                    else:
                        status = "MISSING"
                        unresolved_count += 1
                recommendations = _recommended_assets(facts, identity, target, requirement)
                gap_details.append(
                    {
                        "change_key": str(scope.get("change_key") or ""),
                        "gap_key": gap_key,
                        "operation": cast(
                            JsonValue,
                            identity.model_dump(mode="json") if identity is not None else None,
                        ),
                        "target": cast(
                            JsonValue,
                            target.model_dump(mode="json") if target is not None else None,
                        ),
                        "semantic_requirement": cast(JsonValue, _semantic_requirement(requirement)),
                        "requirement_fingerprint": requirement_fingerprint,
                        "coverage_status": status,
                        "project_known_coverage": "COVERED" if project_covered else "MISSING",
                        "current_test_plan_coverage": status,
                        "recommended_existing_assets": cast(JsonValue, recommendations),
                        "waiver": cast(
                            JsonValue,
                            _waiver_evidence(matching_waiver)
                            if matching_waiver is not None
                            else None,
                        ),
                    }
                )
        summary.update(
            {
                "asset_mapping_gap_count": _json_int(summary.get("asset_mapping_gap_count")),
                "project_semantic_gap_count": project_gap_count,
                "current_test_plan_semantic_gap_count": current_gap_count,
                "waived_current_plan_gap_count": waived_count,
                "unresolved_current_plan_gap_count": unresolved_count,
                "semantic_gap_count": len(
                    {
                        str(gap.get("change_key") or "")
                        for gap in gap_details
                        if gap.get("project_known_coverage") == "MISSING"
                    }
                ),
                "current_plan_gaps": cast(JsonValue, gap_details),
                "current_plan_recommendations": cast(
                    JsonValue,
                    [
                        {
                            "gap_key": gap["gap_key"],
                            "action": "add_project_known_test_to_current_plan",
                            "recommended_existing_assets": gap["recommended_existing_assets"],
                        }
                        for gap in gap_details
                        if gap["coverage_status"] in {"MISSING", "PARTIAL"}
                        and gap["recommended_existing_assets"]
                    ],
                ),
                "plan_gate_evaluated_at": now.isoformat(),
            }
        )
        run.selection_summary = summary
        return summary

    async def _require_resolved_plan_gaps(self, run: ChangeRegressionRun) -> None:
        state = await self._recalculate_plan_gaps(run)
        count = _json_int(state.get("unresolved_current_plan_gap_count"))
        if count == 0:
            return
        gaps = state.get("current_plan_gaps")
        unresolved = (
            [
                item
                for item in gaps
                if isinstance(item, dict)
                and item.get("coverage_status") not in {"COVERED", "WAIVED"}
            ]
            if isinstance(gaps, list)
            else []
        )
        raise AppError(
            code="CHANGE_REGRESSION_PLAN_GAP_UNRESOLVED",
            message="当前测试计划仍有未解决的语义覆盖缺口",
            status_code=409,
            details={"gap_count": count, "gaps": unresolved[:100]},
        )

    async def _required_bundle(self, run_id: UUID) -> ChangeRegressionBundle:
        bundle = await self._repository.get_bundle(run_id)
        if bundle is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        return bundle

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
            change_set = await self._change_sets.get_change_set_for_update(run.change_set_id)
            if change_set is None:
                raise AppError(
                    code="CHANGE_REGRESSION_CHANGE_SET_MISSING",
                    message="变更回归 ChangeSet 不存在",
                    status_code=409,
                )
            if payload.materialization is None:
                materialized_id = await self._materialize_design(
                    project_id=project_id,
                    change_set_id=run.change_set_id,
                    item=item,
                    document=document,
                    actor=actor,
                )
                item.materialized_resource_type = "test_design"
            else:
                target = payload.materialization
                bundle_result = await TestEngineeringProposalService(
                    self._session
                ).materialize_reviewed_design(
                    actor=actor,
                    project_id=project_id,
                    change_set=change_set,
                    title=item.title,
                    design=document,
                    api_definition_id=target.api_definition_id,
                    environment_id=target.environment_id,
                    endpoint_variant=target.endpoint_variant,
                    scenario_ids=target.scenario_ids,
                    frozen_operation=_frozen_operation(change_set, item.position),
                )
                materialized_id = bundle_result.test_design_id
                item.materialized_resource_type = "test_design_bundle"
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
            state_model=(
                document.state_model.model_dump(mode="json")
                if document.state_model is not None
                else {}
            ),
            scenarios=document.model_dump(mode="json")["scenarios"],
            oracles=document.model_dump(mode="json")["oracles"],
            coverage=document.coverage.model_dump(mode="json"),
            evidence_refs=document.model_dump(mode="json")["evidence_refs"],
            warnings=list(document.warnings),
            confidence=document.confidence,
            review_requirements=list(document.review_requirements),
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
        await self._require_resolved_plan_gaps(run)
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
        await self._require_resolved_plan_gaps(run)
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
        run = await self._repository.get_run_for_update(run_id)
        if run is None:
            raise AppError(
                code="CHANGE_REGRESSION_NOT_FOUND", message="变更回归运行不存在", status_code=404
            )
        plan_gate = await self._recalculate_plan_gaps(run)
        if _json_int(plan_gate.get("unresolved_current_plan_gap_count")) > 0:
            run.status = "blocked"
            run.evidence = {
                **run.evidence,
                "semantic_plan_gate": cast(dict[str, Any], plan_gate),
                "semantic_gap_waivers": [
                    _waiver_evidence(waiver)
                    for waiver in await self._repository.list_waivers(run.id)
                    if _waiver_is_current(waiver, datetime.now(UTC))
                ],
            }
            await self._stage(
                run,
                actor=actor,
                stage="release_gate",
                status="blocked",
                details={
                    "reason": "current_test_plan_semantic_gap",
                    "unresolved_current_plan_gap_count": _json_int(
                        plan_gate.get("unresolved_current_plan_gap_count")
                    ),
                },
            )
            self._audit.record(
                actor_user_id=actor.id,
                project_id=project_id,
                action="change_regression.release_blocked_by_plan_gap",
                resource_type="change_regression_run",
                resource_id=run.id,
                details={
                    "unresolved_current_plan_gap_count": _json_int(
                        plan_gate.get("unresolved_current_plan_gap_count")
                    )
                },
            )
            await self._session.commit()
            return await self._required_bundle(run.id)
        active_waiver_evidence = [
            _waiver_evidence(waiver)
            for waiver in await self._repository.list_waivers(run.id)
            if _waiver_is_current(waiver, datetime.now(UTC))
        ]
        if bundle.release_decision is not None:
            run.evidence = {
                **run.evidence,
                "semantic_plan_gate": cast(dict[str, Any], plan_gate),
                "semantic_gap_waivers": active_waiver_evidence,
            }
            run.status = "passed" if bundle.release_decision.status == "pass" else "blocked"
            await self._session.commit()
            return await self._required_bundle(run.id)
        if run.test_plan_run_id is None:
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
        run.evidence = {
            **cast(dict[str, Any], decision.evidence_snapshot),
            "semantic_plan_gate": cast(dict[str, Any], plan_gate),
            "semantic_gap_waivers": active_waiver_evidence,
        }
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
        execution_ids = [item.workflow_execution_id for item in items if item.workflow_execution_id]
        nodes = (
            list(
                (
                    await self._session.scalars(
                        select(WorkflowNodeExecution).where(
                            WorkflowNodeExecution.workflow_execution_id.in_(execution_ids)
                        )
                    )
                ).all()
            )
            if execution_ids
            else []
        )
        nodes_by_execution: dict[UUID, list[WorkflowNodeExecution]] = {}
        for node in nodes:
            nodes_by_execution.setdefault(node.workflow_execution_id, []).append(node)
        signals = [
            signal
            for item in items
            for signal in _triage_signals(
                item,
                nodes_by_execution.get(item.workflow_execution_id, [])
                if item.workflow_execution_id
                else [],
            )
        ]
        return cast(dict[str, JsonValue], triage_failures(signals).model_dump(mode="json"))

    async def _existing_semantic_coverage(
        self, project_id: UUID
    ) -> list_type[SemanticCoverageFact]:
        """Extract only executable workflow facts with an operation identity and oracle."""

        test_cases = list_type(
            (
                await self._session.scalars(
                    select(TestCase).where(TestCase.project_id == project_id)
                )
            ).all()
        )
        workflows = list_type(
            (
                await self._session.scalars(
                    select(Workflow).where(
                        Workflow.project_id == project_id,
                        Workflow.current_version.is_not(None),
                    )
                )
            ).all()
        )
        facts: list_type[SemanticCoverageFact] = []
        workflows_by_id = {workflow.id: workflow for workflow in workflows}
        for case in test_cases:
            workflow_id = _test_case_workflow_id(case.draft_definition)
            workflow = workflows_by_id.get(workflow_id) if workflow_id is not None else None
            if workflow is None:
                continue
            facts.extend(
                await self._workflow_semantic_facts(
                    project_id=project_id,
                    workflow=workflow,
                    source_asset_type="test_case",
                    source_asset_id=case.id,
                )
            )
        for workflow in workflows:
            facts.extend(
                await self._workflow_semantic_facts(
                    project_id=project_id,
                    workflow=workflow,
                    source_asset_type="workflow",
                    source_asset_id=workflow.id,
                )
            )
        return facts

    async def _workflow_semantic_facts(
        self,
        *,
        project_id: UUID,
        workflow: Workflow,
        source_asset_type: Literal["test_case", "workflow"],
        source_asset_id: UUID,
    ) -> list_type[SemanticCoverageFact]:
        if workflow.current_version is None:
            return []
        published = await self._session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version == workflow.current_version,
            )
        )
        if published is None:
            return []
        workflow_definition = published.definition
        facts: list_type[SemanticCoverageFact] = []
        for raw_node in _workflow_api_nodes(workflow_definition):
            config = _mapping(raw_node.get("config"))
            try:
                definition_id = UUID(str(config["api_definition_id"]))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            raw_version = config.get("api_version")
            version_number = raw_version if isinstance(raw_version, int) else None
            resolved = await self._operation_identity(
                project_id=project_id,
                definition_id=definition_id,
                version_number=version_number,
            )
            if resolved is None:
                continue
            identity, contract = resolved
            node_id = raw_node.get("id")
            category, oracle_identities, oracle_conflict = _workflow_oracle_semantics(
                workflow_definition,
                str(node_id) if isinstance(node_id, str) else "",
                config,
            )
            facts.extend(
                _workflow_node_facts(
                    definition=workflow_definition,
                    config=config,
                    identity=identity,
                    contract=contract,
                    expected_category=category,
                    oracle_identities=oracle_identities,
                    oracle_conflict=oracle_conflict,
                    source_asset_type=source_asset_type,
                    source_asset_id=str(source_asset_id),
                )
            )
        return facts

    async def _current_plan_scope(
        self,
        *,
        selected_assets: list_type[dict[str, JsonValue]],
        plan_items: list_type[TestPlanItem],
        project_id: UUID,
    ) -> set[tuple[str, str]]:
        selected = {
            (str(asset.get("target_type")), str(asset.get("target_id")))
            for asset in selected_assets
        }
        scope: set[tuple[str, str]] = set()
        case_ids = [item.target_id for item in plan_items if item.target_type == "case"]
        cases = (
            list_type(
                (
                    await self._session.scalars(
                        select(TestCase).where(
                            TestCase.project_id == project_id,
                            TestCase.id.in_(case_ids),
                        )
                    )
                ).all()
            )
            if case_ids
            else []
        )
        cases_by_id = {case.id: case for case in cases}
        for item in plan_items:
            if item.target_type == "workflow":
                key = ("workflow", str(item.target_id))
                if key in selected:
                    scope.add(key)
                continue
            if item.target_type != "case":
                continue
            case_key = ("test_case", str(item.target_id))
            case = cases_by_id.get(item.target_id)
            workflow_id = _test_case_workflow_id(case.draft_definition) if case else None
            workflow_key = ("workflow", str(workflow_id)) if workflow_id else None
            if case_key in selected or (workflow_key is not None and workflow_key in selected):
                scope.add(case_key)
        return scope

    async def _current_contract_for_gap(
        self,
        project_id: UUID,
        gap: dict[str, JsonValue],
        *,
        selected_assets: list_type[dict[str, JsonValue]],
    ) -> tuple[OperationContract, OperationIdentity] | None:
        explicit_id = _uuid_value(gap.get("api_definition_id"))
        explicit_version = _positive_int(gap.get("api_version"))
        if explicit_id is not None:
            explicit = await self._operation_identity(
                project_id=project_id,
                definition_id=explicit_id,
                version_number=explicit_version,
            )
            if explicit is None or not _resolved_matches_gap(explicit, gap):
                return None
            return _contract_identity(explicit)

        selected_refs = await self._selected_operation_refs(project_id, selected_assets)
        selected = await self._resolve_operation_refs(project_id, selected_refs, gap)
        if len(selected) == 1:
            return _contract_identity(selected[0])
        if len(selected) > 1:
            return None

        current = await self._current_project_operations(project_id)
        return _select_current_operation(current, gap)

    async def _current_project_operations(
        self, project_id: UUID
    ) -> list_type[tuple[OperationIdentity, OperationContract]]:
        definitions = list_type(
            (
                await self._session.scalars(
                    select(APIDefinition).where(
                        APIDefinition.project_id == project_id,
                        APIDefinition.is_active.is_(True),
                    )
                )
            ).all()
        )
        result: list_type[tuple[OperationIdentity, OperationContract]] = []
        for definition in definitions:
            resolved = await self._operation_identity(
                project_id=project_id,
                definition_id=definition.id,
                version_number=definition.current_version,
            )
            if resolved is not None:
                result.append(resolved)
        return result

    async def _resolve_operation_refs(
        self,
        project_id: UUID,
        refs: set[tuple[UUID, int]],
        gap: dict[str, JsonValue],
    ) -> list_type[tuple[OperationIdentity, OperationContract]]:
        result: list_type[tuple[OperationIdentity, OperationContract]] = []
        for definition_id, version in sorted(refs, key=lambda item: (str(item[0]), item[1])):
            resolved = await self._operation_identity(
                project_id=project_id,
                definition_id=definition_id,
                version_number=version,
            )
            if _resolved_matches_gap(resolved, gap):
                result.append(cast(tuple[OperationIdentity, OperationContract], resolved))
        return result

    async def _selected_operation_refs(
        self,
        project_id: UUID,
        selected_assets: list_type[dict[str, JsonValue]],
    ) -> set[tuple[UUID, int]]:
        workflow_ids = await self._selected_workflow_ids(project_id, selected_assets)
        refs: set[tuple[UUID, int]] = set()
        for workflow_id in workflow_ids:
            refs.update(await self._published_workflow_refs(project_id, workflow_id))
        return refs

    async def _selected_workflow_ids(
        self,
        project_id: UUID,
        selected_assets: list_type[dict[str, JsonValue]],
    ) -> set[UUID]:
        workflow_ids: set[UUID] = set()
        for asset in selected_assets:
            target_id = _uuid_value(asset.get("target_id"))
            if target_id is None:
                continue
            target_type = asset.get("target_type")
            if target_type == "workflow":
                workflow_ids.add(target_id)
            elif target_type == "test_case":
                workflow_id = await self._published_test_case_workflow(project_id, target_id)
                if workflow_id is not None:
                    workflow_ids.add(workflow_id)
        return workflow_ids

    async def _published_workflow_refs(
        self, project_id: UUID, workflow_id: UUID
    ) -> set[tuple[UUID, int]]:
        refs: set[tuple[UUID, int]] = set()
        workflow = await self._session.get(Workflow, workflow_id)
        if (
            workflow is None
            or workflow.project_id != project_id
            or workflow.current_version is None
        ):
            return refs
        published = await self._session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version == workflow.current_version,
            )
        )
        if published is None:
            return refs
        for node in _workflow_api_nodes(published.definition):
            config = _mapping(node.get("config"))
            definition_id = _uuid_value(config.get("api_definition_id"))
            version = _positive_int(config.get("api_version"))
            if definition_id is not None and version is not None:
                refs.add((definition_id, version))
        return refs

    async def _published_test_case_workflow(
        self, project_id: UUID, test_case_id: UUID
    ) -> UUID | None:
        test_case = await self._session.get(TestCase, test_case_id)
        if (
            test_case is None
            or test_case.project_id != project_id
            or test_case.current_version is None
        ):
            return None
        version = await self._session.scalar(
            select(TestCaseVersion).where(
                TestCaseVersion.test_case_id == test_case.id,
                TestCaseVersion.version == test_case.current_version,
            )
        )
        return _test_case_workflow_id(version.definition) if version is not None else None

    async def _operation_identity(
        self,
        *,
        project_id: UUID,
        definition_id: UUID,
        version_number: int | None,
    ) -> tuple[OperationIdentity, OperationContract] | None:
        definition = await self._session.get(APIDefinition, definition_id)
        if definition is None or definition.project_id != project_id or not definition.is_active:
            return None
        target_version = version_number or definition.current_version
        version = await self._session.scalar(
            select(APIVersion).where(
                APIVersion.api_definition_id == definition.id,
                APIVersion.version == target_version,
            )
        )
        # A missing pinned version is unknown coverage; never fall back to current.
        if version is None:
            return None
        service_key = "unassigned"
        if definition.service_id is not None:
            service = await self._session.get(Service, definition.service_id)
            if service is None or service.project_id != project_id:
                return None
            service_key = service.service_key
        if version.canonical_contract:
            try:
                contract = OperationContract.model_validate(version.canonical_contract)
            except ValueError:
                return None
            contract = contract.model_copy(update={"service": service_key})
        else:
            contract = await TestEngineeringService(self._session).contract_for_api(
                project_id=project_id,
                definition_id=definition.id,
            )
            if target_version != definition.current_version:
                return None
        identity = OperationIdentity(
            api_definition_id=str(definition.id),
            api_version=version.version,
            portable_operation_ref=contract.operation,
            service_key=service_key,
            method=version.method,
            normalized_path=_semantic_path(version.path),
            contract_fingerprint=fingerprint_contract(contract),
        )
        return identity, contract

    async def _current_path(self, definition: APIDefinition) -> str:
        version = await self._session.scalar(
            select(APIVersion).where(
                APIVersion.api_definition_id == definition.id,
                APIVersion.version == definition.current_version,
            )
        )
        return version.path if version is not None else ""


def _triage_signals(
    item: TestPlanRunItem, nodes: list[WorkflowNodeExecution]
) -> list[FailureSignal]:
    if not nodes:
        return [
            FailureSignal(
                evidence_ref=(f"flowtest://test-plan-runs/{item.test_plan_run_id}/items/{item.id}"),
                item_status=item.status,
                attempts=item.attempts,
            )
        ]
    return [_node_triage_signal(item, node) for node in nodes]


def _node_triage_signal(item: TestPlanRunItem, node: WorkflowNodeExecution) -> FailureSignal:
    result = _validated_node_result(node.result)
    observation = result.observations[-1] if result and result.observations else None
    request_url = urlsplit(observation.request.url) if observation else None
    error = result.error if result is not None else None
    assertions = list(result.assertions) if result is not None else []
    assertion_failed = node.node_type == "assert" or any(
        not assertion.passed for assertion in assertions
    )
    contract_assertion_failed = any(
        not assertion.passed and assertion.name.lower() in _CONTRACT_ASSERTION_NAMES
        for assertion in assertions
    )
    return FailureSignal(
        evidence_ref=(f"flowtest://runs/{node.workflow_execution_id}/nodes/{node.node_id}"),
        item_status=node.status if node.status in {"failed", "cancelled"} else item.status,
        attempts=max(item.attempts, node.attempts),
        error_code=node.error_code or (error.code if error is not None else None),
        retryable=error.retryable if error is not None else False,
        http_status=(
            observation.response.status_code if observation and observation.response else None
        ),
        affected_service=observation.request.service_key if observation is not None else None,
        endpoint_variant=observation.request.endpoint_variant if observation is not None else None,
        affected_operation=(
            f"{observation.request.method} {request_url.path}"
            if observation is not None and request_url is not None
            else None
        ),
        response_received=bool(observation and observation.response),
        assertion_failed=assertion_failed,
        contract_assertion_failed=contract_assertion_failed,
    )


def _validated_node_result(value: dict[str, Any] | None) -> NodeResult | None:
    if value is None:
        return None
    try:
        return NodeResult.model_validate(value)
    except ValueError:
        return None


_CONTRACT_ASSERTION_NAMES = frozenset(
    {"response_schema", "schema", "contract", "json_schema", "openapi_schema"}
)


def _semantic_path(value: str) -> str:
    return re.sub(r"\{\{[^}]+\}\}|\{[^}]+\}", "{}", value)


def _uuid_value(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


def _gap_route(gap: dict[str, JsonValue]) -> tuple[str, str] | None:
    method = gap.get("method")
    path = gap.get("normalized_path")
    if isinstance(method, str) and isinstance(path, str) and path.startswith("/"):
        return method.upper(), _semantic_path(path)
    source_key = str(gap.get("source_key") or "")
    parts = source_key.split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("/"):
        return parts[0].upper(), _semantic_path(parts[1])
    return None


def _operation_matches_route(identity: OperationIdentity, gap: dict[str, JsonValue]) -> bool:
    route = _gap_route(gap)
    return route is None or (identity.method, identity.normalized_path) == route


def _resolved_matches_gap(
    resolved: tuple[OperationIdentity, OperationContract] | None,
    gap: dict[str, JsonValue],
) -> bool:
    if resolved is None:
        return False
    identity, _ = resolved
    if not _operation_matches_route(identity, gap):
        return False
    expected_values = {
        "service_key": identity.service_key,
        "portable_operation_ref": identity.portable_operation_ref,
        "current_contract_fingerprint": identity.contract_fingerprint,
        "api_definition_id": identity.api_definition_id,
        "api_version": identity.api_version,
    }
    return all(
        gap.get(key) is None or str(gap.get(key)) == str(actual)
        for key, actual in expected_values.items()
    )


def _contract_identity(
    resolved: tuple[OperationIdentity, OperationContract],
) -> tuple[OperationContract, OperationIdentity]:
    identity, contract = resolved
    return contract, identity


def _select_current_operation(
    current: list_type[tuple[OperationIdentity, OperationContract]],
    gap: dict[str, JsonValue],
) -> tuple[OperationContract, OperationIdentity] | None:
    fingerprint = gap.get("current_contract_fingerprint")
    if isinstance(fingerprint, str):
        matches = [
            item
            for item in current
            if item[0].contract_fingerprint == fingerprint
            and _operation_matches_route(item[0], gap)
        ]
        if matches:
            return _unique_current_operation(matches)
    service_key = gap.get("service_key")
    if isinstance(service_key, str) and service_key:
        matches = [
            item
            for item in current
            if item[0].service_key == service_key and _operation_matches_route(item[0], gap)
        ]
        if matches:
            return _unique_current_operation(matches)
    portable_ref = gap.get("portable_operation_ref")
    if isinstance(portable_ref, str) and portable_ref:
        matches = [item for item in current if item[0].portable_operation_ref == portable_ref]
        if matches:
            return _unique_current_operation(matches)
    return _unique_current_operation(
        [item for item in current if _operation_matches_route(item[0], gap)]
    )


def _unique_current_operation(
    matches: list_type[tuple[OperationIdentity, OperationContract]],
) -> tuple[OperationContract, OperationIdentity] | None:
    return _contract_identity(matches[0]) if len(matches) == 1 else None


def _frozen_operation(change_set: AIChangeSet, position: int) -> OperationIdentity | None:
    raw = change_set.source_snapshot.get("frozen_operations")
    if not isinstance(raw, list):
        return None
    # Change regression item positions mirror the one-based semantic target positions.
    index = position - 1
    if index < 0 or index >= len(raw) or not isinstance(raw[index], dict):
        return None
    operation = raw[index].get("operation")
    if not isinstance(operation, dict):
        return None
    try:
        return OperationIdentity.model_validate(operation)
    except ValueError:
        return None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _workflow_api_nodes(definition: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict) and node.get("type") == "api"]


def _expected_semantics(
    raw_statuses: object,
) -> tuple[Literal["success", "invalid_request", "unauthorized", "unknown"], str | None]:
    if (
        not isinstance(raw_statuses, list)
        or len(raw_statuses) != 1
        or not isinstance(raw_statuses[0], int)
    ):
        return "unknown", None
    status = raw_statuses[0]
    if 200 <= status <= 299:
        return "success", f"status:{status}"
    if status in {401, 403}:
        return "unauthorized", f"status:{status}"
    if 400 <= status <= 499:
        return "invalid_request", f"status:{status}"
    return "unknown", f"status:{status}"


def _workflow_oracle_semantics(
    definition: dict[str, Any],
    request_node_id: str,
    config: dict[str, Any],
) -> tuple[
    Literal["success", "invalid_request", "unauthorized", "unknown"],
    tuple[str, ...],
    bool,
]:
    direct_statuses = _status_identities(config.get("expected_statuses"))
    assert_groups: dict[str, set[str]] = {}
    nodes = definition.get("nodes")
    if isinstance(nodes, list):
        for raw_node in nodes:
            node = _mapping(raw_node)
            if node.get("type") != "assert":
                continue
            assert_config = _mapping(node.get("config"))
            if assert_config.get("source_node_id") != request_node_id:
                continue
            target, identities = _assert_oracle_identities(assert_config)
            if target is not None and identities:
                assert_groups.setdefault(target, set()).update(identities)
    assert_statuses = assert_groups.get("status", set())
    conflict = bool(direct_statuses and assert_statuses and direct_statuses != assert_statuses)
    conflict = conflict or any(
        target != "status" and len(identities) > 1 for target, identities in assert_groups.items()
    )
    identities = set(direct_statuses)
    for values in assert_groups.values():
        identities.update(values)
    statuses = {
        int(identity.removeprefix("status:"))
        for identity in identities
        if identity.startswith("status:") and identity.removeprefix("status:").isdigit()
    }
    categories = {_status_category(status) for status in statuses}
    category = next(iter(categories)) if len(categories) == 1 else "unknown"
    if conflict:
        return "unknown", (), True
    return category, tuple(sorted(identities)), False


def _status_identities(value: object) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    return {
        f"status:{status}"
        for status in value
        if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599
    }


def _status_category(
    status: int,
) -> Literal["success", "invalid_request", "unauthorized", "unknown"]:
    if 200 <= status <= 299:
        return "success"
    if status in {401, 403}:
        return "unauthorized"
    if 400 <= status <= 499:
        return "invalid_request"
    return "unknown"


def _assert_oracle_identities(config: dict[str, Any]) -> tuple[str | None, set[str]]:
    expression = config.get("expression")
    operator = config.get("operator")
    expected = config.get("expected")
    if config.get("assertion_type") == "json_schema":
        if isinstance(expected, dict):
            return "schema", {f"schema:{semantic_schema_fingerprint(expected)}"}
        return "schema", set()
    if expression == "status_code":
        if operator == "equals" and isinstance(expected, int) and not isinstance(expected, bool):
            return "status", {f"status:{expected}"}
        if operator == "in":
            return "status", _status_identities(expected)
        return "status", set()
    if not isinstance(expression, str) or not isinstance(operator, str):
        return None, set()
    if contains_sensitive_contract_value(expected):
        return expression, set()
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    prefix = "json_path" if expression.startswith(("$", "@")) else "expression"
    identity = f"{prefix}:{expression}|{operator}|{canonical}"
    return f"{prefix}:{expression}", {identity}


def _workflow_node_facts(
    *,
    definition: dict[str, Any],
    config: dict[str, Any],
    identity: OperationIdentity,
    contract: OperationContract,
    expected_category: Literal["success", "invalid_request", "unauthorized", "unknown"],
    oracle_identities: tuple[str, ...],
    oracle_conflict: bool,
    source_asset_type: Literal["test_case", "workflow"],
    source_asset_id: str,
) -> list[SemanticCoverageFact]:
    values: list[tuple[Literal["path", "query", "header", "cookie", "body"], str, object]] = []
    variables = definition.get("variables")
    if isinstance(variables, dict):
        for parameter in contract.parameters:
            if parameter.location == "path" and parameter.name in variables:
                values.append(
                    (
                        "path",
                        parameter.name,
                        _coerce_parameter_value(variables[parameter.name], parameter),
                    )
                )
    overrides = _mapping(config.get("request_overrides"))
    values.extend(_query_override_values(overrides, contract))
    values.extend(_header_override_values(overrides, contract))
    body = overrides.get("body")
    if isinstance(body, dict) and body.get("kind") == "json":
        values.extend(("body", path, value) for path, value in _flatten_values(body.get("value")))
    scenario_kind = str(config.get("scenario_kind") or expected_category)
    fingerprint = None if oracle_conflict else oracle_set_fingerprint(oracle_identities)
    legacy_identity = oracle_identities[0] if len(oracle_identities) == 1 else None
    return [
        SemanticCoverageFact(
            operation_identity=identity,
            request_location=location,
            field_path=field_path,
            semantic_value=_encoded_semantic_value(value),
            scenario_kind=scenario_kind,
            expected_category=expected_category,
            oracle_identity=legacy_identity,
            oracle_identities=oracle_identities if not oracle_conflict else (),
            oracle_set_fingerprint=fingerprint,
            source_asset_type=source_asset_type,
            source_asset_id=source_asset_id,
        )
        for location, field_path, value in values
    ]


def _query_override_values(
    overrides: dict[str, Any], contract: OperationContract
) -> list[tuple[Literal["query"], str, object]]:
    query = overrides.get("query_parameters")
    if not isinstance(query, list):
        return []
    result: list[tuple[Literal["query"], str, object]] = []
    for raw_parameter in query:
        parameter = _mapping(raw_parameter)
        name = parameter.get("name")
        if not isinstance(name, str) or parameter.get("enabled", True) is False:
            continue
        contract_parameter = _contract_parameter(contract, "query", name)
        result.append(
            (
                "query",
                name,
                _coerce_parameter_value(parameter.get("value"), contract_parameter),
            )
        )
    return result


def _header_override_values(
    overrides: dict[str, Any], contract: OperationContract
) -> list[tuple[Literal["header", "cookie"], str, object]]:
    headers = overrides.get("headers")
    if not isinstance(headers, dict):
        return []
    result: list[tuple[Literal["header", "cookie"], str, object]] = []
    for raw_name, value in headers.items():
        if not isinstance(raw_name, str):
            continue
        if raw_name.lower() == "cookie":
            result.extend(_cookie_values(value))
            continue
        contract_parameter = _contract_parameter(contract, "header", raw_name)
        name = contract_parameter.name if contract_parameter is not None else raw_name
        result.append(
            (
                "header",
                name,
                _coerce_parameter_value(value, contract_parameter),
            )
        )
    return result


def _contract_parameter(
    contract: OperationContract,
    location: Literal["path", "query", "header", "cookie"],
    name: str,
) -> ContractParameter | None:
    matches = [
        parameter
        for parameter in contract.parameters
        if parameter.location == location
        and (
            parameter.name.lower() == name.lower()
            if location == "header"
            else parameter.name == name
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _coerce_parameter_value(value: object, parameter: ContractParameter | None) -> object:
    if parameter is None or not isinstance(value, str):
        return value
    schema_type = parameter.schema_.get("type")
    try:
        if schema_type == "integer":
            return int(value)
        if schema_type == "number":
            return float(value)
        if schema_type == "boolean" and value.lower() in {"true", "false"}:
            return value.lower() == "true"
    except ValueError:
        return value
    return value


def _cookie_values(value: object) -> list[tuple[Literal["cookie"], str, object]]:
    if not isinstance(value, str):
        return []
    cookie = SimpleCookie()
    try:
        cookie.load(value)
    except CookieError:
        return []
    return [("cookie", name, morsel.value) for name, morsel in cookie.items()]


def _flatten_values(value: object, path: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [
            item
            for name, child in value.items()
            for item in _flatten_values(child, f"{path}.{name}" if path else str(name))
        ]
    if isinstance(value, list):
        return [(path, child) for child in value]
    return [(path, value)] if path else []


def _encoded_semantic_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _semantic_scope_result(
    *,
    gap: dict[str, JsonValue],
    identity: OperationIdentity | None,
    target: ChangeConstraintTarget | None,
    project_content: dict[str, JsonValue],
    current_plan_content: dict[str, JsonValue],
    project_values: set[str],
    current_plan_values: set[str],
) -> dict[str, JsonValue]:
    project_missing = _design_missing_values(project_content)
    current_plan_missing = _design_missing_values(current_plan_content)
    return {
        "change_key": str(gap.get("change_key") or ""),
        "operation": cast(
            JsonValue, identity.model_dump(mode="json") if identity is not None else None
        ),
        "target": cast(JsonValue, target.model_dump(mode="json") if target is not None else None),
        "project_known_coverage": "missing" if project_missing else "covered",
        "current_test_plan_coverage": "missing" if current_plan_missing else "covered",
        "project_known_values": cast(JsonValue, sorted(project_values)),
        "current_test_plan_values": cast(JsonValue, sorted(current_plan_values)),
        "project_missing_values": cast(JsonValue, project_missing),
        "current_test_plan_missing_values": cast(JsonValue, current_plan_missing),
        "semantic_requirements": cast(JsonValue, current_plan_missing),
        "oracle_sources": cast(JsonValue, _design_oracle_sources(current_plan_content)),
        "semantic_target": _is_semantic_test_target(gap),
        "requires_review": identity is None or target is None,
    }


def _scope_gap_count(scopes: list[dict[str, JsonValue]], key: str) -> int:
    return sum(len(values) for scope in scopes if isinstance((values := scope.get(key)), list))


def _scope_requirements(scope: dict[str, JsonValue]) -> list[str]:
    raw = scope.get("semantic_requirements")
    if not isinstance(raw, list):
        raw = scope.get("current_test_plan_missing_values")
    return sorted({str(item) for item in raw}) if isinstance(raw, list) else []


def _operation_from_scope(scope: dict[str, JsonValue]) -> OperationIdentity | None:
    raw = scope.get("operation")
    if not isinstance(raw, dict):
        return None
    try:
        return OperationIdentity.model_validate(raw)
    except ValueError:
        return None


def _target_from_scope(scope: dict[str, JsonValue]) -> ChangeConstraintTarget | None:
    raw = scope.get("target")
    if not isinstance(raw, dict):
        return None
    try:
        return ChangeConstraintTarget.model_validate(raw)
    except ValueError:
        return None


def _semantic_requirement(token: str) -> dict[str, JsonValue]:
    try:
        value, category, fingerprint = token.rsplit("|", 2)
    except ValueError:
        return {"token": token}
    try:
        semantic_value = json.loads(value)
    except (TypeError, ValueError):
        semantic_value = value
    return {
        "token": token,
        "semantic_value": cast(JsonValue, semantic_value),
        "expected_category": category,
        "oracle_set_fingerprint": fingerprint,
    }


def _semantic_requirement_fingerprint(
    identity: OperationIdentity | None,
    target: ChangeConstraintTarget | None,
    requirement: str,
) -> str:
    payload = {
        "operation": identity.model_dump(mode="json") if identity is not None else None,
        "target": target.model_dump(mode="json") if target is not None else None,
        "requirement": requirement,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _semantic_gap_key(change_key: str, requirement_fingerprint: str) -> str:
    return hashlib.sha256(f"{change_key}|{requirement_fingerprint}".encode()).hexdigest()


def _active_waiver(
    waivers: list[SemanticGapWaiver],
    *,
    gap_key: str,
    requirement_fingerprint: str,
    now: datetime,
) -> SemanticGapWaiver | None:
    matches = [
        waiver
        for waiver in waivers
        if waiver.gap_key == gap_key
        and waiver.requirement_fingerprint == requirement_fingerprint
        and _waiver_is_current(waiver, now)
    ]
    return matches[-1] if matches else None


def _waiver_is_current(waiver: SemanticGapWaiver, now: datetime) -> bool:
    if waiver.expires_at is None:
        return True
    expiry = waiver.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry > now


def _waiver_evidence(waiver: SemanticGapWaiver) -> dict[str, JsonValue]:
    return {
        "id": str(waiver.id),
        "gap_key": waiver.gap_key,
        "reason": waiver.reason,
        "approved_by": str(waiver.approved_by_id),
        "approved_at": waiver.approved_at.isoformat(),
        "expires_at": waiver.expires_at.isoformat() if waiver.expires_at else None,
        "operation_identity": cast(JsonValue, waiver.operation_identity),
        "semantic_requirement": cast(JsonValue, waiver.semantic_requirement),
        "coverage_status": "WAIVED",
    }


def _find_gap(state: dict[str, JsonValue], gap_key: str) -> dict[str, JsonValue] | None:
    gaps = state.get("current_plan_gaps")
    if not isinstance(gaps, list):
        return None
    return next(
        (item for item in gaps if isinstance(item, dict) and item.get("gap_key") == gap_key),
        None,
    )


def _semantic_target(summary: dict[str, Any], change_key: str) -> dict[str, JsonValue] | None:
    targets = summary.get("semantic_targets")
    if not isinstance(targets, list):
        return None
    return next(
        (
            cast(dict[str, JsonValue], item)
            for item in targets
            if isinstance(item, dict)
            and str(item.get("change_key") or item.get("key") or "") == change_key
        ),
        None,
    )


def _json_mapping(value: object) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], dict(value)) if isinstance(value, dict) else {}


def _json_int(value: JsonValue | None) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _recommended_assets(
    facts: list_type[SemanticCoverageFact],
    identity: OperationIdentity | None,
    target: ChangeConstraintTarget | None,
    requirement: str,
) -> list[dict[str, JsonValue]]:
    if identity is None or target is None:
        return []
    assets = {
        (fact.source_asset_type, fact.source_asset_id)
        for fact in facts
        if requirement in semantic_coverage_tokens([fact], identity, target)
    }
    return [
        {"target_type": asset_type, "target_id": asset_id}
        for asset_type, asset_id in sorted(assets)
    ]


def _has_partial_coverage(
    facts: list_type[SemanticCoverageFact],
    identity: OperationIdentity,
    target: ChangeConstraintTarget,
    requirement: str,
    asset_scope: set[tuple[str, str]],
) -> bool:
    try:
        semantic_value, category, _ = requirement.rsplit("|", 2)
    except ValueError:
        return False
    for fact in facts:
        if (fact.source_asset_type, fact.source_asset_id) not in asset_scope:
            continue
        if fact.request_location != target.location or fact.field_path != ".".join(
            target.field_path
        ):
            continue
        if fact.semantic_value != semantic_value or fact.expected_category != category:
            continue
        if _coverage_operation_matches(fact.operation_identity, identity):
            return True
    return False


def _coverage_operation_matches(left: OperationIdentity, right: OperationIdentity) -> bool:
    if left.api_definition_id and right.api_definition_id:
        return left.api_definition_id == right.api_definition_id
    return (
        left.service_key == right.service_key
        and left.method == right.method
        and left.normalized_path == right.normalized_path
    )


def _design_oracle_sources(content: dict[str, JsonValue]) -> list[dict[str, str]]:
    oracles = content.get("oracles")
    if not isinstance(oracles, list):
        return []
    sources: set[tuple[str, str]] = set()
    for raw_oracle in oracles:
        oracle = _mapping(raw_oracle)
        source_type = oracle.get("source_type")
        source_ref = oracle.get("source_ref")
        if isinstance(source_type, str) and isinstance(source_ref, str):
            sources.add((source_type, source_ref))
    return [
        {"source_type": source_type, "source_ref": source_ref}
        for source_type, source_ref in sorted(sources)
    ]


def _design_missing_values(content: dict[str, JsonValue]) -> list[str]:
    try:
        document = TestDesignDocument.model_validate(content)
    except (TypeError, ValueError):
        return []
    result: set[str] = set()
    for scenario in document.scenarios:
        if not scenario.mutations:
            continue
        fingerprint = oracle_set_fingerprint(scenario_oracle_identities(scenario, document.oracles))
        oracle_token = fingerprint or "unknown-oracle"
        result.add(
            f"{_encoded_semantic_value(scenario.mutations[0].value)}|"
            f"{scenario.expected_category}|{oracle_token}"
        )
    return sorted(result)


def _missing_test_targets(
    impact: ImpactRunBundle, asset_gaps: list[dict[str, JsonValue]]
) -> list[dict[str, JsonValue]]:
    """Keep asset coverage and test semantic coverage as independent dimensions."""

    by_key = {str(gap.get("change_key")): gap for gap in asset_gaps}
    ordered_keys = [str(gap.get("change_key")) for gap in asset_gaps]
    for raw_change in impact.run.changes:
        change = cast(dict[str, JsonValue], raw_change)
        if not _is_semantic_test_target(change):
            continue
        key = str(change.get("key") or change.get("change_key"))
        if key in by_key:
            continue
        normalized = {**change, "change_key": key, "reason": "测试语义覆盖需独立核对"}
        by_key[key] = normalized
        ordered_keys.append(key)
    return [by_key[key] for key in ordered_keys]


def _is_semantic_test_target(change: dict[str, JsonValue]) -> bool:
    semantic_type = str(change.get("semantic_type") or "")
    return str(change.get("source_kind")) == "openapi" and semantic_type in {
        "minimum_changed",
        "maximum_changed",
        "exclusiveMinimum_changed",
        "exclusiveMaximum_changed",
        "minLength_changed",
        "maxLength_changed",
        "minItems_changed",
        "maxItems_changed",
        "enum_changed",
        "pattern_changed",
        "format_changed",
    }


def _test_case_workflow_id(definition: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str(definition["workflow_id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _merge_workflow_semantics(coverage: dict[str, set[str]], definition: dict[str, Any]) -> None:
    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        return
    variables = definition.get("variables")
    if isinstance(variables, dict):
        for name, value in variables.items():
            _add_semantic_value(coverage, f"path.{name}", value)
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "api":
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        overrides = config.get("request_overrides")
        if not isinstance(overrides, dict):
            continue
        _merge_override_semantics(coverage, overrides)


def _merge_override_semantics(coverage: dict[str, set[str]], overrides: dict[str, Any]) -> None:
    query = overrides.get("query_parameters")
    if isinstance(query, list):
        for parameter in query:
            if isinstance(parameter, dict) and isinstance(parameter.get("name"), str):
                _add_semantic_value(coverage, f"query.{parameter['name']}", parameter.get("value"))
    headers = overrides.get("headers")
    if isinstance(headers, dict):
        for name, value in headers.items():
            _add_semantic_value(coverage, f"header.{name}", value)
    body = overrides.get("body")
    if isinstance(body, dict) and body.get("kind") == "json":
        _flatten_semantic_values(coverage, "body", body.get("value"))


def _flatten_semantic_values(coverage: dict[str, set[str]], path: str, value: object) -> None:
    if isinstance(value, dict):
        for name, child in value.items():
            _flatten_semantic_values(coverage, f"{path}.{name}", child)
        return
    if isinstance(value, list):
        for child in value:
            _flatten_semantic_values(coverage, path, child)
        return
    _add_semantic_value(coverage, path, value)


def _add_semantic_value(coverage: dict[str, set[str]], path: str, value: object) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return
    coverage.setdefault(path, set()).add(encoded)


def _selected_assets(impact: ImpactRunBundle) -> list[dict[str, JsonValue]]:
    return cast(list[dict[str, JsonValue]], impact.selection.selected_assets)


def _change_label(gap: dict[str, JsonValue], index: int) -> str:
    return str(gap.get("label") or gap.get("source_key") or index)[:160]


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
