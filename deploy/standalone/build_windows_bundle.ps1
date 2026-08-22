param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$PythonHome = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Destination = [System.IO.Path]::GetFullPath($Destination)
if (Test-Path $Destination) { throw "输出目录已存在，拒绝覆盖：$Destination" }
if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    throw "缺少 frontend\dist；请先在开发机执行 pnpm build"
}
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

if (-not $PythonHome) {
    $PythonHome = (& python -c "import sys; print(sys.base_prefix)").Trim()
}
$pythonExe = Join-Path $PythonHome "python.exe"
if (-not (Test-Path $pythonExe)) { throw "PythonHome 中没有 python.exe：$PythonHome" }
$runtime = Join-Path $Destination "runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
Copy-Item -Recurse -Path (Join-Path $PythonHome "*") -Destination $runtime

$builderPython = (Get-Command python -ErrorAction Stop).Source
$null = Get-Command uv -ErrorAction Stop

$requirements = Join-Path $Destination "requirements.txt"
Push-Location (Join-Path $Root "backend")
try {
    & uv export --locked --no-dev --format requirements-txt --output-file $requirements
    if ($LASTEXITCODE -ne 0) { throw "uv export 失败" }
} finally { Pop-Location }
$wheelhouse = Join-Path $Destination "packages"
New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null
$filtered = Join-Path $Destination "requirements.filtered.txt"
Get-Content $requirements | Where-Object { $_ -ne "-e ." } | Set-Content $filtered -Encoding UTF8
& $builderPython -m pip download --requirement $filtered --dest $wheelhouse --only-binary=:all:
if ($LASTEXITCODE -ne 0) { throw "Python wheels 下载失败" }
& $builderPython -m pip install --no-index --find-links $wheelhouse --target (Join-Path $runtime "Lib\site-packages") --requirement $filtered
if ($LASTEXITCODE -ne 0) { throw "Python wheels 安装失败" }
Remove-Item -LiteralPath $filtered -Force

$backendTarget = Join-Path $Destination "backend"
$frontendTarget = Join-Path $Destination "frontend\dist"
$deployTarget = Join-Path $Destination "deploy\standalone"
New-Item -ItemType Directory -Force -Path $backendTarget, $frontendTarget, $deployTarget | Out-Null
Copy-Item -Recurse -Path (Join-Path $Root "backend\*") -Destination $backendTarget
Copy-Item -Recurse -Path (Join-Path $Root "frontend\dist\*") -Destination $frontendTarget
Copy-Item -Recurse -Path (Join-Path $Root "deploy\standalone\*") -Destination $deployTarget
Copy-Item -Path (Join-Path $Root "deploy\standalone\.env.example") -Destination $deployTarget
Write-Host "Standalone Windows 离线包已生成：$Destination"
Write-Host "请将整个目录复制到云桌面，再运行 deploy\standalone\start.ps1。"
