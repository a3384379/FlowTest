param([Parameter(Mandatory = $true)][string]$Destination)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Data = Join-Path $Root "data"
$Destination = [System.IO.Path]::GetFullPath($Destination)
if (-not [System.IO.Path]::IsPathRooted($Destination)) { throw "备份目录必须是绝对路径" }
if (Test-Path $Destination) { throw "备份目录已存在，拒绝覆盖：$Destination" }
if (-not (Test-Path $Data)) { throw "数据目录不存在：$Data" }
$rootPrefix = $Root.TrimEnd('\') + '\'
if ($Destination.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "备份目录不能位于应用目录内：$Destination"
}

& (Join-Path $PSScriptRoot "stop.ps1")
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Copy-Item -Recurse -Path $Data -Destination (Join-Path $Destination "data")
$manifest = [ordered]@{
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    profile = "standalone"
    includes = @("data\flowtest.db", "data\artifacts")
    env_file = "excluded"
}
$manifest | ConvertTo-Json | Set-Content -Path (Join-Path $Destination "manifest.json") -Encoding UTF8
Write-Host "Standalone 备份已创建：$Destination（不包含 .env 和密钥）"
