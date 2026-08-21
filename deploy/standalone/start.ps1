param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StateDir = Join-Path $Root ".flowtest"
$LogDir = Join-Path $Root "logs"
$EnvFile = Join-Path $Root ".env"
$ExampleEnv = Join-Path $PSScriptRoot ".env.example"
$PidFile = Join-Path $StateDir "standalone.pid"

function New-Secret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($buffer) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($buffer)
}

function Ensure-EnvFile {
    if (Test-Path $EnvFile) { return }
    if (-not (Test-Path $ExampleEnv)) { throw "缺少 deploy\standalone\.env.example" }
    $content = Get-Content -Raw $ExampleEnv
    $content = $content.Replace(
        "FLOWTEST_SECRET_KEY=replace-on-first-start",
        "FLOWTEST_SECRET_KEY=$(New-Secret 32)"
    )
    $content = $content.Replace(
        "FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD=replace-on-first-start",
        "FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD=$(New-Secret 24)"
    )
    $content = $content.Replace(
        "FLOWTEST_DATA_ENCRYPTION_KEY=replace-on-first-start",
        "FLOWTEST_DATA_ENCRYPTION_KEY=$(New-Secret 32)"
    )
    Set-Content -Path $EnvFile -Value $content -Encoding UTF8 -NoNewline
    Write-Host "已创建 .env；管理员初始密码已写入本机文件，请登录后立即修改。"
}

function Find-Python {
    $portable = Join-Path $Root "runtime\python.exe"
    if (Test-Path $portable) { return $portable }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $resolved = (& $launcher.Source -3.13 -c "import sys; print(sys.executable)") 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            $candidate = ($resolved | Select-Object -Last 1).Trim()
            if (Test-Path $candidate) { return $candidate }
        }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $python.Source }
    }
    throw "未找到 Python 3.13。请使用个人电脑构建包含 runtime\python.exe 的 Standalone 离线包。"
}

Ensure-EnvFile
New-Item -ItemType Directory -Force -Path $StateDir, $LogDir, (Join-Path $Root "data") | Out-Null
$python = Find-Python
$env:FLOWTEST_RUNTIME_PROFILE = "standalone"
$env:FLOWTEST_DATA_DIR = Join-Path $Root "data"
$env:FLOWTEST_FRONTEND_DIST_DIR = Join-Path $Root "frontend\dist"
$env:PYTHONPATH = "$($Root)\backend;$($Root)\runtime\Lib\site-packages;$($env:PYTHONPATH)"

if (Test-Path $PidFile) {
    $oldPid = [int](Get-Content -Raw $PidFile)
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        Write-Host "FlowTest 已在运行，PID=$oldPid"
        exit 0
    }
    Remove-Item -LiteralPath $PidFile -Force
}

$stdout = Join-Path $LogDir "standalone.out.log"
$stderr = Join-Path $LogDir "standalone.err.log"
$arguments = @("-m", "uvicorn", "app.main:app", "--host", $BindHost, "--port", $Port)
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $Root `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Set-Content -Path $PidFile -Value $process.Id -Encoding ASCII -NoNewline
if ($process.HasExited) {
    Get-Content -Tail 40 $stderr -ErrorAction SilentlyContinue
    throw "FlowTest 启动失败，详见 logs\standalone.err.log"
}
$ready = $false
$deadline = [DateTime]::UtcNow.AddSeconds(60)
while (-not $ready -and [DateTime]::UtcNow -lt $deadline) {
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:$Port/api/v1/ready" -UseBasicParsing
        $ready = $response.StatusCode -eq 200
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) {
    Get-Content -Tail 60 $stderr -ErrorAction SilentlyContinue
    throw "FlowTest 启动超时，详见 logs\standalone.err.log"
}
Write-Host "FlowTest Standalone 已启动：http://$BindHost`:$Port"
Write-Host "验证命令：powershell -ExecutionPolicy Bypass -File deploy\standalone\verify.ps1 -Port $Port"
