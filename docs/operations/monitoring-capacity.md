# 监控、告警与容量门槛

## 指标

Prometheus 抓取 `/api/v1/metrics`：

- `flowtest_info`：当前应用版本。
- `flowtest_http_requests_total`：按 method、归一化 path、status 统计请求。
- `flowtest_http_request_duration_seconds`：HTTP 延迟直方图。
- `flowtest_execution_records`：API、Workflow、Test Plan 当前持久化状态数量。
- `flowtest_execution_metrics_available`：数据库执行指标是否可采集。
- `flowtest_celery_queue_depth`：General、Data、AI 三个逻辑队列（含优先级分片）的等待数。
- `flowtest_celery_workers_active`：60 秒内持续上报心跳的 Worker 数。
- `flowtest_celery_tasks_total`：按 succeeded、failed、retried 统计的 Worker 任务结果。
- `flowtest_celery_metrics_available`：Redis 队列与 Worker 指标是否可采集。
- `flowtest_runner_records`：按 online、offline、draining、disabled 统计的远程 Runner 数。
- `flowtest_runner_tasks`：按 queued、leased、completed、failed 统计的 PostgreSQL Runner Task。
- `flowtest_runner_active_leases`：当前 Active Lease 数，无 UUID、Token 或用户输入标签。

建议告警：readiness 连续 2 分钟失败、5xx 比例 5 分钟超过 2%、P95 超过 1 秒、
失败执行持续升高、执行指标不可用、Worker 健康检查失败、磁盘使用率超过 80%。
Runner Fabric 还应告警：Pool 有排队但 2 分钟内无 online Runner、Active Lease 长时间超过
Pool 并发上限、expired/failed Event 突增、单个 Runner 心跳超时以及控制面 409/429/5xx 突增。

## 分布式追踪与 Grafana

可选观测栈不会随默认 Compose 启动。启用后，API 和 Worker 将 W3C Trace Context 贯穿
FastAPI → Celery → Workflow → Node，并由 OTel Collector 写入 Tempo：

```bash
FLOWTEST_OTEL_ENABLED=true docker compose --profile observability up -d --build --wait
```

- Grafana：`http://localhost:3001`，本地默认用户 `admin`，密码由 `GRAFANA_ADMIN_PASSWORD` 设置。
- Prometheus：`http://localhost:9090`。
- Tempo：`http://localhost:3200`。
- OTel HTTP/gRPC：`localhost:4318` / `localhost:4317`。

生产环境必须修改 Grafana 密码，并根据数据量调整 Tempo/Prometheus 保留期。Trace 标签只允许
平台定义的 Execution、Project、Workflow 版本和 Node 元数据，禁止加入 Token、Credential、
请求正文或用户输入标签。

## 可复现容量门槛

```bash
uv run --project backend python scripts/capacity_s11.py
uv run --project backend python scripts/capacity_workflow.py
uv run --project backend python scripts/capacity_s19.py
uv run --project backend python scripts/capacity_s29.py
```

默认先用 30 个请求预热 HTTP 连接池，再对 `/api/v1/live` 发出 300 个请求、并发 30，
要求零失败且稳态 P95 不超过 500 ms。预热只排除 CI 主机的一次性建连抖动；任一预热请求失败仍会使门禁失败。
可通过 `FLOWTEST_CAPACITY_REQUESTS`、`FLOWTEST_CAPACITY_CONCURRENCY` 和
`FLOWTEST_CAPACITY_P95_SECONDS` 调整。每次变更 Worker 并发、资源限制或宿主机规格后重新执行。
GitHub 托管 Runner 保持 300 请求、并发 30 和零失败要求，使用 1 秒兼容上限；正式参考环境
仍必须通过默认 500 ms 门槛，托管 Runner 的结果不能替代参考硬件记录。

## V1.0 基线结果

2026-08-09 在 Docker Desktop ARM64 单机 Compose 环境执行：300 请求、并发 30、0 失败，
耗时 0.556 秒，P95 0.153 秒，吞吐约 539.25 req/s。该数据是本地健康端点基线，不能替代
真实业务工作流容量测试；生产宿主机或资源限制变化后必须重新记录。

S12 新增 `capacity_workflow.py`，它会创建并发布一个包含真实 HTTP API 节点的 Workflow，S19 默认以
并发 100 完成 100 次持久化、入队、Worker 执行和结果查询。门槛默认要求零失败且端到端 P95 不超过
10 秒；可通过 `FLOWTEST_CAPACITY_WORKFLOW_REQUESTS`、
`FLOWTEST_CAPACITY_WORKFLOW_CONCURRENCY` 和 `FLOWTEST_CAPACITY_WORKFLOW_P95_SECONDS` 调整。
GitHub 托管 Runner 并非 8C/16G 参考环境，因此 CI 保持相同的 100 并发、零失败要求，使用
60 秒兼容上限；正式发布仍必须在参考硬件上通过默认 10 秒门槛，CI 结果不能替代该记录。

