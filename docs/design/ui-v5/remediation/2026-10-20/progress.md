# UI v5 审计整改进度

依据：[完整审计](../../audits/2026-10-19/complete-audit.md)、[详细方案](../../audits/2026-10-19/remediation-plan.md)。审计基线 `420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4`。

2026-10-20 至 21 日整改：**42 项已实现并完成本地验证，31 项待完成**（首批22项，加报告、用例、服务目录5项、请求目标3项、多协议3项、项目治理2项、数据与Mock2项、契约中心2项及测试工程3项）。按73项等权计数，本地完成约58%，已合并37项约51%；不代表工时消耗比例。R0、R1全部整改项已完成本地验证，R2按模块继续推进。**不是73项全部完成，也不是全站设计签收。**

状态指代码和本地验证；浏览器专项、GitHub交付与正式环境验收分开记录。详情见[首批实施与验证](batch-01.md)、[冻结断言来源补充整改](batch-02.md)与[完整本地验证记录](validation.md)。

| 问题       | 模块 | 批次 | 状态                 |
| ---------- | ---- | ---- | -------------------- |
| F-API-01   | M02  | R0   | 已实现，本地验证通过 |
| F-API-02   | M02  | R1   | 已实现，本地验证通过 |
| F-API-03   | M02  | R1   | 已实现，本地验证通过 |
| F-API-04   | M02  | R1   | 已实现，本地验证通过 |
| F-API-05   | M02  | R1   | 已实现，本地验证通过 |
| F-WF-01    | M07  | R1   | 已实现，本地验证通过 |
| F-WF-02    | M07  | R1   | 已实现，本地验证通过 |
| F-WF-03    | M07  | R1   | 已实现，本地验证通过 |
| F-WF-04    | M07  | R0   | 已实现，本地验证通过 |
| F-CASE-01  | M08  | R1   | 已实现，本地验证通过 |
| F-CASE-02  | M08  | R1   | 已实现，本地验证通过 |
| F-CASE-03  | M08  | R1   | 已实现，本地验证通过 |
| F-CASE-04  | M08  | R1   | 已实现，本地验证通过 |
| F-REP-01   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-02   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-03   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-04   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-05   | M15  | R1   | 已实现，本地验证通过 |
| F-DASH-01  | M01  | R3   | 待实施               |
| F-DASH-02  | M01  | R3   | 待实施               |
| F-SVC-01   | M03  | R2   | 已实现，本地验证通过 |
| F-SVC-02   | M03  | R2   | 已实现，本地验证通过 |
| F-SVC-03   | M03  | R2   | 已实现，本地验证通过 |
| F-TGT-01   | M04  | R2   | 已实现，本地验证通过 |
| F-TGT-02   | M04  | R2   | 已实现，本地验证通过 |
| F-TGT-03   | M04  | R2   | 已实现，本地验证通过 |
| F-PROTO-01 | M05  | R0   | 已实现，本地验证通过 |
| F-PROTO-02 | M05  | R2   | 已实现，本地验证通过 |
| F-PROTO-03 | M05  | R2   | 已实现，本地验证通过 |
| F-PROTO-04 | M05  | R2   | 已实现，本地验证通过 |
| F-PRJ-01   | M06  | R2   | 已实现，本地验证通过 |
| F-PRJ-02   | M06  | R2   | 已实现，本地验证通过 |
| F-DATA-01  | M09  | R2   | 已实现，本地验证通过 |
| F-DATA-02  | M09  | R2   | 已实现，本地验证通过 |
| F-CT-01    | M10  | R2   | 已实现，本地验证通过 |
| F-CT-02    | M10  | R2   | 已实现，本地验证通过 |
| F-ENG-01   | M11  | R2   | 已实现，本地验证通过 |
| F-ENG-02   | M11  | R2   | 已实现，本地验证通过 |
| F-ENG-03   | M11  | R2   | 已实现，本地验证通过 |
| F-TASK-01  | M12  | R2   | 待实施               |
| F-TASK-02  | M12  | R2   | 待实施               |
| F-ENV-01   | M13  | R2   | 待实施               |
| F-ENV-02   | M13  | R2   | 待实施               |
| F-PERF-01  | M14  | R2   | 待实施               |
| F-PERF-02  | M14  | R2   | 待实施               |
| F-IMP-01   | M16  | R3   | 待实施               |
| F-IMP-02   | M16  | R3   | 待实施               |
| F-REG-01   | M17  | R0   | 已实现，本地验证通过 |
| F-REG-02   | M17  | R3   | 待实施               |
| F-REG-03   | M17  | R3   | 待实施               |
| F-QLT-01   | M18  | R3   | 待实施               |
| F-QLT-02   | M18  | R3   | 待实施               |
| F-REL-01   | M19  | R0   | 已实现，本地验证通过 |
| F-REL-02   | M19  | R3   | 待实施               |
| F-REL-03   | M19  | R3   | 待实施               |
| F-AI-01    | M20  | R4   | 待实施               |
| F-AI-02    | M20  | R4   | 待实施               |
| F-CTX-01   | M21  | R4   | 待实施               |
| F-AIC-01   | M22  | R4   | 待实施               |
| F-AIC-02   | M22  | R4   | 待实施               |
| F-AIC-03   | M22  | R4   | 待实施               |
| F-MCP-01   | M23  | R4   | 待实施               |
| F-MCP-02   | M23  | R4   | 待实施               |
| F-ORG-01   | M24  | R4   | 待实施               |
| F-ORG-02   | M24  | R4   | 待实施               |
| F-ORG-03   | M24  | R4   | 待实施               |
| F-FAB-01   | M25  | R4   | 待实施               |
| F-FAB-02   | M25  | R4   | 待实施               |
| F-PLAT-01  | M26  | R4   | 待实施               |
| F-PLAT-02  | M26  | R4   | 待实施               |
| F-UX-01    | 全局 | R2   | 已实现，本地验证通过 |
| F-UX-02    | 全局 | R2   | 已实现，本地验证通过 |
| F-UX-03    | 全局 | R2   | 已实现，本地验证通过 |

