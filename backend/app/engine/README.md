# Execution Engine

本目录承载 `ExecutionContext`、变量解析、字段映射、DAG 校验/调度和节点执行器。

关键约束：

- 每次执行使用不可变 Snapshot。
- 节点只通过 Context 读写数据。
- DAG 调度器负责并行、跳过、失败传播和取消。
- Web API 不直接承载耗时执行逻辑。
