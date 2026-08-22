# FlowTest

FlowTest 是一个基于 Python 的可视化接口自动化测试平台，目标是打通 API 资产管理、单接口调试、可视化工作流、异步执行、测试计划与报告。

当前状态：`V3.0 S30/S31 已完成；V4 S32～S36 的 Compact 六服务、离线分发、事务式无外网升级、资源/兼容基线、隐私安全诊断与回滚证明已通过本地及 PR #38 远程自动化验收；S37 Standalone 无 Docker 运行时已通过 PR #39 七项远程检查`；Windows 云桌面 72 小时试点、Standalone→Compact 真实迁移和人工签署待执行。V5 设计草案见 [docs/development-plan-v5.md](docs/development-plan-v5.md)，不改变 V4 发布门槛。

## 技术栈

- 后端：Python 3.13、FastAPI、Pydantic、SQLAlchemy、HTTPX、Celery/Beat
- 前端：React 19、TypeScript、Vite、Ant Design、React Flow
- 数据：PostgreSQL、Redis、MinIO/S3
- 部署：Docker Compose、Nginx

## 目录

```text
FlowTest/
├── backend/            # Python API 与执行引擎
├── frontend/           # Web 管理端与流程设计器
├── docs/               # 架构、迭代计划、设计决策
├── scripts/            # 本地开发和质量检查脚本
├── .github/            # CI 与协作模板
└── compose.yaml        # 本地依赖和应用编排
```

领域边界及完整目录说明见 [docs/architecture.md](docs/architecture.md)，V1/V2 实施节奏见
[docs/development-plan.md](docs/development-plan.md)；V5 设计草案见
[docs/development-plan-v5.md](docs/development-plan-v5.md)。

## 公司电脑快速运行

如果公司 Windows 10 云桌面没有 WSL2、SLAT 或 Docker Desktop 条件，请使用
[Standalone Windows 云桌面部署](docs/operations/standalone-company-quickstart.md)。该离线包把 Python
运行时、依赖 wheels 和前端静态文件一起带入，云桌面不需要安装 Docker、WSL2、Node.js、uv、PostgreSQL、
Redis 或 MinIO；解压后在 PowerShell 执行 `deploy\standalone\start.ps1` 和 `verify.ps1` 即可。

公司内网试用优先使用 V4 Compact 档位。联网电脑安装 Docker Engine/Desktop、Compose v2、
Git、OpenSSL 和 Curl 后，可直接从 GitHub 下载并启动：

```bash
git clone --branch main --single-branch https://github.com/a3384379/FlowTest.git
cd FlowTest
./deploy/compact/start.sh
./deploy/compact/verify.sh
```

首次启动会构建或下载镜像，并在 `deploy/compact/.env` 生成权限为 `0600` 的随机管理员密码和服务密钥；
该文件已被 Git 忽略，不得提交、上传或发到聊天/工单。启动完成后访问 <http://localhost:3000>，
管理员可使用 `admin@flowtest.dev` 或账号别名 `admin` 登录。Windows 公司电脑请在 WSL2 中执行上述命令，并启用 Docker Desktop
的 WSL 集成。

详细的系统要求、首次登录、启停、内网开放、备份、升级及完全离线安装步骤见
[公司电脑 Compact 快速部署](docs/operations/compact-company-quickstart.md)。GitHub 源码压缩包不包含
Docker 镜像；完全无外网电脑必须使用受信工作站生成并校验的单架构离线包。成功的 Compact CI
会短期保留已经完成冷导入、业务、升级回滚和兼容验收的 `amd64` 候选包，供公司试点下载；该候选
不是正式 Release，仍须固定 Commit、校验 SHA-256 并完成公司审批。

## 本地开发启动

推荐安装：Python 3.13、Node.js 20.19+ 或 22.12+、Docker。

Compact 只启动 6 个容器并自动生成随机密钥：

```bash
./deploy/compact/start.sh
```

完整边界和内网开放方式见 [小型化部署手册](deploy/compact/README.md)。需要全部 Worker、Redpanda、
Mock、性能实验室和环境实验室时，继续使用下方 Full 开发栈。