## 已实现项与证据入口

### F-API-01

已保存断言优先显示，只有无保存断言时提供快速预期状态码；执行负载与界面一致。

- 实现：[frontend/src/pages/ApiConsolePage.tsx](../../../../../frontend/src/pages/ApiConsolePage.tsx)。
- 回归：[frontend/src/pages/ApiConsolePage.test.tsx](../../../../../frontend/src/pages/ApiConsolePage.test.tsx)。

### F-API-02

目录显示当前版本的 Method/Path；服务层批量读取版本，避免逐行额外请求。

- 实现：[backend/app/services/api_assets.py](../../../../../backend/app/services/api_assets.py)。
- 回归：[backend/tests/test_api_assets_api.py](../../../../../backend/tests/test_api_assets_api.py)。

### F-API-03

左右/上下布局、目录/响应折叠、拖动和键盘调整；按用户和项目保存，坏存储安全回退；手机面板切换保持子组件。

- 实现：[frontend/src/features/api-console/ApiWorkspace.tsx](../../../../../frontend/src/features/api-console/ApiWorkspace.tsx)。
- 回归：[frontend/src/features/api-console/ApiWorkspace.test.tsx](../../../../../frontend/src/features/api-console/ApiWorkspace.test.tsx)。

### F-API-05

Bearer、Basic、API Key 按具名字段填写，校验必需值和位置，保留既有高级配置；ON/OFF沿用项目策略。

- 实现：[frontend/src/features/api-console/AuthConfigurationFields.tsx](../../../../../frontend/src/features/api-console/AuthConfigurationFields.tsx)。
- 回归：[frontend/src/features/api-console/APIWorkbench.test.tsx](../../../../../frontend/src/features/api-console/APIWorkbench.test.tsx)。

### F-WF-01

摘要展示匹配固定版本的请求信息、组合/一元条件、循环来源、退出条件、并行策略、旧提取/断言/遍历；未知和长值明确标识。

- 实现：[frontend/src/flow/editor/node-presentation.ts](../../../../../frontend/src/flow/editor/node-presentation.ts)。
- 回归：[frontend/src/flow/editor/node-presentation.test.ts](../../../../../frontend/src/flow/editor/node-presentation.test.ts)。

### F-WF-02

