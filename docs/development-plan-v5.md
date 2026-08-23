# FlowTest V5.0 设计设想（草案）

V5 的前提是 V4 的运行档位和供应链不被破坏：Standalone 继续服务没有 Docker/虚拟化能力的
Windows 云桌面，Compact 继续服务公司单机试用，Full 继续承担完整执行平面。V5 不以“再增加一个
部署方式”为目标，而是把 V4 已验证的边界提升为可扩展的企业运行平台。

## 目标

1. **企业隔离**：在现有单组织模型上增加组织/租户边界、成员目录、项目配额和审计查询，默认拒绝
   跨租户读取、Artifact 访问和执行触发。
2. **可恢复执行**：把当前 Celery/进程内任务统一抽象为幂等 Command + Execution Journal；Compact
   保持单机语义，Full 支持 Worker 重启后安全恢复，Standalone 明确继续使用低并发有界队列。
3. **高可用控制面**：为 PostgreSQL/Redis/MinIO 外部依赖定义 HA 运行契约、优雅 Drain、租约续期和
   版本化 Worker 能力；Kubernetes 只作为可选执行面，不成为公司轻量部署前提。
4. **安全生命周期**：支持数据加密密钥轮换、密钥版本、最小权限服务账号、审计保留策略和脱敏支持
   包；迁移工具必须显式声明数据分类和恢复边界。
5. **可观测产品化**：提供租户/项目级 SLO、容量趋势、失败聚类、升级证据和公开的运行档位契约，
   让公司试点结果可以直接进入发布决策。
6. **扩展生态**：以稳定的 Capability/Plugin SDK、版本化 Schema 和签名包支持内部插件，但禁止
   插件获得任意宿主命令、Secret 明文或 Docker Socket。

## GitHub 开源竞品观察

以下比较以各项目当前公开仓库 README/文档的产品定位为准，不把“功能列表相似”当作实现质量或商业
能力的结论。FlowTest 的机会不是复制一个 API Client，而是把“源码/数据证据 → 可审核的接口流程 →
可恢复执行 → 发布证据”串成一条安全链路。

