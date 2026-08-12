from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.domain.event_protocols import EventSourceKind
from app.schemas.common import Page
from app.schemas.event_protocols import (
    EventDebugResponse,
    EventSchemaCreate,
    EventSourceCreate,
    EventSourceResponse,
    KafkaConsumeDebugRequest,
    KafkaProduceDebugRequest,
    RegistrySchemaImport,
    WebSocketExchangeDebugRequest,
)
from app.schemas.protocols import SchemaArtifactResponse
from app.services.event_debug import EventDebugService
from app.services.event_sources import EventSourceService

router = APIRouter()


@router.get("/event-sources", response_model=Page[EventSourceResponse])
async def list_event_sources(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    kind: EventSourceKind | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[EventSourceResponse]:
    items, total = await EventSourceService(session).list_sources(
        actor=current_user,
        project_id=project_id,
        kind=kind,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[EventSourceResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/event-sources",
    response_model=EventSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_event_source(
    payload: EventSourceCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EventSourceResponse:
    source = await EventSourceService(session).create(actor=current_user, payload=payload)
    return EventSourceResponse.model_validate(source)


@router.get(
    "/event-sources/{source_id}/schemas",
    response_model=Page[SchemaArtifactResponse],
)
async def list_event_schemas(
    source_id: UUID,
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[SchemaArtifactResponse]:
    service = EventSourceService(session)
    source = await service.get(
        actor=current_user,
        project_id=project_id,
        source_id=source_id,
        kind=EventSourceKind.KAFKA,
    )
    items, total = await service.list_schemas(
        actor=current_user,
        source=source,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[SchemaArtifactResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/event-sources/{source_id}/schemas",
    response_model=SchemaArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_event_schema(
    source_id: UUID,
    project_id: UUID,
    payload: EventSchemaCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SchemaArtifactResponse:
    service = EventSourceService(session)
    source = await service.get(
        actor=current_user,
        project_id=project_id,
        source_id=source_id,
        kind=EventSourceKind.KAFKA,
        editing=True,
    )
    artifact = await service.create_schema(actor=current_user, source=source, payload=payload)
    return SchemaArtifactResponse.model_validate(artifact)


@router.post(
    "/event-sources/{source_id}/schemas/import",
    response_model=SchemaArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_registry_schema(
    source_id: UUID,
    project_id: UUID,
    payload: RegistrySchemaImport,
    session: SessionDependency,
    current_user: CurrentUser,
) -> SchemaArtifactResponse:
    source = await EventSourceService(session).get(
        actor=current_user,
        project_id=project_id,
        source_id=source_id,
        kind=EventSourceKind.KAFKA,
        editing=True,
    )
    artifact = await EventDebugService(session).import_registry_schema(
        actor=current_user,
        source=source,
        payload=payload,
    )
    return SchemaArtifactResponse.model_validate(artifact)


@router.post(
    "/event-sources/{source_id}/kafka/produce",
    response_model=EventDebugResponse,
)
async def produce_kafka_message(
    source_id: UUID,
    payload: KafkaProduceDebugRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EventDebugResponse:
    result = await EventDebugService(session).execute_kafka_produce(
        actor=current_user,
        source_id=source_id,
        payload=payload,
    )
    return EventDebugResponse(output=result.output, duration_ms=result.duration_ms)


@router.post(
    "/event-sources/{source_id}/kafka/consume",
    response_model=EventDebugResponse,
)
async def consume_kafka_messages(
    source_id: UUID,
    payload: KafkaConsumeDebugRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EventDebugResponse:
    result = await EventDebugService(session).execute_kafka_consume(
        actor=current_user,
        source_id=source_id,
        payload=payload,
    )
    return EventDebugResponse(output=result.output, duration_ms=result.duration_ms)


@router.post(
    "/event-sources/{source_id}/websocket/exchange",
    response_model=EventDebugResponse,
)
async def exchange_websocket_message(
    source_id: UUID,
    payload: WebSocketExchangeDebugRequest,
    session: SessionDependency,
    current_user: CurrentUser,
) -> EventDebugResponse:
    result = await EventDebugService(session).execute_websocket_exchange(
        actor=current_user,
        source_id=source_id,
        payload=payload,
    )
    return EventDebugResponse(output=result.output, duration_ms=result.duration_ms)
