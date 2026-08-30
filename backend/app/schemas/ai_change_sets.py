import json
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
    test_case_definition = _test_case_definition_schema()
    workflow_definition = _workflow_definition_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
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
                            _test_case_create_content(test_case_definition),
                        ),
                        _change_set_suggestion(
                            "test_case",
                            _test_case_update_content(test_case_definition),
                        ),
                        _change_set_suggestion(
                            "workflow",
                            _workflow_create_content(workflow_definition),
                        ),
                        _change_set_suggestion(
                            "workflow",
                            _workflow_update_content(workflow_definition),
                        ),
                        _change_set_suggestion(
                            "assertion",
                            _assertion_update_content(workflow_definition),
                        ),
                    ]
                },
            }
        },
    }


def decode_change_set_content(
    suggestion_type: str, content: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    action = content.get("action")
    target_id = content.get("target_id")
    proposal = {
        str(key): value for key, value in content.items() if key not in {"action", "target_id"}
    }
    raw_definition = proposal.get("definition")
    if raw_definition is not None:
        if suggestion_type == "test_case":
            proposal["definition"] = _decode_test_case_definition(raw_definition)
        else:
            proposal["definition"] = _decode_workflow_definition(raw_definition)
    try:
        draft_model = _draft_model(suggestion_type, action)
        validated = draft_model.model_validate(proposal)
    except (TypeError, ValueError) as error:
        raise ValueError("change-set draft content is invalid") from error
    if action == "update" and not any(
        value is not None for value in validated.model_dump().values()
    ):
        raise ValueError("change-set update must modify at least one draft field")
    if suggestion_type == "assertion" and getattr(validated, "definition", None) is None:
        raise ValueError("assertion update requires a workflow definition")
    result = cast(dict[str, JsonValue], validated.model_dump(mode="json"))
    result["action"] = str(action)
    if action == "update":
        result["target_id"] = str(target_id)
    return result


def _draft_model(suggestion_type: str, action: JsonValue | None) -> type[BaseModel]:
    if suggestion_type == "test_case" and action == "create":
        return AITestCaseDraftCreate
    if suggestion_type == "test_case" and action == "update":
        return AITestCaseDraftUpdate
    if suggestion_type == "workflow" and action == "create":
        return AIWorkflowDraftCreate
    if suggestion_type in {"workflow", "assertion"} and action == "update":
        return AIWorkflowDraftUpdate
    raise ValueError("change-set suggestion type or action is invalid")


def _decode_test_case_definition(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError("test-case definition must be an object")
    decoded = {
        "workflow_id": value.get("workflow_id"),
        "workflow_version": value.get("workflow_version"),
        "environment_id": value.get("environment_id"),
        "runtime_variables": _decode_named_values(value.get("runtime_variables")),
        "runtime_headers": _decode_named_values(value.get("runtime_headers")),
    }
    return cast(
        dict[str, JsonValue],
        TestCaseDefinitionInput.model_validate(decoded).model_dump(mode="json"),
    )


def _decode_workflow_definition(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError("workflow definition must be an object")
    raw_nodes = value.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ValueError("workflow nodes must be a list")
    nodes = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise ValueError("workflow node must be an object")
        node = dict(raw_node)
        node["config"] = _decode_json_object(raw_node.get("config_json"))
        raw_configuration = raw_node.get("configuration_json")
        node["configuration"] = (
            None if raw_configuration is None else _decode_json_object(raw_configuration)
        )
        node.pop("config_json", None)
        node.pop("configuration_json", None)
        nodes.append(node)
    decoded = {
        **value,
        "variables": _decode_named_values(value.get("variables")),
        "nodes": nodes,
    }
    return cast(
        dict[str, JsonValue],
        WorkflowDefinition.model_validate(decoded).model_dump(mode="json"),
    )


def _decode_named_values(value: JsonValue | None) -> dict[str, str]:
    if not isinstance(value, list):
        raise ValueError("named values must be a list")
    result = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("named value must be an object")
        name = item.get("name")
        item_value = item.get("value")
        if not isinstance(name, str) or not isinstance(item_value, str) or name in result:
            raise ValueError("named value is invalid or duplicated")
        result[name] = item_value
    return result


def _decode_json_object(value: JsonValue | None) -> dict[str, JsonValue]:
    if not isinstance(value, str):
        raise ValueError("JSON object field must be encoded as a string")
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("encoded JSON value must be an object")
    return cast(dict[str, JsonValue], decoded)


def _test_case_definition_schema() -> dict[str, JsonValue]:
    named_value = _strict_object(
        {
            "name": {"type": "string", "minLength": 1, "maxLength": 160},
            "value": {"type": "string", "maxLength": 100_000},
        }
    )
    named_values: dict[str, JsonValue] = {
        "type": "array",
        "maxItems": 500,
        "items": named_value,
    }
    return _strict_object(
        {
            "workflow_id": _target_id_schema(),
            "workflow_version": _nullable_schema({"type": "integer", "minimum": 1}),
            "environment_id": _target_id_schema(),
            "runtime_variables": named_values,
            "runtime_headers": named_values,
        }
    )


def _workflow_definition_schema() -> dict[str, JsonValue]:
    named_value = _strict_object(
        {
            "name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
                "pattern": "^[A-Za-z_][A-Za-z0-9_.-]*$",
            },
            "value": {"type": "string", "maxLength": 100_000},
        }
    )
    position = _strict_object({"x": {"type": "number"}, "y": {"type": "number"}})
    binding = _strict_object(
        {
            "input": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
                "pattern": "^[A-Za-z_][A-Za-z0-9_.-]*$",
            },
            "expression": {"type": "string", "minLength": 1, "maxLength": 2000},
        }
    )
    node = _strict_object(
        {
            "id": {"type": "string", "minLength": 1, "maxLength": 128},
            "type": {
                "type": "string",
                "enum": [
                    "start",
                    "api",
                    "extract",
                    "assert",
                    "condition",
                    "delay",
                    "dataset",
                    "subflow",
                    "for_each",
                    "sql",
                    "redis",
                    "capability",
                    "end",
                ],
            },
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "position": position,
            "config_json": {"type": "string", "minLength": 2, "maxLength": 1_000_000},
            "capability_id": _nullable_schema({"type": "string", "minLength": 3, "maxLength": 120}),
            "capability_version": _nullable_schema(
                {"type": "string", "minLength": 5, "maxLength": 64}
            ),
            "configuration_json": _nullable_schema(
                {"type": "string", "minLength": 2, "maxLength": 1_000_000}
            ),
            "bindings": _nullable_schema({"type": "array", "maxItems": 500, "items": binding}),
            "phase": {"type": "string", "enum": ["main", "cleanup"]},
            "run_when": {
                "type": "string",
                "enum": ["success", "failure", "cancel", "always"],
            },
            "cleanup_for": {
                "type": "array",
                "maxItems": 200,
                "items": {"type": "string", "minLength": 1, "maxLength": 128},
            },
            "best_effort": {"type": "boolean"},
            "cleanup_timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 300,
            },
            "cleanup_retry_budget": {
                "type": "integer",
                "minimum": 0,
                "maximum": 3,
            },
        }
    )
    mapping_source = _strict_object(
        {
            "node_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "path": {"type": "string", "minLength": 1, "maxLength": 500},
        }
    )
    mapping_transform = _strict_object(
        {
            "kind": {"type": "string", "enum": ["identity", "template"]},
            "template": {"type": "string", "maxLength": 4000},
        }
    )
    mapping_target = _strict_object(
        {
            "node_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "location": {
                "type": "string",
                "enum": ["query", "header", "body", "variable"],
            },
            "key": {"type": "string", "minLength": 1, "maxLength": 500},
        }
    )
    mapping = _strict_object(
        {
            "source": mapping_source,
            "transform": mapping_transform,
            "target": mapping_target,
        }
    )
    edge = _strict_object(
        {
            "id": {"type": "string", "minLength": 1, "maxLength": 128},
            "source": {"type": "string", "minLength": 1, "maxLength": 128},
            "target": {"type": "string", "minLength": 1, "maxLength": 128},
            "condition": _nullable_schema({"type": "string", "maxLength": 2000}),
            "mappings": {"type": "array", "maxItems": 500, "items": mapping},
        }
    )
    settings = _strict_object(
        {
            "fail_fast": {"type": "boolean"},
            "concurrency": {"type": "integer", "minimum": 1, "maximum": 100},
            "default_timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 300,
            },
        }
    )
    run_policy = _strict_object(
        {
            "request_budget": _nullable_schema(
                {"type": "integer", "minimum": 1, "maximum": 10_000}
            ),
            "max_runtime_seconds": _nullable_schema(
                {"type": "integer", "minimum": 1, "maximum": 3600}
            ),
            "cleanup_request_budget": _nullable_schema(
                {"type": "integer", "minimum": 1, "maximum": 1000}
            ),
            "force_cancel_skips_cleanup": {"type": "boolean"},
        }
    )
    return _strict_object(
        {
            "schema_version": {"type": "string", "minLength": 1, "maxLength": 32},
            "variables": {"type": "array", "maxItems": 500, "items": named_value},
            "nodes": {"type": "array", "minItems": 2, "maxItems": 1000, "items": node},
            "edges": {"type": "array", "maxItems": 5000, "items": edge},
            "settings": settings,
            "run_policy": run_policy,
        }
    )


def _strict_object(properties: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


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
