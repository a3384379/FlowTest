# ADR 0039：Cleanup / Compensation Runtime

## 状态

契约已接受；S54 实现运行语义。

## 背景

集成测试和 Preview 会创建订单、用户或 Mock 数据。普通 DAG 的 fail-fast/cancel 语义无法保证失败后清理，
也不能区分主流程结果与补偿结果。

## 决策

- Workflow 语义区分 `main` 与 `cleanup` Phase；Cleanup 声明 `run_when`、`cleanup_for`、`best_effort`、
  独立 Timeout 和有限 Retry。
- Scheduler 先执行 Main DAG 并不可变地固定 Main Result，再计算已激活 Cleanup DAG，使用独立且有界的
  Request Budget/Token 执行，最后汇总两个结果。
- Main Failed 永不因 Cleanup 成功变为 Passed。
- Main Passed 且 Required Cleanup Failed 时，整体为 Failed；Main Result 仍单独保留为 Passed。
- Best-effort Cleanup Failed 不改变 Main Result，但必须成为结构化 Warning、Report 和 Audit，不能静默。
- 普通 Cancel 执行适用 Cleanup；Force Cancel 可跳过，但必须显式授权并审计原因。
- Cleanup 不得触发无限 Retry，不得作为普通业务输出依赖；Snapshot 固定其完整语义。
- Cleanup 结果进入 Execution/Preview Evidence，重放必须使用原 Snapshot。

## 结果

运行报告同时暴露 Main 与 Cleanup 状态，现有无 Cleanup Workflow 保持兼容。S54 必须覆盖 Passed/Failed、
Cancel/Force Cancel、并行副作用、顺序、Retry、Resume、Runner Reclaim 和三种 Runtime Profile。

## 否决方案

- 用普通末尾节点模拟 Cleanup。
- Cleanup 成功覆盖 Main Failure。
- Force Cancel 静默跳过 Cleanup 或无限重试补偿。