区域普通节点复用主检查器，API支持Service/Variant与请求覆盖等既有配置；弹窗分区、滚动和缩放修复。

- 实现：[frontend/src/flow/WorkflowNodeInspector.tsx](../../../../../frontend/src/flow/WorkflowNodeInspector.tsx)。
- 回归：[frontend/src/flow/WorkflowNodeInspector.test.tsx](../../../../../frontend/src/flow/WorkflowNodeInspector.test.tsx)。

### F-WF-03

常用可视化字段在前，高级控制和区域JSON默认折叠；有未应用JSON时保留提示。

- 实现：[frontend/src/flow/WorkflowControlFields.tsx](../../../../../frontend/src/flow/WorkflowControlFields.tsx)。
- 回归：[frontend/src/flow/WorkflowControlFields.test.tsx](../../../../../frontend/src/flow/WorkflowControlFields.test.tsx)。

### F-WF-04

各级区域节点有独立编辑会话；切节点、关区域与祖先区域保护未应用输入；JSON必须先应用；结构动作避免覆盖待处理输入。

- 实现：[frontend/src/flow/WorkflowNodeEditSession.tsx](../../../../../frontend/src/flow/WorkflowNodeEditSession.tsx)。
- 回归：[frontend/src/flow/WorkflowControlFields.test.tsx](../../../../../frontend/src/flow/WorkflowControlFields.test.tsx)。

### F-CASE-01

新建前明确权限、已发布流程、环境及查询状态，提供流程/环境入口；不自动造资源。

- 实现：[frontend/src/pages/TestAssetsPage.tsx](../../../../../frontend/src/pages/TestAssetsPage.tsx)。
- 回归：[frontend/src/pages/TestAssetsPage.test.tsx](../../../../../frontend/src/pages/TestAssetsPage.test.tsx)。

### F-CASE-02

用例集草稿按用户/项目/对象保留，关闭可继续或丢弃；保存防重复，失败不丢输入，旧保存不能清掉新一代编辑。

- 实现：[frontend/src/features/test-assets/use-suite-edit-draft.ts](../../../../../frontend/src/features/test-assets/use-suite-edit-draft.ts)。
- 回归：[frontend/src/pages/TestAssetsPage.test.tsx](../../../../../frontend/src/pages/TestAssetsPage.test.tsx)。

### F-CASE-03

用例、用例集及批量移动使用层级选择，显示完整目录路径；失效目录明确提示重选。

- 实现：[frontend/src/features/projects/AssetFolderSelect.tsx](../../../../../frontend/src/features/projects/AssetFolderSelect.tsx)。
- 回归：[frontend/src/pages/TestAssetsPage.test.tsx](../../../../../frontend/src/pages/TestAssetsPage.test.tsx)。

### F-REP-01

无显式节点时选择失败或已执行的业务节点并规范URL中的节点/尝试；显式无效节点提示，切节点清理旧实例选择。

- 实现：[frontend/src/features/reports/ReportExecutionWorkspace.tsx](../../../../../frontend/src/features/reports/ReportExecutionWorkspace.tsx)。
- 回归：[frontend/src/pages/ReportsPage.test.tsx](../../../../../frontend/src/pages/ReportsPage.test.tsx)。

### F-REP-03

画布与报告复用响应阅读器：完整已捕获内容搜索、行号、格式化/换行、复制下载；超出预览上限不等于未捕获。

- 实现：[frontend/src/features/api-console/ResponseCodeReader.tsx](../../../../../frontend/src/features/api-console/ResponseCodeReader.tsx)。
- 回归：[frontend/src/features/api-console/ResponseCodeReader.test.tsx](../../../../../frontend/src/features/api-console/ResponseCodeReader.test.tsx)。

### F-REP-05

检查点日志支持服务端节点/实例及检查点尝试过滤，total与分页同范围；明确区别HTTP重试。

- 实现：[backend/app/repositories/durable_execution.py](../../../../../backend/app/repositories/durable_execution.py)。
- 回归：[backend/tests/test_workflows_api.py](../../../../../backend/tests/test_workflows_api.py)。

### F-PROTO-01

按项目/资产/版本/Hash重建调试工作区；提交捕获请求输入，以请求代次阻止旧回包/错误；编辑同一资产请求也清除旧证据。

