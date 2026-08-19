# ADR 0026：显式运行档位与小型化部署

状态：Accepted
日期：2026-08-19

## 背景

Full Compose 为容量、安全和多执行面验收同时启动 PostgreSQL、Redis、MinIO、Redpanda、多类 Worker、
Environment DinD、Mock 目标及 Web/API。该拓扑适合完整发布验收，但首次拉起的服务数量和资源需求阻碍
公司内网试用，尤其不利于只有 2 CPU、4 GB 内存的测试服务器。

仅在文档中少启动若干服务是不安全的：Feature Flag 仍可能声明 k6 或 Environment 能力可用，Celery
任务随后进入没有对应运行时的队列。以 SQLite、本地目录和进程内任务替换现有基础设施又会改变迁移、
锁、持久队列、事件回放和 Artifact 语义，形成难以验证的第二套产品。

## 决策

1. 引入显式 `full` 与 `compact` 运行档位。档位是部署拓扑契约，不是租户功能开关。
2. 两个档位共享 API、领域服务、PostgreSQL Schema、Alembic 链、Redis 协议和 S3 Artifact 格式。
3. Compact 固定为 6 个服务：Frontend、Backend、合并 Celery Worker/Beat、PostgreSQL、Redis、MinIO。
4. Compact Worker 消费所有已知队列以避免消息滞留，但配置层固定拒绝启用缺少 k6 镜像的
   Performance Lab 和缺少隔离 DinD 的 Environment Lab。
5. Redpanda、Mock、观测套件和本地 Runner Agent 不进入 Compact 基线；事件协议可连接经治理的外部目标，
   Runner Fabric 后续可使用远程 Agent。
6. `/api/v1/runtime-profile` 公开当前档位、Worker 拓扑和不可用能力，供部署验收与后续前端能力提示使用。
7. Compact 不使用默认密码。生成器只创建权限为 `0600` 的随机配置并拒绝覆盖已有文件；默认 Web 只监听
   Loopback，PostgreSQL 与 Redis不发布宿主端口，MinIO API 仅发布到 Loopback。
8. Compact 备份使用 Backend 镜像内的受控运维入口，在维护窗口同时固定 PostgreSQL custom
   dump 和 MinIO 对象哈希清单。覆盖恢复前必须完整预验证，恢复后再校验对象集与 Readiness。

## 结果

公司试用可在保留生产数据语义的前提下降至 6 个容器和约 2.6 GB 容器内存上限。Full 继续承担性能、
环境实验室、隔离 Worker、容量和发布验收，因此已有 CI 与部署路径不受影响。

合并 Worker 降低故障隔离，并且 Compact 不具备 WAL-G PITR 和完整观测套件；这些限制
必须在运维文档和运行档位接口中保持可见。未来若引入嵌入式数据库或本地 Artifact Store，必须另立 ADR，
证明迁移、锁、队列、加密、备份和升级语义等价后才能替换本决策。
