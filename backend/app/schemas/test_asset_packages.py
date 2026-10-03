from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.test_assets import (
    AssetName,
    PublishedTestCaseDefinition,
    TagName,
    TestAssetKind,
    TestCaseDefinitionInput,
    TestSuiteDefinitionInput,
)

Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveVersion = Annotated[int, Field(ge=1, strict=True)]
PackageAction = Literal["create", "clone", "update", "skip"]


class StrictPackageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackageFolder(StrictPackageModel):
    id: UUID
    name: Annotated[str, Field(min_length=1, max_length=160)]
    parent_id: UUID | None


class PackageEnvironment(StrictPackageModel):
    id: UUID
    name: Annotated[str, Field(min_length=1, max_length=160)]


class PackageWorkflowVersion(StrictPackageModel):
    version: PositiveVersion
    fingerprint: Fingerprint


class PackageWorkflow(StrictPackageModel):
    id: UUID
    name: AssetName
    versions: list[PackageWorkflowVersion] = Field(max_length=1000)


class PackageCaseVersion(StrictPackageModel):
    version: PositiveVersion
    definition: PublishedTestCaseDefinition
    fingerprint: Fingerprint
    change_note: str = Field(max_length=1000)


class PackageSuiteVersion(StrictPackageModel):
    version: PositiveVersion
    definition: TestSuiteDefinitionInput
    fingerprint: Fingerprint
    change_note: str = Field(max_length=1000)


class PackageCase(StrictPackageModel):
    id: UUID
    name: AssetName
    description: str = Field(max_length=4000)
    folder_id: UUID | None
    tags: list[TagName] = Field(max_length=20)
    is_template: bool
    draft_definition: TestCaseDefinitionInput
    versions: list[PackageCaseVersion] = Field(max_length=1000)


class PackageSuite(StrictPackageModel):
    id: UUID
    name: AssetName
    description: str = Field(max_length=4000)
    folder_id: UUID | None
    tags: list[TagName] = Field(max_length=20)
    draft_definition: TestSuiteDefinitionInput
    versions: list[PackageSuiteVersion] = Field(max_length=1000)


class TestAssetPackage(StrictPackageModel):
    format: Literal["flowtest-test-assets"]
    format_version: Literal[1]
    source_project_id: UUID
    folders: list[PackageFolder] = Field(max_length=1000)
    environments: list[PackageEnvironment] = Field(max_length=1000)
    workflows: list[PackageWorkflow] = Field(max_length=1000)
    cases: list[PackageCase] = Field(max_length=500)
    suites: list[PackageSuite] = Field(max_length=100)

    @field_validator("format_version", mode="before")
    @classmethod
    def validate_format_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("格式版本必须为整数")
        return value

    @model_validator(mode="after")
    def validate_structure(self) -> Self:
        from app.domain.test_asset_packages import validate_package_structure

        validate_package_structure(self)
        return self


class PackageExportRequest(StrictPackageModel):
    case_ids: list[UUID] = Field(default_factory=list, max_length=100)
    suite_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if not self.case_ids and not self.suite_ids:
            raise ValueError("请明确选择需要导出的用例或套件")
        if len(self.case_ids) != len(set(self.case_ids)) or len(self.suite_ids) != len(
            set(self.suite_ids)
        ):
            raise ValueError("导出选择不能重复")
        return self


class PackageAssetChoice(StrictPackageModel):
    kind: TestAssetKind
    source_id: UUID
    action: PackageAction
    name: AssetName | None = None
    target_id: UUID | None = None


class PackageWorkflowBinding(StrictPackageModel):
    target_id: UUID
    versions: dict[PositiveVersion, PositiveVersion] = Field(default_factory=dict)


class PackageBindings(StrictPackageModel):
    workflows: dict[UUID, PackageWorkflowBinding] = Field(default_factory=dict, max_length=1000)
    environments: dict[UUID, UUID] = Field(default_factory=dict, max_length=1000)
    folders: dict[UUID, UUID | None] = Field(default_factory=dict, max_length=1000)


class PackagePreviewRequest(StrictPackageModel):
    package: TestAssetPackage
    choices: list[PackageAssetChoice] = Field(default_factory=list, max_length=600)
    bindings: PackageBindings = Field(default_factory=PackageBindings)


class PackageApplyRequest(PackagePreviewRequest):
    expected_preview_fingerprint: Fingerprint


class PackageDependencyPreview(StrictPackageModel):
    kind: Literal["workflow", "environment", "folder"]
    source_id: UUID
    source_name: str
    target_id: UUID | None
    target_name: str | None
    source_version: int | None = None
    target_version: int | None = None
    fingerprint_changed: bool = False
    problems: list[str] = Field(default_factory=list)


class PackageVersionMapping(StrictPackageModel):
    source_version: int
    target_version: int
    creates_version: bool


class PackageAssetPreview(StrictPackageModel):
    kind: TestAssetKind
    source_id: UUID
    source_name: str
    action: PackageAction
    target_id: UUID | None
    target_name: str
    existing_version: int | None
    existing_updated_at: datetime | None
    existing_draft_fingerprint: str | None
    existing_content_fingerprint: str | None
    versions: list[PackageVersionMapping]
    problems: list[str] = Field(default_factory=list)


class PackagePreviewResponse(StrictPackageModel):
    fingerprint: Fingerprint
    can_apply: bool
    assets: list[PackageAssetPreview]
    dependencies: list[PackageDependencyPreview]


class PackageImportedAsset(StrictPackageModel):
    kind: TestAssetKind
    source_id: UUID
    target_id: UUID
    action: PackageAction
    versions: list[PackageVersionMapping]


class PackageApplyResponse(StrictPackageModel):
    assets: list[PackageImportedAsset]
