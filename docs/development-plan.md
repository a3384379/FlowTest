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
| S5（已完成） | Workflow 数据模型与执行内核 | Workflow/Version、Node/Edge、Snapshot；DAG 校验；ExecutionContext；失败传播、超时、重试和取消 | 循环、悬空边、缺失配置可在运行前定位；历史执行绑定不可变快照；串并行行为测试通过 |
| S6（已完成） | 可视化流程最小闭环 | React Flow 画布；Start/API/End 节点；拖拽、连线、保存；DAG 串行/并行执行；Redis Pub/Sub + WebSocket 状态推送 | 可视化搭建 A→B/C→D 并按依赖并行运行，节点状态实时可见 |
| S7（已完成） | V0.3 字段映射、控制节点与数据驱动 | Extract、Assert、Condition、Delay、Dataset；结构化字段绑定；变量来源追踪；CSV/JSON/Excel 行级执行 | A 响应可映射到 B 请求；条件分支、跳过、断言和数据行子执行可解释 |
| S8（已完成） | 测试计划与任务系统 | Test Plan；批量/手工执行；Celery Worker/Beat；重试、取消；定时任务；CI Token 与签名 Webhook | API 与 Worker 解耦；计划可排队、取消、重试、定时和外部触发且状态一致 |
| S9（已完成） | V0.4 报告与执行中心 | 执行中心；步骤级报告；失败分类；趋势；签名通知；HTML 导出 | 报告可从汇总下钻到脱敏请求/响应、提取和断言；失败可定位到节点 |
| S10（已完成） | 企业治理 | 项目级 RBAC；审计日志；Import Diff/Merge；Secret 与 SSRF 加固；限流和幂等 | 权限矩阵通过；导入变更可审阅选择；安全边界和操作一致性测试通过 |
| S11（已完成） | V1.0 内部发布 | 90 天清理；指标与容量测试；安全扫描；备份恢复；部署、升级与回滚手册；自动化试点验收 | 自动化发布门槛、隔离恢复和告警规则通过；两周稳定性观察在内部上线后执行 |

## S7 完成清单

1. Extract 和 Assert 节点在 ExecutionContext 中记录结构化输入、输出和来源。
2. Condition 和 Delay 节点采用冻结的真假分支、跳过、汇合与失败传播语义。
3. Dataset 节点解析 CSV/JSON/Excel，限制 1000 行并以默认并发 5 形成父子执行。
4. 字段映射支持 A 响应到 B 的 Query/Header/Body/Variable，持久化脱敏映射轨迹。
5. React Flow 节点库、属性面板、条件边、数据集选择、运行聚合及行为测试已完成。
6. Compose 验收覆盖两行数据的真假分支、映射、变量来源和父级聚合。

## S8 完成清单

1. Celery Worker 仅接收执行 ID，使用 `asyncio.Runner` 加载 AES-256-GCM 加密计划并调用独立执行引擎。
2. Celery Beat 领取数据库中的到期计划；Compose 为 Worker 和 Beat 提供独立服务、健康检查和固定 Redis broker/backend。
3. Test Plan 支持最多 100 个固定版本执行项、默认并发 5、应用失败重试、批量聚合和取消传播。
4. 手动、定时、CI Token 和 HMAC-SHA256 Webhook 触发共享持久化 Run/Run Item 状态机。
5. CI Token 固定项目和 `execute:workflow`/`execute:test-plan` 范围，仅保存摘要并支持吊销。
6. Web 任务中心支持计划创建、队列观察、取消、CI Token 和一次性 Webhook Secret 展示。

## S9 完成清单

1. 执行中心从不可变 Snapshot 和节点记录派生汇总、耗时、步骤状态及数据集子执行，不复制报告事实。
2. 步骤报告下钻展示脱敏请求/响应、提取、断言、输入映射、尝试次数和稳定错误码。
3. 失败按断言、超时、网络、HTTP 4xx/5xx、配置、取消和运行错误分类；提供最近 7～90 日趋势。
4. HTML 报告使用安全转义生成并以 `report` Artifact 存入 MinIO，可通过项目授权链路下载。
5. 通用通知 Webhook 使用一次性 AES-GCM Secret、`timestamp.body` HMAC-SHA256 签名和完整投递历史。
6. Web 报告页提供 ECharts 趋势、失败分布、执行下钻、HTML 下载、通知配置和投递状态。

