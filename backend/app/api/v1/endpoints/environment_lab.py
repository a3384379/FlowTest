from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response, status

from app.api.dependencies import CurrentUser, EnvironmentQueue, SessionDependency
from app.schemas.common import Page
from app.schemas.environment_lab import (
    EnvironmentInstanceResponse,
    EnvironmentProvisionRequest,
    EnvironmentTemplateCreate,
    EnvironmentTemplateVersionCreate,
    EnvironmentTemplateVersionResponse,
)
from app.services.environment_lab import (
    EnvironmentInstanceService,
    EnvironmentTemplateService,
    EnvironmentTemplateView,
)

router = APIRouter()


@router.get(
    "/environment-templates",
    response_model=Page[EnvironmentTemplateVersionResponse],
)
async def list_environment_templates(
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[EnvironmentTemplateVersionResponse]:
    versions = await EnvironmentTemplateService(session).list_versions(actor=current_user)
    start = (page - 1) * page_size
    selected = versions[start : start + page_size]
    return Page(
        items=[_template_response(view) for view in selected],
        total=len(versions),
        page=page,
        page_size=page_size,
    )


@router.post(
    "/environment-templates",
    response_model=EnvironmentTemplateVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_environment_template(
    payload: EnvironmentTemplateCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EnvironmentTemplateVersionResponse:
    view = await EnvironmentTemplateService(session).register(
        actor=current_user,
        payload=payload,
    )
    return _template_response(view)


@router.post(
    "/environment-templates/{template_id}/versions",
    response_model=EnvironmentTemplateVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment_template_version(
    template_id: UUID,
    payload: EnvironmentTemplateVersionCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EnvironmentTemplateVersionResponse:
    view = await EnvironmentTemplateService(session).create_version(
        actor=current_user,
        template_id=template_id,
        payload=payload,
    )
    return _template_response(view)


@router.post(
    "/environment-templates/{template_id}/disable",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disable_environment_template(
    template_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> Response:
    await EnvironmentTemplateService(session).disable(
        actor=current_user,
        template_id=template_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/environment-instances",
    response_model=EnvironmentInstanceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def provision_environment(
    project_id: UUID,
    payload: EnvironmentProvisionRequest,
    session: SessionDependency,
    current_user: CurrentUser,
    dispatcher: EnvironmentQueue,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> EnvironmentInstanceResponse:
    instance = await EnvironmentInstanceService(session).queue(
        actor=current_user,
        project_id=project_id,
        payload=payload,
        idempotency_key=idempotency_key,
        dispatcher=dispatcher,
    )
    return EnvironmentInstanceResponse.model_validate(instance)


@router.get(
    "/projects/{project_id}/environment-instances",
    response_model=Page[EnvironmentInstanceResponse],
)
async def list_environment_instances(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[EnvironmentInstanceResponse]:
    instances, total = await EnvironmentInstanceService(session).list_instances(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[EnvironmentInstanceResponse.model_validate(instance) for instance in instances],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/projects/{project_id}/environment-instances/{instance_id}",
    response_model=EnvironmentInstanceResponse,
)
async def get_environment_instance(
    project_id: UUID,
    instance_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EnvironmentInstanceResponse:
    instance = await EnvironmentInstanceService(session).get(
        actor=current_user,
        project_id=project_id,
        instance_id=instance_id,
    )
    return EnvironmentInstanceResponse.model_validate(instance)


@router.post(
    "/projects/{project_id}/environment-instances/{instance_id}/cleanup",
    response_model=EnvironmentInstanceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cleanup_environment_instance(
    project_id: UUID,
    instance_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    dispatcher: EnvironmentQueue,
) -> EnvironmentInstanceResponse:
    instance = await EnvironmentInstanceService(session).cancel(
        actor=current_user,
        project_id=project_id,
        instance_id=instance_id,
        dispatcher=dispatcher,
    )
    return EnvironmentInstanceResponse.model_validate(instance)


def _template_response(view: EnvironmentTemplateView) -> EnvironmentTemplateVersionResponse:
    return EnvironmentTemplateVersionResponse(
        id=view.version.id,
        template_id=view.template.id,
        template_key=view.template.template_key,
        display_name=view.template.display_name,
        description=view.template.description,
        status=view.template.status,
        version=view.version.version,
        manifest=view.manifest,
        manifest_sha256=view.version.manifest_sha256,
        signature=view.version.signature,
        signature_algorithm=view.version.signature_algorithm,
        signed_by_id=view.version.signed_by_id,
        created_at=view.version.created_at,
    )
