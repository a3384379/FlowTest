"""Command-line entry point for the FlowTest MCP application gateway."""

import os
import sys
from collections.abc import Sequence

from app.mcp.server import create_mcp_server
from app.mcp.setup import DEFAULT_TOKEN_ENV, SafeArgumentParser, setup_main, token_environment_name


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["setup"]:
        setup_main(arguments[1:])
        return
    parser = SafeArgumentParser(description="FlowTest MCP application gateway")
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
        "--token-env-var",
        type=token_environment_name,
        default=DEFAULT_TOKEN_ENV,
        help="Environment variable name containing the machine token; never pass a token value.",
    )
    parser.add_argument("--host", default=os.getenv("FLOWTEST_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FLOWTEST_MCP_PORT", "8765")))
    parser.add_argument("--path", default=os.getenv("FLOWTEST_MCP_PATH", "/mcp"))
    args = parser.parse_args(arguments)
    server = create_mcp_server(
        api_base_url=args.api_base_url,
        service_account_token=os.environ.get(args.token_env_var, "")
        if args.transport == "stdio"
        else None,
        allow_process_token=args.transport == "stdio",
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
