# FlowTest V6.0 S49 Context Revision 与 External Evidence

## 1. 阶段身份

| 项目                          | 当前值                                                         |
| ----------------------------- | -------------------------------------------------------------- |
| 阶段基线 Main SHA             | `a260272f9eb20c0a8de6c5d5e6c41d57db4b4edb`                     |
| S49 实现 Main SHA             | `14d4694762cd381e347b248da5e97ecb7452ab21`                     |
| 实现分支                      | `codex/s49-context-contracts-v2`、`codex/s49-context-evidence` |
| 证据收口分支                  | `codex/s49-evidence-closure`                                   |
| Alembic / Standalone Revision | `20260828_0046`                                                |
| Release 状态                  | 未发布；不是 Alpha、Beta、RC 或 GA                             |
| Remote CI                     | PR 精确 Head 与两次实现 Merge SHA 的 Main Push 全部 Success    |

阶段从 S48 Evidence Closure 的全绿 Main 开始。CI Bootstrap、契约/持久化与应用层实现均经独立 PR、
普通 Squash Merge 和合并后 Main Push 验证；下文只记录已达到终态的远程事实。

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

| Review                                       | 本地结论         | 主要证据                                                                      |
| -------------------------------------------- | ---------------- | ----------------------------------------------------------------------------- |
| Requirement Conformance                      | Pass             | 三表边界、六状态、五个 MCP 工具、两个独立 Scope、Draft-only Adapter           |
| Correctness / Data Consistency / Concurrency | Pass             | 不可变行、稳定 Fingerprint、PostgreSQL 行锁、幂等重放/冲突、迁移往返          |
| Security / Tenant / Secret / SSRF            | Pass             | 严格 Envelope、跨租户拒绝、旧 Scope 拒绝、敏感输入/响应/日志回归              |
| End-to-End User Flow                         | Pass（S49 范围） | Compose 上 begin → ingest → requirements → dry-run/persist → close Playwright |

Domain 模块没有导入 FastAPI、Celery、SQLAlchemy Model 或具体基础设施客户端。PR #50 与 #51 均完成
当前代码四维复核，未解决 Review Thread 为 0；线程状态不代替本地与远程代码/行为证据。

## 5. Local Validation

| 门禁                              | 结果                                                                       |
| --------------------------------- | -------------------------------------------------------------------------- |
| Backend Ruff Format / Ruff / Mypy | Pass                                                                       |
| Backend Pytest / Coverage         | `644 passed / 4 skipped`；`90.29%`                                         |
| Frontend Prettier / ESLint        | Pass                                                                       |
| Frontend Vitest Coverage          | `56 files / 215 passed`；S `86.15%` / B `80.11%` / F `85.27%` / L `88.37%` |
| Frontend Build                    | Pass                                                                       |
| PostgreSQL Migration              | Pass；0045/0046 往返与 Alembic Check 无 Drift                              |
| Standalone Migration              | Pass；0045 增量、索引、幂等初始化                                          |
| Compose / Playwright              | Pass；S49 `1 passed`，登录 Setup `1 passed`                                |
| Secret Log Scan                   | Pass；测试 Secret 匹配 `0`                                                 |

## 6. Exit Criteria

| 条件                              | 本地状态 | 说明                                               |
| --------------------------------- | -------- | -------------------------------------------------- |
| Context Revision Fingerprint 稳定 | Pass     | 顺序归一化与输入差异回归                           |
| Expired Context 不能创建 Proposal | Pass     | Preview 与 Persist 均重新校验当前 Revision         |
| Evidence Secret Leak = 0          | Pass     | 输入拒绝、标准错误脱敏、响应摘要、Compose 日志扫描 |
| Cross-Tenant = 0                  | Pass     | Context、Revision、Evidence 与 Source Ref 项目边界 |
| Dry Run 不持久化                  | Pass     | AIChangeSet/Item/Idempotency 行数不变              |
| Idempotency 正确                  | Pass     | 同键同请求重放；同键异请求冲突                     |
| Standalone / PostgreSQL 迁移      | Pass     | 升级、回滚、再升级、无 Drift                       |

## 7. Partially Implemented / Intentionally Out of Scope / Blocked

### Partially Implemented

- 无。S49 定义范围内的实现、本地验证、PR 精确 Head CI、Review、合并与实现 Main Push 均完整。

### Intentionally Out of Scope

- Integration Plan、Executable Compiler、Visual Proposal、外部 Adapter/Java POC、Data Oracle、Cleanup Runtime、
  Sandbox Preview 和 Flagship Skill 分别由 S50～S56 实现。
- 不自动 Review/Apply/Publish/Execute，不读取 Secret，不创建 Credential，不执行脚本或数据库写 SQL。

### Blocked

