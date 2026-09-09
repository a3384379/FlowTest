[CmdletBinding()]
param(
    [ValidateSet("stdio", "streamable-http")][string]$Transport = "stdio",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [ValidatePattern('^[A-Za-z_][A-Za-z0-9_]*$')][string]$TokenEnvVar = "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN",
    [string]$BindHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [string]$McpPath = "/mcp",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root "runtime\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "缺少内置 Python 运行时：runtime\python.exe"
}
$env:PYTHONPATH = "$($Root)\backend;$($Root)\runtime\Lib\site-packages;$($env:PYTHONPATH)"

if ($ValidateOnly) {
    $validation = @'
import asyncio
from app.mcp.server import create_mcp_server

required = {
    "flowtest.plan_integration_test",
    "flowtest.validate_integration_plan",
    "flowtest.compile_integration_flowspec",
    "flowtest.propose_flow_draft",
}
tools = asyncio.run(create_mcp_server(service_account_token="validation-only").list_tools())
available = {tool.name for tool in tools}
missing = sorted(required - available)
if missing:
    raise SystemExit(f"missing MCP tools: {', '.join(missing)}")
print(f"FlowTest MCP 验证通过：{len(available)} 个工具，集成流程工具完整。")
'@
    & $Python -c $validation
    if ($LASTEXITCODE -ne 0) { throw "FlowTest MCP 离线验证失败" }
    exit 0
}

if ($Transport -eq "stdio") {
    $token = [Environment]::GetEnvironmentVariable($TokenEnvVar)
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "缺少机器账号环境变量 $TokenEnvVar；请先在用户环境或凭据工具中配置，不要把 Token 写入脚本。"
    }
}

$arguments = @(
    "-m", "app.mcp.cli",
    "--transport", $Transport,
    "--api-base-url", $ApiBaseUrl,
    "--token-env-var", $TokenEnvVar,
    "--host", $BindHost,
    "--port", $Port,
    "--path", $McpPath
)
& $Python @arguments
exit $LASTEXITCODE
