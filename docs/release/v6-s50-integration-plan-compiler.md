# FlowTest V6.0 S50 Multi-Operation Plan 与 Executable FlowSpec Compiler

## 1. 阶段身份

| 项目 | 当前值 |
| --- | --- |
| 阶段基线 Main SHA | `8040882218bfa70df556c42482c69d2413190ec6` |
| 实现分支 | `codex/s50-integration-plan-compiler` |
| Schema | `flowtest-integration-plan-v1` |
| Compiler | `flowtest-integration-plan-compiler-v1` |
| 数据库变更 | 无；Plan 进入既有 AIChangeSet Source Snapshot |
| Release 状态 | 未发布；不是 Alpha、Beta、RC 或 GA |

S50 从 S49 Evidence Closure 合并且 Main Required Gate 全绿后的精确 Main 创建。本阶段只实现 Plan、
确定性 Planner/Compiler 与既有 Draft Review/Apply 链的证据接入，不提前注册 S51 MCP Tool 或 Proposal UI。

## 2. Implemented

### 版本化 Integration Plan

- 严格 Pydantic Contract 固定 Context Revision/Fingerprint、Objective、Actors、Preconditions、Target
  Environment、Operations、Steps、Branches、Bindings、Data Recipes、Oracles、Cleanup Requirements、
  Coverage Targets、Unresolved Items、Review Requirements、Confidence、Diagnostics 与 Evidence References。
- 所有模型 `extra=forbid`；规范化后计算 `flowtest-integration-plan-fingerprint-v1`，相同语义输入得到相同指纹。
- Operation 必须记录 `selected_by_user=true`、Canonical Contract Fingerprint、Version、成功状态与 Evidence。
- 多候选 Binding 保留全部 Candidate、Confidence 与 Evidence，不选择任意“第一个”；缺少 Evidence、
  Object/Scalar 冲突、未解决 Review 或 Secret Literal 均阻止编译。

### Planner 与真实资产读取

- 纯 Planner 根据 Canonical Contract 的 required Request Field 与先前成功 Response Field 做同名、同型匹配；
  Bearer Token 只使用安全 `Bearer {{value}}` Template，不读取 Secret。
- 已选 Operation 可复用现有单 Operation Test Engineering 的确定性成功 Scenario 和适用 Oracle。
- 只读 `IntegrationPlanAssetService` 从当前项目的 API Definition/Version、Canonical Contract、Service 与已发布
  Existing Workflow Version 解析 Evidence；跨项目、停用或缺失资产使用标准错误信封拒绝。
- Existing Auth 仅以固定 Workflow ID/Version 的 SubFlow 与显式 Token Output Path 进入 Plan；服务不解密 Secret、
  不持久化 Plan、不创建 Workflow。

### Executable FlowSpec Compiler

- Compiler 顺序记录 Normalize、Resolve Operations、Resolve Services、Build Graph、Compile Edge Mapping、
  Compile Assert Nodes、Compile Variables/Data、Validate、Fingerprint 与 Diff 十个 Pass。
- Operation、Response Extraction、Field Binding、Status/Schema/Field Oracle、单个显式二分支、Dataset 与 Existing
  Auth 分别编译为 API、Extract、`WorkflowEdge.mappings`、Assert、Condition、Dataset 与 SubFlow Node。
- 当前运行时不支持的 Path/Cookie Mapping、未确认 Candidate、Secret/External Evidence Runtime Source、多个
  Dataset、Setup API Recipe 和会破坏条件语义的 Branch 首节点 Mapping 均输出 Blocker，不生成降级 FlowSpec。
- Cleanup Requirement 只保留在版本化 Plan Snapshot 并输出 `CLEANUP_RUNTIME_DEFERRED`，不写入 FlowSpec
  `cleanup`；同样不写全局 bindings/assertions、synthetic_data、secret_ref parameter 或非默认 Security Policy。
- Compiler 为纯领域函数，不访问网络、不查询数据库、不写库、不读取 Secret、不创建 Workflow；同一 Plan 的
  FlowSpec 与 Fingerprint 稳定。

### ChangeSet Source Snapshot 与 Golden

- 既有 `FlowSpecService.create_import()` 可接收类型化 Plan/Compilation Provenance；写入前校验 Plan Fingerprint、
  Context Revision/Fingerprint 与实际 FlowSpec Fingerprint 一致。
