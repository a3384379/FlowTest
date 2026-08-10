# ADR 0013：只读数据节点、加密 Credential 与规则化 Mock

状态：Accepted

## 背景

SQL、Redis 和 Mock 会把执行平面扩展到数据库、缓存及公开的模拟入口。若节点可执行任意语句、运行时回读最新 Credential、Mock 模板具备脚本能力，平台会引入写入破坏、SSRF、Secret 泄漏和历史执行漂移风险。

## 决策

1. Credential 归属单一项目，值使用现有 AES-256-GCM 加密，AAD 固定绑定 Credential ID 与 Project ID。REST 接口只返回元数据，创建和轮换后的 Secret 均不可读回。
2. SQL 首批支持 PostgreSQL 与 MySQL，只允许 sqlglot 解析成功的单条 `SELECT` 或 `WITH ... SELECT`。连接事务强制 `READ ONLY`，超时最多 30 秒、结果最多 1000 行、内联结果最多 2 MB。
3. Redis 仅允许 GET、MGET、HGET、HGETALL、SMEMBERS、ZRANGE、EXISTS、TTL，并为每条命令固定参数数量；ZRANGE 只允许非负且最多 1000 项的有界范围。
4. 数据节点在 Workflow 发布时校验节点类型、Credential 类型和只读语法。执行准备阶段解密 Credential 并写入 AES-GCM 加密执行计划；公开 Snapshot 只保存 Credential 元数据，Worker 不回读最新值。
5. PostgreSQL、MySQL 和 Redis 目标统一经过现有 DNS、域名与私网 CIDR 出站策略。DNS 解析后的每个地址均重新校验，连接建立后再校验实际传输对端地址，阻断 DNS Rebinding；元数据、回环、链路本地和未授权私网保持拒绝。
6. Mock 服务按 Method、精确路径模板、Query/Header 条件和可选场景匹配。响应只支持 JSON 占位符，来源限定为 Path、Query、Header 和 Body，不提供表达式求值或用户脚本。
7. Mock 响应状态、延迟和大小均有上限，公开调度使用执行级限流，禁止设置传输级和同源安全敏感 Header。请求日志复用统一脱敏规则，并按项目保留策略清理。
8. 数据驱动实现位于可注入的 Runner 接口之后；Node SDK 与调度器不依赖 SQLAlchemy、Redis 或具体驱动，Celery 仍只恢复固定计划并调用执行引擎。

## 结果

- 数据节点只能读取并具有明确资源上限，驱动异常不会把连接信息或 Secret 暴露到报告。
- 历史执行使用固定 Credential 材料，不受后续轮换或删除影响。
- Mock 可覆盖契约测试与异常场景，但不形成第二套脚本执行环境。
- 未来增加其他数据源时，必须复用 Credential、出站策略、Snapshot、审计、脱敏和报告协议。
