# ADR 0043：Integration Plan v2 Data Recipe 与跨系统 Oracle

## 状态

已接受，S53 起执行。

## 背景

S50 的 `flowtest-integration-plan-v1` 可表达 Operation、Binding、单 Operation Oracle 与 Dataset，但不能
无损表达以下必要语义：

- 运行时 Synthetic、Previous-step、Environment、Secret Reference 与 Setup API 的强类型来源；
- 期望值来自另一个已执行 Node 的 Cross-API Assert；
- 使用现有受限 Credential 的结构化只读 DB Read 及其 Assert；
- `deterministic`、`requires_review`、`source_ref`、`confidence` 与 `applies_to` 组成的
  Data/Oracle Strength。

如果把这些语义塞入 v1 的字面值或任意字典，v1 Fingerprint 将无法准确代表运行意图，
也会绕过现有 SQL、Secret 和 Review 边界。

## 决策

- 新增 `flowtest-integration-plan-v2` 与 `flowtest-integration-plan-fingerprint-v2`；v1 保持可读、可校验、
  可编译，其已有 Fingerprint 输入不改变。
- v2 只扩展既有 Integration Plan 领域合同，不新建 Plan 表、Proposal 表、Review 状态机或
  第二套 DSL。Proposal 仍使用 `AIChangeSet` / `AIChangeItem` 和现有 FlowSpec Review / Apply。
- v2 Compiler 仍输出当前 Portable FlowSpec：Synthetic 由 Start Node 有界生成，Cross-API 由现有
  Assert Node 从两个上游 Node 取值，DB Read 由现有 SQL Node 加 Assert Node 执行。
- DB Read 只接受 Table、Column、Predicate、Variable 与 Credential ID 的封闭字段；Compiler 生成
  单条参数化 `SELECT ... LIMIT 2`，Contract 不提供任意 SQL 文本入口。
- Database Observation 只是设计期 Evidence；尝试把它降级为运行数据时返回 Design-only
  Blocker。Secret 始终只保存引用，不读取、不编译为字面量。
- 低置信度、非确定性或冲突 Oracle 不得编译，必须保留显式 Review 诊断。数据源、
  Oracle 期望源和 DB 参数源必须存在且满足执行顺序。
- 无新数据库表或 Migration。回滚 S53 代码后，v1 Plan 继续工作；已保存的 v2 Snapshot 保留为不可变
  Evidence，旧 Compiler 不会把它误当作 v1 执行。

## 结果

S53 获得可追溯、可审核的可执行 Data/Oracle 链，同时复用现有 Scheduler、SQL Read、
Assert、FlowSpec 和 Proposal 主路径。v1 兼容性与历史 Fingerprint 不被重写。

## 否决方案

- 在 v1 的 `expected` 或 `config` 中嵌入任意字典。
- 新建一套 Data/Oracle 执行引擎或 Preview 调度器。
- 接受用户原始 SQL，或使用写 SQL 生成 Setup Data。
- 把低置信度、冲突或设计期 Evidence 自动升格为 Release Gate。
