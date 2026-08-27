param([Parameter(Mandatory = $true)][string]$Destination)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Data = Join-Path $Root "data"
$Destination = [System.IO.Path]::GetFullPath($Destination)
if (-not [System.IO.Path]::IsPathRooted($Destination)) { throw "传输包目录必须是绝对路径" }
if (Test-Path $Destination) { throw "传输包目录已存在，拒绝覆盖：$Destination" }
if (-not (Test-Path (Join-Path $Data "flowtest.db"))) {
    throw "缺少 Standalone 数据库：$Data\flowtest.db"
}
$rootPrefix = $Root.TrimEnd('\') + '\'
if ($Destination.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "传输包不能写入应用目录内：$Destination"
}

# SQLite 导出必须在进程停止后进行，避免把 WAL 中的未提交状态漏进传输包。
& (Join-Path $PSScriptRoot "stop.ps1")

$portable = Join-Path $Root "runtime\python.exe"
if (Test-Path $portable) {
    $python = $portable
} else {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $resolved = (& $launcher.Source -3.13 -c "import sys; print(sys.executable)") 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            $candidate = ($resolved | Select-Object -Last 1).Trim()
            if (Test-Path $candidate) { $python = $candidate }
        }
    }
    if (-not $python) {
        $systemPython = Get-Command python -ErrorAction SilentlyContinue
        if ($null -ne $systemPython) {
            & $systemPython.Source -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $python = $systemPython.Source }
        }
    }
}
if (-not $python) { throw "未找到 Python 3.13；请使用包含 runtime\python.exe 的离线包" }

$env:PYTHONPATH = "$($Root)\backend;$($Root)\runtime\Lib\site-packages;$($env:PYTHONPATH)"
& $python -m app.operations.standalone_transfer export --source-data $Data --output $Destination
if ($LASTEXITCODE -ne 0) { throw "Standalone→Compact 传输包导出失败" }
Write-Host "Standalone→Compact 传输包已创建：$Destination"
Write-Host "请通过公司批准的安全渠道传输；不要复制 .env 或单独的密钥文件。"
