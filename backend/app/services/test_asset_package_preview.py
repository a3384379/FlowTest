from dataclasses import dataclass, field
from uuid import UUID

from app.core.errors import AppError
from app.domain.test_assets import definition_fingerprint
from app.models.test_assets import TestCase, TestSuite
from app.schemas.test_asset_packages import (
    PackageAssetChoice,
    PackageAssetPreview,
    PackageCase,
    PackageCaseVersion,
    PackageDependencyPreview,
    PackagePreviewRequest,
    PackagePreviewResponse,
    PackageSuite,
    PackageSuiteVersion,
    PackageVersionMapping,
    PackageWorkflow,
    PackageWorkflowBinding,
)
from app.schemas.test_assets import (
    PublishedTestCaseDefinition,
    TestAssetKind,
    TestCaseDefinitionInput,
    TestCaseResponse,
    TestSuiteDefinitionInput,
    TestSuiteItemInput,
    TestSuiteResponse,
)
from app.services.test_asset_packages import TestAssetPackageReader


@dataclass(slots=True)
class ResolvedPackageBindings:
    workflows: dict[UUID, UUID] = field(default_factory=dict)
    workflow_versions: dict[tuple[UUID, int], int] = field(default_factory=dict)
    environments: dict[UUID, UUID] = field(default_factory=dict)
    folders: dict[UUID, UUID | None] = field(default_factory=dict)
    evidence: list[PackageDependencyPreview] = field(default_factory=list)


@dataclass(slots=True)
class PreparedPackageImport:
    preview: PackagePreviewResponse
    bindings: ResolvedPackageBindings
    cases: dict[UUID, list[PackageCaseVersion]]
    suites: dict[UUID, list[PackageSuiteVersion]]


class PackageBindingResolver:
    def __init__(self, reader: TestAssetPackageReader) -> None:
        self._reader = reader

    async def resolve(
        self, project_id: UUID, request: PackagePreviewRequest
    ) -> ResolvedPackageBindings:
        bindings = ResolvedPackageBindings()
        for source in request.package.workflows:
            await self._workflow(
                project_id, source, request.bindings.workflows.get(source.id), bindings
            )
        for source_environment in request.package.environments:
            target_environment_id = request.bindings.environments.get(
                source_environment.id, source_environment.id
            )
            target_environment = await self._reader.environment(project_id, target_environment_id)
            bindings.environments[source_environment.id] = target_environment_id
            bindings.evidence.append(
                PackageDependencyPreview(
                    kind="environment",
                    source_id=source_environment.id,
                    source_name=source_environment.name,
                    target_id=target_environment.id if target_environment else None,
                    target_name=target_environment.name if target_environment else None,
                    problems=[] if target_environment else ["目标环境不可用, 请绑定同项目环境"],
                )
            )
        for source_folder in request.package.folders:
            folder_id = request.bindings.folders.get(source_folder.id, source_folder.id)
            target_folder = await self._reader.folder(project_id, folder_id) if folder_id else None
            bindings.folders[source_folder.id] = folder_id
            bindings.evidence.append(
                PackageDependencyPreview(
                    kind="folder",
                    source_id=source_folder.id,
                    source_name=source_folder.name,
                    target_id=target_folder.id if target_folder else None,
                    target_name=_folder_target_name(
                        folder_id, target_folder.name if target_folder else None
                    ),
                    problems=[]
                    if target_folder or folder_id is None
                    else ["目标目录不可用, 请绑定目录或明确选择未分类"],
                )
            )
        return bindings

    async def _workflow(
        self,
        project_id: UUID,
        source: PackageWorkflow,
        explicit: PackageWorkflowBinding | None,
        bindings: ResolvedPackageBindings,
    ) -> None:
        target_id = explicit.target_id if explicit else source.id
        target = await self._reader.workflow(project_id, target_id)
        bindings.workflows[source.id] = target_id
        if target is None:
            bindings.evidence.append(
                PackageDependencyPreview(
                    kind="workflow",
                    source_id=source.id,
                    source_name=source.name,
                    target_id=None,
                    target_name=None,
                    problems=["目标流程不可用, 请绑定同项目流程及固定版本"],
                )
            )
            return
        if not source.versions:
            bindings.evidence.append(
                PackageDependencyPreview(
                    kind="workflow",
                    source_id=source.id,
                    source_name=source.name,
                    target_id=target_id,
                    target_name=target.name,
                )
            )
        for source_version in source.versions:
            number = (
                explicit.versions.get(source_version.version, source_version.version)
                if explicit
                else source_version.version
            )
            version = await self._reader.workflow_version(target_id, number)
            changed = version is not None and version.fingerprint != source_version.fingerprint
            problems = _workflow_version_problems(
                version is not None,
                changed,
                explicit is not None and source_version.version in explicit.versions,
            )
            bindings.workflow_versions[(source.id, source_version.version)] = number
            bindings.evidence.append(
                PackageDependencyPreview(
                    kind="workflow",
                    source_id=source.id,
                    source_name=source.name,
                    target_id=target_id,
                    target_name=target.name,
                    source_version=source_version.version,
                    target_version=number,
                    fingerprint_changed=changed,
                    problems=problems,
                )
            )


