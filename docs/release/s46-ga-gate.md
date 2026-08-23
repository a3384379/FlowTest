# FlowTest V5 S46 GA Gate

状态：候选收口清单（2026-08-23，Asia/Shanghai）

S46 只负责稳定性、安全、兼容和发布收口，不新增业务大功能。所有证据必须关联同一条
`codex/v5.0` 提交、迁移 head 和运行档位；本地 macOS/ARM 证据不能替代 Windows x64
公司云桌面试点、生产备份恢复或人工签署。

## Gate 清单

| Gate | 必须通过的证据 | 失败处理 |
|---|---|---|
| 代码质量 | Backend Ruff、mypy、pytest；Frontend format、lint、coverage、build | 不生成候选提交 |
| 迁移 | PostgreSQL `upgrade → check → downgrade -1 → upgrade → check` | 停止发布，修复漂移或回到备份恢复 |
| `/api/v1` | Health、Readiness、Runtime Profile、登录、旧资产和错误 Envelope | 保留旧 API，不以页面成功替代接口兼容 |
| Runtime Profile | Full/Compact/Standalone 核心业务语义一致；不支持能力显式拒绝 | 禁止把档位专属能力带入不支持档位 |
| 安全 | Secret/Token/PII、验证错误、审计、支持包、MCP 输出均无明文；依赖/镜像扫描无未接受 High/Critical | 立即阻断 GA；例外必须有范围、责任人和到期日 |
| 租户隔离 | Project、Service、Execution、Artifact、Evidence、Runner、后台任务和审计跨组织拒绝 | 立即阻断 GA，不接受页面层过滤补救 |
| MCP Red Team | 只读工具无副作用；写入仅生成 Draft；无发布/执行/删除/权限提升工具；跨租户和恶意 URI 拒绝 | 关闭 MCP 入口并修复 Application Service 边界 |
| 执行恢复 | Idempotency、Checkpoint、Resume、Retry、Lease/Fence、Worker Restart 场景通过 | 不允许重试发布；保留旧版本和恢复点 |
| 故障注入 | 升级后启动失败自动回滚；依赖降级进入 degraded；旧 Lease 不能覆盖新状态 | 记录 failure stage、rollback status 和 trace ID |
| 性能 | Compact Soak 无失败/重启/积压；容量基线达到当前档位门槛 | 只调整环境或修复回归，不放宽零失败约束 |
| 兼容性 | 见 [S46 兼容矩阵](s46-compatibility-matrix.md)，Transfer Manifest 版本不变 | 增加迁移/兼容适配，不直接改写旧数据 |
| 文档 | 升级、回滚、故障注入、支持包、试点和发布签署记录完整 | 只允许内部候选，不得标记 GA |

## 本地等价验证命令

```bash
cd backend
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run pytest
uv run pip-audit

cd ../frontend
pnpm format:check
pnpm lint
pnpm test:coverage
pnpm build
```

迁移使用一次性、明确命名的 PostgreSQL 容器和临时端口执行；不得复用正在运行的 Compact
数据卷。Compose 验证使用独立 `COMPOSE_PROJECT_NAME`、高端口和临时卷，结束后执行
`down --volumes --remove-orphans`。

故障注入和回滚场景见 [S46 故障注入记录](../operations/s46-failure-injection.md)。
S46 退出时必须记录实际命令、通过数量、覆盖率、迁移 revision、运行档位、镜像/源码摘要、
未完成项和环境差异；不能以“命令启动成功”推断业务恢复成功。

## 发布决策

只有全部 Gate 为 `passed`，且没有未接受的 P0/P1、未关闭的 Secret/PII 泄漏、迁移漂移、
重复终态或跨租户读取，候选才可进入 GA 评审。接受的扫描例外不得覆盖 Critical，且必须在
正式发布前由责任人重新确认。

本文件不代表 Windows 72 小时试点、14 日 RC 观察或公司安全审批已经完成；这些仍需外部
环境和人工签署。

## S47 正确性附加门槛

S47 不放宽上述 S46 Gate，另外增加以下必验事实：

| Gate | 必须通过的证据 | 阻断条件 |
|---|---|---|
| 生成正确性 | required/enum/auth/min/max 精确 Golden；Scenario/Oracle/Coverage 可追溯 | 边界值泛化、证据丢失或敏感值进入设计 |
| 物化闭环 | Generate → Draft → Review → Apply 产生真实 Workflow/TestCase 并可执行 | 只生成 DTO/页面模型或绕过人工审核 |
| FlowSpec 可移植性 | 多 Service/Operation/Variant 跨项目映射，v3 指纹不依赖 UUID 并保留 pinned/current | 无法解析资产被丢弃或 pinned 回退 current |
| Durable 正确性 | Batch 子项 Checkpoint、Resume/Retry 差异、Dispatch 失败补偿、Lease/Fence 拒绝 | 错误跳过、重复终态或孤儿 queued/running |
| MCP 协议 | 工具列表/Schema 稳定；写入默认 dry-run 且幂等；只生成 Draft | 无幂等键写入、默认真写或越权执行 |
| 变更与归因 | 边界变化生成精确回归值；Failure Triage 输出证据/置信度/建议 | 只返回 generic 场景或无证据分类 |

Key Rotation 真实重加密 Apply/Rollback 未实现，因此即使 S47 功能闭环的本地门槛全部通过，
也只能进入功能完成审核，不能判定为 V5 GA Ready。证据与现存限制见
[S47 V5 功能闭环记录](s47-v5-functional-completion.md)。

## S47.1 语义附加门槛

| Gate | 必须通过的证据 | 阻断条件 |
|---|---|---|
| Canonical Contract | OpenAPI/Swagger 导入后 APIVersion 保留位置、Schema、Status、Auth 和 fingerprint | 只保存 Example、丢 response Schema 或默认伪造 200 |
| Evidence Fusion | Source/DataProfile/Existing Test Finding 改变 Scenario/Oracle/Coverage/Graph | 只增加 Evidence 数量或冲突被静默覆盖 |
| 位置执行 | Path/Query/Header/Body/Auth 负场景到真实目标，Schema Assert 执行 | 所有 mutation 写入 Body 或 auth missing 删除 Secret |
| 版本固定 | Source current v3/pinned v1 映射到 Target compatible v1；无兼容版本阻断 | pinned 丢失、仅按版本号匹配或回退 target current |
| 语义变更 | Asset Mapping 与 Test Semantic Coverage 独立；100→999 只补 999/1000 | Mapping=covered 时跳过语义 gap，或伪造 200/400 |
| Evidence Security | 中性字段中的 Token/PII、Repository userinfo/query 被拒绝或哈希摘要 | MCP/Audit/TestDesign 出现敏感原值 |
| Triage Identity | 收到 503=upstream；no response=network/endpoint；service key 优先 | 所有 5xx 都归 Endpoint 或只使用 hostname |
| Migration Truth | 0042 往返和 Standalone backfill；0041 downgrade 保持 planned truth | downgrade 写 migrated 或 partial backfill 泄漏值 |

专项事实见 [S47.1 语义正确性与证据闭环](s47-1-semantic-correctness.md)。即使本地门槛
全部通过，Remote CI、Windows 实机、连续 RC、安全审批和真实 Key Rotation 未完成时，
`GA_READY` 仍必须为 `NO`。
