# FlowTest V5 S47.2 最终正确性与安全收口

本文记录 `S47.2 — V5 Final Correctness & Security Closure` 的代码事实、验证边界和发布判断。它不授权 Merge、Tag 或 Release；真实 Key Rotation、Windows 实机、连续 RC 和安全审批完成前，`GA_READY` 始终为 `NO`。

## 1. Baseline

| 项目 | 值 |
| --- | --- |
| Branch | `codex/v5.0` |
| Start SHA | `1a2ada2e0716221fa2c1046630c60b3b00cc85d1` |
| Remote Code Evidence SHA | `839d4dbcead073d4639906fda3f592751fb1dc7e` |
| Migration Before | `20260823_0042` |
| Migration After | `20260823_0043` |
| FlowSpec Schema | `flowtest-flow-spec-v1` |
| V5 正式 Fingerprint | `flowtest-flow-spec-fingerprint-v3` |

开发期 FlowSpec fingerprint v1/v2 不属于 V5 正式兼容范围，也不是本轮阻断项。本轮复用现有 Service Target、Workflow/Execution Engine、ChangeSet、Organization/RBAC、Runner Lease 和 MCP Application Service，没有建立平行系统。

## 2. Confirmed Findings

S47.2 开始前确认以下缺口：

1. Canonical Contract 会保留 OpenAPI 的 Example/Default/Const，敏感 Enum 也可能原样持久化。
2. Contract Fingerprint 混入来源修订和 Warning，不能稳定表达 Operation 语义。
3. Header omission 和 missing auth 不能保证删除 Project、Environment、Service Endpoint、API 和 Runtime 的继承载体。
4. Existing Coverage 只按字段和值聚合，可能让不同 Operation 的同名字段互相覆盖，也没有严格要求 Expected Category/Oracle。
5. Change Regression 主要按 Body 路径找约束，Query/Header/Path/Cookie 变化会失去位置语义。
6. Evidence Conflict 只覆盖部分方向；DataProfile 的观察统计会被误作规范性约束；Provenance 过宽。
7. Exclusive boundary 和 Python AST 的 `<`、`<=`、`>`、`>=` 语义不完整。
8. 前端和文档没有完整展示上述安全/范围事实；CI 缺少数据净化 Golden Gate。

## 3. Canonical Contract Sanitization

`app.domain.canonical_contracts` 是 OpenAPI/Swagger Import、ImportedOperation、APIVersion、API Response、MCP/Test Engineering Input、Migration 和 Fingerprint 的统一纯领域入口。

- Schema 使用测试语义白名单；`example`、`examples`、`default`、`const`、`x-example`、`x-examples` 递归删除。
- 检测 JWT、Bearer/Basic、Email、Card、Phone、Access Key、PEM、URI Credential 和高熵值。
- 安全 Enum 原样保留；敏感 Enum 删除原值，只保存数量、值哈希和 `values_redacted=true`。
- 发生安全删除后将 Contract 标为 `redacted_partial` 并增加不含原值的 Warning。
- Test Engineering 对敏感字段只生成 `secret://test-data/...` 引用；依赖缺失安全数据的 Scenario 为 Design-only，不能直接物化。
- OpenAPI 本地 `$ref`、嵌套 Object/Array 和 `oneOf`/`anyOf`/`allOf` 在 Sanitizer 前正确解析，避免只净化浅层。

## 4. Contract Fingerprint Semantics

正式 Fingerprint 只包含 Method、Path、Service 语义、Auth、位置化 Parameter、Request/Response Schema 和约束。以下内容被排除：

- `source_ref`、`revision` 和 Warning；
- 数据库 UUID 或实例 ID；
- 已删除的 Example/Default/Const；
- Redaction 文案。

敏感 Enum 的数量和稳定值哈希仍属于安全语义，因此不同 Enum 集合不会错误地得到相同指纹，也不会暴露原值。

## 5. Request Suppression 与 Auth Disable

