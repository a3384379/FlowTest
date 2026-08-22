# ADR 0032：V5 运行档位演进与兼容护栏

## 状态

提案草案；V4 真实公司试点签署后评审，不在 V4 正式标签前生效。

## 背景

V4 同时支持 Full、Compact 和 Windows Standalone。V5 预计增加租户隔离、可恢复执行、密钥轮换和
企业扩展能力；如果直接把新能力绑定到某一个基础设施，会破坏公司云桌面的轻量部署边界或把
Standalone 错误地宣传为高可用执行平台。

## 决策方向

- PostgreSQL/Redis/MinIO 仍是 Compact/Full 的权威外部依赖；SQLite 只用于 Standalone，并通过
  `standalone-compact-transfer-v1` 或其向后兼容版本迁移。
- 新业务能力先定义领域端口和版本化命令/事件契约，再由 Full、Compact、Standalone 分别注入适配器。
  Domain/Engine 不导入 FastAPI、Celery、SQLAlchemy Model 或具体基础设施客户端。
- Durable Command、租约、幂等和恢复策略优先增强 Compact/Full；Standalone 仅实现低并发、有界、
  明确不可恢复的本地行为，并在 Runtime Profile 中公开能力差异。
- `/api/v1` 默认兼容；破坏性变化必须通过新 API 版本、迁移脚本、回滚证据和兼容矩阵发布。
- Secret、Artifact、租户数据和诊断证据在跨档位/跨租户传输前必须带数据分类、密钥版本和显式审计。

## 否决方案

- 不把 Docker、Kubernetes 或云托管服务设为 V5 所有安装的硬前提。
- 不通过复制 SQLite 文件、共享 `.env` 或复用运行时队列状态实现迁移。
- 不让插件执行任意宿主命令、读取 Secret 明文或访问 Docker Socket。

## 评审门槛

V5 每个阶段必须同时提供 profile compatibility、真实 PostgreSQL 迁移、失败恢复、依赖/镜像扫描、
升级回滚和最小权限证据；V4 试点未签署前不创建 V5 正式实现分支或版本标签。
