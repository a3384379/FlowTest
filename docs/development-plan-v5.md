# FlowTest V5.0 设计设想（草案）

V5 的前提是 V4 的运行档位和供应链不被破坏：Standalone 继续服务没有 Docker/虚拟化能力的
Windows 云桌面，Compact 继续服务公司单机试用，Full 继续承担完整执行平面。V5 不以“再增加一个
部署方式”为目标，而是把 V4 已验证的边界提升为可扩展的企业运行平台。

## 目标

1. **企业隔离**：在现有单组织模型上增加组织/租户边界、成员目录、项目配额和审计查询，默认拒绝
   跨租户读取、Artifact 访问和执行触发。
2. **可恢复执行**：把当前 Celery/进程内任务统一抽象为幂等 Command + Execution Journal；Compact
   保持单机语义，Full 支持 Worker 重启后安全恢复，Standalone 明确继续使用低并发有界队列。
3. **高可用控制面**：为 PostgreSQL/Redis/MinIO 外部依赖定义 HA 运行契约、优雅 Drain、租约续期和
   版本化 Worker 能力；Kubernetes 只作为可选执行面，不成为公司轻量部署前提。
4. **安全生命周期**：支持数据加密密钥轮换、密钥版本、最小权限服务账号、审计保留策略和脱敏支持
   包；迁移工具必须显式声明数据分类和恢复边界。
5. **可观测产品化**：提供租户/项目级 SLO、容量趋势、失败聚类、升级证据和公开的运行档位契约，
   让公司试点结果可以直接进入发布决策。
6. **扩展生态**：以稳定的 Capability/Plugin SDK、版本化 Schema 和签名包支持内部插件，但禁止
   插件获得任意宿主命令、Secret 明文或 Docker Socket。

## 建议里程碑

| 小阶段 | 方向 | 首要交付 | 退出条件 |
|---|---|---|---|
| S38 | V4 收口与兼容冻结 | Standalone/Compact 试点签署、V4 迁移证据、API/Schema 兼容基线 | V4 手册、CI、真实试点记录齐全；不改变 `/api/v1` |
| S39 | 组织与租户边界 | Tenant/Org 模型、成员目录、项目配额、审计查询和跨租户拒绝测试 | PostgreSQL 真实迁移、权限矩阵和数据隔离门禁通过 |
| S40 | Durable Command | Command/Journal、幂等键、恢复点、Drain/重试/取消状态机 | Worker 重启和重复投递不丢失、不重复终态 |
| S41 | HA 控制面 | 外部依赖 HA 契约、租约、能力协商、版本化 Worker 和可选 K8s Runner | Compose/Full 主路径、回滚和容量门禁通过；Compact 不增加必需容器 |
| S42 | 密钥与合规 | Key version/rotation、审计保留、支持包签名、策略导出 | 旧密钥只读解密窗口可控；诊断包无 Secret/业务载荷 |
| S43 | 生态与发布 | Plugin SDK、签名扩展包、兼容矩阵、V5 Release Gate | SDK 合约、供应链扫描、升级/回滚和公司试点签署完成 |

## 设计约束

- `/api/v1` 现有客户端保持兼容；破坏性变更只能进入新版本 API，并提供迁移期和回滚方案。
- PostgreSQL 仍是 Compact/Full 的权威业务存储；SQLite 只属于 Standalone，并通过显式 transfer
  manifest 迁移，禁止复制数据库文件冒充迁移。
- Standalone 不承诺 HA、崩溃后任务续跑或容量基线；V5 的 Durable Command 只能增强 Compact/Full，
  不得让公司云桌面被迫安装 Docker、WSL2、数据库或开发工具。
- 领域模块不依赖 FastAPI、Celery、SQLAlchemy Model 或具体云客户端；运行档位通过 typed port/adaptor
  注入，任何新能力必须有 profile compatibility 测试。
- Secret、Cookie、Token、授权头、加密密钥和业务响应默认不进入日志、指标、诊断包或模型输入；所有
  外部错误继续使用带 trace ID 的标准 envelope。

## V5 第一轮实现顺序

1. 先完成 S38 的 V4 试点/迁移证据与 API/Schema 冻结，再从清洁 `main` 建立 V5 分支。
2. 先做数据隔离和权限矩阵，再做 Durable Command；避免在租户边界未固定前扩大执行平面。
3. 每个小阶段同时提供 Standalone 兼容测试、Compact Smoke、Full/Upgrade/Rollback 门禁；没有对应
   运行档位证据的能力不进入默认 Feature Flag。
4. 以真实迁移、失败恢复、容量和安全证据作为阶段退出条件，不用单元测试数量替代公司试点和时间性观察。

该文件是 V5 设计草案，不代表已经创建 V5 代码分支、正式标签或改变 V4 发布门槛。
