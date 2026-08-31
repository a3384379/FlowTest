# FlowTest V6.1 S58 Failure Diagnosis 与 Repair Proposal

## 1. 阶段状态

S58 实现 PR [#78](https://github.com/a3384379/FlowTest/pull/78) 已于
2026-08-31 23:58:56（Asia/Shanghai）普通 Squash Merge。实现 PR 精确 Head 与 Merge 后 Main Push
的 Backend、Frontend、Security、Compose、Standalone Windows、V2→V3 Upgrade 和 Required Gate
Controller 七项工作流均为 Success；最终复审 P0=`0`、P1=`0`。

S58 的实现、复审、PR 候选门禁、普通合并和 Main Acceptance 已闭环。当前保留 3 项不阻断 S58
合并、但必须在 S59 自动 Patch 前关闭的 P2；另有 1 项 `version_strategy` 锁定作为 S59.0 Hardening。

## 2. 已交付能力

- `flowtest-failure-diagnosis-v1` 从终态执行和脱敏节点证据生成确定性分类；每个原始 Signal 单独执行
  Product Defect Guard，任一 Product Defect 都会禁止创建测试 Repair。
- Binding、Data、Cleanup、Contract Drift 与 Oracle 使用不同 FlowSpec 字段白名单；Schema 切换、
  空 Patch、跨类型修改和未确认的 Oracle 变化均 Fail Closed。
- Oracle Repair 只复制既有 Assert Node 的 `config`，保留 Node ID、Kind、Name、Position、Target、
  Operation Identity、Dependency 与 Binding，不能借相同 ID 改变节点类型或引入新出站行为。
- Repair Proposal 复用既有 FlowSpec `AIChangeSet`、Review、Accept、Apply 与一次性 Sandbox Preview；
  `repair://` 只作为 Provenance，不建立第二套 Proposal 表、审批状态机或执行通道。
- Project Edit、执行/工作流/草稿 Revision、Ready Context、敏感值、FlowSpec 和 Patch Scope 校验均在
  Idempotency Claim 前完成。
- 共享 FlowSpec 安全扫描覆盖参数、嵌套字段和 `expected_expression` JMESPath Literal；允许动态表达式
  与 `secret://` 引用，禁止明文 Secret、Credential 与 PII 进入 Proposal。
- Pinned Operation 使用 `source_version` 解析对应契约版本并校验 Fingerprint，不再由旧 Fingerprint
  反向选择错误版本。

## 3. 已完成验证

- 后端 Format、Ruff、Mypy 全绿；Pytest `1008 passed, 4 skipped`，Coverage `90.94%`。
- 前端 Format、ESLint、TypeScript 与 Build 全绿；Vitest `230 passed`，Branch Coverage `80.04%`。
- Compose Playwright “失败诊断 → 受限 Repair Proposal → 人工接受 → Fresh One-time Approval →
  Sandbox Re-preview” `2 passed`。
- 最终安全聚焦回归覆盖 MCP Proposal、Failure Repair Domain 与 S58 API，共 `21 passed`。
- PR 精确 Head 与 Merge 后 Main Push 的七项远程门禁全部成功；普通 PR 的 Compact/容量重门禁按
  路径策略跳过，不影响 Required Gate 结论。

## 4. Exit Criteria

| 条件                                       | 状态 | 证据                        |
| ------------------------------------------ | ---- | --------------------------- |
| Product Defect 不修改测试                  | Pass | Signal 级 Guard 与 API 回归 |
| 五类 Repair 具有严格 Patch 白名单          | Pass | Domain Scope Validation     |
| Oracle Node 身份不可替换                   | Pass | Assert Node 身份回归        |
| 授权、Context、敏感值与 Scope 早于幂等写入 | Pass | Service/API 回归            |
| Repair 复用 AIChangeSet 与 Sandbox Preview | Pass | API + Compose Playwright    |
| 精确 Head Review P0/P1 为 0                | Pass | PR #78 最终复审             |
| 实现 PR 七项 Required Checks               | Pass | 第 6 节 Remote Evidence     |
| Merge 后 Main 七项 Required Checks         | Pass | 第 6 节 Remote Evidence     |

## 5. 已接受 P2 与 S59.0 前置收口

### S58 已知 P2（3）

1. **统一 Proposal Discovery**：Review Dialog 当前调用 MCP Proposal Page 并过滤 `mcp://`；关闭
   Repair 深链后，用户无法从普通列表重新发现 `repair://` Proposal。S59.0 必须建立复用同一
   AIChangeSet 生命周期的统一查询，并返回结构化 `proposal_origin`。
2. **Capability Binding Repair**：Binding Repair 当前只允许顶层 `edges` / `bindings`，不能修改
   `nodes[].bindings`。S59.0 必须纳入严格白名单，或在诊断阶段返回明确的 Unsupported Reason，
   不能先宣称可修复再在提交阶段拒绝。
3. **Cleanup 独立诊断**：Cleanup Repair 当前由整体 Primary Classification 加 Cleanup Node Failed
   推导。S59.0 必须分别计算 Main/Cleanup/Aggregate Diagnosis，仅对 Cleanup 的 BAD_TEST、
   BAD_TEST_DATA 或 CONTRACT_DRIFT 开放 Cleanup Repair。

### S59.0 Hardening（不计入上述 3 项）

- Contract Drift 默认锁定 `version_strategy`；策略迁移若未来需要支持，必须使用独立显式操作和更高等级
  审核，不能夹带在普通 Contract Drift Repair 中。

S59.0 同时收口此前已登记且会影响自动 Flow Patch/Affected Flow 精度的 `previous_step` 跨来源变量冲突、
Body Mapping 完整嵌套路径预检和 Java 全限定引用 Token 解析。

## 6. Remote Evidence

### PR #78 精确 Head

- Final Head：`73f5761ec7bc6ba775289e9e530bedbcb047dd20`
- Merge Commit：`c82f13a528e2bac9cff746951fd9afb766cd95c2`

| 门禁               | Run ID      | 结果    |
| ------------------ | ----------- | ------- |
| Backend CI         | 33409366915 | Success |
| Frontend CI        | 33409367146 | Success |
| Security CI        | 33409366856 | Success |
| Compose Smoke Test | 33409367182 | Success |
| Standalone Windows | 33409366988 | Success |
| V2 to V3 Upgrade   | 33409366942 | Success |
| Required Gate      | 33409361110 | Success |

### Merge 后 Main Push

| 门禁               | Run ID      | 结果    |
| ------------------ | ----------- | ------- |
| Backend CI         | 33411520891 | Success |
| Frontend CI        | 33411520836 | Success |
| Security CI        | 33411520929 | Success |
| Compose Smoke Test | 33411520917 | Success |
| Standalone Windows | 33411520926 | Success |
| V2 to V3 Upgrade   | 33411520834 | Success |
| Required Gate      | 33411520898 | Success |

未使用 Admin Merge、Ruleset Bypass、Force Push 或直接推送 Main。S59 正式功能分支只能从本
Evidence Closure PR 普通合并且其 Main Push Required Gate 成功后的最新 Main 创建。

## 7. 最终判定

```text
S58_IMPLEMENTATION_COMPLETE = YES
S58_PR_MERGED = YES
S58_KNOWN_P0 = 0
S58_KNOWN_P1 = 0
S58_REMAINING_P2 = 3
S58_PR_HEAD_GATE = PASS
S58_POST_MERGE_MAIN_GATE = PASS
S58_SECURITY_BOUNDARY = ACCEPTABLE
S59_DESIGN_AND_FIXTURES = GO
S59_FULL_AUTOMATIC_PATCHING_BEFORE_S59_0 = NO-GO
```
