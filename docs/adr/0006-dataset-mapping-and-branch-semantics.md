# ADR 0006：数据集、字段映射与条件分支语义

## 状态

已接受（S7）。

## 决策

- 一个 Workflow 最多包含一个 Dataset 节点。发布时读取并校验文件，执行时将文件内容和格式
  固定进 Snapshot；CSV、JSON、Excel 统一转成具名字段行，最多 1000 行、200 列。
- 每行创建独立子执行，父执行不重复保存节点结果，只聚合 passed、failed、cancelled 数量。
  子执行默认并发 5，顶层历史只展示父执行，详情可下钻全部数据行。
- 字段映射属于 Edge，源端固定为该边 source 节点，以 JMESPath 读取输出；目标端固定为 target
  节点，支持 Query、Header、JSON Body 路径和 ExecutionContext Variable。
- Condition 节点必须恰有 `true`、`false` 两条出边。未选择边标记为 inactive，其下游节点记为
  `skipped/BRANCH_NOT_SELECTED`；汇合节点只要求所有 active 入边成功，blocked 失败仍会传播。
- 变量优先级保持 Workflow → Dataset → Runtime（前置 Global/Project/Environment 已在请求准备阶段
  解析）；每个最终变量保存 scope、node_id 和 path 来源，报告不保存 Secret 或映射值副本。

## 结果

执行历史可解释每行数据、每个条件选择和每个映射来源；发布版本及其历史执行不会受后续文件、
API、环境或草稿修改影响。父子执行增加少量持久化开销，但提供可靠的取消、下钻和后续报告基础。
