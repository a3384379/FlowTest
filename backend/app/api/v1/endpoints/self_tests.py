"""Thin product and deployment-authenticated self-test adapters."""

from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.api.dependencies import CurrentUser, SessionDependency, TestPlanQueue, bearer_scheme
from app.core.self_tests import SelfTestPrincipal, SelfTestSettings, get_self_test_settings
from app.schemas.self_tests import (
    AgentArtifactUpload,
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    AgentTaskList,
    AgentTaskResponse,
    ArtifactReference,
    BatchCreate,
    BatchResponse,
    BindingResponse,
    ExecuteMaterializedRequest,
    GenerationBatchCreate,
    GenerationProgress,
    GenerationSummary,
    InstallationCreate,
    InstallationPreviewRequest,
    InstallationPreviewResponse,
    InstallationReceipt,
    InstallationResponse,
    LeaseClaim,
    LeaseRequest,
    MaterializedReceipt,
    ScenarioExecutionRelation,
    ScenarioId,
    ScenarioResultResponse,
    SelfTestPage,
    TemplateResponse,
    VerificationReceipt,
)
from app.schemas.test_design import MCPControlledWriteCreate, MCPControlledWriteEnvelope
from app.services.self_test_access import authenticate_agent, self_test_error
from app.services.self_test_agents import SelfTestAgentService
from app.services.self_tests import SelfTestService

Config = Annotated[SelfTestSettings, Depends(get_self_test_settings)]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
router = APIRouter(prefix="/projects/{project_id}/self-tests")
agent_router = APIRouter(prefix="/agent/projects/{project_id}/self-tests")
verification_router = APIRouter(prefix="/ci/projects/{project_id}/self-test-runs")