```bash
cp .env.example .env
docker compose up --build
```

启动后：

- Web：<http://localhost:3000>
- API：<http://localhost:8000>
- OpenAPI：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/v1/health>
- Readiness：<http://localhost:8000/api/v1/ready>
- Mock 目标服务：<http://localhost:8080/docs>
- gRPC/Reflection 目标服务：`localhost:50051`
- MinIO Console：<http://localhost:9001>

登录账号字段同时接受管理员邮箱和 `admin` 别名；别名会解析到
`FLOWTEST_BOOTSTRAP_ADMIN_EMAIL`。Full/Compact 的密码由 `FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD` 配置，
并按安装档位执行首次改密策略；Standalone 新包固定使用 `admin/admin` 且不强制首次改密。所有新建或
主动修改的密码最低为 8 位；生产部署不得沿用示例值。

S1 已提供 `/api/v1/auth`、`/api/v1/users`、`/api/v1/projects`、项目成员和任意层级目录接口。
Refresh Token 仅通过 HttpOnly Cookie 轮换，Access Token 有效期默认 15 分钟。

S2 已提供项目变量/Header、环境、AES-256-GCM Secret、API Definition/不可变版本和请求预览。
Secret 只允许写入，列表与详情不返回明文、密文或 nonce；生产部署必须替换
`FLOWTEST_DATA_ENCRYPTION_KEY`，并安全备份该密钥。

S3 已提供 HTTPX 异步执行、GET/POST/PUT/PATCH/DELETE、响应与耗时查看、状态码、
响应时间、Header、JSONPath、JMESPath、JSON Schema 断言和执行历史。Web 管理端可完成
“创建项目与环境 → 创建 API → 发送请求 → 查看断言与历史”闭环；请求与响应中的认证信息、
Cookie、Token、Password 和 Secret 会在持久化及展示前统一脱敏。

S4 已提供 OpenAPI 3、Swagger 2、Postman Collection 导入和指纹去重；URL 导入可从
Swagger UI、Springdoc、FastAPI 和 Knife4j 页面发现原始文档，并在多分组时先行选择。重导入返回
`added/changed/deleted/unchanged`，变更接口自动创建不可变新版本，删除项只预览不自动停用。
Bearer、Basic 和 Header/Query API Key 已接入真实请求执行。上传文件和二进制响应统一存放于
MinIO，数据库只保留 Artifact 元数据与 SHA-256；支持 multipart 请求、受权下载、文件大小、
文件哈希和 Content-Type 断言。Web 管理端提供中文导入 Diff、文件仓库和认证/文件请求配置。

S5 已提供 Workflow 草稿、乐观并发修订号、不可变发布版本和 Execution Snapshot；发布前校验
Start/End、循环、不可达节点、悬空路径、节点配置及项目内 API 引用。独立异步 DAG 调度器支持
依赖就绪并行、默认 fail-fast、失败传播、1～300 秒超时、网络错误/5xx 分类重试和持久化取消。
每次执行固定 Workflow、API 与 Environment 版本，后续草稿、API 或环境修改不会改变历史快照。
Web 管理端已开放流程草稿编辑、发布、运行和节点结果/历史查看。

S6 已将 Workflow 编辑升级为 React Flow 画布，支持 Start/API/End 节点、拖拽、
连线、节点属性配置、草稿保存、发布和运行。工作流执行接口现在返回
`202 Accepted`，后台协调器按固定 Snapshot 执行；节点状态通过 Redis Pub/Sub 和
`/api/v1/executions/{id}/events` WebSocket 实时推送。WebSocket 使用访问令牌子协议认证，
Redis 保留短期序列化事件用于连接后回放，前端同时使用轻量轮询保证最终一致。

