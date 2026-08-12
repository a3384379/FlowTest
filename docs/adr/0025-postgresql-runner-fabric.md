# ADR 0025：PostgreSQL Lease/Fencing 与隔离 Runner 执行面

## 状态

已接受，S29 实现。

## 背景

V3 需要把 Workflow 从单机 Celery Worker 扩展到可部署在远程 Docker 或 Kubernetes
的 Worker Plane，同时保留不变计划、项目出站策略、取消语义与唯一终态。Redis/Celery
投递不能单独表达任务已持久、由谁认领、租约是否过期和旧 Worker 结果是否已被
Fence。Runner Profile、注册令牌、Workflow Snapshot 和远程结果都必须视为不可信输入。

## 决策

1. PostgreSQL 是 `RunnerTask`、`RunnerLeaseRecord` 和 `RunnerEvent` 的唯一事实源。Task 保存
   Runner 类型、标签、能力、尝试次数、当前 Fence 和唯一终态；加密 Workflow 计划继续固定在
   Execution Snapshot，不复制明文到队列表。
2. 系统管理员创建有运行时、网络区、标签、能力和并发上限的 Worker Pool。Runner 只能使用
   有效期、一次性注册令牌接入；注册与身份令牌只保存 Argon2 哈希，明文只在创建响应中返回
   一次。每个 Token 对应一个不变 Runner 身份，Kubernetes 不共享 Token 水平扩容。
3. Claim 通过 `FOR UPDATE SKIP LOCKED` 选择任务，并用分命名空间的 PostgreSQL 事务级
   advisory lock 串行化 Pool、Runner 和 Project 容量决策。这保留并发上限，且不会与
   Event 外键的 Key Share 行锁形成反向锁链。
4. 每次认领原子递增 Task Fence 并创建有限时 Lease。Renew、Progress、Complete 和 Fail
   必须同时匹配 Runner、Lease、Task 和 Fence；旧 Lease 只能得到标准 `409` Fence 响应，不能
   写入节点或终态。过期租约最多按固定尝试次数重排；故障、超时、取消、Drain 和 Runner
   重启共享同一幂等状态机。
5. Runner 只执行平台已验证的 `flow.workflow` 计划，执行前校验 SHA-256，重新加载项目出站
   Host/CIDR 策略，并对远程结果执行大小、类型和节点唯一性校验。S29 不接收用户自定义
   Compose、Shell、插件代码、宿主凭据或 Kubernetes ServiceAccount。
6. Docker Runner 使用 UID/GID 65532、只读根文件系统、Drop ALL 和
   `no-new-privileges`；Kubernetes 示例同时禁用 ServiceAccount Token、启用 RuntimeDefault
   seccomp 和资源上限。生产环境必须使用 HTTPS 控制面和经审批的不变镜像 Digest。
7. Runner 控制面使用与用户写接口分离的限流桶，按哈希后的 Runner Token 身份计数；
   事件和 Prometheus 标签不包含 Token、UUID 或计划正文。

## 结果

- 远程 Worker 可在控制面进程退出、连续网络失败或重复消息下重新认领，旧结果不会覆盖新
  Fence 的唯一终态。
- PostgreSQL 事务和锁顺序成为关键容量边界；任何调整都必须重跑 5000 排队、500 Workflow、
  多 Worker 与故障转移门槛，并检查数据库无死锁。
- S29 不尝试在 Runner 中开放任意插件或宿主容器管理权限；后续执行类型必须使用独立能力、
  镜像和安全评审。