## S10 完成清单

1. 固定 System Admin、Project Owner、Editor、Viewer 权限矩阵，并通过领域能力统一约束成员、安全策略和审计访问。
2. OpenAPI/Postman 重导入采用只读 Diff 与显式 Merge；删除项默认保留，选中后才停用，重复提交保持幂等。
3. API 调试、Workflow 和通知 Webhook 在 DNS 解析后统一执行域名/CIDR 校验，拒绝元数据、回环、链路本地和未授权私网地址。
4. 登录、执行、写操作使用独立 Redis 限流桶；直接执行、Workflow、Test Plan 和 CI 触发统一支持 `Idempotency-Key`。
5. Secret 继续只写不可读；审计详情统一脱敏并保存 Trace ID，Owner 可在 Web 治理页检索项目审计记录。
6. PostgreSQL 真实迁移完成升级、回滚和模型漂移验证；Compose 冒烟覆盖导入、权限、幂等、SSRF、Secret 和审计完整性。

## S11 完成清单

1. 项目保留策略限制为 1～3650 天，默认 90 天；Celery Beat 每日清理过期执行、报告、附件、通知、会话、幂等记录和预览导入，审计日志不随项目清理。
2. `/api/v1/metrics` 暴露归一化 HTTP 指标和执行状态指标；Compose 服务具有健康检查、持久卷和 CPU/内存限制，Nginx 提供 TLS 1.2/1.3 接入模板。
3. 容量脚本以并发 30 执行 300 个请求，要求零失败且 P95 不超过 500 ms；本地 ARM64 验收实际 P95 为 153 ms。
4. PostgreSQL custom-format dump 与 MinIO manifest/SHA-256 备份可在隔离容器和隔离卷中完整恢复，并逐个校验对象哈希。
5. Ruff 安全规则、依赖审计、ShellCheck 和 Grype 镜像扫描进入 CI；未登记的可修复 Critical/High 漏洞会阻止发布，S12 升级 Python 3.13 后已删除原 Python 3.12 临时例外。
6. S11 Compose 冒烟打通登录、令牌提取、查询用户、创建订单、断言和脱敏报告，并覆盖失败、重试、超时、并行、取消、Viewer 拒绝、指标和清理；Playwright 固化登录、治理、报告与主菜单验收。

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

## V2.0 迭代路线

V2.0 保持 `/api/v1` 兼容和单组织 Compose 部署，以 Feature Flag 隔离未完成能力。
任意脚本、Kafka、gRPC、Kubernetes、多租户和完整性能测试保持在 V2.1 边界外。

| 迭代 | 版本目标 | 主要交付 | 状态 |
|---|---|---|---|
| S12 | V1.1 稳定基线 | Python 3.13、依赖/镜像升级、V2 Feature Flags、真实 Workflow 容量基线、试点观察机制 | 代码与自动化门槛已完成；真实两周观察持续记录 |
| S13 | v1.1.0 前端基础产品化 | React Router、项目上下文、深链接、真实 Dashboard | 已完成 |
| S14 | 团队与 API 工作台 | 管理 UI、完整 API 编辑器、HAR/cURL/Bruno/Excel 导入导出 | 已完成 |
| S15 | 测试资产体系 | Test Case/Suite 不可变版本、检索、模板、Diff、Plan Snapshot | 已完成 |
| S16 | v1.5.0 高级 Workflow | Node SDK V2、SubFlow、ForEach、安全表达式、调试与画布增强 | 已完成 |
| S17 | 数据与 Mock | Credential、只读 PostgreSQL/MySQL/Redis 节点、规则化 Mock | 已完成 |
| S18 | 契约自动化 | OpenAPI 用例生成、Breaking Change、Schema 覆盖率、草稿审核 | 已完成 |
| S19 | v1.8.0 质量与规模 | Cron/时区、多队列、配额、Flaky、JUnit、Quality Gate、100/1000 容量 | 已完成 |
| S20 | 企业与可观测性 | OIDC PKCE、团队授权、Vault KV v2、OpenTelemetry、Grafana、可选 PITR | 已完成 |
| S21 | v2.0.0 AI 助手与发布 | 可审核 AI 建议、脱敏/审计/评测、全量试点与发布 | 功能与 CI 完成；`v2.0.0-rc.1` 已固定，真实 RC 观察待执行 |