def _folder_target_name(target_id: UUID | None, name: str | None) -> str | None:
    return "未分类" if target_id is None else name


def _workflow_version_problems(exists: bool, changed: bool, explicit_version: bool) -> list[str]:
    if not exists:
        return ["目标流程版本不存在, 请明确绑定已发布版本"]
    if changed and not explicit_version:
        return ["流程版本内容不同, 请明确绑定并确认目标版本"]
    return []


class TestAssetPackagePreviewBuilder:
    def __init__(self, reader: TestAssetPackageReader) -> None:
        self._reader = reader

    async def prepare(
        self, project_id: UUID, request: PackagePreviewRequest
    ) -> PreparedPackageImport:
        _validate_choices(request)
        bindings = await PackageBindingResolver(self._reader).resolve(project_id, request)
        choices = {(choice.kind, choice.source_id): choice for choice in request.choices}
        assets: list[PackageAssetPreview] = []
        cases: dict[UUID, list[PackageCaseVersion]] = {}
        suites: dict[UUID, list[PackageSuiteVersion]] = {}
        for source in request.package.cases:
            preview = await self._target(
                project_id, "case", source.id, source.name, choices.get(("case", source.id))
            )
            versions = _mapped_case_versions(source, bindings)
            existing = (
                await self._reader.case_versions(preview.target_id) if preview.target_id else []
            )
            _allocate_versions(
                preview,
                [
                    (version.version, version.fingerprint, version.change_note)
                    for version in versions
                ],
                [
                    (version.version, version.fingerprint, version.change_note)
                    for version in existing
                ],
            )
            assets.append(preview)
            cases[source.id] = versions
        for source_suite in request.package.suites:
            preview = await self._target(
                project_id,
                "suite",
                source_suite.id,
                source_suite.name,
                choices.get(("suite", source_suite.id)),
            )
            suite_versions = _mapped_suite_versions(source_suite, assets)
            existing_suite = (
                await self._reader.suite_versions(preview.target_id) if preview.target_id else []
            )
            _allocate_versions(
                preview,
                [
                    (version.version, version.fingerprint, version.change_note)
                    for version in suite_versions
                ],
                [
                    (version.version, version.fingerprint, version.change_note)
                    for version in existing_suite
                ],
            )
            _guard_suite_reuse(source_suite, preview, assets)
            assets.append(preview)
            suites[source_suite.id] = suite_versions
        _guard_unique_targets(assets)
        can_apply = not any(asset.problems for asset in assets) and not any(
            item.problems for item in bindings.evidence
        )
        fingerprint = definition_fingerprint(
            {
                "project_id": str(project_id),
                "request": request.model_dump(mode="json"),
                "assets": [asset.model_dump(mode="json") for asset in assets],
                "dependencies": [item.model_dump(mode="json") for item in bindings.evidence],
            }
        )
        return PreparedPackageImport(
            preview=PackagePreviewResponse(
                fingerprint=fingerprint,
                can_apply=can_apply,
                assets=assets,
                dependencies=bindings.evidence,
            ),
            bindings=bindings,
            cases=cases,
            suites=suites,
        )

    async def _target(
        self,
        project_id: UUID,
        kind: TestAssetKind,
        source_id: UUID,
        source_name: str,
        choice: PackageAssetChoice | None,
    ) -> PackageAssetPreview:
        selected = choice or PackageAssetChoice(kind=kind, source_id=source_id, action="create")
        name = selected.name or source_name
        named = await self._reader.named(project_id, kind, name)
        target = None
        problems: list[str] = []
        if selected.action in ("update", "skip"):
            target = (
                await self._reader.asset(project_id, kind, selected.target_id)
                if selected.target_id
                else named
            )
            problems = _existing_target_problems(
                target is not None, target.archived_at is not None if target else False
            )
            if target is not None:
                name = selected.name or target.name
                named = await self._reader.named(project_id, kind, name)
                if named is not None and named.id != target.id:
                    problems.append("目标名称已被其他资产占用")
                if selected.action == "skip" and name != target.name:
                    problems.append("跳过导入时不能重命名已有资产")
        else:
            if named is not None:
                problems.append("名称已存在, 请选择跳过、更新或另存名称")
            if selected.target_id is not None:
                problems.append("新建或另存不能指定覆盖对象")
        return PackageAssetPreview(
            kind=kind,
            source_id=source_id,
            source_name=source_name,
            action=selected.action,
            target_id=target.id if target else None,
            target_name=name,
            existing_version=target.current_version if target else None,
            existing_updated_at=target.updated_at if target else None,
            existing_draft_fingerprint=target.draft_fingerprint if target else None,
            existing_content_fingerprint=_target_fingerprint(target) if target else None,
            versions=[],
            problems=problems,
        )


