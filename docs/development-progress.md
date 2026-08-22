# FlowTest 开发进度

最后更新：2026-08-22（Asia/Shanghai）
状态：仓库已公开；S30 Failure Intelligence 与 S31 Release Gate/全局搜索已分别通过
PR #33/#34 五项 CI 并 squash 合并。V2→V3 原地升级/回滚小阶段已完成真实资产执行、
MinIO 哈希验证及 PR #35 远程 Upgrade/Security CI；S31 页面产品化的独立服务目录、
项目导航和全局搜索深链小阶段已完成本地及 PR #36 远程验收，质量指挥中心小阶段已完成本地及
PR #37 远程源码验收。用户已授权提前进入 V4，S32～S36 小型化、离线分发、资源/兼容基线、隐私安全诊断、回滚证明和事务式升级已完成本地真实验收，PR #38 的六项远程 CI 亦全部通过。Standalone PR #39 的 Windows Bundle、Backend、Compose Smoke、Security、Upgrade 六类共七项远程检查也已在 `bed1047` 全部通过。72 小时公司试点和人工签署待执行。
`v2.0.0`、`v3.0.0` 正式标签仍分别受真实部署与连续 14 天 RC 观察门槛约束。

## 当前恢复点

- 收口基线：`main@08db725`，PR #37 已完成 S31 质量指挥中心并合并。
- 当前 V4 小型化小阶段由 `codex/s32-runtime-profile-foundation` 承载，从上述干净基线创建；
  用户随后明确要求连续推进 V4 及 S34，因此范围已扩展到 S32～S36 的备份恢复、离线/私有仓库分发、
  事务式无外网升级、容量稳定性、Full↔Compact 兼容、隐私安全诊断和可恢复回滚验收。
- Standalone 代码在独立 `codex/standalone-runtime` 分支继续推进，避免把仍在评审的 Compact Docker
  PR #38 与无 Docker 运行时混在同一提交中。
- 已发布标签：`v1.1.0`、`v1.5.0`、`v1.8.0`、`v2.0.0-rc.1`、`v3.0.0-alpha.1`、
  `v3.0.0-beta.1`、`v3.0.0-beta.2`、`v3.0.0-beta.3`；不得提前创建 `v2.0.0` 或后续 V3 里程碑。
- 用户已明确要求跳过原计划中的等待顺序并开启 V3 开发；该授权不等于完成或豁免 V2 正式发布门槛。
- `FlowTest_V3_UI_CN_HD/` 的 HTML 设计源和 21 张 2560×1440 PNG 基准在 S22 纳入 Git，原始内容保持不变。

## 进行中：V4 Standalone 无 Docker 云桌面部署

1. Standalone 新增独立 `standalone` 运行档位；Full/Compact 的 PostgreSQL、Redis、MinIO 和
   Celery 拓扑保持不变，不把 SQLite 数据迁移回 Docker 档位。
2. Standalone 使用 SQLite WAL、本地附件目录、进程内事件总线、固定窗口限流和后台调度器；
   API、Web、工作流和测试计划在一个 Python 进程内运行，启动时自动创建当前模型基线并记录
   `20260822_0032` Alembic revision。
