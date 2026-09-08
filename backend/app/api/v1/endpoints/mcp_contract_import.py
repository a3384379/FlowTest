"""HTTP delivery adapters for the S61C governed contract import tools."""

from typing import Annotated

from fastapi import APIRouter, Header

from app.api.dependencies import (
    ImportDocumentFetcherDependency,
    MCPContractImportCurrent,
    SessionDependency,
)
from app.schemas.mcp_contract_import import (
    MCPCommitContractImportRequest,
    MCPCommitContractImportResponse,
    MCPPreviewContractImportRequest,
    MCPPreviewContractImportResponse,
)
from app.services.idempotency import require_idempotency_key
from app.services.mcp_contract_import import MCPContractImportService

router = APIRouter(prefix="/mcp/contracts")
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.post("/preview", response_model=MCPPreviewContractImportResponse)
async def preview_contract_import(
    payload: MCPPreviewContractImportRequest,
    session: SessionDependency,
    principal: MCPContractImportCurrent,
    document_fetcher: ImportDocumentFetcherDependency,
) -> MCPPreviewContractImportResponse:
    return await MCPContractImportService(session, document_fetcher=document_fetcher).preview(
        actor=principal.actor,
        account=principal.account,
        payload=payload,
    )


@router.post("/commit", response_model=MCPCommitContractImportResponse)
async def commit_contract_import(
    payload: MCPCommitContractImportRequest,
    session: SessionDependency,
    principal: MCPContractImportCurrent,
    idempotency_key: IdempotencyHeader = None,
) -> MCPCommitContractImportResponse:
    require_idempotency_key(idempotency_key)
    return await MCPContractImportService(session).commit(
        actor=principal.actor,
        account=principal.account,
        payload=payload,
    )
