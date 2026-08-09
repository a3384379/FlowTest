# ADR 0007：持久化任务分发与测试计划

## 状态

已接受（S8）

## 决策

1. API 进程只校验请求、创建不可变执行数据并向 Celery 发送资源 UUID，不在线程内运行工作流。
2. 工作流的真实运行载荷使用 AES-256-GCM 加密保存；公开 Snapshot 保持脱敏，Worker 仅凭执行 ID 解密并恢复固定计划。
3. Celery 任务通过 `asyncio.Runner` 调用独立执行协调器，执行引擎与领域模型不导入 Celery。
4. Test Plan Item 在创建时固定 Workflow Version；每次入队再复制为 Test Plan Run Item，后续计划修改不影响已排队运行。
5. Celery Beat 周期扫描数据库中的到期计划，使用行锁领取并推进下一次 UTC 运行时间。
6. CI Token 只保存 SHA-256 摘要，固定到单个项目和显式操作范围；Token 明文只在创建响应中返回一次。
7. Webhook Secret 使用 AES-256-GCM 保存；触发请求签名覆盖 `timestamp.body`，默认只接受五分钟时间窗。
8. 计划取消先写数据库状态，再向所有活跃 Workflow Execution 传播协作式取消；Worker 在领取和重试前重新检查状态。

## 结果

- API、Worker 和 Beat 可独立重启和扩缩容，队列消息不包含 Secret、请求体或文件。
- 批量运行、应用级重试、手动/定时/CI/Webhook 触发共享同一持久化状态机。
- 加密运行载荷会增加数据库占用，S11 的保留策略和容量测试必须覆盖大数据集及文件工作流。
