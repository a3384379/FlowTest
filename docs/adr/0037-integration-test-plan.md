# ADR 0037：版本化 Integration Test Plan

## 状态

已接受，S50 实现。

## 背景

Typed Evidence 不能直接变成 Workflow。需要一个可审核、可解释的中间层表达 Operation 顺序、绑定候选、
数据准备、Oracle、Cleanup 与风险，再由纯编译器生成 FlowSpec。

## 决策

- 首版契约为 `flowtest-integration-plan-v1`，使用严格 Pydantic 模型和 `extra=forbid`。
- Plan 固定 Context Revision/Fingerprint、Objective、Target Environment、Operation Identity、Steps、Bindings、
  Data Recipes、Oracles、Cleanup Intent、Review Requirements、Diagnostics 与 Plan Fingerprint。
- Binding 来源只允许 previous response、runtime/environment variable、dataset、secret reference、setup API
  和 external evidence candidate；目标只允许 path/query/header/cookie/body/workflow variable。
- 完全同型可自动绑定；安全模板转换可自动编译；多候选、String/Number 转换需 Review；Object/Scalar 冲突
  阻断；Secret 只保存引用。
- Plan Normalize/Fingerprint/Validate/Compile 都是纯领域逻辑，不持久化、不访问网络、不读取 Secret、
  不创建 Workflow。
- V6.0 不建 `integration_test_plans` 表；Plan 作为 AIChangeSet Source Snapshot 中的版本化内容保存。

## 结果

规划判断与可执行编译分离，Compiler 可基于同一 Plan 确定性重放。若未来正规化持久化，Plan Schema 与
Fingerprint 必须继续兼容，不能改变现有 ChangeSet 证据。

## 否决方案

- 让 LLM 直接输出现有 WorkflowDefinition。
- 把不确定 Binding 当作运行时猜测。
- 在 S50 为 Plan 预建独立数据库生命周期。
