# FlowTest V6.0 Core 开发版系统使用手册

> 文档类型：系统使用文档  
> 适用版本：FlowTest V6.0 Core 开发版（S49；未发布）<br>
> 适用角色：测试工程师、研发人员、项目 Owner/Editor、组织管理员、平台管理员、MCP 客户端集成人员  
> 最后更新：2026-08-28

## 1. 文档说明

本文介绍 FlowTest 当前系统的主要模块和推荐使用路径，重点说明：

1. **接口管理**：接口创建、版本维护、变量与 Secret、认证、请求预览、执行、导入和导出。
2. **接口工作流**：可视化编排、节点配置、不可变发布、执行快照、调试、重放和 FlowSpec 迁移。
3. **对外 MCP 接口**：Service Account、stdio/Streamable HTTP 接入、Tools、Resources、Prompts、受控写入和安全边界。

本文是“如何使用系统”的主手册。安装、备份和升级等运维操作请结合以下文档：

- [公司电脑 Compact 快速部署](operations/compact-company-quickstart.md)
- [Windows 云桌面 Standalone 快速安装](operations/standalone-company-quickstart.md)
- [部署手册](operations/deployment.md)
- [备份与恢复](operations/backup-recovery.md)
- [升级与回滚](operations/upgrade-rollback.md)
- [系统架构](architecture.md)

### 1.1 当前能力边界

- FlowTest 的业务资产以“组织 → 项目 → 环境/服务/API/工作流/测试资产”组织。
- API 和工作流发布后使用不可变版本；历史执行读取当次 Snapshot，不随当前草稿变化。
- Secret、Credential 值只写入并加密保存，正常读取、预览、报告和 MCP 输出不返回明文。
- MCP 是应用网关，不直接访问数据库，也不绕过项目权限、租户隔离、审计或人工审核。
- MCP 目前只有一个受控写工具；它只能创建待审核的 Test Design ChangeSet Draft，不能自动发布、执行、删除、修改权限或创建 Credential。
- FlowSpec 的 V5 正式基线是 `flowtest-flow-spec-v1` Schema + `flowtest-flow-spec-fingerprint-v3` 指纹。开发期 v1/v2 指纹文件不属于正式兼容承诺。
- 当前组合生成属于 **Bounded Pairwise Partitions（有界代表性成对组合）**，不是完整 covering array；State Model 为 unavailable/experimental；Knowledge Graph 仅为 Basic Test Knowledge Graph。
- Standalone 适合本机、单用户或低并发功能验证，不提供高可用、跨进程任务续跑、Performance Lab、Environment Lab 或 Runner Fabric。
- Compact/Full 使用 PostgreSQL；Standalone 使用 SQLite。不要通过复制数据库文件替代正式 Transfer、备份或升级流程。

## 2. 快速开始

### 2.1 访问地址

常见本地或 Compose 部署地址如下：

| 入口 | 默认地址 | 用途 |
| --- | --- | --- |
| Web 管理端 | `http://localhost:3000` | 日常使用入口 |
| Standalone Web | `http://127.0.0.1:8000` | Windows Standalone 单进程入口 |
| Application API | `http://localhost:8000` | REST API 和 MCP 后端地址 |
| OpenAPI | `http://localhost:8000/docs` | REST API 调试文档 |
| Health | `http://localhost:8000/api/v1/health` | 聚合健康状态 |
| Readiness | `http://localhost:8000/api/v1/ready` | 部署就绪状态 |
| Runtime Profile | `http://localhost:8000/api/v1/runtime-profile` | 查看 Full/Compact/Standalone 档位 |

生产或公司内网部署应通过受控域名和 TLS 访问，不应把开发端口直接暴露到公网。

### 2.2 登录

- Full/Compact：使用 `admin@flowtest.dev` 或别名 `admin`，密码读取部署目录 `.env` 中的 `FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD`。首次登录后按页面要求修改密码。
- Standalone 默认包：使用 `admin/admin`。如果不再仅限本机回环访问，应立即修改密码。
- 企业环境可由管理员配置 OIDC；OIDC 首次登录用户不会自动获得项目访问权限，仍需加入组织和项目。

### 2.3 第一次完成可运行闭环

推荐按以下顺序准备资产：

1. 进入“项目管理”，创建或选择项目。
2. 在“项目管理 → 资产管理”配置项目变量、Header、环境变量和 Secret。
3. 在“请求目标”创建项目级 Service，并为目标环境创建 Endpoint Variant。
4. 在“接口管理”手工创建或导入接口，检查最终请求预览后发送一次真实请求。
5. 在“流程编排”基于已验证接口创建工作流，保存草稿并发布版本。
6. 选择环境运行工作流，在运行视图和测试报告中检查节点、断言和脱敏证据。
7. 需要批量、定时或 CI 触发时，在“测试资产”和“任务执行”中创建不可变版本及测试计划。
8. 需要让外部 AI/Agent 读取 FlowTest 证据时，由组织管理员签发 MCP Service Account，并按第 8 章接入。

## 3. 权限和核心概念

### 3.1 组织角色

| 角色 | 主要能力 |
| --- | --- |
| Owner | 组织读取、创建项目、成员管理、Service Account、治理、审计和密钥生命周期计划 |
| Admin | 除组织密钥轮换外的主要组织管理能力 |
| Member | 读取组织并创建项目 |
| Viewer | 只读组织信息 |
| System Admin | 平台级能力、运行档位和 Runner/插件等系统管理入口 |

组织角色不替代项目角色。用户即使能看到组织，也必须拥有对应项目权限才能读取或操作项目资产。

### 3.2 项目角色

| 角色 | 读取 | 编辑资产 | 执行 | 管理成员/安全/审计 |
| --- | --- | --- | --- | --- |
| Owner | 是 | 是 | 是 | 是 |
| Editor | 是 | 是 | 是 | 否 |
| Viewer | 是 | 否 | 否 | 否 |

团队可以以 Editor 或 Viewer 角色授权到项目。项目至少保留一名 Owner。

### 3.3 资产、草稿、版本和快照

- **Definition/资产定义**：稳定身份，例如一个 API 或一个工作流。
- **Draft/草稿**：可继续编辑的工作区。工作流草稿带修订号，用于避免并发覆盖。
- **Version/版本**：保存或发布后形成的不可变内容。API 节点会固定引用具体 API 版本。
- **Snapshot/执行快照**：执行开始前固定工作流版本、API 版本、环境和目标修订等运行材料。历史详情始终读取该快照。
- **Artifact/附件**：上传文件、二进制响应、报告等对象存储资产，数据库仅保存元数据、哈希和授权关系。
- **Evidence/证据**：带版本和来源引用的安全输出，用于报告、影响分析、发布门禁和 MCP。

### 3.4 Service 的两个含义

系统中有两个相关但用途不同的 Service 概念：

| 模块 | 用途 | 是否保存网络目标 |
| --- | --- | --- |
| 服务目录 | 描述多协议服务、契约和上下游依赖 | 否，不保存 Credential 或 Secret |
| 请求目标 | 为 HTTP 请求解析环境、Service、Endpoint Variant、超时、TLS、Header 和变量 | 是 |

接口实际发送到哪里，以“请求目标”的解析结果为准；服务目录主要服务于契约、影响图和治理。

## 4. 模块总览

| 模块 | 主要用途 | 常见前置条件 |
| --- | --- | --- |
| 质量总览 | 查看项目质量指标、趋势和风险入口 | 已选择项目并有执行数据 |
| 项目管理 | 项目成员、目录、变量、Header、环境、Secret、安全策略、审计和保留策略 | 项目 Owner/Editor；治理项通常需 Owner |
| 服务目录 | 多协议服务、契约类型和依赖图 | Contract Hub 功能已启用 |
| 请求目标 | 管理请求 Service、环境 Endpoint Variant 和 API 默认绑定 | 项目、环境 |
| 接口管理 | HTTP API 建模、调试、版本、导入导出和执行历史 | 项目、环境、请求目标 |
| 多协议工作台 | GraphQL、gRPC、Kafka、WebSocket 资产和调试 | 对应 Schema/Descriptor/Event Source 和运行依赖 |
| 测试资产 | 用例、模板、套件和不可变版本 | 已有工作流或测试定义 |
| 流程编排 | DAG、数据驱动、条件、多协议和执行快照 | 已发布或可引用的 API/协议资产 |
| 数据与 Mock | 只读 Credential、Mock 服务/路由/日志 | 项目 Editor；外部数据源可达 |
| 任务执行 | 批量、定时、CI Token、Webhook 和取消 | 已发布工作流/测试资产，Worker 可用 |
| 性能实验室 | 声明式 k6 场景、阈值、基线和门禁 | Full 档位及性能 Worker |
| 环境实验室 | 签名模板、Provision、健康检查、Seed 和清理 | Full 档位、管理员模板和独立 Runner |
| 契约中心 | OpenAPI/Pact、Provider 验证和兼容判断 | Contract Hub 已启用 |
| Test Engineering | 从契约生成 Scenario、Oracle、Coverage 和待审核 Draft | API 契约 |
| 影响分析 | 分析 Git/OpenAPI/GraphQL/Proto 变化并选择测试 | 可验证的变更输入和映射 |
| 变更回归 | 串联 Change、Impact、选择、缺口审核、执行和 Gate | 影响分析和可执行资产 |
| 质量中心 | CI Gate、Flaky 隔离、基线和 JUnit | 测试执行证据 |
| 发布门禁 | 聚合质量、契约、风险、性能和 Runner 证据 | 对应证据均已生成 |
| AI 助手 | 基于脱敏 Schema/元数据生成建议 | 已配置 AI Provider 和 Worker |
| AI 变更集 | 人工接受、编辑或拒绝 AI/MCP Draft | 已有待审核 ChangeSet |
| 测试报告 | 趋势、失败分类、步骤下钻和 HTML 导出 | 已有执行 |
| 组织治理 | 组织成员、Service Account、配额、Runner 治理和审计 | 组织 Owner/Admin |
| 分布式执行面 | Worker Pool、注册、Lease、Fence 和事件 | System Admin、Full/相应 Feature Flag |
| 平台管理 | Capability、插件和运行时边界 | System Admin |