| 项目 | 已形成的优势 | FlowTest 不应重复造轮子 | V5 的补强/差异化 |
|---|---|---|---|
| [Hoppscotch](https://github.com/hoppscotch/hoppscotch) | 轻量 Web API 开发，多协议、环境、集合、团队协作和同步 | 基础请求调试、集合导入导出、常见协议适配 | 增加“从证据生成可审核流程”、不可变 Snapshot、数据关系断言和公司内网离线边界 |
| [Bruno](https://github.com/usebruno/bruno) | Git-friendly、offline-first、文本集合和 CLI/CI | Git 集合协作、OpenAPI/Collection 转换、CLI 运行体验 | 提供 FlowTest ↔ Bruno/OpenAPI 双向导入；保留数据库准备、清理、跨步骤绑定和审计证据 |
| [Insomnia](https://github.com/Kong/insomnia) | REST/GraphQL/WebSocket/SSE/gRPC 调试、OpenAPI 设计、测试套件、Mock、CLI、本地/Git/云存储 | 多协议调试器和基础 API 设计器 | 把请求提升为有类型的业务流程，固定环境/数据/断言版本，并让 LLM 只生成草稿而不能越权发布 |
| [Keploy](https://github.com/keploy/keploy) | 通过真实流量记录/回放生成测试与 Mock，降低手写测试成本 | 录制 HTTP 流量和回放基础设施 | 将录制结果转为脱敏的 FlowSpec，补齐数据依赖、负面场景、契约校验和人工审核 |
| [Schemathesis](https://github.com/schemathesis/schemathesis) | OpenAPI/GraphQL 属性测试、约束覆盖、模糊测试和 Stateful 场景 | 属性生成、缩减失败样例、JUnit/HAR 报告 | 作为 FlowTest 的“生成/验证节点”，把失败样例回写为可审阅断言和回归流程 |
| [Testkube](https://github.com/kubeshop/testkube) | 测试编排、结果/日志/资源聚合、企业治理以及 MCP/AI 接入，偏 Kubernetes 执行面 | 大规模测试编排、Kubernetes Runner 生态 | 保持 Windows Standalone/Compact 的低门槛；仅在 Full 上接入可选远程 Runner，并复用 FlowTest 数据流程语义 |
| [n8n](https://github.com/n8n-io/n8n) | 通用工作流自动化和内置 MCP，可由 LLM 描述并构建工作流 | 通用节点编排、连接器目录、泛自动化 | 不与通用自动化竞争；专注 API 测试的参数/断言/数据一致性、版本快照、回滚和测试证据 |

因此 V5 的优先级是：先做安全、可解释、可回滚的 MCP 工作流生成，再补录制回放、属性测试、Git
协作和企业治理；不要先做一个“可以执行任意代码的 AI Agent”。

## V5 对外 MCP 产品定义

### 部署和边界

V5 提供一个命名空间为 `flowtest` 的 MCP Server，支持两种连接方式：

- **本地 stdio**：个人电脑或 Standalone 云桌面的 LLM 客户端启动本地 MCP 进程；不要求 Docker、
  WSL2 或额外数据库，MCP 进程只通过 FlowTest 本机 API 访问项目。
- **远程 Streamable HTTP**：Compact/Full 部署一个独立 MCP Gateway（可与 API 同机但建议独立进程），
  通过 OAuth/OIDC 或短期 Bearer Token 访问 FlowTest API；MCP Gateway 不直连 PostgreSQL、Redis、
  MinIO，也不接收数据库密码。

实现应优先使用[官方 Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)，并遵循
[MCP Tools 规范](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/draft/server/tools.mdx)。
SDK 版本必须锁定并经过 FlowTest contract test；不要把协议草案版本直接暴露为生产承诺。

数据库分析由“其他数据库 MCP”提供者完成时，FlowTest 作为 MCP Client 消费经过授权的只读资源/工具
结果，并归一化为 `DataProfile`。FlowTest 不把任意 SQL、数据库 Token 或原始 PII 转发给 LLM；没有
外部数据库 MCP 时，用户也可以上传脱敏 Schema/样本摘要完成同样流程。

### MCP 三类原语

官方 SDK 将 MCP 能力分为模型控制的 Tools、应用控制的 Resources、用户控制的 Prompts。FlowTest
按这个边界设计，避免让模型通过一个巨大工具直接写入或执行系统：

| 原语 | 首批名称 | 作用与副作用 |
|---|---|---|
| Resources | `flowtest://projects/{id}/contract`、`flowtest://projects/{id}/data-profile`、`flowtest://drafts/{id}`、`flowtest://runs/{id}/evidence` | 提供版本化、脱敏、可追溯的接口/数据/草稿/运行证据；只读，按租户和项目授权过滤 |
| Prompts | `discover_api_workflow`、`design_data_case`、`review_flow_draft`、`triage_failure`、`migrate_collection` | 固化操作步骤、输入要求、风险提醒和输出格式；由用户显式选择，不自动触发写操作 |
| Tools（只读） | `flowtest.list_projects`、`flowtest.analyze_source`、`flowtest.inspect_contract`、`flowtest.inspect_data_profile`、`flowtest.validate_flow`、`flowtest.explain_failure` | 读取或分析经过授权的证据；结果必须包含 `evidence_refs`、`confidence`、`redactions` 和 `trace_id` |
| Tools（草稿） | `flowtest.propose_flow`、`flowtest.create_flow_draft`、`flowtest.patch_flow_draft` | 生成/修改不可发布草稿；必须带 `idempotency_key`、`expected_revision` 和 `dry_run=true` 默认值 |
| Tools（审批后） | `flowtest.preview_flow`、`flowtest.publish_flow`、`flowtest.execute_flow` | 只有用户确认的 `approval_id`、环境白名单、预算和幂等键同时满足才可运行；模型不能自行提升权限 |

任何变更工具都返回结构化结果：`draft_id`、`revision`、`status`、`required_approval`、`warnings`、
`evidence_refs`、`trace_id`。`publish_flow`/`execute_flow` 在没有人工批准时返回
`approval_required`，而不是尝试执行。

### 从源码和数据库生成接口流程

典型用户请求：“分析这个仓库和订单数据库，创建订单创建→查询→取消的接口测试流程，并补齐参数和断言。”
MCP 编排器应严格按以下阶段运行：

1. **声明范围**：确认 tenant/project、代码仓库 URL/commit、API 环境、数据库 MCP 连接、目标业务
   场景、是否允许预览执行；没有范围时只返回澄清问题。
2. **源码分析**：`analyze_source` 只读取 allowlist 路径和固定 commit，静态解析 OpenAPI、路由、DTO、
   ORM、迁移、示例和现有测试；禁止执行仓库脚本。输出 endpoint、认证方式、字段来源、错误分支和证据行号。
3. **接口契约分析**：读取 OpenAPI/GraphQL/AsyncAPI（AsyncAPI 可描述 Kafka、MQTT、WebSocket 等
   消息 API，参见[规范](https://github.com/asyncapi/spec)），归一化方法、路径、参数、响应 Schema、
   operationId、状态码和依赖关系。
4. **数据画像分析**：通过外部数据库 MCP 的只读工具获取表/列/关系/索引/枚举/脱敏样本统计；每次查询
   设置行数、字节数、耗时和 PII 预算，禁止写事务、任意函数和跨租户表扫描。
5. **关系推断**：将 endpoint 的 request/response 字段与数据库主键、外键、唯一键和状态列关联，推断
   “创建返回 ID → 后续路径参数”“登录 Token → 授权 Header”“数据库状态 → 业务断言”等绑定，并为
   每条推断给出 `evidence_refs` 和置信度，低置信度必须进入人工确认。
6. **生成 FlowSpec**：生成 typed 节点图、参数化环境变量、Secret 引用、前置数据、清理策略、正/负面
   场景和断言；不得把 Token、密码、连接串、原始 PII 或固定生产 ID 写入 FlowSpec。
7. **静态验证**：检查图连通性、循环/并发边界、Schema 类型、状态码覆盖、绑定引用、SSRF/出站白名单、
   幂等性、数据清理、敏感值泄漏和执行预算。验证失败时只能返回修订建议，不能自动发布。
8. **创建草稿**：`create_flow_draft` 保存不可变来源快照、模型/工具版本、提示词哈希、数据画像版本、
   每个节点的证据与置信度；Web 页面展示差异和“接受/编辑/拒绝”操作。
9. **预览与批准**：`preview_flow` 只使用沙箱环境、合成/脱敏数据和受限网络；用户确认参数、断言、清理
   和风险后生成一次性 `approval_id`，再允许发布或执行。
10. **回写证据**：执行结果、请求/响应脱敏摘要、数据库一致性检查、失败缩减样例和人工修改记录回写为
    Run Evidence；后续 LLM 只能读取这些受控资源，不能读取原始 Secret/日志。

### FlowSpec 最小契约

```json
{
  "schema_version": "flowtest-flow-spec-v1",
  "project_id": "uuid",
  "source_evidence": ["source://repo/commit/file.py#L42-L58", "db://profile/v3"],
  "nodes": [
    {"id": "create_order", "kind": "http", "operation_ref": "orders.create", "depends_on": []},
    {"id": "assert_order", "kind": "assert", "depends_on": ["create_order"]}
  ],
  "bindings": [{"from": "create_order.response.body.id", "to": "assert_order.path.order_id"}],
  "parameters": [{"name": "customer_id", "source": "synthetic_data", "secret_ref": null}],
  "assertions": [
    {"node_id": "create_order", "kind": "status_code", "expected": [201]},
    {"node_id": "assert_order", "kind": "json_schema", "schema_ref": "contract://orders.get#response"},
    {"node_id": "assert_order", "kind": "database_invariant", "query_ref": "db://checks/order-created"}
  ],
  "cleanup": [{"operation_ref": "orders.cancel", "best_effort": false}],
  "security_policy": {"secret_refs_only": true, "max_requests": 20, "allow_private_network": false},
  "confidence": {"overall": 0.91, "unresolved": []}
}
```

### 权限、审批和审计

| Scope | 可做什么 | 默认 |
|---|---|---|
| `mcp:read` | 读取脱敏项目、契约、运行证据 | 可申请 |
| `mcp:analyze` | 读取 allowlist 源码和外部 MCP 的只读画像 | 需项目 Owner 授权 |
| `mcp:draft` | 创建/修改草稿，不发布、不执行 | 需项目 Editor 授权 |
| `mcp:preview` | 沙箱预览，固定网络/请求/时间预算 | 每次显式确认 |
| `mcp:publish` | 发布不可变 Flow Version | 仅人工批准 |
| `mcp:execute` | 在白名单环境执行 | 仅人工批准 + 幂等键 |

每次 MCP 调用记录 client/server 版本、tenant/project、tool、输入 Schema 哈希、证据版本、审批 ID、
模型提供者/模型标识、trace ID、结果摘要和拒绝原因；禁止记录原始参数中的 Secret、Cookie、Token、
授权头、数据库连接串和未脱敏样本。

## V5 优化优先级

| 优先级 | 功能 | 价值 | 依赖/风险 |
|---|---|---|---|
| P0 | MCP 只读发现、源码静态分析、DataProfile、FlowSpec、草稿/审批/审计 | 直接实现“LLM 生成接口流程”主价值 | 需要强授权、脱敏和证据链；不得自动执行 |
| P0 | OpenAPI/GraphQL/AsyncAPI/Bruno/Insomnia/Postman 导入与导出 | 吸收竞品生态，降低迁移成本 | 保留版本/Secret 引用，禁止把脚本直接导入执行 |
| P1 | Schemathesis 属性/Stateful 节点、Keploy 流量录制回放、失败样例缩减 | 扩大边界覆盖，减少手工编写 | 录制前脱敏；生产流量必须有审批和采样预算 |
| P1 | GitHub PR/Actions、JUnit/HAR/Allure、变更影响与回归选择 | 把草稿/证据进入团队交付流程 | 签名提交、分支权限和不可变证据 |
| P1 | 数据生成/清理、PII 分类、数据库快照和跨步骤一致性断言 | 解决“数据相关用例”核心难题 | 只读数据库 MCP、租户隔离、可恢复清理 |
| P2 | 多租户/配额、Durable Command、Full HA/Kubernetes Runner | 企业规模与高可用 | 不得增加 Standalone 的硬依赖 |
| P2 | 签名 Plugin/Connector Marketplace、模型评测集和自动提示优化 | 形成扩展生态和持续质量 | 供应链签名、沙箱、模型漂移评测 |

## MCP 质量门槛

- 工具 Schema、资源 URI、Prompt 文本和错误 envelope 均有 contract test；工具列表稳定排序并带版本。
- 100% 生成草稿可追溯到源码/契约/数据证据；低置信度项不能静默变成断言。
- Secret/Token/PII 泄漏率为 0；任意写/发布/执行必须有人工批准、租户授权和幂等键。
- 使用脱敏真实样本建立评测集：流程有效率、Endpoint 覆盖率、参数绑定准确率、断言正确率、人工修改
  率、预览通过率、误报/漏报和平均生成时间；红队提示词不能绕过策略。
- MCP 不可用时 FlowTest 的普通 Web/API/Standalone/Compact 功能不受影响；关闭 MCP 只关闭外部入口。

## 建议里程碑

| 小阶段 | 方向 | 首要交付 | 退出条件 |
|---|---|---|---|
| S38 | V4 收口与兼容冻结 | Standalone/Compact 试点签署、V4 迁移证据、API/Schema 兼容基线 | V4 手册、CI、真实试点记录齐全；不改变 `/api/v1` |
| S39 | MCP 只读基础 | `flowtest.*` Server、stdio/Streamable HTTP、Resources/Prompts/Tools、OAuth/Scope、脱敏审计 | MCP Inspector/contract test 通过；无写/执行副作用 |
| S40 | 源码与数据分析 | 固定 commit 静态分析、OpenAPI/GraphQL/AsyncAPI、外部数据库 MCP `DataProfile` 适配 | 证据引用、置信度、PII/查询预算和跨租户拒绝门禁通过 |
| S41 | FlowSpec 草稿生成 | 参数/Secret 引用、数据绑定、正负场景、断言/清理、Flow Draft Diff | Golden set 流程有效率和人工可审核率达标；不能自动发布 |
| S42 | 沙箱预览与智能回归 | Preview、审批、执行证据、失败缩减、Schemathesis/Keploy 适配、GitHub Actions | 预览隔离、幂等/回滚、Secret 零泄漏和回归证据通过 |
| S43 | 企业平台基础 | Tenant/Org、配额、Durable Command、Key Rotation、HA/可选 K8s Runner | PostgreSQL 真实迁移、Worker 恢复、权限/容量/安全门禁通过 |
| S44 | 生态与发布 | 签名 Plugin/Connector、兼容矩阵、模型评测、MCP Marketplace、V5 Release Gate | SDK/供应链/升级回滚/公司试点签署完成 |

## 设计约束

- `/api/v1` 现有客户端保持兼容；破坏性变更只能进入新版本 API，并提供迁移期和回滚方案。
- PostgreSQL 仍是 Compact/Full 的权威业务存储；SQLite 只属于 Standalone，并通过显式 transfer
  manifest 迁移，禁止复制数据库文件冒充迁移。
- Standalone 不承诺 HA、崩溃后任务续跑或容量基线；V5 的 Durable Command 只能增强 Compact/Full，
  不得让公司云桌面被迫安装 Docker、WSL2、数据库或开发工具。
- 领域模块不依赖 FastAPI、Celery、SQLAlchemy Model 或具体云客户端；运行档位通过 typed port/adaptor
  注入，任何新能力必须有 profile compatibility 测试。
- Secret、Cookie、Token、授权头、加密密钥和业务响应默认不进入日志、指标、诊断包或模型输入；所有
  外部错误继续使用带 trace ID 的标准 envelope。

## V5 第一轮实现顺序

1. 先完成 S38 的 V4 试点/迁移证据与 API/Schema 冻结，再从清洁 `main` 建立 V5 分支。
2. 先做 MCP 只读发现、认证和审计，再做源码/数据证据归一化与 FlowSpec 草稿；所有写/预览/执行都
   经过两阶段审批，避免在证据和权限边界未固定前扩大模型副作用。
3. 在 MCP 主路径稳定后再做租户/配额、Durable Command、Key Rotation 和 HA；避免在租户边界未固定
   前扩大执行平面。
4. 每个小阶段同时提供 Standalone 兼容测试、Compact Smoke、Full/Upgrade/Rollback 门禁；没有对应
   运行档位证据的能力不进入默认 Feature Flag。
5. 以真实迁移、失败恢复、容量和安全证据作为阶段退出条件，不用单元测试数量替代公司试点和时间性观察。

该文件是 V5 设计草案，不代表已经创建 V5 代码分支、正式标签或改变 V4 发布门槛。

## S47 实现校正（2026-08-23）

S47 以已实现代码为事实源，校正了上述早期草案的里程碑命名和能力边界：

- 主链路固定为 `Evidence → Test Engineering → ChangeSet Draft → Human Review →
  Workflow/TestCase → Durable Execution → Run Evidence`。TestDesign 是可审核的设计聚合，
  Workflow/TestCase 仍是物化和执行事实源。
- Evidence 必须带 `source_ref`/revision/confidence/deterministic 并受条数和字节预算限制。
  契约、有界 Python AST 源码快照和已脱敏 DataProfile 都通过 typed provider 进入，
  不执行导入的源码，不读取样本原值。
- 生成器对 required/nullable、number min/max、string min/max/enum/pattern、array min/max、
  类型错误、缺失认证和可选 pairwise 场景做确定性生成；每个 Scenario/Oracle
  都指向 Evidence Ref，低置信度或无契约的 Oracle 必须人工复核。
- FlowSpec 保留 v1 Schema 并新增 v2 跨实例指纹。Service/Operation/Target 使用可移植逻辑键，
  导入时通过显式 Mapping 解析为目标实例 UUID；未解析引用会阻止 Apply，不得默默降级。
- Resume 在同一 Execution 中保留已完成 Checkpoint 并继续 Attempt；Retry 创建新
  Execution 并从新计划。批次执行按子项写 Checkpoint，所有上报必须验证
  Lease/Fence，Dispatch 失败必须补偿为可观测终态。
- MCP 保留 Read/Controlled Write 边界。写工具必须使用幂等键，默认
  `dry_run=true`，且最多生成 Draft；不新增自动发布、执行、删除、权限变更或 Credential
  工具。
- Key Rotation 采用如实能力模型：当前只有元数据计划，没有真实数据重加密、分批进度、
  验证和回滚。完成前 API 显式拒绝 Apply/Rollback，页面标注“未实现”，该项仍为 GA blocker。

S47 不改变 Windows 72 小时试点、14 日 RC 观察、真实备份恢复和人工签署门槛。
实际验收证据、未完成项和发布判定见
[S47 V5 功能闭环记录](release/s47-v5-functional-completion.md)。

## S47.1 语义正确性校正（2026-08-23）

S47.1 不重建 S47 的资产或引擎，而是把真实 OpenAPI 导入后的语义贯穿既有链路：

1. APIVersion 保存 Canonical Operation Contract 和 fingerprint，区分 Path/Query/Header/Cookie/
   Body/Auth，并保留 request/response Schema；旧数据只做可证明的 partial backfill。
2. Evidence Bundle 通过明确 Projection 进入 Scenario、Oracle、Coverage 和 Graph；冲突保留双方
   provenance，自动物化被阻断。
3. Scenario Mutation 和 Workflow request override 保留参数位置，Runtime 支持节点级 auth disabled，
   Schema/JSON Path/受支持 expression Oracle 复用现有 Assert 节点。
4. FlowSpec fingerprint v3 将 pinned/current、source version 和 contract fingerprint 纳入语义；
   pinned 映射必须 exact compatible，禁止回退 current。
5. Change Regression 分离 Asset Mapping 与 Test Semantic Coverage，从 Current Canonical Contract
   生成真实 Oracle，并经既有 ChangeSet 审核后复用 TestEngineering 物化服务。
6. Source Evidence 增加 value-level Secret/PII redaction；Failure Triage 区分 received 5xx upstream
   与 no-response endpoint/network，并使用 service key。
7. 0042 迁移、Standalone SQLite 和 Transfer 同步；0041 downgrade 不再伪造 key migrated。

Pairwise value-partition covering array 和显式 State Model 仍是 P1；State 无证据时能力明确不可用。
真实 Key Rotation 和外部发布门槛仍阻断 GA。详细记录见
[S47.1 语义正确性与证据闭环](release/s47-1-semantic-correctness.md)。

## S47.2 最终正确性与安全闭环（2026-08-23）

S47.2 只关闭 V5 现有链路的正确性、安全和合并门禁，不扩展新的执行引擎或资产模型：

1. Canonical Contract 在导入、持久化、迁移、API、MCP、Test Engineering 和 fingerprint 前统一经过
   allowlist sanitizer；示例、默认值、常量和敏感枚举不进入数据库或对外响应。
2. Request suppression 在 Project、Environment、ServiceEndpoint、API 和 Runtime 合并完成后统一应用，
   因而 required Header omit 与 auth disabled 不会被高优先级层重新注入。
3. Change Regression 的 Coverage 绑定 Operation Identity 和 parameter location，同时区分项目已知覆盖与当前
   TestPlan 覆盖；只有已发布 WorkflowVersion 可以形成执行覆盖事实。
4. Evidence 将规范性约束与观察统计分开，冲突判断对称并保留双方 provenance；Source AST 与 OpenAPI
   exclusive boundary 保留严格/非严格语义。
5. Pairwise 仍是有界组合能力，State Model 保持 unavailable，Knowledge Graph 仅是确定性 Evidence 关系图；
   Key Rotation 仍只有计划能力。

V5 FlowSpec 的唯一正式基线为 `flowtest-flow-spec-fingerprint-v3`。开发期 v1/v2 文件不属于正式兼容范围，
本轮不增加旧格式迁移或兼容逻辑。详细证据见
[S47.2 最终正确性与安全闭环](release/s47-2-final-correctness-security.md)。
