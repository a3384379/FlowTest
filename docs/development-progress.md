# FlowTest 开发进度

最后更新：2026-08-12（Asia/Shanghai）
状态：S20、S21 已合并；`v2.0.0-rc.1` 源码候选已固定。`v2.0.0` 仍受真实部署与连续 14 天 RC 观察门槛约束。

## 当前恢复点

- 当前基线：`main@06699d54bceee091a2efac838e426cf7ef5c9c9e`，S21 PR #23 已 5/5 全绿并 squash 合并。
- 当前分支：`agent/s21-release-record`，仅记录发布候选证据，不包含产品代码变化。
- 已发布标签：`v1.1.0`、`v1.5.0`、`v1.8.0`、`v2.0.0-rc.1`；不得提前创建 `v2.0.0`。
- `FlowTest_V3_UI_CN_HD/` 是用户提供的未跟踪原型资产，本轮保持原样；仅在 `v2.0.0` 发布后从 S22 独立纳入 Git。

## 已完成：S20 企业与可观测性

1. OIDC Authorization Code + PKCE、state/nonce 一次性消费、邮箱域名 JIT 和固定无权限初始身份。
2. Team 授权、Vault KV v2 Credential Provider 与本地 AES-256-GCM Provider。
3. API → Celery → Workflow → Node 的 OpenTelemetry Trace、队列/Worker 指标和 Grafana 模板。
4. 可选 WAL-G 加密归档、隔离 PITR 演练和回滚保护。
5. PR #22 首轮 Compose 容量门槛在共享 Runner 出现 P95 1.074 秒、零失败；阈值按共享 Runner 基线调整为 1.2 秒后，第二轮 5/5 CI 全绿并合并。业务零失败规则与本地 1.0 秒门槛未放宽。

## 已完成：S21 AI 助手

### 后端与数据

1. 新增 `AIJob`、`AISuggestion`、项目样本共享开关和可升降级迁移 `20260812_0018`。
2. 新增 `/api/v1/ai/status`、项目策略、Job 列表/详情、Suggestion 列表和逐项接受/拒绝接口。
3. AI Job 通过独立 Celery `ai` 队列异步执行；网关关闭或失败不影响现有产品能力。
4. OpenAI-compatible Provider 禁止重定向，生产强制 HTTPS，使用 JSON Schema 2020-12 严格输出。
5. 输入执行深度、节点数和字节上限；Password、Authorization、Cookie、Token、Secret、API Key、Bearer、Basic 与 JWT 统一脱敏。
6. 默认只发送 Schema 和脱敏元数据；样本必须由项目 Owner 显式开启并逐次脱敏，Editor 提交被拒绝。
7. 建议只能人工接受、编辑后接受或拒绝；只有接受的 Test Case/Workflow 才创建草稿，AI 不能发布、执行、创建 Credential 或修改权限。
8. 审计保存模型、提示模板版本、输入摘要哈希、Token 用量、脱敏路径和审核结果，不保存 Secret。
9. 新增离线隐私评测集 `backend/tests/fixtures/ai_redaction_evaluation.json`。

### 前端

1. 新增中文“AI 助手”项目路由、关闭状态、模型/样本策略、任务列表和人工审核工作台。
2. 支持 Schema 用例、断言、Workflow 草稿和失败归因任务；样本输入只在 Owner 开启策略后显示。
3. 接受前可编辑 JSON，畸形 JSON 在浏览器端阻断；拒绝不发送编辑内容；已审核建议不可重复操作。Job 从 pending/running 进入 completed 时会切换 Suggestion 查询键并自动刷新，避免缓存空结果。
4. 页面明确展示“AI 不读取 Secret、不自动发布、不自动执行”。

## 当前验证证据

- 后端：Ruff format/check、mypy strict、依赖边界通过；206 项通过、3 项环境跳过；总覆盖率 90.58%。
- AI 专项：Service 97%、OpenAI-compatible HTTP 100%、Redaction Domain 97%；15 项专项测试通过，另有离线隐私评测集。
- 前端：格式、Lint、TypeScript、99 项测试与生产构建通过；Statements 83.71%、Branches 80.80%、Functions 81.72%、Lines 85.67%。AI Feature Statements 92.10%/Branches 100%，AI 审核页 Branches 92.45%。
- 已验证边界：队列故障、网关断网/拒绝/畸形响应、重复 Worker 幂等、样本权限、超限审核内容、无效草稿、接受后才落库。
- 迁移：真实 PostgreSQL 完成两轮 `0017 → 0018 → 0017 → 0018`，`alembic check` 无漂移；曾发现并修复时间戳默认值与唯一约束的模型/迁移不一致。
- Compose：API、Web、PostgreSQL、Redis、MinIO、General/Data/AI Worker 与 Beat 健康；S21 真实队列/脱敏/人工接受闭环以及 S11/S18/S19 回归通过。
- Playwright：S21 中文 AI 页面真实浏览器链路 2/2 通过（包含登录 Setup）；测试曾发现并修复完成态 Suggestion 不自动刷新问题。
- 依赖与镜像安全：Python、前端生产依赖和 API/Web/Mock 发布镜像扫描全部通过。
- GitHub CI：PR #23 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images 和 Compose Smoke 共 5 项全部通过；Compose 同一提交完成 S1-S21 回归、100 并发 Workflow、1000 持久队列任务和隔离备份恢复。

## 尚未完成的发布门槛

1. 将 `v2.0.0-rc.1` 部署到真实试点环境，记录 API/Web/Worker 镜像摘要、Compose 配置、宿主机规格、试点项目和负责人。
2. 在同一 RC 候选上完成连续 14 个自然日观察和试点签署；该真实时间门槛不能由短时自动化代替。
3. RC 期间如有代码修复，必须创建新的 RC 候选并重新开始连续观察，不沿用旧候选天数。

## 下一步

1. 部署 `v2.0.0-rc.1`，在试点记录中补齐镜像摘要和环境元数据后开始 Day 1。
2. 连续记录 14 个自然日的可用性、执行量、通过率、P95、队列峰值、Worker 重启、事故和用户反馈。
3. 只有 RC 签署、恢复演练、扫描和容量证据全部通过后创建 `v2.0.0`。
4. `v2.0.0` 发布后创建 `agent/s22-capability-sdk`，再开始 V3 S22；S22 前不提交 V3 原型资产。
