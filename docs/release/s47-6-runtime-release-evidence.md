# FlowTest V5 S47.6 Runtime Release Evidence Closure

状态：候选实现与验证记录（2026-08-27，Asia/Shanghai）

S47.6 只关闭 Change Regression 发布证据的时序、节点粒度和人工版本闭环，不新增
Workflow Engine、Execution Engine、ChangeSet、权限、资产模型或 FlowSpec 兼容层。

## 1. Baseline

- Branch：`codex/v5.0`
- Start SHA：`7814bae072657c9538ce01d255d41d2f70b76d45`
- Migration Head：`20260823_0045`
- Draft PR：[#40](https://github.com/a3384379/FlowTest/pull/40)
- 开始时本地、远程与 PR Head 一致，工作区干净，S47.5 六条精确 SHA Workflow 成功。

## 2. Confirmed Findings

1. `evaluate_release()` 在检查 TestPlanRun 终态之前计算 Passed Item Scope，提前调用会把
   运行永久写成 `blocked`。
2. S47.5 Release Coverage 只将 Passed RunItem 对应到静态资产 Fact，未证明具体 API/
   Assert Node 实际执行，也未比较最终请求值。
3. Failed/Cancelled 执行在宽松 Release Policy 下存在隐式放行风险。
4. Suite 计划项未展开预执行覆盖；版本/Contract Mismatch 有推荐但无可用的替换动作。

## 3. Early Release State Safety

Release Gate 的固定顺序为：

```text
Lock ChangeRegressionRun
→ Lock and validate TestPlanRun
→ queued/running: 409 without persistence
→ terminal: project runtime evidence
→ semantic gate
→ release decision or explicit blocker
```

`CHANGE_REGRESSION_EXECUTION_PENDING` 不写入 Selection Summary、Evidence、Stage、Decision 或最终
Status。TestPlan 完成后重试会从完整证据正常评估。

## 4. Runtime Semantic Coverage

发布覆盖的真实证据链为：

```text
TestPlanRunItem (passed, immutable target/version snapshot)
→ WorkflowExecution (root and actually created dataset children)
→ WorkflowNodeExecution (API passed, Assert passed)
→ NodeResult
→ HTTP Observation (final request/response)
```

一个 Semantic Coverage Fact 只在以下条件全部成立时进入 Release Coverage：

- RunItem 的 Asset Version 和 Workflow Version 与 Fact 一致；
- WorkflowExecution 实际使用该 Workflow/Version；
- Fact 绑定的 API Node 实际执行且 `passed`；
- 最后成功 Observation 的 Method、Path 和已分配 Service 与 Operation 一致；
- 最终 Path/Query/Header/Cookie/Body 值与 Requirement 语义值一致；
- Response Status 与 Status/Status Set Oracle 一致；
- 构成 Oracle Set 的关联 Assert Node 实际执行且输出 `passed=true`。

Skipped/Failed/Cancelled Node、未进入的条件分支、Skipped Assert、未执行 Dataset Row、缺少成功
Observation 或运行时值不一致均不计覆盖。无法从脱敏 Observation 证明值相等时安全失败。
Path 参数提取使用 Fact 中冻结的原始 Contract Path Template；Operation Identity 仍使用去实例化的
Normalized Path，避免因为 `{}` 标准化丢失参数名而把真实 Path Evidence 误判为不可验证。

Release Evidence 记录 `semantic_coverage_basis=runtime_node_evidence`、TestPlanRun ID 以及
Passed RunItem、Selected RunItem、WorkflowExecution、Passed API Node 和匹配 Fact 数量，不写入敏感值。

## 5. Failed and Cancelled Policy

Change Regression 的 Failed 或 Cancelled TestPlanRun 始终阻断发布，不受
`require_quality_gate=false` 影响：

```text
failed    → CHANGE_REGRESSION_EXECUTION_FAILED
cancelled → CHANGE_REGRESSION_EXECUTION_CANCELLED
```

两者都保存不含敏感值的 Execution Outcome 证据并阻止 Release Decision Pass。Failed Run 仍产生
Failure Triage。S47.6 不新增“豁免整个失败执行”能力。

## 6. Suite and Version Closure

Current Plan 中的 Suite 使用固定 TestSuiteVersion 和其 TestSuiteVersionItem，展开到固定
TestCaseVersion 再解析 Workflow Version。Suite/TestCase/Workflow Draft 后续修改不改变已计划覆盖。

Add-to-Plan 动作统一接受 `MISSING`、`PARTIAL`、`VERSION_MISMATCH` 和
`CONTRACT_MISMATCH`。对后两者执行显式 Replace Plan Item Version：验证推荐资产和固定
版本，保留原 Position，写入旧/新版本 Audit，重算 Gap，不自动执行。

## 7. Golden Tests

- Running 期间调用 Release Gate：409，Run 保持 Running，Evidence/Stage/Decision 不变；
- 执行完成后重试：正常产生 Release Decision；
- 最终 Body 值与 Requirement 一致且 Status 匹配：Covered；
- Runtime Body 值不一致、API Skipped、Assert Skipped：Not Covered；
- Path/Query/Header/Cookie 从最终 HTTP Request Snapshot 取值；
- Failed/Cancelled Run 在宽松 Policy 下仍 Blocked，不创建 Release Decision；
- Suite v1 固定展开；当前资产升级不改写 Suite Scope；
- Replace Version 保留已队列 RunItem 的旧版快照。

## 8. Migration

本轮无数据库结构变化。Runtime NodeResult/Observation、WorkflowExecution 树、Suite Version 和 Audit
均复用现有持久化结构；Migration Head 保持 `20260823_0045`。

## 9. Verification and Decision

本地验证结果：

- Ruff Format / Ruff Check：通过；
- Mypy：324 个源文件通过；
- Import Linter：通过；
- Pytest：579 passed、3 skipped，Coverage 90.09%；
- Pip Audit：未发现已知漏洞；
- Frontend Format / Lint / TypeScript：通过；
- Frontend Test：56 个文件、215 个测试通过；
- Frontend Coverage：Statements 86.15%、Branches 80.11%、Functions 85.27%、Lines 88.37%；
- Frontend Build / Audit：通过；
- PostgreSQL：空库升级到 0045、0045→0044→0045、Current、Alembic Check 均通过；
- 隔离 Compose：当前代码镜像构建、健康检查、S47 Smoke 通过；
- 目标 Playwright：S14 管理工作台在 S47 Smoke 后通过；
- 本地非 CI 等价全量 Playwright 尝试：16/20；其余 4 项因未执行 S11/S19 前置数据、
  S24 使用默认 Registry 端口及 S29 未启用专用 Runner Fabric 而失败，不作为通过声明；
- Remote CI：提交后按精确 End SHA 回填。

本地结果不替代精确 HEAD 的 GitHub Actions。PR #40 继续保持 Draft，不自动 Merge、Tag 或 Release。

Pairwise 仍为 Bounded，State Model 仍为 Unavailable/Experimental，Knowledge Graph 仍为
Basic，Key Rotation 仍为 Planned Metadata Only。Windows 用户实机、Standalone/Compact 长时观察、
RC 连续观察、安全审批和人工签署未完成：

```text
RC_READY: NO
GA_READY: NO
```