功能入口可能因运行档位、Feature Flag 和当前角色而隐藏、只读或明确显示“不支持”。

## 5. 项目、环境、请求目标与 Secret

接口和工作流是否能稳定运行，很大程度取决于这四类基础配置。

### 5.1 项目管理

进入“项目管理”后可以处理：

- 项目成员与团队授权。
- 资产目录。
- 项目变量和项目 Header。
- 环境及其变量、Header 和兼容 Base URL。
- Secret 写入。
- 出站网络安全策略和允许的域名/CIDR。
- 执行、报告和附件保留天数。
- 不可变审计记录。

项目 Viewer 只能读取；Editor 可以编辑一般资产并执行；成员、安全策略和审计能力由项目 Owner 控制。

### 5.2 环境

环境表示一组运行上下文，例如 `本地`、`测试`、`预发布`。每个环境可以配置：

- 名称。
- 环境变量和 Header。
- 默认 Service。
- 兼容 Base URL；创建环境时系统会同步创建默认请求目标。

同一 API 或工作流选择不同环境后，会在执行开始前重新解析相应的 Endpoint Variant、变量和 Secret，再固定进当次 Snapshot。

### 5.3 请求 Service 与 Endpoint Variant

进入“请求目标”：

1. 创建项目级 Service，填写稳定的 `service_key`。跨环境、FlowSpec 和工作流节点优先依赖这个稳定标识。
2. 选择环境。
3. 为 Service 创建一个或多个 Endpoint Variant，例如 `default`、`blue`、`canary`。
4. 配置 Base URL、连接/读取超时、TLS 校验、Proxy 引用、Header、变量和允许使用的 Secret 引用。
5. 执行 Connectivity 检查。
6. 将 Service 设为环境默认值，或将特定 API 绑定到 Service。

修改 Service 或 Endpoint 前，页面会展示影响预览。停用正在被 API 或工作流引用的目标会导致预览或发布/执行失败，应该先迁移引用。

请求目标选择优先级为：

1. 工作流 API 节点的 Service Override。
2. API Definition 绑定的默认 Service。
3. 环境默认 Service。
4. 都未配置时使用环境兼容 Base URL。

Endpoint Variant 默认取 `default`；工作流节点可以显式选择其他 Variant。

### 5.4 变量和 Header 优先级

后出现的 Scope 覆盖前面同名值。变量优先级从低到高为：

```text
Global → Project → Environment → Service Endpoint → API → Workflow → Dataset → Runtime
```

Header 优先级从低到高为：

```text
System → Project → Environment → Service Endpoint → Workflow → API → Runtime
```

Header 名称按不区分大小写的方式合并。Runtime Header 的优先级最高，API 认证生成的 Header 不会覆盖已有 Runtime Header。

#### 5.4.1 最终请求抑制

工作流 API 节点可以在 `request_overrides` 中使用最终抑制语义。抑制发生在 Project、Environment、Service Endpoint、Workflow、API 和 Runtime 全部合并完成之后，因此 Runtime 不能重新注入被删除的载体。

```json
{
  "auth_mode": "disabled",
  "suppressed_headers": ["X-Tenant-Id"],
  "suppressed_query_parameters": ["api_key"],
  "suppressed_cookies": ["session"]
}
```

- `auth_mode=disabled` 会按实际认证方案删除 `Authorization`、API Key Header/Query/Cookie 等载体；`auth_disabled` 仅作为开发期兼容别名，新资产不再生成它。
- Header 名称不区分大小写；Query 名称精确匹配并区分大小写；Cookie 使用安全 Cookie 解析后按名称删除。
- Required Header/Query/Cookie 的 omission 场景会物化为对应 `suppressed_*`，不是简单地“不写节点覆盖值”。
- 未知认证方案无法确定载体时，场景保持 Design-only 并要求人工复核，不会假装已经禁用认证。
- Snapshot 只保存 `auth_mode` 和被抑制的名称，不保存 Token、API Key 或 Cookie 值。

模板变量写法：

```text
{{user_id}}
{{base_path}}
{{secret.BEARER_TOKEN}}
```

变量可用于 Path、Query、Header、Body、Base URL 和认证配置。最终请求仍有未解析变量时，系统返回 `UNRESOLVED_VARIABLE`，不会发送半解析请求。

### 5.5 Secret 与 Credential

- **Secret** 用于 HTTP 请求模板和环境，例如 Bearer Token、API Key。通过 `{{secret.NAME}}` 引用。
- **Credential** 用于 SQL、Redis、gRPC mTLS 等受控节点，包含类型、Host、Port、用户名、TLS 和密钥材料。
- Secret 和 Credential 明文只在写入请求中出现，系统加密保存；列表、详情和报告只返回元数据或脱敏值。
- Environment/Endpoint/API 只有显式引用的 Secret 才会在执行准备阶段加载。
- 不要把真实 Token 写入 API 普通变量、FlowSpec、MCP 参数、Git 或截图；应创建 Secret 引用。

## 6. 接口管理（重点）

“接口管理”用于管理 HTTP API 资产、持续编辑请求模板、发送真实请求并检查执行结果。

### 6.1 使用前准备

至少需要：

- 一个有编辑权限的项目。
- 一个环境。
- 可解析的请求目标。简单场景可以使用环境兼容 Base URL；多服务项目建议完整配置 Service 和 Endpoint Variant。
- 目标 Host 满足项目出站安全策略。
- 认证所需 Secret 已写入项目或环境。

发送按钮只有在项目、环境和接口均已选择时可用。

### 6.2 创建接口

在“接口管理”点击“新建接口”，填写：

- 名称。
- HTTP Method：`GET`、`POST`、`PUT`、`PATCH`、`DELETE`。
- Path，例如 `/users/me` 或 `/users/{{user_id}}`。
- Body 类型和初始值。
- 认证类型和引用。

创建后会得到 API Definition 和首个不可变版本。接口名称可以重命名；请求内容的变化通过“保存新版本”形成新版本，不会就地修改旧版本。

### 6.3 接口列表

接口列表支持：

- 按名称、Path 或说明搜索。
- 按 HTTP Method 筛选。
- 分页。
- 查看当前版本。
- 选择接口进入工作台。
- 重命名接口。

如果一个 API 已被工作流固定引用，重命名只改变展示名称；保存新版本也不会改变已发布工作流引用的旧版本。

### 6.4 API 工作台

工作台顶部可编辑 Method 和 Path，主要标签如下：

| 标签 | 用途 |
| --- | --- |
| Params | Query 参数；可启用/停用，支持变量和批量编辑 |
| Headers | 请求 Header；支持变量、Secret 引用和批量编辑 |
| Auth | 无认证、Bearer、Basic、API Key |
| Body | none、form-data、x-www-form-urlencoded、raw/JSON 等请求体 |
| 提取 | 从响应中提取值，为执行上下文生成变量 |
| 断言 | 校验状态码、响应时间、Header、响应数据、Schema 或文件元数据 |

“预览最终请求”读取当前已保存版本，并展示 URL、Header 来源、Body、变量来源和脱敏后的 Secret。当前页面尚不会把表单中未保存的改动带入预览；因此修改请求后应先保存新版本，再预览新版本。

#### 6.4.1 Params

每个 Query 参数包含名称、值和启用状态。例如：

```text
page = 1
user_id = {{user_id}}
tenant = {{tenant_code}}
```

停用项不会进入最终 URL。批量编辑适合粘贴多行键值；应用前页面会校验格式并列出问题。

#### 6.4.2 Headers

Header 可以直接填写模板值，例如：

```text
X-Tenant-ID: {{tenant_id}}
X-Request-Source: flowtest
X-Api-Key: {{secret.API_KEY}}
```

不要手工复制真实 `Authorization` Token。优先使用 Auth 标签和 Secret 引用，让系统统一脱敏。

#### 6.4.3 Auth

| 类型 | 典型配置 | 结果 |
| --- | --- | --- |
| none | 无 | 不注入认证信息 |
| bearer | `{{secret.BEARER_TOKEN}}` | 生成 `Authorization: Bearer ...` |
| basic | 用户名和密码/Secret | 生成 Basic Authorization |
| api_key | 名称、值、Header/Query 位置 | 注入指定 Header 或 Query |