def _target_fingerprint(target: TestCase | TestSuite) -> str:
    if isinstance(target, TestCase):
        content = TestCaseResponse.model_validate(target).model_dump(mode="json")
    else:
        content = TestSuiteResponse.model_validate(target).model_dump(mode="json")
    return definition_fingerprint(content)


def _existing_target_problems(exists: bool, archived: bool) -> list[str]:
    if not exists:
        return ["更新或跳过的目标资产不存在"]
    if archived:
        return ["目标资产已归档, 不能覆盖或复用, 请另存名称"]
    return []


def _validate_choices(request: PackagePreviewRequest) -> None:
    allowed = {("case", asset.id) for asset in request.package.cases} | {
        ("suite", asset.id) for asset in request.package.suites
    }
    selected = [(choice.kind, choice.source_id) for choice in request.choices]
    if len(selected) != len(set(selected)) or not set(selected).issubset(allowed):
        raise AppError(
            code="TEST_ASSET_PACKAGE_INVALID_CHOICES",
            message="导入选择重复或超出原生包范围",
            status_code=422,
        )
    groups = (
        (set(request.bindings.workflows), {item.id for item in request.package.workflows}),
        (set(request.bindings.environments), {item.id for item in request.package.environments}),
        (set(request.bindings.folders), {item.id for item in request.package.folders}),
    )
    if any(not supplied.issubset(known) for supplied, known in groups):
        raise AppError(
            code="TEST_ASSET_PACKAGE_INVALID_BINDINGS",
            message="资源绑定超出原生包引用范围",
            status_code=422,
        )
    for workflow in request.package.workflows:
        binding = request.bindings.workflows.get(workflow.id)
        if binding is not None and not set(binding.versions).issubset(
            {version.version for version in workflow.versions}
        ):
            raise AppError(
                code="TEST_ASSET_PACKAGE_INVALID_BINDINGS",
                message="流程版本绑定超出原生包引用范围",
                status_code=422,
            )


def map_case_definition(
    definition: TestCaseDefinitionInput, bindings: ResolvedPackageBindings
) -> TestCaseDefinitionInput:
    version = definition.workflow_version
    if version is not None:
        version = bindings.workflow_versions.get((definition.workflow_id, version), version)
    return TestCaseDefinitionInput(
        workflow_id=bindings.workflows.get(definition.workflow_id, definition.workflow_id),
        workflow_version=version,
        environment_id=bindings.environments.get(
            definition.environment_id, definition.environment_id
        ),
        runtime_variables=definition.runtime_variables,
        runtime_headers=definition.runtime_headers,
    )


