# ADR 0028：档位兼容契约与 Compact 质量基线

状态：Accepted
日期：2026-08-19

## 背景

Compact 只有在能够无损进入 Full 时才适合公司试用。仅比较 ORM 或 Alembic 版本不足以证明
Artifact、不可变 Workflow Snapshot、Celery 执行和加密数据在拓扑切换后仍可用。反之，
把短时冒烟当作长时稳定性证据也会隐藏内存增长、容器重启和队列积压。

## 决策

1. Full 与 Compact 在同一代码上共享 PostgreSQL 卷、Redis 协议、MinIO Bucket、加密密钥和
   Alembic Head。档位切换只更换应用进程拓扑，不转换业务数据格式。
2. 双向兼容验收必须在 Compact 创建 Project、Artifact、Workflow Version 和已通过 Execution，
   切换到 Full 分离 Worker/Beat 拓扑后读取并验证；再由 Full 创建同类资产，切回 Compact 验证。
3. 兼容编排是数据和控制面契约工具，不代替 Full 的 Performance/Environment Worker、PITR、
   Redpanda、Runner 和可观测性发布验收。
4. Compact 至少保留两类容量证据：公开 API 并发延迟/失败率，以及真实持久化 Workflow 执行
   P95/吞吐。采样前后保留每容器 CPU/内存数据，验收后所有 Celery 队列必须归零。
5. 稳定性探针持续检查 Readiness、运行档位、6 服务数量、容器重启和队列深度。短时 CI 只验证
   探针逻辑；公司试点仍要求至少 72 小时连续观察，且不替代正式 RC 的 14 天门槛。
6. 不允许在较新 Alembic 迁移已执行后仅通过切换旧镜像回滚。跨版本回滚必须使用升级前一致性备份。

## 结果

Compact 不是独立产品分支，公司试点产生的资产可直接进入同版本 Full。自动化会提前暴露
格式分叉和基本容量回归，但 72 小时试点、公司网络/安全审批和 14 天 RC 仍需要真实时间与人工签署。