API Key、Bearer 和 Basic 密码字段均应引用 Secret。认证 Header 进入持久化、报告和 MCP 输出前会脱敏。

#### 6.4.4 Body

| 模式 | 用途 | 注意事项 |
| --- | --- | --- |
| none | GET/DELETE 等无请求体调用 | 不发送 Body |
| raw JSON | JSON API | 可格式化并使用模板变量 |
| raw Text/XML/HTML | 非 JSON 文本协议 | 按文本发送 |
| x-www-form-urlencoded | 表单键值 | 支持变量和批量编辑 |
| form-data | 文本字段和文件上传 | 文件必须先上传到文件仓库 |

form-data 的文件字段引用 Artifact ID。发布/执行时系统加载受权 Artifact 并固定必要元数据；不要引用已删除或无权访问的文件。

#### 6.4.5 响应提取

提取配置至少包含变量名、表达式类型和表达式，例如：

```text
变量名：access_token
类型：JSONPath
表达式：$.data.token
```

提取值适合供同一执行或工作流的后续节点使用。认证 Token 仍应遵循脱敏规则，不应在日志、断言期望值或普通报告字段中复制明文。

#### 6.4.6 断言

当前接口工作台可以配置以下断言类型：

- 状态码。
- 响应时间。
- Header。
- JSONPath。
- JMESPath。
- JSON Schema（Draft 2020-12）。
工作台可选比较操作为等于、不等于、包含、存在、小于和大于。底层执行契约还支持文件大小、文件 SHA-256、Content-Type、小于等于、大于等于和正则匹配，但当前接口工作台没有对应配置项；需要这些扩展断言时应通过受控 REST/导入链路创建，并在执行前验证，不要假定页面已提供入口。期望值字段会尝试按 JSON 解析；需要纯文本时按页面提示填写。

常见配置示例：

```text
状态码 equals 200
响应时间 less_than 1000
Header Content-Type contains application/json
JSONPath $.data.id exists
JMESPath data.items[0].status equals "active"
```

### 6.5 预览、保存和执行的区别

| 操作 | 是否发送请求 | 是否创建 API 版本 | 主要用途 |
| --- | --- | --- | --- |
| 预览请求 | 否 | 否 | 检查最终 URL、Header、变量来源和脱敏结果 |
| 保存新版本 | 否 | 是 | 固定新的 API 模板版本 |
| 发送请求 | 是 | 否 | 使用当前已保存版本和所选环境执行 |

建议顺序为“编辑 → 保存新版本 → 预览最终请求 → 发送请求”。预览始终基于当前已保存版本，不包含尚未保存的表单变化。不要把成功预览等同于网络可达；Connectivity、出站策略、DNS、TLS 和目标服务状态只在实际连接时完全生效。

### 6.6 请求运行器和执行结果

在请求运行器中设置预期状态码，然后点击“发送请求”。结果区包括：

- 响应状态、耗时、Header 和脱敏 Body。
- 断言结果及实际值。
- 执行历史。
- 错误码和可追踪信息。

二进制或较大响应可能作为 Artifact 存储。请求、响应、认证信息、Cookie、Token、Password 和 Secret 会在持久化及展示前脱敏。

### 6.7 导入接口

点击“导入接口”，可选择本地文件或 URL。

支持格式：

- OpenAPI 3。
- Swagger 2。
- Postman Collection。
- HAR。
- cURL。
- Bruno。
- Excel。

URL 导入支持从 Swagger UI、Springdoc、FastAPI 和 Knife4j 页面发现接口文档。当页面发现多个分组时：

1. 先选择需要的文档分组。
2. 生成 Diff。
3. 按名称、方法或路径筛选变化。
4. 逐项选择本次要合并的变更。
5. 确认后合并。

Diff 状态：

| 状态 | 含义 |
| --- | --- |
| 新增 | 将创建新 API |
| 变更 | 将为现有 API 创建不可变新版本 |
| 待停用 | 来源文档已删除；默认只作为风险提示，不自动停用 |
| 未变化 | 指纹一致，不重复创建版本 |

“待停用”项默认不勾选；只有用户在 Diff 中明确勾选并合并后，对应接口才会被停用。

URL 和导入文档均视为不可信输入。服务端会执行协议、Host、DNS、私网/回环、元数据地址、重定向和响应大小等安全检查。若项目开启出站安全策略，应先在“项目管理”中加入获批 Host/CIDR。

OpenAPI/Swagger 的 Canonical Contract 只保留测试语义白名单字段。`example`、`examples`、`default`、`const`、`x-example` 和 `x-examples` 不会持久化；疑似 Token、PII 或高熵凭据的 Enum 会只保留数量和哈希摘要，并把契约标记为 `redacted_partial`。因此接口详情、Test Engineering、MCP 和 Audit 都不会返回这些原值。`redacted_partial` 场景需要通过 `secret://` 安全测试数据引用并完成人工审核后才能物化。

### 6.8 导出接口

接口管理支持导出：

- HAR。
- cURL。
- Bruno。
- Excel。

导出用于迁移结构和模板，不应被当作 Secret 备份。导出结果不会有意携带 Secret 明文；在其他系统运行前需要重新配置目标环境和认证。

### 6.9 接口管理常见问题

| 现象/错误 | 原因 | 处理方式 |
| --- | --- | --- |
| `UNRESOLVED_VARIABLE` | 模板引用不存在 | 检查拼写和 Scope；Secret 使用 `secret.` 前缀 |
| `SERVICE_ENDPOINT_NOT_FOUND` | 当前环境没有对应 Service/Variant | 在“请求目标”创建相同 Variant |
| `SERVICE_ENDPOINT_DISABLED` | Endpoint 已停用 | 启用目标或迁移 API/工作流引用 |
| 目标被安全策略拒绝 | Host/CIDR 未获批或指向回环/元数据地址 | 检查项目出站策略，不要为绕过校验关闭生产安全策略 |
| TLS 失败 | 证书链、域名或 TLS 配置不匹配 | 修复证书；仅在受控测试环境评估关闭 TLS 校验 |
| 导入 URL 失败 | 页面发现不到原始文档、重定向或响应受限 | 直接使用 OpenAPI URL或上传文件，并检查安全白名单 |
| 工作流仍使用旧接口 | 已发布工作流固定了旧 API 版本 | 修改草稿节点引用并重新发布工作流版本 |

## 7. 接口工作流 / 流程编排（重点）

“流程编排”把接口、数据、条件和多协议能力组织为 DAG，并以不可变版本执行。

### 7.1 使用前准备

- 至少有一个已验证的 API。
- 已创建目标环境，并能解析所有 API 节点的 Service/Endpoint Variant。
- 数据集文件已上传到文件仓库。
- SQL/Redis/gRPC mTLS 节点所需 Credential 已创建。
- GraphQL Schema、gRPC Descriptor、Kafka/WebSocket Event Source 等协议资产已登记并发布可引用版本。
- 子流程必须已有已发布版本。

### 7.2 创建工作流

1. 进入“流程编排”，选择项目和环境。
2. 点击“新建工作流”。
3. 输入名称并选择一个初始 API。
4. 系统创建 `Start → API → End` 草稿。
5. 在画布中拖动节点，从节点右侧连接到下一节点。
6. 点击节点，在右侧检查器中配置属性。
7. 点击“保存草稿”。

草稿显示 `rN` 修订号。并发编辑时，旧修订提交会被拒绝，避免静默覆盖他人变更；应刷新后重新应用修改。

### 7.3 画布操作

工具栏支持：

- 添加接口和协议节点。
- 添加提取、断言、条件、延时、数据集、SQL、Redis、子流程、ForEach 和结束节点。
- 复制/粘贴节点。
- 撤销/重做。
- 自动布局。
- 拖动调整位置和连线。

删除节点或修改连线后要重新检查所有路径。发布校验会拒绝循环、不可达节点、悬空路径、错误的 Start/End、无效配置和跨项目引用。

### 7.4 节点说明

| 节点 | 主要用途 | 关键配置/限制 |
| --- | --- | --- |
| Start | 工作流唯一入口 | 通常只能有一个，不能有入边 |
| API | 执行固定版本 HTTP API | API、版本、超时、重试、Service Override、Endpoint Variant、请求差异 |
| GraphQL | 执行固定 Schema 的 Query/Mutation | Endpoint、文档、Variables、Header |
| gRPC | 调用固定 Descriptor 的方法 | Endpoint、Service/Method、Request、Metadata、TLS/mTLS Credential |
| Kafka Produce | 发送事件 | 固定 Event Source 版本、Topic、消息、Schema/Correlation |
| Kafka Consume | 消费有界消息 | Topic、起始 Offset、最大消息数、Schema/Correlation；不会无限消费 |
| WebSocket Exchange | 建连、发送并读取有界响应 | 固定 Event Source 版本、消息和协议配置 |
| Extract | 从上游结果取值并保存变量 | 安全表达式/路径和目标变量名 |
| Assert | 对上游结果或上下文做比较 | 表达式、操作符和期望值 |
| Condition | 条件分支 | 必须恰有 `true` 和 `false` 两条出边 |
| Delay | 等待固定时长 | 使用有界时长，避免占用执行资源 |
| Dataset | 数据驱动执行 | 一个工作流最多一个；CSV/JSON/Excel，最多 1000 行、200 列 |
| SQL | 只读数据库查询 | 只读 Credential、单条参数化只读语句 |
| Redis | 白名单只读命令 | Redis Credential、命令和参数 |
| Subflow | 调用另一个已发布工作流 | 固定子流程和版本，不能引用自身形成递归 |
| ForEach | 对集合逐项执行子流程 | 元素/索引变量、并发、`fail_fast` 或 `continue` |
| End | 路径终点 | 至少一个，不能有出边 |

