# ADR 0001：模块化单体与执行平面边界

状态：Accepted

FlowTest 以模块化单体启动，但控制平面与执行平面保持代码边界。API 服务负责资产、权限、计划和报告；执行引擎只读取不可变 Snapshot，并通过独立 Worker 运行。执行引擎不得依赖 FastAPI、Celery 或 ORM 模型。