## V3.0 迭代路线

V3 以 Capability、Runner、Service/Change/Impact/Test Selection/Risk/Release Gate 为主线；
控制面继续使用 Compose，Kubernetes 仅作为可选 Worker Plane。正式发布版本仍须满足 V2 RC 与
V3 各自的真实验收门槛。

| 迭代 | 主要交付 | 状态 |
|---|---|---|
| S22 | Capability SDK V3、Legacy Adapter、NodeResult/Event、Runner/Plugin 边界、V3 原型与 Token | 已完成；PR #25 全绿并 squash 合并 |
| S23 | GraphQL、gRPC 与多协议工作台 | 已完成；PR #26 全绿并 squash 合并，发布 `v3.0.0-alpha.1` |
| S24 | Kafka、WebSocket 与 Exchange | 已完成；PR #27 的 5 项 CI 全绿并 squash 合并 |
| S25 | 声明式 k6 性能实验室 | 已完成；PR #28 的 5 项 CI 全绿并 squash 合并 |
| S26 | 签名环境模板、Provision/Cleanup/TTL | 已完成；PR #29 与 main CI 全绿，发布 `v3.0.0-beta.1` |
| S27 | Pact、契约矩阵、Service Graph、Deployment Check | 已完成；PR #30 与 main CI 全绿，发布 `v3.0.0-beta.2` |
| S28 | 多源 Diff、Impact Graph、Smart Selection、Coverage Matrix | 已完成；PR #31 与 main CI 全绿，发布 `v3.0.0-beta.3` |
| S29 | Worker Pool、PostgreSQL Lease/Fencing、远程 Docker/K8s Worker | 进行中；独立分支已创建，正在冻结 Runner/Lease 边界 |
| S30 | Failure Cluster、Release Risk、AI Change Set | 未开始 |
| S31 | 16 页面产品化、Release Gate、容量/安全/升级回滚与 14 天 RC | 未开始 |

S22 的架构决策见 [`ADR 0018`](adr/0018-capability-sdk-and-runner-boundary.md)，S23 多协议边界见
[`ADR 0019`](adr/0019-multi-protocol-schema-snapshots.md)，S24 事件协议边界见
[`ADR 0020`](adr/0020-event-protocols-and-session-boundary.md)，S25 性能执行边界见
[`ADR 0021`](adr/0021-declarative-performance-runner.md)，S26 环境 Runner 边界见
[`ADR 0022`](adr/0022-signed-environment-runner.md)，S27 Pact 与发布证据边界见
[`ADR 0023`](adr/0023-pact-contract-hub-and-release-evidence.md)，S28 变更影响与确定性选择边界见
[`ADR 0024`](adr/0024-change-impact-and-deterministic-selection.md)，视觉源见
[`FlowTest_V3_UI_CN_HD`](../FlowTest_V3_UI_CN_HD/README.md)。用户要求已授权 S22 在 V2 正式标签前
开始开发，但不得将该授权记录为 `v2.0.0` 发布证据。

S12 的两周试点属于真实时间观察，不以短时自动化代替。记录和签署规则见
[`docs/operations/soak-observation.md`](operations/soak-observation.md)。

## S26 完成清单

1. Environment Template 只由系统管理员注册、创建不可变版本和停用；版本保存规范 JSON、SHA-256 与
   平台签名，Provision 和 Runner 执行前都会重新验证。
