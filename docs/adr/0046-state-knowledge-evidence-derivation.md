# ADR 0046：State Knowledge 的证据派生与保守关联

## 状态

已接受，V6.1 S57 起执行。

## 背景

S57 内置 Java/Spring Provider 已能产生 Spring MVC、DTO、Service/Feign、Mapper/JPA、Enum、Exception 与
Kafka 的强类型 Evidence，但 Context Revision 的 `knowledge_snapshot` 仍只保存创建 Context 时由调用方提交的
初始图。用户无法从新 Revision 直接看到 Route、DTO、Service、Repository、Entity 与 Table 之间的结构关系，
RuoYi Golden 的完整证据链也没有进入稳定 Context Fingerprint。

直接把静态命名相似度当成确定事实会放大误判；保存原始源码或运行目标代码来补足调用图又违反 ADR 0045 的安全
边界。因此 State Knowledge 必须只消费已经通过 Evidence Envelope 校验和持久化的结构 Claim，并区分显式关系
与保守关联。

## 决策

- 每次 Evidence Ingest 都使用当前 Revision 的持久化结构 Evidence 重新派生 FlowTest 生成的图；调用方提交的
  初始 Knowledge Node/Edge 原样保留，不建立第二套状态表或可变缓存。
- 生成节点使用基于 `kind + stable identity` 的确定性有界 ID，并带 `origin`、规范化 `reference` 和至少一个
  `evidence_ref`。源码正文、Credential、样本值和未经脱敏的 Finding Statement 不进入 Knowledge。
- 显式 Claim 生成 `accepts`、`returns`、`calls`、`uses_repository`、`maps_entity`、`maps_to`、
  `has_column`、`constrained_by`、`allows_state`、`may_raise`、`produces` 与 `consumes` 关系。
- 缺少直接调用 Claim 时，只在 Java 类型名去除 `I` 前缀以及 `Service/Mapper/Repository/Dao` 后缀后唯一同名
  的情况下生成 `may_use_repository` 或 `may_map_entity`。关系名称明确表示需要复核，不提升 Evidence 的
  deterministic/confidence。
- Request DTO 通过 `handled_by` 连接入口 Service；Response DTO 由 Service 通过 `produces` 连接，避免把响应
  模型错误解释为服务输入。
- Java Enum 与数据库声明/观测枚举生成 `state_candidate`。图只保存去重数量和有界 Sample；完整候选仍以
  Evidence/Entity Mapping 为准。
- 图继续遵守 500 Node、1000 Edge、每 Node 50 Fact 的 Context 契约。派生结果无法完整放入预算时，Evidence
  Ingest 返回现有 `TEST_CONTEXT_CAPACITY_EXCEEDED` 并回滚，不静默截断。
- 相同 Evidence 重建结果必须一致并进入 Context Revision Fingerprint；不执行、编译或加载目标代码。

## 结果

Context Revision 可以稳定表达并追踪：

```text
Route → Request DTO → Service → Mapper/Entity → Table
```

Bean Validation、State Candidate、Exception、Feign/Kafka 与 Table Column 也进入同一张有界图。真实本地 RuoYi
Golden 使用固定源码 Revision 验证上述链路，CI 使用同结构的固定强类型 Fixture，二者均不执行目标代码。

State Knowledge 仍是 Evidence Graph，不是运行时调用追踪，也不自动接受 Entity Mapping 或创建 Flow Proposal。
Context Inspector 负责在 S57 后续交付中向用户展示显式关系、`may_*` 复核关系与关联 Evidence。

## 否决方案

- 保存或重新解析原始源码来构建可变图。
- 把类名相似直接记为 `calls`、`uses_repository` 或其他确定关系。
- 为 State Knowledge 新建独立 Revision、Proposal 或审批生命周期。
- 超过图预算后截断节点/边但仍把 Context 标为 Ready。
