from fastapi import APIRouter, Request

from app.api.dependencies import MCPConnectionCurrent, SessionDependency
from app.schemas.mcp_connection import MCPConnectionRequest, MCPConnectionResponse
from app.services.mcp_connection import MCPConnectionService

router = APIRouter(prefix="/mcp")


@router.post("/connection", response_model=MCPConnectionResponse)
async def inspect_connection(
    payload: MCPConnectionRequest,
    request: Request,
    session: SessionDependency,
    principal: MCPConnectionCurrent,
) -> MCPConnectionResponse:
    return await MCPConnectionService(session).inspect(
        account=principal.account,
        payload=payload,
        client_version=request.headers.get("x-mcp-client-version", "unknown"),
    )
