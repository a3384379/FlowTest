from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.composition import build_external_credential_store
from app.domain.protocols import ProtocolKind
from app.schemas.common import Page
from app.schemas.protocols import (
    GraphQLDebugRequest,
    GraphQLErrorLocationRequest,
    GraphQLSchemaCreate,
    GrpcDebugRequest,
    GrpcDescriptorCreate,
    GrpcReflectionCreate,
    ProtocolDebugResponse,
    ProtocolStructureLocation,
    ProtocolStructureResponse,
    ProtocolStructureView,
    SchemaArtifactResponse,
)
from app.services.grpc_reflection import GrpcReflectionService
from app.services.protocol_assets import ProtocolAssetService
from app.services.protocol_debug import ProtocolDebugService

router = APIRouter()


@router.get("/protocol-assets/{artifact_id}/structure", response_model=ProtocolStructureResponse)
async def inspect_protocol_structure(
    artifact_id: UUID,
    project_id: UUID,
    protocol: Literal["graphql", "grpc"],
    session: SessionDependency,
    current_user: CurrentUser,
    node: str = Query(default="root", min_length=1, max_length=1024),
    offset: int = Query(default=0, ge=0, le=50000),
    limit: int = Query(default=25, ge=1, le=100),
) -> ProtocolStructureResponse:
    artifact, view = await ProtocolAssetService(session).structure(
        actor=current_user,
        project_id=project_id,
        artifact_id=artifact_id,
        protocol=ProtocolKind(protocol),
        node=node,
        offset=offset,
        limit=limit,
    )
    return ProtocolStructureResponse(
        artifact_id=artifact.id,
        project_id=artifact.project_id,
        protocol=protocol,
        version=artifact.version,
        content_sha256=artifact.content_sha256,
        view=ProtocolStructureView.model_validate(view),
    )


@router.post(
    "/graphql/schemas/{artifact_id}/locate-error", response_model=ProtocolStructureLocation
)
async def locate_graphql_error(
    artifact_id: UUID,
    payload: GraphQLErrorLocationRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProtocolStructureLocation:
    artifact, node = await ProtocolAssetService(session).locate_graphql_error(
        actor=current_user, artifact_id=artifact_id, payload=payload
    )
    return ProtocolStructureLocation(
        artifact_id=artifact.id,
        project_id=artifact.project_id,
        version=artifact.version,
        content_sha256=artifact.content_sha256,
        node=node,
    )


@router.get("/graphql/schemas", response_model=Page[SchemaArtifactResponse])
async def list_graphql_schemas(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[SchemaArtifactResponse]:
    items, total = await ProtocolAssetService(session).list(
        actor=current_user,
        project_id=project_id,
        protocol=ProtocolKind.GRAPHQL,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[SchemaArtifactResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/graphql/schemas/{artifact_id}", response_model=SchemaArtifactResponse)
async def get_graphql_schema(
    artifact_id: UUID,
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SchemaArtifactResponse:
    artifact = await ProtocolAssetService(session).get(
        actor=current_user,
        project_id=project_id,
        artifact_id=artifact_id,
        protocol=ProtocolKind.GRAPHQL,
    )
    return SchemaArtifactResponse.model_validate(artifact)


@router.post(
    "/graphql/schemas",
    response_model=SchemaArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_graphql_schema(
    payload: GraphQLSchemaCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SchemaArtifactResponse:
    artifact = await ProtocolAssetService(session).create_graphql(
        actor=current_user,
        payload=payload,
    )
    return SchemaArtifactResponse.model_validate(artifact)


@router.get("/grpc/descriptors", response_model=Page[SchemaArtifactResponse])
async def list_grpc_descriptors(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[SchemaArtifactResponse]:
    items, total = await ProtocolAssetService(session).list(
        actor=current_user,
        project_id=project_id,
        protocol=ProtocolKind.GRPC,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[SchemaArtifactResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/grpc/descriptors/{artifact_id}", response_model=SchemaArtifactResponse)
async def get_grpc_descriptor(
    artifact_id: UUID,
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SchemaArtifactResponse:
    artifact = await ProtocolAssetService(session).get(
        actor=current_user,
        project_id=project_id,
        artifact_id=artifact_id,
        protocol=ProtocolKind.GRPC,
    )
    return SchemaArtifactResponse.model_validate(artifact)


@router.post(
    "/grpc/descriptors",
    response_model=SchemaArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_grpc_descriptor(
    payload: GrpcDescriptorCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SchemaArtifactResponse:
    artifact = await ProtocolAssetService(session).create_grpc(
        actor=current_user,
        payload=payload,
    )
    return SchemaArtifactResponse.model_validate(artifact)


@router.post(
    "/grpc/descriptors/reflection",
    response_model=SchemaArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_grpc_reflection(
    payload: GrpcReflectionCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SchemaArtifactResponse:
    artifact = await GrpcReflectionService(
        session,
        external_secrets=build_external_credential_store(),
    ).import_descriptor(actor=current_user, payload=payload)
    return SchemaArtifactResponse.model_validate(artifact)


@router.post("/graphql/execute", response_model=ProtocolDebugResponse)
async def execute_graphql(
    payload: GraphQLDebugRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProtocolDebugResponse:
    result = await ProtocolDebugService(
        session,
        external_secrets=build_external_credential_store(),
    ).execute_graphql(actor=current_user, payload=payload)
    schema_version, schema_hash = _output_contract(result.output)
    return ProtocolDebugResponse(
        output=result.output,
        schema_id=payload.schema_id,
        schema_version=schema_version,
        schema_hash=schema_hash,
        duration_ms=result.duration_ms,
    )


@router.post("/grpc/execute", response_model=ProtocolDebugResponse)
async def execute_grpc(
    payload: GrpcDebugRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ProtocolDebugResponse:
    result = await ProtocolDebugService(
        session,
        external_secrets=build_external_credential_store(),
    ).execute_grpc(actor=current_user, payload=payload)
    schema_version, schema_hash = _output_contract(result.output)
    return ProtocolDebugResponse(
        output=result.output,
        schema_id=payload.descriptor_id,
        schema_version=schema_version,
        schema_hash=schema_hash,
        duration_ms=result.duration_ms,
    )


def _output_contract(output: object) -> tuple[int, str]:
    if not isinstance(output, dict):
        raise RuntimeError("Protocol runner returned an invalid output contract")
    version = output.get("schema_version")
    schema_hash = output.get("schema_hash")
    if not isinstance(version, int) or not isinstance(schema_hash, str):
        raise RuntimeError("Protocol runner returned an invalid output contract")
    return version, schema_hash
