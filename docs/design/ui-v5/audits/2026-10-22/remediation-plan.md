# FlowTest 全模块复审详细修改方案

日期：2026-10-22。对应[完整审计报告](complete-review.md)。方案基于 main `1038e08ffe078719b7d0fe357d7bc7d0d4a1029a` 的11项确认问题：1项P1、10项P2。

**本文保留修复前制定的验收方案。** 各项实施和实际验证状态见[整改实现和验证记录](implementation-report.md)，下列验收清单不用于替代运行结果。原2026-10-19两份审计和方案继续冻结。

## 1. 实施目标与既有合同

目标是修复旧库启动兼容、实际结果打开错误、跨项目状态、权限刷新、名称缓存和提交期间输入归属。保留原功能已经实现的分页、固定版本、来源快照、审批、草稿、执行和标准错误边界。

- 路由继续只适配HTTP；受权范围与只读投影由服务/仓储承担。Domain/engine不引入FastAPI、ORM或具体基础设施。
- 一次流程继续使用一个environment_id；节点Service/Endpoint Variant覆盖照旧。保存、接受、物化、发布、执行分别保持原语义。
- 所有状态修复绑定原项目/用户/对象/请求代次；旧请求确已完成时，仅刷新其原项目资源。需要显示的回执以发起身份核对，不能落到另一工作区。
- OFF保持请求级短路，不扫描、替换、恢复占位符或阻止已授权字面值。Secret继续一次显示、API写入和加密边界，不增加生产日志/捕获或持久化。
- 复用现有typed query key、受权读取、`_add_column_if_missing`和局部状态守卫。这里涉及的不同表单暂不抽通用“万能事务/缓存管理器”。
- 先把本轮有效反例迁入具名正式测试；补修后用原断言转绿。M22/M25目前为源码确认，先加可达行为反例再改实现。

## 2. 开发批次与依赖

| 顺序 | 范围                         | 目的                         | 交付边界                                               |
| ---- | ---------------------------- | ---------------------------- | ------------------------------------------------------ |
| A1   | R-M11-01                     | 首先解除旧Standalone库阻断   | 真实旧完整库启动补列、原设计可读写、重复启动保持引用   |
| A2   | R-M20-01、R-M15-01、R-M06-01 | 修复错误对象/项目/角色状态   | 真消费者打开新流程、旧项目回执不进入B、降级权限收敛    |
| B1   | R-GLOBAL-01、R-M01-01        | 补缓存和功能开关的小闭环     | inactive重命名同步标签、OFF不请求关闭能力              |
| B2   | R-M01-02、R-M25-01           | 统一受权范围与可消费证据身份 | 团队项目汇总正确、Lease-only事件能定位任务             |
| C    | R-M19-01、R-M22-01、R-M24-01 | 完成提交会话和失败恢复       | pending输入锁定，失败保持，只有成功清表单              |
| D    | 全部修复的交叉复审与正式交付 | 确认原73项没有被补修破坏     | 具名检查、必要集成、最新head门禁、适用部署验收分别记录 |

按模块可以并行准备A2/B/C，但共享文件修改需明确所有者；后端授权与M25 DTO的前后端改动作为一个完整合同验收。长测试窗口串行协调，避免资源竞争影响超时判断。每批结束先完成相关验证，不为未变更模块重复全量测试。

## 3. R-M11-01 · P1 · Standalone旧库缺 materialized_assets

**修改范围**：`backend/app/core/standalone_schema.py` 的设计增量补列；正式测试优先加入 `backend/tests/test_standalone_runtime.py` 或专门的旧设计升级测试文件，复用真实启动入口。

**实施步骤**：

1. `_ensure_s47_test_design_columns` 沿现有 `_add_column_if_missing` 增加 `materialized_assets`，定义与ORM/0064一致：`JSON NOT NULL DEFAULT '[]'`。
2. 完整保留旧design、source_change_set、指纹、场景、testcase refs、审核说明及其他表；只执行必要的增量补列。
3. 启动第二次以及当前新库都不得覆盖已有非空materialized_assets。补列不依赖FlowSpec重建分支。
4. 0064现有Alembic upgrade/downgrade保持；本问题没有新增业务字段，不需要重复创建新的同字段迁移。若实现范围实际扩展模型/持久化合同，另评估相应可逆迁移。

