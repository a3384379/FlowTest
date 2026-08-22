[CmdletBinding()]
param(
    [string]$BindHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [ValidateRange(1, 1024)][int]$MinimumFreeGb = 10,
    [switch]$AllowSystemPython,
    [switch]$SkipPortCheck
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Add-PreflightError([string]$Message) {
    $script:errors.Add($Message)
}

function Add-PreflightWarning([string]$Message) {
    $script:warnings.Add($Message)
}

function Require-Path([string]$RelativePath, [string]$Description) {
    $path = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $path)) {
        Add-PreflightError("缺少$Description：$RelativePath")
    }
}

function Test-DirectoryWritable([string]$Path, [string]$Description) {
    try {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
        $probe = Join-Path $Path (".preflight-{0}.tmp" -f ([guid]::NewGuid().ToString("N")))
        Set-Content -LiteralPath $probe -Value "flowtest-preflight" -Encoding ASCII -NoNewline
        Remove-Item -LiteralPath $probe -Force
    } catch {
        Add-PreflightError("$Description不可写：$Path")
    }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Add-PreflightError("Standalone Windows 包只能在 Windows 上运行")
} elseif (-not [Environment]::Is64BitOperatingSystem) {
    Add-PreflightError("需要 64 位 Windows；当前系统为 32 位")
}

$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
$osSummary = if ($null -ne $os) {
    "{0} {1} (Build {2})" -f $os.Caption, $os.Version, $os.BuildNumber
} else {
    [Environment]::OSVersion.Version.ToString()
}

Require-Path "backend\app\main.py" "后端代码"
Require-Path "frontend\dist\index.html" "前端静态文件"
Require-Path "deploy\standalone\start.ps1" "启动脚本"
Require-Path "deploy\standalone\.env.example" "环境变量模板"

$portablePython = Join-Path $Root "runtime\python.exe"
$python = $null
if (Test-Path -LiteralPath $portablePython) {
    $python = $portablePython
} elseif ($AllowSystemPython) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $systemPython) { $python = $systemPython.Source }
}
if ($null -eq $python) {
    Add-PreflightError("未找到内置 Python 3.13；请使用完整离线包，或显式传入 -AllowSystemPython")
} else {
    $versionOutput = (& $python --version 2>&1 | Out-String).Trim()
    if ($versionOutput -notmatch "Python 3\.13(?:\.\d+)?") {
        Add-PreflightError("Python 版本不受支持：$versionOutput；需要 3.13.x")
    }
    if (Test-Path -LiteralPath (Join-Path $Root "runtime\Lib\site-packages")) {
        $env:PYTHONPATH = "$($Root)\backend;$($Root)\runtime\Lib\site-packages"
    }
    & $python -c "import fastapi, sqlalchemy, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Add-PreflightError("Python 依赖不完整；请重新生成 Standalone 离线包")
    }
}

$dataPath = Join-Path $Root "data"
$logPath = Join-Path $Root "logs"
$statePath = Join-Path $Root ".flowtest"
Test-DirectoryWritable $dataPath "数据目录"
Test-DirectoryWritable $logPath "日志目录"
Test-DirectoryWritable $statePath "运行状态目录"

$envFile = Join-Path $Root ".env"
if (Test-Path -LiteralPath $envFile) {
    $requiredKeys = @(
        "FLOWTEST_SECRET_KEY",
        "FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD",
        "FLOWTEST_DATA_ENCRYPTION_KEY"
    )
    $envKeys = @{}
    foreach ($line in (Get-Content -LiteralPath $envFile)) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $envKeys[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'")
        }
    }
    foreach ($key in $requiredKeys) {
        if (-not $envKeys.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($envKeys[$key]) -or
            $envKeys[$key] -match '^replace-on-first-start$') {
            Add-PreflightError(".env 缺少有效的 $key（不会输出 Secret 内容）")
        }
    }
} else {
    Add-PreflightWarning("尚未找到 .env；首次 start.ps1 会生成随机密钥，并使用 Standalone 初始账号 admin/admin")
}

$drive = New-Object -TypeName System.IO.DriveInfo -ArgumentList ([System.IO.Path]::GetPathRoot($Root))
$freeGb = [math]::Round($drive.AvailableFreeSpace / 1GB, 2)
if ($freeGb -lt $MinimumFreeGb) {
    Add-PreflightError("磁盘剩余空间不足：${freeGb} GB，至少需要 ${MinimumFreeGb} GB")
}

if (-not $SkipPortCheck) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        Add-PreflightError("端口 $Port 已被占用；请停止占用进程或改用 -Port")
    }
}

$status = if ($errors.Count -eq 0) { "passed" } else { "failed" }
[ordered]@{
    schema_version = "standalone-preflight-v1"
    status = $status
    root = $Root
    os = $osSummary
    bind_host = $BindHost
    port = $Port
    free_disk_gb = $freeGb
    python = if ($null -ne $python) { $python } else { $null }
    warnings = @($warnings.ToArray())
    errors = @($errors.ToArray())
} | ConvertTo-Json -Depth 4 | Write-Host

if ($errors.Count -gt 0) {
    exit 1
}
Write-Host "Standalone 安装前检查通过。"
