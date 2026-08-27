# ADR 0040：Sandbox Preview 安全边界

## 状态

契约已接受；S55 实现。

## 背景

Preview 需要验证提案能否执行，但它仍会产生真实出站请求和业务副作用。另建预览引擎会与现有 Snapshot、
Scheduler、Runner、Event 和 Report 发生行为漂移。

## 决策

- Preview 是现有 `WorkflowExecution` 的 `run_purpose=preview`，不建立第二套执行引擎。
- 只允许 Test/Sandbox Environment；Production 硬拒绝，不能用普通管理员开关绕过。
- 执行前必须满足：Proposal 已 Accept、Context 未过期、Target Revision 未 Stale、Secret 已配置、Cleanup
  可执行、出站策略允许、`mcp:preview:execute` Scope 与一次性 Approval 有效。
- 默认上限冻结为 100 Nodes、50 Requests、20 Dataset Rows、5 Parallelism、600 Seconds；实现可在不扩大
  权限的前提下按部署策略收紧。
- Approval 绑定 Actor、Tenant、Proposal/Context Fingerprint、Environment、Budget 和过期时间；消费后不可重放。
- Missing Cleanup、Unresolved Blocker、Secret Literal、Cross-Tenant、Unsupported Node、Arbitrary Script 和
  超预算均硬拒绝。
- Preview Evidence 必须包含 Proposal/Context Fingerprint、Execution Snapshot、Binding Trace、Assert/Cleanup
  Result、Budget Usage、Redactions、Trace ID 与 Approval ID。

## 结果

Preview 复用生产级执行证据但不获得生产执行权。任何 Preview 失败或拒绝都使用标准错误信封和 Trace ID，
且不得记录 Secret、Token、Cookie 或未脱敏正文。

## 否决方案

- 通过“dry-run”标签允许向 Production 发真实请求。
- 可重放 Approval 或无 Budget 的 Preview。
- 执行任意脚本、数据库写 SQL 或缺少 Cleanup 的副作用流程。