**验收**：

- [ ] 完整现库仅缺0064新增列，存有旧approved设计；真实initialize后ORM可读，新列为空列表。
- [ ] 原指纹/来源/场景/引用/审核说明前后逐值相等；已有其他列未变。
- [ ] 可保存新物化结果，第二次initialize后仍完整；列不重复添加。
- [ ] 新装、已有当前库及旧FlowSpec分支继续可用；升级失败时错误明确，不能静默吞掉。

**验证范围**：具名 `test_standalone_runtime.py`、`test_standalone_ai_review_baselines.py`、`test_design_asset_migration.py`、`test_test_engineering_assets.py`；相关Ruff格式/规则，跨文件类型变更时mypy。部署形态属于核心风险，合并前补适用历史升级及Windows旧库包验收；普通Alembic通过不能替代Standalone启动路径。

## 4. R-M20-01 · P2 · 普通AI接受结果打开旧流程

**修改范围**：`frontend/src/features/ai/use-ai-review.ts`、AI结果真实消费者回归。测试可放 `AIAssistantRemediation.test.tsx` / `use-ai-review.test.tsx`，保留真实 `useWorkflows` 联动。

**实施步骤**：

1. review发起时捕获project/job/suggestion身份；接受响应成功后，根据实际materialized type/id刷新原项目的资产目录和相应详情。
2. Workflow至少失效实际的 `['workflows', project]` 前缀；核对TestCase对应的真实目录、选项和计数前缀，按返回类型处理。
3. 缓存修复在原项目完成，即使已导航离开也成立；当前页面toast/选择继续由既有命令身份守卫控制。
4. 失效完成后再呈现可消费的结果入口；保留真实新ID、草稿状态及完整href，接受不自动发布或执行。
5. 维持工作流完整目录选择算法的既有合同。本项优先修正产生结果的一方缺少缓存通知的问题。

**验收**：

- [ ] 同一个QueryClient采用生产15秒staleTime，先加载完整旧目录→实际AI接受新流程→点结果→真实消费者展示新ID/名称。
- [ ] 反例在15秒窗口内到达结果消费，不用Infinity、假时钟、选择逻辑mock或手工刷新制造通过。
- [ ] 接受POST一次，旧项目目录正确失效；另一项目新鲜目录不被清除。
- [ ] TestCase接受也能在其真实工作区打开；已拒绝/未物化/非法结果不创建错误入口。
- [ ] 离开发起路由后的旧响应不抢当前选择，业务成功回执仍能正确更新原资产缓存。

**验证范围**：AI页面、Remediation、Hook与SDK的具名测试，Workflow真实消费者导航反例；格式/lint/types及相关构建。保留原MCP物化、源版本及AI开关测试，不需要调用真实模型来证明缓存修复。

## 5. R-M15-01 · P2 · 报告通知回执跨项目显示Secret

**修改范围**：`ReportsPage.tsx` / `features/reports/use-reports.ts` 的工作区生命周期和通知可见状态；`ReportsPage.test.tsx`。

**实施步骤**：

1. 为报告工作区采用原项目身份key，或使通知编辑/一次性Secret状态明确包含projectId并只在对应当前项目显示。
2. 创建Webhook的成功/失败可见反馈核对发起项目、生命周期和请求身份；切项目后旧响应不关闭B弹窗、不写B的Secret状态、不弹错项目成功提示。
3. 旧请求若已被服务端完成，不回滚或自动重发；对原项目的webhook目录做准确失效。
4. 切项目立即停止显示原项目Secret；仅在发起工作区仍有效时显示一次性回执。保持现有“我已保存”关闭操作。
5. 顺带核对同Hook导出/启停的迟到反馈和准确目录刷新，修复与本项同一归属错误；不扩展通知后端功能。

**验收**：

- [ ] A Owner真实提交通知→请求pending→公开路由切B Viewer→A成功，B配置按钮禁用且无A Secret/成功提示。
- [ ] A失败→B不显示A错误；A原始输入的保持/清理符合原会话身份。
- [ ] A已经显示Secret再切B，立即不可见；不持久化或新增日志。
- [ ] 同项目正常成功只显示一次；取消/关闭恢复符合既有合同，无第二POST或后台自动重新签发。
- [ ] 切换期间失效query只影响发起项目，B的通知目录和编辑状态不被覆盖。

