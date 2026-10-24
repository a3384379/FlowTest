# S5 扩展与非模型验收

2026-10-24：S5 文件、并行 Cookie、worker claim/心跳/崩溃收敛扩展已实现。真实 Host/LLM 按用户要求保持关闭。当前实测来源、三形态收据和剩余外部边界以[当前验证记录](current-validation.md)与[94 项账本](acceptance-matrix.md)为准；[早期开发记录](s5-development-history.md)仅保留失败与旧构建历史。

## 已实现

- 合成文件原生 multipart、下载、SHA-256/长度/content type/项目归属独立核验；同时覆盖 FlowTest B 自身文件 API，提取本轮 UUID、用独立 B 只读用户下载，并精确销毁所属栈回收文件。
- 两个并行分支使用各自客户端和 Cookie，确定性屏障证明并发峰值 2，核对六条请求及 left/right 合成 Cookie，不扩张任意 Cookie 采集。
- TestPlanRun 增加 worker owner 与租约截止，原子 claim、心跳和完成阶段 fencing；旧 worker 的迟到结果不能覆盖已判定失效的执行。取消和准备串行化，取消后不再创建正式任务。未知写入不重放；已知完成保留，其余以 `TEST_PLAN_WORKER_LOST` 失败。
- 新增 Alembic `20261024_0068` upgrade/downgrade，以及既有 Standalone 表增量升级路径；不完整历史表不盲建索引。
- 映射预检覆盖初始化、已有安装预览、H 物化及原生 dispatch：环境、默认 ServiceEndpoint、目标身份或类别漂移即阻断。PostgreSQL 先取得与原生执行一致的项目准入锁，再锁定实际环境与端点行，避免外键和配额锁形成死锁，同时保留新增端点的阻挡；标准错误保留 trace ID。
- 新增产品边界 27、编译/Quick/FlowSpec 草稿 38、独立 O 抗误绿 28，纳入所有适用部署形态 CI。全部 schema 已从 37 个具名强类型模型同步导出。

## worker 部署与迁移

Celery TestPlan runner 使用 60 秒租约和周期心跳；beat 每 15 秒运行失效收敛。Full 使用既有独立 beat；Compact 使用既有内嵌 beat。验收 profile 同样启用真实 beat，不通过改数据库或手动调用恢复函数冒充自动收敛。滚动升级前先完成迁移；回退 schema 前须排空并停止使用新租约列的 worker，恢复旧应用时遵循既有备份/回退流程。

Standalone 本地后台执行不启用 Celery 租约，因此 Celery 双 worker 与消息故障不适用；一般排队、取消、幂等、快照漂移、观察截止仍实际运行。真实 4 个阻塞工作流占满槽位，避免用伪排队状态代替。

## 验收解释

当前来源的本地完整入口、保留原构建摘要的 GUI、原始/独立双 JUnit 和精确清理结果见[当前验证记录](current-validation.md)。`local_untrusted` 不授予远程 Required Gate。旧稳定版本不支持新自测 API 的交叉组合以能力探测明确不适用，不能降级契约来制造通过。真实模型、真人审核及 assisted 质量验收继续 NOT_RUN。
