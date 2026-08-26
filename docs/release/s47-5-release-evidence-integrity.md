# FlowTest V5 S47.5 Release Evidence Integrity Closure

状态：候选实现与验证记录（2026-08-27，Asia/Shanghai）

S47.5 只关闭 Change Regression 与 Release Gate 的证据完整性问题，不增加新的
Workflow、Execution、ChangeSet、权限或兼容体系。

## 1. Baseline

- Branch：`codex/v5.0`
- Start SHA：`185bc9f4926543c90a85e3f9678f3933d3f71fa9`
- Migration Head：`20260823_0045`
- Draft PR：[#40](https://github.com/a3384379/FlowTest/pull/40)
- 基线工作区干净，本地、远程和 PR Head 一致；六条 Required Workflow 成功。

## 2. Confirmed Findings

复审指出的三个 P0 和一个同 Run 闭环问题均已确认：关闭 Missing Draft 会跳过语义分析；
Plan Coverage 读取资产 Current 而非固定版本；Release Gate 读取可变 TestPlanItem 而非本次
RunItem；Current OpenAPI Fingerprint 精确失败后仍回退旧 Route；物化资产无法加入同一 Run。

## 3. Missing Draft Toggle

`generate_missing_tests` 只控制是否创建 AIChangeSet 和 TestDesign Draft。以下链路始终执行：

```text
Change → Operation Resolution → Semantic Requirement → Project Coverage
       → Pinned Plan Coverage → Approve/Execute Gate
```

关闭 Draft 时 `change_set_id=null`、`missing_tests=[]`，但语义 Gap、逐项 Waiver 和三个门禁
保持有效。

## 4. Versioned Coverage Fact

`SemanticCoverageFact` 现在同时冻结：

```text
source_asset_type
source_asset_id
source_asset_version
workflow_version
operation identity
oracle set fingerprint
```

Project Coverage 可读取项目全部已发布不可变版本；Current Plan 只选择 TestPlanItem 固定的
资产版本和 Workflow 版本。TestCase 从 `TestCaseVersion.definition` 解析，不读取 Draft。

## 5. Release Evidence Basis

Approve 和 Execute 前使用固定的 `TestPlanItem`。Release Gate 改用本次
`TestPlanRunItem`：

```text
target_snapshot
target_version
workflow_version
status
```

只有 `status=passed` 的 Item 能形成 Release Coverage。Queued、Running、Failed、Cancelled
和 Quarantined 均不计覆盖。执行后新增或删除 TestPlanItem 不会重新解释历史执行证据。
Release Evidence 标记 `semantic_coverage_basis=test_plan_run` 并记录 Run ID。

## 6. Current Contract Binding

OpenAPI Change 带 `current_contract_fingerprint` 时，该指纹是权威身份。精确匹配失败会产生
Unknown/Contract Mismatch Review Blocker，不再回退 Service+Route、Portable Ref 或唯一
Method+Path。人工 Operation Selection 同样强制所选版本 Fingerprint 完全一致。

未分配 Service 的 Contract 保留 Canonical Contract 中的空 Service 参与 Fingerprint，
Operation Identity 仍使用 `service_key=unassigned`，避免同一 OpenAPI 因部署归属占位符产生
伪 Fingerprint 差异。

## 7. Generated Asset Same-Run Closure

物化产生的 Workflow/TestCase 记录在 `selection_summary.generated_assets`，包含 Change Key、
来源 Item 和资产 ID。资产仍是 Draft，系统不会自动发布或执行。人工发布后，若该固定版本
确实覆盖指定 Gap，可通过现有 Add-to-Plan 动作加入同一 Change Regression Run 的当前计划，
随后重新计算 Coverage。加入时写 Audit，并冻结 `target_version/workflow_version`。

## 8. Golden Evidence

- `generate_missing_tests=false`：无 ChangeSet，但 Approve 返回 409。
- Workflow Current=v2、Plan 固定 v1：Plan Scope 仍为 v1。
- TestPlanRun 完成后删除 Plan Item：Release 使用 RunItem 快照，不受删除影响。
- Queued/Quarantined RunItem：不形成 Release Coverage。
- Current OpenAPI F2、本地仅 F1：解析和人工选择均拒绝旧 Contract。
- Generated Workflow：人工发布并显式加入后，同一 Run 可重新计算并批准。

## 9. Local Verification

- Backend：Ruff、Mypy、Import Linter 通过；`571 passed / 3 skipped`，覆盖率 `90.08%`。
- Frontend：`56` 个测试文件、`215` 个测试通过；Statements `86.15%`，生产构建通过。
- Security：Python/PNPM 依赖审计均无已知漏洞。
- PostgreSQL：`0042→0043→0044→0045→0044→0045`、`downgrade base→upgrade head`
  和 `alembic check` 通过。
- Compose：独立 Project、端口和 Volume 中 `scripts/smoke_s47.py` 通过，结束后已执行
  `down --volumes`。

本地结果不替代最终提交精确 SHA 的 GitHub Actions。

## 10. Migration

本轮没有数据库结构变化。Migration Head 保持 `20260823_0045`；版本身份使用现有不可变
WorkflowVersion、TestCaseVersion、TestPlanItem、TestPlanRunItem 与 JSON Evidence 字段。

## 11. Remaining Risks

- Pairwise：Bounded。
- State Model：Unavailable/Experimental。
- Knowledge Graph：Basic。
- Key Rotation：Planned Metadata Only。
- FlowSpec v1/v2：Unsupported Development Format。
- Windows 用户实机、Standalone/Compact 长时观察、连续 RC、安全审批和人工签署仍未完成。

即使 S47.5 代码和精确 SHA CI 全绿，PR 仍保持 Draft：

```text
RC_READY: NO
GA_READY: NO
```