GraphQL、gRPC、Kafka 和 WebSocket 在执行定义中属于版本化 Capability 节点，页面会按具体能力展示配置。若运行档位、Feature Flag 或 Runner 不支持，发布或执行会明确拒绝。

### 7.5 API 节点配置

#### 7.5.1 固定 API 版本

API 节点引用 API Definition 和具体版本。保存工作流草稿时应确认显示的 API 版本；发布后该引用进入工作流版本和执行 Snapshot。

API 管理中新建 v2 不会自动把已发布工作流从 v1 升级到 v2。升级步骤是：

1. 打开工作流草稿并选择对应 API 节点。
2. 点击“更新至接口最新 vN”，把节点从旧版本更新到接口当前版本。
3. 检查节点请求差异及目标预览。
4. 保存草稿。
5. 发布新的工作流版本。

#### 7.5.2 继承与节点自定义

API 节点的 Params、Headers、Body 支持两种模式：

- **继承接口模板**：使用接口管理中固定版本的值。
- **节点自定义**：只把差异保存到当前工作流，不修改接口管理中的模板。

Auth 继续由接口模板和环境 Secret 管理，节点不会复制明文凭据。节点最终请求预览同样脱敏。

#### 7.5.3 请求目标覆盖

节点可选择：

- 继承 API/环境的 Service 解析。
- 使用 Service Override。
- 指定 Endpoint Variant，例如 `canary`。

只在业务确实需要时使用节点覆盖。稳定默认目标应配置在 API Definition 或环境，减少每个工作流重复维护。

#### 7.5.4 超时和重试

API 节点支持有界超时和重试。网络错误与 `5xx` 可按配置分类重试；断言失败等确定性业务错误不应通过无限重试掩盖。运行视图会展示每次尝试。

### 7.6 节点间数据传递

系统有两种常见传递方式：

1. **Extract 节点**：读取上游输出并写入 Execution Context Variable。
2. **Edge 字段映射**：以边的 Source 节点输出为输入，使用 JMESPath 读取后写到 Target 节点的 Query、Header、JSON Body 路径或 Variable。

字段映射属于连线，不属于全局变量。目标节点没有连接到正确上游时，映射来源下拉框会为空。

示例：登录节点响应为 `{"data":{"token":"..."}}`，可以从上游输出路径读取 Token，再映射到后续节点变量。敏感值只在运行上下文中传递，报告不保存 Secret 或映射值副本。

### 7.7 条件与汇合

Condition 节点必须配置两个出口：

- `true`/“是”。
- `false`/“否”。

未选择分支的节点会标记为 `skipped / BRANCH_NOT_SELECTED`。汇合节点只等待 active 入边；失败传播仍遵循工作流策略。

### 7.8 Dataset 数据驱动

1. 先在文件仓库上传 CSV、JSON 或 Excel。
2. 添加 Dataset 节点并选择文件、格式和 Excel Sheet（如适用）。
3. 配置字段映射或模板变量。
4. 保存并发布。

发布时系统读取并校验数据集，把规范化数据固定进 Snapshot。执行时每行创建独立子执行，父执行聚合 passed、failed、cancelled 数量。页面可下钻每一行的运行状态。

限制：

- 一个工作流最多一个 Dataset 节点。
- 最多 1000 行、200 列。
- 默认子执行并发为 5。
- 数据集变量覆盖同名 Workflow 变量，但会被 Runtime 变量覆盖。

### 7.9 SQL、Redis 和数据安全

- SQL 节点只允许单条参数化只读查询，Credential 由系统注入，不把密码写入节点定义。
- Redis 节点只开放白名单只读命令。
- 外部数据库、Redis Host 和端口均视为不可信目标，需满足网络和 Credential 策略。
- 不要把生产库写权限账号配置为测试 Credential。

### 7.10 保存、发布和运行

| 操作 | 作用 | 是否可修改历史 |
| --- | --- | --- |
| 保存草稿 | 保存当前画布和节点配置，修订号加一 | 不影响旧版本/旧执行 |
| 发布版本 | 校验 DAG 和引用，创建不可变工作流版本 | 不影响旧版本 |
| 运行 | 执行当前已发布版本和所选环境的固定快照 | 执行创建后不可改写为其他版本 |

运行按钮要求：项目、环境、工作流和已发布版本均存在，且当前没有同一页面正在跟踪的活动执行。

### 7.11 运行视图、历史快照和调试

页面有三种视图：

- **编排**：编辑当前草稿。
- **运行视图**：通过执行事件实时更新节点状态；点击节点查看输入、请求、响应、输出、断言/错误和每次重试。
- **历史快照**：读取选中历史执行的不可变画布、节点配置和结果，只读。

调试能力：

- **调试至断点**：执行到选定节点后停止，用于逐段验证。
- **重放节点**：在运行上下文允许时重放单个节点。
- **版本 Diff**：至少有两个已发布版本后比较最新版本差异。

调试和重放仍遵循目标安全策略、Credential 权限和脱敏规则。对于有外部副作用的接口，重放前必须确认幂等性；调试功能不自动消除目标服务的写入副作用。

### 7.12 FlowSpec 导出、导入和跨项目 Mapping

FlowSpec 是工作流的可移植描述，不直接依赖源项目实例 UUID。

导出和导入步骤：

1. 在工作流页面点击“FlowSpec 导入 / Mapping”。
2. 点击“导出当前草稿”，获得 JSON。
3. 在目标项目粘贴 FlowSpec JSON。
4. 点击验证，检查 Schema、兼容性和 Issue Path。
5. 将 Portable Service/Operation Ref 映射到目标项目的 Service 和 API。
6. 生成并查看 ChangeSet Diff。
7. 创建 ChangeSet Draft。
8. 由有权限的人逐项接受、编辑或拒绝，再应用到目标项目。

FlowSpec 不用于携带 Secret、Credential 或源实例内部 ID。跨项目导入必须完成 Mapping Review；不要通过手工替换 UUID 绕过验证。

V5 新导出、验证、Diff、Review 和 Apply 一律使用 `flowtest-flow-spec-fingerprint-v3`。指纹包含 pinned/current API 版本、Operation Contract 和请求抑制语义，但不包含数据库 UUID、来源修订和 Warning。开发期 fingerprint v1/v2 文件不属于 V5 正式兼容范围。

### 7.13 工作流常见问题

| 现象/错误 | 原因 | 处理方式 |
| --- | --- | --- |
| 无法发布 | DAG 循环、不可达、悬空或节点配置不完整 | 按校验路径定位节点和边 |
| 运行按钮不可用 | 未选择环境、无发布版本或执行仍在运行 | 补齐选择或等待终态 |
| 条件分支校验失败 | 缺少 `true`/`false` 出边或多余出口 | 保持恰好两条条件边 |
| Dataset 发布失败 | 文件格式、行列数或 Sheet 不合法 | 修复并重新上传文件 |
| API 节点找不到目标 | Service/Variant 在当前环境缺失或停用 | 在“请求目标”补齐并检查 Connectivity |
| 历史结果和当前草稿不同 | 历史使用执行 Snapshot | 这是预期行为；切回“编排”查看当前草稿 |
| 重放产生重复业务数据 | 目标 API 非幂等 | 对写接口使用幂等键或在隔离环境调试 |
| 草稿保存冲突 | 别人已提交新修订 | 刷新最新草稿后重做本地变更 |

## 8. 对外 MCP 接口（重点）

### 8.1 MCP 的定位

FlowTest MCP 让支持 Model Context Protocol 的外部客户端读取经过授权、脱敏且可追溯的项目证据，并提交受人工控制的测试设计建议。

```text
MCP Client
    │  stdio 或 Streamable HTTP
    ▼
FlowTest MCP Gateway
    │  Service Account Bearer Token
    ▼
FlowTest /api/v1 Application API
    │
    ├─ 租户和项目授权
    ├─ 脱敏、证据引用和 Trace ID
    ├─ 审计
    └─ Application Service → 数据库/对象存储/执行面
```

MCP Gateway 不连接数据库，不接收数据库连接串，不读取 Secret 明文，也不代替 Web 中的发布和审核流程。

### 8.2 签发 Service Account

需要组织 Owner 或 Admin：

1. 进入“组织治理”。
2. 选择目标组织。
3. 打开“Service Account”标签。
4. 填写名称和稳定标识，例如 `mcp-read-bot`。
5. 选择最小权限 Scope。
6. 点击“签发令牌”。
7. 立即复制以 `ftsa_` 开头的 Token，并保存到密码管理器或 Secret Store。

Token 只显示一次。丢失后不能读取旧明文，应轮换令牌；不再使用时立即撤销。

MCP Scope：

