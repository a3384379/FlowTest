# FlowTest V6.0 S54 Cleanup / Compensation Runtime

## 1. 阶段状态

S53 实现与 Evidence Closure 已合并且 Main Push Required Gate 成功。S54 从最新 Main
创建独立分支 `codex/v6-s54-cleanup-runtime`；当前实现与本地定向验证已完成，等待
PR 精确 Head Review 与最终一次完整门禁。

## 2. Implemented

- Workflow 契约显式区分 `main` / `cleanup` Phase；Cleanup 声明 `run_when`、
  `cleanup_for`、`best_effort`、独立 Timeout 与有界 Retry。
- Scheduler 先固化 Main Result，再按 Main DAG 逆序执行已激活 Cleanup；Cleanup 使用独立
  Request Budget，不允许无界重试。
- Main Failed 不会被 Cleanup 成功覆盖；Required Cleanup Failed 使整体失败，
  Best-effort Failure 以结构化 Warning 与 Report 保留。
- Graceful Cancel 执行适用 Cleanup；Force Cancel 可按快照策略跳过 Cleanup，但必须提供
  原因并写入审计字段。Runner 轮询可区分两种取消。
- Execution、Node Checkpoint、Runner Ack 与 Durable Checkpoint 持久化 Phase、Main/Cleanup
  Status、Cleanup Report 和 Force-cancel 审计信息。Runner Reclaim 在 Main 终态检查点
  完整时不重放主流程，只恢复必要的 Cleanup。
- FlowSpec v2 原生表达 Cleanup 和 Run Policy，v1 指纹与无 Cleanup Workflow 保持兼容。
  S50 Integration Plan 的 Cleanup Requirement 现在可编译、审核、应用和再导出。
- Web 执行列表独立展示 Main/Cleanup 状态，节点列表展示 Phase；API 保持旧请求
  字段兼容。

## 3. 数据库与兼容性

- Migration `20260830_0048` 增加 Execution、Node Execution 和 Durable Checkpoint 的 Cleanup
  字段、约束与索引，并为历史终态执行回填 Main Status。
- 隔离 PostgreSQL 17.6 已完成从空库升级到 Head、回滚 0048、再升级与
  `alembic check`；临时容器已自动清理，未修改现有恢复栈。

## 4. 已完成的定向验证

- Scheduler、Runner Fabric、Plan Codec、Workflow API、V6 Golden、S50 与 S51 聚焦回归：
  `85 passed`。
- MCP/Workflow/S50/Golden 兼容回归：`47 passed`。
- 首次复审提出的 Force Cancel Policy、Reclaim Budget 与 Best-effort Fail-fast 三个
  P1 已增加回归并修复；修复后 S54/MCP 合并定向集 `95 passed`。
- Frontend FlowSpec Service、Review Dialog 与 Workflow Page：`6 passed`。
- Ruff Format、Ruff Check、`mypy app` 与 Frontend TypeScript 检查通过。

## 5. S54 Exit Criteria

| 条件                                          | 当前状态 | 证据                           |
| --------------------------------------------- | -------- | ------------------------------ |
| Passed/Failed 与 Required/Best-effort Cleanup | Pass     | Scheduler 状态机回归           |
| Graceful/Force Cancel 语义分离                | Pass     | Scheduler、API 与 Runner 回归  |
| Cleanup Budget/Timeout/Retry 全部有界         | Pass     | Contract 校验与 Scheduler 回归 |
| Snapshot/Report/Checkpoint 可持久化           | Pass     | API、Codec 与 Migration 回归   |
| Resume/Reclaim 不重放已完成 Main              | Pass     | Runner Reclaim 回归            |
| FlowSpec v2 与 S50 Cleanup Requirement 闭环   | Pass     | Golden 与 S50 兼容回归         |
| 精确 Head Review P0/P1 为 0                   | Pending  | 首轮 3 个 P1 已修复，待复审    |
| 最终一次完整门禁                              | Pending  | P0/P1 清零后执行               |

## 6. 范围边界

- S54 不自动 Publish、不自动执行生产环境，也不把 Cleanup 当作无限重试的事务补偿。
- S55 Sandbox Preview 与 S56 RC 不在本阶段提前实现。