S7 已提供 Extract、Assert、Condition、Delay 和 Dataset 节点；字段映射使用稳定节点 ID、
JMESPath 源路径和 Query/Header/Body/Variable 目标位置。条件节点固定为一条 true 和一条 false
出边，未选择分支记为 `skipped/BRANCH_NOT_SELECTED`，汇合节点只等待激活分支。CSV、JSON、
Excel 数据集固定到执行 Snapshot，每行生成一个可下钻子执行，默认并发 5、最多 1000 行；
父执行聚合行级状态，Execution Context 保留 Workflow/Dataset/Runtime 变量值与来源。

S8 已将执行平面迁移到 Celery Worker：API 只持久化 AES-256-GCM 加密运行计划并发送执行 ID，
Worker 通过 `asyncio.Runner` 恢复固定快照后调用独立异步执行引擎。Test Plan 支持批量执行、
失败重试、取消传播和 Celery Beat 定时间隔；每次运行复制固定 Workflow Version、Environment 和
Runtime 配置。项目 Owner 可创建只显示一次、只保存摘要的 CI Token，并限制
`execute:workflow`/`execute:test-plan` 范围；签名 Webhook 使用五分钟时间窗拒绝过期请求。
Web 管理端新增“任务执行”页面，用于创建计划、查看队列、取消和生成外部触发凭据。

S9 已提供统一执行中心、步骤级报告、稳定失败分类和最近 7～90 日趋势。报告从不可变执行快照、
脱敏节点输出和变量来源实时派生，可下钻请求/响应、提取、断言、映射轨迹及数据集子执行；HTML
导出作为 `report` Artifact 存入 MinIO。项目 Owner 可配置通用通知 Webhook，Secret 仅显示一次并
使用 AES-256-GCM 保存；Worker 在工作流或测试计划完成后发送 `timestamp.body` HMAC-SHA256 签名
消息，投递 HTTP 状态与错误可在报告页查询。

S10 已固定 System Admin、Project Owner、Editor、Viewer 四级权限，并在项目治理页展示有效能力、
出站安全策略和带 Trace ID 的脱敏审计记录。OpenAPI/Postman 重导入先生成只读 Diff，再按选择进行
Merge；删除项只有明确选中才停用。API 调试、Workflow 与通知 Webhook 统一在 DNS 解析后执行
域名/CIDR 校验，拒绝元数据、回环和未授权私网地址。执行入口统一支持 `Idempotency-Key`，登录、
执行与普通写请求分别使用 Redis 限流桶。

V4.0 轻量版新增项目级出站策略开关：Standalone 新项目默认关闭，允许本机 `localhost`/私网调试；
开启后恢复严格的域名、CIDR、回环、元数据和保留地址校验。导入文档选择器、导入 Diff 和接口列表均使用
固定高度滚动区域；接口列表支持名称/路径/说明搜索、HTTP 方法筛选和服务端分页。该策略也会随 Runner
Lease 传递到远程工作节点，避免不同执行面出现安全语义不一致。

S11 已提供项目级 1～3650 天保留策略和每日 90 天清理任务、Prometheus 指标、Compose 资源限制、
Nginx TLS 接入模板、Critical/High 镜像漏洞门槛、容量测试以及 PostgreSQL/MinIO 备份恢复工具。
V1.0 验收链路覆盖“登录 → 提取令牌 → 并行查询用户/创建订单 → 断言 → 脱敏报告”，并验证失败、
超时、重试、取消、并行、Viewer 拒绝和清理行为。部署、升级、回滚、监控和恢复说明位于
[`docs/operations`](docs/operations)。

S12–S14 已将运行基线升级到 Python 3.13，并提供 V2 Feature Flags、真实 Workflow 容量基线、
React Router 项目深链接和真实 Dashboard。单组织团队模型支持成员与项目 Editor/Viewer 授权，
直接项目成员权限优先于团队授权。Web 项目治理页可管理用户、团队、目录、环境、变量、Header 和
只写 Secret；API 工作台可持续编辑 Params、Headers、Auth、Body、提取和断言并保存不可变版本。
导入导出已扩展至 HAR、cURL、Bruno 和 Excel，认证信息始终使用 Secret 引用或脱敏占位。

