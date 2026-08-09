# FlowTest

FlowTest 是一个基于 Python 的可视化接口自动化测试平台，目标是打通 API 资产管理、单接口调试、可视化工作流、异步执行、测试计划与报告。

当前状态：`V0.1 单接口闭环`。

## 技术栈

- 后端：Python 3.12、FastAPI、Pydantic、SQLAlchemy、HTTPX
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

领域边界及完整目录说明见 [docs/architecture.md](docs/architecture.md)，实施节奏见 [docs/development-plan.md](docs/development-plan.md)。

## 本地启动

推荐安装：Python 3.12、Node.js 20.19+ 或 22.12+、Docker。

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

全栈启动后可运行 `backend/.venv/bin/python scripts/smoke_s3.py`，自动验收登录、项目、
环境、API 请求、六类断言、执行历史和敏感请求体脱敏。脚本会注销测试会话；创建的验收项目
保留供人工查看，在一次性 CI 卷中会随 Compose 环境销毁。

不使用 Docker 时可分别进入 `backend` 和 `frontend`，按照各自 README 启动。前端统一使用 pnpm，并提交 `pnpm-lock.yaml` 保证依赖可复现。

## 开发原则

- 先纵向打通业务闭环，再扩展页面和节点类型。
- 工作流版本、执行快照、变量作用域和字段映射从第一版建模。
- 控制平面与执行平面保持逻辑隔离，早期可同进程部署。
- 第一版不允许执行任意用户 Python 代码。