| 目的 | 必需 Scope | 建议 |
| --- | --- | --- |
| 使用只读 Tools/Resources | `mcp:read` | 默认只签发这一项 |
| 提交 Test Design ChangeSet Draft | `mcp:write` | 仅给明确需要提案的客户端；通常同时保留 `mcp:read` |
| 创建、补充、查看或关闭 Test Context | `mcp:evidence:write` | 只给受信 Evidence Provider；不会继承自 `mcp:write` |
| 预览或创建 FlowSpec Draft Proposal | `mcp:flow:propose` | S49 仅开放受控 Application API；MCP Tool 在 S51 注册 |

Service Account 绑定签发人的组织和项目可见性。即使拥有 MCP Scope，也不能跨组织读取，也不能读取签发人无权访问的项目。签发后如果项目权限发生变化，调用结果会同步受限。

### 8.3 从源码启动 MCP Gateway

MCP CLI 入口为 `flowtest-mcp`，依赖后端 Python 环境。首次使用先在仓库中安装锁定依赖：

```bash
uv sync --project backend --locked
```

环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOWTEST_MCP_TRANSPORT` | `stdio` | `stdio` 或 `streamable-http` |
| `FLOWTEST_MCP_API_BASE_URL` | `http://localhost:8000` | FlowTest Application API 根地址，不要附加 `/api/v1` |
| `FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN` | 空 | Service Account Token |
| `FLOWTEST_MCP_HOST` | `127.0.0.1` | HTTP Gateway 监听地址 |
| `FLOWTEST_MCP_PORT` | `8765` | HTTP Gateway 监听端口 |
| `FLOWTEST_MCP_PATH` | `/mcp` | Streamable HTTP 路径 |

命令参数会覆盖相应环境变量。Token 的命令行参数名是 `--token`；自动化中优先使用环境变量，避免 Token 出现在进程列表和 Shell 历史。

### 8.4 stdio 接入

stdio 适合本机 MCP 客户端，由客户端直接启动 Gateway 子进程：

```bash
FLOWTEST_MCP_API_BASE_URL=http://localhost:8000 \
FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN='ftsa_替换为真实令牌' \
uv run --project backend flowtest-mcp --transport stdio
```

通用 MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "flowtest": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/FlowTest/backend",
        "flowtest-mcp",
        "--transport",
        "stdio"
      ],
      "env": {
        "FLOWTEST_MCP_API_BASE_URL": "https://flowtest.example.com",
        "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN": "ftsa_替换为真实令牌"
      }
    }
  }
}
```

注意：

- `--project` 必须使用客户端主机可访问的真实绝对路径。
- `command` 必须位于 MCP 客户端进程的 PATH；找不到 `uv` 时填写其绝对路径。
- JSON 文件权限应限制为当前用户；更推荐由客户端的 Secret/环境变量机制注入 Token。
- stdio 模式的标准输出属于 MCP 协议通道，不要在启动脚本中向 stdout 打印调试信息或 Token。

### 8.5 Streamable HTTP 接入

启动本地 HTTP Gateway：

```bash
FLOWTEST_MCP_API_BASE_URL=https://flowtest.example.com \
uv run --project backend flowtest-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --path /mcp
```

客户端连接地址：

```text
http://127.0.0.1:8765/mcp
```

认证有两种方式：

1. **每个客户端发送 Header**：`Authorization: Bearer ftsa_...`。Gateway 会把当前请求 Token 传给 Application API，适合多客户端和独立审计。
2. **Gateway 配置固定 Token**：设置 `FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN`。只适合单一受控客户端，不适合多人共享服务。

生产部署要求：

- Gateway 默认绑定 `127.0.0.1`，应通过受控反向代理终止 TLS。
- 如果改为 `0.0.0.0`，必须同时配置防火墙、来源限制、HTTPS、请求大小和超时策略。
- 不在 URL Query、日志或错误消息中传 Token。
- 为不同系统签发独立 Service Account，便于撤销和审计，不共享一个全能 Token。
- MCP Gateway 可以关闭；关闭不会影响普通 Web、REST、Standalone、Compact 或 Full 功能。

### 8.6 Tools

当前共 21 个 Tool。

#### 8.6.1 项目、服务、契约和运行证据

| Tool | 主要参数 | 作用 |
| --- | --- | --- |
| `flowtest.list_projects` | `page`、`page_size` | 列出当前组织和账号可见项目 |
| `flowtest.inspect_project` | `project_id` | 读取安全的项目元数据 |
| `flowtest.discover_services` | `project_id`、可选 `environment_id` | 读取项目 Service 和可用 Endpoint Variant，不返回 Credential |
| `flowtest.inspect_contract` | `project_id`、可选 `api_definition_id` | 读取已净化的当前 API 契约结构；不返回 Example、PII、Token 或 Secret Enum 原值 |
| `flowtest.inspect_flow` | `workflow_id` | 读取工作流草稿拓扑、安全操作引用和草稿指纹 |
| `flowtest.inspect_run_evidence` | `execution_id` | 读取执行状态证据，不返回原始请求/响应 Body |

#### 8.6.2 FlowSpec

| Tool | 主要参数 | 作用 |
| --- | --- | --- |
| `flowtest.export_flowspec` | `project_id`、`workflow_id`、可选 `version` | 导出可移植且已验证的 FlowSpec |
| `flowtest.validate_flowspec` | `project_id`、`spec` | 只校验和规范化，不持久化 |
| `flowtest.diff_flowspec` | `project_id`、`after`、可选 `before` | 比较两个 FlowSpec，不持久化 |

#### 8.6.3 Test Engineering、覆盖和影响

| Tool | 主要参数 | 作用 |
| --- | --- | --- |
| `flowtest.generate_test_design` | `project_id`、`api_definition_id`、可选 `generation_policy` | 基于契约生成 Scenario、Oracle、Coverage 和证据，不持久化 |
| `flowtest.inspect_test_evidence` | `project_id`、`api_definition_id` | 读取有证据支撑的生成测试语义，不持久化 |
| `flowtest.analyze_test_coverage` | `project_id`、`api_definition_id`、可选 `generation_policy` | 输出维度覆盖和明确缺口，不持久化 |
| `flowtest.inspect_change_impact` | `project_id`、`impact_run_id` | 读取结构化契约变化、覆盖缺口和已选资产 |

Coverage 输出中的完整覆盖不再只表示“某个值出现过”。调用方应同时检查
Operation、Location、Field、Value、Expected Category 和 `oracle_set_fingerprint`。Status 400 与 422、
Status 200 与 201、不同 Response Schema 都属于不同覆盖要求；没有确定性 Oracle 时只能
解读为 `PARTIAL` 或 `UNKNOWN`。MCP 只提供分析与 Draft 提案，不能为 Release Gap 创建 Waiver。

#### 8.6.4 外部证据分析

| Tool | 主要参数 | 作用 |
| --- | --- | --- |
| `flowtest.inspect_source_evidence` | `project_id`、`snapshot` | 仅以 AST 分析有界、允许列表中的 Python 源码快照，不执行源码 |
| `flowtest.inspect_data_profile` | `project_id`、`profile` | 分析已类型化、已脱敏的数据画像，不接收 Credential 或原始数据行 |

#### 8.6.5 受控写入

Context Tool 使用独立 `mcp:evidence:write` Scope：

| Tool | 主要参数 | 作用 |
| --- | --- | --- |
| `flowtest.begin_test_context` | `project_id`、`name`、`objective`、Evidence Requirement 与有版本来源 | 创建首个不可变 Context Revision |
| `flowtest.inspect_context_requirements` | `context_id` | 读取缺失 Evidence、Conflict、状态和当前 Fingerprint |
| `flowtest.ingest_java_evidence` | `context_id`、强类型 Java Evidence | 接收外部 Code MCP 的 Java/Spring 结构证据；不连接外部 MCP、不执行代码 |
| `flowtest.ingest_database_evidence` | `context_id`、强类型 DB Evidence | 接收设计期 Schema、约束与脱敏分布；不接受 SQL 或原始数据行 |
| `flowtest.ingest_external_evidence` | `context_id`、严格 Evidence Envelope | 校验并生成新的不可变 Revision；原始 Finding 不在响应中返回 |
| `flowtest.inspect_entity_mapping` | `context_id` | 读取可追溯 Operation/Field/State 候选与未解决歧义；不自动选择 |
| `flowtest.inspect_test_context` | `context_id` | 读取当前 Revision 与脱敏 Evidence 摘要 |
| `flowtest.close_test_context` | `context_id` | 关闭 Context，阻止继续接收 Evidence 或创建 Proposal |

Evidence Envelope 必须有 Provider/Source Revision、Subject、Finding Fingerprint、Confidence 与
Deterministic 标记。未知字段、跨项目引用、无界内容、Prompt Instruction 字段和 Secret/Token/Cookie/
Password/连接串/PEM/原始 PII 会被拒绝；代码注释、接口描述和数据库 Comment 始终只是不可信数据。

Test Design 的受控写入使用既有 `mcp:write` Scope：

| Tool | 主要参数 | 作用 |
| --- | --- | --- |
| `flowtest.propose_test_design` | `project_id`、`title`、`confidence`、`risk_level`、`design`、`idempotency_key`、`dry_run`、可选 `test_cases`/`source_ref` | 预览或创建待人工审核的 Test Design ChangeSet Draft；从不自动应用 |

`propose_test_design` 的重要规则：

- 默认 `dry_run=true`，只返回预览。
- 真正创建 Draft 时必须显式传 `dry_run=false`。
- `idempotency_key` 必填；相同账号、项目、操作和相同请求可安全重试，不同请求复用同一键会冲突。
- `risk_level` 取 `low`、`medium`、`high` 或 `critical`。
- `confidence` 范围为 0～1。
- `source_ref` 如提供，必须是无 Query 的安全 `mcp://...` 引用。
- `design` 和 `test_cases` 不能包含 Secret、Token、Authorization、Cookie、Password、API Key、Credential 或其他敏感路径。
- 实际写入只创建 `draft` ChangeSet。后续高风险审批、逐项接受/编辑/拒绝和物化在 Web“AI 变更集”或受保护 REST 人工入口完成。
- Tool 本身不能发布工作流、运行测试、删除资产、修改权限或创建 Credential。

