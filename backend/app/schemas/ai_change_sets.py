from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.engine.contracts import WorkflowDefinition
from app.schemas.test_assets import AssetName, TagName, TestCaseDefinitionInput


class AITestCaseDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName
    description: str = Field(max_length=4000)
    tags: list[TagName] = Field(default_factory=list, max_length=20)
    definition: TestCaseDefinitionInput


class AITestCaseDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName | None = None
    description: str | None = Field(default=None, max_length=4000)
    tags: list[TagName] | None = Field(default=None, max_length=20)
    definition: TestCaseDefinitionInput | None = None


class AIWorkflowDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName
    description: str = Field(max_length=4000)
    definition: WorkflowDefinition


class AIWorkflowDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AssetName | None = None
    description: str | None = Field(default=None, max_length=4000)
    definition: WorkflowDefinition | None = None


class AIChangeSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    impact_run_id: UUID
    release_risk_id: UUID
    title: AssetName


class AIChangeItemReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, JsonValue] | None = None
    note: str = Field(default="", max_length=2000)


class AIChangeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    item_type: Literal["test_case", "workflow", "assertion"]
    action: Literal["create", "update"]
    title: str
    target_resource_id: UUID | None
    target_snapshot_sha256: str | None
    proposed_content: dict[str, JsonValue]
    review_status: Literal["pending", "accepted", "rejected"]
    review_note: str
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    materialized_resource_type: str | None
    materialized_resource_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AIChangeSetSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    impact_run_id: UUID
    release_risk_id: UUID
    ai_job_id: UUID
    title: str
    status: str
    source_fingerprint: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime


class AIChangeSetDetailResponse(AIChangeSetSummaryResponse):
    source_snapshot: dict[str, JsonValue]
    items: list[AIChangeItemResponse]


def change_set_output_schema(max_suggestions: int) -> dict[str, JsonValue]:
    test_case_ref, test_case_definitions = _strict_model_definitions(
        TestCaseDefinitionInput, "TestCase"
    )
    workflow_ref, workflow_definitions = _strict_model_definitions(WorkflowDefinition, "Workflow")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {**test_case_definitions, **workflow_definitions},
        "type": "object",
        "additionalProperties": False,
        "required": ["suggestions"],
        "properties": {
            "suggestions": {
                "type": "array",
                "maxItems": max_suggestions,
                "items": {
                    "anyOf": [
                        _change_set_suggestion(
                            "test_case",
                            _test_case_create_content(test_case_ref),
                        ),
                        _change_set_suggestion(
                            "test_case",
                            _test_case_update_content(test_case_ref),
                        ),
                        _change_set_suggestion(
                            "workflow",
                            _workflow_create_content(workflow_ref),
                        ),
                        _change_set_suggestion(
                            "workflow",
                            _workflow_update_content(workflow_ref),
                        ),
                        _change_set_suggestion(
                            "assertion",
                            _assertion_update_content(workflow_ref),
                        ),
                    ]
                },
            }
        },
    }


def _strict_model_definitions(
    model: type[BaseModel], namespace: str
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    raw_schema = cast(
        dict[str, JsonValue],
        model.model_json_schema(mode="serialization"),
    )
    nested = cast(dict[str, JsonValue], raw_schema.pop("$defs", {}))
    root_name = f"{namespace}_{model.__name__}"
    names = {name: f"{namespace}_{name}" for name in nested}
    json_value_name = names.get("JsonValue")
    if json_value_name is not None:
        nested["JsonValue"] = _strict_json_value_schema(json_value_name)
    definitions = {names[name]: _strict_schema(value, names) for name, value in nested.items()}
    definitions[root_name] = _strict_schema(raw_schema, names)
    return {"$ref": f"#/$defs/{root_name}"}, definitions


def _strict_json_value_schema(definition_name: str) -> dict[str, JsonValue]:
    reference: dict[str, JsonValue] = {"$ref": f"#/$defs/{definition_name}"}
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
            {"type": "array", "items": reference},
            {
                "type": "object",
                "patternProperties": {"^.*$": reference},
                "additionalProperties": False,
            },
        ]
    }