**验证范围**：ReportsPage具名通知/权限/路由测试及实际影响的Hook/SDK测试，格式/lint/types。原报告同run/node/attempt、筛选和冻结来源关联继续回归。

## 6. R-M06-01 · P2 · 项目自降级后管理权限仍旧

**修改范围**：`features/projects/AccessManagementPanel.tsx` 成功失效列表与 `ProjectsPage.tsx` 权限消费；`AccessManagementPanel.test.tsx`、`ProjectsPage.test.tsx`。

**实施步骤**：

1. 成员/团队变更成功后，在现有目录、成员、grants、审计失效之外，失效并等待准确项目的 `['project-permissions', projectId]` 前缀，覆盖带userId和不带userId的现有键形态。
2. 必要时刷新该用户项目列表/当前项目摘要中的角色，让不同模块对同一身份一致；仅处理真实受影响身份与项目。
3. 权限刷新期间维持原pending/读取不足禁写语义，刷新失败明确提示；不能仍按旧Owner成功态继续显示管理能力。
4. 自降级成功后表单/目录/管理控件随最新capabilities收紧，不能只改一个身份标签。
5. 保留后端最后Owner保护；合法“两Owner情况下自降级”仍可成功。

**验收**：

- [ ] 普通非系统管理员、同项目另有Owner：自己Owner→Viewer，PUT仅一次；成员viewer、permission viewer、Owner标签消失、管理操作禁用或不再展示。
- [ ] Owner→Editor仅保留真实edit/execute能力；其他项目不受影响。
- [ ] 权限重读403/503期间不误报完整成功、不依赖旧权限继续启用敏感操作；可显式重试。
- [ ] 最后Owner降级仍由后端409拒绝，原身份/输入保持。
- [ ] 团队授权调整/成员移除的有效能力重新读取，原授权边界不扩大。

**验证范围**：上述两前端文件和相关目录组件；后端既有最后Owner/项目隔离具名测试作为合同对照。跨模块能力/缓存合同变化时扩大到实际消费者，不复制一套前端授权规则。

## 7. R-GLOBAL-01 · P2 · 非活跃接口重命名的标签缓存

**修改范围**：`features/api-console/use-api-console.ts` 的rename成功回调；`ApiConsolePage.test.tsx`、`WorkspaceObjectTabs.test.tsx` 的实际联动。

**实施步骤**：

1. 消费PATCH返回的真实ApiDefinition，写准确的 `apiDefinitionKey(projectId, variables.apiId)`。
2. 保留现有项目目录、对应detail和搜索缓存失效。若更新detail中的definition，按已知精确键/结构处理，不修改版本内容或取任意第一个版本。
3. 保持当前选中A、B的完整href/版本/草稿及标签关闭保护；不靠重新请求所有对象或清空tab完成改名。

**验收**：

- [ ] 实际打开B再选A，通过B目录按钮重命名；A仍selected，B目录、B tab立即显示新名，PATCH一次。
- [ ] B处于历史版本、持有本地草稿时名称同步，版本/编辑内容不变。
- [ ] 活跃对象改名、失败保留输入、重新加载tab仍正确；另一个同名/跨项目资产不变。

**验证范围**：ApiConsolePage、use-api-console、WorkspaceObjectTabs具名测试与格式/lint/types。无需新增网络API或后端迁移。

## 8. R-M01-01 · P2 · OFF状态仍请求质量详情

**修改范围**：`features/dashboard/use-dashboard.ts`，`DashboardPage.test.tsx`。

**实施步骤**：

1. 风险详情的enabled同时满足明确项目、质量能力成功可用和有效Risk ID，与风险列表的gate一致。
2. 质量智能/影响关闭时的摘要及队列采用当前已说明的不可用状态；若确实展示历史缓存，明确其历史范围，且不调用关闭能力的HTTP详情。
3. Flaky summary和发布判断等独立可读资源按自身合同读取，不把质量开关扩展为无关功能总开关。
4. 失败仍用标准错误；不要通过吞掉503、删除全部缓存或增加重试来掩盖错误查询。

**验收**：

