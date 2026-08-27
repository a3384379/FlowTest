"""Pure contracts for durable execution commands and checkpoints."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import cast

from pydantic import JsonValue

DURABLE_EXECUTION_SCHEMA_VERSION = "s43-durable-v1"


class ExecutionCommandType(StrEnum):
    START = "start"
    RESUME = "resume"
    RETRY = "retry"
    CANCEL = "cancel"


class ExecutionCommandStatus(StrEnum):
    ACCEPTED = "accepted"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ExecutionCheckpointStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


def is_resumable_checkpoint(status: str) -> bool:
    return status in {
        ExecutionCheckpointStatus.PASSED.value,
        ExecutionCheckpointStatus.SKIPPED.value,
    }


def checkpoint_input_hash(node_id: str, context_snapshot: object) -> str:
    return _digest({"node_id": node_id, "context": context_snapshot})


def checkpoint_output_digest(output: JsonValue) -> str:
    return _digest(output)


def request_hash(payload: object) -> str:
    return _digest(payload)


def json_object(value: object) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
