# FlowTest 全模块整改正确性复审报告

审计日期：2026-10-22。审计对象：main `1038e08ffe078719b7d0fe357d7bc7d0d4a1029a`。本报告与[详细修改方案](remediation-plan.md)配套。

> 本文保留修复前的审计结论；源码链接固定到审计基线。后续修复与实际验证见[整改实现和验证记录](implementation-report.md)。原文内临时前端反例已逐项迁入正式测试，归档位置和校验清单见实现记录。

## 1. 结论与审计范围

**当前不能判定所有修改均正确或全部设计闭环完成。共确认11项待修：1项P1、10项P2；其中9项有真实组件/服务最小反例，2项由完整可达源码链确认。** 本轮没有修改业务代码，所有反例尚无修复后的通过证据。

逐模块复查覆盖 **26模块、3项全局问题、原73个唯一F-ID**，同时检查此次实现涉及的近端权限、缓存、异步状态、固定版本、结果消费者和旧库兼容。原问题的主要实现大多已经落地；剩余问题集中在跨模块消费、项目状态及部署形态。这里的“新发现”表示本轮新增确认，不意味着均由最近PR新引入。M01团队授权、M15通知、M19提交编辑属于已核实的历史整合遗漏。

本轮直接影响原问题闭环的7项为：F-PRJ-02、F-ENG-02、F-REL-02、F-AI-02、F-AIC-02、F-FAB-02、F-UX-02；其余4项为相邻功能边界问题。原73项的覆盖率不是开发完成百分比，也不构成26模块全量端到端或逐像素签收。

### 1.1 精确版本、依据及保护边界

- 实际源码树：`/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest`，HEAD `43b797f93b7ec49dcffda813cb1bb73a0446dab9`；与上述 main 的完整 tree 均为 `e0915ae21547750ca854e61c835691ac36208487`，审计源代码完全相同。frontend tree=`24145966762762f35e79f98922502be9f056f0f3`，backend tree=`7a69e02784f3944abe0976365c1c39524e58e77f`。
- 原冻结依据：[2026-10-19完整审计](../2026-10-19/complete-audit.md)、[原详细方案](../2026-10-19/remediation-plan.md)，原证据基线 `420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4`。同时核对batch01–35相关回执、v5完整重设计与概念图纠偏，不把回执勾选作为正确性证明。原两份文档保持冻结。
- 执行遵循当前 AGENTS：保护原工作区 AGENTS.md / README.md / .playwright；原测试、产品、CI门禁和数据库均未变。临时反例仅在隔离树 ignored output，MSW或独立内存/临时SQLite中执行。
- 桌面实页使用现有专用QA `127.0.0.1:13078`、隔离 bundled Chromium，1440×1000；只读抽查首页→报告→历史画布。没有使用个人浏览器或3000日常页面，没有seed/共享QA业务写入、真实发布、执行、AI生成、账号签发或MCP写入。
- OFF策略复核确认：M22请求级OFF在扫描/替换/占位恢复前短路；未因本轮审计扩大生产日志或数据采集。测试日志中的Secret/账号/消息均为明确合成fixture。

## 2. 待修问题总表

