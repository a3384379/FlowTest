# Execution Engine

本目录承载 `ExecutionContext`、变量解析、字段映射、DAG 校验/调度和节点执行器。

关键约束：

- 每次执行使用不可变 Snapshot。
- 节点只通过 Context 读写数据。
- DAG 调度器负责并行、跳过、失败传播和取消。
- Node SDK V2 通过显式 Handler Registry 扩展节点，调度器不按框架或节点类型堆叠分支。
- SubFlow/ForEach 只运行父执行计划内递归固定的已发布快照；最大深度 5，禁止递归。
- ForEach 使用受限 JMESPath，最多 1000 项、并发 1～20，不执行用户脚本。
- 断点与重放按目标节点裁剪祖先子图，并复用相同执行器与脱敏协议。
- Web API 不直接承载耗时执行逻辑。