S15 已提供 Test Case 与 Test Suite 的可修改草稿、不可变发布版本、标签/搜索、模板、克隆、
批量目录移动和结构化版本 Diff。发布 Case 时固定 Workflow Version 与 Environment；发布 Suite
时固定每个 Case Version。Test Plan 继续兼容 V1 `workflow_id` 输入，同时可选择 Workflow、Case
或 Suite；创建计划即固定目标版本，入队时将 Suite 展开为固定 Case Snapshot，之后修改或重新发布
资产不会改变历史运行。Web“测试资产”页面和 Playwright 验收覆盖两次发布、Diff、克隆、套件发布
及固定套件计划闭环。

S16 已提供框架无关的 Node SDK V2、固定发布版本的 SubFlow、并发受控的 ForEach 和安全 JMESPath
表达式。发布阶段会阻止跨流程递归、超过 5 层的嵌套、无效引用和超过资源边界的配置；执行计划递归
固定子流程、API 与环境快照，历史执行不回读新版本。Web 画布支持子流程/循环配置、复制粘贴、
50 步撤销重做和自动布局，并提供版本 Diff、运行至断点和基于原执行快照的节点重放。当前明确拒绝
把含 Dataset 节点的 Workflow 作为 SubFlow，避免产生未定义的嵌套父子执行语义。

S17 已提供项目级加密 Credential、PostgreSQL/MySQL 单条只读 SQL 节点和 Redis 白名单读取节点。
发布时会校验 Credential 类型与只读语法，执行计划固定加密 Credential 材料，公开 Snapshot 和报告
不保存 Secret；数据库、缓存目标通过域名、DNS、私网 CIDR 及连接后实际对端地址校验。规则化 Mock 支持 Method、
路径、Query/Header 条件、场景、状态码、延迟和安全 JSON 模板，不执行任意脚本；公开调度统一限流，请求日志脱敏并
纳入项目保留策略。Web“数据与 Mock”页面和 React Flow 属性面板可完成配置与只读节点编排。

S22 已提供 Capability SDK V3、全部 V2 节点的 Legacy Adapter、统一 NodeResult/ExecutionEvent、
Runner/Plugin 安全契约以及 V3 中文设计基线。S23 在此基础上提供 GraphQL SDL/Introspection 与
Query/Mutation、gRPC Proto/Protoset/Reflection 与 Unary/Server Streaming、TLS/mTLS Credential、
不可变协议 Snapshot 和 REST→GraphQL/gRPC 结构化绑定。Web“多协议工作台”可完成导入、调试与
版本审阅；协议节点可直接加入 React Flow 工作流。架构边界见
[`ADR 0019`](docs/adr/0019-multi-protocol-schema-snapshots.md)。

S24 新增不可变 Kafka/WebSocket 事件源、Avro/JSON Schema/Protobuf 消息 Schema、兼容 Schema
Registry 导入，以及 Kafka Produce/Consume 和 WebSocket Connect/Send/Await/Close/Exchange
Capability。Kafka 客户端禁用 Admin、自动 Topic 创建和 Offset 自动提交，消费与 WebSocket 等待均有
条数和时间上限；Workflow Snapshot 固定事件源与消息 Schema 哈希。Compose 使用 Redpanda
`v26.2.1`，CI 额外验证 Apache Kafka `4.3.1`。架构边界见
[`ADR 0020`](docs/adr/0020-event-protocols-and-session-boundary.md)。

S25 新增声明式 Performance Scenario、不可变发布版本、独立 `performance` 队列和固定 digest 的
k6 Runner。平台只编译结构化的固定 VU/阶梯升压、HTTP 步骤与 Threshold，不接收用户 JavaScript；
运行前重新校验 Snapshot 哈希及项目 SSRF 白名单。聚合指标、阈值结果和 P95 回归写入 PostgreSQL，
原始 NDJSON 指标写入 MinIO，并与现有 Quality Gate 形成发布证据。Web“性能实验室”支持场景创建、
发布、运行、基线和门禁下钻。架构边界见
[`ADR 0021`](docs/adr/0021-declarative-performance-runner.md)。