- 实现：[frontend/src/pages/ProtocolWorkbenchPage.tsx](../../../../../frontend/src/pages/ProtocolWorkbenchPage.tsx)。
- 回归：[frontend/src/pages/ProtocolWorkbenchPage.test.tsx](../../../../../frontend/src/pages/ProtocolWorkbenchPage.test.tsx)。

### F-REG-01

先在抽屉查看完整缺失测试草案与来源后审核；窗口固定打开或主动刷新时的内容及来源，迟到刷新不会覆盖新审核。前端提交所看内容，服务端加锁后检查，过期审核409；保留人工边界。详情见[审核快照复审](batch-04.md)。

- 实现：[backend/app/services/change_regression.py](../../../../../backend/app/services/change_regression.py)。
- 回归：[backend/tests/test_change_regression.py](../../../../../backend/tests/test_change_regression.py)。

### F-REL-01

Runner证据走项目只读分页/详情接口，保留项目授权与跨项目隔离；不访问全局管理员调度列表。

- 实现：[backend/app/services/release_gate.py](../../../../../backend/app/services/release_gate.py)。
- 回归：[backend/tests/test_release_gate.py](../../../../../backend/tests/test_release_gate.py)。

### F-UX-01

全局搜索明确失败、trace与重试，保留搜索词和已取得结果；错误不伪装为空资产。

- 实现：[frontend/src/features/search/GlobalSearch.tsx](../../../../../frontend/src/features/search/GlobalSearch.tsx)。
- 回归：[frontend/src/features/search/GlobalSearch.test.tsx](../../../../../frontend/src/features/search/GlobalSearch.test.tsx)。

### F-UX-02

对象标签使用稳定API身份缓存，避免先匹配到旧版本的资产名称。

- 实现：[frontend/src/features/api-console/api-query-keys.ts](../../../../../frontend/src/features/api-console/api-query-keys.ts)。
- 回归：[frontend/src/features/navigation/WorkspaceObjectTabs.test.tsx](../../../../../frontend/src/features/navigation/WorkspaceObjectTabs.test.tsx)。

### F-UX-03

仅实际API/流程/报告形成对象标签；兼容清理旧模块标签；最后一个对象关闭后正确返回总览并移除标签。

- 实现：[frontend/src/features/navigation/WorkspaceObjectTabs.tsx](../../../../../frontend/src/features/navigation/WorkspaceObjectTabs.tsx)。
- 回归：[frontend/src/App.test.tsx](../../../../../frontend/src/App.test.tsx)。

### F-REP-02

断言展示冻结运行的实际值和动态期望来源、原始提取路径与运算符；同次运行且可确认的根节点提供尝试定位，区域实例或字段缺失明确未解析，不跨轮次猜测；当前草稿不参与推导。

- 实现：[assertion-source.ts](../../../../../frontend/src/features/evidence/assertion-source.ts)。
- 回归：[assertion-source.test.tsx](../../../../../frontend/src/features/evidence/assertion-source.test.tsx)。
- 详情：[补充实施与验证](batch-02.md)。

### F-API-04

导出面板支持明确的项目/本级分组/未分组/跨页所选范围；服务端校验受权集合及上限，不截断、不退回全项目。详情见[范围导出补充整改](batch-03.md)。

### F-REP-04

报告列表、趋势、分类和全范围汇总共享时间、状态、流程、环境、用例、计划及来源筛选；URL 保存范围和页码，历史来源兼容且不改写快照。未完成记录不计失败，空分母显示未提供。详见[报告统一查询范围整改](batch-05.md)。

