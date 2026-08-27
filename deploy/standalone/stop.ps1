$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PidFile = Join-Path $Root ".flowtest\standalone.pid"
if (-not (Test-Path $PidFile)) {
    Write-Host "FlowTest 当前未运行。"
    exit 0
}
$processId = [int](Get-Content -Raw $PidFile)
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($null -ne $process) {
    Stop-Process -Id $processId
    $process.WaitForExit(10000)
}
Remove-Item -LiteralPath $PidFile -Force
Write-Host "FlowTest Standalone 已停止。"