async def external_principal(
    config: Config,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> SelfTestPrincipal:
    if credentials is None:
        raise self_test_error("SELFTEST_AGENT_UNAUTHORIZED", "需要部署授权的外部身份", 401)
    return authenticate_agent(credentials.credentials, config)


Agent = Annotated[SelfTestPrincipal, Depends(external_principal)]


@router.get("/templates", response_model=SelfTestPage[TemplateResponse])
async def templates(
    project_id: UUID, current_user: CurrentUser, session: SessionDependency, config: Config
) -> SelfTestPage[TemplateResponse]:
    return await SelfTestService(session, config).templates(current_user, project_id)


@router.get("/bindings", response_model=SelfTestPage[BindingResponse])
async def bindings(
    project_id: UUID, current_user: CurrentUser, session: SessionDependency, config: Config
) -> SelfTestPage[BindingResponse]:
    return await SelfTestService(session, config).bindings(current_user, project_id)


@router.post("/installations/preview", response_model=InstallationPreviewResponse)
async def preview(
    project_id: UUID,
    payload: InstallationPreviewRequest,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> InstallationPreviewResponse:
    return await SelfTestService(session, config).preview(current_user, project_id, payload)


@router.post("/installations", response_model=InstallationResponse, status_code=202)
async def install(
    project_id: UUID,
    payload: InstallationCreate,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
    idempotency_key: IdempotencyKey = None,
) -> InstallationResponse:
    return await SelfTestService(session, config).install(
        current_user, project_id, payload, idempotency_key
    )


@router.get("/installations/{installation_id}", response_model=InstallationResponse)
async def installation(
    project_id: UUID,
    installation_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> InstallationResponse:
    return await SelfTestService(session, config).installation(
        current_user, project_id, installation_id
    )


@router.get("/installations/{installation_id}/runs", response_model=SelfTestPage[BatchResponse])
async def list_runs(
    project_id: UUID,
    installation_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
    cursor: UUID | None = None,
    page_size: int = Query(default=50, ge=1, le=100),
) -> SelfTestPage[BatchResponse]:
    return await SelfTestService(session, config).list_batches(
        current_user, project_id, installation_id, cursor=cursor, page_size=page_size
    )


@router.post("/installations/{installation_id}/runs", response_model=BatchResponse, status_code=202)
async def fixed_run(
    project_id: UUID,
    installation_id: UUID,
    payload: BatchCreate,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
    idempotency_key: IdempotencyKey = None,
) -> BatchResponse:
    return await SelfTestService(session, config).create_batch(
        current_user, project_id, installation_id, payload, idempotency_key
    )


@router.post(
    "/installations/{installation_id}/generation-batches",
    response_model=BatchResponse,
    status_code=202,
)
async def generation_batch(
    project_id: UUID,
    installation_id: UUID,
    payload: GenerationBatchCreate,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
    idempotency_key: IdempotencyKey = None,
) -> BatchResponse:
    return await SelfTestService(session, config).create_batch(
        current_user, project_id, installation_id, payload, idempotency_key
    )


@router.get("/runs/{batch_id}", response_model=BatchResponse)
async def run(
    project_id: UUID,
    batch_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> BatchResponse:
    return await SelfTestService(session, config).batch(current_user, project_id, batch_id)


@router.get("/runs/{batch_id}/generation", response_model=GenerationSummary)
async def generation(
    project_id: UUID,
    batch_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> GenerationSummary:
    return await SelfTestService(session, config).generation(current_user, project_id, batch_id)


@router.get("/runs/{batch_id}/scenarios", response_model=SelfTestPage[ScenarioResultResponse])
async def scenarios(
    project_id: UUID,
    batch_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=50, ge=1, le=100),
    category: Literal["api", "engine", "mcp"] | None = None,
    verification: Literal["pending", "matched", "mismatched", "incomplete", "error", "unsupported"]
    | None = None,
    scenario_id: ScenarioId | None = None,
) -> SelfTestPage[ScenarioResultResponse]:
    return await SelfTestService(session, config).scenarios(
        current_user,
        project_id,
        batch_id,
        page=page,
        page_size=page_size,
        category=category,
        verification=verification,
        scenario_id=scenario_id,
    )


@router.get(
    "/runs/{batch_id}/scenarios/{scenario_id}/executions/{execution_id}",
    response_model=ScenarioExecutionRelation,
)
async def execution_relation(
    project_id: UUID,
    batch_id: UUID,
    scenario_id: str,
    execution_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> ScenarioExecutionRelation:
    return await SelfTestService(session, config).relation(
        current_user, project_id, batch_id, scenario_id, execution_id
    )


@router.post("/runs/{batch_id}/execute-materialized", response_model=BatchResponse, status_code=202)
async def execute(
    project_id: UUID,
    batch_id: UUID,
    payload: ExecuteMaterializedRequest,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
    queue: TestPlanQueue,
    idempotency_key: IdempotencyKey = None,
) -> BatchResponse:
    return await SelfTestService(session, config).execute(
        current_user, project_id, batch_id, payload, idempotency_key, queue
    )


@router.post("/runs/{batch_id}/cancel", response_model=BatchResponse)
async def cancel(
    project_id: UUID,
    batch_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> BatchResponse:
    return await SelfTestService(session, config).cancel(current_user, project_id, batch_id)


@router.get("/runs/{batch_id}/artifacts/{artifact_id}")
async def artifact(
    project_id: UUID,
    batch_id: UUID,
    artifact_id: UUID,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> Response:
    content = await SelfTestService(session, config).download(
        current_user, project_id, batch_id, artifact_id
    )
    return Response(
        content=content.content,
        media_type=content.artifact.content_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(content.artifact.filename)
        },
    )


@agent_router.post("/register", response_model=AgentRegistrationResponse)
async def register(
    project_id: UUID,
    payload: AgentRegistrationRequest,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> AgentRegistrationResponse:
    return await SelfTestAgentService(session, config).register(principal, project_id, payload)


@agent_router.get("/tasks", response_model=AgentTaskList)
async def tasks(
    project_id: UUID, principal: Agent, session: SessionDependency, config: Config
) -> AgentTaskList:
    return await SelfTestAgentService(session, config).tasks(principal, project_id)


@agent_router.post("/installations/{installation_id}/claim", response_model=AgentTaskResponse)
async def claim_installation(
    project_id: UUID,
    installation_id: UUID,
    payload: LeaseClaim,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> AgentTaskResponse:
    return await SelfTestAgentService(session, config).claim_installation(
        principal, project_id, installation_id, payload
    )


@agent_router.post("/installations/{installation_id}/lease", response_model=AgentTaskResponse)
async def renew_installation(
    project_id: UUID,
    installation_id: UUID,
    payload: LeaseRequest,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> AgentTaskResponse:
    return await SelfTestAgentService(session, config).renew_installation(
        principal, project_id, installation_id, payload
    )


@agent_router.post("/installations/{installation_id}/receipt", response_model=InstallationResponse)
async def installation_receipt(
    project_id: UUID,
    installation_id: UUID,
    payload: InstallationReceipt,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> InstallationResponse:
    return await SelfTestAgentService(session, config).installed(
        principal, project_id, installation_id, payload
    )


@agent_router.post("/runs/{batch_id}/claim", response_model=AgentTaskResponse)
async def claim_batch(
    project_id: UUID,
    batch_id: UUID,
    payload: LeaseClaim,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> AgentTaskResponse:
    return await SelfTestAgentService(session, config).claim_batch(
        principal, project_id, batch_id, payload
    )


@agent_router.post("/runs/{batch_id}/lease", response_model=AgentTaskResponse)
async def renew(
    project_id: UUID,
    batch_id: UUID,
    payload: LeaseRequest,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> AgentTaskResponse:
    return await SelfTestAgentService(session, config).renew(
        principal, project_id, batch_id, payload
    )


@agent_router.post("/runs/{batch_id}/generation", response_model=BatchResponse)
async def progress(
    project_id: UUID,
    batch_id: UUID,
    payload: GenerationProgress,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> BatchResponse:
    return await SelfTestAgentService(session, config).progress(
        principal, project_id, batch_id, payload
    )


@agent_router.post("/runs/{batch_id}/materialized", response_model=BatchResponse)
async def materialized(
    project_id: UUID,
    batch_id: UUID,
    payload: MaterializedReceipt,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> BatchResponse:
    return await SelfTestAgentService(session, config).materialized(
        principal, project_id, batch_id, payload
    )


@agent_router.post("/runs/{batch_id}/prepared", response_model=BatchResponse, status_code=202)
async def prepared(
    project_id: UUID,
    batch_id: UUID,
    payload: LeaseRequest,
    principal: Agent,
    session: SessionDependency,
    config: Config,
    queue: TestPlanQueue,
) -> BatchResponse:
    return await SelfTestAgentService(session, config).prepared(
        principal, project_id, batch_id, payload, queue
    )


@agent_router.post("/runs/{batch_id}/artifacts", response_model=ArtifactReference, status_code=201)
async def upload(
    project_id: UUID,
    batch_id: UUID,
    payload: AgentArtifactUpload,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> ArtifactReference:
    return await SelfTestAgentService(session, config).upload(
        principal, project_id, batch_id, payload
    )


@verification_router.post("/{batch_id}/verification", response_model=BatchResponse)
async def verification_receipt(
    project_id: UUID,
    batch_id: UUID,
    payload: VerificationReceipt,
    principal: Agent,
    session: SessionDependency,
    config: Config,
) -> BatchResponse:
    return await SelfTestAgentService(session, config).verification(
        principal, project_id, batch_id, payload
    )


@router.post(
    "/runs/{batch_id}/assisted-case-proposals",
    response_model=MCPControlledWriteEnvelope,
    status_code=202,
)
async def assisted_case_proposal(
    project_id: UUID,
    batch_id: UUID,
    payload: MCPControlledWriteCreate,
    current_user: CurrentUser,
    session: SessionDependency,
    config: Config,
) -> MCPControlledWriteEnvelope:
    return await SelfTestService(session, config).assisted_case_proposal(
        current_user, project_id, batch_id, payload
    )
