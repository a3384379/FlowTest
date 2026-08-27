"""MCP proposal and human review endpoints for S42 controlled writes."""

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, status

from app.api.dependencies import CurrentUser, MCPWriteCurrent, SessionDependency
from app.domain.mcp_read import MCPCallType, MCPReadCall, input_schema_hash
from app.schemas.mcp_controlled_write import MCPControlledWriteResponse
from app.schemas.test_design import (
    MCPControlledWriteCreate,
    MCPControlledWriteEnvelope,
    MCPControlledWriteReview,
    MCPManualApprovalCreate,
)
from app.services.mcp_controlled_write import MCPControlledWriteService

router = APIRouter(prefix="/mcp/write")
_CLIENT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")


@router.post(
    "/change-sets",
    response_model=MCPControlledWriteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def propose_change_set(
    payload: MCPControlledWriteCreate,
    request: Request,
    session: SessionDependency,
    principal: MCPWriteCurrent,
) -> MCPControlledWriteEnvelope:
    return await MCPControlledWriteService(session).propose(
        actor=principal.actor,
        payload=payload,
        call=_call(request, "propose_test_design"),
    )


@router.get(
    "/change-sets/{change_set_id}",
    response_model=MCPControlledWriteResponse,
)
async def get_change_set(
    change_set_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MCPControlledWriteEnvelope:
    return await MCPControlledWriteService(session).get_for_user(
        actor=current_user, change_set_id=change_set_id
    )


@router.post(
    "/change-sets/{change_set_id}/approve",
    response_model=MCPControlledWriteResponse,
)
async def approve_change_set(
    change_set_id: UUID,
    payload: MCPManualApprovalCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MCPControlledWriteEnvelope:
    return await MCPControlledWriteService(session).approve(
        actor=current_user,
        change_set_id=change_set_id,
        payload=payload,
    )


@router.post(
    "/change-sets/{change_set_id}/items/{item_id}/{decision}",
    response_model=MCPControlledWriteResponse,
)
async def review_change_item(
    change_set_id: UUID,
    item_id: UUID,
    decision: Literal["accept", "reject"],
    payload: MCPControlledWriteReview,
    session: SessionDependency,
    current_user: CurrentUser,
) -> MCPControlledWriteEnvelope:
    return await MCPControlledWriteService(session).review_item(
        actor=current_user,
        change_set_id=change_set_id,
        item_id=item_id,
        decision=decision,
        payload=payload,
    )


def _call(request: Request, operation: str) -> MCPReadCall:
    client_version = request.headers.get("x-mcp-client-version", "unknown")
    if _CLIENT_VERSION_PATTERN.fullmatch(client_version) is None:
        client_version = "unknown"
    return MCPReadCall(
        operation=operation,
        call_type=MCPCallType.TOOL,
        input_schema_hash=input_schema_hash(f"write:{operation}"),
        client_version=client_version,
    )
