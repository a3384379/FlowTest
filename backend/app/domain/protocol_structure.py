"""Bounded, read-only views of stored protocol contracts."""

from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from app.domain.protocols import MAX_SCHEMA_BYTES, ProtocolSchemaError


@dataclass(frozen=True, slots=True)
class InputExample:
    operation: str | None = None
    variables: dict[str, JsonValue] | None = None
    service: str | None = None
    method: str | None = None
    call_type: Literal["unary", "server_streaming"] | None = None
    request: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class StructureEntry:
    key: str
    label: str
    kind: str
    type_label: str = ""
    required: bool = False
    description: str = ""
    expandable: bool = False


@dataclass(frozen=True, slots=True)
class StructureView:
    node: str
    label: str
    entries: tuple[StructureEntry, ...]
    total: int
    offset: int
    limit: int
    example: InputExample | None = None
    notice: str | None = None
    document: str | None = None
    document_format: Literal["text", "base64"] | None = None


class StructureNodeNotFound(ValueError):
    """The requested path does not exist in this immutable contract."""


def check_structure_size(content: bytes) -> None:
    if not content or len(content) > MAX_SCHEMA_BYTES:
        raise ProtocolSchemaError("存储契约为空或超过2 MB结构浏览上限")


def structure_page(
    node: str,
    label: str,
    entries: list[StructureEntry],
    offset: int,
    limit: int,
    *,
    example: InputExample | None = None,
    notice: str | None = None,
) -> StructureView:
    if offset < 0 or not 1 <= limit <= 100:
        raise ProtocolSchemaError("结构分页范围无效")
    return StructureView(
        node,
        label,
        tuple(entries[offset : offset + limit]),
        len(entries),
        offset,
        limit,
        example,
        notice,
    )
