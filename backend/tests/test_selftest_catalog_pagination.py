"""Discovery consumes every returned page and hashes complete tool schemas."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import Tool

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest.contracts import canonical_digest
from scripts.selftest.io import HarnessError, read_json
from scripts.selftest.mcp_protocol_runner import ProtocolClient


class Session:
    protocol_version = "2026-07-28"

    def __init__(self, pages):
        self.pages = pages
        self.cursors = []

    async def discover(self):
        return SimpleNamespace(model_dump=lambda **_: {"server": "synthetic-schema-fixture"})

    async def list_tools(self, params=None):
        self.cursors.append(None if params is None else params.cursor)
        return self.pages[min(len(self.cursors) - 1, len(self.pages) - 1)]


def tool(name, value=1):
    return Tool(
        name=name,
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {"value": {"const": value}}},
    )


@pytest.mark.asyncio
async def test_real_tool_models_preserve_all_pages_and_full_schema_digest(tmp_path):
    tools = [tool("first"), tool("second")]
    session = Session(
        [
            SimpleNamespace(tools=tools[:1], next_cursor="page-2"),
            SimpleNamespace(tools=tools[1:], next_cursor=None),
        ]
    )
    client = ProtocolClient(session, "streamable-http", "catalog-pagination", tmp_path)
    await client.discover()
    assert session.cursors == [None, "page-2"]
    assert client.tools == {"first", "second"}
    expected = [item.model_dump(mode="json", by_alias=True) for item in tools]
    saved = read_json(tmp_path / "mcp-catalog.json")
    assert saved["tools"] == expected
    assert client.catalog_digest == canonical_digest(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,code", [("cycle", "CATALOG_TRUNCATED"), ("duplicate", "DUPLICATE_TOOL")]
)
async def test_incomplete_or_repeated_catalog_cannot_become_discovered_tools(tmp_path, mode, code):
    session = Session(
        [
            SimpleNamespace(tools=[tool("same")], next_cursor="page-2"),
            SimpleNamespace(
                tools=[tool("same")], next_cursor="page-2" if mode == "cycle" else None
            ),
        ]
    )
    client = ProtocolClient(session, "streamable-http", "catalog-rejection", tmp_path)
    with pytest.raises(HarnessError, match=code):
        await client.discover()
    assert not (tmp_path / "mcp-catalog.json").exists()
    assert len(session.cursors) <= 20


@pytest.mark.asyncio
async def test_same_tool_name_with_changed_output_contract_changes_catalog_identity(tmp_path):
    digests = []
    for value in (1, 2):
        session = Session([SimpleNamespace(tools=[tool("same", value)], next_cursor=None)])
        client = ProtocolClient(session, "streamable-http", "schema-change", tmp_path / str(value))
        await client.discover()
        assert client.tools == {"same"}
        digests.append(client.catalog_digest)
    assert digests[0] != digests[1]