- Snapshot 冻结完整 Plan、Plan Fingerprint、Compiler Version、FlowSpec Fingerprint、Pass、Diagnostics、Node
  Evidence 与 Edge Evidence；不新增 Plan 表或第二套 Proposal/Review 状态机。
- Golden 固定 Login Token → Create Entity → Extract Create Response ID → Query by ID → Assert ID/Status/Schema，
  同时冻结 Plan 与 Compiled FlowSpec JSON 及两类 Fingerprint。
- 真实服务层集成测试完成 Compile → AIChangeSet Draft → Review → Apply → Workflow Draft，并验证 API、Extract、
  Assert 与 Edge Mapping 均进入既有 WorkflowDefinition。

## 3. 安全与兼容边界

- Plan Request 中 Authorization、Cookie、Password、Token、Secret/API Key 等敏感字段拒绝 Literal；只允许
  Secret Reference 作为意图证据，当前 Compiler 不把它作为 FlowSpec Runtime Parameter。
- Existing Auth 复用固定已发布 Workflow Version；Context、Plan、Compilation 与 FlowSpec 指纹任一不一致，
  在 ChangeSet 写入前返回 `INTEGRATION_PLAN_PROVENANCE_INVALID`。
- HTTP Router、MCP Tool 与 UI 未新增；S49 的 Draft-only Adapter 及现有 FlowSpec Import/Mapping/Review/Apply/
  Stale Revision 规则保持唯一实现。
- 无 Alembic 或 Standalone Schema 变更，Migration Head 保持 `20260828_0046`。

## 4. Exit Criteria

| 条件 | 本地状态 | 证据 |
| --- | --- | --- |
| FlowSpec Validate = true | Pass | Golden 编译结果 `validate_flow_spec().valid=true` |
| FlowSpec Importable = true | Pass | Compatibility 无 Blocker，未使用不可执行顶层字段 |
| Workflow Draft 可创建 | Pass | 真实 SQLite 应用层 Review/Apply 集成测试与 Compose Playwright |
| Fingerprint 稳定 | Pass | 静态 Plan/Compiled FlowSpec Golden Fingerprint |
| Node/Edge Evidence 可追溯 | Pass | Compilation 与 ChangeSet Snapshot 双重断言 |

## 5. Intentionally Out of Scope / Blocked

### Intentionally Out of Scope

- S51 MCP Plan/Validate/Compile/Explain/Propose/Inspect Tool、Visual Proposal Mode 与用户可见 Alpha。
- S52 Java/DB Evidence Adapter 与 Entity Mapping、S53 DB Oracle、S54 Cleanup Runtime、S55 Sandbox Preview、
  S56 Flagship Skill。
- 自动 Review、Apply、Publish、Execute，完整 State Graph、多个/嵌套 Branch 与当前引擎不能无损表达的 Mapping。

### Blocked

- S50 当前无本地实现阻断。真实 Key Rotation 仍是 S55 的外部授权门槛，本阶段不推断其完成。

## 6. Validation 与 Remote Evidence

### 本地 Required Checks

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| Backend Format | `uv run ruff format --check .` | Pass；458 files already formatted |
| Backend Lint | `uv run ruff check .` | Pass |
| Backend Types | `uv run mypy app` | Pass；334 source files |
| Backend Tests | `uv run pytest` | Pass；659 passed、4 skipped、总覆盖率 90.32% |
| Compiler Complexity | `uv run ruff check --select C90 app/domain/integration_plans.py app/services/integration_plans.py` | Pass |
| Frontend Format | `pnpm format:check` | Pass |
| Frontend Lint/Types | `pnpm lint` | Pass；ESLint 与 TypeScript |
| Frontend Tests | `pnpm test:coverage` | Pass；56 files、215 tests；S/B/F/L = 86.15/80.11/85.27/88.37% |
| Frontend Build | `pnpm build` | Pass |
| Backend Security Lint | `uv run ruff check --select S app` | Pass |
| Python Dependency Audit | `uv run pip-audit` | Pass；无已知漏洞，非 PyPI 的本项目包按工具约定跳过 |
| Node Dependency Audit | `pnpm audit --audit-level high` | Pass；无已知漏洞 |

