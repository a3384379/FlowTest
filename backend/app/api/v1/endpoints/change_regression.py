from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from app.api.dependencies import CurrentUser, SessionDependency, TestPlanQueue
from app.core.errors import AppError
from app.domain.tasking import ServiceTokenScope
from app.repositories.change_regression import ChangeRegressionBundle
from app.schemas.change_regression import (
    ChangeRegressionApproval,
    ChangeRegressionMissingTestResponse,
    ChangeRegressionReview,
    ChangeRegressionRunCreate,
    ChangeRegressionRunResponse,
    ChangeRegressionRunSummaryResponse,
    ChangeRegressionStageResponse,
)
from app.schemas.common import Page
from app.services.change_regression import ChangeRegressionService
from app.services.idempotency import IdempotencyService
from app.services.tasking import ServiceTokenService

router = APIRouter()


@router.post(
    "/ci/projects/{project_id}/change-regressions",
    response_model=ChangeRegressionRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ci_create_change_regression(
    project_id: UUID,
    payload: ChangeRegressionRunCreate,
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChangeRegressionRunResponse:
    identity = await ServiceTokenService(session).authenticate(
        raw_token=_bearer_token(authorization),
        project_id=project_id,
        required_scope=ServiceTokenScope.ANALYZE_CHANGE_REGRESSION,
    )

    async def start() -> ChangeRegressionRunResponse:
        bundle = await ChangeRegressionService(session).create(
            actor=identity.actor, project_id=project_id, payload=payload
        )
        return _response(bundle)

    response = await IdempotencyService(session).run(
        key=idempotency_key,
        project_id=project_id,
        actor_key=f"service-token:{identity.model.id}",
        operation="ci.change-regression.create",
        request_payload=payload.model_dump(mode="json"),
        action=start,
    )
    return ChangeRegressionRunResponse.model_validate(response)


@router.post(
    "/projects/{project_id}/change-regressions",
    response_model=ChangeRegressionRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_change_regression(
    project_id: UUID,
    payload: ChangeRegressionRunCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ChangeRegressionRunResponse:
    bundle = await ChangeRegressionService(session).create(
        actor=current_user, project_id=project_id, payload=payload
    )
    return _response(bundle)


@router.get(
    "/projects/{project_id}/change-regressions",
    response_model=Page[ChangeRegressionRunSummaryResponse],
)
async def list_change_regressions(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ChangeRegressionRunSummaryResponse]:
    items, total = await ChangeRegressionService(session).list(
        actor=current_user, project_id=project_id, page=page, page_size=page_size
    )
    return Page(
        items=[
            ChangeRegressionRunSummaryResponse(
                id=item.id,
                project_id=item.project_id,
                title=item.title,
                source_ref=item.source_ref,
                source_fingerprint=item.source_fingerprint,
                candidate_ref=item.candidate_ref,
                status=cast(
                    Literal[
                        "review_required",
                        "approved",
                        "queued",
                        "running",
                        "evidence_ready",
                        "passed",
                        "blocked",
                        "failed",
                    ],
                    item.status,
                ),
                impact_run_id=item.impact_run_id,
                test_plan_id=item.test_plan_id,
                test_plan_run_id=item.test_plan_run_id,
                release_policy_id=item.release_policy_id,
                change_set_id=item.change_set_id,
                release_decision_id=item.release_decision_id,
                selected_asset_count=len(item.selected_assets),
                missing_test_count=len(item.missing_tests),
                created_by_id=item.created_by_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/projects/{project_id}/change-regressions/{run_id}",
    response_model=ChangeRegressionRunResponse,
)
async def get_change_regression(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ChangeRegressionRunResponse:
    bundle = await ChangeRegressionService(session).get(
        actor=current_user, project_id=project_id, run_id=run_id
    )
    return _response(bundle)


@router.post(
    "/projects/{project_id}/change-regressions/{run_id}/change-set-items/{item_id}/{decision}",
    response_model=ChangeRegressionRunResponse,
)
async def review_change_regression_item(
    project_id: UUID,
    run_id: UUID,
    item_id: UUID,
    decision: Literal["accept", "reject"],
    payload: ChangeRegressionReview,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ChangeRegressionRunResponse:
    bundle = await ChangeRegressionService(session).review_item(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
        item_id=item_id,
        decision=decision,
        payload=payload,
    )
    return _response(bundle)


@router.post(
    "/projects/{project_id}/change-regressions/{run_id}/approve",
    response_model=ChangeRegressionRunResponse,
)
async def approve_change_regression(
    project_id: UUID,
    run_id: UUID,
    payload: ChangeRegressionApproval,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ChangeRegressionRunResponse:
    bundle = await ChangeRegressionService(session).approve(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
        note=payload.note,
    )
    return _response(bundle)


@router.post(
    "/projects/{project_id}/change-regressions/{run_id}/execute",
    response_model=ChangeRegressionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_change_regression(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    queue: TestPlanQueue,
) -> ChangeRegressionRunResponse:
    bundle = await ChangeRegressionService(session).execute(
        actor=current_user,
        project_id=project_id,
        run_id=run_id,
        dispatcher=queue,
    )
    return _response(bundle)


@router.post(
    "/projects/{project_id}/change-regressions/{run_id}/release-gate",
    response_model=ChangeRegressionRunResponse,
)
async def evaluate_change_regression_release(
    project_id: UUID,
    run_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> ChangeRegressionRunResponse:
    bundle = await ChangeRegressionService(session).evaluate_release(
        actor=current_user, project_id=project_id, run_id=run_id
    )
    return _response(bundle)


def _response(bundle: ChangeRegressionBundle) -> ChangeRegressionRunResponse:
    run = bundle.run
    return ChangeRegressionRunResponse(
        id=run.id,
        project_id=run.project_id,
        title=run.title,
        source_ref=run.source_ref,
        source_fingerprint=run.source_fingerprint,
        candidate_ref=run.candidate_ref,
        status=cast(
            Literal[
                "review_required",
                "approved",
                "queued",
                "running",
                "evidence_ready",
                "passed",
                "blocked",
                "failed",
            ],
            run.status,
        ),
        impact_run_id=run.impact_run_id,
        test_plan_id=run.test_plan_id,
        test_plan_run_id=run.test_plan_run_id,
        release_policy_id=run.release_policy_id,
        release_risk_id=run.release_risk_id,
        deployment_check_id=run.deployment_check_id,
        change_set_id=run.change_set_id,
        release_decision_id=run.release_decision_id,
        selected_assets=cast(list[dict[str, object]], run.selected_assets),
        selection_summary=cast(dict[str, object], run.selection_summary),
        missing_tests=[
            ChangeRegressionMissingTestResponse(
                item_id=item.id,
                title=item.title,
                proposed_content=cast(dict[str, object], item.proposed_content),
                review_status=cast(Literal["pending", "accepted", "rejected"], item.review_status),
                review_note=item.review_note,
                materialized_resource_type=item.materialized_resource_type,
                materialized_resource_id=item.materialized_resource_id,
            )
            for item in bundle.change_items
        ],
        evidence=cast(dict[str, object], run.evidence),
        failure_triage=cast(dict[str, object], run.failure_triage),
        approved_by_id=run.approved_by_id,
        approved_at=run.approved_at,
        created_by_id=run.created_by_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        stages=[ChangeRegressionStageResponse.model_validate(stage) for stage in bundle.stages],
    )


def _bearer_token(value: str | None) -> str:
    if value is None:
        raise AppError(
            code="INVALID_SERVICE_TOKEN", message="CI Token 无效或权限不足", status_code=401
        )
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(
            code="INVALID_SERVICE_TOKEN", message="CI Token 无效或权限不足", status_code=401
        )
    return token