- S49 当前无本地实现阻断。S55 仍受真实 Key Rotation 授权与证据门槛约束，不能由本阶段推断为已完成。

### External Validation

- PR #50/#51 精确 Head 的适用 Backend、Frontend、Security、Compose、Standalone Windows、
  Upgrade/Rollback 与 Required Gate 已全部 Success；两次实现 Merge SHA 的适用 Main Push 亦全部 Success。
- Windows x64 公司云桌面 72 小时试点、连续 RC 观察、安全审批与真实 Key Rotation 仍未完成；这些是后续
  Release/GA 外部门槛，不伪记为 S49 交付证据。

## 8. Remote CI、Review 与合并证据

### 8.1 受控 CI Bootstrap

- PR #49（Head `0ce74d214894674a9fec9a483e8a6e329627743c`）只把 Migration CI 改为相对 Head 往返，
  并让 Windows 断言比较 `BASELINE_REVISION` 与 `STANDALONE_SCHEMA_REVISION`，不携带产品实现。
- 普通 PR 的 trusted Required Gate 对 Workflow 变更按设计失败；受控 Bootstrap 仅临时要求该 Head 的
  Backend `33128079447`、Security `33128079381`、Standalone Windows `33128079502` 三个底层检查，
  全部 Success 后普通 Squash Merge 至 `main@da8f42aab05b8eb8246d4787c3adc314e335c9b5`。
- 整个过程 `bypass_actors=[]`，未用 Admin Merge、Bypass 或 Direct Push；合并后立即恢复唯一 Required Gate。
  该 Main Push 的 Backend `33128974934`、Security `33128974969`、Windows `33128974963` 与 Required Gate
  `33128974931` 全部 Success。

### 8.2 契约、持久化与 Migration PR #50

| 事实        | 精确证据                                                                                                                                                                    |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PR Head     | `4bebb1cdcd99765234fe50896a2725b8457f27ff`                                                                                                                                  |
| PR Workflow | Backend `33129844681`；Compose `33129844698`；Security `33129844690`；Windows `33129844712`；Upgrade/Rollback `33129844700`；最终 Required Gate `33131697019`，全部 Success |
| Review      | 未解决 Thread `0`；Ready 后 CLEAN / MERGEABLE                                                                                                                               |
| Merge       | PR #50 普通 Squash Merge：`e3a70894aadd3ee15cd18c980186015b40e96d06`                                                                                                        |
| Main Push   | Backend `33131727118`；Compose `33131727068`；Security `33131727095`；Windows `33131727145`；Upgrade/Rollback `33131727064`；Required Gate `33131727083`，全部 Success      |

### 8.3 Context/Evidence 与 Draft Proposal PR #51

| 事实        | 精确证据                                                                                                                                                                                                |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PR Head     | `fc17f784ed2bea50460aff5644e9942121a0e5f3`                                                                                                                                                              |
| PR Workflow | Backend `33134071069`；Frontend `33134071062`；Compose `33134071031`；Security `33134071103`；Windows `33134071078`；Upgrade/Rollback `33134071083`；Ready 后 Required Gate `33135732564`，全部 Success |
| Review      | 未解决 Thread `0`；Ready 后 CLEAN / MERGEABLE                                                                                                                                                           |
| Merge       | PR #51 普通 Squash Merge：`14d4694762cd381e347b248da5e97ecb7452ab21`                                                                                                                                    |
| Main Push   | Backend `33135774067`；Frontend `33135774088`；Compose `33135774200`；Security `33135774194`；Windows `33135774493`；Upgrade/Rollback `33135774185`；Required Gate `33135774070`，全部 Success          |

### 8.4 阶段结论

- 所有实现 PR 均从前一 Merge SHA 已全绿的最新 Main 创建，普通 Squash Merge，无 Admin、Bypass、Force Push
  或 Direct Main Push。
- 收口时 `main-required-gate` Ruleset 为 Active，仅要求 Integration `15368` 写入的 `Required Gate`，
  `bypass_actors=[]`，并强制解决 Review Thread。
- S49 Exit Criteria 全部满足；本 Evidence Closure PR 合并且其 Main Push Required Gate 成功后，才允许从
  最新 Main 创建 S50 分支。

## 9. Evidence Closure 与最终跨阶段审计

- Evidence Closure PR #52 已普通 Squash Merge，合并后 Main Push Required Gate
  `33138252316` 为 Success，S49 阶段于此闭环。
- 最终跨阶段审计重新检查了 PR #50/#51 后续出现的历史线程：认证 URL/描述文本、
  Phone/Card PII 与 FlowSpec 凭据字面量的 P1 均由 PR #69 统一修复。
- PR #51 的幂等语义 P2 按发布策略接受并记录为 V6.1 技术债。上述线程均已回复并关闭，
  最终阻塞级结果为 P0=`0`、P1=`0`。
