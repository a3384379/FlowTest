# ADR 0036：复用 AIChangeSet 与 FlowSpec Proposal 生命周期

## 状态

已接受，S49/S51 实现。

## 背景

现有 AIChangeSet 已具备 Draft、逐项 Review、Stale 保护、Materialize 与审计能力，FlowSpec 已具备
Normalize、Validate、Fingerprint、Diff 和导入链路。另建 FlowProposal/Review 表会复制状态机与授权逻辑。

## 决策

- 集成流程提案继续使用 `AIChangeSet`/`AIChangeItem`；Workflow Item 的 proposed content 保存严格的
  FlowSpec Proposal，而不是新建 Proposal 表。
- ChangeSet `source_snapshot` 固定 Context Revision/Fingerprint、Integration Plan/Fingerprint、Compiler
  Version、FlowSpec Schema/Fingerprint 与 Diagnostics 引用。
- MCP `propose_flow_draft` 只创建 Draft，要求 `mcp:flow:propose`、Idempotency Key 和适用时的
  Expected Revision；不得 Publish 或执行。
- Visual Proposal Mode 读取同一 ChangeSet，展示 Diff/Overlay，并复用 Accept/Reject/Review Note。
- Apply 时再次验证 Tenant、Target Revision、Context 未过期和 Fingerprint；Stale 时阻断，不自动覆盖。
- Materialize 复用现有 FlowSpec 导入和 Workflow Draft 路径；历史 ChangeSet 内容保持不可变。

## 结果

API、MCP 与 UI 共享一个审核事实源，避免重复授权和状态转换。S49 不新增 `flow_proposals`、
`flow_proposal_reviews` 或第二套 Workflow 草稿表。

## 否决方案

- LLM 直接写 Workflow Draft 或 Published Version。
- 为 MCP 与 Web 各自维护 Proposal 状态机。
- 审核后静默用最新 Context 重新编译并替换内容。
