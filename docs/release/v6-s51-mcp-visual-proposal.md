# FlowTest V6.0 S51 MCP Flow Draft 与 Visual Proposal Alpha

## 1. 阶段身份

| 项目 | 当前值 |
| --- | --- |
| 阶段基线 Main SHA | `8f20500fd151e89573bb8f01f24cb6512143dbe1` |
| 实现分支 | `codex/s51-mcp-visual-proposal` |
| 实现 PR / Merge SHA | #55 / `f1e2852f7100ae0827a331a7c2ab8f9f87e7781a` |
| Post-Merge Review Fix PR / Merge SHA | #56 / `86d2221e63f93e418b87649f56b3fdfe48d365c9` |
| MCP Server Version | `s51-flow-proposal-v1` |
| Scope | `mcp:flow:propose` |
| 数据库变更 | 无；Migration Head 保持 `20260828_0046` |
| Release 状态 | 实现与补丁已合并，Evidence Closure 进行中；未创建 Tag 或 Release |

S51 从 S50 Evidence Closure 合并且 Main Required Gate 全绿后的精确 Main 创建。本阶段首次完成外部
LLM/MCP 到可视化 Workflow Draft 的用户闭环，但不提前实现 S52～S56，也不把阶段名称等同于已发布版本。

## 2. Implemented

### MCP Tool 与确定性链路

- 官方 MCP SDK Server 与 HTTP Gateway 注册六个精确工具：
  `flowtest.plan_integration_test`、`flowtest.validate_integration_plan`、
  `flowtest.compile_integration_flowspec`、`flowtest.explain_compiler_diagnostics`、
  `flowtest.propose_flow_draft`、`flowtest.inspect_flow_proposal`。
- 六个工具统一要求 `mcp:flow:propose`。Plan 服务先验证 Context Revision、项目内资产与目标环境，再复用
  S50 的 `IntegrationPlanAssetService`、纯 Validation 与 Compiler；不复制 Planner/Compiler。
- `flowtest.propose_flow_draft` 从类型化 Compilation 取得 FlowSpec，`dry_run` 默认 `true`；请求必须提供
  Idempotency Key、Context Revision、Plan、Compilation 与 Service/Operation/Version Mapping。Target Workflow
  可选；更新现有 Draft 时强制 Exact Expected Revision，新建 Workflow 时拒绝 Expected Revision。
- Dry Run 执行同一 FlowSpec Parse/Normalize/Validate/Compatibility、Mapping、Expected Revision 与 Provenance
  校验，但不写 ChangeSet。持久化仅创建既有 `AIChangeSet`/`AIChangeItem` Draft；幂等重放返回同一 ChangeSet。
- Inspect 返回 Tenant-scoped Review/Applied 状态、冻结 Existing Graph、重建 Proposed Graph、Context/Plan/
  Compilation Evidence；Snapshot 无效或 Mapping 资产变化时 fail closed。

### Proposal Review UI

- 复用 `frontend/src/flow/WorkflowDesigner.tsx`，新增只读 `mode="proposal"`，没有第二套 Canvas。Existing 与
  Proposed Graph 使用同一个 Designer 分段切换，并以 Node/Edge Overlay 显示 Added、Modified、Removed 与
  Rewired 状态。
- Proposal Workspace 展示 Mapping Diff、Assert Diff、Evidence、Confidence、Unresolved、Review Requirements
  与 Review Actions。普通路径不能编辑图，也没有 Publish 或 Run Action。
- Pending Proposal 可由人工 Accept 或 Reject；Apply 在 Accepted 前禁用。Apply 继续调用既有
  `FlowSpecService.apply()`，只产生/更新普通 Workflow Draft，随后打开现有 WorkflowDesigner 草稿模式。
- Raw JSON、Cross-instance Mapping 与高级校验继续由既有 `FlowSpecReviewDialog` 负责。MCP Proposal 的 Spec 与
  Mapping 可载入该对话框安全编辑；编辑结果创建新的待审核 FlowSpec ChangeSet，不原地改变冻结 Proposal。

### Post-Merge Review Fix

- PR #55 合并后到达的自动 Review 反馈已全部在 PR #56 闭环：连线 Added/Modified/Removed/
  Rewired 分类补全，Apply 后按钮与查询缓存状态立即一致，用户可见文案全部中文化。
- 本地 Visual Override 与 Proposal ID 绑定；Apply 请求进行中切换提案，不会把旧提案的已应用
  图和操作状态显示到新选择下。
- 历史提案使用专用 MCP-only Keyset Pagination Endpoint，按 `(created_at, id)` 稳定游标遍历；
  新提案在分页间插入时，既有提案不重复也不丢失。
