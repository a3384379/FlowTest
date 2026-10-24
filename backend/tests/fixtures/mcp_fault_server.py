"""Mechanical real-SDK fixture; not a candidate-product acceptance oracle."""

import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field


class Inspection(BaseModel):
    expected_contract_version: str | None = Field(default=None, max_length=80)


def main() -> None:
    server = MCPServer("owned-transport-characterization")

    @server.tool(
        name="flowtest.inspect_connection",
        description="synthetic-catalog-"
        + "x" * int(os.environ.get("FLOWTEST_FAULT_FIXTURE_CATALOG_PADDING", "0")),
    )
    def inspect(request: Inspection) -> dict[str, str]:
        return {"status": "ok"}

    @server.tool(name="flowtest.propose_test_design")
    def propose(project_id: str, idempotency_key: str, design: dict) -> dict[str, dict[str, str]]:
        path = Path(os.environ["FLOWTEST_FAULT_FIXTURE_JOURNAL"])
        with path.open("a") as output:
            output.write(json.dumps({"key": idempotency_key}) + "\n")
        return {"data": {"id": "edc0cf14-a78b-43c1-b019-7285da6bcc65"}}

    @server.tool(name="flowtest.large_result")
    def large_result() -> str:
        return "x" * 300000

    if os.environ.get("FLOWTEST_FAULT_FIXTURE_TRANSPORT") == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=int(os.environ["FLOWTEST_FAULT_FIXTURE_PORT"]),
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
        )


if __name__ == "__main__":
    main()
