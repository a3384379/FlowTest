# FlowTest V5 S47.4 最终评审修复

状态：候选实现与验证记录（2026-08-25，Asia/Shanghai）

本文记录 `S47.4 — V5 Final Review Fix`。它只关闭 Operation Coverage 身份、
AST 条件上下文、Operation Selection 重生成、Waiver 生命周期、Assert 必达性和
Playwright 顺序隔离问题，不新增 V5 大功能，不增加旧 FlowSpec 兼容工作。

## 1. Baseline

- Branch：`codex/v5.0`
- Start SHA：`db622cef81e11b6a4f31213c8b2077f46f5f8b62`
- Migration Before：`20260823_0044`
- Migration After：`20260823_0045`
- Draft PR：[#40](https://github.com/a3384379/FlowTest/pull/40)
- 开始时本地 HEAD、`origin/codex/v5.0` 和 PR Head 一致，独立 Worktree 干净。
- 基线的六个精确 HEAD GitHub Actions 均成功；PR 仍为 Draft 且无人工 Review。

## 2. Confirmed Findings

Phase 0 逐项证实两个 P0 和五个 P1：Coverage 忽略 API Version/Fingerprint；嵌套
AST 局部约束被提升；Operation 选择后 Proposal 未重生成；过期 Waiver 无法续签；
Workflow Assert 未分析必达；S47 后 S14 有顺序失败；PR 仍是 S47.2 旧证据。
未发现已被基线修复的该类 False Positive，也没有为提示词制造无意义 Diff。

## 3. Operation Coverage Identity

所有 Coverage 路径复用同一纯领域匹配器：

```text
api_definition_id
api_version
contract_fingerprint
service_key
method
normalized_path
portable_operation_ref
```

两侧都有实例 API ID 时，全部字段必须精确一致。只有当至少一侧没有实例 ID
时才进入 Portable 比较，使用 Service/Method/Path/Portable Ref/Fingerprint，不使用实例 UUID。
这使跨实例等价资产仍可移植，但不会用 v1 覆盖 v2。

## 4. API Version Coverage

同一 API Definition 的不同固定版本是不同 Operation Semantics。Published Workflow API Node
缺少或包含非法 `api_version` 时不回退 current，因为系统无法证明实际执行版本。
Coverage 诊断显示 `VERSION_MISMATCH`，不会静默转为 Covered。

## 5. Contract Fingerprint Coverage

即使 API ID 和 Version 相同，Canonical Contract Fingerprint 不同也是
`CONTRACT_MISMATCH`。Fingerprint 进入 Change Source Snapshot、Item Binding、Proposal 身份、
Coverage Fact 和 Materialization 复验，防止导入后变更或错误绑定被隐藏。

## 6. AST Conditional Context

AST 遍历传递 `conditional_depth` 和 `branch_kind`。顶层 Assert、明确 Validator Return、
Guard+Raise 仍可作为确定性全局约束；If/Try/Except/Finally/Loop/With/Match 内的
Assert、Return 或 Guard 记录为 `supporting_condition`，`deterministic=false`、
`confidence=0.5`、`requires_review=true`，不投影到全局 Boundary 或 Oracle。

## 7. Operation Selection Regeneration

人工选择 API Definition + Version 后，服务端重新解析 Canonical Contract，重算 Project/Plan
Coverage，并对所选 Operation 重新生成 Missing TestDesign。源 Snapshot 、Frozen Operation、
Item Binding 和 Design Fingerprint 同步更新。旧 Draft 被明确 Supersede/Reject；若精确覆盖已存在，
不会生成假缺口。Reviewed/Materialized 选择返回 409，不得静默改写。

## 8. Waiver Revision

`semantic_gap_waivers` 新增从 1 开始的 Revision 和可空 Self-FK `supersedes_waiver_id`。
同一 Run/Gap 有 Active 版时重复创建返回 409；旧版过期后可创建 Revision 2，
保留 Revision 1 和完整 Audit。门禁和 Release Evidence 只使用最高、未过期、
匹配当前 Requirement Fingerprint 的 Revision。Service Account/CI Token 仍返回 403。

## 9. Assert Reachability

Published Workflow Oracle Extractor 为每个 Request Node 建立有向执行图，分析 Assert 的可达性和
分支性：Linear 和 Post-join 为 `unconditional_assert`；Conditional 为
`conditional_assert` 且只算 Partial；Disconnected 为 `disconnected_assert` 且不计覆盖；
无法证明的 Cycle 为 `unknown_graph` 并要求 Review。API Node 本身的单一确定
`expected_statuses` 记为 `direct_oracle`。

## 10. Playwright Root Cause

首次隔离复现时，S14 的 Project Configuration PUT 成功后，共享 mutation 调用全局
`queryClient.invalidateQueries()`，使同一组件的 `pending` 状态长时为 true，Secret 按钮保持
loading，点击未发出 PUT。修复将失效范围收紧为当前项目的 Folder、Configuration、
Environment、Secret 和 Audit query key；E2E 通过 API 创建独立项目，显式等待按钮离开
loading，并校验 PUT 响应成功。三轮 `S14→S47→S14` 全部通过。

## 11. Migration 0045

0045 不改写已推送的 0044。Upgrade 增加 Revision 列、回填 1、Supersedes Self-FK、
`(run_id, gap_key, revision)` 唯一约束、Revision Check 和索引。Downgrade 为恢复 0044 唯一约束，
每个 Run/Gap 只保留最高 Revision，是明确的表示层有损回滚。Standalone Baseline、
Transfer Revision、Upgrade Script 和 Windows Bundle 都同步到 0045。

## 12. Local Tests

- Backend：Ruff Format/Check、Mypy（324 source files）、Import Linter 全部通过；
  `568 passed, 3 skipped`，Coverage `90.07%`；Pip Audit 无已知漏洞。
- Frontend：Format/Lint、`56` test files / `215` tests、Coverage Gate、Build 通过；
  Statements `86.14%`、Branches `80.16%`、Functions `85.26%`、Lines `88.37%`；
  Pnpm Audit 无已知漏洞。
- Migration：隔离 PostgreSQL 17.6 完成 `0044→0045→0044→0045`；`current` 为
  `20260823_0045 (head)`，`alembic check` 无 Drift，Revision 1/2 和 Self-Link 保持。
- Compose/Playwright：独立 Project Name、Ports、Volumes，S47.4 Smoke 通过；三轮
  `S14→S47→S14` 全部通过；完成后仅对任务项目执行 `down --volumes`。
- Golden：Version/Fingerprint/Portable Match、Conditional AST、Regeneration、Waiver Renewal、
  Assert Reachability 和 Sparse Item Binding 全部通过。

## 13. Remote CI

只有推送后最终 HEAD 的 Backend CI、Frontend CI、Security CI、Compose Smoke Test、
Standalone Windows Bundle 和 V2 to V3 Upgrade CI 全部完成且成功，才能进入人工合并评审。
为避免“回填 Run ID 又创建新 HEAD”的循环，精确 SHA、Run ID、Conclusion 和 URL 以 PR #40
的 `S47.4 final CI evidence` 评论为权威记录；本地结果不代替远程 CI。

## 14. PR Evidence

PR #40 必须更新为 S47.3 + S47.4 当前范围，保持 Draft，不自动请求 Reviewer，
不自动 Merge、Tag 或 Release。最终证据评论必须对应推送后精确 HEAD，不得引用
S47.2 旧 SHA 作为当前证据。

## 15. Remaining Risks

- P0/P1：本地实现和自动化无已知未关闭项；推送后还必须以精确 HEAD Remote CI 复验。
- Pairwise：Bounded。
- State Model：Unavailable/Experimental。
- Knowledge Graph：Basic。
- Key Rotation：Planned Metadata Only，没有真实 Apply/Re-encrypt/Verify/Rollback。
- FlowSpec v1/v2：Unsupported Development Format；V5 正式指纹基线仍是 v3。
- External：Windows 用户实机、长时 Standalone/Compact、连续 RC 观察、安全审批、
  人工 Review/签署仍未完成。

## 16. Final Decision

当前实现已通过本地门禁；最终合并候选判定以推送后精确 HEAD 的六个 Required
Workflow 为准。PR 保持 Draft，因此即使 Remote CI 全绿：

```text
RC_READY: NO
GA_READY: NO
```

本文不构成 Merge、Tag、Release 或生产发布授权。
# S47.5 后续复审说明

S47.4 的指定修复和精确 SHA CI 证据有效，但后续代码复审发现 Missing Draft Toggle、固定计划
版本、RunItem Release Evidence 与 Current Contract 回退问题。最终评审判定应继续参考
`s47-5-release-evidence-integrity.md`，不能仅以 S47.4 全绿结论放行。

# S47.7 治理取代与最终校正

本文的“人工 Review/签署”是 S47.4 当时的历史阶段结论，不再是 V5 功能合并条件。
S47.7 要求 Codex 独立完成 Requirement/Correctness/Security/User Flow 四轮审计，并仅在
精确 HEAD Required CI 和分支保护允许时合并。产品内 TestDesign Review/Waiver 仍需授权人工
用户执行。最终证据见 [S47.7 记录](v5-autonomous-functional-acceptance.md)。
