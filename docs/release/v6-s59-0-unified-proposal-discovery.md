# S59.0 Unified Proposal Discovery

## 目标

S59 Maintenance Proposal 继续复用现有 FlowSpec `AIChangeSet`、Review、Apply 与 Sandbox Preview
生命周期，但 Proposal Review 不再只发现 `mcp://` 来源。统一查询覆盖 MCP、Failure Repair、Maintenance
和手工/Portable Import，避免为每种来源建立独立列表或状态机。

## 实现

- 新增 `GET /projects/{project_id}/flow-specs/change-sets/proposals`，沿用稳定的
  `(created_at, id)` 游标和项目 Read 授权。
- 返回结构化 `proposal_origin`：`mcp`、`repair`、`maintenance`、`import`。
- `flow-spec://`、`import://`、`ui://`、空来源及未来未知来源保守归入 `import`，不依赖前端解析字符串。
- 原 `/change-sets/mcp-proposals` 保留并继续只返回 `mcp://`，现有客户端无需同步升级。
- Flow Proposal Review Dialog 改用统一列表；Repair Proposal 关闭后可从同一入口重新发现，未来
  `maintenance://` Proposal 也直接进入同一人工审核与 Preview 路径。

## 安全与兼容边界

- 不新增表、状态机、Apply 路径或自动执行能力。
- 不改变 AIChangeSet 的项目隔离、人工 Review、草稿 Revision Stale Check 和一次性 Sandbox Approval。
- 统一列表仅扩大已授权项目内的 Proposal 可见来源，不扩大 Project Scope 或编辑权限。
- MCP 兼容接口、响应结构和过滤语义保持不变。

## 验收

- 后端覆盖统一来源分类、分页中途插入不丢失既有项、旧 MCP 过滤兼容。
- 前端覆盖统一游标加载，以及无 Repair 深链参数时从列表重新发现并打开 Repair Proposal。
- 后端 Ruff Format、Ruff Check 与 Mypy 全绿；Pytest `1019 passed, 4 skipped`，Coverage `90.94%`。
- 前端 Format、ESLint 与生产构建全绿；Vitest `230 passed`，Branch Coverage `80.01%`。
- 最终门禁、复审与合并证据在 PR 终态后补录；本地结果不替代精确 Head 的远程 Required Gate。
