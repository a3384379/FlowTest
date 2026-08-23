# S46 故障注入与恢复记录

目标：验证失败可被观察、不会产生重复终态或跨租户副作用，并且回滚证据可以独立复核。

## 场景矩阵

| 场景 | 注入方式 | 必须观察的结果 |
|---|---|---|
| 数据库不可用 | Readiness 测试中令数据库检查抛出连接错误 | `/api/v1/ready` 返回 `503`、`degraded`，包含检查结果和 trace ID |
| 升级后启动失败 | `FLOWTEST_S36_FORCE_POST_START_FAILURE=1 deploy/compact/upgrade_offline.sh ...` | 命令非零；证据 `status=rolled_back`、`failure_stage=forced_post_start`、`rollback_status=passed` |
| Runner/Worker 重启 | 运行中的任务过期 Lease 后由新 Lease 接管 | Attempt/Fence 递增；旧 Lease 返回 `RUNNER_LEASE_FENCED`，不能覆盖终态 |
| 重复执行命令 | 相同 `Idempotency-Key` 重复提交 | 返回同一 Execution/Command，不产生第二个终态 |
| 重复 Checkpoint | 相同执行、节点、Attempt 和输入摘要重复上报 | 返回既有 Checkpoint；不同摘要拒绝，不覆盖旧证据 |
| MCP 恶意调用 | 缺失 Scope、跨组织 ID、恶意 `flowtest://` URI、尝试发布/执行 | 统一拒绝；只读无写副作用；错误不回显 Token/Body |
| 敏感错误输入 | 将 password/token 作为无效字段类型提交 | 标准错误只保留字段位置和 `***`，不返回原始输入 |

## 可复核命令

```bash
cd backend
uv run pytest tests/test_readiness.py tests/test_runner_fabric.py tests/test_workflows_api.py \
  tests/test_mcp_read.py tests/test_errors_and_trace.py tests/test_s46_ga_gate.py --no-cov

cd ..
FLOWTEST_S36_FORCE_POST_START_FAILURE=1 \
  deploy/compact/upgrade_offline.sh \
  /absolute/path/to/compact \
  /absolute/path/to/evidence/backup \
  /absolute/path/to/evidence/failed-upgrade.json
```

升级脚本的失败证据必须脱敏并包含源码/镜像摘要、数据库 revision、失败阶段、回滚状态和时间戳。
验证结束后删除临时 Compose 项目和卷；不得对当前 Compact 项目执行 `down --volumes`，也不得
覆盖现有备份或证据文件。

## 通过条件

- 所有注入场景都能在标准错误、审计或 Evidence 中定位到 trace ID。
- 没有重复 Execution、重复终态、旧 Fence 覆盖新状态或跨租户读取。
- 自动回滚失败时命令保持非零并明确 `rollback_failed`，不能伪装成升级成功。
- 失败路径不把密码、Authorization、Cookie、Token、Secret、PII 或未脱敏 Body 写入日志、支持包、
  审计详情和 MCP 响应。
