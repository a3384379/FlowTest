# FlowTest 开发进度

最后更新：2026-08-12（Asia/Shanghai）
状态：V3 S24 已合并；S25 Draft PR #28 已完成实现、本地全量验收和远端缺陷修复，2026-08-12 再次重跑的 CI 仍受 GitHub Actions 账户计费阻断。`v2.0.0` 正式标签仍受真实部署与连续 14 天 RC 观察门槛约束。

## 当前恢复点

- 当前基线：`main@bad2b51`，S24 Draft PR #27 的 5 项 CI 全绿后已 squash 合并。
- 当前分支：`agent/s25-performance-lab`，Draft PR #28，开发版本 `3.0.0-alpha.1-dev.25`。
- 已发布标签：`v1.1.0`、`v1.5.0`、`v1.8.0`、`v2.0.0-rc.1`、`v3.0.0-alpha.1`；不得提前创建 `v2.0.0` 或后续 V3 里程碑。
- 用户已明确要求跳过原计划中的等待顺序并开启 V3 开发；该授权不等于完成或豁免 V2 正式发布门槛。
- `FlowTest_V3_UI_CN_HD/` 的 HTML 设计源和 21 张 2560×1440 PNG 基准在 S22 纳入 Git，原始内容保持不变。

## 本地验收完成：S25 声明式性能实验室

1. 新增 `PerformanceScenario` 不可变版本、`PerformanceRun`、门禁评价和 `20260812_0022` 增量迁移；
   支持 REST 与纯 HTTP Workflow 目标、固定 VU 和阶梯升压。
2. 固定 `K6ScenarioCompiler` 只接受带类型结构化配置，确定性生成 k6 程序与 SHA-256；拒绝用户脚本，
   关闭重定向并默认丢弃响应体。
3. 新增独立 Celery `performance` 队列和固定 digest 的 k6 2.2.0 Runner；容器以 UID/GID 65532
   非 root 运行，根文件系统只读，移除全部 Capability 并启用 `no-new-privileges`。
4. Runner 执行前重新编译并校验 Snapshot 哈希，再次执行 SSRF/DNS/CIDR 策略；超时、Runner 缺失、
   非法汇总、超限指标和阈值失败均返回稳定错误码；敏感 Header/Query/Body 在进入 Snapshot 前拒绝。
5. 原始 k6 NDJSON 指标以 Artifact 写入 MinIO，P95、失败率、请求率和计数写入 PostgreSQL；同场景
   上一次成功运行自动成为基线，并把 P95 回归与阈值证据写入现有 Quality Gate。
6. Web 新增中文“性能实验室”深链接，提供声明式场景、发布、运行、基线、阈值、门禁和 Artifact 下钻；
   内部 Compose 主机 URL 与公网 URL 均可在前端校验后交由后端安全策略处理。
7. 后端 262 passed/3 skipped，总覆盖率 90.07%，k6 编译器和进程边界均为 100%；Ruff、mypy strict、
   依赖边界通过。前端 130 项全量测试通过，语句 85.78%、分支 80.15%，生产构建通过。
8. 真实 PostgreSQL 完成 `0021 → 0022 → 0021 → 0022`，`alembic check` 无漂移；演练发现并修复
   PostgreSQL 63 字节约束名截断问题。
9. 真实 ARM64 Compose 两次 k6 验收均通过，第二次固定第一次基线，原始指标进入 MinIO；真实 Chromium
   完成“创建 → 发布 → 独立队列运行 → 阈值与产物下钻”1/1。
10. 本轮共修复五项门槛问题：前端分支覆盖率、PostgreSQL 约束名漂移、歧义 VU 选择器、内部主机 URL
    误拒绝和中文展开按钮选择器；所有对应门槛已重跑通过。
11. Draft PR #28 已创建。第二轮远端 Backend、Integration、Frontend 和 Security 全绿；Compose 已通过
    S3–S25 功能、Kafka 兼容和 API 容量，在 Workflow 容量边界失败，随后完成 CI 抖动容差修复。
12. PR #28 首轮 Security CI 发现 k6 2.1.0 二进制的 `golang.org/x/text` 和 gRPC 高危依赖已有
    上游修复版本；已升级至官方 k6 2.2.0 多架构 digest，不添加漏洞豁免。相同 Grype 0.116.1 高危
    扫描已通过，ARM64 固定编译产物完成真实 HTTP 负载兼容验证。
13. 首轮 Compose 在 S3–S25 全部功能闭环通过后，GitHub 两核共享 Runner 的 300 请求/30 并发容量
    P95 为 1.423 秒、0 失败，超过旧 CI 专用 1.2 秒阈值；保留工作量和零失败规则，将非参考宿主的
    抖动容差校准为 1.8 秒，8C/16G 正式容量基线不变。
14. 修复后 Compose 的 100 个真实 Workflow 全部通过且无丢失，P95 60.069 秒仅超过旧 CI 门槛
    68 毫秒；保留 100 并发与零失败条件，将两核共享宿主的 Workflow P95 抖动容差校准为 75 秒，
    正式参考机的 100/1000 门槛不变。