3. Performance Lab、Environment Lab、Runner Fabric 在该档位固定关闭；事件历史、限流桶和未完成
   进程任务在重启后不恢复，业务状态、附件和加密 Snapshot 持久化到 `data\`。
4. 新增 Windows PowerShell 安装前检查、启动、停止、Readiness/档位验收、备份和离线包构建脚本；离线包可携带
   Python 3.13 运行时与 wheels，公司云桌面无需 Docker、WSL2、Node.js、uv 或数据库服务。
5. 已完成 Standalone 核心单元测试、SQLite/本地存储真实 smoke 和完整应用 lifespan smoke；
   已新增不依赖 Docker 的 Windows 长时稳定性探针 `deploy/standalone/soak.ps1`，只记录健康状态、
   延迟和进程元数据，并在 Windows Bundle CI 中执行短窗口验证；已新增
   `standalone-compact-transfer-v1` 逐表/逐 Artifact 迁移工具及 Windows/Compact 包装脚本；试点与迁移
   责任人、证据字段和签署模板见 `docs/operations/standalone-pilot.md`，当前仍需 Windows x64 云桌面
   实机 72 小时真实观察与 Standalone→Compact 真实迁移演练。

## 已完成：V4 S32～S36 小型化与公司可部署性

1. `full` 保持现有隔离 Worker 拓扑；`compact` 显式使用合并 Worker，并公开可机器验收的
   `/api/v1/runtime-profile` 运行契约。
2. Compact 与 Full 共享 PostgreSQL/Alembic、Redis 和 MinIO 语义；不引入 SQLite、本地 Artifact
   或进程内队列产品分支。
3. Compact 基线收缩为 Web、API、合并 Worker/Beat、PostgreSQL、Redis 和 MinIO 六个容器；
   默认容器内存上限合计约 2.6 GB，只向 Loopback 发布 Web 与 MinIO API。
4. 配置层会拒绝 Compact 误开 Performance Lab 或 Environment Lab，避免将任务发送到缺少
   k6/DinD 的运行时。
5. ARM64 真实 Compose 已完成源码构建、六服务健康检查、Readiness 和 S32 业务 smoke；
   smoke 覆盖登录、项目/API/Workflow 创建、不可变发布、合并 Worker 执行与 Snapshot。
   空闲实测约 918 MiB，未发现 Backend/Worker ERROR、CRITICAL 或 Traceback。
6. Docker-only 备份已对非空 PostgreSQL 和 1 个 MinIO Artifact 生成 custom dump 与 SHA-256 清单；
   备份后项目数从 2 增加到 3，覆盖恢复后回到 2 且新项目不存在，对象集哈希相同。
   恢复后再次执行上传、Workflow 发布和合并 Worker 验收通过。
7. S33 已将基础 Compose 与源码构建 Overlay 分离；Backend/Worker 复用单一镜像，
   私有仓库脚本为 5 个镜像输出 `repository@sha256` 不可变引用。
8. ARM64 真实离线包为 353 MiB；在删除离线 Tag 后从 `images.tar` 重新导入，逐文件摘要、
   5 个镜像 ID/架构、`--pull never --no-build` 六服务启动及 S32 业务 smoke 全部通过。
9. 无外网升级演练先对 5 个真实 Artifact 生成一致性备份，再切换新包的 5 个镜像；
   升级后 Readiness、Artifact 上传/下载、Workflow 发布与执行均通过。
10. S34 实测 1000 次 Live API 在 25 并发下零失败，吞吐约 462 req/s、P95 约 154 ms；
    24 次真实持久化 Workflow 在 6 并发下零失败，P95 约 453 ms，全部 Celery 队列归零。
11. 短周期稳定性探针零失败、零容器重启、零队列积压；Full↔Compact 直接共享卷切换已
    双向验证两组 Project、Artifact、Workflow Version 和 Execution Snapshot。72 小时真实试点不以短测代替。
12. 本机回环 Registry 已真实推送 Backend、Frontend、PostgreSQL、Redis 和 MinIO 五个 ARM64 镜像，
    输出 5 条仓库返回的 `repository@sha256` 引用；发布 Tag 带架构后缀。
13. 当前完整门槛：后端 348 passed/3 skipped、总覆盖率 90.54%；前端 43 文件 167 passed，
    Statements 87.71%、Branches 80.76%、Functions 86.42%、Lines 89.69%；格式、Ruff、mypy、Lint、
    TypeScript、生产构建、Compose 解析和真实 Chromium 登录/质量总览均通过。
14. S35 真实诊断目录含 13 个白名单文件、9 个成功探针和逐文件 SHA-256；精确扫描确认管理员口令、
    数据加密密钥、应用密钥和 MinIO 口令均未命中，且不收集 `.env`、原始日志、对象名称/内容或业务载荷。
15. ARM64 回滚演练对 11 个对象生成一致性备份；一次性 Project/Artifact 在首次恢复后消失，恢复后
    再次写入成功，第二次恢复后探针再次消失且 6 服务健康。S35 离线开发包的 23 个内部文件摘要
    全部通过并包含 5 个新运维工具；PR #38 的 amd64 远程 CI 已复验，自动化不能代替维护窗口审批。
16. S36 使用不同离线 Tag 完成真实双版本演练并以最终脚本对 12 个对象复跑：新版本 6 服务全部健康后
    注入失败，自动恢复旧数据、Artifact 和旧镜像，命令保持非零，证据为 `rolled_back`；失败路径未向新目录
    复制 `.env`。随后正常升级为 `passed`，新目录以 `0600` 激活旧配置，运行镜像全部切换到 S36，
    S32 登录、Artifact、Workflow 发布/执行及 Snapshot 业务 smoke 通过。
17. 双版本演练发现离线主机安装 Git 但解压目录不是仓库时，旧备份脚本会因 `git rev-parse` 失败；
    现由新升级器调用新备份工具并显式记录旧包 `SOURCE_REVISION`，普通离线备份也会回退读取包内元数据。
    两份升级 JSON 均未命中管理员口令、数据加密密钥、应用密钥或 MinIO 口令；PR #38 的 amd64
    远程 CI 已复验失败自动回滚、正常升级和业务 smoke。
18. GitHub 首页和公司电脑快速部署手册已补齐联网源码、Windows/WSL2、私有仓库与完全离线三条入口，
    并明确首次登录、内网 TLS、备份、事务式升级及 Secret/业务数据不得提交 Git 的边界。
19. PR #38 提交 `24ce92d` 的 Backend Test/Integration、Compact/Full Compose、Security 和 V2→V3 Upgrade
    六项远程检查全部通过。Compact CI 在所有验收结束后保留 7 天的 `amd64` 离线候选包与外部
    SHA-256，目标公司电脑无需 Git、Python 或 Node.js；候选包不等于正式 Release 或试点签署。

## 已完成：S30 Failure Intelligence 与 AI Draft Change Set

1. 已实现 Failure Cluster、Regression Baseline、可解释 Release Risk 与不可变证据指纹；AI Change Set
   固定 Impact/Risk 来源，只允许逐项接受或拒绝，接受后仅生成 Test Case/Workflow 草稿。
2. AI 不能通过旧 Suggestion 接口绕过 Change Set 审核，不能发布、执行、修改权限或创建 Credential；
   目标草稿发生漂移时以稳定冲突错误拒绝覆盖。
3. `20260813_0027` 已在真实 PostgreSQL 完成升级、`alembic check`、降级和再次升级；前端 3 个原失败
   场景、MSW Handler、Ant Design 弃用 API 与异步动画竞争均已修复。
4. 本地完整质量检查曾达到后端 300 passed/3 skipped、总覆盖率 90.43%，前端 150 passed，
   Statements 87.12%、Lines 89.08%；独立干净 Compose 完成 S3–S30 smoke 与 Playwright 回归。
5. PR #33 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images 和 Compose
   Smoke 五项检查全部通过；最终提交经评审后于 2026-08-14 squash 合并至 `main@bfa80fd`。

## 已完成小阶段：S31 Release Gate 与全局搜索

1. 新增独立 `ReleasePolicy` 与无 `updated_at` 的 `ReleaseDecision`；每次判断固定策略、质量、契约、
   Impact、Release Risk、性能和 Runner 证据快照，并保存 SHA-256 指纹与六类可解释 PASS/BLOCK 原因。
2. Release Decision API 只提供创建、列表与详情，不提供更新/删除；ORM 更新与删除事件也会拒绝变更。
   策略后续修改不影响历史 Snapshot 和指纹，跨项目、证据不匹配、停用策略和未知证据均使用稳定错误码。
3. 新增中文“发布门禁”页面，可配置阈值、绑定六类证据、生成判断并查看只读历史；页面 Statements
   96.92%、Branches 80.43%、Lines 98.33%。禁用的 V3 证据能力按 `/v3/features` 停止查询，避免将
   预期的 404/409/503 当作页面错误；Quality Gate 非必需策略可在不绑定 Gate 时创建。
4. 新增受项目/团队权限约束的全局搜索，覆盖项目与 API、Workflow、Case、Suite、Plan、Environment、
   Mock、Performance、Contract、Impact、Quality、Risk、Release Policy 等核心资产；不索引 Credential、
   Secret、执行日志、请求体或响应体，且对 SQL LIKE 通配符进行字面量转义。
5. `20260813_0028` 已在独立 PostgreSQL 完成全链升级、`alembic check`、降至 `0027`、再次升级和
   `alembic check`；临时数据库已删除，原数据卷未修改。
6. 当前全量本地证据：后端 342 passed/3 skipped、总覆盖率 90.86%；Release Gate Domain 100%、
   Service 98%、Repository 98%、API 100%。前端 159 passed，Statements 87.36%、Branches 80.50%、
   Functions 85.96%、Lines 89.33%，格式、Lint、TypeScript 与生产构建通过。
7. 已增加 `smoke_s31.py`、S31 Playwright 场景和 Compose CI 入口；当前源码重建后全部服务健康，smoke
   验证 PASS/BLOCK、快照不变、无 Decision 写入口和全局搜索，Playwright CLI 与仓库 Chromium 场景
   1/1 均完成“搜索 → 发布门禁 → PASS → 只读证据”；除未登录时预期的 Refresh 401 外无控制台错误。
8. 复用数据卷含 55,247 条 Workflow Execution 时，首页原实现会读取近 7 天完整 ORM/JSON 记录并阻塞
   单 Worker；现改为 PostgreSQL/SQLite 按本地日期与状态聚合。真实卷上首页汇总约 0.15 秒、搜索约
   0.11 秒，避免全局搜索被首页请求拖死。
9. PR #34 实现提交 `d885610` 的 Backend Test（2 分 50 秒）、Backend Integration（1 分 24 秒）、
   Frontend Build（8 分 54 秒）、Security Source/Images（10 分 19 秒）和 Compose Smoke
   （21 分 29 秒）五项远程检查全部通过；Compose 同一提交覆盖 S31 主路径、Team 100 Workflow/
   1000 Queue、Scale 500 Workflow/5000 Queue 和隔离备份恢复；随后已 squash 合并至
   `main@2beb2f0`，合并后 main 五项检查亦全部通过。
10. 正式 S31 仍包含完整容量/安全/备份恢复演练、全部页面试点签署及真实 14 天 RC；
    短时自动化不替代这些门槛。

## 已完成小阶段：V2→V3 原地升级与回滚

1. 演练固定并验证 `v2.0.0-rc.1@06699d54bceee091a2efac838e426cf7ef5c9c9e`，从该 tag
   导出干净源码并构建 V2 Backend/Mock 镜像，不使用当前脚本伪造 V2 应用行为。
2. V2 在 `20260812_0018` 创建真实 Project、Environment、API、Workflow、Execution 和
   Report；备份并用 `pg_restore --list` 验证 PostgreSQL custom-format dump，并对非空 MinIO
   对象生成 SHA-256 清单。
3. 同一数据集已完成 `0018 → 0028 → 0018 → 0028`；两次升级后 `alembic check`
   无漂移，V3、回滚后 V2 和重新升级后 V3 均能读取旧资产、保留旧报告并完成新执行。
4. 演练在首次升级后创建 V3-only Release Policy，并确认 destructive downgrade 会删除该
   V3 证据，但不损坏 V2 资产；三个阶段的 MinIO 对象集和哈希均与升级前清单一致。
5. 新增 `deploy/upgrade/compose.yaml`、`verify_v2_v3_upgrade.sh`、资产验证器和独立
   `V2 to V3 Upgrade CI`；每次使用独立 Compose Project/卷/端口，成功或失败都清理临时资源。
6. 2026-08-14 本地 ARM64 Docker Desktop 完整演练通过；PR #35 实现提交
   `3b7921a` 的 V2 to V3 Upgrade CI（7 分 52 秒）与 Security CI（13 分 26 秒）均通过。
7. 上述自动化证据不等于 V2/V3 连续 14 天 RC，不得因此创建 `v2.0.0` 或
   `v3.0.0` 正式标签。

## 已完成小阶段：S31 服务目录产品化

1. 新增项目级 `/projects/{projectId}/services` 独立路由、侧栏入口和兼容跳转；页面继续复用 S27
   Contract Hub 服务接口，没有复制业务模型或建立第二套目录数据。
2. 页面展示真实服务数量、OpenAPI/Pact 契约数量、失败验证、协议类型、Consumer/Provider 角色、
   依赖数量和更新时间，并提供到契约中心及影响分析的稳定资产深链，不伪造健康状态。
3. Contract Hub Feature Flag 关闭时保留路由并停止服务、摘要和依赖图请求；Viewer 只读，登记表单
   使用与后端一致的服务标识约束，页面和搜索结果不读取 Credential、Secret 或执行敏感数据。
4. 全局搜索的 `contract_service` 结果改为服务目录路径并保留稳定 UUID `focus` 参数；真实 Compose
   Chromium 已完成“页面登记服务 → 搜索 API 返回服务目录深链 → 键盘选择 → 聚焦行 → 契约链接”验收。
5. 本地完整门槛：后端 343 passed/3 skipped、总覆盖率 90.83%；前端 164 passed，Statements
   87.53%、Branches 80.60%、Functions 86.21%、Lines 89.51%，服务目录页面 Lines 96.92%；格式、
   Lint、mypy、TypeScript 和生产构建全部通过。S31 Playwright 文件 2/2 通过，Compose 功能开关及
   既有持久卷在验收后已恢复原状态，15 个服务均健康。
6. Draft PR #36 的 Compose CI 在新增测试项目后暴露全局项目选择器只加载首页 100 条，使旧项目
   深链被误判为不可访问。现在有项目深链时立即并行使用已授权的项目详情 API 按 ID 补取，不等待首页列表，
   并在列表返回后合并到选择器；
   只有详情 API 确认不可访问才返回全局首页。含 183 个项目的复用数据卷上，V1 通过全局搜索进入旧项目与
   S31 两个 Chromium 场景合计 3/3 通过，V1 深链刷新另外连续 10/10 首次通过。
7. PR #36 最终源码提交 `6e738e5` 的 Backend（run `31825085814`）、Frontend（run
   `31825085872`）、V2→V3 Upgrade（run `31825085810`）、Security（run `31825085819`）和
   Compose（run `31825085974`）五项 CI 全部通过。Compose 完成 18/18 非 S29 浏览器、S29 浏览器、
   Team 100 Workflow/1000 Queue、Scale 500 Workflow/5000 Queue 与隔离备份恢复；Playwright 注解
   无 flaky、Retry 或失败。
8. 本小阶段不等于完成其余 V3 页面试点、容量/安全/备份恢复签署或 V2/V3 连续 14 天 RC；未创建
   正式标签，也未开始 V4 S32。

## 已完成（本地）：S31 质量指挥中心产品化

1. 将原“工作台/首页”产品化为 16 张 V3 UI 基准中的“质量指挥中心/质量总览”，保留全局
   `/dashboard` 与项目 `/projects/{projectId}/dashboard` 深链，不改变项目上下文选择规则。
2. 全局视图只使用现有 Dashboard 聚合接口，展示授权范围内的项目、API、Workflow、今日执行、
   终态通过率、7 日趋势和最近运行；不向任意项目发起 Risk、Impact、Flaky 或 Release 请求。
3. 项目视图读取真实 Dashboard Summary、最新 Release Risk/Failure Cluster/Recommended Test、
   Impact Coverage/Gap、Flaky 资产及不可变 Release Decision；所有“最新”记录均复用服务端
   `created_at DESC` 顺序，不在前端伪造风险、覆盖率或发布状态。
4. `quality_intelligence` 和 `impact_engine` 关闭时停止对应 API 请求并展示明确能力状态；Flaky 与
   Release Decision 继续使用既有项目授权接口。首页只读展示历史 Fingerprint 和阻断原因，不提供
   重算、修改、发布或自动执行推荐测试入口。
5. 页面提供影响分析、质量洞察和发布门禁稳定深链；导航文案同步为“质量总览”，认证 Setup、V1
   深链及 S15 资产验收同步使用新名称。
6. 本地门槛：后端 343 passed/3 skipped、总覆盖率 90.86%；前端 43 文件 167 passed，Statements
   87.71%、Branches 80.74%、Functions 86.42%、Lines 89.69%，Dashboard 页面 Lines 100%、
   Branches 90.78%；格式、Lint、mypy、TypeScript 和生产构建全部通过。
7. 真实 Compose 使用显式开启的 Contract Hub、Impact Engine 和 Quality Intelligence 完成 S31
   Chromium 3/3 首轮通过，其中新增“创建不可变 PASS 判断 → 质量指挥中心 → 候选版本/深链”场景
   用时 654 ms；恢复默认关闭状态后 V1 Chromium 1/1 通过，15 个服务均健康。
8. PR #37 源码提交 `74d76ef` 的 Frontend（run `31857200389`）、Security（run
   `31857200448`）和 Compose（run `31857200387`）三项受影响路径 CI 全部通过；本次未修改
   Backend、迁移或升级脚本，因此 Backend 与 V2→V3 Upgrade 工作流按 `paths` 规则不触发，后端
   四项门槛使用上述本地结果。Compose 完成 19/19 非 S29 浏览器、S29 浏览器、Team 100 Workflow/
   1000 Queue、Scale 500 Workflow/5000 Queue 与隔离备份恢复；Playwright 注解无 flaky、Retry
   或失败。
9. 本小阶段仍须完成 PR #37 最终评审与 squash 合并；它不等于其余 V3 页面试点、发布签署或
   V2/V3 连续 14 天 RC，未创建正式标签，也未开始 V4 S32。

## 已完成（本地）：S29 PostgreSQL Runner Fabric 与 Worker Plane

1. 新增管理员 Worker Pool、一次性注册令牌、Runner 身份/心跳、Drain/Resume/Disable、Task、
   Lease、Fence 和 Event API；高熵 Token 只保存 SHA-256 查找哈希，明文只返回一次。
2. `20260812_0026` 扩展 Pool/Runner/Project 容量字段，并创建 Registration Token、
   Runner Task、Lease 和 Event；唯一约束、检查约束、索引和降级路径完整。
3. Workflow 在 Runner Fabric Flag 开启时将加密 Snapshot 固定到 PostgreSQL Task；Claim 通过
   `SKIP LOCKED` 认领并原子递增 Fence，Complete/Fail/Renew/Progress 必须同时匹配
   Runner、Lease、Task 和 Fence，旧 Worker 无法重复写入终态。
4. 高并发实测曾发现 Runner/Pool/Project 行锁与 Event 外键 Key Share 的反向锁链；最终改为
   分命名空间的 PostgreSQL 事务 advisory lock，并把 Progress 续租与 Event 合并为同一事务。
   修复后最终容量时间窗无 `deadlock detected`、429 或 500。
5. Runner 控制面使用独立的按 Token 限流桶，默认 5000/分钟；通用用户写接口仍保持
   120/分钟，没有为容量测试放宽业务安全门槛。
6. 独立 Async Runner Agent 在执行前校验计划 SHA-256，运行现有 Workflow Engine 与 Host/CIDR
   出站策略，对 408/425/429/5xx 和传输错误保持存活；结果类型、节点唯一性和 8 MiB
   上限由控制面再验证。
7. Docker Runner 以 UID/GID 65532、只读根文件系统、Drop ALL 和 `no-new-privileges`
   运行；Kubernetes 参考 Deployment 还禁用 ServiceAccount Token、开启 RuntimeDefault seccomp、
   设置资源上限并规定每 Token 单副本。S29 不接收用户 Compose、Shell、Plugin 或宿主凭据。
8. 中文“执行面”页面展示 PostgreSQL 事实源摘要、Pool/Runner/Task/Lease/Fence/Event，支持
   Pool/注册令牌创建、Drain/恢复/停用和事件详情；空状态、错误、分页与中文选择器均有测试。
9. 后端全量 Ruff format/check、mypy 264 个源文件、依赖边界与 pytest 通过：293 passed、
   3 skipped，总覆盖率 90.57%，Runner Fabric Service 96%、Repository 99%、Domain 96%。
10. 前端格式、ESLint、TypeScript strict、145 项测试、覆盖率和生产构建通过：Statements
    86.92%、Branches 80.72%、Functions 85.06%、Lines 88.90%；执行面页 Statements 92.37%。
11. 真实 PostgreSQL 17 在一次性容器中完成 `0025 → 0026 → 0025 → 0026` 与
    `alembic check`；PostgreSQL/Redis/MinIO 集成测试 3 passed。
12. 最终 ARM64 Compose 容量夹具 `df313b29-5827-496d-b0db-ca81fc48ea74` 确认
    5000 个唯一排队任务和加密计划，500/500 Workflow、500/500 Task、1000 个唯一节点终态、
    0 重复、0 Active Lease、0 制品冲突、2 个实际 Worker；提交 P95 2.141591 秒，总耗时
    144.893 秒。
13. 最终故障转移夹具项目 `521b8519-96b3-4867-83ad-5fe7e07f8c38`：Agent A 认领后中断，
    Agent B 以 Fence 2 完成第 2 次尝试，Workflow passed 且只有 3 条预期节点终态。Playwright
    在真实 Compose 中 1/1 通过，覆盖真实登录、侧栏、事实告警、expired/terminal Event、
    Drain/恢复、详情、Pool 与注册令牌。
14. 整套 Compose 从最终代码重建后 Backend、Frontend、General/Data/AI/Performance/Environment Worker、
    Beat、PostgreSQL、Redis、MinIO、Redpanda 和目标服务全部健康；Dockerfile 默认最终阶段已恢复
    Application Runtime，Beat/AI Worker 不再误用 Runner Entrypoint。
15. Ruff 安全规则、Python/前端依赖审计和 `flowtest-runner:ci` Grype v0.116.1
    High/only-fixed 门槛通过；只使用现有 CPython 3.13.15 精确误报台账，本轮没有新增例外。
16. S29 决策记录为 `ADR 0025`，架构、部署、监控/容量、升级/回滚和威胁模型已同步。
17. 实现提交 `030ed2a` 与本地验收文档提交 `a1c2814` 已推送并创建 Draft PR #32。首轮
    Backend Test（2 分 22 秒）与 Integration（1 分 17 秒，run `31614733014`）、Frontend Build
    （8 分 22 秒，run `31614732898`）和 Security Source/Images（9 分 8 秒，run
    `31614732960`）通过。
18. 首轮 Compose Smoke（run `31614733061`）实际启动并在 S5 失败，不是账户计费阻塞：Job 级
    `FLOWTEST_FEATURE_RUNNER_FABRIC_ENABLED=true` 使旧 S5 Workflow 进入 PostgreSQL Runner Queue，
    但 S29 Runner 尚未注册，因而执行一直处于 queued。最小修复将 S29 功能开关限制在 S29
    Smoke、浏览器和容量窗口，并在其余回归中恢复 Celery；为保证 Backend 重建后不丢失 S18–S28
    功能开关，这些既有开关提升为 Job 级环境。修复后必须重跑五项 CI。
19. 编排修复提交 `7e40dfc` 的 Backend Test（2 分 18 秒）与 Integration（1 分 10 秒，run
    `31616461170`）、Frontend Build（8 分 20 秒，run `31616461166`）和 Security Source/Images
    （10 分 36 秒，run `31616461286`）通过。Compose（run `31616461215`）已通过 S3–S11、S29
    Smoke 与 S29 浏览器、Runner→Celery 恢复，但 S22 浏览器用例仍假设 Runner Pool 为空；S29
    Smoke 已按设计持久化 Pool，因此旧空表文案不存在。S23 在 CI 首次选择器超时、重试通过，本机
    资源抖动下又耗尽 90 秒场景预算，后端未收到 Reflection POST；将真实 GraphQL+gRPC 双链路预算
    调整为 180 秒，并把可见“明文”分段定位限定到具体 Dialog/Tab。S22 最小修复改为验证 Runner
    清单列结构；两处均保留请求成功和 S29 真实 Pool/Runner/Fence 的原有业务断言。本机保留 S29
    Pool 的 Celery 栈上 S22 通过（13.6 秒）；S23 复跑期间 Docker Desktop 全局失去调度，`/live`
    同步超时且安全策略请求由 Nginx 返回 504，不能记作通过，最终以全新 Linux CI Runner 为准。
20. 浏览器稳定性修复提交 `e8ef455` 的 Backend Test（2 分 19 秒）与 Integration（1 分 7 秒，run
    `31620507777`）、Frontend Build（8 分 1 秒，run `31620507771`）和 Security Source/Images
    （9 分 39 秒，run `31620507745`）通过。Compose run `31620507971` 首次在构建 PostgreSQL
    镜像时从 GitHub Release 下载固定校验和 WAL-G 遇到 `curl (56) Connection died`，属于外部下载
    瞬断；同一提交只重跑失败 Workflow 后 attempt 2 在 27 分 58 秒内通过。
21. Compose attempt 2 完成 S3–S29 冒烟、S29 Runner→Celery 双向切换、S29 浏览器 1 passed 和
    非 S29 浏览器 15 passed（1.9 分钟，无 flaky）、Kafka 兼容、API/Workflow/1000 任务容量与隔离卷
    备份恢复。S29 CI 容量项目 `6d4554fc-8009-47ed-8aac-d260998e6a02` 完成 5000 个唯一排队执行与
    加密计划、500/500 Workflow 和 Task、1000 个唯一终态节点、0 重复、0 Active Lease、0 制品
    冲突、2 个实际 Worker；提交 P95 3.376032 秒，总耗时 218.597 秒。最终文档提交仍须重跑五项
    CI；未合并、未开始 S30，也未创建任何新 V3 标签。
22. 最终文档提交 `113458a` 的 Backend Test（2 分 22 秒）与 Integration（58 秒，run
    `31623263953`）、Frontend Build（8 分 5 秒，run `31623263861`）和 Security Source/Images
    （8 分 35 秒，run `31623263885`）通过。Compose run `31623263871` 已通过 S3–S11、S29 Smoke、
    S29 浏览器与 Runner→Celery 恢复，但 S15 首次运行通过资产创建后，计划资产类型用无作用域文本
    点击且未等待条件字段，耗尽 90 秒；Playwright 重试又复用同一名称，创建请求未被显式验证。
    最小修复为每次重试加入唯一后缀，所有 UI 创建操作等待并验证对应 POST 2xx 和 Dialog 关闭，
    Ant Select 使用可见 Dropdown 作用域，并将完整 S15 真实链路预算调整为 180 秒。修复后必须重跑
    完整五项 CI。本机缩减非必要服务后的真实 Compose 栈 S15 1/1 通过，场景 18.2 秒；前端
    145 项覆盖率、格式、ESLint、TypeScript strict 与生产构建再次通过。未合并、未开始 S30，
    也未创建任何新 V3 标签。

## 已完成：S28 变更影响引擎与确定性测试选择

1. 新增 Git Unified Diff、OpenAPI、GraphQL SDL 与 gRPC Proto 四类受控变更源；领域解析器不访问外部
   Git、不接收仓库凭据或脚本，只处理有界文本和已登记 Schema，限制 2 MB、500 文件、100,000 行与
   5,000 个规范化变更。
2. 新增项目级显式 Asset Mapping，将精确或尾部 `*` Source Selector 映射到现有 Test Case、Workflow、
   OpenAPI Contract、Pact Contract 或 Performance Scenario；拒绝跨项目、未知目标和超过 2,000 条映射。
3. `explicit_mapping_v1` 选择器按稳定键排序并去重，不使用不可解释启发式推断；未命中的变更保留为
   Coverage Gap，不会被虚构为已有测试覆盖。
4. 每次 Impact Run 持久化规范 Changes、Change→Impacted→Recommended 图、选择原因、Coverage Matrix、
   Gap、摘要与 SHA-256 Fingerprint，并独立保存 Test Selection 与 Coverage Snapshot，支持历史审计。
5. 中文“变更影响分析”提供 Mapping 管理、四类 Diff 输入、三列影响图、证据原因、Coverage Matrix、
   Gap 与历史下钻；S28 只给出推荐集合，不自动执行测试或改变既有发布门禁。
6. 新增双向迁移 `20260812_0025`；真实 PostgreSQL 已完成 `0024 → 0025 → 0024 → 0025`，最终
   `alembic check` 无漂移。
7. 后端 Ruff format/check、mypy strict、依赖边界及 278 passed/3 skipped 通过，总覆盖率 90.58%，
   Impact Domain 98%；Python 依赖审计和 Ruff 安全规则无已知问题。
8. 前端格式、ESLint、TypeScript strict、142 项测试与生产构建通过；Statements 86.70%、Branches
   80.50%、Functions 84.89%、Lines 88.72%。前端生产依赖审计无已知高危漏洞。
9. 真实 ARM64 Compose 冒烟完成四类 Diff、显式映射、确定性去重、100% Coverage、四条解释边和
   PostgreSQL 持久化；项目 `34869b0f-a790-4c73-a57b-3f2c4e868c97` 的 Impact Run
   `f44a2916-289c-46a8-982b-4da2cfc9d027` 指纹为
   `09af485bf9b86debe1febcd5a1e42970201fd58d865e73f4060d97d812b1e6d2`。
10. 真实 Chromium 已完成“创建 Mapping → Git Diff 分析 → 三列图与原因 → Coverage Matrix → 历史”
    1/1，场景耗时 8.9 秒、总耗时 11.1 秒；过程中修复 Ant Select Portal 与成功提示造成的选择器歧义，
    最终复跑通过。
11. 实现提交 `54a4061` 与本地验收文档提交 `a464fa2` 已推送并创建 Draft PR #31，架构边界记录于
    `ADR 0024`。本地没有 Grype/Trivy 二进制，因此 Backend/Frontend 镜像交由 Draft PR 的 Security
    Source/Images 使用既有 High/Critical 门槛扫描；结果见下一项。在最新提交五项 CI 全绿前不合并、
    不创建 `v3.0.0-beta.3`，也不开始 S29。
12. Draft PR #31 的提交 `5f3f7d4` 已通过 Backend Test（2 分 12 秒，run `31597011115`）、Backend
    Integration（1 分 13 秒，同一 run）、Frontend Build（7 分 28 秒，run `31597011124`）、Security
    Source/Images（9 分 43 秒，run `31597011152`）和 Compose Smoke（14 分 47 秒，run
    `31597011135`）。Compose 同一提交完成 S3–S28、Apache Kafka 兼容、API/Workflow 容量、1000 任务
    持久队列和隔离卷备份恢复；最终验收文档提交仍须复跑全部 CI。
13. 最终文档提交 `5f5da5a` 的 Backend Test（2 分 10 秒）与 Integration（1 分 9 秒，run
    `31598296375`）、Frontend Build（5 分 39 秒，run `31598296441`）、Security Source/Images
    （9 分 57 秒，run `31598296383`）和 Compose Smoke（17 分 54 秒，run `31598296388`）五项全绿。
    PR #31 随后标记 Ready 并 squash 合并至 `main@05e7cc3eb4229b40c4c63619469879d00b1386fc`，
    远端 `agent/s28-impact-intelligence` 已删除。
14. 合并提交触发的 Backend（run `31599845096`）、Frontend（run `31599845036`）、Security（run
    `31599844926`）和 Compose（18 分 47 秒，run `31599844971`）全部成功；Compose 再次通过 S3–S28、
    Kafka、容量与隔离恢复。S15 浏览器用例首次未找到新建行，Playwright 自动重试后通过，工作流留下
    flaky 注解但最终 14 passed。满足门槛后，annotated `v3.0.0-beta.3` 已固定到 `05e7cc3` 并推送。

## 已完成：S27 Pact 契约中心与发布兼容矩阵

1. 新增项目服务目录、不可变 Pact Contract Version、Provider Verification 和 Deployment
   Compatibility Check；Pact 导入自动登记 Consumer/Provider，使用规范 JSON SHA-256 去重。
2. 领域解析器仅支持有界 HTTP Exact Matcher，拒绝 Message Pact、Matching Rule、Generator、
   Plugin、认证/Cookie/Secret、超大文档和过深结构；解析后的类型 Snapshot 不保存原始敏感内容。
3. Provider 验证只接受无凭据、Query、Fragment 和 Path 的 HTTP/HTTPS Origin，关闭重定向和
   系统代理，每个 Interaction 执行项目出站策略；Provider State 只能请求同 Origin 固定路径。
4. 可选 Pact Broker 的 Origin 和 Token 只由部署配置，用户坐标经路径编码，Token 不持久化或回传；
   Broker 和 Provider 出站拒绝均转换为稳定、可审计错误证据。
5. OpenAPI Contract Run 可绑定服务和 Provider 版本。Deployment Check 聚合指定版本的最新 Pact
   验证和 OpenAPI Breaking Change：阻断证据为 `unsafe`，证据缺失为 `unknown`，全部通过才为 `safe`。
6. 中文“契约中心”统一展示 OpenAPI/Pact 资产、服务依赖图、动态 Provider 兼容矩阵、
   验证失败证据和持久化发布判断；页面允许合法 Compose 内部 HTTP Origin。
7. 新增双向迁移 `20260812_0024`；真实 PostgreSQL 完成 `0023 → 0024 → 0023 → 0024`，
   `alembic check` 无漂移。
8. 后端全量 273 passed、3 skipped，总覆盖率 90.28%，Pact Domain 99%；Ruff format/check、mypy
   strict、依赖边界和 Bandit 规则通过。前端 139 passed，Statements 86.34%、Branches 80.49%、
   Functions 84.37%、Lines 88.39%，格式、ESLint、TypeScript strict 和生产构建通过。
9. 真实 ARM64 Compose 冒烟已请求 `mock-target` Provider，验证 Pact 成功、Exact Body Mismatch、
   OpenAPI 绑定、兼容矩阵以及 safe/unsafe 判断；项目
   `5205f2c2-a239-4b61-bda4-cc9e236bff60` 的两条发布判断证据均已持久化。
10. 真实 Chromium 完成“Pact 导入 → Provider 验证 → OpenAPI 绑定 → 矩阵 → 安全发布判断 →
    统一资产” 1/1，最终耗时 5.0 秒；首轮检出 Ant Modal Portal 选择器歧义，已改为可见 Modal/
    精确 Combobox 定位并复跑通过。
11. Python 与前端依赖审计无已知漏洞；本轮重建的 Backend/Frontend 镜像使用 CI 相同
    Grype 0.116.1、`only-fixed` High/Critical 门槛通过，无新增漏洞豁免。
12. 架构边界已记录于 `ADR 0023`；实现提交为 `8ec92a3`，本地验收文档提交为
    `f9ba039`。最终文档提交 `0daab31` 的 Backend Test（2 分 16 秒）、Backend Integration（1 分
    4 秒）、Frontend Build（7 分 32 秒）、Security Source/Images（10 分）和 Compose Smoke（18 分
    32 秒）五项全部通过；Compose 同一提交完成 S3–S27 回归、Apache Kafka 兼容性、API/Workflow 容量、
    1000 任务持久队列和隔离卷备份恢复。
13. PR #30 首轮 Backend Test 在测试前的 Ruff format 门槛失败：本地从仓库根目录格式化
    `scripts/smoke_s27.py` 时未套用 `backend/pyproject.toml` 的 100 字符配置，CI 在 `backend` 工作目录使用
    项目配置后识别出差异。已使用 CI 的精确命令重新格式化，并在本地通过对全部 Backend 与
    `scripts/*.py` 的 Ruff format/check、mypy 以及依赖边界检查；该失败是真实格式门槛，不归因于计费或容量。
14. PR #30 标记 Ready 后已 squash 合并至 `main@83375d20a2726c1088d1afaa6c660863246fed5f`，远端
    `agent/s27-contract-matrix` 已删除；合并后的 main 工作流全绿，annotated tag
    `v3.0.0-beta.2` 已固定到同一提交并推送。

## 本地验收完成：S26 签名环境实验室

1. 新增管理员注册、创建版本和停用的 `EnvironmentTemplate`，版本保存规范 JSON、SHA-256 与平台
   HMAC-SHA256-v1 签名；普通项目成员只能 Provision 已启用的签名版本。
2. 声明式契约只允许固定 Digest 镜像、依赖顺序、受限环境变量、HTTP/TCP Health Check、资源上限、
   TTL 和平台内置 `HTTP_GET_V1` Seed；不接收 Compose、命令、Entrypoint、脚本、Secret、设备或卷。
3. 镜像同时受 OCI Digest 校验和部署级精确白名单约束。独立 `environment` Celery 队列由 UID/GID 65532、
   只读根文件系统、Drop ALL 和 `no-new-privileges` 的 Worker 消费，不挂载宿主 Docker Socket。
4. 独立 DinD daemon 不发布宿主端口；Runner 将签名契约翻译为固定 Docker CLI 参数数组，创建隔离 bridge、
   非 root/只读/无 Capability 容器、随机宿主端口及 CPU、内存、PID 上限，不经过 Shell。
5. `EnvironmentInstance` 保存模板 Snapshot、签名、Fencing Token、端点、Seed 证据、TTL 和 Cleanup 状态；
   Idempotency-Key、Label 枚举、Beat Reconciler 与同一清理任务覆盖失败、超时、取消、TTL、消息重投和
   Runner 重启后的幂等回收。
6. 新增中文“环境实验室”深链接，覆盖模板注册、版本、停用、项目 Provision、状态、端点、Seed/隔离
   证据和清理；页面没有任意 Compose 或脚本入口。
7. 新增双向迁移 `20260812_0023`；真实 PostgreSQL 已完成 `0022 → 0023 → 0022 → 0023`，最终
   `alembic check` 无漂移。
8. 后端最终全量为 270 passed、3 skipped、总覆盖率 90.05%；Ruff、mypy strict、依赖边界和
   Python 依赖审计通过。镜像白名单启动校验已收紧为完整 OCI Digest 格式并有回归测试。前端 133 项通过，
   Statements 85.99%、Branches 80.14%、Functions 84.00%、Lines 88.15%，格式、Lint、TypeScript
   strict 与生产构建通过。
9. 真实 ARM64 Compose 已完成模板 v2、独立队列 Provision、Health、Seed、端点、Worker 停止/恢复、
   队列清理和重复 Cleanup；最终实例 `f61af547-4813-4529-bda3-2499da147ea1` 已清理。真实 Chromium
   最终复跑完成“注册 → 新版本 → Provision → Ready/证据 → Cleanup”1/1，耗时 27.5 秒。
10. Python 与前端依赖审计通过。Environment Runner、定制 Docker 29.7.2/containerd v2.3.3 daemon
    和固定 nginx fixture 均通过既有 Grype `only-fixed` High/Critical 门槛；没有新增漏洞豁免。
11. 实现提交 `5c68bdf` 已推送并创建 Draft PR #29；最新提交 `2455da3` 的 Backend Test、Backend
    Integration、Frontend Build、Security Source/Images 和 Compose Smoke 全部通过，PR 随后标记 Ready
    并 squash 合并至 `main@2434db3`。GitHub 已自动删除远端 S26 分支。
12. 合并提交触发的 Backend、Frontend、Security 与 Compose 主分支工作流全部通过；Compose 再次完成
    S3–S26、Kafka 兼容、API/Workflow 容量、1000 任务持久队列和隔离备份恢复。满足发布门槛后，annotated
    tag `v3.0.0-beta.1` 已固定到 `2434db3` 并推送。

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
    指向账户付款失败或 Actions spending limit。该次结果被正确记录为外部计费阻塞，而不是代码失败。
16. 2026-08-12 14:45（Asia/Shanghai）已对 `9eab87d` 的 Backend `31569796643`、Frontend
    `31569796638`、Security `31569796687` 和 Compose `31569796736` 执行重跑；五个新 Job
    `94033432944`、`94033432935`、`94033432495`、`94033431994`、`94033432684` 均在约 3 秒内失败，
    新 Check Annotation 仍明确提示近期账户付款失败或 Actions spending limit 需要提高，且无任何步骤日志。
    这仍是外部计费阻塞，不是代码失败。
17. 仓库公开后，PR #28 的 Backend Test、Backend Integration、Frontend Build、Security Source/Images
    和 Compose Smoke 已全部重新执行并通过；PR 随后标记 Ready、squash 合并至 `main@eb2f0c8`，远端
    `agent/s25-performance-lab` 分支已删除。公开仓库已开启 Secret Scanning 和 Push Protection。

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

1. 从 PR #38 成功的 Compact CI 下载固定 Commit 的 `amd64` 离线候选包和 SHA-256，通过公司受信
   渠道交付，在目标 Windows/WSL2 或 Linux Docker 主机完成首次安装、备份恢复和回滚演练；Standalone
   试点按 `docs/operations/standalone-pilot.md` 记录。
2. 在同一候选 Commit 上完成至少 72 小时公司真实试点，由业务负责人、运维和安全审批人共同签署；
   任何代码修复都生成新候选并重新开始观察。
3. 试点通过后完成 PR #38 Compact 与 PR #39 Standalone 最终评审和合并；未完成真实试点与人工签署前
   不创建 V4 正式标签。
4. 继续 S31 剩余页面产品化、容量、安全、备份恢复和 V3 试点；未完成这些门槛前不宣告 V3 GA。
5. 并行推进 `v2.0.0-rc.1` 的真实试点与连续 14 个自然日观察；只有签署、恢复演练、扫描和容量证据
   全部通过后创建 `v2.0.0` 正式标签。