建议让 MCP 客户端先 dry-run：

```text
请先调用 flowtest.propose_test_design，dry_run 保持 true；
列出 warnings、confidence、evidence_refs 和将创建的项目资产，等待我确认。
```

确认后再明确要求使用新的幂等键和 `dry_run=false` 创建 Draft。

### 8.7 Resources

| Resource URI | 内容 |
| --- | --- |
| `flowtest://projects/{project_id}` | 安全项目元数据 |
| `flowtest://projects/{project_id}/services` | Service 和 Endpoint Variant 发现结果 |
| `flowtest://projects/{project_id}/contract` | 当前 API 契约结构 |
| `flowtest://drafts/{workflow_id}` | 工作流草稿拓扑和指纹 |
| `flowtest://runs/{execution_id}/evidence` | 执行状态证据 |

Resource 返回 JSON，仍经过与 Tool 相同的组织、项目、Scope、脱敏和审计边界。URI 中的 ID 不是授权凭据，猜到 ID 也不能越权读取。

### 8.8 Prompts

| Prompt | 参数 | 用途 |
| --- | --- | --- |
| `design_data_case` | 可选 `project_id` | 梳理数据场景、边界和脱敏要求，不写数据源、不执行工作流 |
| `discover_api_workflow` | 可选 `project_id` | 先读取项目、Service 和 Contract，再提出只读工作流候选 |
| `migrate_collection` | 可选 `project_id` | 比较集合结构和兼容性风险，只输出待审核建议 |
| `review_flow_draft` | 可选 `workflow_id` | 审查拓扑、目标引用和覆盖风险 |
| `triage_failure` | 可选 `execution_id` | 基于脱敏 Evidence 分类失败，不自动重试或改状态 |

Prompt 是安全操作模板，不是额外权限。客户端仍需显式调用有权使用的 Tool/Resource。

### 8.9 标准返回 Envelope

MCP 只读 Tool 的成功结果包含：

```json
{
  "data": {},
  "evidence_refs": [
    {
      "uri": "flowtest://...",
      "kind": "...",
      "version": "..."
    }
  ],
  "confidence": 1.0,
  "redactions": [],
  "trace_id": "...",
  "warnings": []
}
```

字段说明：

- `data`：已过滤的业务数据。
- `evidence_refs`：结论所依据的版本化证据，不应被模型忽略。
- `confidence`：0～1；低置信度结论必须人工复核。
- `redactions`：被省略或脱敏的字段路径。
- `trace_id`：排查请求和审计事件的关联 ID。
- `warnings`：能力限制、缺失证据或治理警告。

调用方不应只读取 `data`，而应同时展示 `evidence_refs`、`confidence`、`redactions`、`warnings` 和 `trace_id`。

### 8.10 推荐 MCP 使用流程

#### 场景 A：发现接口并设计工作流

1. `flowtest.list_projects` 找到项目 ID。
2. `flowtest.inspect_project` 确认项目元数据。
3. `flowtest.discover_services` 获取 Service 和环境 Variant。
4. `flowtest.inspect_contract` 获取接口结构。
5. `flowtest.generate_test_design` 或 `flowtest.analyze_test_coverage` 生成候选。
6. 外部客户端只输出工作流建议和证据引用。
7. 人工在 FlowTest“流程编排”中创建/检查工作流，或走 ChangeSet Draft 审核。

#### 场景 B：审查 FlowSpec 迁移

1. `flowtest.export_flowspec` 导出源工作流。
2. `flowtest.validate_flowspec` 校验目标 Spec。
3. `flowtest.diff_flowspec` 展示迁移差异。
4. 人工在 Web 中完成 Portable Resource Mapping、Review 和 Apply。

#### 场景 C：失败分类

1. `flowtest.inspect_run_evidence` 读取脱敏运行状态。
2. 使用 `triage_failure` Prompt 约束分析范围。
3. 输出失败分类、证据引用、置信度和需要人工确认的下一步。
4. 不自动重试，不修改运行状态；需要重放时回到 Web 由有执行权限的用户操作。

#### 场景 D：提交测试设计 Draft

1. 先读取 Contract/Coverage/Evidence。
2. 用 `dry_run=true` 调用 `flowtest.propose_test_design`。
3. 人工检查警告、风险等级、测试用例数量和敏感字段。
4. 明确确认后使用新的幂等键和 `dry_run=false` 创建 Draft。
5. 在“AI 变更集”逐项 Review；高风险项先完成人工审批。

### 8.11 MCP 常见问题

| 错误/现象 | 原因 | 处理方式 |
| --- | --- | --- |
| `MCP_AUTHENTICATION_REQUIRED` | 未传 Service Account Token | 配置环境变量或 Bearer Header |
| `INVALID_SERVICE_ACCOUNT_TOKEN` | Token 错误、撤销或格式不对 | 轮换/重签 Token；确认以 `ftsa_` 开头 |
| `SERVICE_ACCOUNT_EXPIRED` | Service Account 已过期 | 由组织管理员重新签发 |
| `MCP_SCOPE_REQUIRED` | 缺少调用所需的独立 MCP Scope | 按用途签发 `mcp:read`、`mcp:write`、`mcp:evidence:write` 或 `mcp:flow:propose`；旧 Scope 不静默扩大 |
| 项目返回不存在 | 跨组织或签发人无项目权限 | 检查组织上下文和项目成员关系，不通过 ID 猜测绕过 |
| `MCP_GATEWAY_UNAVAILABLE` | API 地址错误、网络/TLS 失败或后端未就绪 | 检查 `FLOWTEST_MCP_API_BASE_URL`、Readiness 和代理日志 |
| `MCP_GATEWAY_INVALID_RESPONSE` | 网关收到非预期 Application API 响应 | 核对 API/MCP 版本和反向代理，不记录响应 Body 中的敏感值 |
| ChangeSet 幂等冲突 | 同一 Key 被不同请求复用 | 为新的业务提案生成新 Key |
| 敏感输入被拒绝 | design/test_cases 包含 Token、Secret 等路径 | 改用引用或脱敏元数据，不降低校验标准 |
| HTTP 客户端能连但 Tool 无结果 | Token 未随请求 Header 传入，且 Gateway 无固定 Token | 配置 `Authorization: Bearer ...` |

排障时保留 `trace_id`、时间、Tool 名称、客户端版本和非敏感参数结构；不要把 Token、Authorization Header、Cookie 或原始请求/响应 Body 发到日志、聊天或工单。

## 9. 其他业务模块

### 9.1 质量总览

用于查看选定项目的执行数量、通过率、失败分类、趋势和重点风险，并跳转到影响分析、质量中心或发布门禁。总览是聚合入口，不替代执行详情和证据下钻。

### 9.2 服务目录与契约中心

服务目录登记稳定服务标识、协议类型、说明和依赖；契约中心统一管理 OpenAPI 和 Consumer-Driven Contract，执行 Provider 验证并形成兼容判断。服务目录不保存 Credential；真实请求目标在“请求目标”维护。

### 9.3 多协议接口工作台

用于管理和调试：

- GraphQL Schema、Query/Mutation。
- gRPC Descriptor、Reflection 和 Method。
- Kafka Event Source、Produce/Consume。
- WebSocket Event Source 和 Exchange。

协议资产以不可变版本进入工作流 Snapshot。调试成功不代表任意 Runner 都具备相同网络区和 Capability，发布前应确认运行资源。

### 9.4 测试资产

管理可复用的 TestCase、模板和 Suite。草稿可编辑，发布版本不可变；测试计划执行时固定展开快照，后续编辑不会改写历史任务。

### 9.5 数据与 Mock

- Credential 支持 PostgreSQL、MySQL、Redis、gRPC mTLS 等类型，并可使用平台 AES-256-GCM 或管理员配置的 Vault KV v2。
- 数据节点只执行白名单只读操作。
- Mock 服务由静态路由、状态码、Header、Body 和日志组成，不执行用户脚本。
- 删除 Credential 前应检查工作流引用；生产数据源应使用专用只读账号。

### 9.6 任务执行