15. `3438f4a` 推送后的五项 GitHub Actions 均在 3–4 秒内、执行任何步骤前终止；Check Annotation 明确
    指向账户付款失败或 Actions spending limit。该问题需要仓库所有者在 GitHub Billing & plans 处理，
    处理后重跑 PR #28 全部检查；全绿并 squash 合并前不开始 S26。
16. 2026-08-12 14:45（Asia/Shanghai）已对 `9eab87d` 的 Backend `31569796643`、Frontend
    `31569796638`、Security `31569796687` 和 Compose `31569796736` 执行重跑；五个新 Job
    `94033432944`、`94033432935`、`94033432495`、`94033431994`、`94033432684` 均在约 3 秒内失败，
    新 Check Annotation 仍明确提示近期账户付款失败或 Actions spending limit 需要提高，且无任何步骤日志。
    这仍是外部计费阻塞，不是代码失败；PR 保持 Draft，不合并、不开始 S26。

## 已完成：S24 Kafka、WebSocket 与 Exchange

1. 新增不可变 `EventSource`、`20260812_0021` 增量迁移和 `EVENT_PROTOCOLS` Feature Flag，Kafka
   固定 Bootstrap/Registry，WebSocket 固定 URL，配置 SHA-256 随 Workflow Snapshot 保存。
2. 新增 Avro、JSON Schema 2020-12、Protobuf 消息 Schema 与兼容 Registry 导入；编码/解码支持
   Confluent Wire Format，并拒绝 Schema ID 不匹配、损坏消息和超过 4 MB 的负载。
3. 新增 `kafka.produce/consume` 与 `websocket.connect/send/await/close/exchange` 七个 Capability；
   REST 输出可结构化绑定到 Kafka 消息/Correlation 和 WebSocket 消息，Endpoint/Topic/Schema 不可动态改变。
4. Kafka 使用 `confluent-kafka`，禁用 Admin、Topic 自动创建、自动提交和 Offset Store；Consume 最多
   1000 条/300 秒，Correlation 命中立即返回。WebSocket Session 固定在单次 Runner，结束无条件清理，
   连接丢失统一返回 `SESSION_LOST`。
5. 中文多协议工作台新增 Kafka Registry、Produce/Consume、WebSocket Exchange、事件源版本和 Context
   Inspector；React Flow 支持创建和配置三个常用事件节点。
6. Compose 新增固定 digest 的 Redpanda `v26.2.1`、Schema Registry 与 WebSocket Echo Mock；CI 另用
   固定 digest 的 Apache Kafka `4.3.1` 验证稳定客户端兼容性。
7. `smoke_s24.py` 已在真实 Compose 完成 Registry 导入、调试、REST→Kafka/WebSocket 混合 Workflow、
   结构化绑定及事件源/Schema Snapshot 校验；真实 Chromium 主路径 2/2 通过。
8. 后端 236 passed/3 skipped，总覆盖率 90.11%，事件运行时 95%；Ruff、mypy strict 和依赖边界通过。
   前端全量覆盖率 Statements 85.58%、Branches 80.35%、Functions 83.27%、Lines 87.75%，生产构建通过。
9. 冒烟过程中发现并修复 Kafka 命中 Correlation 后仍等待完整超时，以及纯消息 Protobuf 被错误要求
   包含 gRPC Service、损坏 Avro 泄漏底层异常三项真实缺陷。
10. 真实 PostgreSQL 已完成 `0020 → 0021 → 0020 → 0021` 和 `alembic check`；首次演练发现并修复
    Kafka Schema 阻断旧约束恢复的 downgrade 顺序缺陷。Python 与前端生产依赖审计无已知漏洞。
11. 固定 digest Apache Kafka `4.3.1` 兼容验证、Draft PR #27 的 5 项远程 CI 均通过，随后 squash
    合并至 `main@bad2b51`。

## 已完成：S23 GraphQL、gRPC 与多协议工作台

1. 新增不可变 `SchemaArtifact` 与 `20260812_0020` 增量迁移，支持 GraphQL SDL/Introspection、
   Proto/Protoset 和受 SSRF 策略约束的 gRPC Server Reflection；同内容按 SHA-256 去重。
2. 新增 `graphql.request@3.0.0` 与 `grpc.call@3.0.0` Capability，GraphQL 支持 Query/Mutation，gRPC
   支持 Unary/Server Streaming、TLS/mTLS，明确拒绝 Subscription、Client/Bidi Streaming 和超限消息。
3. Workflow 发布与加密执行计划固定 Schema/Descriptor ID、版本、哈希和规范内容；mTLS Credential
   只写、加密且绑定目标，公开 Snapshot 只保存 Credential ID。
4. 结构化绑定只允许 REST/上游输出写入 GraphQL `variables.*` 或 gRPC `request.*`，不能动态改变
   Endpoint、方法、TLS 或 Credential。
5. Web 新增中文“多协议工作台”，提供版本清单、导入、GraphQL/gRPC 真实调试、Context Inspector；
   React Flow 可创建和配置协议节点、mTLS 与结构化绑定。
