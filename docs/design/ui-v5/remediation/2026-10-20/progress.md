# UI v5 审计整改进度

依据：[完整审计](../../audits/2026-10-19/complete-audit.md)、[详细方案](../../audits/2026-10-19/remediation-plan.md)。审计基线 `420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4`。

2026-10-20 整改：**23 项已实现，50 项待实施**（首批22项，加报告统一范围1项）。本批覆盖 R0 全部 5 项，以及 R1 的接口、编排、用例、报告和全局交互；R1 仅 `F-CASE-04` 仍待实施。**不是 73 项全部完成，也不是全站设计签收。**

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
| F-CASE-04  | M08  | R1   | 待实施               |
| F-REP-01   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-02   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-03   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-04   | M15  | R1   | 已实现，本地验证通过 |
| F-REP-05   | M15  | R1   | 已实现，本地验证通过 |
| F-DASH-01  | M01  | R3   | 待实施               |
| F-DASH-02  | M01  | R3   | 待实施               |
| F-SVC-01   | M03  | R2   | 待实施               |
| F-SVC-02   | M03  | R2   | 待实施               |
| F-SVC-03   | M03  | R2   | 待实施               |
| F-TGT-01   | M04  | R2   | 待实施               |
| F-TGT-02   | M04  | R2   | 待实施               |
| F-TGT-03   | M04  | R2   | 待实施               |
| F-PROTO-01 | M05  | R0   | 已实现，本地验证通过 |
| F-PROTO-02 | M05  | R2   | 待实施               |
| F-PROTO-03 | M05  | R2   | 待实施               |
| F-PROTO-04 | M05  | R2   | 待实施               |
| F-PRJ-01   | M06  | R2   | 待实施               |
| F-PRJ-02   | M06  | R2   | 待实施               |
| F-DATA-01  | M09  | R2   | 待实施               |
| F-DATA-02  | M09  | R2   | 待实施               |
| F-CT-01    | M10  | R2   | 待实施               |
| F-CT-02    | M10  | R2   | 待实施               |
| F-ENG-01   | M11  | R2   | 待实施               |
| F-ENG-02   | M11  | R2   | 待实施               |
| F-ENG-03   | M11  | R2   | 待实施               |
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

首批 22 项已经 [PR #133](https://github.com/a3384379/FlowTest/pull/133) 合并主分支；新增报告范围项仍按独立分支与最新提交门禁交付。完成数量表示代码及本地验证，不等同于 23 项均已合并。

## 下一批的具体边界

1. `F-CASE-04`：服务端发布状态、最近结果、环境和排序合同，列表/total/目录聚合同范围；不能只筛当前页。
2. R2→R3→R4按详细方案逐模块推进；本批未把次级模块的未整改项标为完成。