将已发布工作流和测试资产组成批量计划，通过 Worker 执行。支持定时、CI Token、签名 Webhook、取消和运行历史。CI/Webhook 触发应使用独立 Token、签名和 Idempotency-Key，不共享管理员登录令牌。

### 9.7 性能实验室

使用声明式场景生成平台内部 k6 程序，管理负载、阈值、基线和发布门禁证据。只在支持的 Full 档位和性能 Worker 中启用；Compact/Standalone 明确关闭时不要把页面不可用误判为普通错误。

### 9.8 环境实验室

系统管理员登记签名、不可变 Environment Template，项目用户按模板 Provision 隔离环境，等待健康检查和 Seed 完成后使用，再执行幂等 Cleanup。镜像必须匹配管理员白名单。只在支持的运行档位启用。

### 9.9 Test Engineering

从 API Canonical Contract 和 Evidence 确定性生成 Scenario、Oracle 和 Coverage。页面会展示 Contract Completeness、Operation Identity、参数 Location、Auth Mode、Suppression、Evidence Conflict、Normative/Observed 角色以及 Materializable/Design-only 原因。生成结果先进入 Draft/Review，不直接进入执行体系。

- `complete` 表示契约结构可完整参与生成；`partial`/`legacy_partial` 表示结构不完整；`redacted_partial` 表示敏感语义值已安全删除。
- Contract、用户确认规则、确定性源码验证和显式数据库 Check Constraint 属于规范性 Evidence；数据样本最小/最大值和候选枚举只属于观察统计，不能自动产生非法 Oracle。
- 当前 Pairwise 只提供有界代表性成对组合；Coverage 中未证明的组合仍是 Gap。State 开关缺少显式状态证据时返回 unavailable，不会 silent no-op。
- Basic Test Knowledge Graph 只表达当前已有的 Operation/Schema/Evidence 关系，不代表完整业务知识图谱。
- 只有唯一确定性 Oracle、无冲突、无敏感测试数据缺口且请求可真实表示的场景才能物化为 Workflow/TestCase。

### 9.10 影响分析和变更回归

影响分析读取 Git、OpenAPI、GraphQL 或 Proto 的结构化变化，建立服务/接口/测试资产影响图并生成智能选择。变更回归把 Change、Impact、测试选择、缺失测试审核、执行证据和 Release Gate 串成一条链路。

变更回归页面分别展示 Asset Mapping、Project Known Semantic Coverage 和 Current Test Plan Semantic Coverage。语义覆盖绑定 Service、Method、规范化 Path、请求 Location、Field、Value、Expected Category 和 Oracle Set Fingerprint；Inventory 的 `body.quantity=999` 不会覆盖 Orders 的同名字段，没有确定性 Oracle 的值也不算完整覆盖。

发布缺口以“当前 TestPlan ∩ Impact Selected Assets”为准。项目中已有精确覆盖、但未进入本次计划时，
后端默认阻断 Approve、Execute 和 Release Gate，不再只是建议。用户必须选择以下一种处理：

1. 在 `Existing Asset` 列显式将系统验证过的 Workflow/TestCase 加入当前计划；资产必须属于当前项目、
   Impact Selected Scope，且覆盖完整语义 Token。加入后只重算 Coverage，不自动执行。
2. 由人工 User 对每个 Gap 单独填写不少于 10 字的 Reason，可选设置 Expiry，创建可审计 Waiver。
   Service Account/CI Token 不能 Waive。Waiver 显示为 `WAIVED`，永远不显示为 `COVERED`。

Approve、Execute 和 Release Gate 都会重新计算；审批后删除 Plan Item、修改已发布 Workflow、
Contract 变更或 Waiver 过期，都会恢复阻断。多 Service 共用同一 Method/Path 时，页面显示 Service、
API Version 和 Contract Fingerprint；无法唯一定位时必须人工选择，系统不会选第一个候选。

位置化变更支持 Path、Query、Header、Cookie 和 Body 的 minimum/maximum、exclusive boundary、长度、枚举、pattern 和 format。找不到唯一 Operation/Location/Field 时保持 blocker/requires-review，不会回退成虚构的 `body.value`。

### 9.11 质量中心和发布门禁

质量中心管理 CI Gate、Flaky 隔离、基线比较和 JUnit 产物。发布门禁以不可变证据快照聚合质量、契约、影响、风险、性能和 Runner 信息，输出可解释的 `PASS` 或 `BLOCK`。证据缺失应显示为缺失或阻断，不能伪装为通过。

### 9.12 AI 助手和 AI 变更集

AI 助手只接收 Schema 和脱敏元数据，生成可审核建议，不读取 Secret、不自动发布、不自动执行。AI/MCP 建议进入 ChangeSet 后，由用户逐项接受、编辑或拒绝；高风险建议需要额外人工审批。

### 9.13 测试报告

查看执行趋势、失败分类、工作流步骤、每次重试和脱敏请求/响应；支持导出离线 HTML。报告中的“无 Body”或脱敏字段不等于执行时没有数据，可能是安全策略主动省略。

### 9.14 组织治理

组织 Owner/Admin 管理组织成员、Service Account、配额、Runner 策略、审计保留和 Support Bundle 脱敏清单。当前页面可以创建 Key Rotation Plan 和元数据，但真实 Key Apply/Rollback 尚未实现；不要把计划状态当作密钥已经轮换。

### 9.15 分布式执行面和平台管理

系统管理员维护 Worker Pool、一次性注册 Token、Runner 身份、心跳、Drain/Resume/Disable、Task、Lease、Fence 和事件。平台管理维护版本化 Capability 和插件边界。注册 Token 和 Runner Token 明文只返回一次，远程控制面必须使用 HTTPS。

## 10. 运行档位

| 能力 | Full | Compact | Standalone |
| --- | --- | --- | --- |
| 项目/API/工作流/报告 | 支持 | 支持 | 支持 |
| PostgreSQL/Redis/MinIO | 支持 | 支持 | 不要求；使用 SQLite/本地附件/进程内适配 |
| 多 Worker/完整执行面 | 支持 | 合并/缩减拓扑 | 进程内低并发 |
| Performance Lab | 可启用 | 关闭 | 关闭 |
| Environment Lab | 可启用 | 关闭 | 关闭 |
| Runner Fabric | 可启用 | 依部署策略 | 关闭 |
| HA/跨进程恢复承诺 | 由生产架构提供 | 单机边界 | 不承诺 |
| MCP Gateway | 可独立部署 | 可同机或独立部署 | 可本地 stdio |

切换档位前应阅读部署兼容矩阵并备份。Full/Compact 共享 Schema 和存储契约；Standalone 数据迁移使用正式 Transfer 流程。

## 11. 安全使用要求

1. 真实密码、Token、Cookie、Authorization、API Key 和 Credential 不进入 Git、FlowSpec、普通变量、日志、截图或工单。
2. Secret 和 Service Account Token 使用专用 Secret Store；令牌按系统、环境和用途分离。
3. 生产部署启用 TLS、出站白名单、最小权限、审计和保留策略。
4. 目标 URL、上传文件、导入文档、工作流定义、模板、Runner 结果和 MCP 输入均视为不可信。
5. 不为通过测试而关闭生产出站策略、TLS 校验、人工审批或证据门禁。
6. 重放、重试和调试写接口前确认目标幂等性和隔离环境。
7. Viewer 只读；不要用共享 Owner 账号执行日常自动化。
8. MCP 输出中的低置信度、Warnings 和 Redactions 必须在下游展示，不能只截取有利结论。

## 12. 通用错误和排障

