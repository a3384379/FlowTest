param([Parameter(Mandatory = $true)][string]$Source)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Source = [System.IO.Path]::GetFullPath($Source)
$sourceData = Join-Path $Source "data"
$targetData = Join-Path $Root "data"
if (-not (Test-Path $sourceData)) { throw "备份目录缺少 data：$Source" }
if (-not (Test-Path (Join-Path $Source "manifest.json"))) {
    throw "备份目录缺少 manifest.json：$Source"
}
$rootPrefix = $Root.TrimEnd('\') + '\'
if ($Source.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "恢复源不能位于应用目录内：$Source"
}

& (Join-Path $PSScriptRoot "stop.ps1")
if (Test-Path $targetData) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $previous = Join-Path $Root ".flowtest\data-before-restore-$stamp"
    New-Item -ItemType Directory -Force -Path (Split-Path $previous) | Out-Null
    Move-Item -LiteralPath $targetData -Destination $previous
    Write-Host "原数据已保留：$previous"
}
Copy-Item -Recurse -Path $sourceData -Destination $targetData
Write-Host "Standalone 数据已恢复。请确认 .env 中的 FLOWTEST_DATA_ENCRYPTION_KEY 与备份一致。"
