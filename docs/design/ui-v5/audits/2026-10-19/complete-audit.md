# FlowTest UI v5 模块完整度审计报告

审计编号：FT-UIV5-20261019；版本：1.0；审计期间：2026-10-19—2026-10-20。目录日期为审计开始日。

**结论：26 个模块均已逐项检查入口与相关实现，但目前仍未达到 v5 方案要求的完整交互水平。确认 73 项问题/设计差距，其中 P1 5 项、P2 68 项。主要问题已经超出配色：有效规则与界面不一致、嵌套草稿保护、审核信息不足、对象定位、完整目录、统计口径和复杂配置的可视化维护。**

本轮交付为审计与修改方案，未实施业务修复。相应实施设计见 [详细修改方案](remediation-plan.md)。73 是问题/差距数量，不是缺失模块数，也不是对产品完成百分比的估算。

## 1. 基线、依据与范围

| 项目         | 本轮核实结果                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------- |
| 源码基线     | `420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4`，审计开始时与GitHub main树一致                     |
| 审计分支     | `codex/ui-functional-audit-20261019`                                                          |
| 审计工作树   | `/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest`                                   |
| 原checkout   | `/Volumes/雷电/project/FlowTest`；保留其分支与文件，不用旧checkout评价新main                  |
| 预览         | `http://127.0.0.1:13078`，隔离Compose项目flowtest-product-completion                          |
| 页面身份     | 隔离测试管理员；不能代表所有项目/组织角色验收                                                 |
| 主要设计依据 | 本地完整v5实施交接包，含01/03/04/05/06/08、26模块/28节点映射、80项验收矩阵与交互参考          |
| 本轮验证     | 26模块入口/源码逐项检查；合成API和用例真实执行；部分浏览器交互反例；7文件97条现有前端测试通过 |
| 放行边界     | 未跑make check、完整Compose E2E、Windows/历史升级/性能容量、当前提交远程门禁或生产部署验收    |

### 1.1 设计来源的优先级

完整交接包位于 `/Users/sqz/Documents/Codex/2026-10-02/task/design-library/v5/FlowTest_UI_v5_冰蓝白_实施交接包`。以其文本契约和当前业务/安全合同为准，概念图中的示例数据、禁用按钮或未开放能力不能直接当成生产能力。已对照接口、用例、请求目标原型渲染图，并检查实际请求/编排/报告及移动组织页截图；没有进行全站逐像素签收。