`ApiNodeRequestOverrides` 正式支持：

```text
auth_mode: inherit | disabled
suppressed_headers
suppressed_query_parameters
suppressed_cookies
```

`auth_mode` 优先于兼容别名 `auth_disabled`。所有 Scope 合并和认证注入完成后，`RequestTargetResolver.finalize` 才执行最终抑制：Header 不区分大小写、Query 精确匹配、Cookie 使用标准 Cookie Parser。

认证载体规则：Bearer/Basic/OAuth2 删除 `Authorization`；API Key 始终先删除可能继承的 `Authorization`，再根据 `in` 删除 Header、Query 或 Cookie。未知认证无法可靠定位载体时保持 blocker/design-only。

Test Engineering omission 在物化时写入 `suppressed_*`；Snapshot 只记录 Mode 和 Name，不记录 Token/Cookie/API Key 值。FlowSpec v3 对 API Node Config 的往返和指纹保留这些语义。

## 6. Operation Identity 与 Coverage Scope

`OperationIdentity` 包含实例内 API Definition、Portable Operation Ref、Service Key、Method、规范化 Path 和 Contract Fingerprint。`SemanticCoverageFact` 进一步绑定 Location、Field、Value、Scenario Kind、Expected Category、Oracle 和来源资产。

只有已发布 Workflow Version 且只有一个确定性状态 Oracle 的值才是完整覆盖；Pinned API Version 不存在时不会回退 Current。覆盖结果分别返回：

- Project Known Semantic Coverage；
- Impact Selected Asset 范围；
- Current TestPlan ∩ Impact Selected Assets。

项目中存在但未进入本次计划的测试不会消除当前计划缺口，只会产生“加入当前计划”建议。

## 7. Location-aware Change Regression

`ChangeConstraintTarget` 明确包含 Operation、Location、Field/Parameter、Constraint、Before 和 After。Parameter 从 `OperationContract.parameters` 查找，Body 从 Request Body Schema 查找。

当前支持 Body、Query、Header、Path 和 Cookie 的 minimum/maximum、exclusiveMinimum/exclusiveMaximum、长度、Items、Enum、Pattern 和 Format。找不到唯一字段时生成 requires-review blocker，不再伪造 `body.value`。

缺失测试使用当前 Operation Contract 的真实 Response Status 推导 Oracle；Unsupported/Unknown Oracle 不会静默丢弃。位置化 Mutation 物化后进入真实 URL、Query、Header、Cookie 或 JSON Body。

## 8. Evidence Conflict 与 Provenance

确定性权威来源对同一约束给出不同语义时，无论变宽或变窄都形成 Conflict。覆盖 minimum、maximum、exclusive、enum、pattern、required、nullable、type、format、length/items、multiple/unique/FK 等方向。

优先级为 User Confirmed、Contract、DB Constraint、Source Validation、Existing Assertion、Runtime/Observed。优先级只决定 Primary Candidate，不隐藏其他权威冲突。

DataProfile 将 `observed_*` 与 `constraint_*`/`check_constraint` 分离；旧 `minimum`/`maximum`/`enum_candidates` 按观察统计解释。Observed 只提供合法数据建议和分布提示，不生成非法 Oracle，也不与 Contract 形成规范性冲突。Existing Test 进入 Coverage/Drift Candidate，不改写 Contract。

Scenario、Oracle 和 Coverage 只引用实际参与推导的 Finding。前端以 `normative`、`observed`、`mixed`、`coverage` 或 `supporting` 展示 Evidence Role。

## 9. Exclusive Boundary

内部统一保留 JSON Schema 数值 exclusive 语义：Swagger/OpenAPI 3.0 的 Boolean Exclusive 与 minimum/maximum 合并为数值 Exclusive；OpenAPI 3.1 的数值形式直接保留。

```text
x < 999  → exclusiveMaximum=999 → 998 valid / 999 invalid
x <= 999 → maximum=999
x > 1    → exclusiveMinimum=1   → 1 invalid / 2 valid
x >= 1   → minimum=1
```