## V1.1 真实 Workflow 基线

2026-08-09 在 Docker Desktop ARM64 单机 Compose 环境执行：20 个持久化 Workflow
执行、并发 5、0 失败，耗时 0.724 秒，端到端 P95 0.270 秒，吞吐约
27.64 execution/s。该基线使用 Python 3.13.15 镜像，覆盖 API 请求、快照持久化、Celery
入队、Worker 调度、
HTTP 节点和终态查询；它不代表 S19 的 8C/16G、100/1000 最终容量承诺。

## V1.8 质量与队列容量门槛

`capacity_workflow.py` 的 S19 默认值为 100 个真实 Workflow、请求侧并发 100；
`capacity_s19.py` 会停止 General/Data/AI Worker，创建并确认 1000 个唯一且持久化的 queued Run，
再恢复 Worker 并等待全部终态。验收要求：1000 个 Run ID 唯一、1000 个 Workflow Execution ID
唯一、零失败、零重复终态。默认完成超时为 900 秒，可使用 `FLOWTEST_S19_QUEUE_TASKS` 和
`FLOWTEST_S19_QUEUE_TIMEOUT_SECONDS` 在诊断环境缩小或调整，但 CI 发布门槛始终使用默认 1000。
入队和详情读取默认使用 10 个并发 API 请求，避免压测客户端超过默认数据库连接池；可通过
`FLOWTEST_S19_API_CONCURRENCY` 在 1～50 范围内调整。该参数只控制 API 请求速率，不降低
1000 个持久排队任务的验收目标。

## V3 S22 Capability 兼容容量基线

2026-08-12 在 ARM64 Docker Desktop 29.6.2 上执行，宿主机为 10 核/16 GiB，Docker VM 可用
10 核/约 8 GiB。测试使用相同的真实 HTTP Workflow、100 个持久执行、请求侧并发 100；每轮均验证
Execution 唯一终态，测试结束后恢复默认单 Worker：

| General Worker 数 | 失败 | 总耗时 | 端到端 P95 | 吞吐 |
|---:|---:|---:|---:|---:|
| 1 | 0 | 3.644 秒 | 3.442 秒 | 27.44 execution/s |
| 4 | 0 | 3.178 秒 | 3.100 秒 | 31.47 execution/s |

该结果验证 S22 Legacy Adapter、Capability Snapshot 和统一 NodeResult 未破坏单机吞吐，并形成
四 Worker 的早期对照基线；它不是 S29 远程 Runner Lease/Fencing 的 500/5000 分布式容量承诺。

## V3 S29 Runner Fabric 容量与故障门槛

`capacity_s29.py` 固定以 10 个服务 Token 提交 5000 个唯一 Workflow Execution，在 Runner
启动前由 PostgreSQL 确认 5000 个 queued Task、5000 个唯一 Execution ID 和 5000 份加密计划。
脚本随后只删除本次夹具的 4500 个 Execution，保留 500 个样本交由两个独立身份、各 250
并发的 Runner 完成。退出条件是：500/500 Workflow/Task 通过、1000 个唯一节点终态、0 重复、
0 Active Lease、0 Artifact 冲突且两个 Worker 都被实际使用。任何 PostgreSQL deadlock、控制面
429/5xx 或 Runner 拒绝日志都使本轮证据无效，必须用新夹具重跑。

2026-08-12 在 ARM64 Docker Desktop 29.6.2 上通过最终门槛：宿主机 10 核/16 GiB，Docker VM
10 核/约 7.75 GiB；5000 个唯一持久任务和加密计划完整，提交 P95 2.141591 秒；
500 个 Workflow 在 144.893 秒内全部通过，1000 个节点终态0 重复、0 Active Lease、0 制品冲突，
两个 Worker 均承担任务；从最终镜像启动到结束无 deadlock、429、500 或 Runner 内部失败。

`smoke_s29.py` 是独立故障门槛：Agent A 认领后被强制停止，Lease 过期后 Agent B 必须以
更高 Fence 接管，最终只允许一组节点终态。本次结果为 2 次尝试、Fence 2、Workflow passed、
3 条预期节点终态。这两项本地结果是 S29 Compose 参考证据，不代替生产网络、TLS、异构
Kubernetes 或长时间 RC 观察。

容量结果必须同时记录 Control Plane 与 Worker 的 CPU/内存规格、Docker 版本和宿主架构。
单机 Compose 门槛是兼容性承诺，不等价于 V3 四 Worker Plane 的分布式容量目标。
