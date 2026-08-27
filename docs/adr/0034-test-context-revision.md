# ADR 0034：不可变 TestContext Revision

## 状态

已接受，S49 实现。

## 背景

集成测试方案由仓库提交、接口契约、数据 Profile 与现有测试等多源证据共同决定。若证据在同一 Context
中原地更新，Proposal 无法证明自己基于哪一组事实，Stale 判断、审计和重放也不可靠。

## 决策

- `TestContext` 保存身份、目标、当前 Revision 指针、生命周期与 Tenant 归属。
- `TestContextRevision` 一经创建不可修改；证据变化创建递增 Revision，并重新计算 Fingerprint。
- Revision 至少固定 repository、contract、data profile、existing test 的 Revision，以及有界的 Typed
  knowledge/conflict/completeness Snapshot。
- `ContextEvidenceItem` 归属于确定的 Revision；`source_ref + source_revision + subject_ref + fingerprint`
  构成可追踪来源。
- Proposal、Plan、Compiler Diagnostics 与 Preview 必须引用 Context Revision 和 Fingerprint；不匹配即 Stale。
- S49 只新增 `test_contexts`、`test_context_revisions`、`context_evidence_items`。Graph、Plan 和 Conflict
  先保存为严格版本化 JSON Snapshot，不增加独立表。
- Context 受 TTL、Retention、Tenant 权限、审计和关闭状态控制；关闭或过期后不得接收新 Proposal。

## 结果

同一输入 Revision 可重放并产生稳定的 Plan/FlowSpec；新证据不会静默改变已审核草稿。后续若把 Snapshot
正规化为表，必须以 Revision Fingerprint 保持语义兼容。

## 否决方案

- 原地修改 Evidence 或 Context Snapshot。
- 用“最新仓库/最新契约”隐式解释历史 Proposal。
- S49 预建完整 Knowledge Graph、Provider Run 或 Flow Proposal 表族。
