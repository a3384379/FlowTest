"""Thin MCP gateway for continuous QA reads and review-only proposals."""

import re
from typing import Annotated

from fastapi import APIRouter, Header, Request

from app.api.dependencies import MCPCurrent, MCPFlowProposalCurrent, SessionDependency
from app.domain.mcp_read import MCPCallType, MCPReadCall, MCPReadEnvelope, input_schema_hash
from app.schemas.mcp_continuous import (
    MCPAffectedFlowsRequest,
    MCPContextComparisonRequest,
    MCPContinuousProposalResponse,
    MCPFailureRequest,
    MCPMaintenanceRequest,
    MCPRegressionRequest,
    MCPRepairRequest,
)
from app.services.mcp_continuous import MCPContinuousService

router = APIRouter(prefix="/mcp/continuous")


@router.post("/context-diff", response_model=MCPReadEnvelope)
async def context_diff(
    payload: MCPContextComparisonRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadEnvelope:
    return await MCPContinuousService(session).context_diff(
        actor=principal.actor, payload=payload, call=_call(request, "inspect_context_diff")
    )


@router.post("/affected-flows", response_model=MCPReadEnvelope)
async def affected_flows(
    payload: MCPAffectedFlowsRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadEnvelope:
    return await MCPContinuousService(session).affected_flows(
        actor=principal.actor, payload=payload, call=_call(request, "inspect_affected_flows")
    )


@router.post("/failure-diagnosis", response_model=MCPReadEnvelope)
async def failure_diagnosis(
    payload: MCPFailureRequest, request: Request, session: SessionDependency, principal: MCPCurrent
) -> MCPReadEnvelope:
    return await MCPContinuousService(session).failure_diagnosis(
        actor=principal.actor, payload=payload, call=_call(request, "diagnose_failure")
    )


@router.post("/change-regression", response_model=MCPReadEnvelope)
async def regression(
    payload: MCPRegressionRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPCurrent,
) -> MCPReadEnvelope:
    return await MCPContinuousService(session).regression(
        actor=principal.actor, payload=payload, call=_call(request, "inspect_change_regression")
    )


@router.post("/repair-proposals", response_model=MCPContinuousProposalResponse)
async def repair_proposal(
    payload: MCPRepairRequest,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MCPContinuousProposalResponse:
    return await MCPContinuousService(session).propose_repair(
        actor=principal.actor, payload=payload, idempotency_key=idempotency_key
    )


@router.post("/maintenance-proposals", response_model=MCPContinuousProposalResponse)
async def maintenance_proposal(
    payload: MCPMaintenanceRequest,
    session: SessionDependency,
    principal: MCPFlowProposalCurrent,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MCPContinuousProposalResponse:
    return await MCPContinuousService(session).propose_maintenance(
        actor=principal.actor, payload=payload, idempotency_key=idempotency_key
    )


def _call(request: Request, operation: str) -> MCPReadCall:
    version = request.headers.get("x-mcp-client-version", "unknown")
    if re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", version) is None:
        version = "unknown"
    return MCPReadCall(
        operation=operation,
        call_type=MCPCallType.TOOL,
        input_schema_hash=input_schema_hash(operation),
        client_version=version,
    )
