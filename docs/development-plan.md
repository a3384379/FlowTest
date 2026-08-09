# FlowTest 迭代开发计划

## 计划假设

- 以 2 周为一个迭代，单人全职基线为 20～24 周达到内部可用 V1.0；多人可并行但不压缩架构评审和验收。
- 每个迭代交付可演示的纵向能力，禁止先堆齐全部页面再接执行链路。
- P0 顺序：单接口闭环 → API 资产 → Workflow → 计划/执行 → 报告与治理。

## 版本路线

| 迭代 | 版本目标 | 主要交付 | 退出标准 |
|---|---|---|---|
| S0（已完成） | 工程与契约基线 | Monorepo、CI、配置、数据库/Redis、本地编排；评审变量、Header、Workflow Schema、执行状态机 | 一条空应用链路可启动；CI 通过；4 份核心契约形成 ADR |
| S1（已完成） | 身份、项目与目录 | 登录、JWT、用户/角色最小模型；项目 CRUD；任意层级目录；审计框架 | 用户只能访问授权项目；目录可无限层级增删改查 |
| S2（已完成） | API 与环境资产 | API Definition CRUD；Path/Query/Header/Body；环境、变量、Secret；Header 继承预览 | 可在两个环境间切换且正确解析最终请求 |
| S3（已完成） | V0.1 单接口闭环 | HTTPX 异步请求；常用 HTTP 方法；响应查看；状态码/JSONPath/JMESPath/Schema/响应时间断言；执行历史 | 从页面创建 API、发送、断言并回看脱敏请求/响应 |
| S4（已完成） | V0.2 接口资产 | OpenAPI 3 / Swagger 2 导入；Postman Collection 导入；Auth；上传/下载基础断言 | 示例文档稳定导入；重复导入不重复创建；常用认证和文件接口可调试 |
| S5（第 11～12 周） | Workflow 数据模型 | Workflow/Version、Node/Edge、Snapshot；DAG 校验；ExecutionContext；事件模型 | 循环、悬空边、缺失配置可在运行前定位；历史执行绑定不可变快照 |
| S6（第 13～14 周） | 可视化流程最小闭环 | React Flow 画布；Start/API/End 节点；拖拽、连线、保存；DAG 串行/并行执行；状态推送 | 可视化搭建 A→B/C→D 并按依赖并行运行，节点状态实时可见 |
| S7（第 15～16 周） | V0.3 字段映射与控制节点 | Extract、Assert、Condition、Delay；结构化字段绑定；变量来源追踪；失败传播策略 | A 响应字段可视化映射到 B 请求；条件分支、跳过和断言结果可解释 |
| S8（第 17～18 周） | 测试计划与任务系统 | Test Plan；批量/手工执行；Redis 队列和 Worker；重试、取消；定时任务 | API 服务与 Worker 解耦；计划可排队、取消和重试且状态一致 |
| S9（第 19～20 周） | V0.4 报告与执行中心 | 执行中心；步骤级报告；失败分类；趋势；WebSocket；HTML 导出 | 报告可从汇总下钻到脱敏请求/响应、提取和断言；失败可定位到节点 |
| S10（第 21～22 周） | 企业治理 | 项目级 RBAC；审计日志；Import Diff/Merge；CI/Webhook 触发；通知接口 | 权限矩阵通过；导入变更可审阅选择；外部系统可安全触发并查询结果 |
| S11（第 23～24 周） | V1.0 内部发布 | 性能与容量测试；SSRF/Secret/限流加固；备份恢复；部署手册；试点迁移 | 试点项目连续运行 2 周；P0 缺陷清零；回滚、恢复和告警演练通过 |

## 近期可执行 Backlog（S5）

1. 落地 Workflow、草稿、不可变版本、Node 与 Edge 持久化模型。
2. 以现有 Workflow JSON Schema 作为发布校验入口，返回可定位的字段错误。
3. 建立 DAG 循环、悬空边、Start/End 唯一性和节点配置校验。
4. 建立 ExecutionContext 和变量作用域，不把运行时状态写回版本定义。
5. 保存包含 Workflow、API、Environment 与 Dataset 版本的 Execution Snapshot。
6. 实现依赖就绪调度、默认 fail-fast、失败传播、超时、重试和取消状态机。
7. 为历史快照重放、后续草稿修改隔离和并发分支补齐行为测试。

## 版本验收门槛

### V0.1 可演示

- 支持 GET、POST、PUT、PATCH、DELETE。
- 支持 Path、Query、Header、JSON/Form Body 和常用 Auth。
- 环境变量解析可追踪来源，不在日志暴露 Secret。
- 请求、响应、断言与耗时均可回看。

### V0.3 核心差异化

- DAG 校验、串并行调度和失败传播行为确定。
- Workflow Version 与 Execution Snapshot 可重放和审计。
- 字段绑定保存稳定 ID 与结构化路径，而非仅保存变量名。
- 画布、运行日志和后端事件保持一致。

### V1.0 内部可用

- RBAC、审计、SSRF 控制、限流和 Secret 加密通过安全评审。
- 核心执行链路具备单元、集成和端到端回归测试。
- 具备部署、监控、备份、恢复和升级文档。
- 至少一个真实项目完成试点迁移并达到约定稳定性指标。

## 暂缓项

V1.0 前不进入主线：任意 Python/JavaScript 执行、SQL/Redis/Kafka 节点、Mock、性能测试、gRPC、AI 自动生成。它们必须复用稳定的 Node SDK、Context、Snapshot 和报告协议后再引入。