2. 类型契约仅允许固定 Digest 镜像、依赖、受限环境变量、HTTP/TCP Health Check、资源上限、TTL 与
   预定义 Seed，明确不提供任意 Compose、命令、脚本、Secret、设备和卷。
3. 镜像必须精确命中部署白名单；独立 Environment Worker 不挂载宿主 Docker Socket，只能通过内部
   Control Network 访问不对宿主发布端口的 DinD daemon。
4. Runner 使用参数数组生成固定 Docker CLI 调用，强制非 root、只读根文件系统、Drop ALL、
   `no-new-privileges`、CPU/内存/PID 上限、随机端口、隔离 bridge 和实例 Label。
5. Idempotency-Key、Fencing Token、TTL、Beat Reconciler 与 Label 枚举清理共同覆盖失败、超时、取消、
   消息重投和 Runner 重启；清理任务可安全重复执行。
6. 中文环境实验室提供模板、版本、Provision、端点、Seed/隔离证据和 Cleanup 状态；迁移、后端、前端、
   真实 Compose、Playwright 和镜像安全门槛纳入 S26 Draft PR 的退出条件。

## S28 完成清单

1. Git Unified Diff、OpenAPI、GraphQL SDL 和 gRPC Proto 统一规范化为有界 Change；平台不拉取外部
   Git、不接收仓库凭据，也不执行用户脚本。
2. 项目显式 Mapping 只接受精确或尾部 `*` Selector，并绑定现有平台测试资产；所有目标继续执行项目
   授权、类型和存在性检查。
3. `explicit_mapping_v1` 使用确定性排序和去重生成 Recommended Tests；没有证据的变更明确列为
   Coverage Gap，不以启发式猜测制造覆盖。
4. Impact Run、Test Selection 和 Coverage Snapshot 持久化 Changes、解释边、矩阵、Gap、摘要及
   Fingerprint，历史结果不依赖瞬时 UI 状态。
5. 中文变更影响页面覆盖 Mapping、四类 Diff、Change→Impacted→Recommended 三列图、原因、Coverage
   Matrix、Gap 与历史；S28 只推荐测试，不自动执行或修改发布门禁。
6. `20260812_0025` 双向迁移、后端/前端全量质量门槛、真实 Compose 四源冒烟、Playwright 中文主路径、
   PR #31 五项 CI 与 main 完整回归均已通过；annotated `v3.0.0-beta.3` 固定到 S28 合并提交。

## S13 完成清单

1. React Router 以 `/projects/{project_id}/{section}` 固化页面与项目上下文，刷新和深链接均不丢失选择。
2. 全局项目选择、侧栏链接和面包屑共享同一 URL 真源；无权限或不存在的项目会回到全局工作台。
3. `/api/v1/dashboard/summary` 与 `/api/v1/dashboard/recent-executions` 从可访问项目、API、Workflow 及真实执行记录聚合数据，继续执行项目隔离。
4. Dashboard 展示资产数量、今日执行/通过率、七日趋势和 API/Workflow 最近运行，时间按 Asia/Shanghai 呈现。
5. Vite 8/Rolldown 按 React、TanStack 和 ECharts 的稳定依赖边界拆包；共享首屏块由约 765 KB 降至约 503 KB，最大按需图表块约 519 KB，均低于 550 KB 告警阈值，并通过真实浏览器加载验证。
6. Vitest 覆盖深链接、默认项目、空项目、URL 切换和非法项目回退；Playwright 覆盖项目页刷新及项目 Dashboard 回跳。

## S14 完成清单

