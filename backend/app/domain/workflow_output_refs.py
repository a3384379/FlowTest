"""Pure transformations for large HTTP bodies in workflow reports."""

import json
from typing import Protocol, TypeGuard, cast

from pydantic import JsonValue

REFERENCE_KEY = "__flowtest_workflow_output_ref__"


class WorkflowBodyStore(Protocol):
    async def store(self, body: JsonValue) -> dict[str, JsonValue]: ...

    async def load(self, reference: dict[str, JsonValue]) -> JsonValue: ...


async def compact_response_bodies(
    value: JsonValue, *, store: WorkflowBodyStore, inline_limit_bytes: int
) -> JsonValue:
    if isinstance(value, list):
        return [
            await compact_response_bodies(item, store=store, inline_limit_bytes=inline_limit_bytes)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    if _is_response_output(value):
        body = value["body"]
        if not _needs_storage(value, inline_limit_bytes):
            return value
        return {**value, "body": await store.store(body)}
    return {
        key: await compact_response_bodies(item, store=store, inline_limit_bytes=inline_limit_bytes)
        for key, item in value.items()
    }


async def restore_response_bodies(value: JsonValue, *, store: WorkflowBodyStore) -> JsonValue:
    if isinstance(value, list):
        return [await restore_response_bodies(item, store=store) for item in value]
    if not isinstance(value, dict):
        return value
    if _is_response_output(value):
        body = value["body"]
        return {**value, "body": await store.load(body)} if _is_reference(body) else value
    return {key: await restore_response_bodies(item, store=store) for key, item in value.items()}


def _is_response_output(value: dict[str, JsonValue]) -> bool:
    return (
        "body" in value
        and isinstance(value.get("status_code"), int)
        and isinstance(value.get("size_bytes"), int)
        and isinstance(value.get("headers"), dict)
    )


def _is_reference(value: JsonValue) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict) and set(value) == {REFERENCE_KEY}


def _needs_storage(value: dict[str, JsonValue], inline_limit_bytes: int) -> bool:
    if value["body"] is None:
        return False
    if _is_reference(value["body"]):
        return True
    if cast(int, value["size_bytes"]) > inline_limit_bytes:
        return True
    encoded = json.dumps(value["body"], ensure_ascii=False, separators=(",", ":")).encode()
    return len(encoded) > inline_limit_bytes