- UI 用 Infinite Query 首屏最多只请求 100 条；仅当用户点击“加载更多提案”时才请求下一游标页，
  避免对话框打开时无界串行拉取全部历史。

### 唯一状态与数据模型

- 复用 `AIChangeSet`、`AIChangeItem`、`FlowSpecService`、FlowSpec Mapping/Review/Apply 与 Workflow Draft；没有
  新表、平行 Proposal 状态机、平行审核或平行 Apply 服务。
- Source Snapshot 额外冻结 Expected Revision、Plan、Compilation、资源 Mapping 与 Existing Workflow
  Definition；写入和读取均重算 Plan/Compilation/FlowSpec Provenance。
- MCP Instructions 明示不会自动 Review、Apply、Publish、Execute、创建 Credential 或修改权限。

## 3. 安全与正确性边界

- MCP HTTP Endpoint 使用 Service Account Principal 和 `mcp:flow:propose`；项目授权先于 Context、API、Service、
  Workflow 与 ChangeSet 读取，跨项目 Inspect 返回 404。
- Target Workflow 创建时与 Apply 时均有 Stale Guard：Expected Revision 不符不创建 Proposal；审核后 Draft
  Revision 改变则 Apply 返回 `WORKFLOW_DRAFT_CONFLICT`，不覆盖新草稿。
- Context Revision/Fingerprint、Plan Fingerprint、Compiler Output 与 FlowSpec Fingerprint 任一不匹配均拒绝；
  MCP 不能提交自选 Spec 绕过 Compilation Provenance。
- Proposal 画布只读；未审核 Apply 返回错误且 UI Action 禁用。流程不调用 Publish/Run Endpoint，不创建
  `WorkflowExecution`，也不读取、解密或记录 Secret 值。
- Existing Graph 使用 Proposal 创建时捕获的定义，不读取后来变化的 Draft 冒充原始比较基线；无效 Snapshot
  使用标准错误信封 fail closed。

## 4. Alpha Exit Criteria

| 条件 | 本地状态 | 证据 |
| --- | --- | --- |
| External LLM / MCP → Visual Flow Draft | Pass | 官方 MCP SDK 集成测试与隔离 Compose Playwright 真实链路 |
| Auto Publish | 0 | Proposal UI 无 Publish；应用后 `current_version=null` |
| Production Execution | 0 | UI 无 Run；`WorkflowExecution` / API Execution 查询为 0 |
| Unreviewed Apply | 0 | 服务端 Review Gate、UI Disabled Action 与回归测试 |
| Stale Overwrite | 0 | 创建时 Expected Revision 与 Apply 时 Draft Snapshot 双重冲突测试 |
| Applied Graph 与 Proposal 一致 | Pass | Playwright 后置 API 逐字段比较 Workflow Draft Definition |

## 5. Intentionally Out of Scope / Blocked

### Intentionally Out of Scope

- S52 Java/DB External Evidence Adapter、Entity Mapping 与 Java/Spring POC。
- S53 Data Recipe、Cross-API Oracle 与 DB Read Oracle；S54 Cleanup/Compensation Runtime。
- S55 Sandbox Preview、真实 Key Rotation；S56 Flagship Skill、Evaluation、Compatibility 与 RC Evidence。
- 自动 Review、Apply、Publish、生产执行、任意外部 MCP 连接、内置 Java Provider、第二套 Canvas 或第二套
  Proposal/Review/Apply 状态机。

### Blocked

- 当前无已知本地或远程实现阻断。PR #55、补丁 PR #56 及两者的精确 Merge SHA Main Push 已全绿。
- S51 Evidence Closure PR 合并且其 Main Push Required Gate 成功前，不允许进入 S52。

## 6. Validation 与 Evidence

### 本地 Required Checks

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| Backend Format | `uv run ruff format --check .` | Pass；460 files already formatted |
| Backend Lint | `uv run ruff check .` | Pass |
| Backend Types | `uv run mypy app` | Pass；335 source files |
| Backend Tests | `uv run pytest` | Pass；663 passed、4 skipped、总覆盖率 90.41% |
| Backend Security Lint | `uv run ruff check --select S app` | Pass |
| Frontend Format | `pnpm format:check` | Pass |
| Frontend Lint/Types | `pnpm lint` | Pass；ESLint 与 TypeScript |
| Frontend Tests | `pnpm test:coverage` | Pass；57 files、222 tests；S/B/F/L = 86.23/80.12/85.44/88.48% |
| Frontend Build | `pnpm build` | Pass |
| Python Dependency Audit | `uv run pip-audit` | Pass；无已知漏洞，非 PyPI 项目包按工具约定跳过 |
| Node Dependency Audit | `pnpm audit --audit-level high` | Pass；无已知漏洞 |

### Compose / Playwright

