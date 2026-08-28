# FlowTest V6.0 S49 Context Revision 与 External Evidence

## 1. 阶段身份

| 项目 | 当前值 |
| --- | --- |
| 阶段基线 Main SHA | `a260272f9eb20c0a8de6c5d5e6c41d57db4b4edb` |
| 开发分支 | `codex/s49-context-evidence` |
| Alembic / Standalone Revision | `20260828_0046` |
| Release 状态 | 未发布；不是 Alpha、Beta、RC 或 GA |
| Remote CI | 等待本阶段 PR 精确 Head |

该基线是 S48 Evidence Closure 合并且 Main Push 全绿后的最新 `main`。本记录先保存可复现的本地证据；
PR、Review、合并与 Main Push 的远程事实只能在对应 Workflow 达到终态后追加。

## 2. Implemented

### Context 与 Evidence

- 仅增加 `test_contexts`、`test_context_revisions`、`context_evidence_items` 三张表，没有预建 Graph、Plan、
  Proposal、Provider 或 Skill 表。
- Context 支持 `collecting`、`ready`、`incomplete`、`conflicted`、`expired`、`closed`；Revision 与 Evidence
  Item 不允许原地更新，每次接收 Evidence 产生新 Revision。
- Fingerprint 对引用、Evidence、Knowledge、Conflict 与 Completeness 做规范排序，输入顺序不改变结果；
  Envelope confidence、deterministic、Provider、Source Revision 与 Finding 语义均进入证据身份。
- Knowledge、Conflict、Completeness 使用严格、带版本的 Pydantic JSON Snapshot；未知字段与重复稳定引用拒绝。
- TTL 与 Close 会阻止后续 Proposal；Retention 会删除到期 Context 及其级联 Revision/Evidence。

### External Evidence 安全边界

- Envelope 固定 `schema_version`、Provider type/name/version、Source ref/revision、Subject、Findings、
  Redactions、Warnings、Confidence 与 Deterministic。
- 输入拒绝 Secret Literal、Bearer/Basic/JWT、Cookie、Password、Connection String、PEM、Cloud Key、Email、
  Phone、Card、Prompt Instruction、无界内容、空 Source Revision、未知字段和跨项目引用。
- Context 初始 Name、Objective、Knowledge 与引用同样执行服务层敏感值检查；拒绝时仅返回稳定 422 错误码，
  不回显原始输入。单个 Revision 的引用、冲突和 Evidence Item 达到上限时返回稳定 409，不落入内部 5xx。
- Comment、Description、Statement 与 Warning 全部作为 `untrusted_data`；验证错误不会回显原始 Evidence Body，
  API 错误继续使用标准错误信封与 Trace ID。
- API 响应只返回分类、指纹、来源与安全摘要，不返回 Finding 原文；日志扫描的测试 Secret 匹配为 0。

### MCP 与 Proposal Adapter

- MCP Server 增加 `flowtest.begin_test_context`、`flowtest.inspect_context_requirements`、
  `flowtest.ingest_external_evidence`、`flowtest.inspect_test_context`、`flowtest.close_test_context`。
- 五个工具要求独立 `mcp:evidence:write`；已有 `mcp:write` 不隐式获得该 Scope。
- 既有“组织治理”Service Account 表单增加 `mcp:evidence:write` 与 `mcp:flow:propose` 选项；没有新增
  Context 管理页面或第二套权限界面。
- Proposal Adapter 使用独立 `mcp:flow:propose`，默认 `dry_run=true` 且强制 Idempotency-Key。Dry Run 只调用
  共享 Preview 路径，不写 AIChangeSet、AIChangeItem 或 Idempotency 记录。
- 持久化路径复用 `FlowSpecService.create_import()`，保存 `actor_type=service_account`、`mcp://` Source Ref、
  Context Revision/Fingerprint，并且只产生 Draft/Pending AIChangeSet；不 Review、Apply、Publish 或 Execute。
- `flowtest.propose_flow_draft` 的 MCP Server 注册属于 S51。本阶段建立并测试受控 Adapter/API，不提前改变
  S51 Tool Contract。

## 3. Migration 与兼容

- `20260828_0046` 的 upgrade 创建上述三表、外键、检查约束与索引；downgrade 以依赖逆序完整删除。
- PostgreSQL 17.6 已验证 Empty → Head、`0045 → 0046`、`0046 → 0045 → 0046`、`alembic current` 和
  `alembic check`，最终无 Schema Drift。
