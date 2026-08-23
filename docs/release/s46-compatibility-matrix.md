# FlowTest V5 S46 兼容矩阵

状态：GA 候选基线（2026-08-23，Asia/Shanghai）

| 维度 | Full | Compact | Standalone | 兼容承诺 |
|---|---|---|---|---|
| 业务状态语义 | PostgreSQL/Redis/MinIO，隔离 Worker | PostgreSQL/Redis/MinIO，合并 Worker | SQLite/本地存储，进程内调度 | Domain/Application 状态与错误语义一致 |
| `/api/v1` | 完整 | 完整 | 完整（不支持能力返回标准错误） | 既有客户端请求结构不变 |
| Health/Readiness/Profile | 支持 | 支持 | 支持 | `live`、`ready`、`runtime-profile` 可机器验收 |
| Workflow/Execution Snapshot | 支持 | 支持 | 支持 | Snapshot、Evidence、脱敏规则一致 |
| Service/Endpoint Target | 支持 | 支持 | 支持 | Resolver 优先级和脱敏快照一致 |
| Organization/Tenant | 支持 | 支持 | 支持 | 组织边界、审计和 Service Account 语义一致 |
| Durable Command/Checkpoint | 支持 | 支持 | 受 Standalone 调度边界约束 | 幂等、Fence 和已完成节点跳过规则一致 |
| MCP Read/Controlled Write | stdio/HTTP Gateway | HTTP Gateway | 本机 stdio/HTTP Gateway | Gateway 只调用 Application API，不直连数据库 |
| Performance/Environment Lab | 可按 Feature Flag 启用 | 明确关闭 | 明确关闭 | 不支持档位必须启动时拒绝配置 |
| Transfer | 导入/导出 | 导入/导出 | `standalone-compact-transfer-v1` | Manifest 版本冻结；当前 head `20260823_0040` |

## 数据与版本边界

- PostgreSQL 是 Full/Compact 权威业务存储；SQLite 只属于 Standalone，不能复制数据库文件代替
  Transfer。
- `Environment.base_url` 保留为 Legacy Fallback；`/api/v1` 保持兼容。
- S45 迁移 `20260823_0040` 的回滚目标是 `20260822_0039`；降级会删除 S45 回归运行/阶段记录，
  因此生产回滚优先使用升级前 PostgreSQL + MinIO 一致性恢复点。
- Transfer Manifest 版本保持 `standalone-compact-transfer-v1`；新增表必须通过显式表清单和
  数据分类验证，不能静默改变旧包含义。
- MCP、AI、REST、CLI 只经过 Application Service；MCP 关闭时普通 Web/API/Standalone/Compact
  功能仍应可用。

## 不承诺的兼容性

- Standalone 不承诺 HA、跨进程任务续跑或 Full 的 Performance/Environment/Runner Fabric 能力。
- 较新迁移执行后不能只切换旧镜像完成安全回滚；必须先停止写入、处理 Worker/Lease，再执行兼容的
  downgrade 或恢复完整备份。
- 本地 macOS/ARM、CI 和短时 Soak 不等于 Windows x64 公司云桌面 72 小时试点或生产容量承诺。