- [ ] 预先合法读取过风险目录，flag为OFF，返回首页不请求风险详情；关闭提示存在，其他允许资源照常读取。
- [ ] ON→OFF后失焦/重新进入/手动刷新不重启gated详情；ON正常请求一次。
- [ ] flag读取失败/未完成不按旧能力开启新请求；跨项目旧风险ID不进入当前项目。
- [ ] 原Flaky真实全量、多版本及错误未知状态保持。

**验证范围**：DashboardPage具名缓存/开关用例，相关格式/lint/types；不需要修改质量后端开关策略。

## 9. R-M01-02 · P2 · 团队授权项目在Dashboard范围被遗漏

**修改范围**：`backend/app/repositories/dashboard.py`、相关受权项目查询服务边界，`test_dashboard_api.py`。

**实施步骤**：

1. 确定项目目录与Dashboard共用的授权身份查询合同：直接成员、合法团队grant、系统管理员及当前组织过滤一致。
2. 优先复用已有受类型约束的项目身份能力；若共享会扩大无关重构，仅最小提取真实稳定范围逻辑。避免为Dashboard复制含不同优先级的授权判断。
3. 全局和指定project均采用同一project ID集合，去重之后统计；summary和recent继续同scope。
4. 保留不存在/未受权项目标准404及Trace，不放宽到组织内所有项目；机器账号保持其现有独立授权合同。

**验收**：

- [ ] team-only Viewer/Editor：项目目录与permissions200，Dashboard指定项目summary/recent200，全局汇总包含同一项目和执行。
- [ ] 直接成员和团队重叠去重；多个grant不重复计数，直接角色优先级符合已有合同。
- [ ] grant撤销后不可继续读；其他组织/未授权项目仍404；系统管理员受当前组织范围约束。
- [ ] 原直接成员/管理员统计、时间边界及最近执行分页维持。

**验证范围**：具名Dashboard/API与实际影响的项目授权测试、Ruff、mypy。属于授权/组织隔离核心风险，合并前扩大适用集成验证；本地单反例通过不能直接作为门禁成功。

## 10. R-M19-01 · P2 · 发布判断提交期间仍能修改输入

**修改范围**：`features/release-gate/ReleaseDecisionDialog.tsx` 及自定义证据选择器，必要时补命令同步防重；`ReleaseGatePage.test.tsx`。

**实施步骤**：

1. pending时将完整Form及策略、候选、六类证据选择统一设为只读/disabled；自定义EvidencePicker的搜索、翻页、按ID核对/选入都遵守该状态。
2. 保留当前AntD confirmLoading已经存在的取消/遮罩/Escape保护。不要为已排除的Cancel猜想另建复杂关闭逻辑。
3. 提交快照与结果回执保持同一身份，成功只关闭对应提交会话；失败恢复原A可编辑值，不自动重发。
4. 必要时增加同步pending guard防同事件边界重复提交；不改变策略、BLOCK、过期证据或风险/Impact关联算法。

**验收**：

- [ ] candidate-A提交后，候选、策略、自定义来源控件锁定，真实userEvent不能将当前输入改为B。
- [ ] POST仅一次；服务端返回合法201/BLOCK时回执明确对应A，成功后关闭/详情正确。
- [ ] 503后A输入及所选来源保留、恢复编辑；只有再次明确提交才有第二请求。
- [ ] 既有取消保护、跨项目/跨run晚回执、来源失败/精确ID及只读权限继续成立。

**验证范围**：ReleaseGatePage和相关EvidencePicker/Hook具名测试，格式/lint/types。正式测试用符合后端政策的BLOCK快照，避免把合成PASS误写为发布算法验收。没有证据声称B字段永久删除；修复目标是提交中所见编辑与原回执的身份冲突。

## 11. R-M22-01 · P2 · AI变更审核pending输入保护

**修改范围**：`AIChangeSetsPage.tsx` 的JSON/备注控件；`AIChangeSetsPage.test.tsx`、navigation测试。

**先补反例**：真实审核打开、编辑A/N并确认接受，延迟POST；当前用户仍可改B/N2，原回执成功关闭。拒绝时备注同样要覆盖。本项本轮只有完整源码确认，开发前需要该行为反例。

**实施步骤**：

