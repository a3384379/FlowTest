# ADR 0051：基于明确变更证据的受控维护提案

状态：已采纳（S59C）

## 决策

- 新增 `POST /projects/{project_id}/workflows/{workflow_id}/maintenance-proposals`，显式指定 Context
  前后版本、目标草稿 Revision、Patch 类型和完整 Proposed FlowSpec；请求不接受自定义来源或 Provenance。
- 来源为服务端生成的 `maintenance://...` 与版本化 `flowtest-maintenance-provenance-v1`，持久化在
  既有 AIChangeSet source snapshot；可选关联同项目 ImpactRun。不新增数据表或维护生命周期。
- 顺序为 Project Edit → 敏感值及项目约束 → 当前目标草稿 → 当前 Ready Context → 目标影响分析
  → FlowSpec 校验 → Patch 白名单 → Idempotency Claim → 再校验及持久化。锁定目标与 Context，
  幂等事务提交后重新读取权威状态，避免前置校验与实际写入脱节。
- 精确实例或完整 Portable Operation 证据才允许创建；路由、启发式和单独的显式资产选择不能授权。
  目标解析失败、预算耗尽和截断拒绝创建。全局 `CONTEXT_CHANGE_UNMAPPED` 保留为人工复核诊断，
  不否定已确定的单目标匹配，也不声称所有 Context 变化都已覆盖。
- S58 Failure Repair 与 S59C Maintenance 共享纯领域 Patch 白名单校验；前者仍单独执行故障分类和
  Product Defect Guard，后者不伪装成失败修复。Binding/Data/Cleanup/Contract Drift/Oracle 不能越界，
  不能切换 Schema、Operation version strategy 或节点身份；Oracle 调整需要显式弱化确认。
- 复用既有统一 Proposal List、Visual Review、单次 Sandbox Preview 和 Apply Draft。人工接受前不允许
  Preview 或 Apply；Apply 额外复核维护来源 Context 仍为同一当前版本，已有目标指纹检查继续生效。
- 现有审核窗口展示可信来源、Context 前后版本、目标草稿、影响证据和未覆盖项。无自动 Accept、Apply、
  Publish 或 Production Execute。

## 前置债务和兼容

- PR #82 来源按服务端 schema marker 分类；仅伪造 `mcp://`、`repair://` 或 `maintenance://` 的普通
  Import 仍为 import。历史可信 MCP marker 保留；不修改历史记录或依靠客户端 URI 判定来源。
- PR #84 两项 P2 在本阶段修复：显式 `consumes`，以及 500 节点 / 100 身份 / 100,000 比较总预算。
- 新 Visual Proposal 字段可空，历史 Import/MCP/Repair 仍兼容；无 Alembic 变更。
- S59D 将创建入口、Diff、影响流程、维护提案 ID 接入既有 Change Regression 页面和向后兼容 Snapshot v4；
  S59C 不新建第二个 Change Maintenance 页面，也不将提案审批替代 Release Gate。
