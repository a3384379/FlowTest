# FlowTest 全模块审计整改实现与验证记录

日期：2026-10-22。对应[修复前审计报告](complete-review.md)及[详细修改方案](remediation-plan.md)。基线 main：`1038e08ffe078719b7d0fe357d7bc7d0d4a1029a`；实现分支：`codex/full-module-remediation-20261022`。

## 1. 交付范围与状态

本次针对已确认的11项问题实施修复。范围包含旧Standalone兼容、资产结果消费、项目权限及缓存、功能开关、提交期间输入状态和执行证据下钻。原2026-10-19审计及方案保持冻结；本文件记录后续实现，不能用原基线CI结果代替整改后的验证。

**11项整改、三组独立 max 源码复审、具名回归及首轮完整本地检查已完成；首轮远程发现两项测试超时，补修与验证见5.3。** 本地具名验证、完整本地检查、最新提交的远程门禁、合并及部署验收分别记录；最终提交与门禁状态统一以[PR #148](https://github.com/a3384379/FlowTest/pull/148)的验证记录为准，未运行的项目不标记通过。

## 2. 逐项实现与验收映射

| 审计编号    | 实现文件                                                                                                                 | 修复行为                                                                                                 | 正式回归入口                                                                                               |
| ----------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| R-M11-01    | `backend/app/core/standalone_schema.py`                                                                                  | 沿现有增量补列入口添加0064已定义的`materialized_assets`；不重建原设计，不重复新增迁移                    | `backend/tests/test_standalone_design_assets.py`，并回归原Standalone、设计迁移和测试资产文件               |
| R-M20-01    | `frontend/src/features/ai/use-ai-review.ts`                                                                              | 接受成功按真实结果类型失效原项目目录与详情；失效完成后返回可消费结果，另一项目缓存保留                   | `AIAssistantResultNavigation.test.tsx`实际页面、真实Workflow/TestAssets消费者；`use-ai-review.test.tsx`    |
| R-M15-01    | `ReportsPage.tsx`、`features/reports/use-reports.ts`                                                                     | 项目切换重建报告工作区；迟到成功/失败核对原命令身份，原项目目录仍准确刷新；通知输入提交期间锁定          | `ReportsNotificationsIsolation.test.tsx`，原报告页面测试                                                   |
| R-M06-01    | `AccessManagementPanel.tsx`、`use-project-capabilities.ts`、`ProjectProvider.tsx`及资产/流程/DataMock权限消费者          | 逐准确缓存键汇聚成员/团队变更后的权限和项目摘要重读；错误旧值不开放写入；自降级后控件收敛                | `ProjectsPage.test.tsx`、`AccessManagementPanel.test.tsx`及真实`ServiceCatalogPage.test.tsx`消费者         |
| R-GLOBAL-01 | `features/api-console/use-api-console.ts`                                                                                | 取消准确目标各版本详情旧请求，将PATCH真实定义写入稳定键；非活跃标签同步，当前选择/版本/草稿保持          | `ApiConsolePage.test.tsx`、`WorkspaceObjectTabs.test.tsx`                                                  |
| R-M01-01    | `features/dashboard/use-dashboard.ts`、`DashboardPage.tsx`                                                               | 关闭/读取失败的质量及影响能力不触发相关详情，不将旧缓存作为当前有效指标或队列                            | `DashboardPage.test.tsx`开关、暖缓存、失败及正常读取                                                       |
| R-M01-02    | `backend/app/repositories/{dashboard,access}.py`                                                                         | Dashboard复用项目目录既有授权集合，包含团队grant并保持去重、角色优先级和组织边界                         | `backend/tests/test_dashboard_api.py`；相关项目与组织授权回归                                              |
| R-M19-01    | `ReleaseDecisionDialog.tsx`、`ReleaseEvidencePicker.tsx`、`use-release-gate.ts`、`CatalogPagination.tsx`                 | 提交至目录刷新完成持续锁定输入、选择、搜索和分页；同步防重；失败原值保留，显式重试                       | `ReleaseGatePage.test.tsx`真实表单、失败恢复、慢刷新及精确请求断言                                         |
| R-M22-01    | `AIChangeSetsPage.tsx`、`features/ai/use-ai-change-sets.ts`                                                              | 接受/拒绝期间锁定JSON和说明；原项目草稿及变更集刷新完成再结束pending                                     | `AIChangeSetsPage.test.tsx`接受/拒绝失败恢复及慢刷新；原导航与Hook文件                                     |
| R-M24-01    | `OrganizationGovernancePage.tsx`                                                                                         | 稳定组织/身份工作区持有账号表单，目录刷新卸载Tab不丢输入；仅签发成功后清表并一次展示token                | `OrganizationGovernancePage.test.tsx`失败、显式重试、目录refetch卸载与成功两分支                           |
| R-M25-01    | `backend/app/{repositories,services,schemas}/runner_fabric.py`、`execution-fabric-service.ts`、`ExecutionFabricPage.tsx` | 受权查询投影增加`resolved_task_id`；保留原事件task/lease/details，通过既有任务抽屉下钻；展示完整Lease ID | `backend/tests/test_runner_fabric.py`真实progress到HTTP；`ExecutionFabricPage.test.tsx`真实SDK、链接和抽屉 |

上表前端页面文件位于`frontend/src/pages/`；未写全目录的feature文件位于`frontend/src/features/`。测试使用独立SQL数据库或MSW合成fixture，没有写入真实业务系统或新增生产采集。

## 3. 独立 max 复审后的追加闭环

未参与实现的三名审查员分别复核后端、核心前端与AI/组织治理。后端首轮没有发现可操作问题；前端复审确认以下同范围边界，继续修复和复验：

1. **授权刷新汇聚**：并行重读中，一个项目摘要或同前缀的其他权限键先失败，不能让仍在读取当前权限的界面提前解除锁定。必须等每个真实查询完成，再报告失败；不能只在外层包一层`allSettled`而忽略库内部同组的`Promise.all`。
2. **旧缓存的真实消费者**：项目摘要读取失败时不能优先取保留的旧Owner角色；测试资产、流程编辑器的本地权限投影也要核对读取成功状态。保留可读的名称与表单；未知角色不得被Data/Mock的`role !== viewer`当成可写。正常Owner/Editor和真实系统管理员仍按既有合同使用。
3. **重命名后的迟到读取**：旧B详情GET在切A后完成，会反写稳定对象名称。重命名成功取消准确目标各版本详情；详情查询消费AbortSignal，取消后不再写稳定定义缓存。当前A、B本地草稿和固定版本继续保留。
4. **真实API的组织身份边界**：已完成的账号/AI写入响应可能因当前组织已改变被客户端转为SessionBoundaryError，正常onSuccess没有执行机会。仅显示回执的守卫不足以刷新原scope；需将原目录标为失效，返回原scope再重读，避免携带新组织头读取旧scope。不得放宽回执丢弃、泄露token、显示错scope提示或自动重发写入。

对应原始独立审查记录保留于本地日志目录的`review-backend-max.md`、`review-core-ui-max.md`与`review-ai-org-max.md`。其中首轮发现与补修后的复审结论分别记录，不用后来的通过覆盖原问题证据。最终三组源码复审均未发现未处理的可操作问题。核心权限组对同前缀多键的第二轮残余、最后两处lint所需等价收尾，以及AI/组织组的最终测试helper提取均另行复审。

## 4. 合同和风险控制

- Standalone仅补已有迁移定义的列，旧设计来源、指纹、场景、审核和物化引用逐值保持；重复启动不覆盖非空结果。Alembic0064原有upgrade/downgrade不变。
- Dashboard复用既有受权查询，未增加另一套角色算法；授权撤销、跨组织、不存在项目和管理员范围均需回归。Service Account权限合同不变。
- Runner事件只增加只读DTO字段，不回写ORM，不改历史事件task_id，也不将任意details当任务身份；只有受权关联查询能给出resolved_task_id。旧服务未提供新字段时前端保留原task_id兼容。响应schema包含准确的Lease-only `lease_renewed` OpenAPI示例及中文字段说明；已校验示例可解析、原task_id为空、新字段保持required且nullable。
- 一次流程的environment_id及节点Service/Endpoint Variant规则、执行快照、发布门禁判定、AI接受与草稿语义保持。
- OFF按请求策略短路；不增加日志或诊断捕获，不持久化一次性Secret/token，不改写获授权的字面值。
- 不修改CI路由、覆盖率、测试超时、重试或worker设置；具名检查不替代完整门禁。

## 5. 验证记录

验证完成后在此记录准确命令、结果、日志及对应源码状态。测试准备或动画就绪失败与真实产品反例分别保留；不以重跑次数代替原因分析。

### 5.1 本地具名验证

- Standalone及设计资产：5文件、30项通过；日志`output/full-remediation-20261022/m11-targeted.log`，相关Ruff通过。
- Dashboard及Runner：`tests/test_dashboard_api.py`、`tests/test_runner_fabric.py`，44项通过；授权对照`test_access_api.py`、`test_project_governance_reads.py`、`test_organizations_api.py`，21项通过。后端具名共95项、10文件；相关Ruff通过，mypy检查445源文件无问题。日志分别为`dashboard-runner-targeted.log`、`dashboard-authorization-targeted.log`、`backend-mypy.log`。
- 执行面前端：`ExecutionFabricPage.test.tsx`，10项通过；真实progress→HTTP与页面任务/Lease/Fence下钻分别验证，未写实际Runner。
- 核心前端第一批6文件61项有逐文件通过记录；独立复审后主集重新覆盖最终补修：`make test-frontend-targeted`的12文件、145项全部通过，用时215.44秒，日志`root-final-targeted.log`。完整名单及退出状态见`root-final-validation-result.json`，包含Projects、ApiConsole、TestAssets、Workflows、DataMock、ProjectProvider、SDK以及Reports/Release相关文件。
- AI/组织前期完整相关12文件100项通过；随后新增的pending慢刷新、账号目录卸载重挂经拆分67项验证。最终真实SessionBoundaryError反例为2文件10项通过（92.64秒）：账号create/rotate/revoke×组织切换/卸载六项，以及普通AI/变更集×workflow/test_case四项。日志`ai-org-boundary-green.log`；最终三个测试helper的纯提取由独立max复审核对，后续完整测试已覆盖其最终源码。
- 最终改动的39个前端文件ESLint通过，全局`pnpm exec tsc -b --pretty false`通过。初次静态检查发现Release控件复杂度14和Reports无用旧函数，已等价收尾并复审；没有修改规则、阈值或超时。日志`frontend-changed-eslint.log`、`frontend-types.log`。
- 原始复审红证据保留：`max-review-followup-red.log`为12场景中7个真实业务红、5个对照通过；`permission-multi-key-red.log`为同前缀两键1个业务红；`m24-boundary-red-valid.log`为6个账号边界红，AI普通2个与变更集2个有效红分开归档。fixture/动画/定位准备失败不计为产品反例。以上后来的绿不能相加作唯一测试总量，包含重叠回归。

### 5.2 完整检查、独立复审和交付

`CI=true make check`已在首轮48个产品/正式测试文件的SHA-256快照上完整通过，退出码0，总用时2055.55秒。2026-10-22北京时间10:07:46开始、10:42:01结束，运行前后源码一致。完整日志`make-check.log`；退出状态、时间及源码一致性见`make-check-result.json`、`full-check-source-before.json`与`full-check-source-after.json`。

此轮检查随后绑定提交`1a4d8a78a42628152c6b7f4ca6840c9b7f5fba27`，48个提交内文件校验值均一致。5.3的测试交互补修必须在新提交上重新验证，不能沿用此Head的完整检查或远程结果。

- 后端：658个Python文件格式检查、Ruff、445源文件mypy均通过；完整pytest为**1955 passed、14 skipped，覆盖率91.22%**，达到90%门槛，用时263.12秒。保留两项既有测试类收集warning，未改写历史类或测试发现规则。
- 前端：完整Prettier、ESLint及TypeScript检查通过；Vitest为**185文件、1403项全部通过**，用时1759.78秒。覆盖率Statements 86.56%、Branches 82.75%、Functions 86.49%、Lines 89.12%，达到原80%门槛；生产构建通过。未修改测试配置或覆盖率阈值。

文档校验已通过：39个审计基线代码链接固定到main1038e08并核对行号；41个本地链接存在；26模块、73个原唯一F-ID结构保持；8份原始反例归档SHA-256一致。三份新文档Prettier通过。

修复前main的历史绿色CI不计为本轮整改证据。此记录随实现提交，本地完整检查通过时尚未创建本轮PR；本次提交的远程门禁、合并及发布状态另以实际PR和CI记录为准。

本轮本地尚未另行运行Compose浏览器、Windows打包/实体旧包安装、整包历史升级，也未连接真实LLM、MCP、Runner或KMS执行外部集成验收；容量、稳定性RC及生产部署未执行。本次适用的Compose、Windows和历史升级必须由最新提交的远程integration门禁分别验证，不能由本地SQLite/ASGI、MSW或源码复审代替。现有QA13078仍运行较早源码，未作为本轮整改实页验收。

### 5.3 首轮远程结果与测试交互补修

[首次PR运行39712988493](https://github.com/a3384379/FlowTest/actions/runs/39712988493)对应上述Head。Quick、完整后端及基础设施集成、Compose、安全、Windows、历史升级作业通过；前端185文件中184通过，1403项中1401通过，两项组织账号身份边界用例因60000ms超时失败，完整门禁失败，未合并。完整失败日志保留为`pr148-frontend-full-first.log`。

- 失败场景为`rotate/organization`与`revoke/unmount`，未出现业务断言失败。已有本地27.17秒CPU采样中，约89.3%时间处于jsdom CSS继承计算，可见性断言及userEvent指针命中检查各约12秒；这是耗时路径的诊断依据，不把本地采样当成远程失败栈。
- 补修仅调整`submitAccountCommand`中的轮换/撤销准备动作：保留原按钮role、accessible name、可见及aria-hidden断言，增加enabled和focus断言，通过原生Enter激活按钮。已核对真实AntD Button及安装的user-event实现，仍经过原onClick、mutation、HTTP、组织身份拦截器及MSW；未mock业务入口，未改变生产代码、CSS、指针检查配置、超时、重试或覆盖率。键盘路径不单独证明鼠标布局命中。
- 补修后`make test-frontend-targeted TARGETS='["src/pages/OrganizationGovernancePage.test.tsx"]'`为**39项全部通过，用时96.03秒**，日志`org-ci-keyboard-targeted.log`；该文件Prettier及ESLint通过。额外独立max源码复审无剩余可操作问题，记录`ci-keyboard-review-max.md`；诊断记录`ci-org-diagnostic.md`。补修后的完整本地检查、新Head的远程作业与正式Required Gate结果统一追加在[PR #148验证与状态](https://github.com/a3384379/FlowTest/pull/148)，本文件保留逐轮历史结果。
- 首次Compose日志确认：浏览器主套件67项，另setup、Runner及S47前后隔离运维段分别通过；不将重复执行合计作唯一场景数，也不推断累计零重试。五个独立容量步骤均skipped；隔离卷备份、恢复、校验均为7个对象。Windows通过覆盖新便携包、preflight、MCP工具、首次启动、verify及探针，不能代表实体旧安装升级。首次结果仅归属原Head，补修后必须重验适用门禁。

## 6. 原始证据归档

修复前审计中的临时前端反例原位于`frontend/output/full-review-20261022/`。Vitest会发现其中的测试文件，因此在正式回归前将8份原始源码按原字节归档到仓库根的ignored目录：

`output/full-remediation-20261022/audit-probes-archive/frontend/full-review-20261022/`

原路径、归档路径及SHA-256逐文件记录于`output/full-remediation-20261022/audit-probes-archive/manifest.json`，归档后已核对校验值。正式新增回归位于`frontend/src/`与`backend/tests/`，测试发现配置未修改。旧反例的原始失败日志仍保留在审计报告引用的位置；后端临时反例仍在`backend/output/full-review-20261022/`，不属于pytest默认`tests`路径。

本轮完整本地日志目录为`output/full-remediation-20261022/`；其工作区绝对路径为`/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest/output/full-remediation-20261022/`。原始运行产物不提交Git，交付文档应保留可复现的具名测试和准确结果。
