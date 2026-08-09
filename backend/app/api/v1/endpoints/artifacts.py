from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.config import settings
from app.core.errors import AppError
from app.schemas.artifacts import ArtifactResponse
from app.schemas.common import Page
from app.services.artifacts import ArtifactService

router = APIRouter(prefix="/projects/{project_id}/files")


@router.post("", response_model=ArtifactResponse, status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> ArtifactResponse:
    content = await file.read(settings.artifact_limit_bytes + 1)
    if len(content) > settings.artifact_limit_bytes:
        raise AppError(code="ARTIFACT_TOO_LARGE", message="文件超过 50 MB 上限", status_code=413)
    artifact = await ArtifactService(session).upload(
        actor=current_user,
        project_id=project_id,
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )
    return ArtifactResponse.model_validate(artifact)


@router.get("", response_model=Page[ArtifactResponse])
async def list_artifacts(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ArtifactResponse]:
    artifacts, total = await ArtifactService(session).list_artifacts(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[ArtifactResponse.model_validate(artifact) for artifact in artifacts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{artifact_id}")
async def download_artifact(
    project_id: UUID,
    artifact_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> Response:
    loaded = await ArtifactService(session).download(
        actor=current_user,
        project_id=project_id,
        artifact_id=artifact_id,
    )
    filename = quote(loaded.artifact.filename)
    return Response(
        loaded.content,
        media_type=loaded.artifact.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