既往共享链接：[优化UI方案](https://chatgpt.com/share/6abef2e2-07b8-83ea-bfde-691d3d72d13b)、[后续审计共享链接](https://chatgpt.com/share/6ac1011f-d588-83ea-bfd7-6b30b3a9b6f5)。本次访问前者只有标题、没有可读取正文，后者抓取超时。因此没有把不可读取的“最新聊天内容”冒充已确认需求；本报告以完整本地v5包、仓库记录及本轮实际证据为基线。如果共享页另有未落地到该包的新决策，需要作为新增需求另行比对。

仓库已有实施记录和completeness/acceptance清单是历史交付证据，不能替代本轮验收。例如“26模块任务版式已复核”与本次仍发现交互差距并不矛盾；既有测试证明的是其覆盖场景。

### 1.2 审计边界与证据等级

| 记号   | 含义                                           | 不能据此推断                    |
| ------ | ---------------------------------------------- | ------------------------------- |
| B1     | 浏览器复现反例或真实状态，再用源码定位原因     | 不能推断所有用户/数据规模都已测 |
| B2     | 实际页面/布局观察与源码共同确认交互差距        | 不能替代完整业务执行            |
| S      | 源码分支或前后端合同足以确定问题，尚待专项执行 | 不写成真实外部系统已复现        |
| 待验证 | 现有实现或条件能力存在，本环境没有覆盖执行条件 | 不写“已完成”或“功能不存在”      |
| N      | 超出现有合同的新业务/执行能力                  | 不直接放进本次UI修复承诺        |

P1用于错误结论、输入丢失、关键结果上下文或必要任务不可达；P2用于确定的功能入口、信息架构、范围/反馈和交互差距。未发现可确认的P0，不等于完成安全/权限/引擎的全面无缺陷证明。本报告是功能与设计完整度审查，不是独立渗透或安全认证。

所有问题编号在两份文档一一对应。下文源码链接固定到本轮commit；本地浏览器日志与截图是补充证据，文档本身也写明反例和源码条件，复制MD后仍可理解结论。

## 2. 总体结果

### 2.1 高优先级问题

| ID                        | 模块         | 问题                                                                | 证据                              |
| ------------------------- | ------------ | ------------------------------------------------------------------- | --------------------------------- |
| [F-API-01](#f-api-01)     | 接口管理     | 预期状态码在已有断言时被静默忽略                                    | B1 · 浏览器反例或状态实测＋源码   |
| [F-PROTO-01](#f-proto-01) | 多协议工作台 | GraphQL/gRPC调试结果缺Schema与请求序列隔离                          | S · 源码分支/合同确认，待专项实测 |
| [F-WF-04](#f-wf-04)       | 流程编排     | 嵌套控制块未应用JSON在切换步骤后静默丢失                            | B1 · 浏览器反例或状态实测＋源码   |
| [F-REG-01](#f-reg-01)     | 变更回归     | 缺失测试可以接受/拒绝，但没有展示待审核的具体提案内容               | S · 源码分支/合同确认，待专项实测 |
| [F-REL-01](#f-rel-01)     | 发布门禁     | 项目发布判断依赖管理员全局Runner任务目录，且只截首100条后客户端过滤 | S · 源码分支/合同确认，待专项实测 |

### 2.2 已具备的能力与共性差距

已存在的关键能力包括：接口分组及跨页批量移组、顶栏管理环境、流程28类节点、控制区域、主画布草稿与保存状态、用例/套件版本和导入导出、真实执行及冻结报告、计划队列和人工审核边界。它们需要保留。

仍不足的共性是：复杂字段仍直接暴露JSON；列表能看却不能选择/定位完整对象；当前页数量被当总量；审核只见标题或拟议内容，看不到完整基线/来源；执行成功后只toast而不进入对应结果；错误、关闭、缺数据有时混用；有些局部编辑未进入全局草稿会话。

### 2.3 26模块覆盖总表

| 模块                       | 页面族                         | 本轮检查状态                                                              |  P1 |  P2 |
| -------------------------- | ------------------------------ | ------------------------------------------------------------------------- | --: | --: |
| [M01 质量总览](#m01)       | A 风险总览                     | 已审计：源码、项目总览与跨项目总览浏览器                                  |   0 |   2 |
| [M02 接口管理](#m02)       | B 请求工作台                   | 已审计：源码与管理员浏览器                                                |   1 |   4 |
| [M03 服务目录](#m03)       | C 目录/详情                    | 源码已审计；浏览器验证Contract Hub关闭态                                  |   0 |   3 |
| [M04 请求目标](#m04)       | G 分组表单＋影响预览           | 已审计：配置/影响源码与实际页面；该页回归未本轮运行                       |   0 |   3 |
| [M05 多协议工作台](#m05)   | B 多协议工作台                 | 源码已审计；浏览器验证Schema管理与调试关闭态                              |   1 |   3 |
| [M06 项目管理](#m06)       | G 治理表单                     | 已审计：源码与管理员治理页，只读核对                                      |   0 |   2 |
| [M07 流程编排](#m07)       | B 画布工作台＋D 历史证据       | 已审计：源码、节点库、until与嵌套区域浏览器交互                           |   1 |   3 |
| [M08 测试用例与套件](#m08) | C 用例目录/列表/详情           | 已审计：源码、空态、发布夹具、直接运行与套件关闭交互                      |   0 |   4 |
| [M09 数据与 Mock](#m09)    | C＋G 数据与Mock双子域          | 已审计：源码、Credential空态与Mock入口；未写入真实秘密                    |   0 |   2 |
| [M10 契约中心](#m10)       | C 契约目录＋D 兼容证据＋E 审核 | 已审计：Contract Hub关闭态、自动化页面及服务合同链；未访问Broker/Provider |   0 |   2 |
| [M11 测试工程](#m11)       | E 设计审核                     | 已审计：源码与生成入口空态                                                |   0 |   3 |
| [M12 任务执行](#m12)       | C＋F 计划与任务生命周期        | 已审计：源码与计划/运行队列空态                                           |   0 |   2 |
| [M13 环境实验室](#m13)     | F 受控环境生命周期             | 已审计：源码与能力关闭态；未Provision                                     |   0 |   2 |
| [M14 性能实验室](#m14)     | F 场景/运行＋D 冻结证据        | 已审计：源码与能力关闭态；未压测                                          |   0 |   2 |
| [M15 测试报告](#m15)       | D 冻结执行证据                 | 已审计：源码、用例→流程→报告实际API/Worker链路、390px阅读几何             |   0 |   5 |
| [M16 影响分析](#m16)       | E 差异＋D 映射/覆盖证据        | 已审计：源码与能力关闭态                                                  |   0 |   2 |
| [M17 变更回归](#m17)       | F 回归链路＋E 人工审核         | 已审计：源码与创建/历史空态；未批准执行                                   |   1 |   2 |
| [M18 质量中心](#m18)       | A 质量洞察＋D 冻结风险         | 已审计：源码、常规空态和风险功能状态                                      |   0 |   2 |
| [M19 发布门禁](#m19)       | D 发布决策/证据                | 已审计：源码与策略/判断空态；未生成新判断                                 |   1 |   2 |
| [M20 AI 助手](#m20)        | E AI建议审核                   | 已审计：源码与AI未配置关闭态；未调用模型                                  |   0 |   2 |
| [M21 上下文检查器](#m21)   | D 只读上下文/证据              | 已审计：源码与上下文列表空态，只读                                        |   0 |   1 |
| [M22 AI 变更集](#m22)      | E 变更列表/差异/来源           | 已审计：源码与关闭态503；未生成或接受变更                                 |   0 |   3 |
| [M23 MCP 变更集](#m23)     | E 受控多类型变更审核           | 已审计：源码与无focus入口态；未批准/接受                                  |   0 |   2 |
| [M24 组织治理](#m24)       | G＋F 组织治理                  | 已审计：源码与默认组织管理员页面，只读                                    |   0 |   3 |
| [M25 分布式执行面](#m25)   | F 分布式执行运维               | 已审计：源码、系统管理员能力关闭态                                        |   0 |   2 |
| [M26 平台管理](#m26)       | C 库存＋G 契约检查             | 已审计：源码、能力列表与切换插件浏览器复现                                |   0 |   2 |

另有跨模块问题3项，均为P2，不重复计入某一业务模块。26/26表示审查覆盖，**不表示26/26功能验收通过**。

## 3. 逐模块审计

<a id="m01"></a>

### M01 · 质量总览

**设计预期与任务**：项目/时间/分母明确的风险摘要、优先问题和真实证据入口；不能把当前样本当全量。

**入口/实现**：`/projects/:projectId/dashboard`；[frontend/src/pages/DashboardPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DashboardPage.tsx)。页面族：A 风险总览。

**本轮覆盖**：已审计：源码、项目总览与跨项目总览浏览器。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 风险摘要/问题队列/趋势/最近运行分层。
- 项目与跨项目范围。
- 明确关闭态和未知数据。
- 失败与冻结决策精确链接。

**发现的问题/差距**：

<a id="f-dash-01"></a>

#### F-DASH-01 · P2 · Flaky摘要将首100条页内数量作为资产总数

- 类型与证据：统计口径；S · 源码分支/合同确认，待专项实测。
- 现状与影响：主摘要传入flaky.data.items，使用length和页内quarantined数量，服务调用默认page1/page_size100，丢弃total。队列每项虽说明已加载范围，摘要卡仍无范围限制说明。大于100条时失真。
- 源码：[frontend/src/pages/DashboardPage.tsx:239-290](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DashboardPage.tsx#L239)；[frontend/src/features/dashboard/use-dashboard.ts:55-59](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/dashboard/use-dashboard.ts#L55)；[frontend/src/features/quality/quality-service.ts:122-131](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/quality/quality-service.ts#L122)。
- 达标目标：首页Flaky/隔离指标代表明确的项目范围。
- 修改项：[对应实施方案](remediation-plan.md#f-dash-01)。

<a id="f-dash-02"></a>

#### F-DASH-02 · P2 · Flaky问题入口只打开质量中心，没有定位具体资产

- 类型与证据：证据定位；S · 源码分支/合同确认，待专项实测。
- 现状与影响：问题已掌握target_type/id/version，但href不携带记录或目标；用户进入质量中心仍需再找，和冻结失败/门禁精确定位体验不一致。
- 源码：[frontend/src/features/dashboard/priority-issues.ts:124-139](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/dashboard/priority-issues.ts#L124)；[frontend/src/pages/QualityCenterPage.tsx:36-82](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.tsx#L36)。
- 达标目标：首页优先问题打开对应资产和质量记录。
- 修改项：[对应实施方案](remediation-plan.md#f-dash-02)。

**未实测与限制**：

- 当前验收环境quality_intelligence和impact_engine关闭；风险聚类等只做源码复核。

**相关回归入口**：

- [frontend/src/pages/DashboardPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DashboardPage.test.tsx)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m02"></a>

### M02 · 接口管理

**设计预期与任务**：集合目录—请求—响应/断言的连续任务；版本、发送环境和最终目标清楚；导入、批量范围与认证仍可用。

**入口/实现**：`/projects/:projectId/apis`；[frontend/src/pages/ApiConsolePage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.tsx)。页面族：B 请求工作台。

**本轮覆盖**：已审计：源码与管理员浏览器。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 集合/分组树。
- 跨页批量移动。
- 向分组批量添加。
- 页面顶栏管理环境。
- 环境编辑与发送环境分离。
- 已保存版本发送与冻结历史。
- 参数启用和重复参数。
- 导入预览合并与草稿版本冲突。

**发现的问题/差距**：

<a id="f-api-01"></a>

#### F-API-01 · P1 · 预期状态码在已有断言时被静默忽略

- 类型与证据：正确性；B1 · 浏览器反例或状态实测＋源码。
- 现状与影响：合成 GET /health 接口保存了 status_code=200 断言，界面把预期状态码改为201后发送，响应200仍通过；页面继续显示预期201。
- 源码：[frontend/src/features/api-console/api-service.ts:383-406](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/api-service.ts#L383)；[frontend/src/pages/ApiConsolePage.tsx:216-230](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.tsx#L216)。
- 达标目标：界面显示的校验规则与本次实际提交规则使用同一个来源。
- 修改项：[对应实施方案](remediation-plan.md#f-api-01)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/01-api-expect-201.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/01-api-expect-201.png`。

复核过程/条件：

1. 打开合成接口审计健康检查，确认已保存v1断言为status_code equals 200。
2. 保持保存版本不变，把响应区预期状态码改成201并发送。
3. 实际HTTP 200，界面仍显示预期201，却提示接口执行通过；实际采用已保存断言。

<a id="f-api-02"></a>

#### F-API-02 · P2 · 主接口目录缺方法与路径摘要

- 类型与证据：交互完整度；B2 · 页面/几何观察＋源码。
- 现状与影响：主目录仅名称、版本与重命名；已有目录DTO提供method/path但仅批量分组弹窗使用。
- 源码：[frontend/src/pages/ApiConsolePage.tsx:638-731](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.tsx#L638)；[frontend/src/features/api-console/api-service.ts:48-73](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/api-service.ts#L48)。
- 达标目标：目录一眼可区分同名接口和请求目标。
- 修改项：[对应实施方案](remediation-plan.md#f-api-02)。

<a id="f-api-03"></a>

#### F-API-03 · P2 · 请求响应区不可调整，桌面首屏出现固定最小高度溢出

- 类型与证据：布局；B2 · 页面/几何观察＋源码。
- 现状与影响：1440x900:请求区y246/h420，响应区y678/h240，文档高938。固定上下布局，没有分栏拖动与布局恢复。
- 源码：[frontend/src/styles.css:236-341](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/styles.css#L236)；[frontend/src/styles.css:2161-2166](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/styles.css#L2161)。
- 达标目标：桌面可同时阅读请求和响应，布局按用户调整并恢复。
- 修改项：[对应实施方案](remediation-plan.md#f-api-03)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/01-api-geometry.log`。

<a id="f-api-04"></a>

#### F-API-04 · P2 · 导出只支持整个项目，缺分组或选中接口范围说明

- 类型与证据：操作范围；S · 源码分支/合同确认，待专项实测。
- 现状与影响：导出仅传projectId和format，当前搜索/分组和selectedIds不参与，也没有范围确认。
- 源码：[frontend/src/pages/ApiConsolePage.tsx:510-530](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.tsx#L510)；[frontend/src/features/api-console/api-service.ts:285-297](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/api-service.ts#L285)。
- 达标目标：导出对象范围和当前选择一致且事前可见。
- 修改项：[对应实施方案](remediation-plan.md#f-api-04)。

<a id="f-api-05"></a>

#### F-API-05 · P2 · 认证配置仍依赖通用键值与技术键名

- 类型与证据：表单可用性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：Bearer/Basic/API Key仍手工输入token、username/password、name/value/in；缺按认证方式的专用表单与前置必填引导。属于交互差距，非认证能力缺失。
- 源码：[frontend/src/features/api-console/APIWorkbench.tsx:584-630](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/APIWorkbench.tsx#L584)。
- 达标目标：认证按类型填写，秘密和适用位置清楚。
- 修改项：[对应实施方案](remediation-plan.md#f-api-05)。

**不应误报/边界**：

- HTTP接口仅五种方法是现有前后端合同限制，HEAD/OPTIONS应作为新能力评估，不能描述为本次前端丢失功能。
- 新环境默认Service选择禁用且说明自动配置，不认定为提交字段被丢弃。

**未实测与限制**：

- 未对所有低权限角色、错误/断网/晚回包和大目录执行完整矩阵。

**相关回归入口**：

- [frontend/src/pages/ApiConsolePage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.test.tsx)
- [frontend/src/features/api-console/APIWorkbench.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/APIWorkbench.test.tsx)
- [frontend/src/features/api-console/ApiFolderActions.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/ApiFolderActions.test.tsx)
- [frontend/src/features/api-console/EnvironmentManager.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/EnvironmentManager.test.tsx)
- [backend/tests/test_execution_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_execution_api.py)
- [backend/tests/test_api_assets_domain.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_api_assets_domain.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m03"></a>

### M03 · 服务目录

**设计预期与任务**：服务目录完整可搜索，选择服务后查看契约/依赖摘要，并准确进入该服务的契约和影响上下文。

**入口/实现**：`/projects/:projectId/services`；[frontend/src/pages/ServiceCatalogPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.tsx)。页面族：C 目录/详情。

**本轮覆盖**：源码已审计；浏览器验证Contract Hub关闭态。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 服务登记/概览/契约类型/上下游角色。
- 权限与Contract Hub开关。
- 契约/影响跳转入口。

**发现的问题/差距**：

<a id="f-svc-01"></a>

#### F-SVC-01 · P2 · 搜索分页仅覆盖首100条服务，缺服务端目录分页

- 类型与证据：目录规模；S · 源码分支/合同确认，待专项实测。
- 现状与影响：默认只取第一页100条，再客户端搜索与10条分页。并非完整服务目录；focus到页外服务也不加载对象。
- 源码：[frontend/src/features/services/use-service-catalog.ts:32-36](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/services/use-service-catalog.ts#L32)；[frontend/src/features/contracts/contract-hub-service.ts:105-110](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/contract-hub-service.ts#L105)；[frontend/src/pages/ServiceCatalogPage.tsx:26-35,195-200,394-403](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.tsx#L26)。
- 达标目标：服务目录的搜索、分页与总数覆盖全部服务。
- 修改项：[对应实施方案](remediation-plan.md#f-svc-01)。

<a id="f-svc-02"></a>

#### F-SVC-02 · P2 · 契约和影响链接携带的服务定位参数未被目标页消费

- 类型与证据：跨模块关联；S · 源码分支/合同确认，待专项实测。
- 现状与影响：契约链接focus=contract_service:id，但目标只处理tab；影响链接service_id=id，但目标选择只处理run。当前验收环境开关关闭，判定为源码确定的链路缺口，未冒称已在启用环境点击复现。
- 源码：[frontend/src/pages/ServiceCatalogPage.tsx:246-258](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.tsx#L246)；[frontend/src/pages/ContractHubPage.tsx:64-77](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.tsx#L64)；[frontend/src/features/impact/use-impact-analysis.ts:35-55](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/impact/use-impact-analysis.ts#L35)。
- 达标目标：服务到契约/影响分析的跨模块入口使用被消费的参数。
- 修改项：[对应实施方案](remediation-plan.md#f-svc-02)。

<a id="f-svc-03"></a>

#### F-SVC-03 · P2 · 服务目录仍为登记表格，缺设计中的选中服务详情工作区

- 类型与证据：目录详情；S · 源码分支/合同确认，待专项实测。
- 现状与影响：服务名不可打开本页详情，依赖、版本、验证结果仍需跳其他页；缺目录—详情的同对象上下文与选中恢复。
- 源码：[frontend/src/pages/ServiceCatalogPage.tsx:177-264](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.tsx#L177)。
- 达标目标：服务目录具备就地详情和清楚的后续操作。
- 修改项：[对应实施方案](remediation-plan.md#f-svc-03)。

**未实测与限制**：

- Contract Hub在当前栈关闭，未进行真实服务登记、契约导入或提供方验证。

**相关回归入口**：

- [frontend/src/pages/ServiceCatalogPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.test.tsx)
- [backend/tests/test_contract_hub.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_contract_hub.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m04"></a>

### M04 · 请求目标

**设计预期与任务**：Service→环境 Endpoint Variant→API默认绑定→最终目标→下游影响可连续阅读；先预览再保存。

**入口/实现**：`/projects/:projectId/request-targets`；[frontend/src/pages/RequestTargetsPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.tsx)。页面族：G 分组表单＋影响预览。

**本轮覆盖**：已审计：配置/影响源码与实际页面；该页回归未本轮运行。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- Service/Endpoint/默认绑定。
- 环境选择与最终目标共享解析。
- 保存前静态影响预览。
- 显式连通性检查。
- 缓存失效刷新和只写Secret引用。

**发现的问题/差距**：

<a id="f-tgt-01"></a>

#### F-TGT-01 · P2 · 配置页仍为高密度技术表格和英文/JSON表单

- 类型与证据：专业表单与布局；B2 · 页面/几何观察＋源码。
- 现状与影响：Timeout/TLS/Proxy/Headers/Variables/Secret/Health/Revision等同屏列出；Headers/Variables用JSON编辑。应按环境—服务—Endpoint详情分层，复用已实现的MapEditor，保留高级原文入口。
- 源码：[frontend/src/pages/RequestTargetsPage.tsx:392-595,777-868](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.tsx#L392)。
- 达标目标：请求目标按用户任务组织，减少同时理解技术字段的负担。
- 修改项：[对应实施方案](remediation-plan.md#f-tgt-01)。

<a id="f-tgt-02"></a>

#### F-TGT-02 · P2 · 影响预览只拼名称，丢弃已有原因和对象定位

- 类型与证据：影响可解释性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：ImpactItem已有id/name/reason，界面只拼name字符串；不能直接定位受影响API/流程/计划，未给变更前后最终地址。后者需扩只读预览合同，不能发送真实连通请求冒充。
- 源码：[frontend/src/pages/RequestTargetsPage.tsx:699-729,882-892](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.tsx#L699)；[frontend/src/features/service-targets/service-target-service.ts:65-78](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/service-targets/service-target-service.ts#L65)。
- 达标目标：影响预览显示哪些对象、为何受影响、目标将如何变化。
- 修改项：[对应实施方案](remediation-plan.md#f-tgt-02)。

<a id="f-tgt-03"></a>

#### F-TGT-03 · P2 · 默认Service/API绑定直接提交，没有统一影响确认

- 类型与证据：变更交互一致性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：编辑Service/Endpoint先审阅再保存，默认环境Service和API绑定却下拉一变即保存；缺清楚的提交状态、影响摘要和前后目标对照。
- 源码：[frontend/src/pages/RequestTargetsPage.tsx:142-164,270-292,597-636](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.tsx#L142)。
- 达标目标：默认绑定和其他配置使用一致的预览/确认/保存过程。
- 修改项：[对应实施方案](remediation-plan.md#f-tgt-03)。

**未实测与限制**：

- 本轮未发起新的连通检查或改变已有绑定

**相关回归入口**：

- [frontend/src/pages/RequestTargetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.test.tsx)
- [backend/tests/test_request_target_guards.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_request_target_guards.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m05"></a>

### M05 · 多协议工作台

**设计预期与任务**：Schema/Descriptor/事件源目录、专用请求编辑、响应和契约检查；结果锁定协议/项目/资产/请求。

**入口/实现**：`/projects/:projectId/protocols`；[frontend/src/pages/ProtocolWorkbenchPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx)。页面族：B 多协议工作台。

**本轮覆盖**：源码已审计；浏览器验证Schema管理与调试关闭态。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- GraphQL/gRPC/Kafka/WebSocket专用模式。
- SDL/Introspection/Proto/Descriptor/Reflection导入。
- Kafka Registry Subject导入。
- gRPC方法/传输安全与mTLS引用。
- 有界事件协议与只读能力限制。

**发现的问题/差距**：

<a id="f-proto-01"></a>

#### F-PROTO-01 · P1 · GraphQL/gRPC调试结果缺Schema与请求序列隔离

- 类型与证据：响应归属；S · 源码分支/合同确认，待专项实测。
- 现状与影响：切Schema时同一编辑器组件继续挂载，result是单个useState，mutation成功直接setResult；旧Schema请求迟到或已有结果不会按选中Schema隔离。属于源码确定的响应串选路径；当前调试开关关闭，未做真实协议执行复现。
- 源码：[frontend/src/pages/ProtocolWorkbenchPage.tsx:319-369,415-446](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L319)。
- 达标目标：调试响应只属于其发起时的协议、资产和请求。
- 修改项：[对应实施方案](remediation-plan.md#f-proto-01)。

复核过程/条件：

1. 源码条件：同一协议编辑器已显示Schema A结果，选择Schema B并不重建组件。
2. GraphQLEditor/GrpcEditor的result仍是单个useState，onSuccess直接setResult，没有schema/request序号校验。
3. 因此既有A结果及迟到A回包可能显示在B名下；本轮未向真实协议服务执行此竞态。

<a id="f-proto-02"></a>

#### F-PROTO-02 · P2 · Schema/事件源翻页或刷新会隐式换选中对象

- 类型与证据：目录上下文；S · 源码分支/合同确认，待专项实测。
- 现状与影响：仅mode进URL，选择保存在局部state；当前页找不到旧ID即选择新页第一项，没有精确对象读取/选择恢复。
- 源码：[frontend/src/pages/ProtocolWorkbenchPage.tsx:92-110,724-730](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L92)；[frontend/src/features/protocols/EventProtocolWorkspace.tsx:129-155](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/protocols/EventProtocolWorkspace.tsx#L129)。
- 达标目标：协议资产选择可刷新、分享和从页外恢复。
- 修改项：[对应实施方案](remediation-plan.md#f-proto-02)。

<a id="f-proto-03"></a>

#### F-PROTO-03 · P2 · 后端支持的GraphQL Headers和gRPC Metadata没有编辑入口

- 类型与证据：调试表单；S · 源码分支/合同确认，待专项实测。
- 现状与影响：两个调试请求分别硬编码headers:{}、metadata:{}；需要Header/Metadata的认证或租户上下文无法从工作台配置。属于已有后台合同的前端能力缺口。
- 源码：[frontend/src/pages/ProtocolWorkbenchPage.tsx:355-365,426-441](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L355)；[frontend/src/features/protocols/protocol-service.ts](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/protocols/protocol-service.ts)。
- 达标目标：GraphQL Headers和gRPC Metadata可受控配置。
- 修改项：[对应实施方案](remediation-plan.md#f-proto-03)。

<a id="f-proto-04"></a>

#### F-PROTO-04 · P2 · Schema检查器主要是哈希/格式/数量，缺结构浏览与输入引导

- 类型与证据：Schema可用性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：gRPC虽可选Service/Method，但消息仍手工JSON，GraphQL也没有类型字段浏览；可先基于已有summary做类型/方法树，缺字段结构时需补授权只读合同，不能编造。
- 源码：[frontend/src/pages/ProtocolWorkbenchPage.tsx:533-560,380-395,488-493](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L533)。
- 达标目标：Schema检查器提供真实契约浏览和输入引导。
- 修改项：[对应实施方案](remediation-plan.md#f-proto-04)。

**未实测与限制**：

- multi_protocol/event_protocols在当前环境关闭
- 本轮无Kafka收发、gRPC调用、WebSocket会话或Reflection外部访问

**相关回归入口**：

- [frontend/src/pages/ProtocolWorkbenchPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.test.tsx)
- [backend/tests/test_multi_protocol.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_multi_protocol.py)
- [backend/tests/test_event_protocols.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_event_protocols.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m06"></a>

### M06 · 项目管理

**设计预期与任务**：成员/角色/egress/并发速率/保留/请求级策略和可追踪审计；保留原有读取与写入权限。

**入口/实现**：`/projects/:projectId/settings`；[frontend/src/pages/ProjectsPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProjectsPage.tsx)。页面族：G 治理表单。

**本轮覆盖**：已审计：源码与管理员治理页，只读核对。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 项目权限矩阵。
- 出站白名单/限额、保留与请求级脱敏策略。
- 策略读取失败时禁止提交默认值。
- 成员/团队、资产目录与只写Secret管理。

**发现的问题/差距**：

<a id="f-prj-01"></a>

#### F-PRJ-01 · P2 · 审计日志仅首50条且缺操作者和资源详情

- 类型与证据：审计可追踪性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：服务固定page=1/page_size=50，页面丢弃total且pagination=false；现有AuditLog含actor_user_id/resource_id/details，表格只显示时间、action、resource_type和Trace ID，无法继续翻阅或定位具体变更。
- 源码：[frontend/src/features/projects/project-service.ts:116-121](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/projects/project-service.ts#L116)；[frontend/src/pages/ProjectsPage.tsx:532-569](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProjectsPage.tsx#L532)。
- 达标目标：项目审计可翻阅和追踪到真实操作者与资源。
- 修改项：[对应实施方案](remediation-plan.md#f-prj-01)。

<a id="f-prj-02"></a>

#### F-PRJ-02 · P2 · 成员与团队面板仍使用UUID，部分读取失败表现为空列表

- 类型与证据：身份表达与失败态；S · 源码分支/合同确认，待专项实测。
- 现状与影响：现有成员用户列直接user_id，非系统管理员添加成员需手填UUID；用户/团队仅取首100条；独立面板没有QueryFailureNotice，读取失败时pageItems/arrayItems回退空列表。需要保留权限边界并提供可访问的身份摘要/服务端选择和错误态。
- 源码：[frontend/src/features/projects/AccessManagementPanel.tsx:61-120,135-178](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/projects/AccessManagementPanel.tsx#L61)；[frontend/src/features/projects/access-service.ts:11-15,55-57](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/projects/access-service.ts#L11)。
- 达标目标：成员维护不要求猜UUID，读取失败不伪装空成员。
- 修改项：[对应实施方案](remediation-plan.md#f-prj-02)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/09-projects.log`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/09-projects.snapshot.log`。

**未实测与限制**：

- 未变更真实权限、安全/保留/脱敏策略；多角色与超过50条日志未浏览器实测

**相关回归入口**：

- [frontend/src/pages/ProjectsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProjectsPage.test.tsx)
- [backend/tests/test_access_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_access_api.py)
- [backend/tests/test_access_domain.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_access_domain.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m07"></a>

### M07 · 流程编排

**设计预期与任务**：28类节点可见；画布、检查器和运行证据相互定位；未应用/未保存/已发布/历史状态分离，所有层级保护输入。

**入口/实现**：`/projects/:projectId/workflows`；[frontend/src/pages/WorkflowsPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/WorkflowsPage.tsx)。页面族：B 画布工作台＋D 历史证据。

**本轮覆盖**：已审计：源码、节点库、until与嵌套区域浏览器交互。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 28类节点注册与前置资源入口。
- 主画布撤销重做、复制粘贴、插入、校验与布局。
- 应用/保存/发布/执行与历史只读分离。
- 节点查看入口已修复。
- 控制来源/条件/策略和区域画布。
- Service/Endpoint Variant节点级选择。

**发现的问题/差距**：

<a id="f-wf-01"></a>

#### F-WF-01 · P2 · 节点摘要不足以读懂真实请求和控制意图

- 类型与证据：信息表达；S · 源码分支/合同确认，待专项实测。
- 现状与影响：API摘要只有接口资产vN，条件块摘要主要是次数/并发/上限；缺方法、URL、条件、退出规则等真实可读摘要。不能仅凭节点外观认为达到原型可读性。
- 源码：[frontend/src/flow/editor/node-presentation.ts:19-64](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/editor/node-presentation.ts#L19)。
- 达标目标：主画布无需逐个打开检查器也能读懂流程意图。
- 修改项：[对应实施方案](remediation-plan.md#f-wf-01)。

<a id="f-wf-02"></a>

#### F-WF-02 · P2 · 控制块内部API/普通步骤的可视化编辑弱于主画布

- 类型与证据：功能入口部分实现；B2 · 页面/几何观察＋源码。
- 现状与影响：区域工具栏只插入等待、API和控制块；普通API主要只有接口下拉，无法复用主画布的请求覆盖、Service/Variant、断言等完整检查器；高级JSON可表达但不等于完整可视化能力。
- 源码：[frontend/src/flow/WorkflowControlFields.tsx:1230-1385](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L1230)；[frontend/src/flow/WorkflowRegionCanvasModal.tsx:185-348](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRegionCanvasModal.tsx#L185)；[frontend/src/flow/WorkflowRegionCanvas.tsx:23-93](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRegionCanvas.tsx#L23)。
- 达标目标：区域内已有普通步骤可用与主画布一致的配置能力维护。
- 修改项：[对应实施方案](remediation-plan.md#f-wf-02)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/02-region.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/02-region.png`。

<a id="f-wf-03"></a>

#### F-WF-03 · P2 · 高级JSON默认展开并放在条件/区域等主要任务之前

- 类型与证据：交互层级；B2 · 页面/几何观察＋源码。
- 现状与影响：until节点同时显示整份配置JSON、可视化条件和完整区域JSON；320px检查器大量滚动，主任务被技术结构挤压。
- 源码：[frontend/src/flow/WorkflowControlFields.tsx:103-149](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L103)；[frontend/src/flow/ControlConfigurationJson.tsx:65-85](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/ControlConfigurationJson.tsx#L65)；[frontend/src/flow/WorkflowControlFields.tsx:1114-1130](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L1114)。
- 达标目标：常用控制配置优先，高级结构按需展开。
- 修改项：[对应实施方案](remediation-plan.md#f-wf-03)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/02-workflow-until.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/02-workflow-until.png`。

<a id="f-wf-04"></a>

#### F-WF-04 · P1 · 嵌套控制块未应用JSON在切换步骤后静默丢失

- 类型与证据：输入丢失；B1 · 浏览器反例或状态实测＋源码。
- 现状与影响：until区域插入步骤组，选中步骤组，在配置JSON增加合法inputs.audit literal=1，不应用；点击区域内等待步骤后选回，inputs恢复为空，未出现应用/丢弃/取消提示。NestedControlEditor把NodeEditContext设为null，局部JSON未进入主编辑会话。
- 源码：[frontend/src/flow/WorkflowControlFields.tsx:1199-1225](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L1199)；[frontend/src/flow/WorkflowRegionCanvasModal.tsx:38-49,145-165](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRegionCanvasModal.tsx#L38)；[frontend/src/flow/ControlConfigurationJson.tsx:20-43](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/ControlConfigurationJson.tsx#L20)。
- 达标目标：任意层级的未应用输入在切换步骤时都受同一套保护。
- 修改项：[对应实施方案](remediation-plan.md#f-wf-04)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/02-nested-valid-before.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/02-nested-valid-after.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/nested-valid-switch.log`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/02-nested-draft-loss.png`。

复核过程/条件：

1. 在合成流程添加until，打开内部区域并插入group。
2. 选group，在配置JSON中增加合法inputs.audit={kind:literal,value:1}，不应用。
3. 选wait，再回group：JSON恢复旧值，未出现应用/放弃/取消处理。主流程未保存到服务器。

**不应误报/边界**：

- 区域禁止隐式分支和部分重连是当前引擎的明确约束，不能通过放宽UI来假实现。
- 独立节点环境不是现有合同；当前流程共享environment_id，节点可选Service/Variant。
- until无独立轮询间隔/耗尽可选策略属于现有引擎合同边界，新增需单列能力需求；可由区域等待节点表达间隔。

**未实测与限制**：

- 28类节点未逐个执行
- 全部嵌套层级和断网竞态未穷举
- 大图性能与多角色未实测

**相关回归入口**：

- [frontend/src/pages/WorkflowsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/WorkflowsPage.test.tsx)
- [frontend/src/flow/WorkflowControlFields.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.test.tsx)
- [frontend/src/flow/WorkflowDesigner.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowDesigner.test.tsx)
- [frontend/src/flow/editor/node-presentation.test.ts](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/editor/node-presentation.test.ts)
- [backend/tests/test_workflow_control_nodes.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_workflow_control_nodes.py)
- [backend/tests/test_structured_control_contract.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_structured_control_contract.py)
- [backend/tests/test_control_reports.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_control_reports.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m08"></a>

### M08 · 测试用例与套件

**设计预期与任务**：目录、状态/结果/版本、已发布流程绑定、套件、计划、导入导出和删除影响明确；执行和发布分开。

**入口/实现**：`/projects/:projectId/assets`；[frontend/src/pages/TestAssetsPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx)。页面族：C 用例目录/列表/详情。

**本轮覆盖**：已审计：源码、空态、发布夹具、直接运行与套件关闭交互。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 目录/标签/服务端分页统计。
- 原生包导入预览与所选导出。
- 固定发布流程版本、运行环境、变量与头覆盖。
- 直接运行与加入计划。
- 套件固定成员版本、历史与报告关联。
- 版本对比/克隆/批量删除影响预览。

**发现的问题/差距**：

<a id="f-case-01"></a>

#### F-CASE-01 · P2 · 缺前置资源时新建用例只显示禁用，没有缺项解释与跳转

- 类型与证据：前置条件反馈；B1 · 浏览器反例或状态实测＋源码。
- 现状与影响：新项目没有已发布流程或环境时按钮禁用，未清楚指向应先发布流程还是配置环境；管理员已在新建合成项目前置状态复现。
- 源码：[frontend/src/pages/TestAssetsPage.tsx:734-754,910-978](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L734)。
- 达标目标：新建用例的缺项和下一步可直接理解。
- 修改项：[对应实施方案](remediation-plan.md#f-case-01)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/cases-transition.log`。

<a id="f-case-02"></a>

#### F-CASE-02 · P2 · 套件编辑关闭没有草稿确认或恢复，和用例编辑不一致

- 类型与证据：输入保护；B1 · 浏览器反例或状态实测＋源码。
- 现状与影响：新建套件输入名称后关闭即消失；重新打开字段为空。CaseDialog有放弃确认，SuiteDialog直接onClose。
- 源码：[frontend/src/pages/TestAssetsPage.tsx:1496-1500,1956-2004](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L1496)。
- 达标目标：套件编辑草稿保护与用例编辑保持一致。
- 修改项：[对应实施方案](remediation-plan.md#f-case-02)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/03-suite-close.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/03-suite-after-reopen.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/03-suite-reopened.png`。

复核过程/条件：

1. 新建套件，输入审计未保存套件。
2. 关闭弹窗，再次新建套件。
3. 输入已清空且无草稿确认；与CaseDialog的保护行为不一致。

<a id="f-case-03"></a>

#### F-CASE-03 · P2 · 编辑用例和套件时目录选择没有树层级或完整路径

- 类型与证据：目录表达；S · 源码分支/合同确认，待专项实测。
- 现状与影响：目录浏览是树，编辑选择却folders.map只使用name；不同父级下同名目录无法清楚区分。
- 源码：[frontend/src/pages/TestAssetsPage.tsx:1560-1562,2018-2020,2120-2122](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L1560)。
- 达标目标：目录选择展示完整层级和可区分路径。
- 修改项：[对应实施方案](remediation-plan.md#f-case-03)。

<a id="f-case-04"></a>

#### F-CASE-04 · P2 · 用例目录缺发布状态、最近结果、环境和排序等任务筛选

- 类型与证据：筛选与维护；S · 源码分支/合同确认，待专项实测。
- 现状与影响：当前只有名称/描述、标签与目录。字段已经在对象和列表呈现，但不能直接筛出未发布、失败或指定环境待维护资产。属于交互增强，需补服务端筛选合同。
- 源码：[frontend/src/pages/TestAssetsPage.tsx:632-669](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L632)；[frontend/src/features/test-assets/use-test-assets.ts:47-66](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-assets/use-test-assets.ts#L47)。
- 达标目标：维护用例时可按真实发布/执行/环境维度定位。
- 修改项：[对应实施方案](remediation-plan.md#f-case-04)。

**不应误报/边界**：

- 用例主要职责是固定流程版本/环境/输入；独立于流程的步骤编辑器、维护状态或测试设计模型若不存在需新能力，不应按概念图虚构。
- 全历史分页与版本包已实现，不沿用旧报告里仅最近20次和无导入导出的结论。

**未实测与限制**：

- 多角色实测
- 大目录负载
- 全部导入冲突和归档影响分支

**相关回归入口**：

- [frontend/src/pages/TestAssetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.test.tsx)
- [frontend/src/pages/TestAssetsWorkspace.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsWorkspace.test.tsx)
- [frontend/src/features/test-assets/AssetPlanDialog.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-assets/AssetPlanDialog.test.tsx)
- [frontend/src/features/test-assets/AssetRunEvidence.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-assets/AssetRunEvidence.test.tsx)
- [backend/tests/test_tasking_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_tasking_api.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m09"></a>

### M09 · 数据与 Mock

**设计预期与任务**：Credential元数据与秘密只写；Mock服务/规则/场景与请求日志可维护，配置不变成任意脚本。

**入口/实现**：`/projects/:projectId/data`；[frontend/src/pages/DataMockPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DataMockPage.tsx)。页面族：C＋G 数据与Mock双子域。

**本轮覆盖**：已审计：源码、Credential空态与Mock入口；未写入真实秘密。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- Credential元数据和加密只写输入。
- Vault引用与平台加密选项。
- Mock服务启停、规则创建删除、场景/优先级/延迟。
- 服务端分页请求日志与错误提示。

**发现的问题/差距**：

<a id="f-data-01"></a>

#### F-DATA-01 · P2 · Mock规则只有创建删除，没有编辑和单规则启停

- 类型与证据：已有能力未接入；S · 源码分支/合同确认，待专项实测。
- 现状与影响：后端已有update_route及is_enabled/priority等字段，前端无PATCH包装与编辑入口，表格不显示启用状态/优先级，新增固定is_enabled=true。维护已建场景要删除重建，影响可理解性和稳定引用。
- 源码：[frontend/src/pages/DataMockPage.tsx:399-490,591-604](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DataMockPage.tsx#L399)；[frontend/src/features/data-sources/data-source-service.ts:78-106](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/data-sources/data-source-service.ts#L78)；[backend/app/api/v1/endpoints/data_sources.py:198-219](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/api/v1/endpoints/data_sources.py#L198)。
- 达标目标：已建Mock规则可直接维护与启停。
- 修改项：[对应实施方案](remediation-plan.md#f-data-01)。

<a id="f-data-02"></a>

#### F-DATA-02 · P2 · Mock匹配条件和响应配置仍依赖四块JSON，缺结构化预览

- 类型与证据：表单交互；S · 源码分支/合同确认，待专项实测。
- 现状与影响：Query/Header/响应头/响应体都直接JSON输入，jsonRule仅检查可解析，不检查字符串映射等字段类型；缺规则详情与变量/场景匹配结果预览。建议复用现有模板语义，纯本地/受控预览，不增加脚本执行。
- 源码：[frontend/src/pages/DataMockPage.tsx:519-618](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DataMockPage.tsx#L519)。
- 达标目标：Mock规则有结构化条件和可解释的响应预览。
- 修改项：[对应实施方案](remediation-plan.md#f-data-02)。

**未实测与限制**：

- 未创建或读取真实Credential秘密
- 未执行数据库/Redis命令、外部Mock访问和高流量日志场景

**相关回归入口**：

- [frontend/src/pages/DataMockPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DataMockPage.test.tsx)
- [backend/tests/test_data_nodes_and_mock.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_data_nodes_and_mock.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m10"></a>

### M10 · 契约中心

**设计预期与任务**：服务、OpenAPI/Pact、兼容矩阵和真实阻断证据联动；导入与候选审核覆盖完整目录。

**入口/实现**：`/projects/:projectId/contracts`；[frontend/src/pages/ContractHubPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.tsx)。页面族：C 契约目录＋D 兼容证据＋E 审核。

**本轮覆盖**：已审计：Contract Hub关闭态、自动化页面及服务合同链；未访问Broker/Provider。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 服务目录、兼容矩阵、部署判断。
- Pact/OpenAPI导入及Provider验证合同。
- 契约自动化：基线比较、生成候选、人工接受/拒绝。
- 明确不可信输入和Exact Matcher边界。

**发现的问题/差距**：

<a id="f-ct-01"></a>

#### F-CT-01 · P2 · OpenAPI批次/候选固定首100条；兼容提供方选项只来自当前目录页

- 类型与证据：完整目录与对象选择；S · 源码分支/合同确认，待专项实测。
- 现状与影响：自动化把Page转items后无服务端翻页入口；超过100批次/候选不能继续审核。Hub已有目录分页，但提供方/验证/导入下拉只拿当前20条services/pacts，需独立分页搜索与按ID补取，不能把当前页当全集。
- 源码：[frontend/src/features/contracts/contract-service.ts:3-8,31-40](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/contract-service.ts#L3)；[frontend/src/features/contracts/ContractAutomationPanel.tsx:54-78](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/ContractAutomationPanel.tsx#L54)；[frontend/src/pages/ContractHubPage.tsx:67-75,864-867](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.tsx#L67)。
- 达标目标：契约批次、候选审核和引用选择能到达所有授权对象。
- 修改项：[对应实施方案](remediation-plan.md#f-ct-01)。

<a id="f-ct-02"></a>

#### F-CT-02 · P2 · 发布阻断证据和契约变更主要停留在数量摘要

- 类型与证据：证据查看；S · 源码分支/合同确认，待专项实测。
- 现状与影响：不可发布判断只显示blockers数量；统一资产表只给破坏性变更数量/覆盖率，没有行详情、具体失败Interaction、期望/实际或版本变更定位。已有evidence/breaking_changes未形成可操作的证据面板。
- 源码：[frontend/src/pages/ContractHubPage.tsx:464-484,503-583](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.tsx#L464)。
- 达标目标：不可发布判断可以直接检查阻断原因和Interaction。
- 修改项：[对应实施方案](remediation-plan.md#f-ct-02)。

**不应误报/边界**：

- contract_hub关闭不等于整个契约自动化不存在；两者开关/合同需分别判断

**未实测与限制**：

- Pact Broker同步、Provider真实请求、复杂Matcher拒绝和部署兼容算法未本轮执行

**相关回归入口**：

- [frontend/src/pages/ContractHubPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.test.tsx)
- [frontend/src/features/contracts/ContractAutomationPanel.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/ContractAutomationPanel.test.tsx)
- [backend/tests/test_contract_hub.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_contract_hub.py)
- [backend/tests/test_contract_automation.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_contract_automation.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m11"></a>

### M11 · 测试工程

**设计预期与任务**：契约→只读设计→Scenario/Oracle/Coverage→Draft→Review→Apply→已生成资产；来源与不确定性可检查。

**入口/实现**：`/projects/:projectId/test-engineering`；[frontend/src/pages/TestEngineeringPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.tsx)。页面族：E 设计审核。

**本轮覆盖**：已审计：源码与生成入口空态。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 契约只读生成、Scenario/Oracle/Coverage证据。
- API分页资源选择与目标Variant约束。
- Draft→人工Review→Apply状态限制。
- 设计态与可物化场景区分、契约完整性和指纹。

**发现的问题/差距**：

<a id="f-eng-01"></a>

#### F-ENG-01 · P2 · 空覆盖项被显示为100%覆盖

- 类型与证据：指标口径；S · 源码分支/合同确认，待专项实测。
- 现状与影响：total为0时percent直接100，未区分无可评估项与全部覆盖；违反未知/无数据不能伪装满分的设计约定。
- 源码：[frontend/src/pages/TestEngineeringPage.tsx:292-295,322-328](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.tsx#L292)。
- 达标目标：无评估项与100%覆盖明确区分。
- 修改项：[对应实施方案](remediation-plan.md#f-eng-01)。

<a id="f-eng-02"></a>

#### F-ENG-02 · P2 · 物化成功只弹数量，丢弃具体Workflow/TestCase定位

- 类型与证据：跨模块闭环；S · 源码分支/合同确认，待专项实测。
- 现状与影响：Apply返回workflow_ids/test_case_ids，但hook只显示数量toast并置applied=true，页面仅已进入执行体系Tag；缺生成资产清单、版本、打开编排/用例入口，用户无法从审核任务自然继续维护。
- 源码：[frontend/src/features/test-engineering/use-test-engineering.ts:137-152](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-engineering/use-test-engineering.ts#L137)；[frontend/src/pages/TestEngineeringPage.tsx:494-532](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.tsx#L494)。
- 达标目标：Apply后可以打开每个生成的工作流和用例。
- 修改项：[对应实施方案](remediation-plan.md#f-eng-02)。

<a id="f-eng-03"></a>

#### F-ENG-03 · P2 · 主要页面大量开发阶段标签和英文术语，证据引用不能钻取

- 类型与证据：任务可理解性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：S47、Scenario Review、Oracle/Evidence Priority等直接进入业务界面；Evidence只计数，source_ref文本ellipsis，无场景→Oracle→来源的选中联动。需中文任务层级与技术信息渐进披露。
- 源码：[frontend/src/pages/TestEngineeringPage.tsx:60-72,307-351,378-416,552-611](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.tsx#L60)。
- 达标目标：测试设计按来源、场景、Oracle和缺口组织为可读审核任务。
- 修改项：[对应实施方案](remediation-plan.md#f-eng-03)。

**未实测与限制**：

- 未创建、Review或Apply新Proposal；外部上下文与物化结果未浏览器实测

**相关回归入口**：

- [frontend/src/pages/TestEngineeringPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.test.tsx)
- [frontend/src/features/test-engineering/use-test-engineering.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-engineering/use-test-engineering.test.tsx)
- [backend/tests/test_test_engineering.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_test_engineering.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m12"></a>

### M12 · 任务执行

**设计预期与任务**：计划编组、固定版本、调度、队列、取消、CI/Webhook与冻结执行证据闭环；一次性秘密规则保持。

**入口/实现**：`/projects/:projectId/tasks`；[frontend/src/pages/TestPlansPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestPlansPage.tsx)。页面族：C＋F 计划与任务生命周期。

**本轮覆盖**：已审计：源码与计划/运行队列空态。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 计划服务端分页、运行队列与取消。
- 手动/间隔/Cron时区、优先级重试。
- 用例/套件/流程固定版本目标选择。
- CI Token只显示一次与撤销、签名Webhook。
- 运行详情冻结目标→报告/编排真实定位。

**发现的问题/差距**：

<a id="f-task-01"></a>

#### F-TASK-01 · P2 · 新建计划只能添加一个目标，未开放后端多执行项编组

- 类型与证据：已有能力未接入；S · 源码分支/合同确认，待专项实测。
- 现状与影响：后端TestPlanCreate支持1–100项，前端固定items:[单目标]；缺批量选入、顺序/逐项环境与重试摘要。编辑合同仅维护调度，不能在UI绕过固定版本或擅自改历史项。
- 源码：[frontend/src/pages/TestPlansPage.tsx:434-547](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestPlansPage.tsx#L434)；[frontend/src/features/task-plans/task-plan-service.ts:134-155](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/task-plans/task-plan-service.ts#L134)；[backend/app/schemas/tasking.py:37-47](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/schemas/tasking.py#L37)。
- 达标目标：计划新建可以组织多个固定版本执行项。
- 修改项：[对应实施方案](remediation-plan.md#f-task-01)。

<a id="f-task-02"></a>

#### F-TASK-02 · P2 · focus链接仅高亮当前页，运行详情不进入URL

- 类型与证据：对象定位；S · 源码分支/合同确认，待专项实测。
- 现状与影响：收到focus后没有按ID补取/定位页，目标不在前20条则无反馈；selectedRunId仅局部状态，刷新或分享无法重开同一运行详情。
- 源码：[frontend/src/pages/TestPlansPage.tsx:43-52,131-159,270-280](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestPlansPage.tsx#L43)；[frontend/src/features/task-plans/use-test-plans.ts:30-34,68-81](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/task-plans/use-test-plans.ts#L30)。
- 达标目标：计划与运行深链接在页外、刷新和返回后仍可恢复。
- 修改项：[对应实施方案](remediation-plan.md#f-task-02)。

**未实测与限制**：

- 未新建计划、签发Token或触发调度/Webhook；真实Worker批量顺序与取消未本轮执行

**相关回归入口**：

- [frontend/src/pages/TestPlansPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestPlansPage.test.tsx)
- [frontend/src/features/task-plans/TestPlanTargetSelect.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/task-plans/TestPlanTargetSelect.test.tsx)
- [backend/tests/test_tasking_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_tasking_api.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m13"></a>

### M13 · 环境实验室

**设计预期与任务**：签名模板/版本→Provision→实例/TTL→Seed/健康记录→清理；多服务声明式配置受原合同约束。

**入口/实现**：`/projects/:projectId/environments`；[frontend/src/pages/EnvironmentLabPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/EnvironmentLabPage.tsx)。页面族：F 受控环境生命周期。

**本轮覆盖**：已审计：源码与能力关闭态；未Provision。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 签名模板版本/镜像Digest白名单。
- 实例按ID深链接、生命周期/端点/Seed/清理证据。
- 目录分页和幂等清理。
- 健康信息明确是生命周期记录而非实时监控。

**发现的问题/差距**：

<a id="f-env-01"></a>

#### F-ENV-01 · P2 · 模板创建固定单web服务，完整版本维护退回整份JSON

- 类型与证据：可视化配置完整度；S · 源码分支/合同确认，待专项实测。
- 现状与影响：服务列表、depends_on、environment、健康参数/Seed等合同已存在；注册表单固定name=web、NGINX_PORT和固定健康参数，只支持单镜像，新版本全部JSON。缺多服务结构化编辑、依赖/资源校验与变更对比；不能以允许任意Compose/脚本补齐。
- 源码：[frontend/src/pages/EnvironmentLabPage.tsx:488-618,671-710,863-911](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/EnvironmentLabPage.tsx#L488)；[frontend/src/features/environments/environment-service.ts:14-39](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/environments/environment-service.ts#L14)。
- 达标目标：受控模板的完整多服务配置有可视化维护入口。
- 修改项：[对应实施方案](remediation-plan.md#f-env-01)。

<a id="f-env-02"></a>

#### F-ENV-02 · P2 · 实例绑定模板配置受当前模板目录页限制

- 类型与证据：冻结版本定位；S · 源码分支/合同确认，待专项实测。
- 现状与影响：实例有template_version_id，但资源页只在当前20条templates中find，不在页内即要求手动翻目录；没有按版本ID读取/补取，无法可靠从实例打开完整绑定配置。后端需受权只读版本查询或稳定补取能力。
- 源码：[frontend/src/pages/EnvironmentLabPage.tsx:775-823](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/EnvironmentLabPage.tsx#L775)；[frontend/src/features/environments/use-environment-lab.ts:49-54](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/environments/use-environment-lab.ts#L49)；[backend/app/api/v1/endpoints/environment_lab.py:27-44](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/api/v1/endpoints/environment_lab.py#L27)。
- 达标目标：从实例可靠读取它绑定的模板版本。
- 修改项：[对应实施方案](remediation-plan.md#f-env-02)。

**不应误报/边界**：

- 持续健康采样不是现有实例合同，须单列新能力而非用ready伪装实时健康

**未实测与限制**：

- 模板签名/Provision/Seed/TTL到期和清理重试未本轮执行

**相关回归入口**：

- [frontend/src/pages/EnvironmentLabPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/EnvironmentLabPage.test.tsx)
- [backend/tests/test_environment_lab.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_environment_lab.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m14"></a>

### M14 · 性能实验室

**设计预期与任务**：声明式HTTP步骤、固定/阶梯负载、阈值、版本、基线和门禁分离；阅读页面不自动压测。

**入口/实现**：`/projects/:projectId/performance`；[frontend/src/pages/PerformanceLabPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PerformanceLabPage.tsx)。页面族：F 场景/运行＋D 冻结证据。

**本轮覆盖**：已审计：源码与能力关闭态；未压测。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 场景发布版本、配置/运行按ID独立读取。
- 冻结负载、阈值、基线摘要、门禁证据。
- 分页目录、原始指标授权下载。
- 无稳定性判定时明确未提供。

**发现的问题/差距**：

<a id="f-perf-01"></a>

#### F-PERF-01 · P2 · 新建只支持单HTTP步骤，复杂负载与版本维护依赖JSON

- 类型与证据：可视化配置完整度；S · 源码分支/合同确认，待专项实测。
- 现状与影响：后端现有steps/stages/headers/body/thresholds等声明式合同；初建表单仅一个请求和一个升压目标，版本编辑直接18行JSON。需有界步骤列表、阶段/阈值表单和版本对比，保留不执行用户JS与原有负载限制。
- 源码：[frontend/src/pages/PerformanceLabPage.tsx:297-432,459-504,822-896](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PerformanceLabPage.tsx#L297)；[frontend/src/features/performance/performance-service.ts:10-48](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/performance/performance-service.ts#L10)。
- 达标目标：复杂HTTP负载与版本编辑无需手写整份配置。
- 修改项：[对应实施方案](remediation-plan.md#f-perf-01)。

<a id="f-perf-02"></a>

#### F-PERF-02 · P2 · 启动运行后未选中新运行或提供直接进入证据的入口

- 类型与证据：执行结果闭环；S · 源码分支/合同确认，待专项实测。
- 现状与影响：runPerformanceScenario返回运行对象，通用withFeedback丢弃返回值，只刷新列表并toast；当前详情可能仍是旧运行，用户需回列表自行寻找新任务。应绑定返回run.id更新URL与队列状态，同时保护跨项目响应。
- 源码：[frontend/src/features/performance/use-performance-lab.ts:112-132,176-186](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/performance/use-performance-lab.ts#L112)；[frontend/src/pages/PerformanceLabPage.tsx:135-165](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PerformanceLabPage.tsx#L135)。
- 达标目标：启动后立即进入所返回的新运行上下文。
- 修改项：[对应实施方案](remediation-plan.md#f-perf-02)。

**不应误报/边界**：

- 无持续原始时序和稳定性合同不应填演示图或伪造稳定标签；取消/任意基线选择也需先核实后端扩展

**未实测与限制**：

- 未运行k6、下载指标或检验回归门禁；功能开关关闭

**相关回归入口**：

- [frontend/src/pages/PerformanceLabPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PerformanceLabPage.test.tsx)
- [frontend/src/features/performance/use-performance-lab.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/performance/use-performance-lab.test.tsx)
- [backend/tests/test_performance_lab.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_performance_lab.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m15"></a>

### M15 · 测试报告

**设计预期与任务**：项目/工作流/运行/节点/attempt及可用实例路径一致；真实期望/实际/单位/来源可定位；历史只读且可导出。

**入口/实现**：`/projects/:projectId/reports`；[frontend/src/pages/ReportsPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReportsPage.tsx)。页面族：D 冻结执行证据。

**本轮覆盖**：已审计：源码、用例→流程→报告实际API/Worker链路、390px阅读几何。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 同一执行的报告/只读流程快照互链。
- 节点/请求attempt/控制实例证据。
- 失败筛选与预期实际比较。
- 统计明确本页分母。
- HTML冻结执行树导出与通知配置。
- 390px合成报告无页面横向溢出。

**发现的问题/差距**：

<a id="f-rep-01"></a>

#### F-REP-01 · P2 · 默认选中节点未规范化到链接上下文，跨视图跳转改变选中节点

- 类型与证据：上下文保留；B1 · 浏览器反例或状态实测＋源码。
- 现状与影响：从用例运行打开流程历史时URL只有execution，流程自动选中API；点击查看完整报告后报告自动选中开始。显式node/attempt URL已有转发逻辑，不能写成所有节点链接都未实现。问题限于默认选中状态和URL不同步。
- 源码：[frontend/src/pages/WorkflowsPage.tsx:1381-1398,1600-1635](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/WorkflowsPage.tsx#L1381)；[frontend/src/features/reports/ReportExecutionWorkspace.tsx:56-72,254-260](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L56)。
- 达标目标：默认选中和显式选中使用同一个可分享的证据定位。
- 修改项：[对应实施方案](remediation-plan.md#f-rep-01)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/03-case-workflow-runtime.snapshot.yml`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/04-report-detail.snapshot.yml`。

复核过程/条件：

1. 从合成用例直接执行进入该workflow运行页，URL只有execution且未带node。
2. 运行页默认选中API业务节点，点击查看完整报告。
3. 同一run进入报告后默认选中开始节点；显式node/attempt参数的转发代码已存在，问题只在默认选中未规范化。

<a id="f-rep-02"></a>

#### F-REP-02 · P2 · 断言证据来源主要是静态文字，缺上游来源路径与直接定位

- 类型与证据：证据定位；S · 源码分支/合同确认，待专项实测。
- 现状与影响：断言展示预期/实际和差值，但来源传当前节点名，不能从断言直接定位冻结快照中的上游HTTP节点和字段路径；单位缺失明确显示未提供，不能填演示金额单位。
- 源码：[frontend/src/features/evidence/AssertionEvidence.tsx:3-9,53-57](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/evidence/AssertionEvidence.tsx#L3)；[frontend/src/features/evidence/assertion-model.ts:20-33](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/evidence/assertion-model.ts#L20)；[frontend/src/features/reports/ReportExecutionWorkspace.tsx:340-380](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L340)。
- 达标目标：断言结论能追溯到同一冻结运行的来源和路径。
- 修改项：[对应实施方案](remediation-plan.md#f-rep-02)。

<a id="f-rep-03"></a>

#### F-REP-03 · P2 · 报告与流程证据仍以通用pre JSON展示，缺API工作台的阅读工具

- 类型与证据：证据阅读；S · 源码分支/合同确认，待专项实测。
- 现状与影响：普通证据没有统一格式/换行/复制/有界预览工具，复杂请求响应和错误阅读仍依赖原始JSON。大型对象引用已有授权下载，不能描述为完全没有大响应处理。
- 源码：[frontend/src/flow/WorkflowRunInspector.tsx:1069-1110](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRunInspector.tsx#L1069)；[frontend/src/features/reports/ReportExecutionWorkspace.tsx:462-533](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L462)；[frontend/src/features/api-console/ResponseCodeReader.tsx:4-69](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/ResponseCodeReader.tsx#L4)。
- 达标目标：编排和报告证据具备可读、可复制、受边界约束的阅读器。
- 修改项：[对应实施方案](remediation-plan.md#f-rep-03)。

<a id="f-rep-04"></a>

#### F-REP-04 · P2 · 报告缺时间、流程、环境或用例等任务维度筛选

- 类型与证据：筛选与统计范围；S · 源码分支/合同确认，待专项实测。
- 现状与影响：趋势固定7日，列表只按项目与状态查询；无法直接收敛到一次回归时间段或某个环境/流程。需补服务端过滤及同范围汇总，不能用当前页估计全量。
- 源码：[frontend/src/pages/ReportsPage.tsx:145-242](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReportsPage.tsx#L145)；[frontend/src/features/reports/report-service.ts:30-58](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/report-service.ts#L30)。
- 达标目标：报告列表与趋势具有一致且可见的查询范围。
- 修改项：[对应实施方案](remediation-plan.md#f-rep-04)。

<a id="f-rep-05"></a>

#### F-REP-05 · P2 · 节点页的检查点日志没有沿节点/尝试筛选

- 类型与证据：检查点作用域；S · 源码分支/合同确认，待专项实测。
- 现状与影响：检查点组件只接受project/execution/running，查询整次执行的全部节点日志；与当前节点卡片并置，缺当前node/attempt/控制实例范围和明确切换。现有列表展示节点名，不认定为数据越权或错误归属。
- 源码：[frontend/src/features/reports/ReportExecutionWorkspace.tsx:426-434](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L426)；[frontend/src/features/workflows/ExecutionCheckpointLog.tsx:12-35](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/workflows/ExecutionCheckpointLog.tsx#L12)。
- 达标目标：节点检查点/日志明确当前筛选范围。
- 修改项：[对应实施方案](remediation-plan.md#f-rep-05)。

**不应误报/边界**：

- 报告与编排的执行关联已存在且本轮真实运行验证，不能再笼统列为未关联。
- 仅失败筛选、缺证据空态、冻结名称/版本、分页历史和递归HTML导出均有实现。

**未实测与限制**：

- 本轮没有新建通知或实际外发
- 递归导出全部规模/边界未重跑
- 复杂失败循环报告只源码复核
- 未进行全站像素/WCAG/发布验收

**相关回归入口**：

- [frontend/src/pages/ReportsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReportsPage.test.tsx)
- [frontend/src/features/workflows/execution-navigation.test.ts](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/workflows/execution-navigation.test.ts)
- [backend/tests/test_reporting_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_reporting_api.py)
- [backend/tests/test_control_reports.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_control_reports.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m16"></a>

### M16 · 影响分析

**设计预期与任务**：变更→影响→推荐集合→覆盖缺口之间有可解释关联和资产入口，不执行仓库命令。

**入口/实现**：`/projects/:projectId/impact`；[frontend/src/pages/ImpactAnalysisPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ImpactAnalysisPage.tsx)。页面族：E 差异＋D 映射/覆盖证据。

**本轮覆盖**：已审计：源码与能力关闭态。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 显式映射、有限Git diff/Schema版本对比。
- 分析历史分页与run按ID定位。
- 冻结变更、推荐原因与覆盖矩阵。
- 创建后绑定返回分析ID并保护跨项目响应。

**发现的问题/差距**：

<a id="f-imp-01"></a>

#### F-IMP-01 · P2 · 三列影响视图是静态列表，缺变更到资产/证据的联动定位

- 类型与证据：联动与可行动性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：变更、受影响资产、推荐测试都无选中联动；后两列重复同一selected_assets，仅切换原因文案；资产名不可打开，覆盖格只计数。已有change_keys/target_type/id/reasons可支撑过滤与资产跳转。
- 源码：[frontend/src/pages/ImpactAnalysisPage.tsx:245-352,354-405](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ImpactAnalysisPage.tsx#L245)。
- 达标目标：影响视图能从一个变更追到原因、覆盖和真实资产。
- 修改项：[对应实施方案](remediation-plan.md#f-imp-01)。

<a id="f-imp-02"></a>

#### F-IMP-02 · P2 · 资产列数量使用边数，映射摘要只统计当前页且关闭态显示0

- 类型与证据：统计口径；S · 源码分支/合同确认，待专项实测。
- 现状与影响：受影响资产Badge用graph.edges.length，但实际渲染selected_assets；一个资产命中多个变更时数值不符。显式映射概览使用mappings.length，非Page.total，且未获取数据时显示0。
- 源码：[frontend/src/pages/ImpactAnalysisPage.tsx:79-82,133,189-225,269-282](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ImpactAnalysisPage.tsx#L79)。
- 达标目标：影响摘要的数量与渲染对象和查询范围一致。
- 修改项：[对应实施方案](remediation-plan.md#f-imp-02)。

**未实测与限制**：

- 未打开impact_engine或提交分析；实际多来源映射与复杂覆盖未执行

**相关回归入口**：

- [frontend/src/pages/ImpactAnalysisPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ImpactAnalysisPage.test.tsx)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m17"></a>

### M17 · 变更回归

**设计预期与任务**：变更来源→影响→当前计划覆盖→缺失测试审核→人工批准→执行→发布门禁，端到端证据可检查。

**入口/实现**：`/projects/:projectId/change-regression`；[frontend/src/pages/ChangeRegressionPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.tsx)。页面族：F 回归链路＋E 人工审核。

**本轮覆盖**：已审计：源码与创建/历史空态；未批准执行。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 变更→影响→覆盖缺口→人工Review/批准→执行→发布判断。
- 当前计划与项目已知覆盖区分。
- 语义豁免原因/到期与固定版本回归约束。
- Context维护、Sandbox/Apply Draft边界。

**发现的问题/差距**：

<a id="f-reg-01"></a>

#### F-REG-01 · P1 · 缺失测试可以接受/拒绝，但没有展示待审核的具体提案内容

- 类型与证据：审核信息完整度；S · 源码分支/合同确认，待专项实测。
- 现状与影响：MissingTestProposal已有proposed_content、review_note和物化资源字段，页面只显示标题、review_status和接受/拒绝按钮；无法在当前审核上下文检查将生成的请求/断言/版本/目标，削弱人工Review的真实可审阅性。后端仍执行状态守卫，本轮未证明绕过。
- 源码：[frontend/src/pages/ChangeRegressionPage.tsx:251-310](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.tsx#L251)；[frontend/src/features/change-regression/change-regression-service.ts:38-46](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/change-regression/change-regression-service.ts#L38)。
- 达标目标：接受缺失测试前可以审阅将被物化的完整内容和依据。
- 修改项：[对应实施方案](remediation-plan.md#f-reg-01)。

复核过程/条件：

1. 源码条件：链路包含review_status=pending的MissingTestProposal。
2. RunDetail表格只呈现title/status/接受/拒绝，proposed_content未渲染。
3. 按钮可提交reviewItem，但当前审核位置无法核对将被物化的完整内容；未实际接受或证明后端守卫可绕过。

<a id="f-reg-02"></a>

#### F-REG-02 · P2 · 新建回归强制Git Diff，不能通过已有OpenAPI/Schema版本差异发起

- 类型与证据：已有来源未接入；S · 源码分支/合同确认，待专项实测。
- 现状与影响：输入合同支持openapi_diffs/schema_diffs，前端固定传空数组且git_diff required；影响分析已有可复用版本对比选择，回归链路没有接通。
- 源码：[frontend/src/pages/ChangeRegressionPage.tsx:54-67,142-144](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.tsx#L54)；[frontend/src/features/change-regression/change-regression-service.ts:15-28](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/change-regression/change-regression-service.ts#L15)。
- 达标目标：回归链路可以使用既有的契约版本差异来源。
- 修改项：[对应实施方案](remediation-plan.md#f-reg-02)。

<a id="f-reg-03"></a>

#### F-REG-03 · P2 · 关键链路证据ID仅文本，失败分类无法定位具体运行和证据引用

- 类型与证据：端到端追踪；S · 源码分支/合同确认，待专项实测。
- 现状与影响：Impact Run/Test Plan Run/Release Decision显示UUID，FailureTriage仅EvidenceRefs数量和推荐字符串；缺跨模块精确跳转、对应节点/attempt和提案资产入口。
- 源码：[frontend/src/pages/ChangeRegressionPage.tsx:233-248,945-1001](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.tsx#L233)。
- 达标目标：回归端到端证据可以逐环节打开并返回。
- 修改项：[对应实施方案](remediation-plan.md#f-reg-03)。

**未实测与限制**：

- 未创建/接受缺失测试或批准执行；复杂语义门禁、豁免失效及真实维护提案未执行

**相关回归入口**：

- [frontend/src/pages/ChangeRegressionPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.test.tsx)
- [frontend/src/features/change-regression/RegressionMaintenancePanel.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/change-regression/RegressionMaintenancePanel.test.tsx)
- [backend/tests/test_change_regression.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_change_regression.py)
- [backend/tests/test_s59d_change_regression.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s59d_change_regression.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m18"></a>

### M18 · 质量中心

**设计预期与任务**：质量门禁、Flaky隔离、基线、风险/聚类、推荐测试与JUnit；统计和修复入口具备真实范围。

**入口/实现**：`/projects/:projectId/quality`；[frontend/src/pages/QualityCenterPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.tsx)。页面族：A 质量洞察＋D 冻结风险。

**本轮覆盖**：已审计：源码、常规空态和风险功能状态。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 质量门禁创建、Flaky目录/隔离。
- 计划运行与JUnit产物。
- 风险按ID读取、风险窗口/算法/因子/聚类。
- Flaky摘要明确已载入范围，不当作全量统计。

**发现的问题/差距**：

<a id="f-qlt-01"></a>

#### F-QLT-01 · P2 · 启用门禁统计包含停用门禁

- 类型与证据：统计正确性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：传给gateCount的是listItems(gates.data).length，没有filter(enabled)，但标签为启用门禁；全部门禁数和启用数语义不一致。
- 源码：[frontend/src/pages/QualityCenterPage.tsx:69-75,327-345](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.tsx#L69)。
- 达标目标：启用门禁数量按真实enabled状态统计。
- 修改项：[对应实施方案](remediation-plan.md#f-qlt-01)。

<a id="f-qlt-02"></a>

#### F-QLT-02 · P2 · 风险历史有翻页却无记录选择，资产和运行也缺证据入口

- 类型与证据：对象选择与追踪；S · 源码分支/合同确认，待专项实测。
- 现状与影响：activeRiskId只能来自risk URL或当前页首项；页面未呈现risks.items的选择表，无法打开同页第2–20项。Flaky资产为短ID、最近运行只提供JUnit，建议测试/聚类没有对象/报告定位，质量任务到修复的闭环不足。
- 源码：[frontend/src/features/quality/use-quality-center.ts:75-104](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/quality/use-quality-center.ts#L75)；[frontend/src/pages/QualityCenterPage.tsx:76-82,120-180,202-323,527-560](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.tsx#L76)。
- 达标目标：质量问题和任意风险快照可被选择、分享并进入修复证据。
- 修改项：[对应实施方案](remediation-plan.md#f-qlt-02)。

**未实测与限制**：

- 未修改真实质量门禁或隔离状态；quality_intelligence关闭，风险业务链仅源码确认

**相关回归入口**：

- [frontend/src/pages/QualityCenterPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.test.tsx)
- [backend/tests/test_quality_domain.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_domain.py)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m19"></a>

### M19 · 发布门禁

**设计预期与任务**：版本/策略→必需证据→PASS/BLOCK及逐项理由→历史指纹；缺失、过期、失败与不满足规则可区分。

**入口/实现**：`/projects/:projectId/release`；[frontend/src/pages/ReleaseGatePage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.tsx)。页面族：D 发布决策/证据。

**本轮覆盖**：已审计：源码与策略/判断空态；未生成新判断。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 策略与必需证据配置。
- 不可变PASS/BLOCK、逐项实际/期望和策略/证据快照。
- decision按ID读取与项目校验。
- 明确不触发生产部署。

**发现的问题/差距**：

<a id="f-rel-01"></a>

#### F-REL-01 · P1 · 项目发布判断依赖管理员全局Runner任务目录，且只截首100条后客户端过滤

- 类型与证据：权限与证据选择正确性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：runner_fabric开启时所有项目使用者请求系统管理员任务API；普通项目Owner/Editor会403且无该查询错误展示，管理员也只能取全局最近100条再按项目过滤，可能看不到本项目有效证据。需项目范围受权只读证据查询，不能放开系统管理权限。此项由源码确认，开关关闭未用低权限浏览器复现。
- 源码：[frontend/src/features/release-gate/use-release-gate.ts:118-122](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/release-gate/use-release-gate.ts#L118)；[frontend/src/pages/ReleaseGatePage.tsx:371-374](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.tsx#L371)；[frontend/src/features/execution-fabric/execution-fabric-service.ts:123-127](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/execution-fabric/execution-fabric-service.ts#L123)；[backend/app/services/runner_fabric.py:183-186,1157-1165](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/services/runner_fabric.py#L183)；[backend/app/services/release_gate.py:106-110](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/services/release_gate.py#L106)。
- 达标目标：项目角色在其授权范围内选择Runner证据。
- 修改项：[对应实施方案](remediation-plan.md#f-rel-01)。

复核过程/条件：

1. 源码条件：runner_fabric开启，当前用户是非系统管理员的项目Owner/Editor。
2. useReleaseGate调用/execution-fabric/tasks；RunnerFabricService.list_tasks要求is_system_admin，否则403。
3. 前端只把全局最近100条再按项目过滤，且该读取错误未被展示；本轮开关关闭，未用低权限浏览器执行。

<a id="f-rel-02"></a>

#### F-REL-02 · P2 · 生成判断没有按所选策略展示必需证据/关闭原因，性能证据仅当前20条

- 类型与证据：证据选择体验；S · 源码分支/合同确认，待专项实测。
- 现状与影响：六类证据统一可选，默认未选择，没有策略要求标记、能力关闭/读取失败/无数据区分；performanceRuns是默认第一页且无分页入口。后端缺证据会正确BLOCK，但前端不能在提交前帮助完成收集。
- 源码：[frontend/src/pages/ReleaseGatePage.tsx:495-593](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.tsx#L495)；[frontend/src/features/release-gate/use-release-gate.ts:111-122](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/release-gate/use-release-gate.ts#L111)。
- 达标目标：按策略引导收集真实必需证据。
- 修改项：[对应实施方案](remediation-plan.md#f-rel-02)。

<a id="f-rel-03"></a>

#### F-REL-03 · P2 · 判断证据缺到原始对象的结构化跳转

- 类型与证据：证据定位；S · 源码分支/合同确认，待专项实测。
- 现状与影响：理由表显示状态/类型/消息/actual/expected，完整快照可读，但没有按证据类型进入固定质量运行、契约判断、影响分析、风险、性能/Runner的入口；排查阻断需复制ID手动找。
- 源码：[frontend/src/pages/ReleaseGatePage.tsx:163-227,597-699](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.tsx#L163)。
- 达标目标：每条发布阻断理由可进入对应冻结来源。
- 修改项：[对应实施方案](remediation-plan.md#f-rel-03)。

**未实测与限制**：

- 未创建发布策略/判断；普通项目角色的Runner403为源码确认；未验证所有跨证据一致性算法

**相关回归入口**：

- [frontend/src/pages/ReleaseGatePage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.test.tsx)
- [backend/tests/test_release_gate.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_release_gate.py)
- [backend/tests/test_runner_fabric.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_runner_fabric.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m20"></a>

### M20 · AI 助手

**设计预期与任务**：任务来源与建议可审阅、编辑/备注/接受/拒绝及生成草稿定位；不自动执行或扩大数据采集。

**入口/实现**：`/projects/:projectId/ai`；[frontend/src/pages/AIAssistantPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIAssistantPage.tsx)。页面族：E AI建议审核。

**本轮覆盖**：已审计：源码与AI未配置关闭态；未调用模型。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 任务分页与运行状态轮询。
- 显式样本共享开关与只写草稿审核。
- 接受前可编辑内容、拒绝附备注。
- 不自动发布/执行的提示和权限守卫。

**发现的问题/差距**：

<a id="f-ai-01"></a>

#### F-AI-01 · P2 · 四种AI任务使用同一Schema/元数据JSON表单，接受也只编辑JSON

- 类型与证据：任务表单与审核表达；S · 源码分支/合同确认，待专项实测。
- 现状与影响：用例/断言/流程草稿/失败归因均要求同一OpenAPI Schema表单，缺已有API/执行证据来源选择、按任务的必填引导和结构化草稿预览。样本/元数据统一称脱敏也未反映项目ON/OFF策略；文案应按实际授权采集和策略说明，不新增扫描或采集。
- 源码：[frontend/src/pages/AIAssistantPage.tsx:284-315,374-448](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIAssistantPage.tsx#L284)。
- 达标目标：AI建议按实际任务选择来源并展示可理解内容。
- 修改项：[对应实施方案](remediation-plan.md#f-ai-01)。

<a id="f-ai-02"></a>

#### F-AI-02 · P2 · 任务失败原因和接受后资产字段未展示

- 类型与证据：失败反馈与输出定位；S · 源码分支/合同确认，待专项实测。
- 现状与影响：AIJob已有error_code/error_message，AISuggestion已有accepted_resource_type/id，但UI只有状态Tag和审核按钮；失败无法看原因/Trace上下文，接受后也没有打开对应草稿或建议内容的只读入口。
- 源码：[frontend/src/features/ai/ai-service.ts:17-47](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/ai-service.ts#L17)；[frontend/src/pages/AIAssistantPage.tsx:179-247](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIAssistantPage.tsx#L179)；[frontend/src/features/ai/use-ai-review.ts:112-119](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/use-ai-review.ts#L112)。
- 达标目标：AI任务失败和接受结果均可继续处理。
- 修改项：[对应实施方案](remediation-plan.md#f-ai-02)。

**未实测与限制**：

- 未开启样本共享、提交AI任务、接受建议或调用外部网关

**相关回归入口**：

- [frontend/src/pages/AIAssistantPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIAssistantPage.test.tsx)
- [backend/tests/test_ai_assistant.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_ai_assistant.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m21"></a>

### M21 · 上下文检查器

**设计预期与任务**：Context Revision、完整性/冲突、来源Finding、知识关系和Proposal可联动检查，保持只读。

**入口/实现**：`/projects/:projectId/contexts`；[frontend/src/pages/ContextInspectorPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContextInspectorPage.tsx)。页面族：D 只读上下文/证据。

**本轮覆盖**：已审计：源码与上下文列表空态，只读。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- Context分页、focus按ID详情。
- 完整性、冲突、Provider Finding、知识关系。
- 关联Proposal有编排跳转。
- 只读边界明确，无自动Review/Apply。

**发现的问题/差距**：

<a id="f-ctx-01"></a>

#### F-CTX-01 · P2 · 证据、冲突与知识关系是长列表，缺来源联动和精确引用定位

- 类型与证据：证据浏览交互；S · 源码分支/合同确认，待专项实测。
- 现状与影响：所有详情纵向铺开；冲突subject_ref、Finding的source_path/source_ref/revision、State Candidate的evidence_ref都是文本；无法从冲突筛选来源、从知识边定位证据，缺类型/确定性/警告筛选。应在只读范围内做主从联动，不把修复或Apply放入检查器。
- 源码：[frontend/src/pages/ContextInspectorPage.tsx:120-157,192-339](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContextInspectorPage.tsx#L120)。
- 达标目标：只读检查器可以沿冲突、知识和来源定位证据。
- 修改项：[对应实施方案](remediation-plan.md#f-ctx-01)。

**不应误报/边界**：

- 创建/刷新/修改Context不应强行放入只读检查器；历史revision查询若新增需核实API能力

**未实测与限制**：

- 未导入真实仓库或Context；复杂冲突、过期修订和大证据集未浏览器实测

**相关回归入口**：

- [frontend/src/pages/ContextInspectorPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContextInspectorPage.test.tsx)
- [frontend/src/features/context-inspector/use-context-page.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/context-inspector/use-context-page.test.tsx)
- [backend/tests/test_s49_context_contracts.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s49_context_contracts.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m22"></a>

### M22 · AI 变更集

**设计预期与任务**：固定风险与影响证据，逐项查看目标基线和变更、审核备注/冲突，接受后进入允许的草稿。

**入口/实现**：`/projects/:projectId/ai-changes`；[frontend/src/pages/AIChangeSetsPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.tsx)。页面族：E 变更列表/差异/来源。

**本轮覆盖**：已审计：源码与关闭态503；未生成或接受变更。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 分页变更集、按focus详情与项目一致性校验。
- 风险→影响来源固定。
- 逐项接受/拒绝、接受仅更新草稿。
- 生成任务轮询与失败重试提示。

**发现的问题/差距**：

<a id="f-aic-01"></a>

#### F-AIC-01 · P2 · 修改项没有目标基线与前后差异，来源证据也没有进入审核面板

- 类型与证据：审核依据；S · 源码分支/合同确认，待专项实测。
- 现状与影响：ChangeSetDetail只传items，忽略source_snapshot；每项只显示proposed_content。target_resource_id/target_snapshot_sha256和审核人/时间/备注不展示；修改无法对照固定基线，不能用当前资产冒充冻结基线。必要时扩展受权只读基线快照。
- 源码：[frontend/src/pages/AIChangeSetsPage.tsx:178-200,268-333](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.tsx#L178)；[frontend/src/features/ai/ai-change-set-service.ts:3-19,42-45](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/ai-change-set-service.ts#L3)。
- 达标目标：变更审核同时呈现固定来源、目标基线和拟修改内容。
- 修改项：[对应实施方案](remediation-plan.md#f-aic-01)。

<a id="f-aic-02"></a>

#### F-AIC-02 · P2 · 接受后无物化资产入口，审核编辑关闭会直接丢弃

- 类型与证据：结果定位与输入保护；S · 源码分支/合同确认，待专项实测。
- 现状与影响：已有materialized_resource_type/id只剩已接受Tag，缺打开草稿入口；修改JSON或备注后onCancel直接关闭卸载，没有保留或应用/放弃/取消提示。
- 源码：[frontend/src/pages/AIChangeSetsPage.tsx:299-333,374-430](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.tsx#L299)；[frontend/src/features/ai/ai-change-set-service.ts:14-19](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/ai-change-set-service.ts#L14)。
- 达标目标：审核编辑受到保护，接受后能打开物化草稿。
- 修改项：[对应实施方案](remediation-plan.md#f-aic-02)。

<a id="f-aic-03"></a>

#### F-AIC-03 · P2 · AI/质量智能开关与只读历史提示不一致，关闭态仍请求并重试503

- 类型与证据：功能状态合同；B1 · 浏览器反例或状态实测＋源码。
- 现状与影响：页面声称AI未启用仍可查看已有审核；实际list/get均要求quality_intelligence与AI开启。目录不受状态控制，当前同一目录读取及其重试均返回503。需明确只读历史是否可用并统一前后端合同；若保留历史，应只放开授权读取，写入/生成仍受开关。
- 源码：[frontend/src/features/ai/use-ai-change-sets.ts:28-58,121-125](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/use-ai-change-sets.ts#L28)；[frontend/src/pages/AIChangeSetsPage.tsx:164-176](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.tsx#L164)；[backend/app/services/ai_change_sets.py:165-179,485-491](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/services/ai_change_sets.py#L165)。
- 达标目标：关闭生成能力仍可在授权范围内读取历史，写入继续受控。
- 修改项：[对应实施方案](remediation-plan.md#f-aic-03)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/.playwright-cli/console-2026-10-19T15-42-11-586Z.log`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/22-ai-changes.log`。

**未实测与限制**：

- 未调用模型、生成或审核真实变更；固定基线冲突未执行

**相关回归入口**：

- [frontend/src/pages/AIChangeSetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.test.tsx)
- [frontend/src/features/ai/use-ai-change-sets.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/use-ai-change-sets.test.tsx)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m23"></a>

### M23 · MCP 变更集

**设计预期与任务**：精确变更集、治理摘要、批准、逐项内容/差异/结果，保留当前模型的审批和修订号限制。

**入口/实现**：`/projects/:projectId/mcp-changes`；[frontend/src/pages/MCPChangeSetsPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/MCPChangeSetsPage.tsx)。页面族：E 受控多类型变更审核。

**本轮覆盖**：已审计：源码与无focus入口态；未批准/接受。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 精确ChangeSet ID读取、项目校验。
- 高风险需批准、逐项接受与服务端修订冲突守卫。
- 控制工作流/控制块图预览。
- 新建工作流接受后有草稿入口。

**发现的问题/差距**：

<a id="f-mcp-01"></a>

#### F-MCP-01 · P2 · 返回的warnings与Trace ID、置信度/风险原因未进入审核页

- 类型与证据：治理信息展示；S · 源码分支/合同确认，待专项实测。
- 现状与影响：仅使用response.data，Envelope.warnings/trace_id被忽略；governance仅展示risk_level，confidence/reason_codes和approval人/时间缺失。需要可核对的治理摘要，保留服务端批准限制。
- 源码：[frontend/src/features/mcp/mcp-change-set-service.ts:41-64](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/mcp/mcp-change-set-service.ts#L41)；[frontend/src/pages/MCPChangeSetsPage.tsx:91-95,154-189](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/MCPChangeSetsPage.tsx#L91)。
- 达标目标：批准前能看完整治理结论和请求诊断身份。
- 修改项：[对应实施方案](remediation-plan.md#f-mcp-01)。

<a id="f-mcp-02"></a>

#### F-MCP-02 · P2 · Test Design/TestCase/TestPlan更新缺结构化预览和物化结果定位

- 类型与证据：多类型审核完整度；S · 源码分支/合同确认，待专项实测。
- 现状与影响：只有workflow类型有图与目标链接；其他三类统一原始JSON，未呈现固定版本、计划项变更前后/环境/重试等任务摘要，接受后没有materialized_resource_id入口。不能把已有工作流预览概括成所有类型都完成。
- 源码：[frontend/src/pages/MCPChangeSetsPage.tsx:190-247,280-373](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/MCPChangeSetsPage.tsx#L190)；[frontend/src/features/mcp/mcp-change-set-service.ts:3-17](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/mcp/mcp-change-set-service.ts#L3)。
- 达标目标：各类MCP变更都有对应的审核摘要和结果入口。
- 修改项：[对应实施方案](remediation-plan.md#f-mcp-02)。

**不应误报/边界**：

- 无focus不列出全部MCP变更集符合精确资源发现边界，不以增加全局发现权限补齐UI

**未实测与限制**：

- 未新建、批准、Review或物化MCP提案；真实MCP客户端验收未执行

**相关回归入口**：

- [frontend/src/pages/MCPChangeSetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/MCPChangeSetsPage.test.tsx)
- [backend/tests/test_s51_mcp_flow_proposals.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s51_mcp_flow_proposals.py)
- [backend/tests/test_s62_planning_mcp.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s62_planning_mcp.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m24"></a>

### M24 · 组织治理

**设计预期与任务**：组织角色、服务账号、配额/Runner、审计与密钥生命周期按角色呈现，失败不伪装健康。

**入口/实现**：`/organization`；[frontend/src/pages/OrganizationGovernancePage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.tsx)。页面族：G＋F 组织治理。

**本轮覆盖**：已审计：源码与默认组织管理员页面，只读。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 组织/角色、Service Account签发轮换撤销与一次显示。
- 配额/Runner治理、审计保留。
- 密钥Prepare/Apply/Rollback受角色与原有事务合同约束。
- 支持包数据边界说明。

**发现的问题/差距**：

<a id="f-org-01"></a>

#### F-ORG-01 · P2 · 审计/Runner/安全/支持包读取失败未显示对应错误，安全区仍固定宣称可用

- 类型与证据：失败态与真实状态；S · 源码分支/合同确认，待专项实测。
- 现状与影响：顶层仅检查governance/members/accounts三项，另外四项错误回退undefined或空数组；KeyRotationCard仍显示成功Alert真实Key Rotation可用，掩盖当前读取失败。应分别显示Loading/Error/无权限/可用证据与重试，不能把能力描述当运行健康。
- 源码：[frontend/src/pages/OrganizationGovernancePage.tsx:304-318,450-465,1010-1054](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.tsx#L304)。
- 达标目标：每个治理子域按其实际读取结果显示状态。
- 修改项：[对应实施方案](remediation-plan.md#f-org-01)。

<a id="f-org-02"></a>

#### F-ORG-02 · P2 · 组织审计固定首50条且缺操作者和资源定位

- 类型与证据：审计目录完整度；S · 源码分支/合同确认，待专项实测。
- 现状与影响：服务请求page1/size50，传items后前端每页10条，只能翻这50条；没有时间/动作/人员/资源过滤，details为整段JSON。应按服务端total翻页并提供只读详情。
- 源码：[frontend/src/features/organizations/organization-service.ts:252-259](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/organizations/organization-service.ts#L252)；[frontend/src/pages/OrganizationGovernancePage.tsx:411-417,1165-1201](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.tsx#L411)。
- 达标目标：组织审计能服务真实追踪任务。
- 修改项：[对应实施方案](remediation-plan.md#f-org-02)。

<a id="f-org-03"></a>

#### F-ORG-03 · P2 · 组织成员需填用户ID，提交尚未成功就清空输入

- 类型与证据：身份输入与失败保护；S · 源码分支/合同确认，待专项实测。
- 现状与影响：添加/更新表单同步触发mutate后立即resetFields，失败仅通用toast，已输入ID/角色丢失；表格也只显示UUID。需要受权限约束的身份选择与成功后清空、失败保留。
- 源码：[frontend/src/pages/OrganizationGovernancePage.tsx:598-608,613-639](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.tsx#L598)。
- 达标目标：身份维护可理解且提交失败保留输入。
- 修改项：[对应实施方案](remediation-plan.md#f-org-03)。

**未实测与限制**：

- 未改变组织角色、配额、令牌或密钥；低权限与真实KMS/重加密未执行

**相关回归入口**：

- [frontend/src/pages/OrganizationGovernancePage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.test.tsx)
- [backend/tests/test_organization_governance.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_organization_governance.py)
- [backend/tests/test_organizations_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_organizations_api.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m25"></a>

### M25 · 分布式执行面

**设计预期与任务**：管理员可检查Worker/队列/任务/Lease/Fence的当前状态与证据，计数范围/更新时间可辨。

**入口/实现**：`/execution-fabric`；[frontend/src/pages/ExecutionFabricPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ExecutionFabricPage.tsx)。页面族：F 分布式执行运维。

**本轮覆盖**：已审计：源码、系统管理员能力关闭态。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 仅管理员入口与能力边界。
- Worker Pool/Runner状态、Drain/Resume、一次性注册令牌。
- 真实overview与Lease/Fencing事件合同。
- 禁止任意脚本/镜像计划。

**发现的问题/差距**：

<a id="f-fab-01"></a>

#### F-FAB-01 · P2 · 队列分组统计只取最近100个任务，Pool目录也固定首100

- 类型与证据：目录/队列口径；S · 源码分支/合同确认，待专项实测。
- 现状与影响：按required_runner_type分组统计取limit100任务，标签为当前队列/排队运行失败，无最近100条范围提示；可能与真实overview计数不一致。Pool分页合同已有但UI只取首100，没有继续选择入口。
- 源码：[frontend/src/features/execution-fabric/execution-fabric-service.ts:114-144](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/execution-fabric/execution-fabric-service.ts#L114)；[frontend/src/pages/ExecutionFabricPage.tsx:142-156,288-315](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ExecutionFabricPage.tsx#L142)。
- 达标目标：当前队列指标和库存不受最近样本窗口误导。
- 修改项：[对应实施方案](remediation-plan.md#f-fab-01)。

<a id="f-fab-02"></a>

#### F-FAB-02 · P2 · 执行面不定时刷新且没有任务/Lease详情定位

- 类型与证据：运维任务闭环；S · 源码分支/合同确认，待专项实测。
- 现状与影响：五个读查询未配置运行态轮询或显式刷新按钮，本页显式invalidate由变更后触发，浏览器聚焦等默认查询刷新不等于持续监测；leases读取却不展示，事件仅短任务/Runner ID，无法钻取对应任务、Lease/Fence和workflow执行证据。需要有界刷新、时间戳与只读任务详情，不改变调度一致性。
- 源码：[frontend/src/pages/ExecutionFabricPage.tsx:70-87,157-166,256-284,317-342](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ExecutionFabricPage.tsx#L70)。
- 达标目标：执行面有明确刷新节奏和任务/Lease证据链。
- 修改项：[对应实施方案](remediation-plan.md#f-fab-02)。

**未实测与限制**：

- runner_fabric关闭；未签发令牌、接入Runner、Drain或制造Lease故障转移

**相关回归入口**：

- [frontend/src/pages/ExecutionFabricPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ExecutionFabricPage.test.tsx)
- [backend/tests/test_runner_fabric.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_runner_fabric.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

<a id="m26"></a>

### M26 · 平台管理

**设计预期与任务**：按能力/插件/Runner选择对象并检查版本、Schema、Digest和安全边界；未开放的安装保持不可用。

**入口/实现**：`/platform`；[frontend/src/pages/PlatformCapabilitiesPage.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PlatformCapabilitiesPage.tsx)。页面族：C 库存＋G 契约检查。

**本轮覆盖**：已审计：源码、能力列表与切换插件浏览器复现。页面状态检查与可选功能真实执行分开记账。

**已实现、应保留**：

- 能力/插件/Runner库存与角色分界。
- 版本/哈希/网络/超时/Snapshot摘要。
- 安装插件禁用且有未开放说明。
- 已载入计数明确范围。

**发现的问题/差距**：

<a id="f-plat-01"></a>

#### F-PLAT-01 · P2 · 切换插件/Runner后右侧仍展示上一个能力详情

- 类型与证据：对象上下文正确性；B1 · 浏览器反例或状态实测＋源码。
- 现状与影响：mode只切换左表，右侧始终CapabilityInspector(selected)；浏览器选插件，左侧无插件而右侧仍assertion.evaluate@2.0.0，产生错误对象上下文。插件与Runner行也没有对应详情选择。
- 源码：[frontend/src/pages/PlatformCapabilitiesPage.tsx:39-67,158-166,170-247,366-406](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PlatformCapabilitiesPage.tsx#L39)。
- 达标目标：右侧详情始终属于当前库存模式和选中对象。
- 修改项：[对应实施方案](remediation-plan.md#f-plat-01)。
- 本地补充证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/26-platform-plugin.log`。

复核过程/条件：

1. 打开平台能力列表，右侧默认显示assertion.evaluate@2.0.0。
2. 切换为插件；当前插件列表为空。
3. 右侧仍展示该能力的Schema/Runner/策略，属于上一模式的对象上下文。

<a id="f-plat-02"></a>

#### F-PLAT-02 · P2 · 能力检查器没有提供已返回的完整Schema和策略字段

- 类型与证据：契约可检查性；S · 源码分支/合同确认，待专项实测。
- 现状与影响：只显示哈希前16位、Runner、网络、默认超时、Credential类型和是否固定哈希；input/output/configuration_schema、最大超时、协议/DNS、插件Digest/签名关联等已有字段缺只读查看和复制，无法完成能力契约核对。
- 源码：[frontend/src/pages/PlatformCapabilitiesPage.tsx:366-406](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PlatformCapabilitiesPage.tsx#L366)；[frontend/src/features/capabilities/capability-service.ts:17-51](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/capabilities/capability-service.ts#L17)。
- 达标目标：能力契约可完整只读核对。
- 修改项：[对应实施方案](remediation-plan.md#f-plat-02)。

**不应误报/边界**：

- 受控插件安装/签名验证后端未开放，不能把禁用按钮改为假安装；Capability35条并不等于工作流35类节点，28类编辑节点映射另行核对

**未实测与限制**：

- 未安装插件、接入Runner或运行全部Capability；超过100条库存未实测

**相关回归入口**：

- [frontend/src/pages/PlatformCapabilitiesPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PlatformCapabilitiesPage.test.tsx)
- [backend/tests/test_workflow_contract.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_workflow_contract.py)

以上为可复用/需补强的测试位置；除第6节列出的7个文件外，本轮未运行这些测试。已通过旧用例不能覆盖本报告未被测试断言的反例。

## 4. 跨模块审计

全局壳已具备68px常用任务栏、全部模块抽屉、项目/搜索/账号和冰蓝白主题。以下问题不重复计入业务模块。

<a id="f-ux-01"></a>

### F-UX-01 · P2 · 全局搜索请求失败被显示成没有可访问资产

SearchEmpty只判断query和isFetching，无isError；浏览器对合成搜索请求返回503两次后显示未找到可访问的资产，实际失败文案不可见。应提供真实错误/Trace ID/重试，避免把服务失败混成搜索无结果。

证据等级：B1 · 浏览器反例或状态实测＋源码。源码：[frontend/src/features/search/GlobalSearch.tsx:31-62,76-79](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/search/GlobalSearch.tsx#L31)。

本地证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/27-global-search-error.log`。对应 [修改方案](remediation-plan.md#f-ux-01)。

1. 仅在本次浏览器拦截合成关键词的/api/v1/search读取，返回503标准错误；不改服务器。
2. 输入审计故障检索20261020，等待自动重试结束。
3. 记录到2次拦截后界面显示未找到可访问的资产，错误文案计数为0；随后撤销拦截并清空搜索。

<a id="f-ux-02"></a>

### F-UX-02 · P2 · 接口标签读取的缓存键少了版本维度，名称不能更新

cachedLabel读取[api-detail,projectId,apiId]，实际查询[api-detail,projectId,apiId,selectedVersion]；ReactQuery按完整key取值，标签回退截断UUID。1280与1440浏览器均显示接口·e6eca458-ca8，主编辑器已有真实名称。

证据等级：B1 · 浏览器反例或状态实测＋源码。源码：[frontend/src/features/navigation/WorkspaceObjectTabs.tsx:254-263](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/navigation/WorkspaceObjectTabs.tsx#L254)；[frontend/src/features/api-console/use-api-console.ts:398-402](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/use-api-console.ts#L398)。

本地证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/27-api-1280.log`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/09-projects.log`。对应 [修改方案](remediation-plan.md#f-ux-02)。

<a id="f-ux-03"></a>

### F-UX-03 · P2 · 对象标签页自动累积模块入口，重复承担第二份模块导航

routeWorkspaceTab对所有section都创建标签，无focus的模块也保留；依次审计后标签包含服务目录、项目管理、数据、契约、环境等二十余模块。v5要求对象标签仅承载已打开接口/流程/报告，局部目录随任务替换。应停止自动登记普通模块，不删除已持久化的真实对象标签/草稿。

证据等级：B2 · 页面/几何观察＋源码。源码：[frontend/src/features/navigation/workspace-tab-store.ts:17-44](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/navigation/workspace-tab-store.ts#L17)；[frontend/src/features/navigation/WorkspaceObjectTabs.tsx:62-78](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/navigation/WorkspaceObjectTabs.tsx#L62)。

本地证据：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/27-api-1280.log`；`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/04-report-desktop.png`。对应 [修改方案](remediation-plan.md#f-ux-03)。

### 4.1 多模块共用的验收要求

- 选中对象独立于当前目录页；URL/对象tab/详情都使用同一身份。不能为方便而无提示选择首项。
- 原始JSON、表单值、已应用配置、服务器保存版本和冻结运行结果分别建模；关闭或切换必须处理未提交内容。
- 未加载、无权限、功能关闭、读取失败、真实空列表、缺证据分别反馈；缺值不能自动为0或通过。
- 权限守卫放在现有服务层，前端禁用仅用于解释。不能为接UI开放管理员目录或秘密读取。
- 颜色本身不表示结论；状态同时显示文本/图标。复杂表单与证据阅读仍需按页面族重组。
- 390px只承诺报告/证据/受权审核可用，不将完整复杂画布强行塞进移动端；本轮只抽查报告/组织页。

## 5. 28类节点与80项验收的核对

### 5.1 节点映射

来源：[frontend/src/flow/editor/node-registry.ts](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/editor/node-registry.ts)及v5文档03。当前编辑器确有28项一对一入口；平台Capability列表35项是另一种库存，不能据此说编辑节点增加为35类。开始定位标记不作为第29个注册执行类型。

| 注册键               | 显示名             | 本轮结论                                         |
| -------------------- | ------------------ | ------------------------------------------------ |
| `delay`              | 等待               | 入口/前置条件源码核对；未执行                    |
| `end`                | 结束               | 合成主图执行；节点结束不等于所有断言通过         |
| `api`                | 接口请求           | 主图API合成执行成功；区域完整配置仍有F-WF-02     |
| `graphql`            | GraphQL 请求       | 入口/前置条件源码核对；未执行                    |
| `grpc`               | gRPC 调用          | 入口/前置条件源码核对；未执行                    |
| `kafka.produce`      | Kafka Produce      | 入口/前置条件源码核对；未执行                    |
| `kafka.consume`      | Kafka Consume      | 入口/前置条件源码核对；未执行                    |
| `websocket.exchange` | WebSocket Exchange | 入口/前置条件源码核对；未执行                    |
| `extract`            | 提取变量           | 入口/前置条件源码核对；未执行                    |
| `assert`             | 断言校验           | 入口/前置条件源码核对；未执行                    |
| `condition`          | 条件判断           | 旧类型独立保留，不自动迁移；执行待验证           |
| `control.if`         | 条件判断 · 控制块  | 入口/前置条件源码核对；未执行                    |
| `control.switch`     | 多分支判断         | 入口/前置条件源码核对；未执行                    |
| `control.foreach`    | 集合遍历           | 入口/前置条件源码核对；未执行                    |
| `control.repeat`     | 重复次数           | 入口/前置条件源码核对；未执行                    |
| `control.while`      | 条件循环           | 入口/前置条件源码核对；未执行                    |
| `control.do_while`   | 先执行后判断       | 入口/前置条件源码核对；未执行                    |
| `control.until`      | 直到满足条件       | 编辑与区域切换实测；F-WF-03/04；未执行该控制语义 |
| `control.parallel`   | 并行执行           | 入口/前置条件源码核对；未执行                    |
| `control.try`        | 异常处理           | 入口/前置条件源码核对；未执行                    |
| `control.group`      | 步骤组             | 编辑与区域切换实测；F-WF-03/04；未执行该控制语义 |
| `control.fail`       | 主动失败           | 入口/前置条件源码核对；未执行                    |
| `control.return`     | 返回调用方         | 入口/前置条件源码核对；未执行                    |
| `dataset`            | 数据集             | 入口/前置条件源码核对；未执行                    |
| `sql`                | 只读 SQL           | 只读白名单合同保留；未发数据库命令               |
| `redis`              | Redis 读取         | 只读白名单合同保留；未发数据库命令               |
| `subflow`            | 子流程             | 入口/前置条件源码核对；未执行                    |
| `for_each`           | ForEach            | 旧类型独立保留，不自动迁移；执行待验证           |

所有节点共性摘要问题见F-WF-01；区域可视化覆盖见F-WF-02；本轮没有宣称28类运行全部通过。

### 5.2 原始80项验收映射

状态是本轮审查证据，不是改写原矩阵的通过勾选。原始矩阵在交接包templates/acceptance-matrix.csv；下表保留每个ID，无遗漏。

| ID     | 原检查项             | 本轮状态                       | 证据/缺口与后续范围                                                      |
| ------ | -------------------- | ------------------------------ | ------------------------------------------------------------------------ |
| V5-001 | 主工作区             | 局部视觉核对                   | 1440/1280实页和源码浅色主题；未穷举系统深色、全部工作区。                |
| V5-002 | 主图一致性           | 存在设计差距                   | F-WF-01/F-WF-02/F-WF-03；未做全站逐像素签收。                            |
| V5-003 | 全局导航             | 入口映射核对                   | 26模块逐一进入；F-UX-03对象标签重复模块导航。                            |
| V5-004 | 弹出层               | 局部核对，待穷举               | 本轮打开的套件/区域弹窗可见，所有Tooltip/Toast未逐项测。                 |
| V5-005 | 代码区               | 存在阅读差距                   | F-REP-03/F-AIC-01/F-MCP-02；浅色已接入不等于阅读器完整。                 |
| V5-006 | 图表                 | 发现计数差距                   | F-DASH-01/F-ENG-01/F-IMP-02/F-QLT-01/F-FAB-01。                          |
| V5-007 | 无毛玻璃支持         | 源码核对，待实测               | AppearanceSettings有减少透明设置；未做禁用blur的全站截图。               |
| V5-008 | 文字对比             | 待专项测量                     | 未运行本轮全站4.5/3对比度自动测量。                                      |
| V5-009 | 长文字               | 局部核对                       | 长ID/JSON源码有换行，全部长错误/参数/URL场景未覆盖。                     |
| V5-010 | 响应式               | 局部核对，存在布局差距         | F-API-03；1440×900、1280×900及390px样本，未替代1280×800完整验收。        |
| V5-011 | 节点数量             | 28类映射核对完成               | node-registry与设计逐项对应；不表示28类都执行通过。                      |
| V5-012 | 旧节点兼容           | 源码核对，待执行               | condition与for_each独立保留；未导入旧版本逐个运行。                      |
| V5-013 | 真实端口             | 源码核对，待穷举               | 真实端口/校验沿用当前定义，未测试全部非法连接。                          |
| V5-014 | 拖放添加             | 局部实测                       | until/group添加与区域步骤操作；键盘拖放组合未穷举。                      |
| V5-015 | 复制粘贴             | 已有实现，待本轮专项           | 复制/粘贴引用和跨选择集未在本轮执行。                                    |
| V5-016 | 撤销重做             | 已有实现，待本轮专项           | 主图撤销重做存在，全部操作栈未执行。                                     |
| V5-017 | 连线操作             | 已有实现，待本轮专项           | 插入/重连/非法连接守卫未穷举。                                           |
| V5-018 | 自动布局             | 源码核对，待本轮专项           | 布局为显式操作；主题切换坐标比较未执行。                                 |
| V5-019 | 节点apply            | 局部核对                       | 主编辑会话存在；嵌套JSON应用层级见F-WF-04。                              |
| V5-020 | 未应用切节点         | 实测不符合                     | F-WF-04：嵌套group未应用JSON切步骤丢失。                                 |
| V5-021 | 保存成功             | 局部链路实测                   | 合成流程保存并发布v1；并非所有编辑表单都测。                             |
| V5-022 | 保存失败             | 待故障注入                     | 未注入真实保存超时/断网；不可复用历史绿灯。                              |
| V5-023 | 保存竞态             | 待竞态专项                     | 本轮未执行r12/r13保存晚回包场景。                                        |
| V5-024 | 关tab/切项目         | 存在输入保护差距               | F-WF-04/F-CASE-02/F-AIC-02；主工作流关tab保护已有。                      |
| V5-025 | session隔离          | 源码核对，待多身份             | 现有user/project隔离；未切多个真实用户验证全部缓存。                     |
| V5-026 | 快捷键上下文         | 源码核对，待键盘专项           | 未穷举输入框/代码/弹窗快捷键。                                           |
| V5-027 | 数据来源             | 部分实现                       | 主图有来源关系；F-REP-02冻结断言来源链不足。                             |
| V5-028 | 无法解析引用         | 源码核对                       | 未知引用不可猜；复杂表达式全种类未实测。                                 |
| V5-029 | 依赖线               | 待专项                         | 未比较依赖线开关前后的执行edges集合。                                    |
| V5-030 | if/switch            | 源码核对，待执行               | if/switch真实条件/default/error路径未执行。                              |
| V5-031 | foreach/repeat       | 源码核对，待执行               | foreach/repeat所有作用域和嵌套执行未测。                                 |
| V5-032 | while/do-while/until | 编辑局部实测，执行待测         | until编辑有证据；while/do-while/until执行语义未穷举。                    |
| V5-033 | 循环上限             | 源码核对，待执行               | 按当前ConditionLoopPolicy边界；不凭概念图新增耗尽策略。                  |
| V5-034 | parallel             | 源码核对，待执行               | parallel join和一支失败实际执行未测。                                    |
| V5-035 | try/return/fail      | 源码核对，待执行               | try/return/fail未逐类执行。                                              |
| V5-036 | SQL/Redis            | 源码守卫核对，待实际命令       | 未执行SQL/Redis写入尝试；不放宽白名单。                                  |
| V5-037 | 运行对象             | 合成运行实测                   | case v1→workflow v1→environment→真实mock health执行成功。                |
| V5-038 | 历史冻结             | 冻结对象局部核对               | 报告显示v1快照；未覆盖所有草稿变更后历史对比。                           |
| V5-039 | 节点证据             | 局部实测且有差距               | F-REP-01默认节点切换不一致；显式node/attempt可转发。                     |
| V5-040 | 循环证据             | 源码核对，待复杂运行           | 迭代/嵌套item实际证据未测。                                              |
| V5-041 | 并行证据             | 源码核对，待复杂运行           | branch/subflow多路径实际证据未测。                                       |
| V5-042 | 选择竞态             | 发现相关竞态缺口               | F-PROTO-01源代码有串结果风险；报告全部晚回包场景未执行。                 |
| V5-043 | HTTP与断言           | 实测界面/有效规则不一致        | F-API-01：UI预期201但实际采用保存200规则；不等于引擎忽略已提交失败断言。 |
| V5-044 | 缺字段               | 局部核对且有计数差距           | 报告缺单位标未提供；部分统计见F-ENG-01/F-IMP-02。                        |
| V5-045 | 重跑资格             | 源码核对，待权限专项           | 重跑资格/低权限拒绝未本轮穷举。                                          |
| V5-046 | 只读回看             | 局部实测                       | 打开合成报告未触发新执行；全类型证据回看未穷举。                         |
| V5-047 | 网络中断             | 待网络故障专项                 | 搜索503已注入，但不能代替运行中断网/恢复验收。                           |
| V5-048 | 新运行               | 待重跑专项                     | 本轮一个case执行；重放/重试新run验收未执行。                             |
| V5-049 | 继承头               | 源码核对，待组合发送           | 继承头/覆盖/启用规则存在，未执行全部组合。                               |
| V5-050 | 重复参数             | 实现与源码核对                 | 重复键行合同已保留；本轮未穷举所有保存/导入往返。                        |
| V5-051 | 禁用参数             | 实现与源码核对                 | enabled参数存在，组合发送未逐项执行。                                    |
| V5-052 | 文件引用             | 待附件场景                     | 文件库/引用实现存在，未上传真实文件验证全部行为。                        |
| V5-053 | 认证                 | 有交互差距，策略待专项         | F-API-05；严格按AGENTS的ON/OFF现行策略，不能把旧演示遮罩当默认要求。     |
| V5-054 | 导入                 | 已有实现，待本轮导入           | 导入预览/冲突合并存在，未重跑完整导入矩阵。                              |
| V5-055 | 版本冲突             | 已有实现，待竞态专项           | 版本冲突处理存在，未本轮制造并发覆盖。                                   |
| V5-056 | 最终目标             | 局部实测＋源码                 | 合成请求确实到mock-target；F-TGT-02候选影响预览不足，多Variant未执行。   |
| V5-057 | 用例发布             | 合成用例实测                   | 固定workflow v1执行和报告关联；套件全部组合待测。                        |
| V5-058 | 批量范围             | 部分实现，范围有缺口           | 接口批量移组已存在；F-API-04导出缺范围，用例跨页能力源码核对。           |
| V5-059 | 失败筛选             | 源码核对，待失败样本           | 失败节点过滤存在；本次成功运行不足以验证过滤结果。                       |
| V5-060 | 统计分母             | 确认多处口径差距               | F-DASH-01/F-CT-01/F-ENG-01/F-IMP-02/F-QLT-01/F-FAB-01。                  |
| V5-061 | 导出                 | 源码核对，待全部导出           | 冻结HTML/授权附件已有；F-API-04导出范围不足，未穷举递归边界。            |
| V5-062 | 移动报告             | 390px局部实测                  | 合成报告与组织页无整页横向溢出；长失败JSON/完整定位交互仍待测。          |
| V5-063 | 环境语义             | 语义核对完成                   | 环境实验室确为签名模板/实例/TTL；API变量环境分开。                       |
| V5-064 | 环境安全             | 源码边界核对                   | 受控manifest；未执行Provision/清理，不宣称运行验收通过。                 |
| V5-065 | 性能默认             | 关闭态核对                     | 未自动压测；F-PERF-01配置交互不足。                                      |
| V5-066 | 门禁缺证据           | 源码核对，未生成判断           | 缺证据应BLOCK；F-REL-01/02收集环节有差距，不据此声称算法假PASS。         |
| V5-067 | 门禁动作             | 源码/页面语义核对              | 明确判断不触发生产部署；未创建真实决策。                                 |
| V5-068 | AI提案               | 源码核对，审核信息不足         | F-REG-01/F-AIC-01/02；未执行AI Review/Apply。                            |
| V5-069 | MCP高风险            | 源码核对，待真实提案           | 高风险批准守卫存在；F-MCP-01/02审核展示不足。                            |
| V5-070 | 组织权限             | 源码核对，发现项目证据权限错配 | F-REL-01；26入口只用管理员检查，多角色验收待做。                         |
| V5-071 | 一次性秘密           | 源码核对，未签发               | 一次性Token/Secret输入不因审核读取；未轮换或签发真实令牌。               |
| V5-072 | 未开放能力           | 关闭态实测，合同有差距         | 插件安装禁用正确；F-AIC-03历史读取/开关不一致。                          |
| V5-073 | 特殊状态             | 局部实测                       | 隔离预览正常登录；空/关闭/搜索错误有证据，强制改密/会话/404未全测。      |
| V5-074 | 键盘焦点             | 局部核对，待键盘专项           | 导航有焦点恢复源码；所有模态/区域检查器未全键盘走查。                    |
| V5-075 | 减弱动效             | 源码核对，待系统设置           | use-reduced-motion存在；未在本轮改系统设置重做全部截图。                 |
| V5-076 | 图规模               | 未执行                         | 不宣称大图性能提升；需同环境前后基线测量。                               |
| V5-077 | 工作区保护           | 本轮工作区核对                 | 原checkout不改；审计分支只新增两份MD，业务代码不变。                     |
| V5-078 | 当前版本             | 本轮依赖核对                   | 不改package/lockfile/工具链；不复用旧CI绿灯。                            |
| V5-079 | 真实测试             | 证据边界已记录                 | 7文件97测试通过；26入口核对≠80项验收全部通过。                           |
| V5-080 | 回滚                 | 本轮无业务回滚操作             | 文档可回退；未执行主题/业务挂接回滚演练，不清数据库或草稿。              |

## 6. 本轮实际验证记录

### 6.1 环境、合成夹具与副作用范围

启动Docker后复用现有隔离Compose容器，没有重建原3000环境。确认后端ready以及database/storage/redis依赖可用；预览前端dist与工作树绑定，源码按本轮基线核对。

| 夹具         | 标识/范围                                                                                                             |
| ------------ | --------------------------------------------------------------------------------------------------------------------- |
| 项目         | 设计完整度审计20261019；`7509312b-445e-4f6f-ae90-ccffe9b8d2a2`                                                        |
| API          | 审计健康检查；GET /health；`e6eca458-ca8e-4a50-bf64-5ac31f8778aa`                                                     |
| 环境         | 审计合成环境，仅指向隔离mock-target                                                                                   |
| 流程/用例    | 审计合成流程v1、审计合成用例v1，固定版本关联                                                                          |
| 真实执行     | `d946de58-372d-453a-9b47-e5549ebd8e20`；case→workflow→report，结果通过                                                |
| 流程本地输入 | 用于复现until/group编辑保护；未保存到服务器发布版                                                                     |
| 未执行动作   | 未调用外部AI/Broker/数据库/生产目标，未Provision/压测、发送通知、签发或轮换真实令牌/密钥，未Review/Apply/批准业务提案 |

合成API发送只访问本地mock health；测试数据与真实项目/秘密隔离。只读截图并不证明后端算法通过。

### 6.2 现有定向回归

实际命令：

```sh
make test-frontend-targeted TARGETS='["src/pages/ApiConsolePage.test.tsx","src/flow/WorkflowControlFields.test.tsx","src/pages/ProtocolWorkbenchPage.test.tsx","src/pages/ChangeRegressionPage.test.tsx","src/pages/ReleaseGatePage.test.tsx","src/features/navigation/WorkspaceObjectTabs.test.tsx","src/features/search/GlobalSearch.test.tsx"]'
```

实际结果：7个文件通过、97条测试通过，耗时19.65秒。完整日志：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/targeted-baseline.log`。

这些测试与本轮反例同时成立：它们未覆盖本次的保存断言/快捷预期冲突、嵌套原始JSON切换、真实多角色Runner目录及错误空态等组合。修改时需要补公开行为回归，不能通过削弱原断言或仅更新快照消除缺陷。

### 6.3 浏览器/视觉记录

- API：预期201而实际200仍通过的反例；1440×900和1280×900几何检查，文档高度938；目录和环境入口。
- 编排：until/group嵌套配置、区域工具栏、合法JSON未应用切换丢失。
- 用例：前置资源缺项、套件关闭输入丢失；真实直接运行到编排/报告。
- 报告：同run默认选中变化、冻结v1与合成环境；390px文档宽375，无整页横向溢出。长失败和复杂实例仍未测。
- 其他模块：逐入口检查空态/关闭态/相关源码；平台切插件保留错误能力详情；组织390px无整页横向溢出。
- 全局搜索：浏览器503注入后显示假空列表；已撤销拦截。没有改服务器搜索实现。

完整本地证据目录：`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019`。MD里的复核条件和固定源码链接是主要可移交证据；上述忽略目录不随Git提交或复制MD自动携带。

### 6.4 尚未执行

- make check及全量覆盖率；本轮没有业务代码变更，未为文档重新跑全部后端和发布形态。
- 完整Compose Playwright套件、所有28类节点真实执行、所有低权限/组织角色、长任务晚回包/断网/保存竞态。
- Windows Standalone、历史迁移升级、容量/大图/高并发性能，真实KMS、Runner故障转移、外部协议/AI/Broker。
- 最新文档提交的远程Required Gate、GitHub合并、合并后main CI和部署/生产验收。本轮不声称已提交合并。

### 6.5 文档质量检查

两份MD检查格式、内部链接/锚点、固定commit源码路径和行号、问题编号一对一、26模块覆盖、原始80项验收顺序和本地补充证据文件。实施项依赖也检查引用和循环；这些文档检查不改变业务验收状态。

## 7. 已解决与不应扩大的结论

| 既往疑问                  | 本轮结论                                                                                                  |
| ------------------------- | --------------------------------------------------------------------------------------------------------- |
| 接口没有分组/只能逐个移组 | 当前main已有分组与跨页批量移组、向分组批量添加；不要重新报缺失。目录摘要/导出范围仍有差距                 |
| 环境管理放哪里            | 已选择并实现页面顶栏入口，管理与发送环境分离；后续保持这一决策                                            |
| 节点查看详情不能点        | 已合入的节点配置入口存在；本轮重点是摘要、区域编辑完整度和嵌套输入保护                                    |
| 用例只是占位页            | 已有版本/套件/导入导出/历史/直接运行；本轮反例仍表明交互未全面达标                                        |
| 报告与编排完全没关联      | 同一真实run已关联；显式node/attempt能转发，缺口是自动默认选择与来源链                                     |
| 每节点不同部署地址        | 流程共享environment_id，节点可选Service/Endpoint Variant，能表达多模块地址；独立完整节点环境是N类合同扩展 |
| 实验室没有实时健康/稳定性 | 已明确未提供相应采样/判定，不应填演示数值；若要新增需独立方案                                             |
| 所有概念图按钮都要开放    | 插件安装、任意脚本/Compose、自动执行/发布等不得由UI直接扩权                                               |

## 8. 修复交付要求

按 [详细修改方案](remediation-plan.md) 的R0→R1→R2/R3/R4实施。每项完成需同时提供：实际交互/逻辑变更、公开行为测试、对应真实或条件环境证据、基线/commit，以及仍未测试的边界。

不建议按73项做一个巨大PR。先处理5项P1，再完成接口/编排/用例/报告的核心任务闭环；其他模块按依赖拆分。任一模块的“实现完成、局部测试通过、最新提交门禁通过、合并、合并后CI、真实环境验收”分别记录，不能用其中一项代替其他项。
