from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.config import settings
from app.core.errors import AppError
from app.importers.contracts import ImportSourceType
from app.schemas.common import Page
from app.schemas.imports import ImportMergeRequest, ImportRunResponse
from app.services.imports import ImportService

router = APIRouter(prefix="/projects/{project_id}/imports")


@router.post("", response_model=ImportRunResponse, status_code=status.HTTP_201_CREATED)
async def import_api_document(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    document: Annotated[UploadFile, File()],
    source_type: Annotated[ImportSourceType, Form()] = ImportSourceType.AUTO,
    source_name: Annotated[str | None, Form(max_length=255)] = None,
) -> ImportRunResponse:
    content = await document.read(settings.artifact_limit_bytes + 1)
    if len(content) > settings.artifact_limit_bytes:
        raise AppError(code="IMPORT_TOO_LARGE", message="导入文件超过 50 MB 上限", status_code=413)
    run = await ImportService(session).import_document(
        actor=current_user,
        project_id=project_id,
        source_name=source_name or document.filename or "import-document",
        source_type=source_type,
        content=content,
    )
    return ImportRunResponse.model_validate(run)


@router.post("/preview", response_model=ImportRunResponse, status_code=status.HTTP_201_CREATED)
async def preview_api_document(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    document: Annotated[UploadFile, File()],
    source_type: Annotated[ImportSourceType, Form()] = ImportSourceType.AUTO,
    source_name: Annotated[str | None, Form(max_length=255)] = None,
) -> ImportRunResponse:
    content = await document.read(settings.artifact_limit_bytes + 1)
    if len(content) > settings.artifact_limit_bytes:
        raise AppError(code="IMPORT_TOO_LARGE", message="导入文件超过 50 MB 上限", status_code=413)
    run = await ImportService(session).preview_document(
        actor=current_user,
        project_id=project_id,
        source_name=source_name or document.filename or "import-document",
        source_type=source_type,
        content=content,
    )
    return ImportRunResponse.model_validate(run)


@router.post("/{run_id}/merge", response_model=ImportRunResponse)
async def merge_api_import(
    project_id: UUID,
    run_id: UUID,
    payload: ImportMergeRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ImportRunResponse:
    run = await ImportService(session).merge_preview(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
        selected_keys=payload.selected_keys,
    )
    return ImportRunResponse.model_validate(run)


@router.get("", response_model=Page[ImportRunResponse])
async def list_import_runs(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ImportRunResponse]:
    runs, total = await ImportService(session).list_runs(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[ImportRunResponse.model_validate(run) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
    )
