"""Command-line entry point for the FlowTest MCP read gateway."""

import argparse
import os
from collections.abc import Sequence

from app.mcp.server import create_mcp_server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="FlowTest read-only MCP gateway")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("FLOWTEST_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("FLOWTEST_MCP_API_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument(
        "--token",
        default=os.getenv("FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN", ""),
        help="Service account token; prefer FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN for automation.",
    )
    parser.add_argument("--host", default=os.getenv("FLOWTEST_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FLOWTEST_MCP_PORT", "8765")))
    parser.add_argument("--path", default=os.getenv("FLOWTEST_MCP_PATH", "/mcp"))
    args = parser.parse_args(argv)
    server = create_mcp_server(
        api_base_url=args.api_base_url,
        service_account_token=args.token or None,
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        json_response=True,
        stateless_http=True,
    )