| 编号        | 优先级 | 模块             | 原问题关联 | 影响                                                                                                                                                                                                    | 确认证据                                                                                                                                                  |
| ----------- | ------ | ---------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R-M11-01    | P1     | M11 测试工程     | F-ENG-02   | [旧 Standalone 升级漏补 materialized_assets，设计 ORM 读取失败](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/core/standalone_schema.py#L502)          | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m11-standalone-materialized-assets-probe.log) |
| R-M20-01    | P2     | M20 AI 助手      | F-AI-02    | [接受新流程后，真实工作区被新鲜旧目录解析成旧流程](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/ai/use-ai-review.ts#L143)                   | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m20-ai-result-navigation.log)                 |
| R-M15-01    | P2     | M15 测试报告     | 新增边界   | [A 项目通知迟到回执在 B 项目展示 A 的一次性 Secret](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/reports/use-reports.ts#L102)               | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m15-cross-project-secret-probe-r4.log)        |
| R-M06-01    | P2     | M06 项目管理     | F-PRJ-02   | [合法自降级后，权限缓存及管理控件仍保持 Owner](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/projects/AccessManagementPanel.tsx#L96)         | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m06-self-demotion.log)                        |
| R-GLOBAL-01 | P2     | 全局 / M02       | F-UX-02    | [非活跃接口重命名后，目录新名称与对象标签旧名称不一致](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/api-console/use-api-console.ts#L206)    | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/global-inactive-api-rename.log)               |
| R-M01-02    | P2     | M01 质量总览     | 新增边界   | [仅团队授权的合法项目在总览被遗漏，项目汇总返回 404](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/repositories/dashboard.py#L56)                      | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m01-team-scope.log)                           |
| R-M01-01    | P2     | M01 质量总览     | 新增边界   | [质量智能关闭时，旧列表缓存仍触发被关闭的详情请求](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/dashboard/use-dashboard.ts#L47)             | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m01-warm-off.log)                             |
| R-M19-01    | P2     | M19 发布门禁     | F-REL-02   | [提交 A 期间仍能编辑 B，A 回执关闭已变更编辑窗口](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/release-gate/ReleaseDecisionDialog.tsx#L107) | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m19-delayed-receipt-probe.log)                |
| R-M22-01    | P2     | M22 AI 变更集    | F-AIC-02   | [审核 pending 时 JSON / 备注仍可编辑，成功后后续编辑未提交](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/AIChangeSetsPage.tsx#L516)            | 源码确认；未新增动态probe                                                                                                                                 |
| R-M24-01    | P2     | M24 组织治理     | 新增边界   | [Service Account 签发失败前已经清空名称、标识和 Scope](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/OrganizationGovernancePage.tsx#L820)       | [运行反例](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m24-service-account-retention.log)            |
| R-M25-01    | P2     | M25 分布式执行面 | F-FAB-02   | [真实 Lease-only 进度事件无法从事件目录下钻任务 / Lease](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/ExecutionFabricPage.tsx#L431)            | 源码确认；未新增动态probe                                                                                                                                 |

P1优先处理旧库部署阻断；P2中先处理打开错误资产、跨项目状态及权限刷新。问题逐条行为、漏测与最小修复见下节；完整实施顺序和验收矩阵见配套方案。

## 3. 问题详解

### R-M11-01 · P1 · 旧Standalone升级未补0064列，测试设计ORM读写失败

**定位**：

- [standalone_schema.py:502](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/core/standalone_schema.py#L502)：`_ensure_s47_test_design_columns` 仅补 scenarios/evidence_refs/warnings/confidence/review_requirements，遗漏 `materialized_assets`。
- [standalone_schema.py:30](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/core/standalone_schema.py#L30)、[main.py:47](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/main.py#L47)：真实Standalone启动调用create_all及增量补列，不调用Alembic；create_all不为已有表加列。
- [test_design.py:58](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/models/test_design.py#L58)：ORM现要求该非空JSON列。
- [test_engineering_proposals.py:94](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/services/test_engineering_proposals.py#L94)、[test_engineering_proposals.py:490](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/services/test_engineering_proposals.py#L490)：旧物化结果恢复读取完整TestDesign，新Apply插入也包含该列。
- [0064:14](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/migrations/versions/20261021_0064_test_design_materialization.py#L14)本身有正确upgrade/downgrade；问题是Standalone增量入口漏接，不应改动该迁移来掩盖。

**触发/实际/预期**：已有S47/S62/0063完整SQLite数据库中存在旧 `test_designs`，升级到当前代码并正常启动。启动不报错，但随后真实`session.get(TestDesign,id)`抛`sqlite3.OperationalError: no such column: test_designs.materialized_assets`；物化读取/新Apply不能正常使用。预期启动增量添加 `JSON NOT NULL DEFAULT '[]'`，旧设计/指纹/原引用及审核记录保持，旧记录新列为空列表。

**反例证据**：`/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/backend/output/full-review-20261022/test_m11_standalone_materialized_assets.py`。使用完整当前metadata建立独立临时SQLite，保存approved设计及场景、来源、testcase引用、原指纹和审核说明，只移除0064新增的一列；断言其余列和当前模型一一相等、FlowSpec无需重建。经真正initialize入口后，原raw行比较仍相等，随后实际ORM读取在缺列处失败。不是空表、pre-S40伪表或私有补列函数镜像断言；没有改共享DB。

**实际命令/日志**：在SECOND/backend运行`uv run pytest -q --no-cov output/full-review-20261022/test_m11_standalone_materialized_assets.py`，exit1，单case实际OperationalError；完整日志 [m11-standalone-materialized-assets-probe.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m11-standalone-materialized-assets-probe.log)。日志有probe直接导入名为TestDesign的模型产生的CollectionWarning，不是失败原因。

**漏测**：`backend/tests/test_design_asset_migration.py`只跑Alembic64升降级；`test_standalone_runtime.py`未构造“现有完整设计表仅缺64列”；`test_standalone_ai_review_baselines.py`只移除65列，64列一直已存在。因此新装、Alembic、0065旧库测试都不能覆盖该缺口。

**最小修复与验证计划**：沿既有`_add_column_if_missing`在设计增量补列中添加该列；不触发FlowSpec表重建、不改Alembic64/65或升级脚本。正式反例覆盖完整旧库+旧设计/引用/审核保持、真实ORM读取、新物化引用保存后重复启动不被覆盖、两次幂等；保留新装和pre-S40路径，具名standalone/design migration/test engineering资产文件、Ruff，必要mypy；合并前完整后端/升级/Windows仍由风险计划要求独立验收。

### R-M20-01 / P2：接受新流程后，结果链接可由新鲜完整目录解析成旧流程

**关联**：原 F-AI-02 的“接受后打开正确草稿”仍有真实消费者边界缺口；不是 href 拼接错误。

**精确位置**：

- `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/src/features/ai/use-ai-review.ts:143`：成功后只更新 `ai-suggestions`，直到 150 行返回，没有失效物化资产目录。
- `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/src/features/ai/AISuggestionReviewDialog.tsx:173`：结果通过 React Link 导航 `/workflows?focus=<真实新ID>`。
- `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/src/features/workflows/use-workflows.ts:872`：完整目录不含 selection 时，874 行回退首项；854 行的精确查询使用已经回退的 ID。
- `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/src/main.tsx:19`：生产 QueryClient 的真实 `staleTime: 15_000`。
- `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/backend/app/services/ai.py:243`：普通 workflow 建议接受确实创建新流程，252 行把新 ID 写入接受结果。

**触发**：先打开少于 100 条且已完整加载的 Workflow 目录（例如只有旧 W1，items.length == total）；15 秒新鲜期内进入 AI 助手接受一个创建 W2 的建议，再点“打开流程草稿”。

**期望 / 实际**：期望真实 Workflow 消费者展示 W2；实际本项目目录未失效、仍为完整旧目录，消费者把显式 W2 当作不在完整目录中的选择而回退 W1；空目录时也可能没有可编辑结果。没有 GET W2 的保证。不能以 href 正确证明实际对象正确。

**漏测**：`AIAssistantRemediation.test.tsx:133` 和 `:362` 只核链接属性；已有 MCP 的消费者缓存导航反例没有覆盖普通 AI 路径。本轮最小反例已实际执行并精准在新 ID 断言失败，见下段。

**最小修复**：接受响应确认后，按响应类型失效捕获原项目的实际资产查询前缀；至少 workflow 对应 `['workflows', project]`，并核对实际详情前缀。TestCase 同理刷新目录、选项和计数，不能因修这一项改动工作流选择算法、跨项目缓存或自动发布/执行。即使导航已离开，原项目资产缓存仍应正确失效；是否显示 toast 继续由现有命令身份守卫决定。

**本轮反例**：`frontend/output/full-review-20261022/m20-ai-result-navigation.audit.test.tsx` 使用未修改的实际 `AIAssistantPage`、Hook、服务、`useWorkflows`；最小消费者仅将 Hook 当前选择输出，未模拟选择算法。实际结果：elapsed **2850ms**、catalogReads **1**、exactReads **[]**、writes **1**，所选仍为旧流程 `00000000-0000-4000-8000-000000000060`。生产 15 秒时窗真实满足；退出1，1测试失败，4.81秒。首次 fixture 遗漏 projects GET/按钮图标名称的失败单独保留，修正后无MSW未处理请求，不计为产品证据。

**红绿验证**：同 QueryClient，生产 15 秒 staleTime，实际 `useWorkflows` 先读取完整目录→实际 AI 页面接受→点结果 Link→实际 `useWorkflows` 展示新 ID/名称；记录原目录时间到打开结果小于 15 秒，不用 Infinity、假时钟或选择算法 mock 造失败。另验证仅一次接受、另一项目新鲜目录不失效。建议回归 M20 页面/整改/Hook/SDK及相关 Workflow 消费者测试；无需为此全量跑覆盖率或真实模型。

### R-M15-01 · P2 · A项目通知创建的迟到回执在B项目Viewer上下文显示A秘密

**定位**：

- [use-reports.ts:34](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/reports/use-reports.ts#L34)：`webhookOpen/revealedSecret`是普通useState，不随项目重置。
- [use-reports.ts:94](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/reports/use-reports.ts#L94)：创建完成直接关闭窗口并写`created.secret`，没有项目/工作区生命周期或请求代次校验。
- [ReportsPage.tsx:46](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/ReportsPage.tsx#L46)：项目参数变化复用同一个页面/Hook，未key为项目工作区。
- [ReportsPage.tsx:395](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/ReportsPage.tsx#L395)：Secret弹窗只看revealedSecret，未绑定原项目身份。

**触发/实际/预期**：A项目Owner从真实表单提交通知，POST尚未返回；浏览器Back/地址导航使当前页切到B，B权限为Viewer，配置通知按钮实际已禁用；此时释放A成功回执。当前B报告页出现A的一次性secret。预期旧项目回执不影响B、不显示A秘密；A后端已完成的命令不回滚、不自动重发。该问题为前端跨项目展示混淆，未证明后端跨租户越权，也不声称秘密落日志。

**反例参数与证据**：`/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/output/full-review-20261022/m15-cross-project-secret.probe.test.tsx`。使用真实ReportsPage/useReports/ProjectProvider和公开React Router导航，MSW无实际业务写入。唯一POST为A，payload名称`synthetic-A-webhook`、URL `https://notify.example.test/a`、原默认两种events；响应为最小读取fixture `{id:'audit-webhook-A', project_id:A, secret:'synthetic-project-A-secret'}`。B ID `00000000-0000-4000-8000-000000000998`、Viewer/read。反例先确认B路径及Viewer按钮禁用、A唯一请求和原payload，释放后“页面不应包含A secret”失败。token全是明确合成字符串。

**实跑**：`CI=true pnpm exec vitest run output/full-review-20261022/m15-cross-project-secret.probe.test.tsx --coverage.enabled=false`，exit1；最终r4 test 865ms，总3.17s，真实业务末断言失败。完整日志 [m15-cross-project-secret-probe-r4.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m15-cross-project-secret-probe-r4.log)。原配置、60s、单worker及业务断言保留。

**漏测/归因**：ReportsPage现有通知用例只验证单项目创建、secret出现、切换enabled及Editor禁写，没有A在途→B归属断言。冻结420d2e0的useReports已有相同普通state/无回执守卫，因此这是本轮发现的历史整合漏项，不误归为PR146新增代码引入。

**最小修复与验证计划**：用项目key隔离报告工作区或项目作用域state，并为创建成功/失败、导出/切换的可见反馈加发起项目+生命周期校验；旧项目命令的目录刷新只指向原项目。secret状态含原项目，切项目立即不可见；不把secret持久化、记录日志或额外读取。新增A慢成功/失败→B、A已显示secret→B、B Viewer和同项目正常显示/关闭反例，保留原payload/秘密一次性行为及零额外POST。具名ReportsPage与相关报告文件、格式/lint/types；后续最新head完整前端门禁独立执行。

### R-M06-01 · P2 · 合法自降级后权限缓存与控件不收敛

- **定位**：[AccessManagementPanel.tsx:96](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/projects/AccessManagementPanel.tsx#L96)。成员/团队写入成功只失效 members、team-grants、team-members、access-directory 和 audit，没有失效项目权限。
- **读取链**：[ProjectsPage.tsx:86](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/ProjectsPage.tsx#L86) 使用 `['project-permissions', projectId]`；115–117 行依其成功缓存计算成员管理、编辑和审计能力；[431 行](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/ProjectsPage.tsx#L431)显示当前角色。成员表单和删除入口依旧 `canManage`，见 [154 行](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/projects/AccessManagementPanel.tsx#L154) 与 [203 行](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/projects/AccessManagementPanel.tsx#L203)。
- **合法触发条件**：非系统管理员，项目存在自己和另一位 Owner；通过现有成员表单把自己更新为 viewer。服务端允许该操作：[projects.py:519](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/services/projects.py#L519) 仅要求另一位 Owner 存在；[801 行](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/services/projects.py#L801) 只拦截最后一位 Owner。
- **期望**：一次成功 PUT 后，权限读取刷新，当前身份变为 viewer，成员和安全管理写控件及时消失或禁用。
- **实际**：一次 PUT 成功，成员查询已回填自己为 viewer，另一 Owner 保留；权限 GET 仍仅一次，缓存 `effective_role: owner`，身份标签仍为“项目 Owner”，“添加成员”仍启用。后端会拒绝后续越权写入，并不能使当前前端权限状态正确。
- **真实探针**：真实 `ProjectsPage`、ProjectProvider、AccessManagementPanel、QueryClient 与 MSW HTTP；没有替换业务 hook。用户 ID 为 `00000000-0000-4000-8000-000000000001`，项目为 `00000000-0000-4000-8000-000000000010`，另一 Owner 为 `00000000-0000-4000-8000-000000000902`。PUT 严格断言 `{user_id: self, role: 'viewer'}`，等待成功提示及新成员列表后检查 UI。日志记录 `writes=1 / permissionReads=1 / serverRole=viewer / oldOwnerLabelPresent=true / addDisabled=false`。
- **原测试漏点**：`AccessManagementPanel.test.tsx` 60、99、126、163 行覆盖候选、读错误、团队和初始 viewer，向组件提供静态 `canManage`；`ProjectsPage.test.tsx` 14、38 行没有成功改变自身权限的真实缓存联动。后端 `test_access_api.py:486` 已有普通 Owner 转移/自降级并拒绝后续写的合法合同，并非要放宽后端权限。
- **最小修复**：成员/团队授权变更成功后，等待准确项目权限 key 的失效和刷新，再完成成功反馈；至少覆盖本页 `['project-permissions', projectId]`。跨模块须同时核对已有权限消费者，避免只修本页：共享能力 hook 使用该前缀加 userId，测试资产使用单数 `['project-permission', projectId]`，接口编辑能力来自项目目录 `['projects']` / `['project', projectId]` 的 role。后两项是静态影响范围，本轮未把它们冒充已复现的额外缺陷。新增反例应保留两 Owner、非系统管理员、一次 PUT 和最新角色/控件断言，不改变最后 Owner 守卫。

探针源码：[project-self-demotion.test.tsx](/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/output/full-remediation-20261022/audit-probes-archive/frontend/full-review-20261022/project-self-demotion.test.tsx)。日志：[m06-self-demotion.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m06-self-demotion.log)；结构结果：[m06-self-demotion-results.json](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m06-self-demotion-results.json)。执行一次，exit 1，1 项失败，测试 9.67 秒、总 11.81 秒；三个失败断言分别对应旧 Owner 标签、仍存在的管理入口及未刷新权限。

### R-GLOBAL-01 · P2 · 未激活接口的重命名没有同步对象标签缓存

**定位**：[ApiConsolePage.tsx:769](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/pages/ApiConsolePage.tsx#L769) 的目录重命名按钮明确 stopPropagation，允许在选中 A 时重命名 B；[use-api-console.ts:206](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/api-console/use-api-console.ts#L206) 忽略 PATCH 返回 definition，仅失效 apis / api-detail / global-search；[WorkspaceObjectTabs.tsx:262](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/navigation/WorkspaceObjectTabs.tsx#L262) 优先读取稳定 apiDefinitionKey。只有实际 detail 查询重新读取时才写回此 key；非活跃 detail 默认不因 invalidate 自动 refetch。

**复现**：真实 ApiConsolePage+WorkspaceObjectTabs+ProjectProvider，先打开 B 形成真实 definition 缓存和对象标签，再选择 A；从目录的 B 重命名按钮改为“接口B新名”。唯一 PATCH 正确，目录 B 已更新，A 的 aria-pressed 仍 true；B detailReads 前后均为1，稳定缓存与 B tab 仍为“接口B原名”，新名 tab 不存在。正确行为为同一资产各位置名称一致，href / 版本 / 选中 A 不变。

**证据**：[global-inactive-api-rename.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/global-inactive-api-rename.log)，最终23.38s、exit1，命中真实业务末断言，无 MSW 未处理请求。首次 B preview handler 遗漏日志单独保留，不计有效反例。该纯预览在 MSW 中处理，没有请求真实目标网络或业务写入。

**漏测**：ApiConsolePage.test.tsx:556 只重命名当前活跃对象；WorkspaceObjectTabs.test.tsx 只直接预置 detail，没有真实 rename 与稳定 definition 缓存联动。原 F-UX-02 对切版本/重命名/刷新后的真实名称要求尚未完整闭环。

**最小建议**：成功时用 PATCH 返回 definition 更新准确的 apiDefinitionKey(projectId, targetApiId)，保留原目录/detail失效；不要改为任取某个版本缓存、清空全部 tab 或新增无条件网络请求。正式行为回归保留两对象、A仍选中、B tab即刻新名和完整href的断言。

### R-M01-02 · P2 · 团队授权项目与总览的“可访问项目”范围不一致

**定位**：[DashboardRepository.accessible_project_ids:56](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/repositories/dashboard.py#L56) 对非系统管理员只 JOIN ProjectMember；[ProjectRepository.list_for_user:231](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/repositories/access.py#L231) 与 get_role:277 同时支持 TeamMember / ProjectTeamGrant。DashboardService._scope 因此把正常项目目录已授权的团队项目当不可访问。

**复现**：独立内存数据库中保留完整项目/执行数据，普通 Viewer 无直接 ProjectMember，只有合法 TeamMember+ProjectTeamGrant(viewer)。同一身份 GET /projects 200且包含该项目、项目 /permissions 200且 effective_role=viewer；项目范围 /dashboard/summary 与 /dashboard/recent-executions 均404 PROJECT_NOT_FOUND，全局 summary.project_count=0。正确结果应包含此合法项目且继续拒绝未受权项目。

**证据**：[m01-team-scope.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m01-team-scope.log)，真实 ASGI / 服务 / SQL，无共享数据库；最终单反例 2.15s、exit1。原 Dashboard 两个直接成员/系统管理员用例在对照运行中通过，原日志保留在 m01-team-scope-setup-attempt.log；第一次探针遗漏 grant.created_by_id 的 fixture 错误不作产品证据。

**归因 / 漏测**：基线420d至当前这两个 Dashboard 文件无差异，因此属于本轮发现的历史权限整合漏项，不能称作 PR146 新引入。原 Dashboard fixture 只含直接成员和系统管理员，没有团队角色。不是后端权限扩大或数据泄漏，而是合法授权被遗漏。

**最小建议**：将总览范围接到与项目目录一致的受类型约束的授权项目身份查询，覆盖团队/直接角色优先、去重和当前组织边界；不能仅删掉 Dashboard 的404检查。增加 team-only viewer/editor、直接+团队重叠、撤销 grant、跨组织拒绝及全局/项目汇总与最近运行一致性测试。

### R-M01-01 · P2 · 功能关闭时，合法旧列表缓存仍触发关闭能力的详情请求

**定位**：[use-dashboard.ts:43](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/dashboard/use-dashboard.ts#L43) 从缓存风险列表取得 latestRiskId；第47行仅以 ID 存在启用详情，没有同时要求 hasProject / qualityEnabled。后端 [quality_intelligence.py:188](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/backend/app/services/quality_intelligence.py#L188) 的 get_risk 仍要求能力开启；不是允许历史只读的 M22 合同。

**复现**：QueryClient 留有先前受权读取的 release-risks 列表；当前 v3 flags 明确 quality_intelligence=false。真实 DashboardPage 显示“质量智能能力未启用”，仍 GET 该风险详情；受控后端按真实关闭合同返回 QUALITY_INTELLIGENCE_DISABLED/503。反例记录 detailReads=1、riskState=error、offMessageVisible=true、errorTraceVisible=false。正确行为应不发这个 gated 请求。这里没有写入或越权成功；问题是关闭状态和查询链不一致，且相应错误被 enabledError 隐去。

**证据**：[m01-warm-off.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m01-warm-off.log)；临时 probe 为 /Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/output/full-review-20261022/dashboard-warm-off.test.tsx，最终 321ms 业务断言失败，exit1。首次因诊断查询匹配两个同名提示而失败的日志另存，不计产品证据。

**漏测 / 归属**：DashboardPage.test.tsx:434 只覆盖全新空缓存下的 OFF，未覆盖有效旧目录缓存。Flaky 全量聚合整改与独立质量智能开关不是同一功能，不能把该问题说成聚合 SQL 又只统计首100条。

**最小建议**：风险详情启用条件与父列表使用同一明确能力及项目状态；不为此删除全部项目缓存或请求额外历史数据。补 warm-cache OFF、ON→OFF、ON 正常读取和项目切换的具名行为测试。

### R-M19-01 · P2 · 判断A提交中表单仍可改为B，A回执关闭已变更的编辑上下文

**定位**：

- [ReleaseDecisionDialog.tsx:95](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/release-gate/ReleaseDecisionDialog.tsx#L95)：confirmLoading仅表示提交中，Form没有disabled。
- [ReleaseDecisionDialog.tsx:107](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/release-gate/ReleaseDecisionDialog.tsx#L107)：候选版本/策略/各证据控件仍可修改；旧onFinish在await返回true后无条件onClose。
- [use-release-gate.ts:158](https://github.com/a3384379/FlowTest/blob/1038e08ffe078719b7d0fe357d7bc7d0d4a1029a/frontend/src/features/release-gate/use-release-gate.ts#L158)：回执只核路由项目/location，表单值变化不会改变该上下文；成功选中A并返回true。

**触发/实际/预期**：人工提交candidate-A，延迟唯一POST响应；等待期间仍可真实clear/paste把候选输入改为candidate-B；释放A成功回执，UI关闭当前编辑窗口并打开A判断，未区分B是未提交的新输入。预期提交期间锁住对应Form/来源选择；或者以编辑代次保护后续B，明确A的回执身份。不能让屏幕所见B与实际提交A混为同一审核对象。

**证据与限制**：`/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/output/full-review-20261022/m19-delayed-receipt.probe.test.tsx`，真实ReleaseGatePage/useReleaseGate/Form，唯一POST精确为 `{release_policy_id:'00000000-0000-4000-8000-000000000301',candidate_ref:'candidate-A'}`；等待中已确认candidate字段确为B；A回执处理后A详情实际可见，当前编辑dialog的`toBeVisible`失败。响应使用现有decision fixture的合成201/pass，只验证前端异步归属，不作为后端策略/证据完备算法或真实PASS的证据；201/BLOCK也走同一关闭分支。

**实跑**：`CI=true pnpm exec vitest run output/full-review-20261022/m19-delayed-receipt.probe.test.tsx --coverage.enabled=false`，exit1，test1.29s/总2.73s，完整日志 [m19-delayed-receipt-probe.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m19-delayed-receipt-probe.log)。没有证明B值永久删除：Form.useForm在组件顶层，Modal销毁内容不等于清空store。本问题是所见编辑与回执身份混淆/旧完成打断新输入。

**重要反证**：最初“提交中Cancel→重开B”的猜想已撤销。当前AntD6.5.4 `Modal.js:113–120`在confirmLoading时handleCancel直接return，现有取消守卫有效；不能把它重复报为缺口。最终probe不使用取消重开。冻结420d2e0同样未禁用Form，属于历史表单状态缺口在新来源编辑器中仍保留，不声称新版本才出现。

**漏测/最小修复计划**：现有ReleaseGatePage测试覆盖离开发起路由后的成功/失败，却没有同route提交期间继续改候选/策略/证据。最小补修使Form及自定义证据输入（分页/核对/选入/搜索）在提交中统一只读，增加同步防重入或编辑代次保护；不改评估算法、必需/过期/权限门槛。正式反例应使用真实可产生的201/BLOCK fixture，验证A输入冻结、没有第二POST、503后原输入可编辑且只有显式重试、同项目成功/失败以及跨项目旧回执。取消/遮罩/Escape原有AntD守卫继续保留，不提高超时或弱化断言。

### R-M22-01 / P2：审核请求等待期间仍可改 JSON/备注，成功回执关闭后静默丢弃后续输入

**关联**：原 F-AIC-02 的审核编辑保护尚未覆盖 pending 输入。

**精确位置**：`/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/src/pages/AIChangeSetsPage.tsx:516`（JSON TextArea，至 521）、`:525`（备注，至 532）。两者没有 `disabled/readOnly` 绑定 submitting；`:497` 发送当时 content/note，`:158` 在成功后无条件销毁 review。

**触发**：编辑内容 A/备注 N，确认接受；在慢 POST 尚未返回时继续把可编辑文本框改为 B/N2；随后原 A/N 成功。拒绝时备注同样可编辑。

**期望 / 实际**：确认过的提交应锁定正在被审核的输入，或明确保留响应期间的新编辑；实际服务端收到 A/N，而屏幕一度显示 B/N2，原请求成功后弹窗关闭并丢弃 B/N2，没有 dirty 确认。此问题不依赖关闭弹窗：原代码已锁关闭路径，AntD confirmLoading 也阻止取消，但不会替这些 TextArea 设置 readOnly。

**漏测**：页面已有失败保留输入、dirty 取消放弃、修改后接受；导航测试已有迟到回执和同项刷新失败。未测试“POST pending 后继续编辑同一控件”的可达路径。

**最小修复**：仅将 JSON 和备注的可编辑状态绑定 `readOnly || submitting`（或同等 disabled/readOnly），保留原值、JSON 校验、提交同步防重、失败恢复、路由保护和固定基线。不得通过吞掉输入事件、关闭 dirty 检查、自动重发或忽略新值来掩盖。

**红绿验证**：一个受控延迟 MSW POST，真实打开/编辑/确认，pending 时两个输入均锁定且 userEvent 不能改变，取消/X/Esc原保护保留，重复确认 POST 为 1；释放503后输入保留并恢复编辑，显式第二次成功后关闭。另用拒绝备注验证同一锁定语义。回归 AIChangeSetsPage、navigation、use-ai-change-sets 和 SDK；固定来源、baseline/hash、OFF行为断言全部保留。

**排除的候选**：已读当前 `frontend/node_modules/antd/es/modal/Modal.js:113` 的 `handleCancel`：confirmLoading 时直接 return。撤回“生成 Modal 没显式 guard 所以可在 pending 取消重开”的静态推断，不列为缺陷，也不建议为它无证据修改产品。

### R-M24-01 / P2：服务账号签发失败前已清空身份和最小权限 Scope

**关联**：组织 Service Account 原功能的新边界缺口；**不推翻** F-ORG-03 原成员表单的已完成整改。

**精确位置**：`/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/src/pages/OrganizationGovernancePage.tsx:820`：同步 `onCreate(values)` 后立刻 `form.resetFields()`；调用方 `:394` 使用 `workspace.accountMutation.mutate(input)`，`:513` 创建异步 HTTP；`:519` 错误仅 toast。POST 失败时没有任何恢复表单值的路径。

**触发**：Owner/Admin填写名称、稳定标识、多个最小 Scope，点击签发；服务器返回409/403/503或网络失败。

**期望 / 实际**：失败保留原账号身份和权限选择供核对与显式重试；实际请求还没完成就 reset，所有字段和 Scope 消失。签发涉及最小权限配置，用户必须重填，容易选错范围。按钮 loading 不能恢复已经清除的输入。

**漏测**：`OrganizationGovernancePage.test.tsx:42` 只验证成功签发及一次显示；`:563` 验证的是成员表单失败保护，不能覆盖此账号表单。现有成员实现 `OrganizationGovernancePage.tsx:642` 等待结果才 reset，且 DirectoryPicker pending 锁定和自降级目录等待都已落实。

**最小修复**：让 ServiceAccountsTab 的 onCreate 返回可等待的成功结果（或以 mutation 的明确成功身份驱动 reset），只在本次请求成功后清空；失败保持值并显示已有标准错误/Trace。pending 期间显式禁用该表单，避免成功时清掉用户刚写的下一份输入；共享 rotate/revoke pending 的现有角色/令牌一次显示边界保持。不能把 token 或真实输入增加到日志。

**本轮反例**：`frontend/output/full-review-20261022/m24-service-account-retention.audit.test.tsx` 一次运行即精准失败：name/key当前DOM值均为空、已选Scope缺失；精确POST payload、POST=1和没有token断言通过。退出1，1测试失败（三项soft断言），2.78秒；没有MSW未处理请求或真实业务写入。

**红绿验证**：真实页面+QueryClient+MSW的单个 503公开交互反例：填写合成 name/key/scopes，真实点击签发，断言 HTTP 精确负载、失败后重新查询当前 DOM 的三项值保留、POST只有1次、没有一次性token；之后服务恢复，显式重试成功才清空且token显示一次。要重新查询DOM，AntD resetFields会卸载重建控件，旧DOM引用不是证据。建议连同成员失败、自降级、DirectoryPicker和rotation相关文件具名回归。

### R-M25-01 / P2：Lease-only 真实进度事件在事件目录没有任务/Lease下钻入口

**关联**：原 F-FAB-02 的任务/Lease证据链仍有一类实际记录不闭合；已修复的跨组织过滤不应被描述为仍泄漏。

**精确链路**：

1. `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/backend/app/services/runner_fabric.py:586`：真实 progress(message=...) 写入 runner/pool/lease/kind/message，未传 task_id（参数默认 None，`:1314`）；不是合成非法事件。
2. `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/backend/app/repositories/runner_fabric.py:318`：coalesce(event.task_id, lease.task_id) 只用于归属join、组织过滤与 task_id 条件；`:320` 仍 select(RunnerEvent) 并返回原 ORM。
3. `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/backend/app/api/v1/endpoints/runner_fabric.py:211`：直接 RunnerEventResponse.model_validate(item)；schema `/backend/app/schemas/runner_fabric.py:302` 原 task_id 仍 null、lease_id 虽有值。
4. `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/src/pages/ExecutionFabricPage.tsx:431`：事件列表只在 task_id 非空时渲染打开任务按钮，否则 `—`（438行），全列到450没有 lease_id 或授权Lease定位入口。

**触发**：真实 Runner对有效租约报告带 message 的进度；管理员从事件历史看到该条进度。任务可在150+任务历史其他页，不能要求操作者从短Runner ID/消息猜出任务。

**期望 / 实际**：这类已经按租约识别组织并授权返回的任务进度，能进入确切任务及其Lease/Fence证据；实际该行显示任务`—`，Lease ID也不显示，没有入口。手工已知task_id访问任务抽屉能看到此事件，不等于事件目录能定位未知任务。

**漏测**：`backend/tests/test_runner_fabric.py:1473` 明确刻画真实progress.task_id=None；后续只核scope、分页和按已知task过滤包含event，未核HTTP返回可导航身份。前端现有事件夹具有直接task_id，因此不覆盖此公开记录形态。

**最小修复**：复用现有 authorized effective task 解析，为管理事件只读响应显式投影可下钻任务身份（可增加清楚命名的 resolved_task_id，或定义task_id对读取的有效归属语义），前端据此生成任务按钮并可展示完整lease_id。不要把补值写回受SQLAlchemy追踪的事件实体，不修改进度写路径、增加事件/日志/采集或改变Lease/Fence状态机。目录、total、任务过滤和组织边界仍复用同一个授权查询；无法解析的关联保持fail closed，纯Pool注册事件继续没有任务。

**红绿验证**：在既有内存数据库场景调用真实progress→管理HTTP events（不是只看repository）断言可定位task身份；组织A不能读B事件，B和global可读，shared pool纯注册事件保留；两页total无重复。前端以实际DTO形态显示事件，点击打开精确task URL/抽屉，展示同lease及Fence，读取和翻页零Token/Drain/执行POST。回归 test_runner_fabric、ExecutionFabricPage；若新增DTO还跑相应mypy/tsc，组织隔离变更按核心风险补适用整合验证。

## 4. 原73项逐模块复查

以下“符合/整改成立”表示在本轮源码、合同和已存在行为断言范围内未发现原问题仍存在，不代表重新执行了该模块所有测试。所有模块都列出其对应原问题及未验边界，不能用未发现新问题替代真实环境验收。

### M01 · 质量总览

| 原问题    | 原问题标题                                    | 当前核对结果                                                                                                                             | 证据与边界                                                                                                                                                                                            |
| --------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-DASH-01 | Flaky摘要将首100条页内数量作为资产总数        | 主整改符合：后端受权聚合按target_type/target_id去重并保留版本记录数；摘要显示项目累计/观察时间，读取失败为未知；问题队列明确已载入样本。 | 核查backend/app/repositories/quality.py:85、services/quality.py:122、test_flaky_summary_api.py；DashboardPage/useDashboard及现有150条、多版本、503和晚项目反例。另有R-M01-01/02，不把其藏入整体通过。 |
| F-DASH-02 | Flaky问题入口只打开质量中心，没有定位具体资产 | 主整改符合：Flaky入口带record/target_type/target/version；质量中心按ID读页外记录，校验项目和完整locator，固定版本只读证据不取当前draft。 | 核查priority-issues.ts:134、quality-service.ts、use-quality-center及QualityTargetVersion；无效记录/元数据不符不回退另一资产。本轮未重做150条GUI。                                                     |

### M02 · 接口管理

| 原问题   | 原问题标题                                       | 当前核对结果                                                                                                                                                                        | 证据与边界                                                                                                                                         |
| -------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-API-01 | 预期状态码在已有断言时被静默忽略                 | 整改成立。`ExecutionAssertionSummary` 和 `executeApi` 共用 `effectiveApiAssertions`；已保存非空断言优先，快捷状态码仅在保存断言为空时生成，不把草稿值当已保存执行规则。             | `ApiConsolePage.test.tsx`、`api-service.test.ts`。本轮未发目标 HTTP；只读核对实际 payload 构造和结果 scope。                                       |
| F-API-02 | 主接口目录缺方法与路径摘要                       | 原方法/路径摘要整改成立。目录展示 method/path，服务端按当前版本批量取得真实摘要，不从接口名称猜测；没有摘要时明确未提供。另见第2节重命名标签交接，不把它隐入该项通过。              | `ApiConsolePage.test.tsx`、后端 API 列表/当前版本读取路径。固定历史节点不复用当前路径，见第4节。                                                   |
| F-API-03 | 请求响应区不可调整，桌面首屏出现固定最小高度溢出 | 整改成立。`ApiWorkspace` 对目录宽、请求/响应高、折叠提供受边界限制的调整，按 origin/user/project 存储；切布局保留 children，不靠卸载表单重建。                                      | `ApiWorkspace.test.tsx` 包含键盘调整、偏好恢复、输入保留、损坏存储与用户/项目隔离。本轮无新浏览器尺寸验收。                                        |
| F-API-04 | 导出只支持整个项目，缺分组或选中接口范围说明     | 整改成立。导出明确项目/本级分组/未分组/显式ID，跨页选择不由当前列表截断，搜索/方法不暗改范围；服务端先授权，再验证全部选中ID/分组归属及有效性，当前版本缺失拒绝，超额拒绝而非截断。 | `ApiExportDialog.test.tsx`；`api_exports.py:52–145`、`api_assets.py:107`。未逐个打开 HAR/cURL/Bruno/XLSX；本轮只追踪范围合同、固定版本与失败保留。 |
| F-API-05 | 认证配置仍依赖通用键值与技术键名                 | 整改成立。已知认证字段使用专门表单和统一校验，高级未知字段保留；提交时执行校验，不依赖用户先展开认证 tab。没有新增 Secret 值读取或扫描。                                            | `APIWorkbench.test.tsx` 与认证配置函数。未验证外部 OAuth/目标服务认证成功；不把存量 auth_config 与 Secret 值混为一谈。                             |

### M03 · 服务目录

| 原问题   | 原问题标题                                         | 当前核对结果                                                                                                                                                                                             | 证据与边界                                                                                                                                                                                                   |
| -------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| F-SVC-01 | 搜索分页仅覆盖首100条服务，缺服务端目录分页        | 整改成立。服务端按 display_name/id 稳定排序并搜索真实名称/key/description；分页和 total 同 SQL；选中ID独立精确读取，页外资产不换成当前首行。                                                             | `ServiceCatalogPage.test.tsx:70/141/200`；`contract_hub.py` repository 的 page_services 和 ranked page。未生成新百条数据或访问共享 DB。                                                                      |
| F-SVC-02 | 契约和影响链接携带的服务定位参数未被目标页消费     | 整改成立。契约和影响链接携带 contractServiceId，目标页解析并精确授权读取；契约矩阵作为 provider，影响列表/详情把 serviceId传给服务端，不将请求目标 Service 的同名对象冒充映射。非法/不可读ID不自动改选。 | `use-contract-service-context.ts`、`contract-service-location.ts`、`ContractHubPage.tsx:75–147`、`use-impact-analysis.ts:62–90`；已核原测试入口与缺失/旧链接分支。未执行真实 Pact/OpenAPI/影响分析业务写入。 |
| F-SVC-03 | 服务目录仍为登记表格，缺设计中的选中服务详情工作区 | 整改成立。选中服务详情包含稳定ID、描述、契约类型、依赖角色及固定导入版本；OpenAPI/Pact 版本页在本项目及该服务角色下合并，不把项目汇总冒充单服务详情。                                                    | `ServiceContractVersions.tsx`、`ServiceCatalogPage.test.tsx`；服务版本 repository 的 union/provider/consumer 条件。外部契约兼容性成功不是本轮结论。                                                          |

### M04 · 请求目标

| 原问题   | 原问题标题                                    | 当前核对结果                                                                                                                                                                                                       | 证据与边界                                                                                                                                                              |
| -------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-TGT-01 | 配置页仍为高密度技术表格和英文/JSON表单       | 整改成立。服务→当前环境地址的任务链已拆分，typed字符串映射编辑保留高级字段；选择服务只改查看对象，环境默认绑定单独明确提交。凭据引用不读 Secret 值，保存不自动连通性测试。                                         | `RequestTargetsPage.test.tsx` 的查看/编辑/环境消失/只读用例；`EnvironmentEndpointCard` 和 API环境更新只传 default_service_id 的调用。未做本轮布局/真实网络连通性检查。  |
| F-TGT-02 | 影响预览只拼名称，丢弃已有原因和对象定位      | 整改成立。只读候选预览返回 before/after 解析与原因；真实依赖分析遍历主图/regions、固定子流程、用例/套件/计划版本与实际环境。目录/字节/节点/比较预算超限明确 incomplete，不声称零影响；发布策略只称可能关联元数据。 | `test_target_dependencies.py`、`test_target_dependency_api.py`；分析器与repository预算/项目过滤已查。未穷举超大真实库、全部路径模板或执行目标；未把推断影响当运行结果。 |
| F-TGT-03 | 默认Service/API绑定直接提交，没有统一影响确认 | 整改成立。先锁本地候选再显式确认，失败保留；API候选预览与PATCH携同一个 base_version，后端原行锁内409拒绝过期候选；重新分析、取消后的迟到读取有会话/代次守卫。                                                      | `RequestTargetsPage.test.tsx:94/187/753/805/846`，`BindingReviewModal`、`TargetResolutionPreview`、`target_preview.py`。本轮没有重跑 PostgreSQL 并发或浏览器确认。      |

### M05 · 多协议工作台

| 原问题     | 原问题标题                                             | 当前核对结果                                                                                                                                                                                                                | 证据与边界                                                                                                                                                                                  |
| ---------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-PROTO-01 | GraphQL/gRPC调试结果缺Schema与请求序列隔离             | 整改成立。工作区/草稿身份包含项目、协议、资产版本/hash；结果 generation 在编辑和新请求时推进，unmount后不接收旧回执；GraphQL/gRPC/事件协议不共享认证及执行结果。                                                            | `ProtocolWorkbenchPage.test.tsx:197/215/294/406/476/521`，共享结果 hook 与各调用者已核。未重新触发所有真实传输迟到场景。                                                                    |
| F-PROTO-02 | Schema/事件源翻页或刷新会隐式换选中对象                | 整改成立。模式各自保存URL资产/page，页外ID精确读取；Kafka source 与 message schema独立参数，非法mode/ID/page不静默回退。只有首次无ID才规范化默认选择。                                                                      | `ProtocolWorkbenchPage.test.tsx:79/118/142/159`、`protocol-location.test.ts`。未穷举浏览器恢复与所有归档数据。                                                                              |
| F-PROTO-03 | 后端支持的GraphQL Headers和gRPC Metadata没有编辑入口   | 整改成立。Headers/Metadata提供启用/键值入口，提交构造捕获当前规范化数组，修改使旧证据失效；认证引用单独读取，不跨协议继承。运行/导入要求权限成功，缓存权限读取失败有明确停写测试。                                          | `ProtocolWorkbenchPage.test.tsx:215/294/1094`、`ProtocolHeadersEditor`。未验证外部服务端实际接收内容或凭据后端部署配置。                                                                    |
| F-PROTO-04 | Schema检查器主要是哈希/格式/数量，缺结构浏览与输入引导 | 整改成立。检查器从受权固定artifact读取真实SDL/Descriptor路径，懒加载/分页；样例明确点击才写入编辑器，不执行。递归、自定义scalar、unsupported streaming、损坏定义有明确说明，不伪造合法样例；错误alias定位使用同一存储契约。 | `ProtocolContractBrowser.test.tsx`、`test_protocol_structure.py`；`protocol_assets.py:105–185` 的项目/协议归属、2MB及分页上限、GraphQL/Descriptor解析已查。未做全部复杂外部Schema适配验收。 |

### M06 · 项目管理

| 原问题   | 原问题标题                                         | 当前核对结果                                                                                                                                                                                      | 证据与边界                                                                                                                                               |
| -------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-PRJ-01 | 审计日志仅首50条且缺操作者和资源详情               | 原整改成立。审计服务端分页/total/action范围，URL页码非法不放宽；actor当前显示名/稳定ID、resource、trace和授权details分别展示。资源deep-link先经当前项目精确授权读取成功后提供，未知资源不猜链接。 | `ProjectAuditPanel.test.tsx:45/78/110/136/155/168/187`；`ProjectAuditPanel.tsx`与项目审计服务读取已核。未新增真实审计记录/日志采集。                     |
| F-PRJ-02 | 成员与团队面板仍使用UUID，部分读取失败表现为空列表 | 候选搜索、身份回显、目录失败与读取不足禁写整改有效；新增自降级缓存回归仍需修复，见第1节，不能按本页整体无误签收。普通Owner候选仍限定组织，系统管理员目录权限未扩展。                              | `AccessManagementPanel.test.tsx`、`ProjectsPage.test.tsx` 与公开反例；后端最后Owner守卫保持。一次成功PUT后控件未收敛是确认问题，不等同于后端授权被绕过。 |

### M07 · 流程编排

| 原问题  | 原问题标题                                    | 当前核对结果                                                                                                                                                                                                                    | 证据与边界                                                                                                                                                                                                 |
| ------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-WF-01 | 节点摘要不足以读懂真实请求和控制意图          | 整改成立。node-presentation 摘要使用固定api_version；只有目录 current_version与其一致才展示该目录method/path，不拿当前路径冒充历史请求。条件/控制摘要按真实config和节点来源生成且受深度限制，不改节点内容。                     | `editor/node-presentation.test.ts`、`WorkflowNodeInspector.test.tsx`。固定旧版本摘要缺方法路径时明确未载入，不等同于执行引用丢失；未逐个运行28类节点。                                                     |
| F-WF-02 | 控制块内部API/普通步骤的可视化编辑弱于主画布  | 整改成立。region普通节点使用共同NodeEditSession/inspector，并保留节点ID、API版本、service_override和endpoint_variant；仍是全流程一个environment。串行增删移遵循边/依赖约束，不擅自扩展引擎语义。                                | `WorkflowControlFields.test.tsx:141/199/229/572/654/673/710`；region canvas与NestedControlEditor调用链已读。未真实执行全部嵌套、网络及并发控制组合。                                                       |
| F-WF-03 | 高级JSON默认展开并放在条件/区域等主要任务之前 | 整改成立。主要条件/区域任务优先，高级配置受折叠区管理；raw JSON先验证和应用至局部会话，节点Apply再提交图，不能把未应用raw当有效可视配置。                                                                                       | `ControlConfigurationJson.tsx`、`WorkflowControlFields.tsx`、`WorkflowNodeEditSession.test.tsx`。本轮没有逐像素检查默认排版。                                                                              |
| F-WF-04 | 嵌套控制块未应用JSON在切换步骤后静默丢失      | 整改成立。原始输入按完整origin/user/project/workflow/region/node会话标识保留；选择、结构动作、祖先关闭经统一dirty guard；应用时比较内容基线，拒绝覆盖较新内容，位置变化可合并。raw与已应用值分开，不能被外部graph刷新直接擦掉。 | `WorkflowControlFields.test.tsx:19/775/799/1294/1323`、`WorkflowNodeEditSession.test.tsx:143/192/341/385/407`；guard/session/region ancestorclose已核。未重做浏览器刷新/存储配额及所有多层region组合验收。 |

### M08 · 测试用例与套件

| 原问题    | 原问题标题                                         | 当前核对结果                                                                                                                                                                                                                          | 证据与边界                                                                                                                                                 |
| --------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-CASE-01 | 缺前置资源时新建用例只显示禁用，没有缺项解释与跳转 | 整改成立。新建禁用条件与提示同查权限、工作流、环境读取状态；区分loading/error/只读/无流程/未发布/无环境，提供对应入口；不把读错误当没有资源。选项完整收集而非首100条判空。                                                            | `TestAssetsPage.tsx:754–819`、`asset-workspace-service.ts` collectPages；既有创建用例测试来源已核。未新建真实业务资产。                                    |
| F-CASE-02 | 套件编辑关闭没有草稿确认或恢复，和用例编辑不一致   | 整改成立。suite表单会话按origin/user/project/suite区分，close确认/明确丢弃、失败保留、pending关闭保护；保存完成只清理同代草稿，成员固定版本不会因元信息保存升级。                                                                     | `TestAssetsPage.test.tsx:281/323/357/415/446`、`use-suite-edit-draft.ts`、`SuiteDialog`。本轮无真实持久化/跨浏览器恢复验收，草稿会话能力不冒称服务器保存。 |
| F-CASE-03 | 编辑用例和套件时目录选择没有树层级或完整路径       | 整改成立。用例/套件共用完整层级路径TreeSelect，以ID保持身份；同名不同父目录不混淆，已失效ID明确提示而不是替换成任意目录。                                                                                                             | `AssetFolderSelect.tsx`、`test-asset-view-model.ts`、原表单测试来源。未穷举损坏循环目录；合法目录树由既有后端约束维护。                                    |
| F-CASE-04 | 用例目录缺发布状态、最近结果、环境和排序等任务筛选 | 整改成立。发布状态、最近真实运行结果、实际历史环境和排序均经服务端范围查询；先选最近一次再过滤状态/环境，total/目录计数不从当前页推断；URL非法范围不放宽，筛选重置选择。unrun/queued/quarantined无虚构报告，suite待完成历史另有轮询。 | `test_asset_catalog_api.py:29/90/167/259/298/374/501/515`、前端catalog scope/history来源；未重复运行完整容量或实际计划执行。                               |

### M09 · 数据与 Mock

| 原问题    | 原问题标题                                         | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | 证据与边界                                                             |
| --------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-DATA-01 | Mock规则只有创建删除，没有编辑和单规则启停         | 主路径符合，未发现新的可证实缺陷。 MockRouteWorkspace按project/service key隔离；编辑调用原route ID的PUT，启停沿同一routeInput；dirty切规则确认、失败保留输入、pending阻止对象切换；服务名称/说明使用原PATCH，slug未编辑。读权限与写权限分别由MockServiceManager的项目授权和服务/route归属检查。检查：`frontend/src/pages/DataMockPage.tsx`、`features/data-sources/{MockRouteWorkspace,MockRouteForm}.tsx`、`data-source-service.ts`、`backend/app/services/mock_services.py`、`api/v1/endpoints/data_sources.py`。                                                                                                                                                        | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-DATA-02 | Mock匹配条件和响应配置仍依赖四块JSON，缺结构化预览 | 主路径符合，未发现新的可证实缺陷。 string-map高级JSON保留原始重复键检查，Query/Header/响应头的字符串对象合同；response-body JSON值/文本字符串明确区分。Preview受READ及service/route归属限制，候选按priority+created_at，与dispatch同场景、path、条件及模板渲染语义；候选预算越界明确失败而非截目录，预览不写请求日志/审计、不sleep、不发外部请求。读过`domain/mock_preview.py`、`services/mock_services.py`、`repositories/data_sources.py`、前端use-mock-preview代次失效。现有`test_mock_preview.py`覆盖真实dispatch对照、Viewer/外项目、场景优先级、Unicode预算及无捕获写入；domain测试覆盖类型/错误位置/重复创建顺序，MockRouteForm/Workspace测试覆盖晚返回和失败保留。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：没有再次运行真实Mock/HTTP、Unicode大对象或真实浏览器；数据库读取间并发变更、所有反向代理路径编码组合不作运行正确性承诺。

### M10 · 契约中心

| 原问题  | 原问题标题                                                  | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | 证据与边界                                                             |
| ------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-CT-01 | OpenAPI批次/候选固定首100条；兼容提供方选项只来自当前目录页 | 主路径符合，未发现新的可证实缺陷。 ContractAutomationPanel的run/cases分页携带服务端total及review过滤；selected run按ID查询独立于目录；review显式绑定item.contract_run_id+item.id，回执只关闭相同item；Provider/Pact/baseline使用ContractReferencePicker独立分页/搜索+精确读取，不依赖初始化目录前100项。backend repositories/contracts.py、contract_hub.py使用稳定排序和目录元数据分页。查看的测试含第101批次/候选、页外选项失败重试、Viewer写403/外项目404、相同候选失败输入保留。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-CT-02 | 发布阻断证据和契约变更主要停留在数量摘要                    | 主路径符合，未发现新的可证实缺陷。 ContractEvidenceDrawer按固定run/pact/verification/check读取，历史栈防循环；verification引用其原pact，actual明确“未采集”，不冒充expected；blocker/pending逐条及原文保留。get_pact/get_verification/get_deployment_check先项目READ再归属检查，不启动Provider/Broker。检查`ContractEvidenceDrawer.tsx`、`contract-hub-service.ts`、`backend/app/services/contract_hub.py:274–316`、`test_contract_catalog_evidence.py:178`及对应公开页面/抽屉测试。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：未联系外部Broker/Provider，未运行完整102候选GUI、数据库分页fixture或真实验证；没有将只读证据支持等同验证网络行为通过。

### M11 · 测试工程

| 原问题   | 原问题标题                                           | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | 证据与边界                                                             |
| -------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-ENG-01 | 空覆盖项被显示为100%覆盖                             | 源码及已有行为符合。 DesignCoverageSummary严格区分undefined、空、未评估boolean缺失、0/1及1/1，不把空覆盖画成100%。检查DesignCoverageSummary、DesignReviewTables、TestEngineeringPage测试的覆盖边界；不改变engine分母。                                                                                                                                                                                                                                                             | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-ENG-02 | 物化成功只弹数量，丢弃具体Workflow/TestCase定位      | Alembic主路径已实现；Standalone未闭环（R-M11-01/P1）。 新Apply在同一事务写原始workflow/case引用，GET按project+design+source_change_set恢复，并批量过滤外项目资产；legacy只恢复原testcase refs，不从可变draft猜workflow。前端保留回执、显示逐资产精确入口，刷新目录/相关资产查询，不自动发布/执行。0064有升降级；现有test_test_engineering_assets验证编辑可变case后原引用仍在、Viewer、外部篡改引用，Hook测试覆盖失败Apply、切项目/Proposal及卸载迟到。这些不覆盖旧Standalone缺列。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-ENG-03 | 主要页面大量开发阶段标签和英文术语，证据引用不能钻取 | 源码及已有行为符合。 DesignEvidenceWorkspace按完整来源身份/修订/字段路径展示，只解析受支持内部引用；来源API用固定版本，未知ref保留原文；materializationBlocker保留仅设计/无唯一状态预期的禁用原因。覆盖顶层auth与相对路径、只读Viewer、来源读取失败重试；不把人工accepted当可执行证明。                                                                                                                                                                                            | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：除R-M11-01真实启动ORM反例外，不重跑生成/接受/Apply或PostgreSQL64往返；真实生成质量与所有Oracle组合未逐个执行。

### M12 · 任务执行

| 原问题    | 原问题标题                                       | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                                                                            | 证据与边界                                                             |
| --------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-TASK-01 | 新建计划只能添加一个目标，未开放后端多执行项编组 | 主路径符合，未发现新的可证实缺陷。 CreatePlanDialog使用1–100有序items，目标选择时写current_version；三种类型、上下移/删除、逐项重试和workflow环境都保留。case/suite明示继承固定发布配置，不伪造不支持的覆盖。TestPlanTargetSelect独立服务端目录分页/搜索和精确读，因此初始100项不是完整候选上限；SDK实际发送item顺序，编辑旧计划只调度/启停，不替换targets。backend原TestPlan创建/固定版本展开合同仍在；test_tasking_api包含固定套件成员版本、CI/Webhook/retry/cancel。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-TASK-02 | focus链接仅高亮当前页，运行详情不进入URL         | 主路径符合。 focus精确读与list分离；run直接get详情，SDK校验project+id；execute用真实返回run.id写URL，关闭run保留focus。isCurrent同时包含project/focus/run和DataRouter当前location；现有用例覆盖第21计划、run history返回、404/503不回退、切项目/切运行/卸载/precommit晚回执。TestPlanRunDetails的item URL可定位第21项并回到选中页。未看到读链接自动execute。                                                                                                            | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **检查路径**：`frontend/src/features/task-plans/{CreatePlanDialog,TestPlanTargetSelect,FocusedTestPlan,TestPlanRunDetails}.tsx`、`use-test-plans.ts`、`task-plan-service.ts`；对应页面/SDK/Hook测试；batch30用于确认用例运行源与已发布定义的边界，没有把它算作新增M12后端能力。
- **本轮未验**：没有实际Scheduler/Cron/签名Webhook/Worker/取消，100项目录及环境组合只读代码和原断言；未声称实际排队、容量或一次性真实凭据验收。

### M13 · 环境实验室

| 原问题   | 原问题标题                                      | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                        | 证据与边界                                                             |
| -------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-ENV-01 | 模板创建固定单web服务，完整版本维护退回整份JSON | 主路径符合。 共用EnvironmentTemplateDialog/ManifestFields读取完整所选manifest，不以首service/seed重建；1–5服务、依赖/循环、变量、health浮点精度、resources、seed、TTL与高级JSON显式应用均保留。unknown keys拒绝，安全flags固定true；没有任意command/volume。dirty/提交保护与scope上下文守卫保持。检查environment-template-manifest.ts与后端domain/environment模板模型、现有多服务/seed/0.15精度测试。               | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-ENV-02 | 实例绑定模板配置受当前模板目录页限制            | 主路径符合。 ProvisionCard有独立分页/搜索/UUID精确读；实例绑定版本来自原template_version_id的项目受权接口，管理员全局停用读取和普通读者自己的绑定读取边界分开。服务校验key/version/manifest hash+签名，错误不fallback最新；禁用后刷新目录、精确版本和实例绑定查询。检查environment-service.ts、use-environment-lab.ts、backend/services/environment_lab.py:183–248、test_environment_template_reads及SDK/页面测试。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：未运行环境Docker daemon、容器Provision/健康检查/Seed/cleanup；签名与只读归属只核源码及既有断言；不会把合成failed历史实例当真实运行成功。

### M14 · 性能实验室

| 原问题    | 原问题标题                                       | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                      | 证据与边界                                                             |
| --------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-PERF-01 | 新建只支持单HTTP步骤，复杂负载与版本维护依赖JSON | 主路径符合。 PerformanceScenarioDialog+DefinitionFields和performance-definition完整保留多steps、headers/body、stages、thresholds、graceful stop；constant/ramping草稿分别保存，提交只规范当前模型字段；高级JSON经同一校验显式应用，unknown/非HTTP/总阶段时长超限拒绝。新版本只从已发布原版本派生，已有run摘要使用冻结snapshot，不读当前draft替换。对应页面/编辑器/SDK原测试保留原始下载、完整多项保留和JSON反例。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-PERF-02 | 启动运行后未选中新运行或提供直接进入证据的入口   | 主路径符合。 startRun立即缓存真实202对象并selectObject(run,id)，清scenario；run detail按queued/running有界轮询；失败不清原selection、不自动再次POST；project/scenario/run及DataRouter precommit身份守卫。检查use-performance-lab.ts、performance-service.ts及两个Hook命令测试，涵盖旧运行→新返回ID、终态和原生路由迟到。                                                                                          | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：不执行k6、真实负载/网络隔离、产物下载或CPU容量；不是性能执行指标真实性验收。

### M15 · 测试报告

| 原问题   | 原问题标题                                                | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | 证据与边界                                                             |
| -------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-REP-01 | 默认选中节点未规范化到链接上下文，跨视图跳转改变选中节点  | 主路径符合。 ReportExecutionWorkspace先failed后已执行业务节点；节点/attempt规范写URL，reportExecutionPath/workflowExecutionPath保留同execution及控制实例；显式失效节点显示警告，切node清旧instance。WorkflowControlEvidence复用控制证据读取，不从当前流程草稿还原。现有ReportsPage/执行导航/控制报告测试覆盖默认业务节点、失效显式node和冻结画布关联。                                                                                                                                                                                       | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REP-02 | 断言证据来源主要是静态文字，缺上游来源路径与直接定位      | 主路径符合。 assertion-source优先冻结实际字段，仅单条Assert允许从同次frozen definition补全；缺/冲突/未知expression不猜测source；sourceAttempt从已存observation取对应尝试，无法解析区域来源轮次明确不跳到别的instance。API断言原始target/operator未保存时明确未提供；use-checkpoint-assertion-source区分普通checkpoint与嵌套ID。原断言测试覆盖同次来源、缺失与冲突、固定/动态期望、区域实例边界。                                                                                                                                             | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REP-03 | 报告与流程证据仍以通用pre JSON展示，缺API工作台的阅读工具 | 主路径符合。 通过WorkflowEvidencePayload复用ResponseCodeReader，搜索/复制/行号/换行/有界预览与原artifact下载保留，不新增采集或做OFF值扫描；scope变化清旧源，不把下载预览片段充作完整捕获。                                                                                                                                                                                                                                                                                                                                                   | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REP-04 | 报告缺时间、流程、环境或用例等任务维度筛选                | 主路径符合。 report-scope规范UTC首尾范围（1–90天）、非法URL停query；list与trend传相同scope。repository `_execution_criteria`共享project/root执行、时间/状态/流程/环境/case/plan/source条件，list用ranked atomic page；trend全匹配聚合，不用当前页；完成分母排除queued/running，空分母null。历史筛选选项独立分页/search/selectedID，计划正式来源优先并兼容legacy，原重试执行关联不只保留最后一次。检查backend domain/repositories/services/reporting.py、report-scope/ReportFilters/use-reports及test_reporting_api；没有以分页样本充作全量。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REP-05 | 节点页的检查点日志没有沿节点/尝试筛选                     | 主路径符合。 ExecutionCheckpointLog默认按node/instance，显式切全部执行；node/checkpoint-attempt同时传服务端predicates，total与rows同scope；切scope/attempt清page/selected详情。HTTP重试与checkpoint attempt分别解释，legacy缺字段可从全部执行核对，不冒充当前节点。检查durable_execution service/repository及日志组件测试。                                                                                                                                                                                                                  | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **新增边界未闭环**：通知配置不属于上述只读证据定位，却共用同页；其project state和迟到回执未隔离，见R-M15-01/P2。
- **本轮未验**：不重新执行loop/parallel/retry/dataset、导出或下载真实artifact，不扩大历史采集；区域跨节点来源无法唯一还原时明确未知是当前合同，不视作伪造入口。

### M16 · 影响分析

| 原问题   | 原问题标题                                            | 当前核对结果                                                                                                                                                                                                                                                                                                                                                             | 证据与边界                                                             |
| -------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| F-IMP-01 | 三列影响视图是静态列表，缺变更到资产/证据的联动定位   | 主路径符合。 ImpactEvidenceWorkspace分别读取冻结graph与selection；change_keys过滤关系/推荐/coverage，asset/change写URL；assetEvidenceIssue拒绝无关联组合；未知graph引用保留原文，不猜固定版本；QualityAssetEvidence打开已知固定workflow/case版本或精确契约/性能对象。切run/变更清旧选择。原测试覆盖一变多资产、一资产多变更、缺口、无关联URL、固定旧版本及off-page run。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-IMP-02 | 资产列数量使用边数，映射摘要只统计当前页且关闭态显示0 | 主路径符合。 graph assets按edge.to分组去重并独立显示关系数；mapping显示Page.total和已载入长度，功能关闭/flag错误/目录失败不显示0。useImpactAnalysis的功能成功态、项目/route/卸载回执守卫保持。检查impact-service.ts、use-impact-analysis.ts、ImpactAnalysisPage、ImpactEvidenceWorkspace及backend/impact frozen生成/项目授权合同。                                       | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：不运行Git命令/仓库分析、真实多来源mapping或生成新run；原全映射摘要与本轮当前目录不是同事务快照，未额外承诺并发全站一致性。

### M17 · 变更回归

| 原问题   | 原问题标题                                                   | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                                                      | 证据与边界                                                             |
| -------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-REG-01 | 缺失测试可以接受/拒绝，但没有展示待审核的具体提案内容        | 主路径符合。 必须打开MissingTestReview抽屉看完整proposed_content与来源/指纹/候选；打开时structuredClone冻结，背景刷新不替换，显式refresh代次隔离。review固定run.id/item_id/expectedContent，服务端锁内检查所见快照（含缺失/null拒绝）。接受后仍需批准/执行，按钮锁提交；Viewer禁写。原公开测试覆盖后台刷新、409、主动刷新失败/重试、旧刷新不能覆盖新审核。                                                                                        | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REG-02 | 新建回归强制Git Diff，不能通过已有OpenAPI/Schema版本差异发起 | 主路径符合。 RegressionSourcesEditor保留Git输入并提交真实OpenAPI/GraphQL/Proto配对，至少一种来源；共享后端impact输入校验即便混Git也拒绝相同版本；项目/协议由现有服务检查。RegressionSourceSnapshot从原Impact frozen source_summary读精确版本，不拿当前目录替代；协议URL `graphqlSchema/grpcDescriptor`与目标工作台实际解析一致。对应页面测试含无Git创建、混协议、相同/缺/目录外反例及来源冻结。                                                   | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REG-03 | 关键链路证据ID仅文本，失败分类无法定位具体运行和证据引用     | 主路径符合。 RegressionChainLinks使用impact run / plan run+focus / release decision；Triage只解析受支持flowtest引用，并先查父计划run核对实际execution/item归属；未知、foreign或unavailable保留原文不拼假链接。物化资产来自generated_assets与source_item_id，不从designID猜workflow；计划item能定位页外。检查RegressionEvidence、SourceSnapshot、use-change-regression及TestPlanRunDetails；现有测试核零写导航、未知引用及阻断未生成Decision状态。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：未接受/批准/执行链路、未评估真实发布门禁，语义缺口/豁免过期算法只检查守卫未运行全部组合；没有把只读链接可用性当端到端实际执行成功。

### M18 · 质量中心

| 原问题   | 原问题标题                                         | 当前核对结果                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | 证据与边界                                                             |
| -------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-QLT-01 | 启用门禁统计包含停用门禁                           | 主路径符合。 qualityGateCounts filter(enabled)并另标total；页面只在gates读取成功后传数据，loading/error为未知。现有测试覆盖2启用/1停用、全停用、读取失败，不用length冒充启用数。                                                                                                                                                                                                                                                                                                                                                                                                                                | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-QLT-02 | 风险历史有翻页却无记录选择，资产和运行也缺证据入口 | 主路径符合。 risk历史任意行可selectEvidence写URL，首次最新固定后翻页不改risk，明确ID失败不回退；Flaky record按ID独立读取并校验完整target_type/id/version元数据。QualityTargetVersion查真实固定版本，不取当前draft；推荐各类型进入精确对象，clusters样本以executionID进report，plan baseline携run。service READ+project限定新增record读取；stable Flaky排序含ID，避免同分同时间翻页重复。isCurrent与canEdit的permissions.isSuccess防旧许可/迟到隔离提示；read actions不自动quarantine/execute。检查quality-metrics、QualityEvidence、quality-service、use-quality-center、backend/quality及原记录读取/排序测试。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：未生成真实风险、隔离/恢复记录、下载JUnit或重新跑150条分页fixture；没有依据早期合成数据计数声称当前真实质量总量。

### M19 · 发布门禁

| 原问题   | 原问题标题                                                          | 当前核对结果                                                                                                                                                                                                                                                                                                                                              | 证据与边界                                                             |
| -------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| F-REL-01 | 项目发布判断依赖管理员全局Runner任务目录，且只截首100条后客户端过滤 | 主路径符合。 页面不再调用全局execution-fabric tasks API；ReleaseGateService list/get_runner_evidence先项目READ，repository限定project后分页/search/exactID；DTO最小摘要，不给全局管理权。检查release-gate-service、use-release-gate、backend release_gate service/repository/API与test_release_gate中项目Owner/Viewer、101+、外项目反例。                 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REL-02 | 生成判断没有按所选策略展示必需证据/关闭原因，性能证据仅当前20条     | 来源选择主路径符合，提交编辑边界未闭环（R-M19-01/P2）。 六类required根据selected policy读取；disabled/flag失败/目录失败/空区分；各类分页，performance/runner跨页search，六类精确ID读+显式选入，风险和Impact关联在提交前及后端都校验；不默认填来源，缺项仍按后端BLOCK。ReleaseDecisionDialog同route提交中未锁Form，见实跑反例，不能以跨route迟到用例替代。 | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |
| F-REL-03 | 判断证据缺到原始对象的结构化跳转                                    | 主路径符合。 ReleaseEvidenceSources只在快照来源ID与decision引用完全一致且UUID合法时给入口；四类精确跨页URL、contract/runner项目受权只读抽屉，未知历史保原文。policy/evidence snapshot由create_decision按值保存并指纹化，读取不重新评估。原后端用例验证修改当前策略不改旧判断及cross-project拒绝；Runner/契约源链接不触发执行/Provider。                   | 本轮具体未验范围见本模块下述说明；既有测试为源码核对依据，未全量重跑。 |

- **本轮未验**：除R-M19-01纯MSW页面反例外，不创建真实Decision、不访问外部Runner、不触发发布/部署；过期/终态与门禁算法保留既有合同，未通过合成201/pass反例声称它们重新验收。

### M20 · AI 助手

| 原问题  | 原问题标题                                                | 当前核对结果                                                                                                                                                                                                      | 证据与边界                                                                   |
| ------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| F-AI-01 | 四种AI任务使用同一Schema/元数据JSON表单，接受也只编辑JSON | 四种任务有各自材料字段，Schema仅在真正需要的任务要求；公开来源显式展开、选择固定版本、最终payload预览；服务端project授权、具名列及1MiB限制；结构化建议和原文均可审核。ON/OFF按请求策略执行，OFF的敏感判断均短路。 | 未重跑真实网关/样本授权业务；当前源代码未确认新增P1/P2。                     |
| F-AI-02 | 任务失败原因和接受后资产字段未展示                        | error/time/无Trace说明、job/suggestion URL和已审核备注/真实resource ID已展示；普通change_set job守卫存在，迟到回执带项目/路由身份。                                                                               | **R-M20-01**：新工作流结果实际消费者缓存遗漏，链接正确不能证明打开对象正确。 |

### M21 · 上下文检查器

| 原问题   | 原问题标题                                             | 当前核对结果                                                                                                                                                                                        | 证据与边界                                                                                                   |
| -------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| F-CTX-01 | 证据、冲突与知识关系是长列表，缺来源联动和精确引用定位 | 五分区、冲突fingerprint→证据、知识evidence_ref唯一匹配、来源/修订/路径、筛选计数和Proposal深链已实现；backend按revision取证据/同revision提案；前端错project/id拒绝、旧revision不冒充当前，URL固定。 | 未发现新增可证实P1/P2。当前接口仅当前revision是明确能力边界，不要求新写接口；本轮未独立执行浏览器/后端合同。 |

### M22 · AI 变更集

| 原问题   | 原问题标题                                                 | 当前核对结果                                                                                                                                                                                                                                         | 证据与边界                                                                    |
| -------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| F-AIC-01 | 修改项没有目标基线与前后差异，来源证据也没有进入审核面板   | source_snapshot和独立review_baselines持久化，type/id/hash唯一匹配，历史缺失明确警告，无当前资产冒充；省略运行字段合并规则与后端一致，assertion要求完整workflow定义；0065及Standalone补列可见。                                                       | 未执行真实生成期间并发漂移或升级；源码未确认该项新倒退。                      |
| F-AIC-02 | 接受后无物化资产入口，审核编辑关闭会直接丢弃               | materialized type/id入口、review actor/time/note、dirty关闭/路由保护、失败保留和同步pending防重存在；原项目草稿目录/详情缓存失效存在。                                                                                                               | **R-M22-01**：提交期间输入仍可变。生成Modal取消重开候选已按AntD实际合同排除。 |
| F-AIC-03 | AI/质量智能开关与只读历史提示不一致，关闭态仍请求并重试503 | list/get仅项目读授权，create/review保留AI+质量智能开关；UI关闭生成/审核/轮询、保留历史及错误提示。OFF `_target_definition_for_ai:575` / `_restore_redacted_value:690` / create guards:998,1022 均在敏感扫描/恢复之前短路，字面REDACTED不是替换指令。 | 未发现已修OFF合同的新P1/P2；未把普通AI历史review策略和专用M22混为一个合同。   |

### M23 · MCP 变更集

| 原问题   | 原问题标题                                                  | 当前核对结果                                                                                                                                                                                                                                                                         | 证据与边界                                                                                                             |
| -------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| F-MCP-01 | 返回的warnings与Trace ID、置信度/风险原因未进入审核页       | Envelope warnings/trace、置信度/原因及approval actor/time展示；editable依赖当前精确读取/权限成功，失败需重新读取恢复；服务端accept验证实际approved及approval_id，读者不能Approve/Review。                                                                                            | 未发现新增P1/P2；未接真实外部MCP客户端或压力并发审批。                                                                 |
| F-MCP-02 | Test Design/TestCase/TestPlan更新缺结构化预览和物化结果定位 | Design/Case/Plan/Workflow各结构化只读预览；计划before缺字段明确说明；设计结果校验cs/item/accepted/type/materialized ID/project/source；其他类型链接到实际workflow/assets/tasks消费者，workflow+workflow目录及plan查询前缀已失效；控制块expected_revision和plan指纹仍服务端原子守卫。 | 未发现新增可证实P1/P2；本轮未实测四类真实物化、外部客户端/生产运行。旧图刷新失败带错误，不能仅凭缓存保留猜跨项目漏洞。 |

### M24 · 组织治理

| 原问题   | 原问题标题                                                          | 当前核对结果                                                                                                                                                                | 证据与边界                                                                             |
| -------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| F-ORG-01 | 审计/Runner/安全/支持包读取失败未显示对应错误，安全区仍固定宣称可用 | members/accounts/governance/runner/security/support/audit独立读边界，pending/403/error不回退成功空；security必须真实能力字段成立，失败时无操作；支持包按已授权字段展示。    | 未发现原读取失败伪健康问题重现；本轮未真实KMS/重加密。                                 |
| F-ORG-02 | 组织审计固定首50条且缺操作者和资源定位                              | 服务端total分页和action/actor/resource/time过滤，数据库同过滤计数，详情展示允许details；org key卸载清理上组织筛选/详情，403不显示旧数据。                                   | 未发现新增P1/P2；未向共享审计库写记录或测试保留策略清理。                              |
| F-ORG-03 | 组织成员需填用户ID，提交尚未成功就清空输入                          | 成员请求await后成功才reset，失败保留身份/角色；有权限目录、UUID高级定位、pending显式禁用DirectoryPicker；自降级等待members+精确organizations刷新，canManage随返回角色收紧。 | 原成员整改已落实。相邻Service Account为独立 **R-M24-01**，不将其倒算成原成员问题未修。 |

### M25 · 分布式执行面

| 原问题   | 原问题标题                                         | 当前核对结果                                                                                                                                                   | 证据与边界                                                                                           |
| -------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| F-FAB-01 | 队列分组统计只取最近100个任务，Pool目录也固定首100 | SQL按全部授权任务聚合，不用近期100样本当总计；Pool/任务/Lease/事件Page total，准确scope/generated_at，失败累计语义标注；后端仍system admin并按org/shared范围。 | 未发现该项新增P1/P2；本轮未制造150任务/101池或真实capacity场景。                                     |
| F-FAB-02 | 执行面不定时刷新且没有任务/Lease详情定位           | 可见15s轮询/隐藏停止/manual刷新/成功时间、旧数据失败提示、精确task drawer、多Lease/Fence有效性与workflow/report来源已实现。                                    | **R-M25-01**：真实lease-only进度行缺回到任务的可消费身份；已修共享Pool组织过滤保留，不报告为新泄漏。 |

### M26 · 平台管理

| 原问题    | 原问题标题                                     | 当前核对结果                                                                                                                                                                   | 证据与边界                                                                      |
| --------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| F-PLAT-01 | 切换插件/Runner后右侧仍展示上一个能力详情      | URL选择为typed mode+ID+version，切模式清空；key含user/org/admin、detail含完整选择；exact endpoint不回退首能力；普通角色不读取管理库存，Pool使用org/shared边界，插件安装禁用。  | 未发现新增P1/P2；未真实安装插件或接Runner。                                     |
| F-PLAT-02 | 能力检查器没有提供已返回的完整Schema和策略字段 | 三份完整Schema及policy原值只读阅读器，复制/下载使用完整formatCode文本，预览300行/64k与顶层200项有清楚说明；hash/Digest完整、timeout/network/DNS/snapshot按返回值，未知值保留。 | 未发现新增P1/P2；本轮源码核对download Blob/原值，不声称浏览器下载字节重新验过。 |

### GLOBAL · 全局壳

| 原问题  | 原问题标题                                         | 当前核对结果                                                                                                                                                       | 证据与边界                                                                                                                                           |
| ------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-UX-01 | 全局搜索请求失败被显示成没有可访问资产             | 源码及既有行为依据符合：503显示标准错误/Trace与显式重试；可用旧结果明确标识，关键词queryKey隔离晚响应，不缓存成功空目录掩盖失败。                                  | 核查GlobalSearch.tsx和3个现有测试；auth epoch在main.tsx:28清QueryClient。无真实搜索服务故障注入。                                                    |
| F-UX-02 | 接口标签读取的缓存键少了版本维度，名称不能更新     | 仍有闭环缺口R-GLOBAL-01：已有实际版本query key和稳定definition缓存；非活跃接口目录重命名后该缓存不更新，真实UI目录和对象标签不一致。                               | 本轮真实ApiConsolePage+WorkspaceObjectTabs公开反例已复现，PATCH=1、A仍选中、B目录新名而tab旧名、B详情未重读。                                        |
| F-UX-03 | 对象标签页自动累积模块入口，重复承担第二份模块导航 | 源码及既有行为依据符合：只有API/workflow focus及report execution登记tab；坏/外部/跨项目href拒绝，旧无对象模块记录清理不删除草稿；关闭保留完整href并受dirty guard。 | 核查workspace-tab-store、WorkspaceObjectTabs与现有8个测试；App按user/project key重建；本轮报告/画布往返实页未新增模块tab。未逐26模块重做浏览器恢复。 |

## 5. 跨模块链路复核

- 接口当前摘要与固定API版本分开：主画布和区域节点发布时校验原版本、服务覆盖及Endpoint Variant；用例/套件运行来自已发布固定定义。草稿未保存不冒充可执行版本。保存不自动发布/运行。
- 请求目标继续采用一个流程一个environment_id，节点可选service_override / endpoint_variant；未以本轮审计悄悄新增逐节点environment_id或改变引擎语义。
- 首页失败记录→报告→定位画布实际保持 execution=`4e9105f7-ebcd-463d-a246-4306f2b4352a`、node=`m17-check`、attempt=`1`，画布显示历史执行快照及只读，来源与URL一致。此处原关联整改有效；不是对所有嵌套/重试组合的实跑签收。
- 普通AI与MCP物化不是同一缓存链：MCP当前已处理真实消费者目录，普通AI仍存在R-M20-01，不能因MCP通过就判普通AI结果正确。
- 组织成员自降级已经等待组织权限读取；项目成员面板却缺对应权限缓存失效（R-M06-01）。同名“成员管理”不代表两条路径共享正确性。
- Mock Preview已沿真实dispatch匹配与受权查询核对，未通过为了预览新增执行/日志；报告、影响、风险、发布判断均追踪冻结引用，未知/不可唯一解析的历史来源明确保留原文。

## 6. 本轮实际验证与证据边界

### 6.1 有效反例

以下9个反例均按正确行为写断言，当前实现分别失败，属于已复现问题，**没有任何修复后转绿**。使用原Vitest/Pytest配置、原timeout/worker/重试边界；没有调整业务断言、覆盖阈值或视觉阈值。

| 问题        | 实际入口                               | 关键观测                                                                    | 完整最终日志                                                                                                                                                                                  |
| ----------- | -------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R-M11-01    | 真实initialize→ORM                     | 完整旧设计表仅缺64列；初始化后仍缺列                                        | [m11-standalone-materialized-assets-probe.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m11-standalone-materialized-assets-probe.log) |
| R-M20-01    | 实际AI页面接受→Link→真实useWorkflows   | 生产15秒staleTime；2850ms内catalogReads=1、GET新ID=0、仅一次接受，实际仍旧W | [m20-ai-result-navigation.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m20-ai-result-navigation.log)                                 |
| R-M15-01    | 真实ReportsPage+Router                 | A唯一POST，B Viewer状态已生效，仍出现A合成secret                            | [m15-cross-project-secret-probe-r4.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m15-cross-project-secret-probe-r4.log)               |
| R-M06-01    | 真实ProjectsPage/hook/cache            | 两个Owner合法自降级，成员已viewer，permissions仍owner、管理按钮仍enabled    | [m06-self-demotion.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m06-self-demotion.log)                                               |
| R-GLOBAL-01 | 真实ApiConsolePage+WorkspaceObjectTabs | B目录新名，A仍selected，B详情未重读、tab仍旧名                              | [global-inactive-api-rename.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/global-inactive-api-rename.log)                             |
| R-M01-02    | 真实ASGI+SQL                           | 目录/permissions200，但团队项目dashboard summary/recent404、全局项目0       | [m01-team-scope.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m01-team-scope.log)                                                     |
| R-M01-01    | 真实DashboardPage+QueryClient          | OFF+旧cache，仍1次详情503，关闭提示可见、错误隐藏                           | [m01-warm-off.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m01-warm-off.log)                                                         |
| R-M19-01    | 真实ReleaseGatePage/hook/Form          | A POST期间B可编辑，A成功后关闭B界面并展示A                                  | [m19-delayed-receipt-probe.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m19-delayed-receipt-probe.log)                               |
| R-M24-01    | 真实OrganizationGovernancePage         | 503后重新查询当前DOM的name/key/scopes全空；精确一次POST、无token            | [m24-service-account-retention.log](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m24-service-account-retention.log)                       |

临时前端probe原位于 `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/frontend/output/full-review-20261022/`，后端probe在同树 `backend/output/full-review-20261022/`。具体文件名、命令、fixture和退出状态见各问题详解及[证据清单](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/audit-manifest.json)。前端使用 `CI=true pnpm exec vitest run <单个probe> --reporter=verbose`；后端使用 `uv run pytest --no-cov <单个probe>`，团队授权probe额外 `PYTHONPATH=tests`复用既有fixture。正式修复应把必要反例迁入对应具名测试，保留原问题级别断言。

另有两个原 `test_dashboard_api.py` 直接成员/系统管理员对照用例实际通过，记录在[原始对照日志](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m01-team-scope-setup-attempt.log)；该次probe自身缺created_by_id的准备失败单独剔除，不能将混合命令写成整组通过。

R-M22-01 / R-M25-01本轮为源码确认，未新增动态probe。相关实现与现有测试已读，后续补修先增加对应可失败行为测试，不能把它们写成9个实跑反例中的一部分。

### 6.2 排除的误报与保留的诊断

- M03 / M19 / M22“confirmLoading时仍能Cancel→重开B”的静态猜想已撤销。当前AntD6.5.4的handleCancel在confirmLoading时直接return；M03未观察到声称的错误，不计问题，也不据准备失败判整个模块不正确。最终M19反例是提交中仍可编辑，同取消重开无关。
- AntD关闭不必卸载DOM，具名Dialog可能受测试宿主标题关联影响；相应准备失败没有当作产品问题。M15最终使用公开Router切换而非假设Cancel成功。
- 全局重命名首轮缺B预览handler、M01诊断重复文字和团队fixture缺creator、M20首轮目录handler/图标按钮名等均保留原日志。修正的是探针准备，未改变产品或降低预期。
- 缓存权限200后重读503是否必须停写，需以各功能明确合同判断；没有将尚不确定的共享缓存策略差异升级为本报告确认项。

### 6.3 CI与发布验收不能混用

历史证据显示上述main的 Full Regression [39671687547](https://github.com/a3384379/FlowTest/actions/runs/39671687547) 已成功；原始精确head证据保存在 [final-main-run-evidence.json](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/final-main-run-evidence.json)。该历史结果包含后端1948通过/14跳过、前端1353通过/182文件、Compose67通过；本轮没有重新运行它们，也没有从该green推断11个遗漏场景已正确。

本轮未运行make check、完整覆盖率、构建、全量Compose、Windows打包/实体旧安装、真实LLM/MCP/Runner/KMS、生产故障转移、容量或部署验收；只有M11执行了独立临时SQLite的真实初始化反例。26模块全量逐像素/移动端验收也未在本轮重做。上述限制不妨碍已复现问题成立，亦不能由本报告扩大结论。

## 7. 文档、实现和后续交付状态

新增本报告与配套详细方案；原2026-10-19审计/方案和产品代码均未修改。没有在本轮创建PR、合并业务修复或部署。修复完成条件是逐项反例转绿、相关集成检查、最新head正式门禁及适用部署验收分别有证据；不能把本报告形成当作修复完成。

完整审计分工记录保留为 [M02–M08](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m02-m08-review.md)、[M09–M19](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m09-m19-review.md)、[M20–M26](/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/full-review-20261022/m20-m26-review.md)；主报告已经纳入全部原73项和11个问题，不需要阅读分工记录才能理解结论。
