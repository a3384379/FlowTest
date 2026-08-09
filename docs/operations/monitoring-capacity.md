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
```

默认对 `/api/v1/live` 发出 300 个请求、并发 30，要求零失败且 P95 不超过 500 ms。
可通过 `FLOWTEST_CAPACITY_REQUESTS`、`FLOWTEST_CAPACITY_CONCURRENCY` 和
`FLOWTEST_CAPACITY_P95_SECONDS` 调整。每次变更 Worker 并发、资源限制或宿主机规格后重新执行。

## V1.0 基线结果

2026-08-09 在 Docker Desktop ARM64 单机 Compose 环境执行：300 请求、并发 30、0 失败，
耗时 0.556 秒，P95 0.153 秒，吞吐约 539.25 req/s。该数据是本地健康端点基线，不能替代
真实业务工作流容量测试；生产宿主机或资源限制变化后必须重新记录。
