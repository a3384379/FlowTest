# FlowTest V5 自主功能验收与合并记录

## 1. 验收基线

- 任务：S47.7 — V5 Autonomous Functional Acceptance & Merge。
- 开发分支：`codex/v5.0`。
- 开始 SHA：`793f00f6b3b47b808b703011b0bef0b14a425860`。
- 同步的 main Base：`c1b688df64f41a283d5261455a0116a8de04c867`。
- Pull Request：[#40](https://github.com/a3384379/FlowTest/pull/40)。
- Migration Head：`20260823_0045`。
- 最终 Branch HEAD、Merge Commit 和合并后 main CI 由 PR #40 的
  `V5 autonomous acceptance evidence` 评论和任务最终报告记录。Git 提交不在自身内写入
  一个伪造的“自引用最终 SHA”。

S47.7 不扩展 V5 功能面，只完成最终需求核对、独立自动审计、缺陷修复、
真实用户链路验收和合并收口。开发代码不等待人工 Reviewer，但不绕过分支保护、
Required Checks、安全扫描或仓库权限。产品内 TestDesign Review 和 Waiver 的人工业务语义不变。

## 2. V5 需求矩阵

| 能力 | 实现 | 验证证据 | 能力边界 |
|---|---|---|---|
| Service Target | Environment/Service/Endpoint/Variant 分层，API 默认与 Node Override 共用 Resolver | Multi-Service Smoke、Snapshot/Suppression 回归 | Legacy `base_url` 仅作兼容退路 |
| FlowSpec | v3 Fingerprint、Portable Service/Operation Ref、固定 API 版本、ChangeSet Import | Roundtrip、UUID-independent Fingerprint、Pinned Version 回归 | 开发期 v1/v2 不支持 |
| Test Engineering | Canonical Contract + Evidence + Scenario + Oracle + Coverage + Materialization | Boundary/Location/Auth/Oracle/Conflict/Consistency Golden Tests | Pairwise 仅 Bounded/Representative；State 不可用/实验性；KG 为 Basic |
| MCP | Application Service 边界、`mcp:read/write`、Dry Run、幂等 Draft Write | MCP Read/Controlled Write/Redaction/Conflict Smoke | 不自动 Publish/Execute，不创建 Credential/修改权限 |
| Tenant | Organization/TenantContext 覆盖 Project/Execution/Evidence/Runner/MCP | Tenant Isolation、Service Account Scope、Runner Claim 回归 | Standalone 使用 `local-default` |
| Durable Execution | Command/Checkpoint/Resume/Retry/Lease/Fence/Child Execution | Durable Execution、Dataset Child、Fence 和恢复回归 | 档位差异仅限基础设施能力 |
| Change Regression | Change→Impact→Selection→Semantic Gate→Plan→Execution→Release | S47.1–S47.7 Golden/Integration/Compose | Waiver 始终是 WAIVED，不伪装为 COVERED |
| Runtime Release Evidence | RunItem→Execution→Node→Observation→Assert | Early 409、Skipped/Failed/Runtime Override/Dataset/Mutation/Repeat 回归 | 缺失或脱敏后无法精确证明时 fail closed |
| Runtime Profiles | Standalone/Compact/Full 共用业务语义 | SQLite/PostgreSQL/Transfer/Compose/Windows CI | Standalone 不承诺 HA |
| Security | Canonical 严格校验、SSRF/重定向、Tenant、Redaction、固定依赖 | Security Rules、Leak Tests、Dependency/Image Scan | Key Rotation 仅 Planned Metadata Only |

## 3. Automated Review Pass A — Requirement Conformance

审计代码、迁移、测试和实际链路，不仅引用进度文档。十个 V5 能力均有 Domain /
Application Service / API 或 Runtime / Test 证据链。未发现伪造的完整 Pairwise、完整
State Engine、高级 Knowledge Graph 或真实 Key Rotation 宣称。

- Implemented：V5 正式目标。
- Partially Implemented：仅文档明确的 Bounded/Basic/Experimental 能力。
- Intentionally Out of Scope：FlowSpec 开发期 v1/v2、真实 Key Rotation、GA 外部签署。
- Missing/Misrepresented P0/P1：无。

## 4. Automated Review Pass B — Correctness and Consistency

发现并修复：

1. 已分配 Service 的 Runtime Coverage 曾允许缺失 `service_key` 的 Observation 匹配；
   现在只允许精确 Service，仅 legacy `unassigned` 保留非约束语义。
2. 已完成的 Release Gate 重复调用曾可重新解释后续 Plan/Waiver 状态；现在在确认
   TestPlanRun 仍为终态后直接返回同一不可变 Decision/Evidence/Stage。
3. 聚焦变更字段的 Missing Test 生成会丢失完整当前契约中其他必填请求字段；
   现在将聚焦变异重放到完整有效请求基线上。

重复 Execute/Add-to-Plan/MCP Write 的幂等、固定版本、Contract Drift、Dataset Child、
Checkpoint/Fence、Waiver Revision/Supersede 和事务顺序均由现有测试覆盖。

## 5. Automated Review Pass C — Security

本轮按 Python/FastAPI 和 React/TypeScript 安全检查表审计。修复了允许 Credentialed
CORS 配置 `*` 或非 HTTP(S)/含 UserInfo、Query、Fragment、非根 Path Origin 的配置缺口。

已确认：生产默认值阻断、JWT/Argon2、最终地址 SSRF 校验、重定向限制、Tenant
边界、Canonical/MCP/Audit/Observation 脱敏、敏感 Enum 无哈希持久化。防御深度 P2：
Swagger 默认可见、未配置 Trusted Host 中间件、边缘层尚需由部署补齐 CSP /
frame-ancestors / Permissions-Policy；未发现因此导致的 V5 P0/P1。

## 6. Automated Review Pass D — End-to-End User Flow

在独立 Compose Project/Network/Volume/Port 中执行：

```text
S14 management workbench
→ OpenAPI import / Service / Endpoint / API / Workflow
→ TestDesign generate / review / materialize / publish
→ Change Regression / Missing Test / Add-to-Plan
→ TestPlan execute
→ Runtime Node Evidence / Release Gate
→ repeated immutable Release Gate
→ S14 management workbench
```

物化的 5 个固定版本 Workflow 均实际执行通过，非目标必填 Body 字段保持完整；
Release Evidence 基础为 `runtime_node_evidence`，没有使用 Waiver。运行前后 S14 都通过，
未发现顺序污染。

## 7. S47.6 Runtime Evidence 最终核对

| 场景 | 结果 |
|---|---|
| Queued/Running 时提前评估 | `409 CHANGE_REGRESSION_EXECUTION_PENDING`，状态/Evidence/Stage/Decision/最终 Audit 不变 |
| Runtime Variable Override | 仅 Observation 中的最终值可覆盖对应 Requirement |
| Conditional/Skipped Node | 未进入分支的 API/Assert 不计 Covered |
| Dataset | 按 Child Execution/实际行证据分开计算 |
| Plan Mutation After Execution | 使用当次 TestPlanRunItem Snapshot，不重解释当前 Plan |
| Failed/Cancelled | 无视宽松 Policy 固定阻断 |
| Repeated Evaluation | 同一 Decision ID、Evidence、Stage 和 Fingerprint |
| Service Identity | 已分配 Service 必须与 Runtime Observation 精确匹配 |

## 8. 门禁与合并流程

完成验收的最终实际数值同步记录在 PR #40 评论和最终报告。可重现门禁为：

- Backend：Ruff Format/Check、Mypy App+Scripts、Import Linter、Full Pytest + Coverage、Pip Audit。
- Frontend：Format、Lint、Vitest Coverage、Build、Audit。
- Migration：PostgreSQL Empty→0045、0045→0044→0045、Current、Check；SQLite/Transfer 回归。
- Compose/Playwright：独立 `S14→S47.7→S14`。
- Remote：Backend、Frontend、Security、Compose、Upgrade、Windows 必须绑定精确 PR HEAD。

本次最终工作区的本地结果：

- Backend Ruff/Mypy/Import Linter：通过；Pytest `590 passed / 3 skipped`，Coverage `90.11%`。
- Backend Pip Audit：无已知漏洞；本地项目包因不在 PyPI 而按工具预期跳过。
- Frontend：`56` 个文件、`215` 个测试通过；Statements `86.15%`、Branches
  `80.11%`、Functions `85.27%`、Lines `88.37%`；Build/Audit 通过。
- PostgreSQL：Empty→0045、0045→0044→0045、Current 和 Alembic Check 通过，无 Drift。
- Compose/Playwright：独立端口与数据卷的 `S14→S47.7→S14` 通过，资源已精确清理。
- Remote CI：仓库文档提交时尚未产生自身的最终 SHA；不预写成 PASS。推送后的精确
  Run ID/SHA/Conclusion/URL 固化在 PR #40 验收证据评论和最终任务报告中。

在 P0/P1 清零、本地门禁全通过、精确 HEAD 的 Required CI 全绿、Base 未过期且
GitHub 报告 Mergeable 后，将 PR #40 从 Draft 转为 Ready，再依仓库策略 Squash Merge。
不使用 Admin/Force Merge，不降低分支保护。如 main CI 失败，只通过新分支和 PR 修复。

## 9. Remaining Risks 与功能判定

- P0/P1：合并前必须为 0。
- P2：上述 HTTP 边缘防御深度，不影响 V5 业务正确性或安全放行。
- External Validation：Windows 用户实机、Standalone/Compact 长时观察、RC 连续观察。
- GA Blockers：企业安全审批、生产发布授权、真实 Key Rotation。

```text
Pairwise = Bounded / Representative
State Model = Unavailable / Experimental
Knowledge Graph = Basic
Key Rotation = Planned Metadata Only
FlowSpec v1/v2 = Development-only / Unsupported Compatibility
GA_READY = NO
```
