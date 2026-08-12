# ADR 0018：Capability SDK、Legacy Adapter 与 Runner 边界

## 状态

已接受（S22）

## 背景

V2 节点以 `type + config` 保存并由进程内 Handler 执行。V3 需要在不重建历史 Workflow、Snapshot
和报告的前提下引入多协议、插件及远程 Runner。如果直接修改 V2 数据或允许插件进入 API/Worker
进程，将破坏历史可重放性并扩大 Secret、网络与容器权限边界。

## 决策

1. 每项执行能力由不可变 `CapabilityManifest` 标识，固定 `id/version`、JSON Schema 2020-12
   输入/输出/配置、Credential 类型、网络策略、Runner 类型、超时、Snapshot 与脱敏策略。
2. V2 节点不执行数据迁移。`LegacyNodeAdapter` 在计划阶段把全部 12 种 V2 节点编译为固定的
   `2.0.0` Capability；显式 V3 节点保存 `capability_id/capability_version/configuration/bindings`。
3. Workflow Snapshot 为每个节点保存 Capability ID、版本、Schema SHA-256、Runner 类型、来源及
   Plugin ID/OCI Digest。配置仍随不可变 Workflow Definition 固定，Credential 材料继续由现有加密
   Execution Plan 保存，不进入公开 Snapshot。
4. 调度器接受旧节点输出或统一 `NodeResult`，并始终归一化后持久化。`NodeResult` 固定包含状态、
   结构化输出、断言、指标、Artifact、Trace、脱敏路径和标准错误；原 `output/error_code` 字段保留以
   兼容 V1/V2 API 和报告。
5. `ExecutionEvent` 从基础引擎模块定义，使用 Redis 原子递增序号发布；事件预留 Attempt 与
   Fencing Token。领域/引擎不依赖 FastAPI、Celery、SQLAlchemy 或 Redis。
6. S22 仅定义 Runner Control Plane 的类型接口、Runner Pool/Runner 元数据和 Feature Flag。
   PostgreSQL 任务、Lease/Fencing 的事实源及远程领取协议在 S29 实现，不用临时 Redis 队列冒充。
7. Plugin 只接受管理员声明的 OCI 镜像与 sha256 Digest，Manifest 必须固定签名身份、能力所有权和
   Digest，并强制只读根文件系统、`cap-drop ALL`、`no-new-privileges` 及资源上限。S22 只验证
   Manifest；Cosign 安装与专用 Plugin Runner 在后续安全迭代开放。
8. 三项能力分别由 `CAPABILITY_SDK`、`PLUGIN_REGISTRY`、`RUNNER_FABRIC` Feature Flag 控制。
   默认均关闭；关闭时 V2 Workflow 行为不变，显式 Capability 发布被拒绝。

## 结果

- V2 与 V3 节点可在同一 DAG 中运行，历史数据无须迁移且继续可重放。
- Capability、插件、Runner 与传输实现之间保持显式、可测试的依赖方向。
- 未实现的签名安装和分布式 Lease 不会以假数据或不安全捷径暴露给用户。
- 后续协议节点只需提供版本化 Manifest 和隔离 Runner，实现不再侵入核心调度器。
