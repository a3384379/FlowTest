# ADR 0005：后台执行与实时事件传输

状态：Accepted

## 决策

- `POST /api/v1/projects/{project_id}/workflows/{workflow_id}/executions` 在 Snapshot 落库后返回
  `202 Accepted`，不在 HTTP 请求生命周期内等待执行完成。
- S6 使用由 FastAPI lifespan 管理的显式协调器启动应用内异步任务；协调器为每次
  执行创建独立数据库会话。S8 将保持同一 `WorkflowRunPlan` 边界并替换为 Celery Worker。
- 纯 DAG 调度器只发出类型化节点状态回调，不依赖 Redis、FastAPI、Celery 或 ORM。
- 应用层将事件转换为带单调递增 `sequence` 的执行事件。Redis 以受限列表保存最近
  500 条事件，默认保留 24 小时，同时通过 Pub/Sub 发布。
- WebSocket 路径为 `/api/v1/executions/{id}/events`。客户端请求
  `flowtest.events.v1` 和 `flowtest.token.{access_token}` 子协议；服务端先验证用户及项目可见性，
  再接受连接。
- WebSocket 订阅先订阅 Pub/Sub，再回放 Redis 历史，并以 `sequence` 去重，避免连接窗口丢失事件。

## 结果

前端可在获得 Execution ID 后立即订阅节点状态，且稍晚连接仍可回放。S6 运行任务在 API
进程内，不承诺进程崩溃后续跑；持久队列、跨进程取消和故障恢复属于 S8。
