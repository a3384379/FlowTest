# FlowTest 架构基线

## 1. 架构目标

FlowTest 采用模块化单体起步，在代码边界上区分控制平面与执行平面，待吞吐量和隔离需求明确后再拆分 Worker。

```text
React Web
    │ REST / WebSocket
FastAPI Control Plane
    ├── Project / API / Environment / Workflow / Plan / Report
    ├── PostgreSQL
    └── Redis / Task Queue
              │
        Execution Plane
        HTTPX + asyncio + DAG
              │
          Target APIs
```

## 2. 仓库结构

```text
backend/app/
├── api/          # HTTP 适配层，不放业务规则
├── core/         # 配置、安全、数据库、日志
├── domain/       # 领域实体、值对象和规则
├── services/     # 应用用例与事务编排
├── repositories/ # 持久化接口及实现
├── models/       # SQLAlchemy 模型
├── schemas/      # API 输入输出契约
├── engine/       # Context、变量、映射、DAG 与节点执行器
├── http/         # 请求构造、异步客户端、响应解析
├── importers/    # OpenAPI / Swagger / Postman
├── assertions/   # 断言库
└── extractors/   # JSONPath / JMESPath / Header 等提取器

frontend/src/
├── pages/        # 路由页面
├── features/     # 领域功能
├── components/   # 跨功能组件
└── flow/         # 节点、边、画布和运行态
```

## 3. 首批领域边界

- Identity：用户、角色、项目成员。
- Project：项目与任意层级目录。
- API Definition：请求、响应示例、断言配置及版本。
- Environment：环境、变量、Secret 和 Header 继承。
- Workflow：DAG、节点、边、字段映射和版本。
- Execution：Snapshot、Context、节点结果、事件日志。
- Test Plan：流程集合、触发器与调度。
- Report：执行汇总、步骤详情、失败分类和趋势。

## 4. 必须前置冻结的契约

1. 变量作用域与覆盖顺序：Global → Project → Environment → Workflow → Dataset → Runtime。
2. Header 覆盖顺序：System → Project → Environment → Workflow → API → Runtime。
3. Workflow JSON Schema：节点、边、条件、结构化字段映射。
4. Execution Snapshot：工作流版本、API 版本、环境和数据集版本。
5. 节点状态机：pending、running、passed、failed、skipped、cancelled。
6. 错误传播、超时、重试、并发和取消语义。

## 5. 安全基线

- Secret 加密存储，日志和报告默认脱敏。
- 目标 URL 执行 SSRF 校验并限制内网/元数据地址策略。
- 请求、响应、上传、下载、超时与并发均设置上限。
- 第一版只提供安全函数 DSL，不运行任意用户脚本。
- 生产环境运行需要明显标识、权限控制和审计记录。

## 6. 质量策略

- 领域规则和执行引擎以单元测试为主。
- 数据库、Redis、导入器和 HTTP 调用使用集成测试。
- 一条稳定的示例业务流程作为端到端回归基线。
- 工作流 Schema 与 API OpenAPI 契约进入版本控制。
