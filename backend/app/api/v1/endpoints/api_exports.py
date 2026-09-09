from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CurrentUser, SessionDependency
from app.services.api_exports import APIExportFormat, APIExportService

router = APIRouter(prefix="/projects/{project_id}/exports")


@router.get("/apis")
async def export_apis(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    export_format: Annotated[APIExportFormat, Query(alias="format")],
) -> Response:
    document = await APIExportService(session).export(
        actor=current_user,
        project_id=project_id,
        export_format=export_format,
    )
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={"Content-Disposition": attachment_disposition(document.filename)},
    )


def attachment_disposition(filename: str) -> str:
    fallback = "".join(
        character if character.isascii() and (character.isalnum() or character in "._-") else "_"
        for character in filename
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
