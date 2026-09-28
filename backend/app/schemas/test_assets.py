import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.domain.api_assets import JsonValue

RuntimeName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$", max_length=160)]
TagName = Annotated[str, Field(min_length=1, max_length=50)]
AssetName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def validate_runtime_headers(headers: dict[str, str]) -> dict[str, str]:
    seen: set[str] = set()
    for name, value in headers.items():
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            raise ValueError("Header 名称不合法")
        if "\r" in value or "\n" in value:
            raise ValueError("Header 值不能包含换行")
        key = name.lower()
        if key in seen:
            raise ValueError("Header 名称重复")
        seen.add(key)
    return headers


class StoredTestCaseDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    workflow_version: int | None = Field(default=None, ge=1)
    environment_id: UUID
    runtime_variables: dict[RuntimeName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)


class TestCaseDefinitionInput(StoredTestCaseDefinition):
    @field_validator("runtime_headers")
    @classmethod
    def validate_headers(cls, headers: dict[str, str]) -> dict[str, str]:
        return validate_runtime_headers(headers)


class PublishedTestCaseDefinition(TestCaseDefinitionInput):
    workflow_version: int = Field(ge=1)


class StoredPublishedTestCaseDefinition(StoredTestCaseDefinition):
    workflow_version: int = Field(ge=1)


class TestCaseCreate(BaseModel):
    name: AssetName
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None
    tags: list[TagName] = Field(default_factory=list, max_length=20)
    is_template: bool = False
    definition: TestCaseDefinitionInput


class TestCaseUpdate(BaseModel):
    name: AssetName | None = None
    description: str | None = Field(default=None, max_length=4000)
    folder_id: UUID | None = None
    tags: list[TagName] | None = Field(default=None, max_length=20)
    is_template: bool | None = None
    definition: TestCaseDefinitionInput | None = None


class TestCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    folder_id: UUID | None
    name: str
    description: str
    tags: list[str]
    is_template: bool
    draft_definition: StoredTestCaseDefinition
    draft_fingerprint: str
    current_version: int | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class VersionPublish(BaseModel):
    change_note: str = Field(default="", max_length=1000)


class TestCaseRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["published", "draft"] = "published"
    version: int | None = Field(default=None, ge=1)
    publish_draft: bool = False
    expected_draft_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    runtime_variables: dict[RuntimeName, str] = Field(default_factory=dict)
    runtime_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("runtime_headers")
    @classmethod
    def validate_headers(cls, headers: dict[str, str]) -> dict[str, str]:
        return validate_runtime_headers(headers)


class TestCaseRunResponse(BaseModel):
    execution_id: UUID
    case_id: UUID
    case_version: int
    workflow_id: UUID
    workflow_version: int
    environment_id: UUID
    status: str
    source: Literal["direct", "plan"]
    started_at: datetime
    created_new_version: bool = False


class TestCaseVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_case_id: UUID
    version: int
    definition: StoredPublishedTestCaseDefinition
    fingerprint: str
    change_note: str
    created_by_id: UUID
    created_at: datetime


class TestSuiteItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_case_id: UUID
    test_case_version: int | None = Field(default=None, ge=1)


class TestSuiteDefinitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TestSuiteItemInput] = Field(min_length=1, max_length=500)


class PublishedTestSuiteItem(BaseModel):
    test_case_id: UUID
    test_case_version: int = Field(ge=1)


class PublishedTestSuiteDefinition(BaseModel):
    items: list[PublishedTestSuiteItem]


class TestSuiteCreate(BaseModel):
    name: AssetName
    description: str = Field(default="", max_length=4000)
    folder_id: UUID | None = None
    tags: list[TagName] = Field(default_factory=list, max_length=20)
    definition: TestSuiteDefinitionInput


class TestSuiteUpdate(BaseModel):
    name: AssetName | None = None
    description: str | None = Field(default=None, max_length=4000)
    folder_id: UUID | None = None
    tags: list[TagName] | None = Field(default=None, max_length=20)
    definition: TestSuiteDefinitionInput | None = None


class TestSuiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    folder_id: UUID | None
    name: str
    description: str
    tags: list[str]
    draft_definition: TestSuiteDefinitionInput
    current_version: int | None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class TestSuiteVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_suite_id: UUID
    version: int
    definition: PublishedTestSuiteDefinition
    fingerprint: str
    change_note: str
    created_by_id: UUID
    created_at: datetime


class AssetClone(BaseModel):
    name: AssetName


class AssetBulkMove(BaseModel):
    asset_ids: list[UUID] = Field(min_length=1, max_length=100)
    folder_id: UUID | None = None


class AssetBulkMoveResponse(BaseModel):
    updated: int


class VersionChangeResponse(BaseModel):
    path: str
    before: JsonValue
    after: JsonValue


class VersionDiffResponse(BaseModel):
    from_version: int
    to_version: int
    changes: list[VersionChangeResponse]