### Compose / Playwright

- 使用临时 `flowtest-s50-local` Compose Project 与独立端口启动完整栈，15 个服务全部 Healthy。
- `FLOWTEST_E2E_BASE_URL=http://localhost:3305 pnpm exec playwright test --project=setup e2e/auth.setup.ts`：
  1 passed。
- `FLOWTEST_E2E_BASE_URL=http://localhost:3305 pnpm exec playwright test --project=chromium
  e2e/s50-integration-plan-compiler.spec.ts`：Setup 与 S50 用例共 2 passed。
- 应用日志未发现 Password Field、JWT-like Value 或 Traceback；命中的 Authorization/Bearer 字样仅来自
  Redpanda 启动说明，不包含应用凭据。
- 验收后仅删除 `flowtest-s50-local` 容器、网络、卷与临时 Override；用户既有 `flowtest-compact`、
  `flowtest-ruoyi`、`flowtest-v5-compact` 分别保持 6、2、6 个运行容器。

### Golden 与本地 Review

- Integration Plan Fingerprint：`7bd623c2832118dd070d707b91b5be87c714bdea6035bbfa66bd3c2155ccd85a`。
- Compiled FlowSpec Fingerprint：`e1d437108b19296a0d73fd23159f9f80e872f2ff86e5a946e9d97c94fb177e12`。
- Requirement Conformance：必需 Contract 字段、十个 Compiler Pass、Golden、Exit Criteria 与 S51+ 边界均有
  实现和回归证据。
- Correctness / Data Consistency / Concurrency：读取固定 API/Workflow Version 并重算 Canonical Fingerprint；
  Assert 节点串联为后续节点的执行门，消除断言失败仍可绕行的图路径；纯编译无共享可变状态。
- Security / Tenant / Secret / SSRF：项目授权先于资产读取；跨项目引用拒绝；Secret 仅保留引用证据且不解密、
  不写参数、不记录值；Header CRLF 与 External JSON Schema `$ref` 拒绝；编译无网络 I/O。
- E2E / Scope：真实 Draft → Review → Apply 创建 Workflow Draft；未新增 S51 MCP Endpoint、Router 或 UI。

### Remote Evidence

#### Implementation PR #53

| 事实 | 精确证据 |
| --- | --- |
| Base | `8040882218bfa70df556c42482c69d2413190ec6` |
| PR Head | `9193b7fe8bcdf012d275e15319bee65ca907fb4a` |
| PR Workflow | Backend `33142324888`；Frontend `33142324905`；Compose `33142324889`；Security `33142324904`；Standalone Windows `33142324907`；Upgrade/Rollback `33142324903`；Draft Controller `33142324894`；Ready 后 Controller/Required Gate `33143796260`，全部 Success |
| Review | Review `0`、Comment `0`、Review Thread `0`；Ready 后 CLEAN / MERGEABLE |
| Merge | PR #53 普通 Squash Merge：`507aff999606ab6b3190810cf25717a55265eb88` |
| Main Push | Backend `33143838057`；Frontend `33143837990`；Compose `33143838011`；Security `33143838022`；Standalone Windows `33143837984`；Upgrade/Rollback `33143837977`；Required Gate Controller `33143838004`，全部 Success |

- PR 与 Main Push 的全部 Workflow 都绑定各自记录的精确 Head/Merge SHA；没有把旧 Run 或其他分支结果记为
  本阶段证据。
- PR 保持 Draft 直至底层检查与四类本地 Review 完成；切 Ready 后新触发的 Controller `33143796260`
  Success，随后才执行普通 Squash Merge。未使用 Admin Merge、Bypass、Force Push 或 Direct Main Push。
- Merge SHA Commit Status 为 Success，且只有 Integration `15368` 写入的 `Required Gate`；其 Target 为 Main
  Controller `33143838004`。

#### Governance 与串行结论

- 收口时 `main-required-gate` Ruleset `21653796` 为 Active，`bypass_actors=[]`，要求解决 Review Thread，
  Strict Required Status Check 仅为 `Required Gate`。
- S50 实现 Exit Criteria 与实现 PR/Main Push 远程证据已满足；本 Evidence Closure PR 合并且其 Main Push
  Required Gate 成功前，不进入 S51，也不把 S50 标为阶段闭环完成。