S26 新增管理员注册、平台签名、不可变版本化的 Environment Template，以及独立 `environment` 队列。
模板只允许白名单中的固定 Digest 镜像、类型化 Health Check、资源上限、TTL 和预定义 Seed，不接收
任意 Compose、命令、脚本、Secret、设备或卷。Environment Worker 不挂载宿主 Docker Socket，而是通过
内部 Control Network 使用不对宿主发布端口的独立 daemon；固定 Docker CLI 参数强制非 root、只读、
无 Capability 和资源隔离。实例以 Idempotency-Key、Fencing Token、Label、TTL 和 Reconciler 保证失败、
超时、取消、消息重投及 Runner 重启后可幂等清理。Web“环境实验室”展示模板版本、端点、Seed/隔离证据
和 Cleanup 状态。架构边界见 [`ADR 0022`](docs/adr/0022-signed-environment-runner.md)。

S27 新增服务目录、不可变 Pact 版本、可选固定 Pact Broker、Provider 验证、服务依赖图和
部署兼容矩阵。契约中心统一展示 OpenAPI 与 Consumer-Driven Contract，只有指定 Provider
版本的 Pact 验证和 OpenAPI 破坏性证据都通过时才记录“可安全发布”。Pact 仅支持有界 HTTP
Exact Matcher，不执行用户 Matching Rule、Generator、Plugin 或脚本。架构边界见
[`ADR 0023`](docs/adr/0023-pact-contract-hub-and-release-evidence.md)。
S31 产品化阶段将服务目录从契约中心拆分为独立项目路由和导航入口，展示真实协议类型、上下游角色、
依赖数量及契约统计；全局搜索直接返回带稳定资产 ID 的服务目录深链。Contract Hub 未启用时保留
稳定路由但不读取目录 API，Viewer 只读，Credential 与 Secret 不进入目录或搜索结果。
质量总览同步升级为“质量指挥中心”：全局视图汇总授权范围内的真实资产和执行趋势；项目视图按
Feature Flag 读取最新 Release Risk、Impact、Flaky 与不可变 Release Decision，并提供质量洞察、
影响分析和发布门禁深链。首页不重算历史发布判断，也不自动执行推荐测试。

S28 新增 Git Unified Diff、OpenAPI、GraphQL SDL 与 gRPC Proto 四类有界变更解析、项目级显式
Asset Mapping、Change→Impacted→Recommended 影响图、确定性 Test Selection 和 Coverage Matrix。
平台不访问外部 Git、不接收仓库凭据或脚本；`explicit_mapping_v1` 只按已登记证据选择并解释测试，
未匹配项明确列为 Gap。Impact Run、选择结果、覆盖快照与 Fingerprint 均持久化。Web“变更影响分析”
提供 Mapping、四类 Diff、三列图、原因、矩阵与历史。架构边界见
[`ADR 0024`](docs/adr/0024-change-impact-and-deterministic-selection.md)。

全栈启动后可运行 `backend/.venv/bin/python scripts/smoke_s3.py`，自动验收登录、项目、
环境、API 请求、六类断言、执行历史和敏感请求体脱敏。脚本会注销测试会话；创建的验收项目
保留供人工查看，在一次性 CI 卷中会随 Compose 环境销毁。

运行 `backend/.venv/bin/python scripts/smoke_s4.py` 可继续验收重复导入去重、Secret Bearer、
multipart 上传、二进制响应外置、文件断言和受权下载。macOS 自带 Python 版本过旧时可改用
`uv run --project backend python scripts/smoke_s4.py`。

运行 `uv run --project backend python scripts/smoke_s5.py` 可验收不可变发布、DAG 执行、API
版本快照、5xx 重试和跨请求取消。脚本默认复用 Compose Mock 服务并保持所有敏感值脱敏。

运行 `uv run --project backend python scripts/smoke_s6.py` 可验收后台启动语义、节点结果持久化和
`Start → A → B/C → D → End` 的依赖就绪并行；验收会直接比较 B/C 执行时间区间是否重叠。