1. 单组织 Team、TeamMember 和 ProjectTeamGrant 已落库；团队只能授予 Editor/Viewer，System Admin 最高、直接项目成员覆盖团队授权，并通过越权、撤销和数据隔离测试。
2. 项目治理页开放用户、团队、项目成员、团队授权、任意层级目录、项目配置、环境与只写 Secret 管理；Secret 列表不返回明文、密文或 nonce。
3. API 工作台可持续编辑 Method、Path、Params、Headers、Auth、Body、提取和断言，每次保存生成不可变版本，并可预览带来源和脱敏值的最终请求。
4. 导入扩展至 HAR、cURL、Bruno 和 Excel，继续使用指纹 Diff/Merge；cURL 只由 `shlex` 解析且拒绝 shell 选项、多个 URL、未知方法和不完整引号，不执行输入内容。
5. API 资产可导出 HAR、cURL、Bruno 和 Excel；认证值统一输出 Secret 引用或脱敏占位，不导出可用凭据。
6. `20260809_0011` 可在真实 PostgreSQL 上 0010→0011→0010→0011 往返；Alembic 漂移检查现同时比较类型和服务器默认值，并对 PostgreSQL JSON 默认值采用结构化比较。
7. Playwright 打通 API v2 保存与预览、环境、目录重命名、变量/Header、Secret、团队成员和团队授权；S3–S11 原业务冒烟保持全绿。

## S15 完成清单

1. Test Case 与 Test Suite 均采用可修改草稿和不可变发布版本；发布内容保存稳定指纹、发布说明与创建人，历史版本没有更新接口。
2. Case 发布时固定已发布 Workflow Version 与 Environment；Suite 发布时固定每项 Case Version，并拒绝重复、跨项目和未发布引用。
3. 资产列表支持名称/说明搜索、标签、模板、克隆和最多 100 项批量目录移动；版本 Diff 返回稳定字段路径及前后值。
4. Test Plan Item 新增兼容的 `target_type/target_id/target_version`，旧 `workflow_id` 请求继续可用；Case/Suite 在计划创建时固定版本，Suite 入队时展开为不可变 Case Snapshot。
5. Web 新增“测试资产”深链接，覆盖用例/套件编辑、发布、Diff、克隆和批量移动；任务中心可直接选择已发布 Workflow、Case 或 Suite。
6. `20260810_0012` 已在真实 PostgreSQL 完成 0011→0012→0011→0012 往返及 Alembic 漂移检查；后端总覆盖率 90.14%，执行引擎 Mapping/Control/Scheduler 分别为 100%/98%/97%，前端覆盖率四项均超过 80%。
7. Playwright 打通“用例两次发布与 Diff → 克隆 → 套件发布 → Test Plan 固定套件目标”，并保持 S14 与 V1 浏览器主路径兼容。

## S16 完成清单

1. Node SDK V2 使用带类型的 Handler Registry 隔离调度器与节点实现；Celery 继续只恢复固定执行计划并调用独立异步引擎。
2. SubFlow 固定同项目已发布版本；父 Snapshot 递归保存子流程定义、指纹、API 和下级引用，发布时禁止递归并限制最大深度 5。
3. ForEach 使用安全 JMESPath 从上游输出取得数组，限制最多 1000 项、默认并发 5、最大 20，并支持 fail-fast 与继续后汇总失败。
4. 工作流版本 Diff 返回稳定字段路径；断点调试裁剪至目标祖先子图，节点重放从原 Execution 加密计划恢复，两者统一脱敏和审计。
5. React Flow 画布支持 SubFlow/ForEach 配置、复制粘贴、50 步撤销重做与拓扑自动布局，选择态不会污染定义历史。
6. 当前明确拒绝把含 Dataset 节点的 Workflow 作为 SubFlow；嵌套 Dataset 在定义父执行/行执行/循环项的兼容持久化协议后再开放。
7. 后端单元/服务/引擎测试、前端交互测试和 Playwright 真实链路覆盖递归拒绝、固定快照、循环并发、版本 Diff、断点与重放。

## S17 完成清单