首批22项、报告范围及用例范围经 [PR #133](https://github.com/a3384379/FlowTest/pull/133)、[PR #136](https://github.com/a3384379/FlowTest/pull/136)、[PR #137](https://github.com/a3384379/FlowTest/pull/137) 合并主分支，服务目录 [PR #138](https://github.com/a3384379/FlowTest/pull/138)、请求目标 [PR #139](https://github.com/a3384379/FlowTest/pull/139) 及多协议 [PR #140](https://github.com/a3384379/FlowTest/pull/140) 均已按最新提交正式门禁合并，项目治理[PR #141](https://github.com/a3384379/FlowTest/pull/141)也已按最新提交正式门禁合并，目前35项已合并。

### F-CASE-04

发布状态、最近结果、实际环境及排序均由服务端处理，列表/total/目录同范围；URL 保存状态，批量选择保持明确边界，固定版本和实际报告可直接打开。另修复三类列表并发读取不一致。详见[用例目录整改](batch-06.md)。

### F-SVC-01 至 F-SVC-03

完整服务端目录和页外精确读取、桌面主从/手机详情、固定契约版本目录、契约提供方定位和冻结服务影响范围均已实现。权限及迟到响应补修经过公开交互回归，完整检查与真实 PostgreSQL/浏览器通过。详见[服务目录整改](batch-07.md)。

## 下一批的具体边界

1. 任务执行 `F-TASK-01/02`：多执行项固定发布版本、环境说明、顺序与重试，以及计划/运行URL深链接。已读取方案和原处理链，正在开发，未计入完成项。
2. R2→R3→R4按详细方案逐模块推进；尚余31项，未把其他模块的未整改项标为完成。

## 请求目标当前边界

任务化与1280/390px验收完成；只读解析、候选确认、环境/权限/迟到响应及共享草稿保护已实现。复审补修新版HTTP引用与内联发布固定版本。候选下游按真实版本、子流程、用例套件及计划环境分析，缺项/超限明确标不完整；补齐套件展开预算与手机固定操作区。3项均完成本地验收；详细合同、验证提交及交付限制见[请求目标整改](batch-08.md)。

## 多协议当前边界

三项均已实现并完成本地完整检查、具名反例复审和实际浏览器验收。包含跨页精确版本、Headers/Metadata、可展开真实契约树、样例与错误路径定位、事件回包归属、会话/权限/凭据边界及手机布局。范围、精确源码与尚未执行的外部目标联调见[多协议整改](batch-09.md)。GitHub最新HEAD门禁、合并和合并后回归分开确认。

## 项目治理当前边界

F-PRJ-01/02完成本地整改：审计分页/动作URL、身份和资源详情、受权定位、组织范围成员搜索、团队搜索、身份摘要及明确失败重试。管理员、普通Owner和Viewer相关公开行为与数据库分页边界完成验证，普通Owner真实浏览器未请求全局用户目录；手机长选择项和键盘详情补修通过。精确源码、两轮完整检查及未交付边界详见[项目治理整改](batch-10.md)。该批已合并；当前合计37本地完成、35已合并，合并后回归独立记账。

## 多协议合并回执

PR #140最终HEAD `c163ba5975cc3ec7eaec5fba8dc6e6cc96a21ac0` 的正式Required Gate通过，审查线程无未解决项，按匹配SHA合并为main `4a27c3b14743be4d0df756f83238766a294adee8`。合并后[Full Regression 39505978249](https://github.com/a3384379/FlowTest/actions/runs/39505978249)已启动并核对精确head，结果等待完成。项目治理同步该main后，两侧应用源码树与最终本地完整验证逐一一致。

## 数据与Mock当前边界

`F-DATA-01/02`完成：已有规则原ID编辑与启停、服务维护、草稿保护、结构化条件、真实语义只读预览、输入/目录/输出预算、Viewer及范围隔离。最终精确源码完整检查后端1874项、前端1056项通过，真实Mock对照、同一中文模板记录及1440/390px验收通过；详见[第十一批](batch-11.md)。当前37项本地完成、36项待完成、35项已合并；本批PR门禁、合并与合并后验收分开记录。

PR #140合并后的39505978249已结束为失败，唯一失败为新公布的Vite高危依赖公告；其余检查通过。项目治理PR #141已修复该依赖并通过最新正式门禁合并，不能将旧main运行改记为成功。

## 项目治理合并与Mock后续交付

[PR #141](https://github.com/a3384379/FlowTest/pull/141)最终HEAD `b4f0ea592c082b6153022da47ae408e279525e2a` 的[正式Required Gate 39513064716](https://github.com/a3384379/FlowTest/actions/runs/39513064716)成功，审查线程为空且无下一页，按匹配SHA命令合并main为 `9e9d95ce6deb3a5dfd669ae6b4a7eae731055d33`。合并后[Full Regression 39517147484](https://github.com/a3384379/FlowTest/actions/runs/39517147484)已结束为成功，已核对精确head一致；该结果独立于PR门禁及正式环境验收。

数据与Mock [PR #142](https://github.com/a3384379/FlowTest/pull/142)同步该main时仅保留三份包含最新验证回执的整改文档，后端树 `d0096a516e80d991a72c9a0b3305ccef2b525121`、前端树 `f5245a50446913511c1f55c0a4a21301f308ce3c` 均与最终完整本地验证一致。当前37/73项本地完成、36项待完成、35项已合并；Mock的2项尚未合并。

## M09 远端失败定位与测试补修

PR #142 的旧HEAD `b30027ef96424b6bfdefc97d5e8555fa6b6b16cf` 对应[正式运行39517249183](https://github.com/a3384379/FlowTest/actions/runs/39517249183)最终失败：frontend-full中3个测试超时、1个错误提示唯一性断言失败，1052通过、4失败；backend/full与集成、Compose完整smoke（含S17）、Windows及升级作业通过。旧失败保留，不能将其他作业成功视为正式Required Gate通过。

测试补修提交 `0e771b434c26305cbb0bdcc2709ee527c8e07939` 将查询限制到本次render及相应表单，复用具名控件，在测试中关闭动画，等待保存后启停控件可用；服务目录fixture按实际服务ID隔离。失败保存保留输入与唯一错误提示断言，并新增真实PUT调用恰好一次的断言。未提高超时、跳过测试或弱化失败断言，没有修改产品实现。

3个具名文件30项定向测试通过，相关格式、ESLint和TypeScript通过。随后精确前端树 `eeaa1ebd93e4439fbb139ff219295e97108b2996` 的完整检查通过：159文件1056项、无未处理异常，覆盖率85.94/82.01/85.52/88.41%，格式、lint/类型和生产构建通过。后端树仍为 `d0096a516e80d991a72c9a0b3305ccef2b525121`，与最终1874项完整检查一致，未重复运行不变后端。日志 `remediation-mock-ci-scoped-targeted.log`、`remediation-mock-ci-followup-frontend-full.log`，旧失败完整日志 `remediation-mock-pr142-ci-failed.log`。

本地37项完成、35项已合并的数量不变。下一步仅以推送后最新HEAD的正式Required Gate及审查状态决定合并；不把本地通过或旧HEAD的部分远端通过当作新HEAD门禁。

## 契约中心当前边界

`F-CT-01/02`已实现并完成本地专项、完整检查及真实浏览器验收：完整批次/候选、独立引用、冻结只读证据、全部阻断原因、明确缺失数据及手机布局。真实第101批次/候选跨页审核、21号Provider及旧Pact固定预期通过。整合Mock后的最终完整复验独立记账，详见[第十二批](batch-12.md)。当前39/73本地完成、34待完成、37已合并；未把尚未合并模块算入GitHub交付。


## Mock合并与契约中心同步

[PR #142](https://github.com/a3384379/FlowTest/pull/142)最终HEAD `2b332c04435509661f5f33fb21597f838f241616` 的[正式Required Gate 39536764845](https://github.com/a3384379/FlowTest/actions/runs/39536764845)成功，审查线程全部解决且无下一页；按匹配SHA命令合并为main `df1d481330b8d063ea0b18f5397d089fa6de4964`。该精确提交的合并后Full Regression已单独发起，尚未确认终态。

契约中心同步main时保留本批最新进度/验证文档，Mock表单、原始字符串映射与第十一批记录采用已合并的审查补修版本。当前39项本地完成、34项待完成、37项已合并；新增Mock修复后的契约中心完整检查独立记录，未把更早前端树的完整通过套用为新树结果。

## 测试工程当前边界

`F-ENG-01/02/03`已通过具名专项、完整本地检查和真实PostgreSQL/浏览器验收，详见[第十三批](batch-13.md)。覆盖未知/空分母、原始资产引用刷新恢复、只读来源/修订/字段路径、人工审核和仅设计限制及跨上下文迟到响应均已核对，不自动发布或执行。当前42/73项本地完成、31项待完成、37项已合并。任务执行M12继续开发，本批通过不代表全站设计签收。