Number 优先使用 `multipleOf` 作为步长，否则使用稳定的 next-representable 值；Fingerprint 不依赖浮点展示文案。

## 10. Migration

Revision `20260823_0043` 扫描 `api_versions.canonical_contract`，调用运行时同一 Sanitizer，重算 Fingerprint 和 Completeness。迁移没有结构变更，Downgrade 只移动 Alembic Revision，不恢复已删除数据；安全净化是不可逆操作。

Standalone Baseline/Incremental Schema 和 Transfer Manifest 同步到 `0043`。真实 PostgreSQL Golden 流程在 `0042` 插入敏感 Fixture 后执行 `0042 → 0043 → 0042 → 0043`，每一步验证原值不再出现、指纹稳定且 `alembic check` 无 Drift。

## 11. Frontend

Test Engineering 展示 Contract Completeness、Redaction Warning、Operation Identity、Parameter Location、Auth Mode、Suppression、Evidence Role/Conflict、Coverage Scope 和 Design-only 原因。

Change Regression 展示 Asset Mapping、Project Known 和 Current TestPlan 三个维度，并列出 Operation、Location、Field、Constraint、Before/After、Existing/Missing Values 和 Oracle Source。Failure Triage v2 的 Service、Variant、Primary/Secondary、Evidence 和 Action 保持不变。

## 12. CI 与 Smoke

- Security CI 执行 Canonical Contract Domain、API/Audit/TestDesign 和 Standalone 数据泄漏 Golden Test。
- Backend Integration 在真实 PostgreSQL 执行 `0042 → 0043 → 0042 → 0043` 数据验证。
- Compose CI 的 S47.2 Smoke 使用真实 Mock Target 验证多 Service、Body/Query/Path/Header、Bearer/Basic/API Key Query/API Key Cookie、跨层 Suppression、Response Schema、Operation-scoped Regression、Current TestPlan Scope、Exclusive Boundary、MCP Generate/Dry Run、Proposal Review/Apply 和 Snapshot Redaction。
- PR 和 `main` 都会触发相关 Workflow；`deploy/s47/**` 和 `scripts/smoke_s47*.py` 会触发 Compose。
- Compose Gate 使用独立 Project、容器、Network、Volume 和 Host Port；PostgreSQL、Redis、MinIO、Redpanda 与 gRPC Target 不暴露宿主端口。验证结束后使用 `down --volumes` 清理全部专用资源。

## 13. Capability Truthfulness

- Pairwise：当前名称和承诺为 Bounded Pairwise Partitions/Representative Pair Combinations，不是完整 covering array。
- State Model：unavailable/experimental；请求但无显式状态证据时返回 Capability Unavailable，不 silent no-op。
- Knowledge Graph：Basic Test Knowledge Graph，不宣称完整业务知识图谱。
- Key Rotation：只有 planned 元数据；真实 Apply/Re-encrypt/Verify/Rollback 未实现。
- FlowSpec：V5 正式支持 fingerprint v3；开发期 v1/v2 不属于正式兼容范围。

## 14. Local Test Results

| Gate | 结果 |
| --- | --- |
| Ruff Format / Check | PASS；467 个 Python 文件格式检查通过，Ruff 全量检查通过 |
| Mypy | PASS；354 个 Source File 无错误 |
| Import Linter | PASS；321 个文件、1421 条依赖，1 个架构 Contract 保持 |
| Backend Pytest | PASS；494 passed、3 skipped |
| Backend Coverage | PASS；90.02%（32,071 statements，3,202 missed） |
| Frontend Tests | PASS；56 个文件、212 个测试 |
| Frontend Coverage | PASS；Statements 86.21%、Branches 80.25%、Functions 85.47%、Lines 88.38% |
| Frontend Build | PASS |
| Migration | PASS；真实 PostgreSQL `0042 → 0043 → 0042 → 0043`，最终 Current/Head 均为 `0043`，无 Drift |
| Standalone | PASS；23 个 Standalone Runtime/Transfer 测试 |
| Compact | NOT RUN |
| Compose Smoke | PASS；6 个负向执行、4 个跨层 Suppression 执行，隔离资源已清理 |
| Playwright | PASS；1 个 Setup、2 个 S47 端到端规格 |
| MCP | PASS；7 个 MCP Read/Generate/Dry Run 测试 |
| Dependency Audit | PASS；Python 与 Frontend 均无已知高危漏洞 |

