import pytest
from pydantic import JsonValue

from app.domain.workflow_output_refs import (
    REFERENCE_KEY,
    compact_response_bodies,
    restore_response_bodies,
)


class MemoryBodyStore:
    def __init__(self) -> None:
        self.bodies: dict[str, JsonValue] = {}

    async def store(self, body: JsonValue) -> dict[str, JsonValue]:
        key = str(len(self.bodies))
        self.bodies[key] = body
        return {REFERENCE_KEY: {"key": key}}

    async def load(self, reference: dict[str, JsonValue]) -> JsonValue:
        marker = reference[REFERENCE_KEY]
        assert isinstance(marker, dict)
        return self.bodies[str(marker["key"])]


@pytest.mark.asyncio
async def test_large_response_body_is_referenced_without_touching_untrusted_nested_keys() -> None:
    store = MemoryBodyStore()
    user_body: JsonValue = {
        "items": [1, 2],
        "status_code": 200,
        "size_bytes": 99999,
        "headers": {},
        "body": {"user_data": "kept"},
    }
    output: JsonValue = {
        "branches": [
            {
                "nodes": [
                    {
                        "output": {
                            "status_code": 200,
                            "headers": {},
                            "body": user_body,
                            "size_bytes": 5000,
                        }
                    }
                ]
            }
        ]
    }

    compacted = await compact_response_bodies(output, store=store, inline_limit_bytes=1024)
    assert compacted["branches"][0]["nodes"][0]["output"]["body"] == {REFERENCE_KEY: {"key": "0"}}
    assert store.bodies == {"0": user_body}
    assert await restore_response_bodies(compacted, store=store) == output


@pytest.mark.asyncio
async def test_small_body_is_inlined_and_user_supplied_reference_marker_is_escaped() -> None:
    store = MemoryBodyStore()
    output: JsonValue = {
        "status_code": 200,
        "headers": {},
        "size_bytes": 4,
        "body": {"ok": True},
    }
    assert await compact_response_bodies(output, store=store, inline_limit_bytes=1024) == output
    assert store.bodies == {}
    spoofed: JsonValue = {**output, "body": {REFERENCE_KEY: {"key": "user-value"}}}
    compacted = await compact_response_bodies(spoofed, store=store, inline_limit_bytes=1024)
    assert compacted["body"] == {REFERENCE_KEY: {"key": "0"}}
    assert await restore_response_bodies(compacted, store=store) == spoofed
