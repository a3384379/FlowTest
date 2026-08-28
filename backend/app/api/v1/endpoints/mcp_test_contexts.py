"""Thin MCP HTTP adapters for test contexts and FlowSpec proposals."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status

from app.api.dependencies import (
    MCPEvidenceCurrent,
    MCPFlowProposalCurrent,
    SessionDependency,
)
from app.domain.integration_plans import IntegrationPlan, IntegrationPlanCompilation
from app.schemas.test_contexts import (
    BeginTestContextRequest,
    CompilerDiagnosticsResponse,
    ContextRequirementsResponse,
    FlowSpecProposalInspectionResponse,
    FlowSpecProposalRequest,
    FlowSpecProposalResponse,
    IngestExternalEvidenceRequest,
    IntegrationPlanCompileRequest,
    IntegrationPlanRequest,
    IntegrationPlanValidateRequest,
    IntegrationPlanValidationResponse,
    TestContextResponse,
)
from app.services.mcp_flow_proposals import MCPFlowProposalService
from app.services.mcp_integration_plans import MCPIntegrationPlanService
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
