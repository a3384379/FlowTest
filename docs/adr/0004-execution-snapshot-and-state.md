# ADR 0004：Execution Snapshot 与状态机

状态：Accepted

执行开始时固定 Workflow、API、Environment 和 Dataset 版本。节点状态固定为 pending、running、passed、failed、skipped、cancelled。节点通过 ExecutionContext 交换数据，不直接访问其他节点内部对象。
