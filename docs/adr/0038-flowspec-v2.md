# ADR 0038：FlowSpec v2 与 v1 兼容边界

## 状态

已接受，S48 起冻结。

## 背景

现有 `flowtest-flow-spec-v1` 的模型和外部消费者使用 `extra=forbid`。它只有扁平 Cleanup 引用，不能无损
表达 Cleanup Phase、Run When、目标节点、独立 Timeout/Retry/Budget、Force Cancel 和 Run Policy。
直接给 v1 增加字段会使旧消费者拒绝，也会在旧 Fingerprint 中遗漏新的可执行语义。

## 决策

- 新可执行契约使用 `flowtest-flow-spec-v2`；Fingerprint 使用
  `flowtest-flow-spec-v2-fingerprint-v1`。
- v2 复用 v1 的 Service、Operation、Node、Edge、Binding、Parameter、Assertion、Security 与 Confidence
  类型，只新增严格的 `cleanup`、`run_policy` 和 `plan_metadata`。
- Cleanup 和 Run Policy 进入 v2 语义 Fingerprint；`project_id`、Evidence、Confidence、Fingerprint Version
  与仅用于追踪的 Plan Metadata 不进入。
- v1 导入、导出、Fingerprint v1/v2/v3 和现有 Workflow 转换保持原样；不重解释或改写历史 v1 文档。
- 提供纯函数确定性 v1→v2 转换。v1 Cleanup 转为 `run_when=always`、30 秒、0 Retry、无目标列表；空
  Run Policy 和 Plan Metadata 使用固定默认值。
- 只有 v2 未使用任何 v2-only 运行语义时才允许 v2→v1；否则显式阻断，不做有损降级。
- v2 Validation 必须包含 v1 图/引用规则，并校验 Cleanup Operation/Target 与 Security Request Budget。
- Existing Execution Snapshot 的 `schema_version=1.0` 和 WorkflowDefinition 不变；S48 不迁移数据库或历史行。

## 兼容矩阵

| 路径 | 结果 |
| --- | --- |
| v1 Import | 支持，行为不变 |
| v1 Export / Fingerprint v1、v2、v3 | 支持，Golden 固定 |
| v1 → v2 | 支持，确定性、无损保留 v1 语义 |
| v2 Import | 契约已冻结；运行接入按后续迭代 Feature Flag 开放 |
| v2 → v1（仅 v1 语义） | 支持，受守卫保护 |
| v2 → v1（含 Cleanup/Run Policy） | 阻断，返回明确兼容错误 |
| 历史 Execution Snapshot | 不修改、不迁移 |
| 未知字段 | v1/v2 均拒绝 |

## Migration 与 Rollback

S48 只增加领域契约、Golden Fixture 和转换函数，没有 Alembic Migration。后续持久化若保存 v2，必须显式
记录 Schema/Fingerprint Version。回滚代码时，v1 资产继续可用；含 v2-only 语义的资产必须保持只读或
先人工移除语义后受控降级，禁止自动丢字段。

## 否决方案

- 在 v1 顶层追加可执行字段并继续使用旧 Fingerprint。
- 创建独立于 FlowSpec 的第二套 DSL。
- 修改历史 Snapshot 或批量把 v1 行改写为 v2。