1. 项目 Credential 使用 AES-256-GCM 与资源绑定 AAD 加密，接口只返回 Host、端口、类型等元数据；Secret 创建、轮换和列表均不可读回。
2. SQL 节点支持 PostgreSQL/MySQL 参数化单条 `SELECT` 或 `WITH ... SELECT`，事务强制只读，限制 30 秒、1000 行和 2 MB；Redis 节点固定八条只读命令及参数边界。
3. 数据节点复用 DNS、域名和私网 CIDR 策略，并在建立连接后校验实际传输对端，阻断 DNS Rebinding；发布阶段校验 Credential 类型和语法，执行计划固定加密材料，公开 Snapshot 不保存 Secret。
4. 规则化 Mock 支持 Method、路径参数、Query/Header 条件、场景、状态码、模板响应和最多 30 秒延迟；公开调度统一限流，模板不执行脚本，传输/安全敏感 Header 和超限请求/响应被拒绝。
5. Mock 请求日志统一脱敏 Authorization、Cookie、Token、Password 和 Secret，并纳入项目保留期清理；配置变更写入审计。
6. Web 新增“数据与 Mock”深链接，提供 Credential、Mock 服务、路由和日志管理；React Flow 新增只读 SQL 与 Redis 节点及类型兼容的 Credential 配置。
7. Alembic `20260810_0013` 已在真实 PostgreSQL 完成 `0012 → 0013 → 0012 → 0013` 漂移校验；后端 167 项测试通过、总覆盖率 90.79%，数据节点执行器 97%；前端 85 项测试通过，四项覆盖率均超过 80%。
8. Compose 八服务健康检查、PostgreSQL/Redis/MinIO 真实集成测试和 Playwright S17 闭环均已通过；前后端依赖审计无已知漏洞。

## S18 完成清单

1. OpenAPI 3.x / Swagger 2.0 文档通过 Schemathesis 校验，按操作生成边界、属性和异常三类待审核草稿，记录生成引擎版本与 Schema SHA-256。
2. Contract Run 保存不可变 Schema、显式/自动基线、added/changed/deleted/unchanged Diff、Breaking Change 证据和字段覆盖率。
3. 破坏性规则覆盖操作、必填请求、请求/响应类型、成功响应和响应字段，每条结果保存稳定代码和路径。
4. 生成草稿只能单次接受或拒绝；接受前可编辑并会再次验证结构，未确认草稿不暴露执行入口，所有决策记录审计。
5. 安全边界拒绝外部 `$ref`、超过 5 MB/64 层/10 万节点/500 操作的文档和超过 256 KB 的编辑定义；生成请求复用 Token/Secret 脱敏。
6. Web 在测试资产中提供契约上传、基线选择、Diff/覆盖率、破坏性提示和生成草稿编辑/接受/拒绝闭环。
7. Alembic `20260811_0014` 提供可升级与可回滚路径；后端、前端、Compose 和 Playwright 验收均覆盖契约主路径。

## S19 完成清单

1. Test Plan 支持五字段 Cron、IANA 时区、0～9 优先级与 `general/data/ai` 队列；间隔与 Cron 互斥且最短周期为 60 秒。
2. 项目级运行并发和排队配额在 PostgreSQL 行锁内检查；达到运行配额的 Worker 延迟领取，达到排队上限的 API 请求明确拒绝。
3. Compose 提供 General、Data、AI 三个独立 Worker；Celery 路由按目标类型分发，同时保持已有 V1/V2 任务兼容。
4. Flaky 使用目标版本唯一键、Upsert 与行锁确定性聚合；Owner 可隔离资产，后续 Plan Snapshot 显式记录 `quarantined`，历史运行不变。
5. Quality Gate 支持通过率、失败数、Flaky、耗时基线回归与 Breaking Change 规则；Web 与 CI Token 接口共享持久化 Evaluation。
6. JUnit XML 从结构化 Run/Item 数据安全导出；质量中心提供门禁、Flaky、隔离、基线摘要和 JUnit 下载。
7. `20260811_0015` 已完成真实 PostgreSQL `0014 → 0015 → 0014 → 0015` 往返与漂移检查；单元、前端、Playwright 和 Compose 冒烟覆盖完整主路径。
8. 容量门槛使用真实 Workflow 验证 100 并发，并在停止所有 Worker 后持久化 1000 个 Run，恢复 Worker 后验证零丢失、零重复终态和唯一 Execution。
