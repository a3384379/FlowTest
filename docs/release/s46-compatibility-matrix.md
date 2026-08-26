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
| Test Engineering/Evidence | 支持 | 支持 | 支持 | Canonical Contract、位置生成与审核语义一致；物化复用 Workflow/TestCase |
| FlowSpec Portable Mapping | 支持 | 支持 | 支持 | V5 正式基线为 v3 指纹，不依赖 UUID 并保留 pinned/current；开发期 v1/v2 不作正式兼容承诺 |
| Performance/Environment Lab | 可按 Feature Flag 启用 | 明确关闭 | 明确关闭 | 不支持档位必须启动时拒绝配置 |
| Transfer | 导入/导出 | 导入/导出 | `standalone-compact-transfer-v1` | Manifest 版本冻结；当前 head `20260823_0044` |

## 数据与版本边界

- PostgreSQL 是 Full/Compact 权威业务存储；SQLite 只属于 Standalone，不能复制数据库文件代替
  Transfer。
- `Environment.base_url` 保留为 Legacy Fallback；`/api/v1` 保持兼容。
- S45 迁移 `20260823_0040` 的回滚目标是 `20260822_0039`；降级会删除 S45 回归运行/阶段记录，
  因此生产回滚优先使用升级前 PostgreSQL + MinIO 一致性恢复点。
- S47 迁移 `20260823_0041` 的回滚目标是 `20260823_0040`；它为 `test_designs` 增加
  Scenario、Evidence Ref、Warning、Confidence 和 Review Requirement。升级会将无真实重加密证据却
  被标记为 `migrated` 的 Key Version 恢复为 `planned`；降级仅用于 Schema 兼容回滚，
  不能当作真实密钥数据回滚。
- S47.1 迁移 `20260823_0042` 的回滚目标是 `20260823_0041`；它为 `api_versions` 增加
  Canonical Contract、fingerprint 和 completeness，并对 PostgreSQL/Standalone 旧版本做安全
  partial backfill。Backfill 不复制 Header/Query 值、不伪造 response status。
- V5 新 Export、Import、Review、Apply 和测试只以 `flowtest-flow-spec-fingerprint-v3` 为正式基线，
  并保存 pinned/current 版本策略。`schema_version` 仍为 `flowtest-flow-spec-v1`，它与 fingerprint
  版本是两个独立维度，因此不修改 `/api/v1` 路由版本。仓库中的 v1/v2 读取代码可保留，但开发期
  旧文件不属于正式兼容范围，S47.2 不增加迁移或兼容逻辑。
- S47.2 迁移 `20260823_0043` 的回滚目标是 `20260823_0042`；升级统一净化既有 Canonical Contract、
  重算 fingerprint/completeness。降级保留已净化数据，绝不恢复已删除的敏感值。
- S47.3 迁移 `20260823_0044` 的回滚目标是 `20260823_0043`；它新增逐 Gap Waiver 持久化、
  删除历史敏感 Enum Hash、清理非法 Keyword 并重算指纹。降级只删除 Waiver Schema，
  安全净化不可逆，不恢复原值或 Hash。
- S47.4 迁移 `20260823_0045` 的回滚目标是 `20260823_0044`；它为 Semantic Gap Waiver
  增加 Revision、Supersedes 自引用、约束和索引。降级为表示层有损：同一 Run/Gap 仅保留
  最高 Revision 以恢复 0044 唯一约束，不会恢复被净化的敏感数据。
- Transfer Manifest 版本保持 `standalone-compact-transfer-v1`；新增表必须通过显式表清单和
  数据分类验证，不能静默改变旧包含义。
- MCP、AI、REST、CLI 只经过 Application Service；MCP 关闭时普通 Web/API/Standalone/Compact
  功能仍应可用。

## 不承诺的兼容性

- Standalone 不承诺 HA、跨进程任务续跑或 Full 的 Performance/Environment/Runner Fabric 能力。
- 较新迁移执行后不能只切换旧镜像完成安全回滚；必须先停止写入、处理 Worker/Lease，再执行兼容的
  downgrade 或恢复完整备份。
- 本地 macOS/ARM、CI 和短时 Soak 不等于 Windows x64 公司云桌面 72 小时试点或生产容量承诺。
| S47.5 Plan/Run Evidence | 固定 TestPlanItem 版本；Release 使用 Passed RunItem Snapshot | Supported |
| S47.5 Current Contract Binding | OpenAPI Current Fingerprint 精确匹配；旧 Route 不回退 | Supported |
| Generated Asset Same-Run | 人工发布后显式加入；不自动 Publish/Execute | Supported |