def _strict_schema(value: JsonValue, names: dict[str, str]) -> JsonValue:
    if isinstance(value, list):
        return [_strict_schema(item, names) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        str(key): _strict_schema(item, names)
        for key, item in value.items()
        if key not in {"default", "title"}
    }
    reference = result.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        original_name = reference.rsplit("/", maxsplit=1)[-1]
        mapped_name = names.get(original_name)
        if mapped_name is not None:
            result["$ref"] = f"#/$defs/{mapped_name}"
    properties = result.get("properties")
    pattern_properties = result.get("patternProperties")
    additional = result.get("additionalProperties")
    is_object = (
        result.get("type") == "object"
        or isinstance(properties, dict)
        or isinstance(pattern_properties, dict)
        or isinstance(additional, dict)
    )
    if not is_object:
        return result
    if isinstance(additional, dict):
        patterns = dict(pattern_properties) if isinstance(pattern_properties, dict) else {}
        patterns["^.*$"] = additional
        result["patternProperties"] = patterns
    result["additionalProperties"] = False
    if isinstance(properties, dict):
        result["required"] = list(properties)
    return result


def _change_set_suggestion(
    suggestion_type: str, content_schema: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "title", "content"],
        "properties": {
            "type": {"const": suggestion_type},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "content": content_schema,
        },
    }


def _test_case_create_content(
    definition_schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return _draft_content_schema(
        action="create",
        required=["action", "name", "description", "tags", "definition"],
        properties={
            "name": _asset_name_schema(nullable=False),
            "description": _description_schema(nullable=False),
            "tags": _tags_schema(nullable=False),
            "definition": definition_schema,
        },
    )


def _test_case_update_content(
    definition_schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return _draft_content_schema(
        action="update",
        required=[
            "action",
            "target_id",
            "name",
            "description",
            "tags",
            "definition",
        ],
        properties={
            "target_id": _target_id_schema(),
            "name": _asset_name_schema(nullable=True),
            "description": _description_schema(nullable=True),
            "tags": _tags_schema(nullable=True),
            "definition": _nullable_schema(definition_schema),
        },
    )


def _workflow_create_content(
    definition_schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return _draft_content_schema(
        action="create",
        required=["action", "name", "description", "definition"],
        properties={
            "name": _asset_name_schema(nullable=False),
            "description": _description_schema(nullable=False),
            "definition": definition_schema,
        },
    )


def _workflow_update_content(
    definition_schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return _draft_content_schema(
        action="update",
        required=["action", "target_id", "name", "description", "definition"],
        properties={
            "target_id": _target_id_schema(),
            "name": _asset_name_schema(nullable=True),
            "description": _description_schema(nullable=True),
            "definition": _nullable_schema(definition_schema),
        },
    )


def _assertion_update_content(
    definition_schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    return _draft_content_schema(
        action="update",
        required=["action", "target_id", "name", "description", "definition"],
        properties={
            "target_id": _target_id_schema(),
            "name": _asset_name_schema(nullable=True),
            "description": _description_schema(nullable=True),
            "definition": definition_schema,
        },
    )


def _nullable_schema(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {"anyOf": [schema, {"type": "null"}]}


def _draft_content_schema(
    *, action: str, required: list[JsonValue], properties: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {"action": {"const": action}, **properties},
    }


def _asset_name_schema(*, nullable: bool) -> dict[str, JsonValue]:
    return {
        "type": ["string", "null"] if nullable else "string",
        "minLength": 1,
        "maxLength": 200,
    }


def _description_schema(*, nullable: bool) -> dict[str, JsonValue]:
    return {
        "type": ["string", "null"] if nullable else "string",
        "maxLength": 4000,
    }


def _tags_schema(*, nullable: bool) -> dict[str, JsonValue]:
    return {
        "type": ["array", "null"] if nullable else "array",
        "maxItems": 20,
        "items": {"type": "string", "minLength": 1, "maxLength": 50},
    }


def _target_id_schema() -> dict[str, JsonValue]:
    return {
        "type": "string",
        "pattern": (
            "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
    }