- 最终使用临时 `flowtest-s51-review-local` Compose Project 与独立前端端口启动完整栈，15 个服务全部 Healthy。
- `FLOWTEST_E2E_BASE_URL=http://localhost:3306 pnpm exec playwright test --project=chromium
  e2e/s51-mcp-visual-proposal.spec.ts`：Setup 与 S51 用例共 2 passed。
- 真实路径覆盖 Context、Typed External Evidence、Plan、Validate、Compile、Diagnostics、默认 Dry Run、
  Idempotent Draft、MCP Inspect、UI Proposal、Accept、Apply 与 WorkflowDesigner Draft；最终 Graph 与 Proposal
  完全一致，发布版本和 Execution 均为 0。
- 应用日志 Traceback 为 0。敏感关键词分类审计确认 Redpanda 命中均为内置认证机制说明；Backend/Frontend
  的三个命中仅为 Alembic Migration 名称与 `/auth/change-password` 路径，不含请求体、Credential 或 Secret。
- 验收后只删除 `flowtest-s51-review-local` 容器、网络、卷与临时 Override；用户既有
  `flowtest-compact` / `flowtest-ruoyi` / `flowtest-v5-compact` 仍分别保持 6 / 2 / 6 个运行容器。

### 本地 Review

- Requirement Conformance：六个精确 Tool、Scope、Default Dry Run、Idempotency、Expected/Context Revision、
  Optional Target、Mapping、Draft-only 与全部 Proposal 展示/操作均有实现和回归证据。
- Correctness / Data Consistency / Concurrency：复用唯一 Mapping/Review/Apply 链；Snapshot 冻结 Existing Graph；
  Idempotency 与两阶段 Stale Guard 阻止重复写入和陈旧覆盖。
- Security / Tenant / Secret / SSRF：Service Account Scope 与项目授权先行；跨项目拒绝；Proposal/Plan 不访问
  任意 URL、不执行 Flow、不读取 Secret；敏感输入仍沿用 Context/FlowSpec 既有校验。
- E2E / Scope：真实 Alpha 链只到 Workflow Draft。审查中发现并修复 Raw JSON Action 未把当前 Proposal/Mapping
  载入既有 Dialog 的问题；现在安全编辑创建新 ChangeSet，冻结 Proposal 不被原地修改。
- Post-Merge Review：PR #55 合并后才到达的 4 个有效线程全部回复、修复并解决。PR #56 又串行闭环
  Rewired Edge 语义变更、断言空态本地化、Proposal-keyed Override、Offset 分页与无界预加载共 5 轮
  精确头审查；最终头 `0e32e21a76d80b330508d031d18629efa24374c7` 的 Codex Review 明确返回未发现重大问题，
  5 / 5 个 PR #56 Review Thread 均已解决。

### Remote Evidence

- 实现 PR #55：Base `8f20500fd151e89573bb8f01f24cb6512143dbe1`，最终 Head
  `bd4f3276d31fe9882fb7153cbf69275191854d88`。Backend `33150877370`、Frontend `33150877441`、Compose
  `33150877327`、Security `33150877302`、Windows `33150877338`、Upgrade `33150877445`、Draft Controller
  `33150877403` 与 Ready Controller `33153095136` 均 Success。
- PR #55 通过普通 Squash Merge 生成 `f1e2852f7100ae0827a331a7c2ab8f9f87e7781a`。该精确 Main SHA 的
  Backend `33153138632`、Frontend `33153138637`、Compose `33153138644`、Security `33153138584`、Windows
  `33153138682`、Upgrade `33153138664` 与 Required Gate `33153138741` 均 Success。
- 合并后迟到 Review 触发 Post-Merge Review Fix PR #56。该 PR Base 为 `f1e2852f7100ae0827a331a7c2ab8f9f87e7781a`，
  最终 Head 为 `0e32e21a76d80b330508d031d18629efa24374c7`。Backend `33163852048`、Frontend `33163852064`、
  Compose `33163852109`、Security `33163852132`、Windows `33163852069`、Upgrade `33163852068` 与 Required Gate
  `33163850670` 均 Success；合并前状态为 Ready / MERGEABLE / CLEAN，无未解决线程。
- PR #56 通过普通 Squash Merge 生成 `86d2221e63f93e418b87649f56b3fdfe48d365c9`。该精确 Main SHA 的
  Backend `33165883973`、Frontend `33165884044`、Compose `33165883986`、Security `33165884058`、Windows
  `33165884089`、Upgrade `33165884052` 与 Required Gate `33165884082` 均 Success。
- #55 / #56 均未使用 Admin Merge、Ruleset Bypass 或直接推送 Main；合并时 Ruleset Bypass Actor 为空，当前
  用户不可绕过。
- S51 Evidence Closure PR 合并且其 Main Push Required Gate 成功前，不进入 S52。
