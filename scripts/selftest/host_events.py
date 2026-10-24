"""Fail-closed, bounded CLI JSONL metadata parsing without storing message contents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import Field
from scripts.selftest.contracts import Contract, Sha256, canonical_digest
from scripts.selftest.host_contracts import HostToolReceipt
from scripts.selftest.io import HarnessError, JsonObject, object_value, text_value


class EventReceipt(Contract):
    sequence: int = Field(ge=1, le=2000, strict=True)
    event_type: str = Field(min_length=1, max_length=40)
    event_digest: Sha256
    item_id: str | None = Field(default=None, max_length=100)
    item_type: str | None = Field(default=None, max_length=40)
    tool_name: str | None = Field(default=None, max_length=160)
    request_digest: Sha256 | None = None


@dataclass
class EventLedger:
    allowed_tools: frozenset[str]
    maximum_bytes: int = 1048576
    consumed_bytes: int = 0
    receipts: list[EventReceipt] = field(default_factory=list)
    calls: dict[str, tuple[str, str]] = field(default_factory=dict)
    completed_calls: set[str] = field(default_factory=set)
    thread_started: bool = False
    turn_started: bool = False
    turn_completed: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None

    def accept(self, encoded: bytes) -> None:
        self.consumed_bytes += len(encoded)
        if self.consumed_bytes > self.maximum_bytes or len(self.receipts) >= 2000:
            raise HarnessError("HOST_EVENT_BUDGET_EXCEEDED")
        try:
            value = object_value(json.loads(encoded))
        except (ValueError, UnicodeError):
            raise HarnessError("HOST_EVENT_JSON_INVALID") from None
        kind = text_value(value.get("type"))
        item = self._event(kind, value)
        self.receipts.append(
            EventReceipt(
                sequence=len(self.receipts) + 1,
                event_type=kind,
                event_digest=canonical_digest(value),
                item_id=text_value(item["id"]) if item else None,
                item_type=text_value(item["type"]) if item else None,
                tool_name=text_value(item["tool"]) if item.get("type") == "mcp_tool_call" else None,
                request_digest=canonical_digest(
                    {"name": item["tool"], "arguments": item.get("arguments")}
                )
                if item.get("type") == "mcp_tool_call"
                else None,
            )
        )

    def _event(self, kind: str, value: JsonObject) -> JsonObject:
        handlers = {
            "thread.started": self._thread,
            "turn.started": self._start,
            "turn.completed": self._finish,
            "item.started": self._item,
            "item.updated": self._item,
            "item.completed": self._item,
        }
        if kind not in handlers:
            raise HarnessError("HOST_EVENT_FAILED_OR_UNSUPPORTED")
        return handlers[kind](kind, value)

    def _thread(self, _kind: str, value: JsonObject) -> JsonObject:
        if self.thread_started or self.turn_started or not value.get("thread_id"):
            raise HarnessError("HOST_EVENT_ORDER_INVALID")
        self.thread_started = True
        return {}

    def _start(self, _kind: str, _value: JsonObject) -> JsonObject:
        if not self.thread_started or self.turn_started:
            raise HarnessError("HOST_EVENT_ORDER_INVALID")
        self.turn_started = True
        return {}

    def _finish(self, _kind: str, value: JsonObject) -> JsonObject:
        if not self.turn_started or self.turn_completed:
            raise HarnessError("HOST_EVENT_ORDER_INVALID")
        usage = object_value(value.get("usage"))
        self.input_tokens = _nonnegative(usage.get("input_tokens"))
        self.output_tokens = _nonnegative(usage.get("output_tokens"))
        self.turn_completed = True
        return {}

    def _item(self, kind: str, value: JsonObject) -> JsonObject:
        if not self.turn_started or self.turn_completed:
            raise HarnessError("HOST_EVENT_ORDER_INVALID")
        item = object_value(value.get("item"))
        item_type = text_value(item.get("type"))
        if item_type == "mcp_tool_call":
            self._mcp(kind, item)
        elif item_type not in {"agent_message", "reasoning", "todo_list"}:
            raise HarnessError("HOST_NON_MCP_TOOL_FORBIDDEN")
        return item

    def _mcp(self, kind: str, item: JsonObject) -> None:
        tool, identifier = text_value(item.get("tool")), text_value(item.get("id"))
        if item.get("server") != "flowtest" or tool not in self.allowed_tools:
            raise HarnessError("HOST_EVENT_TOOL_NOT_ALLOWED")
        value = (tool, canonical_digest({"name": tool, "arguments": item.get("arguments")}))
        if kind == "item.started":
            if identifier in self.calls:
                raise HarnessError("HOST_EVENT_TOOL_DUPLICATED")
            self.calls[identifier] = value
        elif self.calls.get(identifier) != value:
            raise HarnessError("HOST_EVENT_TOOL_ARGUMENTS_CHANGED")
        if kind == "item.completed":
            if identifier in self.completed_calls or item.get("status") not in {
                "completed",
                "failed",
            }:
                raise HarnessError("HOST_EVENT_TOOL_COMPLETION_INVALID")
            self.completed_calls.add(identifier)

    def reconcile(self, receipts: tuple[HostToolReceipt, ...]) -> None:
        expected = sorted((item.tool_name, item.request_digest) for item in receipts)
        if (
            not self.turn_completed
            or self.completed_calls != set(self.calls)
            or sorted(self.calls.values()) != expected
        ):
            raise HarnessError("HOST_TOOL_EVENT_RECEIPT_MISMATCH")


def _nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarnessError("HOST_USAGE_INVALID")
    return value
