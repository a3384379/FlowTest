# ADR 0042：V6 MCP 最小权限 Scope

## 状态

已接受，新增 Tool 上线前强制执行。

## 背景

现有 MCP Scope 为 `mcp:read` 与受控的 `mcp:write`。V6 增加 Evidence 写入、Flow Proposal 和 Preview；
若让旧 `mcp:write` 自动继承，会在没有管理员重新授权的情况下扩大现有 Service Account 权限。

## 决策

- V6.0 首批只新增 `mcp:evidence:write`、`mcp:flow:propose`、`mcp:preview:execute`。
- 现有 `mcp:write` 不包含、暗示或自动迁移为任何新 Scope；Service Account 必须由授权管理员显式授予。
- Context Evidence 写入要求 Evidence Scope；Plan/Compile 可读操作仍受 Tenant `mcp:read` 和对象权限约束；
  Draft Proposal 要求 Flow Scope；Preview 同时要求 Preview Scope 与一次性 Approval。
- Scope 检查在统一依赖/服务边界执行，Repository 与 Domain 不复制授权逻辑。
- 每个写 Tool 必须校验 Tenant、Idempotency Key、Expected Revision（适用时）、Schema Version、Budget 和 Audit。
- V6 MCP 永不提供 `publish_flow`、`execute_production_flow`、`delete_workflow`、`read_secret`、任意脚本、数据库
  写 SQL、权限修改或自动 Repair。
- Scope 拒绝使用标准错误信封与 Trace ID；日志只记录 Account/Scope/Object ID，不记录 Token 或请求敏感值。

## 结果

升级不会扩大已有 Service Account 权限。V6.1 的 Repair/Test Plan Proposal Scope 必须另立决策，不预建空
Scope 或 Feature Flag。

## 否决方案

- 让 `mcp:write` 成为全能写权限。
- 依靠 Tool 名称或前端隐藏代替服务端授权。
- 将 Preview Approval 当作可复用 Credential。