1. JSON与审核备注的可编辑状态绑定readOnly/submitting，pending保持已提交原值。
2. 保留JSON校验、dirty关闭/路由保护、同步防重、固定baseline和hash冲突检测；失败不清除原内容。
3. 生成Modal现有confirmLoading取消保护有效，此项只修实际仍可编辑的审核输入。
4. OFF模式和字面REDACTED处理完全沿用已正确的服务端请求策略；不借此扩大敏感扫描或采集。

**验收**：

- [ ] 受控pending中两个输入均不能改动；接受/拒绝备注使用同样语义，唯一POST。
- [ ] 释放503后JSON与备注保持，编辑恢复；显式第二次成功后才关闭。
- [ ] dirty继续编辑/明确放弃、切项目晚回执、后台更新冲突和只读历史仍可用。
- [ ] 固定基线、遗漏运行字段保留及OFF字面值相关原断言保持。

**验证范围**：页面、navigation、实际影响的use-ai-change-sets/SDK测试及格式/lint/types；只有后端有实际改动时再跑对应backend合同，不为前端锁定盲目重跑全后端。

## 12. R-M24-01 · P2 · Service Account签发失败清空输入

**修改范围**：`OrganizationGovernancePage.tsx` 的ServiceAccountsTab与上层mutation回执合同；对应具名测试。

**实施步骤**：

1. 将onCreate改为可等待的成功结果或等效、带当前请求身份的成功通知；提交时先保留原name/account_key/scopes。
2. 仅本次请求成功才resetFields；403/409/503/网络失败保留值，通过已有标准错误/Trace提供明确反馈。
3. pending期间锁定当前账号表单，防止成功清掉等待期间新增的下一份输入；失败恢复编辑。
4. 原token只显示一次、rotate/revoke、组织自降级和目录权限合同保持；不扩大scope选项或日志。

**验收**：

- [ ] 503时精确payload正确，当前重新查询的DOM仍保留三项输入、POST一次、没有token。
- [ ] 恢复后用户显式重试，成功才清表单、token只显示一次；同组织正常签发保持。
- [ ] 403/409失败保持；换组织/卸载后的旧回执不清当前表单或显示旧token。
- [ ] 原成员失败输入保持、DirectoryPicker pending、自降级最新角色与rotation测试继续通过。

**验证范围**：OrganizationGovernancePage及实际影响的组织SDK/rotation具名测试、格式/lint/types。反例必须在resetFields后重新查DOM，避免用AntD已经卸载的旧input引用得到假结论。本项不是原ORG03成员修复被推翻，而是相邻账号表单的同类遗漏。

## 13. R-M25-01 · P2 · Lease-only事件缺任务定位

**修改范围**：Runner管理事件只读DTO/投影、`ExecutionFabricPage.tsx`任务入口、相关SDK与测试；不改变progress写入或调度状态机。

**先补反例**：真实有效Lease调用progress(message)，再从管理HTTP events读取此记录；验证该事件能提供可消费的任务身份，并在页面实际打开同任务/Lease。现有测试只核过滤包含该事件，未核序列化/消费者。

**实施步骤**：

1. 复用受权查询已有effective task解析（event.task_id优先，否则lease.task_id），明确只读返回合同。
2. 可增加具名resolved_task_id，或清楚定义管理读取的task_id有效归属语义；选一方案贯穿DTO/SDK/UI。避免向SQLAlchemy受跟踪的原事件实体写回补值。
3. 前端以可消费身份构建任务入口，必要时显示完整Lease ID；精确任务Drawer继续带Lease/Fence和关联report/workflow。
4. 组织、pool、task筛选与total复用同一授权范围；无法解析的关联不猜测。纯Pool注册等无任务事件继续显示无任务。
5. 只投影已授权数据，保持零新增事件/日志/采集，不更改Lease/Fence状态或增加管理权限。

**验收**：

- [ ] 真实progress→管理HTTP events→前端点击，能打开确切任务及该Lease/Fence。
- [ ] 直接task_id事件继续可用；纯Pool事件没有伪造任务入口。
- [ ] A组织不可读B事件，B及真实授权global可读；shared pool边界保留，页数/total无重复。
- [ ] 回看/翻页/刷新仅GET，零Token签发/Drain/运行POST。

