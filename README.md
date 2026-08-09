# FlowTest

FlowTest 是一个基于 Python 的可视化接口自动化测试平台，目标是打通 API 资产管理、单接口调试、可视化工作流、异步执行、测试计划与报告。

当前状态：`V2.0 路线 S16 高级 Workflow 已完成`；S12 真实两周试点仍按观察窗口持续记录。

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
[docs/development-plan.md](docs/development-plan.md)。

## 本地启动

推荐安装：Python 3.13、Node.js 20.19+ 或 22.12+、Docker。

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
- MinIO Console：<http://localhost:9001>

本地初始管理员为 `admin@flowtest.dev`，密码由
`FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD` 配置。首次登录后必须修改密码；生产部署不得沿用示例值。

S1 已提供 `/api/v1/auth`、`/api/v1/users`、`/api/v1/projects`、项目成员和任意层级目录接口。
Refresh Token 仅通过 HttpOnly Cookie 轮换，Access Token 有效期默认 15 分钟。

S2 已提供项目变量/Header、环境、AES-256-GCM Secret、API Definition/不可变版本和请求预览。
Secret 只允许写入，列表与详情不返回明文、密文或 nonce；生产部署必须替换
`FLOWTEST_DATA_ENCRYPTION_KEY`，并安全备份该密钥。

S3 已提供 HTTPX 异步执行、GET/POST/PUT/PATCH/DELETE、响应与耗时查看、状态码、
响应时间、Header、JSONPath、JMESPath、JSON Schema 断言和执行历史。Web 管理端可完成
“创建项目与环境 → 创建 API → 发送请求 → 查看断言与历史”闭环；请求与响应中的认证信息、
Cookie、Token、Password 和 Secret 会在持久化及展示前统一脱敏。

S4 已提供 OpenAPI 3、Swagger 2、Postman Collection 导入和指纹去重；重导入返回
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

执行全部本地质量门槛使用 `./scripts/check.sh`。

Compose 冒烟产生 S11 验收数据后，可执行可重复的 Playwright 中文 Web 验收：

```bash
pnpm --dir frontend e2e:setup
pnpm --dir frontend e2e
```

不使用 Docker 时可分别进入 `backend` 和 `frontend`，按照各自 README 启动。前端统一使用 pnpm，并提交 `pnpm-lock.yaml` 保证依赖可复现。

## 开发原则

- 先纵向打通业务闭环，再扩展页面和节点类型。
- 工作流版本、执行快照、变量作用域和字段映射从第一版建模。
- 控制平面与执行平面保持逻辑隔离，早期可同进程部署。
- 第一版不允许执行任意用户 Python 代码。
