"""Thin HTTP adapters for the S61B organization bootstrap tools."""

from typing import Annotated

from fastapi import APIRouter, Header

from app.api.dependencies import MCPBootstrapCurrent, SessionDependency
from app.schemas.mcp_bootstrap import (
    MCPEnsureEnvironmentRequest,
    MCPEnsureEnvironmentResponse,
    MCPEnsureProjectRequest,
    MCPEnsureProjectResponse,
    MCPEnsureServiceTargetRequest,
    MCPEnsureServiceTargetResponse,
)
from app.services.mcp_bootstrap import MCPBootstrapService

router = APIRouter(prefix="/mcp/bootstrap")
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.post("/projects/ensure", response_model=MCPEnsureProjectResponse)
async def ensure_project(
    payload: MCPEnsureProjectRequest,
    session: SessionDependency,
    principal: MCPBootstrapCurrent,
    idempotency_key: IdempotencyHeader = None,
) -> MCPEnsureProjectResponse:
    return await MCPBootstrapService(session).ensure_project(
        actor=principal.actor,
        account=principal.account,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/environments/ensure", response_model=MCPEnsureEnvironmentResponse)
async def ensure_test_environment(
    payload: MCPEnsureEnvironmentRequest,
    session: SessionDependency,
    principal: MCPBootstrapCurrent,
    idempotency_key: IdempotencyHeader = None,
) -> MCPEnsureEnvironmentResponse:
    return await MCPBootstrapService(session).ensure_test_environment(
        actor=principal.actor,
        account=principal.account,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/service-targets/ensure", response_model=MCPEnsureServiceTargetResponse)
async def ensure_service_target(
    payload: MCPEnsureServiceTargetRequest,
    session: SessionDependency,
    principal: MCPBootstrapCurrent,
    idempotency_key: IdempotencyHeader = None,
) -> MCPEnsureServiceTargetResponse:
    return await MCPBootstrapService(session).ensure_service_target(
        actor=principal.actor,
        account=principal.account,
        payload=payload,
        idempotency_key=idempotency_key,
    )