Application API 的对外错误格式为：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "面向用户的安全消息",
    "details": null,
    "trace_id": "..."
  }
}
```

常见 HTTP 状态：

| 状态 | 含义 | 排查方向 |
| --- | --- | --- |
| 401 | 未登录、登录过期或服务账号 Token 无效 | 重新认证；不要把 Token 打印出来 |
| 403 | 角色、Scope、首次改密或功能权限不足 | 检查组织/项目角色、MCP Scope 和运行档位 |
| 404 | 资源不存在或因租户隔离不可见 | 核对组织、项目和 ID；不要据此推断其他租户资源存在 |
| 409 | 修订、幂等、状态或唯一性冲突 | 刷新资源，使用正确修订或新的业务幂等键 |
| 422 | 配置、变量、DAG、Schema 或安全校验失败 | 根据 `details` 的安全字段定位输入 |
| 429 | 超过限流或并发配额 | 等待并降低频率，不循环无退避重试 |
| 500/502/503 | 应用、上游或网关暂不可用 | 记录 Trace ID，检查 Readiness、Worker 和非敏感日志 |

推荐排障顺序：

1. 记录页面时间、项目、操作、错误码和 Trace ID。
2. 检查 `/api/v1/ready` 和 `/api/v1/runtime-profile`。
3. 检查当前组织、项目角色、Feature Flag 和运行档位。
4. 对接口检查最终请求预览、Service/Variant、Connectivity、变量来源和出站策略。
5. 对工作流检查发布版本、Snapshot、失败节点、每次尝试和上游映射。
6. 对 MCP 检查 Gateway 地址、Transport、Service Account 状态和 Scope。
7. 只收集脱敏日志和 Support Bundle；任何时候都不要复制 Secret 明文。

## 13. 术语表

| 术语 | 含义 |
| --- | --- |
| API Definition | 接口稳定身份 |
| API Version | 不可变请求模板版本 |
| Workflow Draft | 可编辑工作流草稿和修订 |
| Workflow Version | 发布后的不可变 DAG |
| Execution Snapshot | 一次执行固定的工作流、API、环境和目标材料 |
| Service | 请求目标或服务目录中的稳定服务标识，具体含义看所在模块 |
| Endpoint Variant | 某 Service 在某环境中的具体网络目标版本/变体 |
| Artifact | 文件、二进制响应或报告等对象资产 |
| Secret | HTTP 模板使用的写入式加密敏感值 |
| Credential | SQL/Redis/gRPC 等受控能力使用的连接凭据 |
| FlowSpec | 不依赖源实例 UUID 的可移植工作流描述 |
| ChangeSet | 需要人工逐项 Review 的结构化变更集合 |
| Evidence Ref | 指向结论来源及版本的安全引用 |
| Trace ID | 贯穿请求、错误和审计的关联标识 |
| MCP | Model Context Protocol，对外提供受控工具、资源和提示模板 |
| Lease/Fence | 分布式执行中限制任务所有权和旧 Runner 写入的机制 |

## 14. 推荐日常检查清单

接口变更前：

- [ ] 确认项目和环境。
- [ ] 检查 Service/Endpoint Variant 和 Connectivity。
- [ ] Secret 使用引用，不填明文。
- [ ] 预览最终请求并确认变量/Header 来源。
- [ ] 保存不可变 API 新版本。

工作流发布前：

- [ ] 每个 API/协议节点固定了正确版本。
- [ ] Start/End、条件边、汇合和错误传播符合预期。
- [ ] Dataset、Credential、子流程和 Endpoint Variant 均存在且可用。
- [ ] 写接口具备幂等或在隔离环境执行。
- [ ] 发布后先用测试环境运行并下钻 Snapshot。

MCP 上线前：

- [ ] 每个客户端使用独立最小权限 Service Account。
- [ ] Token 只进入 Secret Store/安全 Header，不进入 Git 和命令历史。
- [ ] API Base URL 不附加 `/api/v1`，并已通过 Readiness。
- [ ] 远程 HTTP 使用 TLS、来源限制和 `Authorization: Bearer ...`。
- [ ] 下游完整处理 Evidence、Confidence、Redactions、Warnings 和 Trace ID。
- [ ] 所有写入先 dry-run，真实提案只创建 Draft 并由人工 Review。

## 15. S47.4 变更回归审核操作

### 15.1 如何理解 Operation Coverage

变更回归页的“已覆盖”不只表示 Method/Path 一样。系统同时核对 API Definition、
API Version、Contract Fingerprint、Service、Method、归一化 Path、Portable Operation Ref，
以及值、预期分类和 Oracle Set。因此：

- 同一 API 的 v1 测试不会代替 v2 测试。
- 版本号相同但 Contract Fingerprint 不同时，状态为 `CONTRACT_MISMATCH`。
- Version 不同时，状态为 `VERSION_MISMATCH`。
- 没有确定性且对请求必达的 Assert 时，只能是 `PARTIAL/UNKNOWN`，不是 `COVERED`。

### 15.2 处理多 Service Operation 歧义

当两个 Service 都有相同 Method/Path 时，页面会显示 Service、API ID、Version、Path、
Portable Ref 和 Contract Fingerprint，并保持 Review Blocker。审核人需选择明确的 API
Definition 和固定版本。确认后系统会使用该版本的 Canonical Contract 重新生成
TestDesign，页面显示旧/新设计指纹、场景数和 Oracle 数。不能直接物化旧的合成草案。

### 15.3 续签过期 Semantic Gap Waiver

豁免仍必须逐 Gap 操作，Reason 必填，且只能由人工用户创建。过期后选择
“Renew Waiver”会创建 Revision 2（或下一 Revision），不会覆盖 Revision 1。历史表会显示
Revision、Supersedes、Approver、Approved At、Expiry 和 Active/Expired。同一 Gap 只有最高且
未过期、仍匹配当前 Contract Requirement 的 Revision 可通过 Approve/Execute/Release Gate；
Waiver 状态仍是 `WAIVED`，永远不显示为 `COVERED`。

### 15.4 Workflow Assert 覆盖规则

系统只读取 Published Workflow Version，且 Assert 必须能从具体 Request Node 沿执行图必然
到达：线性 Assert 和分支汇合后的 Assert 可以形成完整覆盖；只在某个分支中的 Assert
是 Partial；与 Request 断开的 Assert 不计覆盖；循环存在无法证明必达的路径时显示
Unknown/Requires Review。在审批前应展开 Oracle Reachability 列核对这一状态。
# S47.5：固定版本计划与实际执行证据

创建 Change Regression 时，“生成缺失测试 Draft”开关只决定是否创建供人工审核的草案。
无论开关是否关闭，系统都会解析 Operation、生成语义需求、计算 Project/Current Plan
Coverage，并在缺口未解决时阻断 Approve、Execute 和 Release Gate。

审批和执行前，Current Plan Coverage 使用计划项保存的固定 `target_version` 与
`workflow_version`，不会读取资产最新版本。TestCase 使用已发布的 TestCaseVersion Definition，
不会读取 Draft。Release Gate 则只读取本次 TestPlanRun 的不可变 RunItem 快照；只有 Passed
Item 算覆盖，Quarantined、Cancelled、Failed 或未执行 Item 均不算。

Test Engineering 物化出的 Workflow/TestCase 会显示为 Generated Assets。先由人工发布资产，
再在语义缺口的 Recommended Asset 中选择明确版本并执行 Add to Plan。系统会校验资产属于
当前 Change Key、确实覆盖该 Requirement，并写入 Audit；不会自动发布或自动执行。

若 OpenAPI Change 显示 Contract Mismatch，表示本次 Current Contract Fingerprint 在项目 API
版本中没有精确对应项。请先导入/同步 Current OpenAPI，再重新分析或明确选择精确版本；系统
不会再用相同 Service/Method/Path 的旧 Contract 代替。

# S47.6：运行时发布证据

Approve 和 Execute 前仍使用当前 TestPlan 的固定版本做“预计覆盖”检查。Release Gate 不再仅凭
整个 Workflow/TestCase Run Item 已通过就认定覆盖，而是沿本次执行证据链逐节点核对：

```text
TestPlanRunItem
→ WorkflowExecution（含已实际运行的数据集子执行）
→ WorkflowNodeExecution
→ NodeResult / HTTP Observation
```

只有 API Node 实际执行且状态为 `passed`、最终 Method/Path/Service 和请求值与语义需求一致、
Response Status 与 Oracle 一致，并且关联的 Assert Node 实际执行且通过，才显示为 Release
Coverage。最终请求值取自 HTTP Observation，因此 TestPlan 的 Runtime Variable、Runtime Header、
节点 Mapping、Query、Cookie、Body、Path 和数据集行造成的变化都会反映在结果中。敏感值被脱敏后
无法证明精确相等时，系统采用安全的未覆盖结果，不会用静态默认值补偿。

以下情况均不能形成最终发布覆盖：API/Assert 被条件分支跳过、节点失败或取消、运行时值与计划
语义不一致、某个数据集行未执行、缺少成功 HTTP Observation。页面的 Coverage Basis 会显示
“实际节点证据”，并列出匹配 Fact、Passed API Node 和 Workflow Execution 数量。

TestPlanRun 仍处于 Queued/Running 时调用 Release Gate 会返回
`409 CHANGE_REGRESSION_EXECUTION_PENDING`，不会写入 Blocked 状态、Release Evidence 或
Release Decision。运行完成后可再次评估。Failed 或 Cancelled 的 Change Regression 执行始终
阻断发布，即使 Release Policy 未启用 Quality Gate，也不会隐式放行。

Suite 计划项在审批与执行前按固定 SuiteVersion 展开到其中固定的 TestCaseVersion；后续修改
Suite Draft 不会改变覆盖。若 Gap 是 `VERSION_MISMATCH` 或 `CONTRACT_MISMATCH`，页面显示
“Replace Plan Version”，人工确认后替换同一计划资产的固定版本、写入 Audit 并重新计算；系统
仍不会自动执行。

### S47.7 发布证据与生成请求补充说明

对于明确绑定 Service 的 Operation，实际 HTTP Observation 必须带有并精确匹配该
`service_key`；缺失或匹配到另一 Service 都不计入 Release Coverage。仅从旧
`Environment.base_url` 路径迁移的 `unassigned` Operation 保留非约束兼容。

已生成 Release Decision 的终态回归运行重复调用 Release Gate 时，系统在确认关联
TestPlanRun 仍为终态后返回同一 Decision、Evidence 和 Stage，不会用事后 Plan
修改或 Waiver 过期重写历史结论。

Change Regression 为单个变更字段生成 Boundary Scenario 时，最终请求以完整当前
Canonical Contract 的有效请求为基线，再叠加目标变异。因此不会因为只测
`quantity` 而丢失同一 Body 中其他必填字段。这些基准值不会被误认为新的
变更覆盖 Requirement，Coverage Token 仍只跟踪目标字段、值、分类和 Oracle Set。
