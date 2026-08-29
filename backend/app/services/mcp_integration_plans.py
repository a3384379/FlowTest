"""Tenant-scoped MCP orchestration for deterministic Integration Plans."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.integration_plans import (
    IntegrationPlan,
    IntegrationPlanCompilation,
    PlanValidationResult,
    compile_integration_plan,
    validate_integration_plan,
)
from app.models.access import User
from app.schemas.test_contexts import (
    CompilerDiagnosticsResponse,
    IntegrationPlanRequest,
)
from app.services.integration_plans import (
    ExistingAuthWorkflowSelection,
    IntegrationPlanAssetCommand,
    IntegrationPlanAssetService,
    OperationPlanSelection,
)
from app.services.mcp_flow_proposals import require_mcp_flow_propose_scope
from app.services.test_contexts import TestContextService


class MCPIntegrationPlanService:
    """Resolve authorized assets, while keeping planning and compilation pure."""

    def __init__(self, session: AsyncSession) -> None:
        self._contexts = TestContextService(session)
        self._plans = IntegrationPlanAssetService(session)

    async def plan(
        self,
        *,
        actor: User,
        payload: IntegrationPlanRequest,
    ) -> IntegrationPlan:
        require_mcp_flow_propose_scope()
        context = await self._contexts.require_proposable(
            actor=actor,
            project_id=payload.project_id,
            context_id=payload.context_id,
            revision_id=payload.context_revision_id,
        )
        _validate_target_environment(
            context.context.target_environment_id,
            payload.target_environment.source_ref,
        )
        existing_auth = payload.existing_auth
        return await self._plans.build(
            actor=actor,
            project_id=payload.project_id,
            command=IntegrationPlanAssetCommand(
                context_revision_id=context.revision.id,
                context_fingerprint=context.revision.fingerprint,
                objective=context.context.objective,
                actors=tuple(payload.actors),
                preconditions=tuple(payload.preconditions),
                target_environment=payload.target_environment,
                operations=tuple(
                    OperationPlanSelection(
                        definition_id=item.definition_id,
                        scenario_id=item.scenario_id,
                    )
                    for item in payload.operations
                ),
                existing_auth=(
                    ExistingAuthWorkflowSelection(
                        workflow_id=existing_auth.workflow_id,
                        workflow_version=existing_auth.workflow_version,
                        token_path=existing_auth.token_path,
                        step_id=existing_auth.step_id,
                    )
                    if existing_auth is not None
                    else None
                ),
                data_recipes=tuple(payload.data_recipes),
                database_reads=tuple(payload.database_reads),
                additional_oracles=tuple(payload.additional_oracles),
                cleanup_requirements=tuple(payload.cleanup_requirements),
            ),
        )

    def validate(self, plan: IntegrationPlan) -> PlanValidationResult:
        require_mcp_flow_propose_scope()
        return validate_integration_plan(plan)

    def compile(self, plan: IntegrationPlan) -> IntegrationPlanCompilation:
        require_mcp_flow_propose_scope()
        return compile_integration_plan(plan)

    def explain(self, plan: IntegrationPlan) -> CompilerDiagnosticsResponse:
        require_mcp_flow_propose_scope()
        compilation = compile_integration_plan(plan)
        blockers = sorted(
            {item.code for item in compilation.diagnostics if item.severity == "blocker"}
        )
        reviews = sorted(
            {item.code for item in compilation.diagnostics if item.severity == "review"}
        )
        return CompilerDiagnosticsResponse(
            plan_fingerprint=compilation.plan_fingerprint,
            importable=compilation.importable,
            diagnostics=compilation.diagnostics,
            blocker_codes=blockers,
            review_codes=reviews,
            next_actions=[
                *(f"补齐或修正阻断证据: {code}" for code in blockers),
                *(f"完成人工确认: {code}" for code in reviews),
            ],
        )


def _validate_target_environment(expected_id: UUID | None, source_ref: str) -> None:
    if expected_id is None:
        return
    if source_ref != f"environment://{expected_id}":
        raise AppError(
            code="INTEGRATION_PLAN_ENVIRONMENT_MISMATCH",
            message="Integration Plan 目标环境与 Context Revision 不一致",
            status_code=409,
        )
