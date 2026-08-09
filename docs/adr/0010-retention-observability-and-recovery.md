# ADR 0010：保留期、可观测性与可恢复发布

## 状态

已接受（S11）

## 决策

1. 项目默认保留执行、报告和附件 90 天，Owner 可在系统上限内调整。审计记录不随项目保留期删除。
2. Celery Beat 每日触发清理；只有已完成且超过项目截止时间的执行可删除，运行中记录不参与清理。
3. Artifact 删除先校验并删除 S3 对象，再删除数据库元数据。对象存储失败时保留元数据并记录失败计数，等待下次重试。
4. 过期幂等记录、Refresh Session 和未合并 Import Preview 作为系统临时状态独立清理。
5. API 暴露低基数 Prometheus 文本指标；UUID 路径统一为 `{id}`，执行数量从 PostgreSQL 当前状态派生。
6. PostgreSQL 使用 custom-format `pg_dump`，MinIO 使用带对象 key、大小和 SHA-256 的版本化 Manifest。正式恢复必须显式确认。
7. 每次发布在临时 Docker 网络和独立 PostgreSQL/MinIO 卷中执行恢复验证，成功或失败后均清除隔离资源。
8. 单机 Compose 是 V1.0 唯一部署目标；服务设置内存/CPU 上限，Worker 并发通过配置调整。

## 结果

- 数据生命周期、指标基数和恢复流程具有确定、可测试的边界。
- 备份不仅证明“可以生成”，还证明 PostgreSQL 表与 MinIO 对象能在隔离环境恢复并校验。
- 保留期清理不依赖 FastAPI，HTTP 手工触发和 Celery 定时任务复用同一应用服务。