**验证范围**：`backend/tests/test_runner_fabric.py`、`frontend/src/pages/ExecutionFabricPage.test.tsx`及实际影响的SDK；Ruff/mypy/tsc。DTO及组织范围属于跨层合同，合并前补适用集成与隔离验收。

## 14. 统一验证与交付要求

### 14.1 开发检查

先执行各问题具名测试及受影响文件格式/规则/类型检查。仓库提供以下定向入口，实际TARGETS按本次触达文件选择：

```sh
make test-backend-targeted TARGETS='["tests/test_standalone_runtime.py", "tests/test_standalone_ai_review_baselines.py", "tests/test_design_asset_migration.py", "tests/test_test_engineering_assets.py"]'
make test-frontend-targeted TARGETS='["src/pages/ProjectsPage.test.tsx", "src/features/projects/AccessManagementPanel.test.tsx"]'
```

以上为实施时的示例，**不是本轮已运行或通过的结果**。开发中不默认跑全量覆盖、Compose、Windows和容量；出现失败先看相关摘要和完整日志，不在无修复/新信息时重复同一失败。

### 14.2 修复后交叉验收矩阵

| 场景                                          | 主要关联                | 必须核对的实际结果                                        |
| --------------------------------------------- | ----------------------- | --------------------------------------------------------- |
| 升级旧完整SQLite库→设计读取→物化引用保存→重启 | M11/M22/M23             | 64/65新增字段都具备、原设计及固定来源保持、重复启动不覆盖 |
| 普通AI / MCP接受→结果链接→真实对象工作区      | M20/M22/M23/M07/M08/M12 | 精确新ID、目录缓存一致、历史/草稿版本准确、零自动发布执行 |
| 项目/组织成员自降级→跨模块操作                | M06/M24/共享能力        | 最新角色收敛、管理控件收紧、当前身份与服务器一致          |
| A慢请求→B / Back / 卸载                       | M15/M20/M22/M24         | 旧回执仅影响原项目资源，B输入/选择/Secret不变             |
| 原输入提交→pending尝试编辑→失败/成功          | M19/M22/M24             | 提交快照唯一、pending锁定、失败保持、显式重试             |
| 非活跃接口改名 / 切版本 / 本地草稿            | M02/全局                | 目录/tab/工作台名称一致，href/版本/草稿保持               |
| 团队授权 / 直接成员 / 撤权 / 跨组织           | M01/M06/M24             | 可访问项目与汇总/最近运行一致，去重及拒绝边界正确         |
| Lease-only事件→任务→历史报告/画布             | M25/M15/M07             | 同task/lease/fence/run身份，受权只读，未知关系不猜链接    |
| flag OFF且有旧缓存                            | M01/M16/M22             | 按各模块真实读取合同控制请求，状态与错误可解释            |

桌面浏览器先验1440/1280的实际任务流；响应式仅作为适用的附加回归维度。使用 bundled Chromium/Chrome for Testing及专用临时profile，不连接个人Chrome。对共享QA仅在明确的受控验收范围内操作；不得为方便截图自动生成生产资产或执行真实发布。

### 14.3 完成标准

- [ ] 11个问题各有实现文件、正式行为反例及修复后通过证据；原9个有效反例保留问题级断言，M22/M25先补真实反例。
- [ ] 本轮排除的Cancel猜想和fixture失败不混入待修列表；没有为了“转绿”改timeout/重试/阈值或用假选择器替换真实消费者。
- [ ] 原73项逐项重新核对受影响交叉路径，原冻结文档不改写；追加新实施/验证记录。
- [ ] 相关定向检查完成；核心/跨层风险按实际范围补集成、旧库和Windows验收。
- [ ] 最终变更集执行适用完整`make check`及合并计划要求；每个结果绑定准确新head，不用当前main历史green替代。
- [ ] 新PR的正式Required Gate、是否已合并、合并后CI、部署和外部环境验收分别记录。缺哪层证据就保持未验，不推断。
- [ ] 完整报告列出实际修改文件、实际通过/失败/未运行检查及剩余边界；没有完成的外部LLM/MCP/KMS/Runner/容量验收明确保留。

本方案的完成边界是上述修复与对应验证完成。文档生成、局部反例通过、正式门禁通过、合并和发布验收分别具有独立状态。
