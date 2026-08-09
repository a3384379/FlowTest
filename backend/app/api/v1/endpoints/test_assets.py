from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.domain.test_assets import VersionChange
from app.schemas.common import Page
from app.schemas.test_assets import (
    AssetBulkMove,
    AssetBulkMoveResponse,
    AssetClone,
    TestCaseCreate,
    TestCaseResponse,
    TestCaseUpdate,
    TestCaseVersionResponse,
    TestSuiteCreate,
    TestSuiteResponse,
    TestSuiteUpdate,
    TestSuiteVersionResponse,
    VersionChangeResponse,
    VersionDiffResponse,
    VersionPublish,
)
from app.services.test_assets import TestCaseService, TestSuiteService

router = APIRouter(prefix="/projects/{project_id}")


@router.get("/test-cases", response_model=Page[TestCaseResponse])
async def list_test_cases(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=50),
    is_template: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[TestCaseResponse]:
    items, total = await TestCaseService(session).list_cases(
        actor=current_user,
        project_id=project_id,
        search=search,
        tag=tag,
        is_template=is_template,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[TestCaseResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/test-cases", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    project_id: UUID,
    payload: TestCaseCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestCaseResponse:
    model = await TestCaseService(session).create(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        tags=payload.tags,
        is_template=payload.is_template,
        definition=payload.definition,
    )
    return TestCaseResponse.model_validate(model)


@router.post("/test-cases/bulk-move", response_model=AssetBulkMoveResponse)
async def bulk_move_test_cases(
    project_id: UUID,
    payload: AssetBulkMove,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AssetBulkMoveResponse:
    updated = await TestCaseService(session).bulk_move(
        actor=current_user,
        project_id=project_id,
        case_ids=payload.asset_ids,
        folder_id=payload.folder_id,
    )
    return AssetBulkMoveResponse(updated=updated)


@router.get("/test-cases/{case_id}", response_model=TestCaseResponse)
async def get_test_case(
    project_id: UUID,
    case_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestCaseResponse:
    model = await TestCaseService(session).get(
        actor=current_user, project_id=project_id, case_id=case_id
    )
    return TestCaseResponse.model_validate(model)


@router.patch("/test-cases/{case_id}", response_model=TestCaseResponse)
async def update_test_case(
    project_id: UUID,
    case_id: UUID,
    payload: TestCaseUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestCaseResponse:
    model = await TestCaseService(session).update(
        actor=current_user,
        project_id=project_id,
        case_id=case_id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        change_folder="folder_id" in payload.model_fields_set,
        tags=payload.tags,
        is_template=payload.is_template,
        definition=payload.definition,
    )
    return TestCaseResponse.model_validate(model)


@router.post(
    "/test-cases/{case_id}/clone",
    response_model=TestCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_test_case(
    project_id: UUID,
    case_id: UUID,
    payload: AssetClone,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestCaseResponse:
    model = await TestCaseService(session).clone(
        actor=current_user,
        project_id=project_id,
        case_id=case_id,
        name=payload.name,
    )
    return TestCaseResponse.model_validate(model)


@router.post("/test-cases/{case_id}/versions", response_model=TestCaseVersionResponse)
async def publish_test_case(
    project_id: UUID,
    case_id: UUID,
    payload: VersionPublish,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestCaseVersionResponse:
    model = await TestCaseService(session).publish(
        actor=current_user,
        project_id=project_id,
        case_id=case_id,
        change_note=payload.change_note,
    )
    return TestCaseVersionResponse.model_validate(model)


@router.get("/test-cases/{case_id}/versions", response_model=list[TestCaseVersionResponse])
async def list_test_case_versions(
    project_id: UUID,
    case_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[TestCaseVersionResponse]:
    versions = await TestCaseService(session).list_versions(
        actor=current_user, project_id=project_id, case_id=case_id
    )
    return [TestCaseVersionResponse.model_validate(item) for item in versions]


@router.get(
    "/test-cases/{case_id}/versions/{from_version}/diff/{to_version}",
    response_model=VersionDiffResponse,
)
async def diff_test_case_versions(
    project_id: UUID,
    case_id: UUID,
    from_version: int,
    to_version: int,
    session: SessionDependency,
    current_user: CurrentUser,
) -> VersionDiffResponse:
    diff = await TestCaseService(session).diff(
        actor=current_user,
        project_id=project_id,
        case_id=case_id,
        from_version=from_version,
        to_version=to_version,
    )
    return _diff_response(diff.from_version, diff.to_version, diff.changes)


@router.get("/test-suites", response_model=Page[TestSuiteResponse])
async def list_test_suites(
    project_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[TestSuiteResponse]:
    items, total = await TestSuiteService(session).list_suites(
        actor=current_user,
        project_id=project_id,
        search=search,
        tag=tag,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[TestSuiteResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/test-suites", response_model=TestSuiteResponse, status_code=status.HTTP_201_CREATED)
async def create_test_suite(
    project_id: UUID,
    payload: TestSuiteCreate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestSuiteResponse:
    model = await TestSuiteService(session).create(
        actor=current_user,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        tags=payload.tags,
        definition=payload.definition,
    )
    return TestSuiteResponse.model_validate(model)


@router.post("/test-suites/bulk-move", response_model=AssetBulkMoveResponse)
async def bulk_move_test_suites(
    project_id: UUID,
    payload: AssetBulkMove,
    session: SessionDependency,
    current_user: CurrentUser,
) -> AssetBulkMoveResponse:
    updated = await TestSuiteService(session).bulk_move(
        actor=current_user,
        project_id=project_id,
        suite_ids=payload.asset_ids,
        folder_id=payload.folder_id,
    )
    return AssetBulkMoveResponse(updated=updated)


@router.get("/test-suites/{suite_id}", response_model=TestSuiteResponse)
async def get_test_suite(
    project_id: UUID,
    suite_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestSuiteResponse:
    model = await TestSuiteService(session).get(
        actor=current_user, project_id=project_id, suite_id=suite_id
    )
    return TestSuiteResponse.model_validate(model)


@router.patch("/test-suites/{suite_id}", response_model=TestSuiteResponse)
async def update_test_suite(
    project_id: UUID,
    suite_id: UUID,
    payload: TestSuiteUpdate,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestSuiteResponse:
    model = await TestSuiteService(session).update(
        actor=current_user,
        project_id=project_id,
        suite_id=suite_id,
        name=payload.name,
        description=payload.description,
        folder_id=payload.folder_id,
        change_folder="folder_id" in payload.model_fields_set,
        tags=payload.tags,
        definition=payload.definition,
    )
    return TestSuiteResponse.model_validate(model)


@router.post(
    "/test-suites/{suite_id}/clone",
    response_model=TestSuiteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_test_suite(
    project_id: UUID,
    suite_id: UUID,
    payload: AssetClone,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestSuiteResponse:
    model = await TestSuiteService(session).clone(
        actor=current_user,
        project_id=project_id,
        suite_id=suite_id,
        name=payload.name,
    )
    return TestSuiteResponse.model_validate(model)


@router.post("/test-suites/{suite_id}/versions", response_model=TestSuiteVersionResponse)
async def publish_test_suite(
    project_id: UUID,
    suite_id: UUID,
    payload: VersionPublish,
    session: SessionDependency,
    current_user: CurrentUser,
) -> TestSuiteVersionResponse:
    model = await TestSuiteService(session).publish(
        actor=current_user,
        project_id=project_id,
        suite_id=suite_id,
        change_note=payload.change_note,
    )
    return TestSuiteVersionResponse.model_validate(model)


@router.get("/test-suites/{suite_id}/versions", response_model=list[TestSuiteVersionResponse])
async def list_test_suite_versions(
    project_id: UUID,
    suite_id: UUID,
    session: SessionDependency,
    current_user: CurrentUser,
) -> list[TestSuiteVersionResponse]:
    versions = await TestSuiteService(session).list_versions(
        actor=current_user, project_id=project_id, suite_id=suite_id
    )
    return [TestSuiteVersionResponse.model_validate(item) for item in versions]


@router.get(
    "/test-suites/{suite_id}/versions/{from_version}/diff/{to_version}",
    response_model=VersionDiffResponse,
)
async def diff_test_suite_versions(
    project_id: UUID,
    suite_id: UUID,
    from_version: int,
    to_version: int,
    session: SessionDependency,
    current_user: CurrentUser,
) -> VersionDiffResponse:
    diff = await TestSuiteService(session).diff(
        actor=current_user,
        project_id=project_id,
        suite_id=suite_id,
        from_version=from_version,
        to_version=to_version,
    )
    return _diff_response(diff.from_version, diff.to_version, diff.changes)


def _diff_response(
    from_version: int, to_version: int, changes: tuple[VersionChange, ...]
) -> VersionDiffResponse:
    return VersionDiffResponse(
        from_version=from_version,
        to_version=to_version,
        changes=[
            VersionChangeResponse.model_validate(change, from_attributes=True) for change in changes
        ],
    )
