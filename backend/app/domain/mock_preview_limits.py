import json
from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue


class MockPreviewError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        field: str,
        pointer: str = "",
        route_id: UUID | None = None,
        code: str = "INVALID_MOCK_PREVIEW",
    ) -> None:
        super().__init__(message)
        self.field = field
        self.pointer = pointer
        self.route_id = route_id
        self.code = code


@dataclass(frozen=True, slots=True)
class MockPreviewLimits:
    source_bytes: int = 65_536
    source_depth: int = 32
    source_nodes: int = 4_096
    output_bytes: int = 2 * 1024 * 1024
    output_depth: int = 64
    output_nodes: int = 8_192
    candidate_count: int = 500
    warning_count: int = 20
    metadata_bytes: int = 512 * 1024
    metadata_nodes: int = 32_768


class MockJsonBudget:
    def __init__(
        self,
        *,
        maximum_bytes: int,
        maximum_depth: int,
        maximum_nodes: int,
        field: str,
        route_id: UUID | None = None,
    ) -> None:
        self._remaining = maximum_bytes
        self._maximum_depth = maximum_depth
        self._maximum_nodes = maximum_nodes
        self._field = field
        self._route_id = route_id
        self._nodes = 0

    def check(self, value: JsonValue, *, depth: int = 0, pointer: str = "") -> None:
        self._nodes += 1
        if depth > self._maximum_depth or self._nodes > self._maximum_nodes:
            self._fail("预览数据超过深度或节点数量上限", pointer)
        if isinstance(value, dict):
            self._check_object(value, depth, pointer)
        elif isinstance(value, list):
            self._check_array(value, depth, pointer)
        else:
            self._consume_literal(value, pointer)

    def _check_object(self, value: dict[str, JsonValue], depth: int, pointer: str) -> None:
        self._reserve(2, pointer)
        for index, (name, child) in enumerate(value.items()):
            if len(name) > 256:
                self._fail("预览对象键名超过256字符上限", pointer)
            self._consume_literal(name, pointer)
            self._reserve(2 + (2 if index else 0), pointer)
            self.check(child, depth=depth + 1, pointer=json_pointer(pointer, name))

    def _check_array(self, value: list[JsonValue], depth: int, pointer: str) -> None:
        self._reserve(2, pointer)
        for index, child in enumerate(value):
            self._reserve(2 if index else 0, pointer)
            self.check(child, depth=depth + 1, pointer=json_pointer(pointer, str(index)))

    def _consume_literal(self, value: JsonValue, pointer: str) -> None:
        if isinstance(value, str) and len(value) > self._remaining:
            self._fail("预览数据超过字节上限", pointer)
        if isinstance(value, int) and value.bit_length() > max(self._remaining, 0) * 4:
            self._fail("预览数值超过字节上限", pointer)
        try:
            size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except (UnicodeEncodeError, ValueError) as error:
            raise MockPreviewError(
                "预览仅支持可编码的标准JSON值",
                field=self._field,
                pointer=pointer,
                route_id=self._route_id,
            ) from error
        self._reserve(size, pointer)

    def _reserve(self, count: int, pointer: str) -> None:
        self._remaining -= count
        if self._remaining < 0:
            self._fail("预览数据超过字节上限", pointer)

    def _fail(self, message: str, pointer: str) -> None:
        raise MockPreviewError(
            message,
            field=self._field,
            pointer=pointer,
            route_id=self._route_id,
            code="MOCK_PREVIEW_LIMIT_EXCEEDED",
        )


def json_pointer(parent: str, name: str) -> str:
    escaped = name.replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"