- Standalone 从 0045 缺表数据库首次启动会补齐三表与索引并写入 0046；重复初始化幂等。Transfer Manifest、
  Windows 断言、升级脚本与 CI Migration Target 已同步。
- 旧 FlowSpec Import API 行为保持不变；新增 Preview/Provenance 是共享服务能力，没有复制 Mapping、Validation、
  Review、Apply 或 Stale Revision 规则。

## 4. 四类 Review

| Review | 本地结论 | 主要证据 |
| --- | --- | --- |
| Requirement Conformance | Pass | 三表边界、六状态、五个 MCP 工具、两个独立 Scope、Draft-only Adapter |
| Correctness / Data Consistency / Concurrency | Pass | 不可变行、稳定 Fingerprint、PostgreSQL 行锁、幂等重放/冲突、迁移往返 |
| Security / Tenant / Secret / SSRF | Pass | 严格 Envelope、跨租户拒绝、旧 Scope 拒绝、敏感输入/响应/日志回归 |
| End-to-End User Flow | Pass（S49 范围） | Compose 上 begin → ingest → requirements → dry-run/persist → close Playwright |

Domain 模块没有导入 FastAPI、Celery、SQLAlchemy Model 或具体基础设施客户端。远程自动 Review 与当前代码的
P0/P1/P2 复核将在 PR 创建后追加，不以线程是否关闭代替代码审查。

## 5. Local Validation

| 门禁 | 结果 |
| --- | --- |
| Backend Ruff Format / Ruff / Mypy | Pass |
| Backend Pytest / Coverage | `644 passed / 4 skipped`；`90.29%` |
| Frontend Prettier / ESLint | Pass |
| Frontend Vitest Coverage | `56 files / 215 passed`；S `86.15%` / B `80.11%` / F `85.27%` / L `88.37%` |
| Frontend Build | Pass |
| PostgreSQL Migration | Pass；0045/0046 往返与 Alembic Check 无 Drift |
| Standalone Migration | Pass；0045 增量、索引、幂等初始化 |
| Compose / Playwright | Pass；S49 `1 passed`，登录 Setup `1 passed` |
| Secret Log Scan | Pass；测试 Secret 匹配 `0` |

## 6. Exit Criteria

| 条件 | 本地状态 | 说明 |
| --- | --- | --- |
| Context Revision Fingerprint 稳定 | Pass | 顺序归一化与输入差异回归 |
| Expired Context 不能创建 Proposal | Pass | Preview 与 Persist 均重新校验当前 Revision |
| Evidence Secret Leak = 0 | Pass | 输入拒绝、标准错误脱敏、响应摘要、Compose 日志扫描 |
| Cross-Tenant = 0 | Pass | Context、Revision、Evidence 与 Source Ref 项目边界 |
| Dry Run 不持久化 | Pass | AIChangeSet/Item/Idempotency 行数不变 |
| Idempotency 正确 | Pass | 同键同请求重放；同键异请求冲突 |
| Standalone / PostgreSQL 迁移 | Pass | 升级、回滚、再升级、无 Drift |

## 7. Partially Implemented / Intentionally Out of Scope / Blocked

### Partially Implemented

- 无。S49 定义范围内的实现与本地验证完整；远程 CI 属于待取得的 External Validation，不记为实现缺口。

### Intentionally Out of Scope

- Integration Plan、Executable Compiler、Visual Proposal、外部 Adapter/Java POC、Data Oracle、Cleanup Runtime、
  Sandbox Preview 和 Flagship Skill 分别由 S50～S56 实现。
- 不自动 Review/Apply/Publish/Execute，不读取 Secret，不创建 Credential，不执行脚本或数据库写 SQL。

### Blocked

- S49 当前无本地实现阻断。S55 仍受真实 Key Rotation 授权与证据门槛约束，不能由本阶段推断为已完成。

### External Validation

- PR 精确 Head 的 Backend、Frontend、Security、Compose、Standalone Windows、Upgrade/Rollback 与 Required
  Gate 尚未运行。
- GitHub Review Threads、普通 Squash Merge 与合并后 Main Push Workflow 尚未发生。
- Windows x64 公司云桌面 72 小时试点、连续 RC 观察、安全审批与真实 Key Rotation 未完成。

## 8. Remote CI、Review 与合并证据

等待本阶段 PR 产生精确 Head 后追加。未运行或进行中的 Workflow 不记为成功，也不引用旧 Head 结果。