运行 `uv run --project backend python scripts/smoke_s7.py` 可验收 JSON 数据集父子执行、字段映射、
提取、断言、真假条件分支、跳过原因、汇合语义和变量来源追踪。

运行 `uv run --project backend python scripts/smoke_s8.py` 可验收真实 Celery Worker 执行、双工作流
测试计划、CI Token、签名 Webhook、Beat 调度配置和跨 Worker 取消传播。

运行 `uv run --project backend python scripts/smoke_s9.py` 可验收失败分类、执行下钻、趋势聚合、
MinIO HTML 报告和 Worker 到 Mock 接收器的签名通知，并重新计算 HMAC 验证请求完整性。

运行 `uv run --project backend python scripts/smoke_s10.py` 可验收固定权限、出站白名单、Import
Diff/Merge、删除停用、执行幂等、SSRF 拦截、Secret 不可读和带 Trace ID 的审计链路。

运行 `uv run --project backend python scripts/smoke_s11.py` 可验收 V1.0 Mock 业务链路、失败分类、
超时、重试、并行、取消、Viewer 权限、Token 持久化脱敏、指标和保留清理。容量与恢复门槛分别为：

```bash
uv run --project backend python scripts/capacity_s11.py
uv run --project backend python scripts/capacity_workflow.py
scripts/backup.sh /absolute/path/to/backup
scripts/verify_restore.sh /absolute/path/to/backup
```

运行 `uv run --project backend python scripts/smoke_s25.py` 可在 Compose 中执行两次真实 k6 场景，
验证独立队列、阈值、MinIO 原始指标、自动基线和 Quality Gate 证据。

启用 `FLOWTEST_FEATURE_ENVIRONMENT_LAB_ENABLED=true` 并将固定 Digest fixture 写入
`FLOWTEST_ENVIRONMENT_IMAGE_ALLOWLIST` 后，运行
`uv run --project backend python scripts/smoke_s26.py` 可验证管理员签名模板、版本、独立队列
Provision、Health、Seed、TTL 证据与重复 Cleanup；设置 `FLOWTEST_S26_RESTART_WORKER=1` 时还会验证
Environment Worker 停止、队列清理和恢复后的幂等回收。

启用 `FLOWTEST_FEATURE_CONTRACT_HUB_ENABLED=true` 后，运行
`uv run --project backend python scripts/smoke_s27.py` 可在 Compose 中验证 Pact 导入、真实 Provider
请求、Exact Matcher 失败证据、OpenAPI 绑定、兼容矩阵与 safe/unsafe 发布判断。

启用 `FLOWTEST_FEATURE_IMPACT_ENGINE_ENABLED=true` 后，运行
`uv run --project backend python scripts/smoke_s28.py` 可在 Compose 中验证 Git/OpenAPI/GraphQL/Proto
四类 Diff、显式 Mapping、确定性去重、解释边、Coverage Matrix、Gap 与历史证据持久化。

执行全部本地质量门槛使用 `./scripts/check.sh`。

Compose 冒烟产生 S11 验收数据后，可执行可重复的 Playwright 中文 Web 验收：

```bash
pnpm --dir frontend e2e:setup
pnpm --dir frontend e2e
```

全量浏览器验收会为每个隔离场景重新登录；启动验收专用 Compose 栈时应设置
`FLOWTEST_AUTH_RATE_LIMIT_PER_MINUTE=100`。生产默认值仍为 10，不应为测试放宽生产限流。

不使用 Docker 时可分别进入 `backend` 和 `frontend`，按照各自 README 启动。前端统一使用 pnpm，并提交 `pnpm-lock.yaml` 保证依赖可复现。

## 开发原则

- 先纵向打通业务闭环，再扩展页面和节点类型。
- 工作流版本、执行快照、变量作用域和字段映射从第一版建模。
- 控制平面与执行平面保持逻辑隔离，早期可同进程部署。
- 第一版不允许执行任意用户 Python 代码。
