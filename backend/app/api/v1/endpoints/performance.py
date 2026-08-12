from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, PerformanceQueue, SessionDependency
from app.schemas.common import Page
from app.schemas.performance import (
    PerformanceGateEvaluationResponse,
    PerformanceRunResponse,
    PerformanceScenarioResponse,
    PerformanceScenarioVersionWrite,
    PerformanceScenarioWrite,
)
from app.services.performance import PerformanceRunService, PerformanceScenarioService

router = APIRouter()


@router.get(
    "/projects/{project_id}/performance-scenarios",
    response_model=Page[PerformanceScenarioResponse],
)
async def list_performance_scenarios(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[PerformanceScenarioResponse]:
    items, total = await PerformanceScenarioService(session).list_scenarios(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[PerformanceScenarioResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/performance-scenarios",
    response_model=PerformanceScenarioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_performance_scenario(
    project_id: UUID,
    payload: PerformanceScenarioWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> PerformanceScenarioResponse:
    scenario = await PerformanceScenarioService(session).create(
        actor=current_user,
        project_id=project_id,
        payload=payload,
    )
    return PerformanceScenarioResponse.model_validate(scenario)


@router.post(
    "/projects/{project_id}/performance-scenarios/{scenario_id}/versions",
    response_model=PerformanceScenarioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_performance_scenario_version(
    project_id: UUID,
    scenario_id: UUID,
    payload: PerformanceScenarioVersionWrite,
    session: SessionDependency,
    current_user: CurrentUser,
) -> PerformanceScenarioResponse:
    scenario = await PerformanceScenarioService(session).create_version(
        actor=current_user,
        project_id=project_id,
        scenario_id=scenario_id,
        payload=payload,
    )
    return PerformanceScenarioResponse.model_validate(scenario)


@router.post(
    "/projects/{project_id}/performance-scenarios/{scenario_id}/publish",
    response_model=PerformanceScenarioResponse,
)
async def publish_performance_scenario(
    project_id: UUID,
    scenario_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> PerformanceScenarioResponse:
    scenario = await PerformanceScenarioService(session).publish(
        actor=current_user,
        project_id=project_id,
        scenario_id=scenario_id,
    )
    return PerformanceScenarioResponse.model_validate(scenario)


@router.post(
    "/projects/{project_id}/performance-scenarios/{scenario_id}/runs",
    response_model=PerformanceRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_performance_scenario(
    project_id: UUID,
    scenario_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    dispatcher: PerformanceQueue,
) -> PerformanceRunResponse:
    run = await PerformanceRunService(session).queue(
        actor=current_user,
        project_id=project_id,
        scenario_id=scenario_id,
        dispatcher=dispatcher,
    )
    return PerformanceRunResponse.model_validate(run)


@router.get(
    "/projects/{project_id}/performance-runs",
    response_model=Page[PerformanceRunResponse],
)
async def list_performance_runs(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[PerformanceRunResponse]:
    service = PerformanceRunService(session)
    items, total = await service.list_runs(
        actor=current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[PerformanceRunResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/projects/{project_id}/performance-runs/{run_id}",
    response_model=PerformanceRunResponse,
)
async def get_performance_run(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> PerformanceRunResponse:
    run, evaluations = await PerformanceRunService(session).get(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
    )
    response = PerformanceRunResponse.model_validate(run)
    return response.model_copy(
        update={
            "gate_evaluations": [
                PerformanceGateEvaluationResponse.model_validate(item) for item in evaluations
            ]
        }
    )
