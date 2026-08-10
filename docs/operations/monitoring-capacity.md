# 监控、告警与容量门槛

## 指标

Prometheus 抓取 `/api/v1/metrics`：

- `flowtest_info`：当前应用版本。
- `flowtest_http_requests_total`：按 method、归一化 path、status 统计请求。
- `flowtest_http_request_duration_seconds`：HTTP 延迟直方图。
- `flowtest_execution_records`：API、Workflow、Test Plan 当前持久化状态数量。
- `flowtest_execution_metrics_available`：数据库执行指标是否可采集。

建议告警：readiness 连续 2 分钟失败、5xx 比例 5 分钟超过 2%、P95 超过 1 秒、
失败执行持续升高、执行指标不可用、Worker 健康检查失败、磁盘使用率超过 80%。

## 可复现容量门槛

```bash
uv run --project backend python scripts/capacity_s11.py
uv run --project backend python scripts/capacity_workflow.py
uv run --project backend python scripts/capacity_s19.py
```

默认先用 30 个请求预热 HTTP 连接池，再对 `/api/v1/live` 发出 300 个请求、并发 30，
要求零失败且稳态 P95 不超过 500 ms。预热只排除 CI 主机的一次性建连抖动；任一预热请求失败仍会使门禁失败。
可通过 `FLOWTEST_CAPACITY_REQUESTS`、`FLOWTEST_CAPACITY_CONCURRENCY` 和
`FLOWTEST_CAPACITY_P95_SECONDS` 调整。每次变更 Worker 并发、资源限制或宿主机规格后重新执行。

## V1.0 基线结果

2026-08-09 在 Docker Desktop ARM64 单机 Compose 环境执行：300 请求、并发 30、0 失败，
耗时 0.556 秒，P95 0.153 秒，吞吐约 539.25 req/s。该数据是本地健康端点基线，不能替代
真实业务工作流容量测试；生产宿主机或资源限制变化后必须重新记录。

S12 新增 `capacity_workflow.py`，它会创建并发布一个包含真实 HTTP API 节点的 Workflow，S19 默认以
并发 100 完成 100 次持久化、入队、Worker 执行和结果查询。门槛默认要求零失败且端到端 P95 不超过
10 秒；可通过 `FLOWTEST_CAPACITY_WORKFLOW_REQUESTS`、
`FLOWTEST_CAPACITY_WORKFLOW_CONCURRENCY` 和 `FLOWTEST_CAPACITY_WORKFLOW_P95_SECONDS` 调整。
GitHub 托管 Runner 并非 8C/16G 参考环境，因此 CI 保持相同的 100 并发、零失败要求，使用
30 秒兼容上限；正式发布仍必须在参考硬件上通过默认 10 秒门槛，CI 结果不能替代该记录。

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

容量结果必须同时记录 Control Plane 与 Worker 的 CPU/内存规格、Docker 版本和宿主架构。
单机 Compose 门槛是兼容性承诺，不等价于 V3 四 Worker Plane 的分布式容量目标。