def _mapped_case_versions(
    source: PackageCase, bindings: ResolvedPackageBindings
) -> list[PackageCaseVersion]:
    versions = []
    for version in source.versions:
        definition = PublishedTestCaseDefinition.model_validate(
            map_case_definition(version.definition, bindings).model_dump()
        )
        versions.append(
            PackageCaseVersion(
                version=version.version,
                definition=definition,
                fingerprint=definition_fingerprint(definition.model_dump(mode="json")),
                change_note=version.change_note,
            )
        )
    return versions


def map_suite_definition(
    definition: TestSuiteDefinitionInput, assets: list[PackageAssetPreview]
) -> TestSuiteDefinitionInput:
    cases = {asset.source_id: asset for asset in assets if asset.kind == "case"}
    items = []
    for item in definition.items:
        case = cases[item.test_case_id]
        versions = {version.source_version: version.target_version for version in case.versions}
        items.append(
            TestSuiteItemInput(
                test_case_id=case.target_id or case.source_id,
                test_case_version=versions[item.test_case_version]
                if item.test_case_version is not None
                else None,
            )
        )
    return TestSuiteDefinitionInput(items=items)


def _mapped_suite_versions(
    source: PackageSuite, assets: list[PackageAssetPreview]
) -> list[PackageSuiteVersion]:
    versions = []
    for version in source.versions:
        definition = map_suite_definition(version.definition, assets)
        versions.append(
            PackageSuiteVersion(
                version=version.version,
                definition=definition,
                fingerprint=definition_fingerprint(definition.model_dump(mode="json")),
                change_note=version.change_note,
            )
        )
    return versions


def _allocate_versions(
    preview: PackageAssetPreview,
    incoming: list[tuple[int, str, str]],
    existing: list[tuple[int, str, str]],
) -> None:
    available = list(existing)
    next_version = (preview.existing_version or 0) + 1
    for number, fingerprint, note in incoming:
        match = next((row for row in available if row[1:] == (fingerprint, note)), None)
        if match is not None:
            available.remove(match)
            preview.versions.append(
                PackageVersionMapping(
                    source_version=number, target_version=match[0], creates_version=False
                )
            )
            continue
        if preview.action == "skip":
            preview.problems.append(
                f"无法跳过: 现有资产缺少与原 v{number} 内容及说明一致的固定版本"
            )
        preview.versions.append(
            PackageVersionMapping(
                source_version=number, target_version=next_version, creates_version=True
            )
        )
        next_version += 1


def _guard_suite_reuse(
    source: PackageSuite, preview: PackageAssetPreview, assets: list[PackageAssetPreview]
) -> None:
    new_ids = {
        asset.source_id for asset in assets if asset.kind == "case" and asset.target_id is None
    }
    referenced = {
        item.test_case_id for version in source.versions for item in version.definition.items
    }
    if not referenced.intersection(new_ids):
        return
    if preview.action == "skip":
        preview.problems.append("包含待新建用例时, 不能跳过复用既有套件固定版本")
    next_version = (preview.existing_version or 0) + 1
    preview.versions = [
        PackageVersionMapping(
            source_version=version.version,
            target_version=next_version + index,
            creates_version=True,
        )
        for index, version in enumerate(source.versions)
    ]


def _guard_unique_targets(assets: list[PackageAssetPreview]) -> None:
    seen_names: set[tuple[TestAssetKind, str]] = set()
    seen_ids: set[tuple[TestAssetKind, UUID]] = set()
    for asset in assets:
        name = (asset.kind, asset.target_name)
        identity = (asset.kind, asset.target_id) if asset.target_id is not None else None
        if name in seen_names or (identity is not None and identity in seen_ids):
            asset.problems.append("同一原生包不能重复写入同名或同一目标资产")
        seen_names.add(name)
        if identity is not None:
            seen_ids.add(identity)
