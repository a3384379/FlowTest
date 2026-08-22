from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.domain.api_assets import (
    APIAssertionSpec,
    APIVersionSpec,
    ExtractionRuleSpec,
    HttpMethod,
    QueryParameterSpec,
)
from app.schemas.api_assets import (
    APIDefinitionCreate,
    APIDefinitionResponse,
    APIDefinitionUpdate,
    APIDetailResponse,
    APIVersionInput,
    APIVersionResponse,
    EnvironmentCreate,
    EnvironmentResponse,
    EnvironmentUpdate,
    PreviewRequest,
    PreviewResponse,
    ProjectConfigurationResponse,
    ProjectConfigurationUpdate,
    ResolvedHeaderResponse,
    ResolvedVariableResponse,
    SecretMetadata,
    SecretWrite,
)
from app.schemas.common import Page
from app.services.api_assets import APIAssetService

router = APIRouter(prefix="/projects/{project_id}")


@router.get("/configuration", response_model=ProjectConfigurationResponse)
async def get_project_configuration(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectConfigurationResponse:
    variables, headers = await APIAssetService(session).get_project_configuration(
        actor=current_user, project_id=project_id
    )
    return ProjectConfigurationResponse(project_id=project_id, variables=variables, headers=headers)


@router.put("/configuration", response_model=ProjectConfigurationResponse)
async def update_project_configuration(
    project_id: UUID,
    payload: ProjectConfigurationUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProjectConfigurationResponse:
    variables, headers = await APIAssetService(session).update_project_configuration(
        actor=current_user,
        project_id=project_id,
        variables=payload.variables,
        headers=payload.headers,
    )
    return ProjectConfigurationResponse(project_id=project_id, variables=variables, headers=headers)


@router.get("/environments", response_model=list[EnvironmentResponse])
async def list_environments(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[EnvironmentResponse]:
    environments = await APIAssetService(session).list_environments(
        actor=current_user, project_id=project_id
    )
    return [EnvironmentResponse.model_validate(environment) for environment in environments]


@router.post(
    "/environments",
    response_model=EnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment(
    project_id: UUID,
    payload: EnvironmentCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EnvironmentResponse:
    environment = await APIAssetService(session).create_environment(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        base_url=str(payload.base_url),
        variables=payload.variables,
        headers=payload.headers,
    )
    return EnvironmentResponse.model_validate(environment)


@router.patch("/environments/{environment_id}", response_model=EnvironmentResponse)
async def update_environment(
    project_id: UUID,
    environment_id: UUID,
    payload: EnvironmentUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EnvironmentResponse:
    environment = await APIAssetService(session).update_environment(
        actor=current_user,
        project_id=project_id,
        environment_id=environment_id,
        name=payload.name,
        base_url=str(payload.base_url) if payload.base_url is not None else None,
        variables=payload.variables,
        headers=payload.headers,
    )
    return EnvironmentResponse.model_validate(environment)


@router.get("/secrets", response_model=list[SecretMetadata])
async def list_secrets(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[SecretMetadata]:
    secrets = await APIAssetService(session).list_secrets(actor=current_user, project_id=project_id)
    return [SecretMetadata.model_validate(secret) for secret in secrets]


@router.put("/secrets", response_model=SecretMetadata)
async def write_secret(
    project_id: UUID,
    payload: SecretWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SecretMetadata:
    secret = await APIAssetService(session).write_secret(
        actor=current_user,
        project_id=project_id,
        environment_id=payload.environment_id,
        name=payload.name,
        value=payload.value,
    )
    return SecretMetadata.model_validate(secret)


@router.get("/apis", response_model=Page[APIDefinitionResponse])
async def list_api_definitions(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    method: HttpMethod | None = None,
) -> Page[APIDefinitionResponse]:
    definitions, total = await APIAssetService(session).list_definitions(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
        search=search,
        method=method.value if method is not None else None,
    )
    return Page(
        items=[APIDefinitionResponse.model_validate(item) for item in definitions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/apis",
    response_model=APIDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_definition(
    project_id: UUID,
    payload: APIDefinitionCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> APIDetailResponse:
    definition, version = await APIAssetService(session).create_definition(
        actor=current_user,
        project_id=project_id,
        folder_id=payload.folder_id,
        name=payload.name,
        description=payload.description,
        request=_version_spec(payload.request),
    )
    return APIDetailResponse(
        definition=APIDefinitionResponse.model_validate(definition),
        version=APIVersionResponse.model_validate(version),
    )


@router.get("/apis/{definition_id}", response_model=APIDetailResponse)
async def get_api_definition(
    project_id: UUID,
    definition_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    version: int | None = Query(default=None, ge=1),
) -> APIDetailResponse:
    definition, api_version = await APIAssetService(session).get_detail(
        actor=current_user,
        project_id=project_id,
        definition_id=definition_id,
        version=version,
    )
    return APIDetailResponse(
        definition=APIDefinitionResponse.model_validate(definition),
        version=APIVersionResponse.model_validate(api_version),
    )


@router.patch("/apis/{definition_id}", response_model=APIDefinitionResponse)
async def update_api_definition(
    project_id: UUID,
    definition_id: UUID,
    payload: APIDefinitionUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> APIDefinitionResponse:
    definition = await APIAssetService(session).update_definition(
        actor=current_user,
        project_id=project_id,
        definition_id=definition_id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        change_folder="folder_id" in payload.model_fields_set,
    )
    return APIDefinitionResponse.model_validate(definition)


@router.get("/apis/{definition_id}/versions", response_model=list[APIVersionResponse])
async def list_api_versions(
    project_id: UUID,
    definition_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[APIVersionResponse]:
    versions = await APIAssetService(session).list_versions(
        actor=current_user,
        project_id=project_id,
        definition_id=definition_id,
    )
    return [APIVersionResponse.model_validate(version) for version in versions]


@router.post(
    "/apis/{definition_id}/versions",
    response_model=APIVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_version(
    project_id: UUID,
    definition_id: UUID,
    payload: APIVersionInput,
    session: SessionDependency,
    current_user: CurrentUser,
) -> APIVersionResponse:
    version = await APIAssetService(session).create_version(
        actor=current_user,
        project_id=project_id,
        definition_id=definition_id,
        request=_version_spec(payload),
    )
    return APIVersionResponse.model_validate(version)


@router.post("/apis/{definition_id}/preview", response_model=PreviewResponse)
async def preview_api_request(
    project_id: UUID,
    definition_id: UUID,
    payload: PreviewRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> PreviewResponse:
    preview = await APIAssetService(session).preview(
        actor=current_user,
        project_id=project_id,
        definition_id=definition_id,
        environment_id=payload.environment_id,
        runtime_variables=payload.runtime_variables,
        runtime_headers=payload.runtime_headers,
        body_override=payload.body_override,
        use_body_override=payload.use_body_override,
        query_parameters_override=(
            tuple(
                QueryParameterSpec(name=item.name, value=item.value, enabled=item.enabled)
                for item in payload.query_parameters_override
            )
            if payload.query_parameters_override is not None
            else None
        ),
        headers_override=payload.headers_override,
        version_number=payload.version,
    )
    return PreviewResponse(
        method=preview.method,
        url=preview.url,
        headers=[ResolvedHeaderResponse.model_validate(header) for header in preview.headers],
        body=preview.body,
        variables=[
            ResolvedVariableResponse.model_validate(variable) for variable in preview.variables
        ],
    )


def _version_spec(payload: APIVersionInput) -> APIVersionSpec:
    return APIVersionSpec(
        method=payload.method,
        path=payload.path,
        query_parameters=tuple(
            QueryParameterSpec(name=item.name, value=item.value, enabled=item.enabled)
            for item in payload.query_parameters
        ),
        headers=payload.headers,
        body_kind=payload.body_kind,
        body=payload.body,
        auth_kind=payload.auth.kind,
        auth_config=payload.auth.values,
        extraction_rules=tuple(
            ExtractionRuleSpec(name=item.name, kind=item.kind, expression=item.expression)
            for item in payload.extraction_rules
        ),
        assertions=tuple(
            APIAssertionSpec(
                kind=item.kind.value,
                operator=item.operator.value,
                target=item.target,
                expected=item.expected,
            )
            for item in payload.assertions
        ),
    )