6. Compose 新增确定性 GraphQL 与带 Reflection 的 gRPC 目标服务；`smoke_s23.py` 覆盖导入、调试、
   REST→GraphQL/gRPC 并行绑定及 Snapshot 固定，Playwright 覆盖真实中文工作台主路径。
7. 后端 Ruff、mypy strict、依赖边界和 236 passed/3 skipped 通过，总覆盖率 90.53%；
   `protocol_nodes.py` 96%，`protocol_runtime.py` 95%。Python 与前端生产依赖审计无已知漏洞。
8. 前端格式、Lint、TypeScript、118 项 Vitest 与生产构建通过；Statements 85.35%、
   Branches 80.01%、Functions 83.17%、Lines 87.46%，多协议工作台 Branches 92%。
9. 真实 PostgreSQL 已完成 `0019 → 0020 → 0019 → 0020`，`alembic check` 无漂移；运行中
   应用会持有 DDL 锁，因此回滚演练明确要求维护窗口内停止 API/Worker。
10. Compose 全栈健康，S3–S11、S18、S19、S21–S23 共 14 个真实冒烟链路通过；
    Playwright 在重复数据卷上 10/10 通过，并修复 S14 异步保存、S15 资产前置与 S21 名称冲突的测试隔离问题。
11. Draft PR #26 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images
    和 Compose Smoke 全绿后已 squash 合并，并创建 `v3.0.0-alpha.1`。

## 已完成：S22 Capability SDK V3

1. 已建立不可变 `CapabilityManifest`、12 个 V2 内置 Manifest、Legacy Adapter、显式 Capability
   节点契约和 Schema SHA-256；旧 Workflow 不修改存量数据。
2. 调度器统一生成 `NodeResult`，节点执行记录保留兼容字段并新增脱敏结果包；纯引擎层
   `ExecutionEvent` 增加单调序号、Attempt 与 Fencing Token 契约。
3. 已定义 Runner Control Plane 类型接口，新增 Plugin、Capability、Runner Pool、Runner 增量模型与
   `20260812_0019` 双向迁移；分布式 Lease 的 PostgreSQL 事实源保留至 S29。
4. Plugin Manifest 校验固定 OCI Digest、签名身份、能力所有权、禁网声明和容器加固开关；安装入口
   在 Cosign 与隔离 Runner 完成前保持关闭。
5. 新增 `/api/v1/v3/features`、`capabilities`、`plugins`、`runner-pools` 和 Manifest 校验接口；
   三个 Feature Flag 默认关闭，Compose 验收只开启 Capability SDK。
6. 前端新增中文“能力与插件中心”深链接、真实能力清单、Plugin/Runner 管理员边界和右侧
   Context Inspector；采用 `#5b5cf0` / `#101936` V3 Token。
7. 当前本地证据：后端 214 passed、3 skipped、覆盖率 90.85%，Ruff/mypy 通过；前端 104 项通过，
   Statements 85.01%、Branches 80.70%、Functions 82.84%、Lines 87.04%，格式/Lint/TypeScript/构建通过。
8. `0018 → 0019 → 0018 → 0019` 已在隔离真实 PostgreSQL 完成，`alembic check` 无漂移；现有 V2
   Compose 数据原地升级至 `0019`，API、Web、PostgreSQL、Redis、MinIO、General/Data/AI Worker 与 Beat 健康。
9. S22 冒烟完成 Legacy Start/End 与显式 `flow.delay@2.0.0` 混合执行，验证 Capability 版本、Schema
   哈希和 NodeResult 固定入 Snapshot；Playwright 登录、平台深链接、能力/插件/Runner 边界 2/2 通过。
10. 单 Worker 与四 Worker 均完成 100 个真实 Workflow、请求侧并发 100、零失败容量基线；分别为
    P95 3.442 秒/27.44 execution/s 与 P95 3.100 秒/31.47 execution/s，测试后恢复单 Worker。
11. 全量回归曾发现 5 项失败均源于 `skipped` NodeResult 原因码被误判为非法错误；契约调整为
    `passed` 禁止错误、`failed` 必须有错误、`skipped/cancelled` 可携带解释原因，5 项回归现全部通过。
12. Draft PR #25 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images 和
    Compose Smoke 共 5 项全部通过，随后 squash 合并至 `main@3eac7ec`。

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

1. 仓库所有者先在 GitHub Billing & plans 处理付款或 Actions spending limit；恢复后重跑 PR #28 的
   Backend Test、Backend Integration、Frontend Build、Security Source/Images 和 Compose Smoke。
   只有五项全部真实通过后才将 PR 标记 Ready、squash 合并并开始 S26。
2. V3 开发期间并行推进 `v2.0.0-rc.1` 的真实试点部署与连续 14 个自然日观察；代码变更不得冒充观察天数。
3. 未通过 S25 退出门槛不开始 S26；只有 V2 RC 签署、恢复演练、扫描和容量证据全部通过后创建
   `v2.0.0` 正式标签。
