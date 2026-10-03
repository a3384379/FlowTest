from typing import TYPE_CHECKING

from app.domain.test_assets import definition_fingerprint

if TYPE_CHECKING:
    from app.schemas.test_asset_packages import (
        PackageCase,
        PackageCaseVersion,
        PackageSuite,
        PackageSuiteVersion,
        TestAssetPackage,
    )


def validate_package_structure(package: "TestAssetPackage") -> None:
    groups = (
        package.folders,
        package.environments,
        package.workflows,
        package.cases,
        package.suites,
    )
    for group in groups:
        ids = [item.id for item in group]
        if len(ids) != len(set(ids)):
            raise ValueError("原生包中存在重复对象 ID")
    if not package.cases and not package.suites:
        raise ValueError("原生包未包含测试资产")
    for workflow in package.workflows:
        numbers = [version.version for version in workflow.versions]
        if len(numbers) != len(set(numbers)):
            raise ValueError("原生包存在重复流程版本引用")
    _validate_folders(package)
    for case in package.cases:
        _validate_case(package, case)
    for suite in package.suites:
        _validate_suite(package, suite)


def _validate_folders(package: "TestAssetPackage") -> None:
    parents = {folder.id: folder.parent_id for folder in package.folders}
    for folder in package.folders:
        seen = {folder.id}
        parent = folder.parent_id
        while parent is not None:
            if parent not in parents or parent in seen:
                raise ValueError("原生包目录存在缺失父目录或循环")
            seen.add(parent)
            parent = parents[parent]
    assets: list[PackageCase | PackageSuite] = [*package.cases, *package.suites]
    for asset in assets:
        if asset.folder_id is not None and asset.folder_id not in parents:
            raise ValueError("原生包测试资产引用了缺失目录")


def _validate_case(package: "TestAssetPackage", case: "PackageCase") -> None:
    _validate_versions(case.versions)
    workflows = {workflow.id: workflow for workflow in package.workflows}
    environments = {environment.id for environment in package.environments}
    for definition in [case.draft_definition, *(version.definition for version in case.versions)]:
        workflow = workflows.get(definition.workflow_id)
        if workflow is None or definition.environment_id not in environments:
            raise ValueError("原生包用例缺失流程或环境引用")
        if definition.workflow_version is not None and definition.workflow_version not in {
            version.version for version in workflow.versions
        }:
            raise ValueError("原生包用例缺失固定流程版本引用")


def _validate_suite(package: "TestAssetPackage", suite: "PackageSuite") -> None:
    _validate_versions(suite.versions)
    cases = {case.id: case for case in package.cases}
    for definition in [suite.draft_definition, *(version.definition for version in suite.versions)]:
        ids = [item.test_case_id for item in definition.items]
        if len(ids) != len(set(ids)):
            raise ValueError("原生包套件存在重复成员")
        for item in definition.items:
            case = cases.get(item.test_case_id)
            if case is None or (
                item.test_case_version is not None
                and item.test_case_version not in {version.version for version in case.versions}
            ):
                raise ValueError("原生包套件缺失用例或固定用例版本")
    if any(
        item.test_case_version is None
        for version in suite.versions
        for item in version.definition.items
    ):
        raise ValueError("原生包已发布套件成员必须固定用例版本")


def _validate_versions(versions: "list[PackageCaseVersion] | list[PackageSuiteVersion]") -> None:
    numbers = [version.version for version in versions]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("原生包版本必须从 1 开始完整递增, 不能省略或重复")
    for version in versions:
        if (
            definition_fingerprint(version.definition.model_dump(mode="json"))
            != version.fingerprint
        ):
            raise ValueError("原生包版本内容与指纹不一致")
