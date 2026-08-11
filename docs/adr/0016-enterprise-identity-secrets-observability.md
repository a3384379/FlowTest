# ADR 0016：企业身份、外部密钥、分布式追踪与时间点恢复

## 状态

已接受（S20）

## 决策

1. OIDC 使用 Authorization Code + PKCE。登录事务只保存 state、nonce 的摘要与加密后的 verifier，且在换取 Token 前以数据库行锁一次性消费。
2. ID Token 固定校验签名、Issuer、Audience、nonce、允许算法、邮箱已验证和邮箱域名；生产环境只允许 HTTPS。JIT 用户默认没有项目权限，本地管理员登录继续保留。
3. Credential 通过 `local` 或 `vault_kv_v2` Provider 保存。Vault 路径由平台生成，数据库仅保存引用；API 始终只读回元数据。包含 Vault Credential 时禁止直接降级迁移，必须先显式转存或删除。
4. OpenTelemetry 位于基础设施适配层。API、HTTPX、SQLAlchemy 和 Celery 自动插桩，执行引擎只通过装饰器产生 Workflow/Node Span，不依赖 OTel SDK。
5. API 到 Celery 使用 W3C Trace Context；Trace 包含 Execution、Project、Workflow 版本和 Node 类型，不记录 Secret、请求正文或高基数任意标签。
6. Prometheus 指标增加固定三队列深度、活跃 Worker 心跳和任务终态计数。Redis 只是运维指标存储，PostgreSQL 仍是业务终态事实源。
7. 可选观测栈由 Compose Profile 提供 OTel Collector、Tempo、Prometheus 和 Grafana；关闭时不影响核心执行。
8. PostgreSQL 镜像固定包含经过 SHA-256 校验的 WAL-G。PITR 默认关闭；启用后连续归档 WAL，并使用加密的 S3/MinIO 前缀保存基础备份和日志。
9. PITR 发布演练必须恢复到独立临时卷，验证目标时间前后的数据边界，并删除演练容器与临时卷；不得覆盖当前数据卷。

## 结果

- 企业登录事务可抵抗 state/nonce/PKCE 重放，JIT 身份不会隐式获得项目权限。
- Secret 可以迁移到 Vault 而不进入数据库密文列、日志或响应。
- API 请求可沿 Celery 消息下钻到 Workflow 与节点，同时执行引擎保持框架无关。
- 指标与 Trace 存储故障不会改变业务执行终态。
- 逻辑备份和 PITR 被明确区分，并各自具备隔离恢复验证流程。
