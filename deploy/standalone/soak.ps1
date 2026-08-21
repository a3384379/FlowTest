param(
    [ValidateRange(1, 604800)][int]$DurationSeconds = 300,
    [ValidateRange(1, 3600)][int]$IntervalSeconds = 10,
    [ValidateRange(1, 120)][int]$TimeoutSeconds = 10,
    [string]$BindHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$probeHost = if ($BindHost -in @("0.0.0.0", "::")) { "127.0.0.1" } else { $BindHost }
$baseUrl = "http://{0}:{1}" -f $probeHost, $Port
$pidFile = Join-Path $Root ".flowtest\standalone.pid"

if (-not $OutputPath) {
    $OutputPath = Join-Path $Root ".flowtest\standalone-soak.json"
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
if (Test-Path $OutputPath) {
    throw "证据文件已存在，拒绝覆盖：$OutputPath"
}
$outputParent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputParent | Out-Null

if (-not (Test-Path $pidFile)) {
    throw "未找到 Standalone PID 文件，请先运行 deploy\standalone\start.ps1"
}

$script:StartedAt = [DateTime]::UtcNow
$script:ProbeCount = 0
$script:FailureCount = 0
$script:FailureCounts = @{}
$script:FailureSamples = New-Object System.Collections.Generic.List[object]
$script:Observations = New-Object System.Collections.Generic.List[object]
$script:InitialProcessId = $null
$script:MaxLatencyMilliseconds = 0.0
$script:ObservationsTruncated = $false
$deadline = $script:StartedAt.AddSeconds($DurationSeconds)

function Add-Failure([string]$Code, [string]$Endpoint) {
    $script:FailureCount += 1
    if ($script:FailureCounts.ContainsKey($Code)) {
        $script:FailureCounts[$Code] += 1
    } else {
        $script:FailureCounts[$Code] = 1
    }
    if ($script:FailureSamples.Count -lt 20) {
        $script:FailureSamples.Add([ordered]@{
                code = $Code
                endpoint = $Endpoint
            })
    }
}

function Get-ProcessSnapshot {
    if (-not (Test-Path $pidFile)) {
        return [pscustomobject]@{ alive = $false; process_id = $null }
    }
    try {
        $processId = [int](Get-Content -Raw $pidFile)
    } catch {
        return [pscustomobject]@{ alive = $false; process_id = $null }
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        alive = $null -ne $process
        process_id = $processId
    }
}

function Invoke-Probe([string]$Path) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $body = Invoke-RestMethod "$baseUrl$Path" -UseBasicParsing -TimeoutSec $TimeoutSeconds
        $watch.Stop()
        return [pscustomobject]@{
            ok = $true
            elapsed_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 2)
            body = $body
        }
    } catch {
        $watch.Stop()
        return [pscustomobject]@{
            ok = $false
            elapsed_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 2)
            body = $null
        }
    }
}

function Invoke-SoakProbe {
    $script:ProbeCount += 1
    $timestamp = [DateTime]::UtcNow
    $process = Get-ProcessSnapshot
    if (-not $process.alive) {
        Add-Failure "process_not_running" "process"
    } elseif ($null -eq $script:InitialProcessId) {
        $script:InitialProcessId = $process.process_id
    } elseif ($script:InitialProcessId -ne $process.process_id) {
        Add-Failure "process_id_changed" "process"
    }

    $live = Invoke-Probe "/api/v1/live"
    $ready = Invoke-Probe "/api/v1/ready"
    $profile = Invoke-Probe "/api/v1/runtime-profile"
    $latencies = @($live.elapsed_ms, $ready.elapsed_ms, $profile.elapsed_ms)
    $cycleLatency = ($latencies | Measure-Object -Maximum).Maximum
    if ($cycleLatency -gt $script:MaxLatencyMilliseconds) {
        $script:MaxLatencyMilliseconds = $cycleLatency
    }

    if (-not $live.ok) {
        Add-Failure "live_probe_failed" "/api/v1/live"
    } elseif ($live.body.status -ne "ok") {
        Add-Failure "live_status_not_ok" "/api/v1/live"
    }

    if (-not $ready.ok) {
        Add-Failure "ready_probe_failed" "/api/v1/ready"
    } elseif ($ready.body.status -ne "ok") {
        Add-Failure "ready_status_not_ok" "/api/v1/ready"
    } else {
        foreach ($checkName in @("database", "storage")) {
            if ($ready.body.checks.$checkName -ne "ok") {
                Add-Failure "ready_${checkName}_not_ok" "/api/v1/ready"
            }
        }
        if ($ready.body.checks.PSObject.Properties.Name -contains "redis") {
            Add-Failure "unexpected_redis_check" "/api/v1/ready"
        }
    }

    if (-not $profile.ok) {
        Add-Failure "profile_probe_failed" "/api/v1/runtime-profile"
    } else {
        if ($profile.body.profile -ne "standalone") {
            Add-Failure "wrong_runtime_profile" "/api/v1/runtime-profile"
        }
        if ($profile.body.worker_topology -ne "in_process") {
            Add-Failure "wrong_worker_topology" "/api/v1/runtime-profile"
        }
    }

    if ($script:Observations.Count -lt 10000) {
        $script:Observations.Add([ordered]@{
                timestamp_utc = $timestamp.ToString("o")
                process_id = $process.process_id
                process_alive = $process.alive
                live_ok = $live.ok
                ready_ok = $ready.ok
                profile_ok = $profile.ok
                max_latency_ms = $cycleLatency
            })
    } else {
        $script:ObservationsTruncated = $true
    }
}

try {
    Write-Host "开始 Standalone 长时探针：$baseUrl，持续 ${DurationSeconds}s，间隔 ${IntervalSeconds}s"
    while ([DateTime]::UtcNow -lt $deadline) {
        Invoke-SoakProbe
        $remaining = ($deadline - [DateTime]::UtcNow).TotalSeconds
        if ($remaining -le 0) { break }
        $sleepSeconds = [int][math]::Max(1, [math]::Min($IntervalSeconds, [math]::Ceiling($remaining)))
        Start-Sleep -Seconds $sleepSeconds
    }
} finally {
    $endedAt = [DateTime]::UtcNow
    $status = if ($script:FailureCount -gt 0) { "failed" } else { "passed" }
    $evidence = [ordered]@{
        schema_version = "standalone-soak-v1"
        status = $status
        profile = "standalone"
        worker_topology = "in_process"
        target = $baseUrl
        started_at_utc = $script:StartedAt.ToString("o")
        ended_at_utc = $endedAt.ToString("o")
        duration_seconds = [math]::Round(($endedAt - $script:StartedAt).TotalSeconds, 2)
        interval_seconds = $IntervalSeconds
        timeout_seconds = $TimeoutSeconds
        probe_count = $script:ProbeCount
        failure_count = $script:FailureCount
        failure_counts = $script:FailureCounts
        failure_samples = @($script:FailureSamples)
        initial_process_id = $script:InitialProcessId
        max_latency_ms = $script:MaxLatencyMilliseconds
        observations_truncated = $script:ObservationsTruncated
        observations = @($script:Observations)
        note = "仅记录健康状态、延迟和进程元数据；不记录响应体、Cookie、Token、Secret 或业务载荷。"
    }
    $evidence | ConvertTo-Json -Depth 6 | Set-Content -Path $OutputPath -Encoding UTF8
    Write-Host "Standalone 长时探针结束：$status；证据：$OutputPath"
}

if ($script:FailureCount -gt 0) {
    exit 1
}
exit 0
