"""Explicit local setup: diagnose an existing machine account and emit a safe template."""

import argparse
import asyncio
import json
import os
import re
from collections.abc import Sequence
from typing import Literal, Never
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.mcp.client import MCPGatewayError, MCPReadGatewayClient, _validate_base_url
from app.mcp.connection_diagnostics import ConnectionDiagnostic, connection_diagnostic
from app.schemas.mcp_connection import (
    MCP_CONNECTION_VERSION,
    MCPConnectionRequest,
    MCPConnectionResponse,
)

DEFAULT_TOKEN_ENV = "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN"  # noqa: S105 - variable name, not a secret


class SetupDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    credential_status: Literal["missing", "configured", "expired", "valid"]
    connection: MCPConnectionResponse | None = None
    diagnostic: ConnectionDiagnostic | None = None
    trace_id: str


class SetupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    diagnosis: SetupDiagnosis
    config_template: str
    configuration_written: Literal[False] = False
    transport_verified: Literal[False] = False
    verification_scope: Literal["application_gateway_machine_auth"] = (
        "application_gateway_machine_auth"
    )


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse normally echoes invalid arguments, which may contain an accidental token.
        self.print_usage()
        self.exit(2, "连接参数无效; 请查看 --help, 不要传入令牌明文。\n")


def token_environment_name(value: str) -> str:
    if re.fullmatch(r"[A-Z_][A-Z0-9_]{0,79}", value) is None:
        raise argparse.ArgumentTypeError("仅接受环境变量名称")
    return value


def setup_main(argv: Sequence[str]) -> None:
    parser = SafeArgumentParser(description="使用已授权机器账号检查连接并输出无令牌配置模板")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--mcp-url", default="http://localhost:8765/mcp")
    parser.add_argument("--token-env-var", type=token_environment_name, default=DEFAULT_TOKEN_ENV)
    args = parser.parse_args(argv)
    try:
        api_url = _validate_base_url(args.api_base_url)
        mcp_url = _validate_base_url(args.mcp_url)
    except ValueError:
        parser.error("invalid endpoint")
    result = SetupResult(
        diagnosis=asyncio.run(_diagnose(api_url, args.token_env_var)),
        config_template=_configuration(args.transport, api_url, mcp_url, args.token_env_var),
    )
    print(result.model_dump_json(indent=2))


async def _diagnose(api_url: str, token_env: str) -> SetupDiagnosis:
    token = os.environ.get(token_env)
    if not token:
        return SetupDiagnosis(
            credential_status="missing",
            diagnostic=ConnectionDiagnostic(
                code="AUTH_REQUIRED", next_action="configure_machine_account", setup_required=True
            ),
            trace_id=uuid4().hex,
        )
    try:
        async with MCPReadGatewayClient(
            base_url=api_url,
            token=token,
            client_version=MCP_CONNECTION_VERSION,
        ) as client:
            response = await client.inspect_connection(
                MCPConnectionRequest(expected_contract_version=MCP_CONNECTION_VERSION)
            )
    except MCPGatewayError as error:
        diagnostic = connection_diagnostic(error)
        return SetupDiagnosis(
            credential_status="expired" if diagnostic.code == "AUTH_EXPIRED" else "configured",
            diagnostic=diagnostic,
            trace_id=error.trace_id,
        )
    return SetupDiagnosis(
        credential_status="valid", connection=response, trace_id=response.trace_id
    )


def _configuration(transport: str, api_url: str, mcp_url: str, token_env: str) -> str:
    # JSON quoted strings are also valid TOML basic strings for these validated values.
    quote = json.dumps
    if transport == "streamable-http":
        return (
            f"[mcp_servers.flowtest]\nurl = {quote(mcp_url)}\n"
            f"bearer_token_env_var = {quote(token_env)}\n"
        )
    arguments = ["--transport", "stdio", "--api-base-url", api_url, "--token-env-var", token_env]
    return (
        '[mcp_servers.flowtest]\ncommand = "flowtest-mcp"\n'
        f"args = {quote(arguments)}\nenv_vars = [{quote(token_env)}]\n"
    )
