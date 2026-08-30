"""Thin MCP HTTP adapters for test contexts and FlowSpec proposals."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status

from app.api.dependencies import (
    MCPEvidenceCurrent,
    MCPFlowProposalCurrent,
    MCPPreviewCurrent,
    SessionDependency,
    WorkflowCoordinator,
)
from app.composition import build_workflow_service
from app.domain.evidence_adapters import EntityMappingResult
from app.domain.integration_plans import IntegrationPlan, IntegrationPlanCompilation
from app.schemas.sandbox_preview import (
    MCPSandboxPreviewExecuteRequest,
    SandboxPreviewExecuteRequest,
    SandboxPreviewExecutionResponse,
)
from app.schemas.test_contexts import (
    BeginTestContextRequest,
    CompilerDiagnosticsResponse,
    ContextRequirementsResponse,
    EvidenceAdapterIngestionResponse,
    FlowSpecProposalInspectionResponse,
    FlowSpecProposalRequest,
    FlowSpecProposalResponse,
    IngestDatabaseEvidenceRequest,
    IngestExternalEvidenceRequest,
    IngestJavaEvidenceRequest,
    IntegrationPlanCompileRequest,
    IntegrationPlanRequest,
    IntegrationPlanValidateRequest,
    IntegrationPlanValidationResponse,
    TestContextResponse,
)
from app.schemas.workflows import WorkflowExecutionResponse
from app.services.durable_execution import DurableExecutionService
from app.services.evidence_adapters import EvidenceAdapterService
from app.services.idempotency import IdempotencyService, require_idempotency_key
from app.services.mcp_flow_proposals import MCPFlowProposalService
from app.services.mcp_integration_plans import MCPIntegrationPlanService
from app.services.sandbox_preview import SandboxPreviewService
from app.services.test_contexts import TestContextService

evidence_router = APIRouter(prefix="/mcp/evidence/contexts")
flow_router = APIRouter(prefix="/mcp/flow")


@evidence_router.post(
    "",
    response_model=TestContextResponse,
    status_code=status.HTTP_201_CREATED,
)
async def begin_test_context(
    payload: BeginTestContextRequest,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> TestContextResponse:
    return await TestContextService(session).begin(actor=principal.actor, payload=payload)


@evidence_router.get(
    "/{context_id}/requirements",
    response_model=ContextRequirementsResponse,
)
async def inspect_context_requirements(
    context_id: UUID,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> ContextRequirementsResponse:
    return await TestContextService(session).requirements(
        actor=principal.actor, context_id=context_id
    )


@evidence_router.post(
    "/{context_id}/evidence",
    response_model=TestContextResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_external_evidence(
    context_id: UUID,
    payload: IngestExternalEvidenceRequest,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> TestContextResponse:
    return await TestContextService(session).ingest(
        actor=principal.actor,
        context_id=context_id,
        envelope=payload.envelope,
    )


@evidence_router.post(
    "/{context_id}/java-evidence",
    response_model=EvidenceAdapterIngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_java_evidence(
    context_id: UUID,
    payload: IngestJavaEvidenceRequest,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> EvidenceAdapterIngestionResponse:
    return await EvidenceAdapterService(session).ingest_java(
        actor=principal.actor,
        context_id=context_id,
        evidence=payload.evidence,
    )


@evidence_router.post(
    "/{context_id}/database-evidence",
    response_model=EvidenceAdapterIngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_database_evidence(
    context_id: UUID,
    payload: IngestDatabaseEvidenceRequest,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> EvidenceAdapterIngestionResponse:
    return await EvidenceAdapterService(session).ingest_database(
        actor=principal.actor,
        context_id=context_id,
        evidence=payload.evidence,
    )


@evidence_router.get(
    "/{context_id}/entity-mapping",
    response_model=EntityMappingResult,
)
async def inspect_entity_mapping(
    context_id: UUID,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> EntityMappingResult:
    return await EvidenceAdapterService(session).inspect_mapping(
        actor=principal.actor,
        context_id=context_id,
    )


@evidence_router.get("/{context_id}", response_model=TestContextResponse)
async def inspect_test_context(
    context_id: UUID,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> TestContextResponse:
    return await TestContextService(session).inspect(actor=principal.actor, context_id=context_id)


@evidence_router.post("/{context_id}/close", response_model=TestContextResponse)
async def close_test_context(
    context_id: UUID,
    session: SessionDependency,
    principal: MCPEvidenceCurrent,
) -> TestContextResponse:
    return await TestContextService(session).close(actor=principal.actor, context_id=context_id)


@flow_router.post(
    "/plans",
    response_model=IntegrationPlan,
)
async def plan_integration_test(
    payload: IntegrationPlanRequest,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
) -> IntegrationPlan:
    return await MCPIntegrationPlanService(session).plan(actor=principal.actor, payload=payload)


@flow_router.post(
    "/plans/validate",
    response_model=IntegrationPlanValidationResponse,
)
async def validate_integration_plan(
    payload: IntegrationPlanValidateRequest,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
) -> IntegrationPlanValidationResponse:
    result = MCPIntegrationPlanService(session).validate(payload.plan)
    return IntegrationPlanValidationResponse(**result.model_dump(mode="python"))


@flow_router.post(
    "/plans/compile",
    response_model=IntegrationPlanCompilation,
)
async def compile_integration_flowspec(
    payload: IntegrationPlanCompileRequest,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
) -> IntegrationPlanCompilation:
    return MCPIntegrationPlanService(session).compile(payload.plan)


@flow_router.post(
    "/plans/diagnostics",
    response_model=CompilerDiagnosticsResponse,
)
async def explain_compiler_diagnostics(
    payload: IntegrationPlanCompileRequest,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
) -> CompilerDiagnosticsResponse:
    return MCPIntegrationPlanService(session).explain(payload.plan)


@flow_router.post(
    "/proposals",
    response_model=FlowSpecProposalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def propose_flow_draft(
    payload: FlowSpecProposalRequest,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> FlowSpecProposalResponse:
    return await MCPFlowProposalService(session).propose(
        actor=principal.actor,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@flow_router.get(
    "/proposals/{change_set_id}",
    response_model=FlowSpecProposalInspectionResponse,
)
async def inspect_flow_proposal(
    change_set_id: UUID,
    project_id: UUID,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
) -> FlowSpecProposalInspectionResponse:
    return await MCPFlowProposalService(session).inspect(
        actor=principal.actor,
        project_id=project_id,
        change_set_id=change_set_id,
    )


@flow_router.post(
    "/proposals/{change_set_id}/preview-executions",
    response_model=SandboxPreviewExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_flow_proposal_preview(
    change_set_id: UUID,
    payload: MCPSandboxPreviewExecuteRequest,
    session: SessionDependency,
    principal: MCPPreviewCurrent,
    coordinator: WorkflowCoordinator,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SandboxPreviewExecutionResponse:
    key = require_idempotency_key(idempotency_key)
    request = SandboxPreviewExecuteRequest.model_validate(
        payload.model_dump(mode="json", exclude={"project_id"})
    )

    async def start() -> SandboxPreviewExecutionResponse:
        execution, plan = await SandboxPreviewService(
            session,
            workflows=build_workflow_service(session),
        ).prepare_execution(
            actor=principal.actor,
            project_id=payload.project_id,
            change_set_id=change_set_id,
            payload=request,
            commit=False,
        )
        actor_key = f"service-account:{principal.account.id}"
        try:
            command = await DurableExecutionService(session).create_start_command(
                actor=principal.actor,
                project_id=payload.project_id,
                execution_id=execution.id,
                actor_key=actor_key,
                idempotency_key=key,
                payload={
                    "change_set_id": str(change_set_id),
                    "execution_id": str(execution.id),
                    "run_purpose": "preview",
                },
            )
        except Exception:
            await session.rollback()
            raise
        try:
            await coordinator.start(plan)
            await DurableExecutionService(session).mark_dispatched(command.id)
        except Exception:
            await session.rollback()
            await DurableExecutionService(session).mark_failed(
                command.id,
                error_code="PREVIEW_COMMAND_DISPATCH_FAILED",
                error_message="Sandbox Preview 启动命令未能提交到执行运行时",
            )
            raise
        return SandboxPreviewExecutionResponse(
            execution=WorkflowExecutionResponse.model_validate(execution)
        )

    response = await IdempotencyService(session).run(
        key=key,
        project_id=payload.project_id,
        actor_key=f"service-account:{principal.account.id}",
        operation=f"sandbox_preview.execute:{change_set_id}",
        request_payload=payload.model_dump(mode="json"),
        action=start,
    )
    return SandboxPreviewExecutionResponse.model_validate(response)
