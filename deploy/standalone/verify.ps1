param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:$Port"
$ready = Invoke-RestMethod "$base/api/v1/ready"
$profile = Invoke-RestMethod "$base/api/v1/runtime-profile"
$frontend = Invoke-WebRequest "$base/" -UseBasicParsing
if ($ready.status -ne "ok") { throw "Standalone Readiness 未通过" }
if ($profile.profile -ne "standalone" -or $profile.worker_topology -ne "in_process") {
    throw "运行档位不是 standalone/in_process"
}
if ($null -ne $ready.checks.redis) { throw "Standalone 不应依赖 Redis" }
if ($frontend.StatusCode -ne 200) { throw "Web 首页不可访问" }
Write-Host "Standalone 验收通过：SQLite、本地存储、进程内任务、Web 首页。"