本地结果不替代 Remote CI；未执行的 Compact 长时运行仍明确为 `NOT RUN`。

## 15. Remote CI Results

代码证据提交 `839d4dbcead073d4639906fda3f592751fb1dc7e` 的 Draft PR 远端矩阵全部完成并通过：

| Workflow | Run ID | Conclusion | Failed Job/Step | URL |
| --- | ---: | --- | --- | --- |
| Backend CI | 32637129945 | SUCCESS | — | https://github.com/a3384379/FlowTest/actions/runs/32637129945 |
| Frontend CI | 32637129858 | SUCCESS | — | https://github.com/a3384379/FlowTest/actions/runs/32637129858 |
| Security CI | 32637129848 | SUCCESS | — | https://github.com/a3384379/FlowTest/actions/runs/32637129848 |
| Compose Smoke Test | 32637129857 | SUCCESS | — | https://github.com/a3384379/FlowTest/actions/runs/32637129857 |
| Standalone Windows Bundle | 32637129851 | SUCCESS | — | https://github.com/a3384379/FlowTest/actions/runs/32637129851 |
| V2 to V3 Upgrade CI | 32637129859 | SUCCESS | — | https://github.com/a3384379/FlowTest/actions/runs/32637129859 |

Compose 的 `smoke` 和 `compact-smoke` 两个 Job 都成功；完整 Smoke 同时通过了 S19 不可变工作流 Flaky 验证、S47.2、容量和备份恢复。表中 Windows 结果是 GitHub-hosted Windows Bundle 构建验证，不等同于用户环境 Windows 实机验收。

## 16. Remaining Risks

- P0：本地与代码证据 SHA 的 Remote CI 均无已知 P0。
- P1：完整 covering array、显式 State Engine 和完整 Knowledge Graph 未实现。
- P2：本地 Compact 长时运行未执行；远端 Compact Smoke 已通过，但不能替代连续长时运行。
- External：Windows 实机、连续 Standalone/Compact 运行、RC 观察和安全审批仍需外部证据。
- GA Blocker：真实 Key Rotation 尚未实现。

## 17. Release Decision

```text
READY_FOR_V5_FUNCTIONAL_COMPLETION_REVIEW
MERGE_TO_MAIN: GO
RC_READY: YES
GA_READY: NO
```

这里的 `MERGE_TO_MAIN: GO` 仅表示功能与自动化门禁允许进入人工合并评审；本文不授权也未执行 Merge、Tag 或 Release，Draft PR 状态保持不变。

## S47.3 取代说明

S47.2 完成后复审发现 Oracle-aware Coverage、Current Plan Gate、多 Service 身份、AST 控制流、
Canonical Keyword 值校验、Enum Hash 和 MultipleOf 仍有缺口。本文的 GO 判定不再作为当前合并证据；
以 [S47.3 最终语义完整性闭环](s47-3-final-semantic-integrity.md) 和最终 HEAD 的 Required CI 为准。

## S47.4 取代说明

S47.4 复审发现 S47.3 Coverage 匹配仍可跨 API Version/Contract Fingerprint，条件 AST 与
Workflow Assert 必达性仍可制造过度覆盖。本文中旧 SHA 和 `MERGE_TO_MAIN: GO` 不再是当前
合并证据；以 [S47.4 最终评审修复](s47-4-final-review-fix.md) 和 PR #40 的精确
HEAD CI 证据为准。`RC_READY: NO`，`GA_READY: NO`。
