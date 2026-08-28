"""Thin MCP HTTP adapters for test contexts and FlowSpec proposals."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status

from app.api.dependencies import (
    MCPEvidenceCurrent,
    MCPFlowProposalCurrent,
    SessionDependency,
)
from app.schemas.test_contexts import (
    BeginTestContextRequest,
    ContextRequirementsResponse,
    FlowSpecProposalRequest,
    FlowSpecProposalResponse,
    IngestExternalEvidenceRequest,
    TestContextResponse,
)
from app.services.mcp_flow_proposals import MCPFlowProposalService
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
