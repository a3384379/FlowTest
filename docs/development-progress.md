# FlowTest 开发进度

最后更新：2026-08-12（Asia/Shanghai）
状态：S20 本地实现与验收完成，待 Draft PR 全量 CI；S21 尚未开始功能编码。

## 当前恢复点

- V1.8 基线：`main@7f2b6a7846ad157336c902ecfe518b49e89c8c9c`，标签 `v1.8.0`。
- 当前分支：`agent/s20-enterprise-observability`。
- S19 PR #21 已全绿并 squash 合并；用户要求修复的五项取消/失败检查已由新提交全部替代为通过结果。
- S20 本地功能、迁移、单元/集成、浏览器、观测栈和 PITR 演练已通过；尚未提交 Draft PR，GitHub CI 状态待创建 PR 后记录。
- S21 AI 助手与 V2 发布、V3 S22–S31 均未开始。
- `FlowTest_V3_UI_CN_HD/` 是用户提供的未跟踪原型资产，保持原样；计划在 S22 排除 `.DS_Store` 后单独纳入 Git。

## S20 已完成实现

### OIDC Authorization Code + PKCE

1. 新增一次性 `OIDCLoginTransaction`；state/nonce 只保存 SHA-256，PKCE verifier 使用 AES-GCM 加密。
2. 回调在访问 Provider 前以数据库行锁消费事务，阻止并发重放；校验签名、Issuer、Audience、nonce、允许算法、邮箱已验证和允许域名。
3. JIT 用户默认无系统管理员和项目权限；本地管理员登录保留；固定前端成功地址，不在 URL 暴露 Access Token。
4. Access Token 保持 15 分钟；Refresh Token 通过 HttpOnly/SameSite Cookie 轮换与撤销。
5. Alembic `20260811_0016` 提供 upgrade/downgrade。

### Vault KV v2 Credential Provider

1. Credential 支持 `local` 与 `vault_kv_v2`；Vault 路径由平台生成，数据库仅保存 Provider 引用。
2. 创建、运行时读取、轮换和删除均通过固定 KV v2 API；禁止重定向，生产要求 HTTPS，API 只返回元数据。
3. Workflow Snapshot 通过注入的外部 Secret Store 固定运行材料；Vault 明文不进入 ORM、响应、日志或 Snapshot。
4. Alembic `20260811_0017` 提供 upgrade/downgrade；若存在 Vault Credential，降级会明确拒绝而不是静默丢失引用。

### OpenTelemetry、指标与 Grafana

1. FastAPI、HTTPX、SQLAlchemy、Celery 使用 OTel 自动插桩；执行引擎通过基础设施装饰器产生 Workflow/Node Span，不依赖 OTel SDK。
2. W3C Trace Context 已真实验证贯通 API → Celery → Workflow → Node；Trace 标签不含请求正文或 Secret。
3. Prometheus 新增 General/Data/AI 队列深度、三类 Worker 心跳、任务 succeeded/failed/retried 计数和可用性指标。
4. 修复不可变 `NodeExecutionError` 穿过 OTel Context Manager 后丢失重试类别的回归，并增加行为测试。
5. 可选 Compose `observability` Profile 固定 OTel Collector 0.153.0、Tempo 2.10.7、Prometheus 3.12.0、Grafana 12.4.3；中文仪表盘和数据源已真实启动验证。

### WAL-G PITR

1. PostgreSQL 17.6 镜像内置 WAL-G 3.0.8；ARM64/AMD64 下载包分别固定 SHA-256 并在构建期校验。
2. PITR 默认关闭；启用时打开 `archive_mode`，使用加密 WAL-G S3/MinIO 前缀连续归档。
3. 提供基础备份脚本和隔离 PITR 演练脚本；临时容器与卷使用显式前缀并在结束后清理，不挂载当前数据卷。
4. 真实演练已验证：目标时间前的 `base`、`before-target` 存在，目标时间后的 `after-target` 不存在。

## S20 已完成验证

- 后端：Ruff format/check、mypy strict 全绿；190 项通过、3 项按环境跳过；总覆盖率 90.30%。
- 安全重点：OIDC Service 97%、OIDC HTTP 96%、Credential 96%、Vault HTTP 97%，均达到 95% 模块门槛。
- 前端：95 项通过；Statements 83.27%、Branches 80.07%、Functions 81.25%、Lines 85.19%；构建通过。
- Playwright：Setup 1/1、S14–S19 与 V1 主路径 7/7 通过；人工浏览器验收登录与真实 Dashboard 通过。
- 迁移：真实 PostgreSQL 完成 `0017 → 0015 → 0017`，`alembic check` 无漂移。
- 观测栈：Collector、Tempo、Prometheus、Grafana 启动通过；Prometheus Target 为 up，Grafana 预置仪表盘可查询，跨 API/Worker Trace 可下钻。
- 恢复：WAL-G 加密基础备份、WAL 归档和隔离时间点恢复通过。
- 依赖审计：Python 与前端生产依赖均无已知漏洞。
- Compose：API、Web、PostgreSQL、Redis、MinIO、General/Data/AI Worker、Beat 与可选观测栈均已真实运行。

## 本轮额外修复

1. S15 E2E 不再假设项目列表第一项固定为 V1 Pilot，改用当前项目内可用环境。
2. Ant Design Select 定位器限定到最后打开的可见下拉层，避免关闭动画导致跨下拉误点。
3. V1 E2E 显式选择 `S11 V1 Pilot` 项目，避免容量/Smoke 新建项目改变路由目标。
4. E2E Setup 无论首次改密标志如何，都会把管理员密码规范为唯一 active 密码，消除每个测试双重失败登录和限流碰撞。
5. Compose 的 OIDC/OTel JSON 环境变量修正为无额外引号的合法 JSON。

## 下一步

1. 提交 S20，创建 Draft PR，执行 Backend、Frontend、Security、Compose 全量 CI；真实失败修复后再 Ready/squash 合并。
2. 合并后从 `main` 创建 `agent/s21-ai-release`，实现 OpenAI-compatible 异步 AI Job、Suggestion 审核、严格 JSON Schema、脱敏与评测集。
3. S21 完成升级/回滚、隔离恢复、安全扫描和两周 RC 观察前，不创建 `v2.0.0`。
4. `v2.0.0` 真实发布前不开始 S22；V3 原型资产在 S22 以独立提交纳入。
