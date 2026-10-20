# FlowTest UI v5 详细修改与验收方案

对应审计：FT-UIV5-20261019；版本：1.0；编制日期：2026-10-20。

**本方案逐项对应审计报告的73个问题/设计差距，覆盖26个模块和3个全局问题。目标是把现有能力接成可理解、可维护、可追踪的真实交互。本文为待实施方案，不表示业务修复已完成。**

审计依据、实际反例和未实测范围见 [完整审计报告](complete-audit.md)。源码基线：`420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4`；若开发时main已更新，先逐项复核而不覆盖其他改动。

## 1. 目标与不变量

接口/流程/用例/报告的核心任务应连续：查找对象→理解当前版本/状态→编辑并明确应用/保存→有权执行→进入新运行→定位冻结证据→返回准确对象。辅助模块也必须有自己的目录/详情/错误/关闭态和可行动入口，不能靠统一换色或简单套Card宣称完成。

本轮方案遵守以下不变量：

- 继续使用当前React/AntD/XYFlow/查询与状态栈；不为UI整体升级依赖或另建静态演示。
- HTTP router只适配；业务授权/解析/筛选放服务或领域，基础设施通过类型化接口接入。领域/引擎不依赖FastAPI/Celery/ORM。
- 原28类节点、固定版本、真实执行端口/控制语义保持；区域仍按引擎允许结构，未支持的任意分支/新节点单列需求。
- Workflow共享environment_id，节点按现有Service/Endpoint Variant解析；目标预览复用RequestTargetResolver，不手工拼接猜结果。
- 未应用输入、图草稿、已保存/发布版本、当前执行和历史冻结证据分别管理。布局偏好不进入执行JSON。
- 权限和租户/项目边界不因方便而放宽；只写秘密仍只写、加密保存，一次性令牌仍只显示一次。
- 不扩大日志/采集。默认OFF不扫描/代换/遮蔽已授权值；已授权诊断开启时按现行安装/请求级项目ON/OFF策略处理。
- AI/MCP只产生允许的草稿，保留人工Review/Apply/高风险批准；UI跳转、预览、阅读不自动触发发布、执行、压测或外部消息。
- 真实字段不足显示未提供/未解析/未评估，不能补示例分数、实时健康、稳定性或假PASS。

## 2. 实施批次与依赖

| 批次 | 范围/目标                                                                 | 项数 | 先决条件与交付                                                |
| ---- | ------------------------------------------------------------------------- | ---: | ------------------------------------------------------------- |
| R0   | 5项P1：有效断言、嵌套输入、协议响应身份、缺失测试审核、项目Runner证据权限 |    5 | 先补能揭示反例的行为测试，再修复；相关鉴权/读取扩展需集成验证 |
| R1   | 接口、编排、用例、报告其余问题＋全局搜索/对象标签                         |   19 | 依赖R0正确性；形成完整核心工作闭环和1440/1280/390适配证据     |
| R2   | 服务目录、请求目标、协议、项目、数据、契约、测试工程、任务、环境/性能     |   24 | 按稳定定位/完整目录/现有配置合同推进，可按模块独立PR          |
| R3   | 首页、影响、变更回归、质量、发布决策                                      |   10 | 使用真实聚合和冻结来源；依赖R0项目证据及R1运行定位            |
| R4   | AI/Context/MCP/组织/执行面/平台                                           |   15 | 关闭态/角色/历史读取有明确合同，真实外部系统另行验收          |

R2—R4按组件和API依赖择序，不需要串行等待整个上一批全部完成；同一文件/共享状态修改避免并发冲突。建议以“一个完整任务链＋其验证”拆PR，结构性提取与特性改动尽量分开，不将73项塞入一个难以复核的大改。

### 2.1 优先交付清单

| 顺序 | 项目                           | 首个可复核结果                                                               |
| ---- | ------------------------------ | ---------------------------------------------------------------------------- |
| 1    | F-API-01、F-WF-04              | 两个本轮浏览器反例转为可重复通过的行为测试与实际页面证据                     |
| 2    | F-PROTO-01、F-REG-01、F-REL-01 | 模拟慢响应身份测试；可审阅缺失提案；Owner/Editor本项目Runner读取与跨项目拒绝 |
| 3    | F-REP-01、F-UX-01/02/03        | 同run同node往返、搜索错误可解释、真实对象tab恢复                             |
| 4    | 核心API/编排/用例/报告其余项   | 实际目录/表单/证据闭环及桌面/移动截图                                        |
| 5    | 辅助模块逐项任务               | 目录完整、状态真实、可定位、复杂配置可维护                                   |

### 2.2 共享能力的边界

| 需要统一的行为       | 已出现位置                         | 建议做法                                                                            |
| -------------------- | ---------------------------------- | ----------------------------------------------------------------------------------- |
| 冻结对象/证据locator | 报告、编排、计划、回归、门禁、质量 | 先完善既有execution-navigation；对其他对象建立有类型locator及消费者，保留旧链接兼容 |
| 页外选中与完整目录   | 服务/协议/契约/任务/风险/模板      | 分页、搜索、按ID读取三者分离；目录数据不作为选中对象全集                            |
| 未提交编辑保护       | 主节点、区域、用例/套件、审核弹窗  | 在已有DraftSession/表单保护基础上先做特征测试，再抽稳定会话适配；不要建全局万能字典 |
| 读取状态             | 搜索、治理、能力页、证据选择       | 统一Loading/Error/Forbidden/Disabled/Empty/Missing，但保留每个任务的下一步解释      |
| 浅色证据阅读         | API、报告、回归、审核/能力         | 复用已有阅读器，限制体积与懒加载；不能把原始值额外送日志                            |
| 统计范围             | Dashboard/Quality/Impact/Fabric    | 类型明确的count/scope/period/available；未提供和0不同                               |

只有同一稳定行为在至少三处出现才抽共享；上述共性已有多个实例，但各模块授权和执行合同仍分开。先用行为特征测试保护，再提取，不以重构为由扩大范围。

## 3. 逐模块详细修改项

每项均给出目标交互、改动步骤、API/数据边界和可验收结果；本节所有勾选项当前均为待实施。源码落点链接指向审计基线，开发时需与当前main复核。复杂度为相对改动风险（小/中/大），不是工期承诺。

<a id="m01"></a>

### M01 · 质量总览

**目标任务与版式**：A 风险总览；项目/时间/分母明确的风险摘要、优先问题和真实证据入口；不能把当前样本当全量。

**入口**：`/projects/:projectId/dashboard`。本模块实际已有功能见 [审计章节](complete-audit.md#m01)，不得以新页面替掉其原处理链。

<a id="f-dash-01"></a>

#### F-DASH-01 · Flaky摘要将首100条页内数量作为资产总数

**优先级/批次/复杂度**：P2 / R3 / 中。对应 [审计证据](complete-audit.md#f-dash-01)。

**目标交互**：首页Flaky/隔离指标代表明确的项目范围。

**改动落点**：[frontend/src/pages/DashboardPage.tsx:239-290](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DashboardPage.tsx#L239)；[frontend/src/features/dashboard/use-dashboard.ts:55-59](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/dashboard/use-dashboard.ts#L55)；[frontend/src/features/quality/quality-service.ts:122-131](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/quality/quality-service.ts#L122)。

**实施步骤**：

1. 短期将样本统计标已载入前N项，失败/关闭/未查询显示未提供。
2. 新增受权聚合读取flaky_total/quarantined_total与时间范围；首页队列保留样本数量说明。
3. 摘要和跳转使用一致筛选，不把Page.total误当满足某个条件的数量。

**API、模型与兼容**：需要受权只读聚合；不为统计而抓取所有记录或修改Flaky算法。

**验收与新增行为测试**：

- [ ] 总数150而首100条只有10项隔离时，显示真实全量或明确样本范围。
- [ ] 关闭/失败不显示0个风险。
- [ ] 项目与时间切换后旧数据不覆盖新摘要。

<a id="f-dash-02"></a>

#### F-DASH-02 · Flaky问题入口只打开质量中心，没有定位具体资产

**优先级/批次/复杂度**：P2 / R3 / 中。对应 [审计证据](complete-audit.md#f-dash-02)。

**目标交互**：首页优先问题打开对应资产和质量记录。

**改动落点**：[frontend/src/features/dashboard/priority-issues.ts:124-139](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/dashboard/priority-issues.ts#L124)；[frontend/src/pages/QualityCenterPage.tsx:36-82](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.tsx#L36)。

**实施步骤**：

1. priority-issues为Flaky问题生成带record/target/version的精确locator。
2. 质量中心补取页外记录并高亮选中，必要时打开只读详情。
3. 对象失效或无权限明确提示，保留返回首页上下文。

**API、模型与兼容**：复用已有受权资源查询；若只有分页列表，补按ID读取或按目标精确过滤。

**依赖**：[F-QLT-02](#f-qlt-02)。

**验收与新增行为测试**：

- [ ] 打开第101项Flaky问题也能定位。
- [ ] 同资产不同版本可区分。
- [ ] 跨项目/失效记录不自动落在另一条记录。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/DashboardPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DashboardPage.test.tsx)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m02"></a>

### M02 · 接口管理

**目标任务与版式**：B 请求工作台；集合目录—请求—响应/断言的连续任务；版本、发送环境和最终目标清楚；导入、批量范围与认证仍可用。

**入口**：`/projects/:projectId/apis`。本模块实际已有功能见 [审计章节](complete-audit.md#m02)，不得以新页面替掉其原处理链。

<a id="f-api-01"></a>

#### F-API-01 · 预期状态码在已有断言时被静默忽略

**优先级/批次/复杂度**：P1 / R0 / 中。对应 [审计证据](complete-audit.md#f-api-01)。

**目标交互**：界面显示的校验规则与本次实际提交规则使用同一个来源。

**改动落点**：[frontend/src/features/api-console/api-service.ts:383-406](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/api-service.ts#L383)；[frontend/src/pages/ApiConsolePage.tsx:216-230](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.tsx#L216)。

**实施步骤**：

1. 提取纯函数计算effectiveAssertions，响应区摘要和executeApi均使用其结果。
2. 已有保存断言时移除可编辑的独立预期数字，显示按保存断言校验；有状态码断言则显示其真实操作符和值，无状态码规则则明确未配置。
3. 仅在保存断言为空时保留快捷状态码输入；需修改已有规则时进入断言页并保存新版本。
4. 执行详情展示冻结生效规则，重看旧执行不跟随当前表单。

**API、模型与兼容**：沿用现有assertions执行输入，不修改后端断言优先级或旧版本；预期状态不单独持久化为第二份真值。

**验收与新增行为测试**：

- [ ] 保存status=200时不能把未生效201显示为有效预期；修改并保存v2=201后健康接口200应断言失败。
- [ ] 空断言时快捷201必须进入实际请求并产生失败结果。
- [ ] 仅Body断言、多状态规则、旧版回看均显示真实规则，HTTP状态与断言状态分开。

<a id="f-api-02"></a>

#### F-API-02 · 主接口目录缺方法与路径摘要

**优先级/批次/复杂度**：P2 / R1 / 小。对应 [审计证据](complete-audit.md#f-api-02)。

**目标交互**：目录一眼可区分同名接口和请求目标。

**改动落点**：[frontend/src/pages/ApiConsolePage.tsx:638-731](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.tsx#L638)；[frontend/src/features/api-console/api-service.ts:48-73](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/api-service.ts#L48)。

**实施步骤**：

1. 使用已有目录method/path字段渲染方法标识、接口名和第二行路径。
2. 保留复选框/版本/重命名，操作图标不抢主点击区域。
3. 长路径可展开或复制，目录行选中和批量选中保持独立。

**API、模型与兼容**：无API变更，复用ApiDirectoryEntry。

**验收与新增行为测试**：

- [ ] 同名GET/POST显示可区分的方法与路径。
- [ ] 长中文名、无路径和窄目录不遮挡选择/重命名。
- [ ] 筛选、分页、移组后原选择范围不变。

<a id="f-api-03"></a>

#### F-API-03 · 请求响应区不可调整，桌面首屏出现固定最小高度溢出

**优先级/批次/复杂度**：P2 / R1 / 大。对应 [审计证据](complete-audit.md#f-api-03)。

**目标交互**：桌面可同时阅读请求和响应，布局按用户调整并恢复。

**改动落点**：[frontend/src/styles.css:236-341](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/styles.css#L236)；[frontend/src/styles.css:2161-2166](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/styles.css#L2161)。

**实施步骤**：

1. 建立目录/请求/响应的可调整工作区；宽屏默认请求与响应并列，较窄桌面可折叠响应或切上下分栏。
2. 以容器剩余高度分配空间，去除互相叠加的420/240固定最小高度。
3. 以用户/项目/工作区键保存分栏比例和折叠状态；存储失败仍可编辑。
4. 390以请求/证据切换阅读为主，避免三列缩小和整页双滚动。

**API、模型与兼容**：纯布局偏好，不进入接口版本、执行输入或全局环境。

**验收与新增行为测试**：

- [ ] 1440×900与1280×800截图可找到请求编辑和有效响应区域，无操作被裁切。
- [ ] 分栏拖动、键盘调整、刷新恢复及坏偏好回退可用。
- [ ] 切换布局不重发请求、不清草稿、不改变断言与环境。

<a id="f-api-04"></a>

#### F-API-04 · 导出只支持整个项目，缺分组或选中接口范围说明

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-api-04)。

**目标交互**：导出对象范围和当前选择一致且事前可见。

**改动落点**：[frontend/src/pages/ApiConsolePage.tsx:510-530](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.tsx#L510)；[frontend/src/features/api-console/api-service.ts:285-297](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/api-service.ts#L285)。

**实施步骤**：

1. 打开导出范围面板，明确整个项目/当前分组/已选接口及数量。
2. 已有后端不支持范围时只开放全项目并明确不受当前筛选影响，不能假装支持局部导出。
3. 扩展受权导出合同后再开放选择范围；复用导入冲突/包版本约束。

**API、模型与兼容**：现有export仅project+format；分组/所选导出需显式ids或受权过滤参数，不用客户端抓全量拼包。

**验收与新增行为测试**：

- [ ] 筛选或跨页选择后导出范围说明正确。
- [ ] 导出所选只含选择集合，拒绝跨项目ID，空选择不可提交。
- [ ] 旧全项目导出和文件名/错误处理保持可用。

<a id="f-api-05"></a>

#### F-API-05 · 认证配置仍依赖通用键值与技术键名

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-api-05)。

**目标交互**：认证按类型填写，秘密和适用位置清楚。

**改动落点**：[frontend/src/features/api-console/APIWorkbench.tsx:584-630](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/APIWorkbench.tsx#L584)。

**实施步骤**：

1. 按none/Bearer/Basic/API Key显示专用字段和必要验证。
2. 表单与现有键值结构双向适配，保留已有资产兼容；未知字段放高级区。
3. 显示继承/覆盖与写入方式，按当前ON/OFF策略提供既有授权范围内的预览/复制。
4. 临时输入不写日志；只写Secret保持引用，不提供读取。

**API、模型与兼容**：优先前端适配现有auth合同；不引入新的OAuth流程或秘密读取API。

**验收与新增行为测试**：

- [ ] 各认证类型保存/重载/发送往返不丢字段。
- [ ] 缺用户名/位置/键名在对应字段提示，不能默默生成错误请求。
- [ ] ON/OFF两种安装/项目策略和只写引用遵守现有行为。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ApiConsolePage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ApiConsolePage.test.tsx)
- [frontend/src/features/api-console/APIWorkbench.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/APIWorkbench.test.tsx)
- [frontend/src/features/api-console/ApiFolderActions.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/ApiFolderActions.test.tsx)
- [frontend/src/features/api-console/EnvironmentManager.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/EnvironmentManager.test.tsx)
- [backend/tests/test_execution_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_execution_api.py)
- [backend/tests/test_api_assets_domain.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_api_assets_domain.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m03"></a>

### M03 · 服务目录

**目标任务与版式**：C 目录/详情；服务目录完整可搜索，选择服务后查看契约/依赖摘要，并准确进入该服务的契约和影响上下文。

**入口**：`/projects/:projectId/services`。本模块实际已有功能见 [审计章节](complete-audit.md#m03)，不得以新页面替掉其原处理链。

<a id="f-svc-01"></a>

#### F-SVC-01 · 搜索分页仅覆盖首100条服务，缺服务端目录分页

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-svc-01)。

**目标交互**：服务目录的搜索、分页与总数覆盖全部服务。

**改动落点**：[frontend/src/features/services/use-service-catalog.ts:32-36](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/services/use-service-catalog.ts#L32)；[frontend/src/features/contracts/contract-hub-service.ts:105-110](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/contract-hub-service.ts#L105)；[frontend/src/pages/ServiceCatalogPage.tsx:26-35,195-200,394-403](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.tsx#L26)。

**实施步骤**：

1. useServiceCatalog把search/page/pageSize传到服务端，保留当前选中ID独立于页。
2. 目录表格绑定Page.total，切搜索重置页码。
3. 页外深链接单独按ID受权读取，不退回当前页首项。

**API、模型与兼容**：listContractServices支持分页，搜索若未提供则扩展受权读取参数与仓储过滤；不一次取全量。

**验收与新增行为测试**：

- [ ] 101条以上第101条可搜索和打开。
- [ ] 空结果、失败、无权限各有不同反馈。
- [ ] 搜索与翻页后详情仍对应选中服务。

<a id="f-svc-02"></a>

#### F-SVC-02 · 契约和影响链接携带的服务定位参数未被目标页消费

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-svc-02)。

**目标交互**：服务到契约/影响分析的跨模块入口使用被消费的参数。

**改动落点**：[frontend/src/pages/ServiceCatalogPage.tsx:246-258](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.tsx#L246)；[frontend/src/pages/ContractHubPage.tsx:64-77](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.tsx#L64)；[frontend/src/features/impact/use-impact-analysis.ts:35-55](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/impact/use-impact-analysis.ts#L35)。

**实施步骤**：

1. 确定共同的contractServiceId locator，移除无消费者的focus=contract_service前缀约定。
2. 契约页按该ID选择Provider并补取页外对象；影响页按服务展示关联分析/显式说明无关联。
3. 统一导航构造器和旧链接兼容解析，不把合同服务误当请求目标Service。

**API、模型与兼容**：关系不存在时显示未建立映射；不能用相似名称自动建立Service关联。必要只读查询需要明确两种服务ID。

**验收与新增行为测试**：

- [ ] 点击服务A后目标页展示A，刷新和前后退一致。
- [ ] 页外服务、无Pact/无影响运行给准确空态。
- [ ] 不存在/无权限ID不会选成B。

<a id="f-svc-03"></a>

#### F-SVC-03 · 服务目录仍为登记表格，缺设计中的选中服务详情工作区

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-svc-03)。

**目标交互**：服务目录具备就地详情和清楚的后续操作。

**改动落点**：[frontend/src/pages/ServiceCatalogPage.tsx:177-264](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.tsx#L177)。

**实施步骤**：

1. 改为可搜索目录/列表＋服务详情主从布局，保存选中ID。
2. 详情列出身份/描述、已知契约版本、兼容与依赖摘要、实际证据入口。
3. 信息不足标未提供并提供配置路径，移动端以抽屉或详情页承载。
4. 登记服务表单作为独立动作，避免创建表单长期挤占阅读区。

**API、模型与兼容**：先用已有ServiceCatalogEntry/summary/graph；新聚合字段必须有真实只读来源。

**依赖**：[F-SVC-01](#f-svc-01)、[F-SVC-02](#f-svc-02)。

**验收与新增行为测试**：

- [ ] 选择服务可直接理解其契约与当前关联。
- [ ] 跳转带精确服务ID且可返回。
- [ ] 关闭态、长名称、无关联及Viewer不出现可写错觉。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ServiceCatalogPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ServiceCatalogPage.test.tsx)
- [backend/tests/test_contract_hub.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_contract_hub.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m04"></a>

### M04 · 请求目标

**目标任务与版式**：G 分组表单＋影响预览；Service→环境 Endpoint Variant→API默认绑定→最终目标→下游影响可连续阅读；先预览再保存。

**入口**：`/projects/:projectId/request-targets`。本模块实际已有功能见 [审计章节](complete-audit.md#m04)，不得以新页面替掉其原处理链。

<a id="f-tgt-01"></a>

#### F-TGT-01 · 配置页仍为高密度技术表格和英文/JSON表单

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-tgt-01)。

**目标交互**：请求目标按用户任务组织，减少同时理解技术字段的负担。

**改动落点**：[frontend/src/pages/RequestTargetsPage.tsx:392-595,777-868](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.tsx#L392)。

**实施步骤**：

1. 以环境/Service目录选择驱动Endpoint详情，将14列拆为摘要表和分组详情。
2. 常用字段先展示名称/地址/Variant/默认状态，连接/TLS/认证等放高级分组。
3. 将稳定映射表改为受类型约束的键值编辑，保留原始结构高级入口。
4. 给出Service、Variant和默认绑定的中文关系说明。

**API、模型与兼容**：保留service-target合同、凭据引用和egress校验，不改变目标解析优先级。

**验收与新增行为测试**：

- [ ] 从服务到环境Endpoint再到API绑定无需跨多个密集表格查找。
- [ ] 固定地址/多Variant/凭据引用均可完整读写。
- [ ] 1280与390不会把整个技术表硬缩到一行。

<a id="f-tgt-02"></a>

#### F-TGT-02 · 影响预览只拼名称，丢弃已有原因和对象定位

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-tgt-02)。

**目标交互**：影响预览显示哪些对象、为何受影响、目标将如何变化。

**改动落点**：[frontend/src/pages/RequestTargetsPage.tsx:699-729,882-892](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.tsx#L699)；[frontend/src/features/service-targets/service-target-service.ts:65-78](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/service-targets/service-target-service.ts#L65)。

**实施步骤**：

1. 按对象渲染id/name/reason和准确入口，提供受影响总数与分页范围。
2. 增加受权只读的变更前/后解析预览，优先复用RequestTargetResolver计算路径。
3. 无足够上下文时显示无法计算及缺项，不用拼接URL猜结果。
4. 连通性检查保持独立显式动作，预览本身不发外部请求。

**API、模型与兼容**：已有影响DTO可先接回reason；候选配置预览需扩展只读合同，服务层验证项目、候选值与解析边界。

**验收与新增行为测试**：

- [ ] 每个API/流程影响有原因和准确目标链接。
- [ ] 预览URL与同配置实际解析一致，默认Service/Variant、非法目标和缺失映射都有测试。
- [ ] 打开/修改预览不发目标请求也不保存配置。

<a id="f-tgt-03"></a>

#### F-TGT-03 · 默认Service/API绑定直接提交，没有统一影响确认

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-tgt-03)。

**目标交互**：默认绑定和其他配置使用一致的预览/确认/保存过程。

**改动落点**：[frontend/src/pages/RequestTargetsPage.tsx:142-164,270-292,597-636](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.tsx#L142)。

**实施步骤**：

1. 默认Service下拉先写本地候选，不立即mutation。
2. 统一显示未保存与变更对比、影响摘要，确认保存后才提交。
3. 切环境/Service或离开时处理候选输入，失败保留候选并可重试。
4. 当前已生效值与候选值分别标识。

**API、模型与兼容**：沿用现有更新接口；不需要放宽授权或创建自动连通检查。

**依赖**：[F-TGT-02](#f-tgt-02)。

**验收与新增行为测试**：

- [ ] 更改下拉但取消时服务器值不变。
- [ ] 预览显示同一候选，保存成功才清dirty。
- [ ] 失败/快速切换/后台刷新不会提交或覆盖其他环境的值。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/RequestTargetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/RequestTargetsPage.test.tsx)
- [backend/tests/test_request_target_guards.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_request_target_guards.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m05"></a>

### M05 · 多协议工作台

**目标任务与版式**：B 多协议工作台；Schema/Descriptor/事件源目录、专用请求编辑、响应和契约检查；结果锁定协议/项目/资产/请求。

**入口**：`/projects/:projectId/protocols`。本模块实际已有功能见 [审计章节](complete-audit.md#m05)，不得以新页面替掉其原处理链。

<a id="f-proto-01"></a>

#### F-PROTO-01 · GraphQL/gRPC调试结果缺Schema与请求序列隔离

**优先级/批次/复杂度**：P1 / R0 / 大。对应 [审计证据](complete-audit.md#f-proto-01)。

**目标交互**：调试响应只属于其发起时的协议、资产和请求。

**改动落点**：[frontend/src/pages/ProtocolWorkbenchPage.tsx:319-369,415-446](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L319)。

**实施步骤**：

1. 为调试建立project/protocol/schemaId/requestSequence身份并冻结请求摘要。
2. 切资产清理或保留在原会话中，当前面板不继承另一资产结果。
3. 回包前校验当前身份；旧请求取消只是优化，不能代替迟到响应守卫。
4. 错误/取消/开始新调试分别更新对应会话，gRPC方法选择也随Descriptor校验。

**API、模型与兼容**：无执行后端变更，保持有界协议调用和原权限；返回结果按发起时请求身份记录。

**验收与新增行为测试**：

- [ ] 慢A回包前切B，B不显示A响应或错误。
- [ ] 同Schema快速发起两次，旧响应不覆盖新请求。
- [ ] 切项目、协议、Descriptor方法和卸载时仍无串结果；不自动重发。

<a id="f-proto-02"></a>

#### F-PROTO-02 · Schema/事件源翻页或刷新会隐式换选中对象

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-proto-02)。

**目标交互**：协议资产选择可刷新、分享和从页外恢复。

**改动落点**：[frontend/src/pages/ProtocolWorkbenchPage.tsx:92-110,724-730](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L92)；[frontend/src/features/protocols/EventProtocolWorkspace.tsx:129-155](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/protocols/EventProtocolWorkspace.tsx#L129)。

**实施步骤**：

1. URL规范化mode/schema/eventSource及必要目录页码，选中对象独立于当前页。
2. 增加按ID读取/补取并校验协议/项目，目录换页不替换已选对象。
3. 切mode时保存或明确处理该模式草稿，前后退同步。
4. 无效ID、已删除、无权限分别展示，不静默选首项。

**API、模型与兼容**：已有按ID能力优先复用；缺失的事件源/Schema只读查询需明确扩展。

**依赖**：[F-PROTO-01](#f-proto-01)。

**验收与新增行为测试**：

- [ ] 选第2页Schema后刷新仍打开同一版本。
- [ ] 事件源与Schema链接参数不混用。
- [ ] 无效链接与跨项目返回正确错误，无调试副作用。

<a id="f-proto-03"></a>

#### F-PROTO-03 · 后端支持的GraphQL Headers和gRPC Metadata没有编辑入口

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-proto-03)。

**目标交互**：GraphQL Headers和gRPC Metadata可受控配置。

**改动落点**：[frontend/src/pages/ProtocolWorkbenchPage.tsx:355-365,426-441](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L355)；[frontend/src/features/protocols/protocol-service.ts](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/protocols/protocol-service.ts)。

**实施步骤**：

1. 请求编辑器增加可启用/禁用的键值配置，明确协议允许的头和Metadata格式。
2. 调试请求提交真实字段，保留超时、TLS/mTLS与凭据引用。
3. 专用认证输入与高级字段分层，显示继承规则和发送摘要。

**API、模型与兼容**：后端已接受headers/metadata；按现有校验和项目策略传入，不允许读取Credential材料。

**依赖**：[F-PROTO-01](#f-proto-01)。

**验收与新增行为测试**：

- [ ] GraphQL认证头、重复/无效键、gRPC Metadata与禁用项发送行为正确。
- [ ] 切协议或Schema时不会把A的凭据配置误当B。
- [ ] ON/OFF策略与TLS/mTLS约束保持。

<a id="f-proto-04"></a>

#### F-PROTO-04 · Schema检查器主要是哈希/格式/数量，缺结构浏览与输入引导

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-proto-04)。

**目标交互**：Schema检查器提供真实契约浏览和输入引导。

**改动落点**：[frontend/src/pages/ProtocolWorkbenchPage.tsx:533-560,380-395,488-493](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.tsx#L533)。

**实施步骤**：

1. GraphQL按操作/类型/字段，gRPC按服务/方法/请求响应类型建立可折叠树。
2. 从schema_summary/descriptor公开结构生成字段说明和合法样例，缺字段标未提供。
3. 树与请求编辑、错误路径联动，保留源文档和哈希只读查看。
4. 复杂Schema大树按需展开，不在浏览中自动请求外部introspection/reflection。

**API、模型与兼容**：仅用已有结构；不足时增加受权、有大小边界的解析摘要API，不暴露原始秘密。

**验收与新增行为测试**：

- [ ] 字段类型/必填/方法类型来自真实契约。
- [ ] Schema损坏、缺摘要、深嵌套能解释失败。
- [ ] 选择字段不改变Schema版本，也不自动执行调试。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ProtocolWorkbenchPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProtocolWorkbenchPage.test.tsx)
- [backend/tests/test_multi_protocol.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_multi_protocol.py)
- [backend/tests/test_event_protocols.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_event_protocols.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m06"></a>

### M06 · 项目管理

**目标任务与版式**：G 治理表单；成员/角色/egress/并发速率/保留/请求级策略和可追踪审计；保留原有读取与写入权限。

**入口**：`/projects/:projectId/settings`。本模块实际已有功能见 [审计章节](complete-audit.md#m06)，不得以新页面替掉其原处理链。

<a id="f-prj-01"></a>

#### F-PRJ-01 · 审计日志仅首50条且缺操作者和资源详情

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-prj-01)。

**目标交互**：项目审计可翻阅和追踪到真实操作者与资源。

**改动落点**：[frontend/src/features/projects/project-service.ts:116-121](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/projects/project-service.ts#L116)；[frontend/src/pages/ProjectsPage.tsx:532-569](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProjectsPage.tsx#L532)。

**实施步骤**：

1. listProjectAuditLogs开放page/pageSize和已有可支持的过滤。
2. 表格绑定total，显示操作者摘要、动作、资源ID/名称、Trace ID。
3. 只读详情按允许字段展示details并提供合法资源定位。
4. 读取失败与无记录分开，保留过滤URL。

**API、模型与兼容**：先接分页合同；时间/动作/人员过滤若需扩展，在服务层授权和仓储过滤。无需新增审计采集。

**验收与新增行为测试**：

- [ ] 第51条日志可达且总数正确。
- [ ] 同类不同资源可区分并复制Trace ID。
- [ ] 无权限资源不可钻取，旧日志无actor/trace字段明确未提供。

<a id="f-prj-02"></a>

#### F-PRJ-02 · 成员与团队面板仍使用UUID，部分读取失败表现为空列表

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-prj-02)。

**目标交互**：成员维护不要求猜UUID，读取失败不伪装空成员。

**改动落点**：[frontend/src/features/projects/AccessManagementPanel.tsx:61-120,135-178](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/projects/AccessManagementPanel.tsx#L61)；[frontend/src/features/projects/access-service.ts:11-15,55-57](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/projects/access-service.ts#L11)。

**实施步骤**：

1. 成员行显示可访问的显示名/邮箱摘要和角色，ID放详情/复制。
2. 提供按权限裁剪的用户/团队服务端搜索选择，保留精确ID作为高级输入。
3. users/teams/members/grants各查询显式显示失败和重试。
4. 用户/团队数量超首100时仍可选，不扩大可发现用户范围。

**API、模型与兼容**：普通项目Owner的身份检索需独立受权合同；不能为了方便开放系统管理员/users全量目录。

**验收与新增行为测试**：

- [ ] 管理员与普通Owner都能在权限内找到可授权用户。
- [ ] 第101个用户/团队可按授权搜索选择。
- [ ] 读取403/500不显示暂无数据；失败后已填信息不丢。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ProjectsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ProjectsPage.test.tsx)
- [backend/tests/test_access_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_access_api.py)
- [backend/tests/test_access_domain.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_access_domain.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m07"></a>

### M07 · 流程编排

**目标任务与版式**：B 画布工作台＋D 历史证据；28类节点可见；画布、检查器和运行证据相互定位；未应用/未保存/已发布/历史状态分离，所有层级保护输入。

**入口**：`/projects/:projectId/workflows`。本模块实际已有功能见 [审计章节](complete-audit.md#m07)，不得以新页面替掉其原处理链。

<a id="f-wf-01"></a>

#### F-WF-01 · 节点摘要不足以读懂真实请求和控制意图

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-wf-01)。

**目标交互**：主画布无需逐个打开检查器也能读懂流程意图。

**改动落点**：[frontend/src/flow/editor/node-presentation.ts:19-64](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/editor/node-presentation.ts#L19)。

**实施步骤**：

1. 扩展node-presentation纯显示模型：API资产版本/方法/路径、条件表达、循环集合/退出条件、分支数量和关键策略。
2. 从当前已知资产/配置读取，缺数据标未提供；长信息保留完整检查器与复制。
3. 摘要层级固定为名称、请求或控制意图、引用/配置摘要，执行badge独立。
4. 对旧condition/for_each和未知类型保留真实类型显示。

**API、模型与兼容**：不修改WorkflowDefinition、执行edges或控制语义；必要资产摘要走已有受权查询。

**验收与新增行为测试**：

- [ ] API、if/switch、until、parallel、提取/断言显示真实摘要。
- [ ] 长URL/表达式不覆盖端口和操作条。
- [ ] 主题/摘要更新不能改变坐标、节点配置或执行结果。

<a id="f-wf-02"></a>

#### F-WF-02 · 控制块内部API/普通步骤的可视化编辑弱于主画布

**优先级/批次/复杂度**：P2 / R1 / 大。对应 [审计证据](complete-audit.md#f-wf-02)。

**目标交互**：区域内已有普通步骤可用与主画布一致的配置能力维护。

**改动落点**：[frontend/src/flow/WorkflowControlFields.tsx:1230-1385](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L1230)；[frontend/src/flow/WorkflowRegionCanvasModal.tsx:185-348](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRegionCanvasModal.tsx#L185)；[frontend/src/flow/WorkflowRegionCanvas.tsx:23-93](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRegionCanvas.tsx#L23)。

**实施步骤**：

1. 先为区域节点编辑建立行为特征测试，再提取可复用的检查器内容和资源选择适配层。
2. 区域API开放现有请求覆盖、Service/Variant、参数/头/断言等字段，保留固定API版本。
3. 逐项核对区域实际支持节点，再开放其可视化插入/编辑；不以菜单支持替代引擎校验。
4. 区域更新回写父定义，显示有界顺序和嵌套路径；与主会话共享未应用保护。

**API、模型与兼容**：区域保持当前线性结构和引擎允许类型；不增隐式分支/任意重连；若某节点仅主图可用，明确解释限制。

**依赖**：[F-WF-04](#f-wf-04)。

**验收与新增行为测试**：

- [ ] 同一API配置在主图与区域往返一致且保存/执行有效。
- [ ] 区域Service/Variant与流程environment共同解析正确。
- [ ] 非法类型/深度/端口继续拒绝；拒绝时保留已有配置。
- [ ] 祖先区域删除或切换前处理子编辑草稿。

<a id="f-wf-03"></a>

#### F-WF-03 · 高级JSON默认展开并放在条件/区域等主要任务之前

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-wf-03)。

**目标交互**：常用控制配置优先，高级结构按需展开。

**改动落点**：[frontend/src/flow/WorkflowControlFields.tsx:103-149](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L103)；[frontend/src/flow/ControlConfigurationJson.tsx:65-85](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/ControlConfigurationJson.tsx#L65)；[frontend/src/flow/WorkflowControlFields.tsx:1114-1130](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L1114)。

**实施步骤**：

1. 检查器先展示控制条件、循环来源/退出、区域步骤、限额和错误策略。
2. 整份配置JSON和区域JSON放进明确高级折叠面板，默认收起。
3. 展开时解释应用JSON与应用节点配置的层级，使用浅色代码阅读/编辑。
4. 保留最大化配置与焦点恢复，技术schema可按需查看。

**API、模型与兼容**：只改变展示次序，不移除高级表达能力。

**依赖**：[F-WF-04](#f-wf-04)。

**验收与新增行为测试**：

- [ ] until首屏能看到条件和循环体入口。
- [ ] 展开/收起不应用JSON、不重置未应用文本。
- [ ] 320px检查器、最大化和键盘焦点都可用。

<a id="f-wf-04"></a>

#### F-WF-04 · 嵌套控制块未应用JSON在切换步骤后静默丢失

**优先级/批次/复杂度**：P1 / R0 / 大。对应 [审计证据](complete-audit.md#f-wf-04)。

**目标交互**：任意层级的未应用输入在切换步骤时都受同一套保护。

**改动落点**：[frontend/src/flow/WorkflowControlFields.tsx:1199-1225](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.tsx#L1199)；[frontend/src/flow/WorkflowRegionCanvasModal.tsx:38-49,145-165](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRegionCanvasModal.tsx#L38)；[frontend/src/flow/ControlConfigurationJson.tsx:20-43](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/ControlConfigurationJson.tsx#L20)。

**实施步骤**：

1. 为嵌套节点建立含user/project/workflow/region/node的编辑身份，接回NodeEditContext和父DraftSession。
2. 将原始JSON文本、解析状态与已应用基线纳入节点会话；禁用父级value=null绕过。
3. 切节点/换区域/关闭弹窗/切模块/开历史先处理未应用：应用、放弃、取消。
4. 结构替换时只清理已确认移除节点的会话；保存旧修订成功不能清除新输入。

**API、模型与兼容**：前端状态修复；不直接把未应用文本写入执行定义，不新增后端保存动作。

**验收与新增行为测试**：

- [ ] 按本轮until→group→JSON增加inputs.audit→切wait再返回的步骤复现，输入不再静默丢失。
- [ ] 合法、非法JSON与表单同时未应用均可取消离开并恢复。
- [ ] 应用只改本地图；保存失败、父区域关闭和不同用户项目之间不串数据。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/WorkflowsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/WorkflowsPage.test.tsx)
- [frontend/src/flow/WorkflowControlFields.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowControlFields.test.tsx)
- [frontend/src/flow/WorkflowDesigner.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowDesigner.test.tsx)
- [frontend/src/flow/editor/node-presentation.test.ts](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/editor/node-presentation.test.ts)
- [backend/tests/test_workflow_control_nodes.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_workflow_control_nodes.py)
- [backend/tests/test_structured_control_contract.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_structured_control_contract.py)
- [backend/tests/test_control_reports.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_control_reports.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m08"></a>

### M08 · 测试用例与套件

**目标任务与版式**：C 用例目录/列表/详情；目录、状态/结果/版本、已发布流程绑定、套件、计划、导入导出和删除影响明确；执行和发布分开。

**入口**：`/projects/:projectId/assets`。本模块实际已有功能见 [审计章节](complete-audit.md#m08)，不得以新页面替掉其原处理链。

<a id="f-case-01"></a>

#### F-CASE-01 · 缺前置资源时新建用例只显示禁用，没有缺项解释与跳转

**优先级/批次/复杂度**：P2 / R1 / 小。对应 [审计证据](complete-audit.md#f-case-01)。

**目标交互**：新建用例的缺项和下一步可直接理解。

**改动落点**：[frontend/src/pages/TestAssetsPage.tsx:734-754,910-978](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L734)。

**实施步骤**：

1. 从已发布流程、环境、编辑权限和读取状态计算创建资格与缺项。
2. 禁用按钮旁显示原因列表，并提供发布流程/管理环境的受权跳转。
3. 返回原项目与目录，刷新资源但不替换用户已填内容。

**API、模型与兼容**：复用已有资源/权限查询，读取失败与确实没有资源分开。

**验收与新增行为测试**：

- [ ] 无流程、无发布版本、无环境、只读四种状态说明不同。
- [ ] 配置入口正确携带项目并可返回。
- [ ] 条件满足后按钮立即可用，读取失败不能显示创建默认对象。

<a id="f-case-02"></a>

#### F-CASE-02 · 套件编辑关闭没有草稿确认或恢复，和用例编辑不一致

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-case-02)。

**目标交互**：套件编辑草稿保护与用例编辑保持一致。

**改动落点**：[frontend/src/pages/TestAssetsPage.tsx:1496-1500,1956-2004](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L1496)。

**实施步骤**：

1. SuiteDialog记录初始成员/名称/目录/变量等与当前表单差异。
2. 取消、叉号、遮罩、Escape和路由离开统一经过草稿处理。
3. 提供继续编辑/放弃；若选择保留，则按用户项目保存非秘密草稿，成功后清理。
4. 提交pending时阻止重复保存和提前卸载。

**API、模型与兼容**：优先复用现有CaseDialog保护机制，不自动创建服务端套件。

**验收与新增行为测试**：

- [ ] 输入审计未保存套件再关闭重开，不经明确放弃不得静默清空。
- [ ] 成员顺序、固定版本与变量改动也触发保护。
- [ ] 保存失败保留全部输入；已明确放弃后重开才恢复初始值。

<a id="f-case-03"></a>

#### F-CASE-03 · 编辑用例和套件时目录选择没有树层级或完整路径

**优先级/批次/复杂度**：P2 / R1 / 小。对应 [审计证据](complete-audit.md#f-case-03)。

**目标交互**：目录选择展示完整层级和可区分路径。

**改动落点**：[frontend/src/pages/TestAssetsPage.tsx:1560-1562,2018-2020,2120-2122](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L1560)。

**实施步骤**：

1. 统一使用现有目录树选择组件，选中值仍为folder.id。
2. 叶名称相同时展示父路径，支持按路径搜索和未分类。
3. 创建/移动/批量编辑/套件选择均使用相同路径标签。

**API、模型与兼容**：无模型变更，不用目录名称代替稳定ID。

**验收与新增行为测试**：

- [ ] A/公共和B/公共可明确区分。
- [ ] 删除/无权限目录给失效提示，不自动移动到同名目录。
- [ ] 跨页批量改目录范围准确。

<a id="f-case-04"></a>

#### F-CASE-04 · 用例目录缺发布状态、最近结果、环境和排序等任务筛选

**优先级/批次/复杂度**：P2 / R1 / 大。对应 [审计证据](complete-audit.md#f-case-04)。

**目标交互**：维护用例时可按真实发布/执行/环境维度定位。

**改动落点**：[frontend/src/pages/TestAssetsPage.tsx:632-669](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.tsx#L632)；[frontend/src/features/test-assets/use-test-assets.ts:47-66](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-assets/use-test-assets.ts#L47)。

**实施步骤**：

1. 增加发布状态、最近结果、环境及排序的紧凑筛选，URL保存筛选/页码。
2. 先确定发布状态与最近执行结果的独立语义，列表与统计使用相同查询范围。
3. 扩展服务端过滤/排序后接入，切筛选重置页码但不偷换跨页选中范围。
4. 详情保留固定版本和最近结果入口。

**API、模型与兼容**：需扩展列表查询合同和对应聚合；不能只过滤当前页；如增加数据库索引需相应迁移。

**验收与新增行为测试**：

- [ ] 超过100条时结果/total/目录计数一致。
- [ ] 未执行、取消、失败、草稿和已发布语义不混合。
- [ ] 过滤后的跨页选择、导出/删除说明与实际对象一致。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/TestAssetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsPage.test.tsx)
- [frontend/src/pages/TestAssetsWorkspace.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestAssetsWorkspace.test.tsx)
- [frontend/src/features/test-assets/AssetPlanDialog.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-assets/AssetPlanDialog.test.tsx)
- [frontend/src/features/test-assets/AssetRunEvidence.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-assets/AssetRunEvidence.test.tsx)
- [backend/tests/test_tasking_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_tasking_api.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m09"></a>

### M09 · 数据与 Mock

**目标任务与版式**：C＋G 数据与Mock双子域；Credential元数据与秘密只写；Mock服务/规则/场景与请求日志可维护，配置不变成任意脚本。

**入口**：`/projects/:projectId/data`。本模块实际已有功能见 [审计章节](complete-audit.md#m09)，不得以新页面替掉其原处理链。

<a id="f-data-01"></a>

#### F-DATA-01 · Mock规则只有创建删除，没有编辑和单规则启停

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-data-01)。

**目标交互**：已建Mock规则可直接维护与启停。

**改动落点**：[frontend/src/pages/DataMockPage.tsx:399-490,591-604](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DataMockPage.tsx#L399)；[frontend/src/features/data-sources/data-source-service.ts:78-106](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/data-sources/data-source-service.ts#L78)；[backend/app/api/v1/endpoints/data_sources.py:198-219](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/api/v1/endpoints/data_sources.py#L198)。

**实施步骤**：

1. 接入现有PATCH路由规则，选行打开规则详情和编辑表单。
2. 表格补启用/优先级/场景摘要，启停明确只影响后续匹配。
3. 保存失败保留输入，删除沿用现有确认；按服务ID隔离编辑状态。
4. 服务编辑仅开放后端已有字段，不重建已有路由ID。

**API、模型与兼容**：使用后端update_route及已存在审计；不新增脚本执行或秘密读接口。

**验收与新增行为测试**：

- [ ] 修改响应/条件/优先级后同一路由ID生效。
- [ ] 停用该规则后匹配转到正确后备规则。
- [ ] Viewer不可写；失败和切服务不会改错规则。

<a id="f-data-02"></a>

#### F-DATA-02 · Mock匹配条件和响应配置仍依赖四块JSON，缺结构化预览

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-data-02)。

**目标交互**：Mock规则有结构化条件和可解释的响应预览。

**改动落点**：[frontend/src/pages/DataMockPage.tsx:519-618](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DataMockPage.tsx#L519)。

**实施步骤**：

1. Query/Header/响应头使用键值行，响应体保留JSON/文本的实际合同。
2. 校验JSON对象与值类型，模板语法错误定位到字段。
3. 用合成请求输入显示命中条件、场景、优先级和模板展开预览。
4. 预览沿用同一渲染语义并有大小/深度限制，明确不发送外部请求。

**API、模型与兼容**：若前端不能可靠复用模板解析，增加受权只读预览服务；不运行用户脚本，不扩大请求日志。

**依赖**：[F-DATA-01](#f-data-01)。

**验收与新增行为测试**：

- [ ] 合法模板预览与真实Mock响应一致。
- [ ] 数组/数字Header条件在表单定位错误而非保存后报泛错。
- [ ] 空匹配、场景优先级、未定义变量和超大模板都有明确反馈。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/DataMockPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/DataMockPage.test.tsx)
- [backend/tests/test_data_nodes_and_mock.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_data_nodes_and_mock.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m10"></a>

### M10 · 契约中心

**目标任务与版式**：C 契约目录＋D 兼容证据＋E 审核；服务、OpenAPI/Pact、兼容矩阵和真实阻断证据联动；导入与候选审核覆盖完整目录。

**入口**：`/projects/:projectId/contracts`。本模块实际已有功能见 [审计章节](complete-audit.md#m10)，不得以新页面替掉其原处理链。

<a id="f-ct-01"></a>

#### F-CT-01 · OpenAPI批次/候选固定首100条；兼容提供方选项只来自当前目录页

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-ct-01)。

**目标交互**：契约批次、候选审核和引用选择能到达所有授权对象。

**改动落点**：[frontend/src/features/contracts/contract-service.ts:3-8,31-40](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/contract-service.ts#L3)；[frontend/src/features/contracts/ContractAutomationPanel.tsx:54-78](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/ContractAutomationPanel.tsx#L54)；[frontend/src/pages/ContractHubPage.tsx:67-75,864-867](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.tsx#L67)。

**实施步骤**：

1. 将runs/cases改为显式分页/过滤Page状态，绑定total。
2. Provider/Pact/基线等选择器独立按服务端搜索分页，已选对象按ID补取。
3. 统一资产表和自动化记录显示全量总数/当前页范围。
4. 翻页时不丢失当前审核内容或已选版本。

**API、模型与兼容**：契约列表已有Page参数可扩展客户端；按ID或查询缺项需补只读合同，拒绝抓全部数据。

**验收与新增行为测试**：

- [ ] 第101批次/候选可审核；第21个服务可作为Provider。
- [ ] 不同目录页不会把已选服务名变未知或换成首项。
- [ ] Viewer读取与受控审核限制保持。

<a id="f-ct-02"></a>

#### F-CT-02 · 发布阻断证据和契约变更主要停留在数量摘要

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-ct-02)。

**目标交互**：不可发布判断可以直接检查阻断原因和Interaction。

**改动落点**：[frontend/src/pages/ContractHubPage.tsx:464-484,503-583](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.tsx#L464)。

**实施步骤**：

1. 兼容单元格、失败判断和统一资产行打开冻结证据详情。
2. 展示真实expected/actual、Interaction/契约版本、破坏性变更列表和基线。
3. 已知源对象提供受权定位；证据缺失标未提供，不推断无破坏性变更。
4. 源文档/JSON放高级只读区。

**API、模型与兼容**：先使用已有evidence/breaking_changes；需要更细证据时扩展读取DTO，不重新执行Provider验证。

**验收与新增行为测试**：

- [ ] 有3项blocker时可逐项查看而非仅计数。
- [ ] 旧契约与新导入版本共存且不会替换冻结预期。
- [ ] 打开证据不访问Broker/Provider、不发验证请求。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ContractHubPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContractHubPage.test.tsx)
- [frontend/src/features/contracts/ContractAutomationPanel.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/contracts/ContractAutomationPanel.test.tsx)
- [backend/tests/test_contract_hub.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_contract_hub.py)
- [backend/tests/test_contract_automation.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_contract_automation.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m11"></a>

### M11 · 测试工程

**目标任务与版式**：E 设计审核；契约→只读设计→Scenario/Oracle/Coverage→Draft→Review→Apply→已生成资产；来源与不确定性可检查。

**入口**：`/projects/:projectId/test-engineering`。本模块实际已有功能见 [审计章节](complete-audit.md#m11)，不得以新页面替掉其原处理链。

<a id="f-eng-01"></a>

#### F-ENG-01 · 空覆盖项被显示为100%覆盖

**优先级/批次/复杂度**：P2 / R2 / 小。对应 [审计证据](complete-audit.md#f-eng-01)。

**目标交互**：无评估项与100%覆盖明确区分。

**改动落点**：[frontend/src/pages/TestEngineeringPage.tsx:292-295,322-328](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.tsx#L292)。

**实施步骤**：

1. 覆盖率模型使用number。
2. null并附evaluatedCount/coveredCount。
3. total=0时显示未评估/无可评估项，不渲染满圈。
4. 与Coverage表和摘要统一分母。

**API、模型与兼容**：前端显示修复，覆盖引擎不改。

**验收与新增行为测试**：

- [ ] 0项显示未评估，1/1显示100%，0/1显示0%。
- [ ] 缺coverage数据不渲染成功标签。
- [ ] 读旧Proposal时保持原设计内容。

<a id="f-eng-02"></a>

#### F-ENG-02 · 物化成功只弹数量，丢弃具体Workflow/TestCase定位

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-eng-02)。

**目标交互**：Apply后可以打开每个生成的工作流和用例。

**改动落点**：[frontend/src/features/test-engineering/use-test-engineering.ts:137-152](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-engineering/use-test-engineering.ts#L137)；[frontend/src/pages/TestEngineeringPage.tsx:494-532](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.tsx#L494)。

**实施步骤**：

1. 保存Apply返回的workflow_ids/test_case_ids，展示生成资产清单与受权入口。
2. 刷新相关目录/详情缓存，状态区分物化为草稿与已发布/已执行。
3. 刷新后按已有关联恢复；若DTO没有持久关系则补只读物化资源引用。
4. 跳转前处理当前未保存设计输入。

**API、模型与兼容**：Apply边界不变；持久结果定位需要复用关联数据或增加只读字段，不自动发布/执行。

**验收与新增行为测试**：

- [ ] 生成多个资产逐一可打开正确对象。
- [ ] 重复Apply/失败不显示虚假已物化。
- [ ] 页面刷新后能从Proposal找回结果，跨项目ID被拒绝。

<a id="f-eng-03"></a>

#### F-ENG-03 · 主要页面大量开发阶段标签和英文术语，证据引用不能钻取

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-eng-03)。

**目标交互**：测试设计按来源、场景、Oracle和缺口组织为可读审核任务。

**改动落点**：[frontend/src/pages/TestEngineeringPage.tsx:60-72,307-351,378-416,552-611](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.tsx#L60)。

**实施步骤**：

1. 主标题/按钮/状态统一中文，S47等研发阶段标签移到诊断信息。
2. 场景选中联动Oracle/coverage/evidence，明确确定性、置信度与仅设计原因。
3. 证据引用提供来源/修订/字段路径只读展开和合法对象入口。
4. 保留原始表达和指纹在高级区，不隐藏重要审核限制。

**API、模型与兼容**：复用已有design/evidence_refs；无法从source_ref解析的引用显示原文且不猜链接。

**验收与新增行为测试**：

- [ ] 选择场景后可找到支持其预期的Oracle与来源。
- [ ] 低置信度/无可执行Oracle不被误当可执行用例。
- [ ] 中文界面与长技术标识并存可读，Viewer无写入口。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/TestEngineeringPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestEngineeringPage.test.tsx)
- [frontend/src/features/test-engineering/use-test-engineering.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/test-engineering/use-test-engineering.test.tsx)
- [backend/tests/test_test_engineering.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_test_engineering.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m12"></a>

### M12 · 任务执行

**目标任务与版式**：C＋F 计划与任务生命周期；计划编组、固定版本、调度、队列、取消、CI/Webhook与冻结执行证据闭环；一次性秘密规则保持。

**入口**：`/projects/:projectId/tasks`。本模块实际已有功能见 [审计章节](complete-audit.md#m12)，不得以新页面替掉其原处理链。

<a id="f-task-01"></a>

#### F-TASK-01 · 新建计划只能添加一个目标，未开放后端多执行项编组

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-task-01)。

**目标交互**：计划新建可以组织多个固定版本执行项。

**改动落点**：[frontend/src/pages/TestPlansPage.tsx:434-547](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestPlansPage.tsx#L434)；[frontend/src/features/task-plans/task-plan-service.ts:134-155](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/task-plans/task-plan-service.ts#L134)；[backend/app/schemas/tasking.py:37-47](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/schemas/tasking.py#L37)。

**实施步骤**：

1. 把单目标表单改为执行项列表，逐项选workflow/case/suite及固定发布版本。
2. 各项显示环境继承/覆盖、重试与执行顺序，批量添加后逐项核对。
3. 提交现有items数组，遵守最多100项及服务端去重/嵌套约束。
4. 编辑旧计划仅开放现有支持的调度字段；修改目标若无合同则通过新建计划/版本，不偷改历史。

**API、模型与兼容**：后端创建已支持多项；现有TestPlanUpdate没有items，不能擅自把UI编辑映射成删除重建。

**验收与新增行为测试**：

- [ ] 3项含不同类型/环境能创建并在运行详情保持冻结顺序与版本。
- [ ] 第101项、未发布目标、无权目标被前后端拒绝。
- [ ] 调度、签名Webhook、CI Token及取消回归均不退化。

<a id="f-task-02"></a>

#### F-TASK-02 · focus链接仅高亮当前页，运行详情不进入URL

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-task-02)。

**目标交互**：计划与运行深链接在页外、刷新和返回后仍可恢复。

**改动落点**：[frontend/src/pages/TestPlansPage.tsx:43-52,131-159,270-280](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestPlansPage.tsx#L43)；[frontend/src/features/task-plans/use-test-plans.ts:30-34,68-81](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/task-plans/use-test-plans.ts#L30)。

**实施步骤**：

1. focus计划按ID补取或服务端定位，选中对象不受当前页限制。
2. selectedRunId写入run URL并直接读取运行详情。
3. 无效对象和缺权限时给明确提示，不回落另一条任务。
4. 切项目清理旧选中但不携带另一个项目结果。

**API、模型与兼容**：运行详情合同已存在；计划缺按ID读取时补受权只读查询。

**验收与新增行为测试**：

- [ ] 第21个计划从搜索打开可见；运行详情刷新仍是同一run。
- [ ] 队列执行后可准确定位新运行。
- [ ] 跨项目/已删除/取消的记录处理清楚。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/TestPlansPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/TestPlansPage.test.tsx)
- [frontend/src/features/task-plans/TestPlanTargetSelect.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/task-plans/TestPlanTargetSelect.test.tsx)
- [backend/tests/test_tasking_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_tasking_api.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m13"></a>

### M13 · 环境实验室

**目标任务与版式**：F 受控环境生命周期；签名模板/版本→Provision→实例/TTL→Seed/健康记录→清理；多服务声明式配置受原合同约束。

**入口**：`/projects/:projectId/environments`。本模块实际已有功能见 [审计章节](complete-audit.md#m13)，不得以新页面替掉其原处理链。

<a id="f-env-01"></a>

#### F-ENV-01 · 模板创建固定单web服务，完整版本维护退回整份JSON

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-env-01)。

**目标交互**：受控模板的完整多服务配置有可视化维护入口。

**改动落点**：[frontend/src/pages/EnvironmentLabPage.tsx:488-618,671-710,863-911](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/EnvironmentLabPage.tsx#L488)；[frontend/src/features/environments/environment-service.ts:14-39](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/environments/environment-service.ts#L14)。

**实施步骤**：

1. 建立services列表编辑：镜像Digest、端口、环境键值、depends_on、健康检查、资源限额与Seed。
2. 新增与新版本共用同一表单，默认单web仍可作为快捷模板。
3. 新增版本显示与固定旧manifest的字段差异，高级JSON与表单双向校验且明确应用。
4. 依赖图检查循环/缺服务，限额按服务端合同，未授权字段不可输入。

**API、模型与兼容**：复用EnvironmentTemplateManifest，不增加任意Compose/命令/卷/脚本；签名仍由管理员服务完成。

**验收与新增行为测试**：

- [ ] 2个服务与依赖/多个Seed可创建和编辑，新版本不丢旧配置。
- [ ] 超限、缺Digest、依赖循环在对应字段提示且服务端仍拒绝。
- [ ] 关闭或切对象保护输入；打开页面不Provision。

<a id="f-env-02"></a>

#### F-ENV-02 · 实例绑定模板配置受当前模板目录页限制

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-env-02)。

**目标交互**：从实例可靠读取它绑定的模板版本。

**改动落点**：[frontend/src/pages/EnvironmentLabPage.tsx:775-823](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/EnvironmentLabPage.tsx#L775)；[frontend/src/features/environments/use-environment-lab.ts:49-54](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/environments/use-environment-lab.ts#L49)；[backend/app/api/v1/endpoints/environment_lab.py:27-44](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/api/v1/endpoints/environment_lab.py#L27)。

**实施步骤**：

1. 按instance.template_version_id独立查询签名模板版本，不从当前目录页推断。
2. 资源页显示固定模板ID/版本/manifest摘要与可复制哈希。
3. 模板不可读取/已停用/权限不足分别说明，不能替换为最新版本。
4. Provision选择器也支持按ID补取和完整授权目录查找。

**API、模型与兼容**：补受权只读模板版本查询；保留全局模板可见性、签名校验与项目实例授权，无需迁移执行快照。

**验收与新增行为测试**：

- [ ] 实例绑定第21条或旧版本时不需手动翻模板页。
- [ ] 模板更新后旧实例仍显示原manifest。
- [ ] 无权/缺失版本不显示别的配置，也不重新Provision。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/EnvironmentLabPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/EnvironmentLabPage.test.tsx)
- [backend/tests/test_environment_lab.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_environment_lab.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m14"></a>

### M14 · 性能实验室

**目标任务与版式**：F 场景/运行＋D 冻结证据；声明式HTTP步骤、固定/阶梯负载、阈值、版本、基线和门禁分离；阅读页面不自动压测。

**入口**：`/projects/:projectId/performance`。本模块实际已有功能见 [审计章节](complete-audit.md#m14)，不得以新页面替掉其原处理链。

<a id="f-perf-01"></a>

#### F-PERF-01 · 新建只支持单HTTP步骤，复杂负载与版本维护依赖JSON

**优先级/批次/复杂度**：P2 / R2 / 大。对应 [审计证据](complete-audit.md#f-perf-01)。

**目标交互**：复杂HTTP负载与版本编辑无需手写整份配置。

**改动落点**：[frontend/src/pages/PerformanceLabPage.tsx:297-432,459-504,822-896](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PerformanceLabPage.tsx#L297)；[frontend/src/features/performance/performance-service.ts:10-48](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/performance/performance-service.ts#L10)。

**实施步骤**：

1. 新建/新版本复用有界steps、headers/body、stage和threshold编辑器。
2. 固定VU与阶梯模型切换时保留明确策略，显示单位/上限和负载总时长。
3. 新版本先给字段差异与原版摘要，再保存为独立草稿。
4. 高级JSON可用但需显式应用及输入保护。

**API、模型与兼容**：沿用现有PerformanceDefinition和编译白名单；不接用户JS，不改变负载默认值或网络策略。

**验收与新增行为测试**：

- [ ] 多HTTP步骤和多升压阶段可往返维护。
- [ ] 时长、VU、阈值/单位校验与服务端一致。
- [ ] 新版本不改变旧运行冻结配置；打开/预览/保存均不自动压测。

<a id="f-perf-02"></a>

#### F-PERF-02 · 启动运行后未选中新运行或提供直接进入证据的入口

**优先级/批次/复杂度**：P2 / R2 / 中。对应 [审计证据](complete-audit.md#f-perf-02)。

**目标交互**：启动后立即进入所返回的新运行上下文。

**改动落点**：[frontend/src/features/performance/use-performance-lab.ts:112-132,176-186](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/performance/use-performance-lab.ts#L112)；[frontend/src/pages/PerformanceLabPage.tsx:135-165](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PerformanceLabPage.tsx#L135)。

**实施步骤**：

1. startRun使用返回PerformanceRun更新run URL和详情缓存，清scenario选中。
2. 队列状态显示新run.id、发起配置版本和当前状态，终态前有界轮询。
3. 回包前校验仍在原项目/发起会话；离开页面可在该项目历史找到新运行。
4. 失败保留场景选择并允许显式重试，不自动创建第二个运行。

**API、模型与兼容**：不改运行接口，使用其既有返回ID；重试幂等行为须遵守现有后端合同。

**验收与新增行为测试**：

- [ ] 原详情是旧run时启动成功后明确显示新run。
- [ ] 迟到回包不导航到另一个项目。
- [ ] 旧运行链接仍可回看，运行失败不提示已通过。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/PerformanceLabPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PerformanceLabPage.test.tsx)
- [frontend/src/features/performance/use-performance-lab.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/performance/use-performance-lab.test.tsx)
- [backend/tests/test_performance_lab.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_performance_lab.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m15"></a>

### M15 · 测试报告

**目标任务与版式**：D 冻结执行证据；项目/工作流/运行/节点/attempt及可用实例路径一致；真实期望/实际/单位/来源可定位；历史只读且可导出。

**入口**：`/projects/:projectId/reports`。本模块实际已有功能见 [审计章节](complete-audit.md#m15)，不得以新页面替掉其原处理链。

<a id="f-rep-01"></a>

#### F-REP-01 · 默认选中节点未规范化到链接上下文，跨视图跳转改变选中节点

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-rep-01)。

**目标交互**：默认选中和显式选中使用同一个可分享的证据定位。

**改动落点**：[frontend/src/pages/WorkflowsPage.tsx:1381-1398,1600-1635](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/WorkflowsPage.tsx#L1381)；[frontend/src/features/reports/ReportExecutionWorkspace.tsx:56-72,254-260](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L56)。

**实施步骤**：

1. 提取默认节点策略：失败执行优先首个有证据的失败实例，成功执行优先有业务证据的节点。
2. 首次自动选择后以replace规范化node/attempt及现有instance/branch参数。
3. 编排与报告使用同一定位构造器，显式URL优先且保留已有转发逻辑。
4. 切换节点/attempt/实例时同步URL，返回/刷新恢复；无效选择给提示而非静默首节点。

**API、模型与兼容**：前端路由/选择状态调整；不需要改变执行快照。

**验收与新增行为测试**：

- [ ] 用例→编排自动选API→查看完整报告仍选同一API。
- [ ] 显式node+attempt和循环实例URL原样往返。
- [ ] 首失败节点、无失败、无证据、无效ID均有确定反馈。

<a id="f-rep-02"></a>

#### F-REP-02 · 断言证据来源主要是静态文字，缺上游来源路径与直接定位

**优先级/批次/复杂度**：P2 / R1 / 大。对应 [审计证据](complete-audit.md#f-rep-02)。

**目标交互**：断言结论能追溯到同一冻结运行的来源和路径。

**改动落点**：[frontend/src/features/evidence/AssertionEvidence.tsx:3-9,53-57](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/evidence/AssertionEvidence.tsx#L3)；[frontend/src/features/evidence/assertion-model.ts:20-33](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/evidence/assertion-model.ts#L20)；[frontend/src/features/reports/ReportExecutionWorkspace.tsx:340-380](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L340)。

**实施步骤**：

1. AssertionEvidence增加有类型的source locator：来源节点/attempt/实例、提取路径、原始表达和是否已解析。
2. 仅由冻结定义与当次证据确定关系；不能静态解析时显示未解析。
3. 来源入口使用共享证据定位器，单位缺失仍显示未提供。
4. 期望/实际/差值/单位按真实合同渲染，不复用当前草稿。

**API、模型与兼容**：优先读取已冻结内容；若报告DTO缺必要来源字段，新增只读可选字段并保持旧报告兼容。

**依赖**：[F-REP-01](#f-rep-01)。

**验收与新增行为测试**：

- [ ] 改当前草稿后旧报告来源和预期不变。
- [ ] 循环不同item/attempt的来源不串；未知表达式不猜节点。
- [ ] 无单位时不补分/毫秒，缺字段不填0。

<a id="f-rep-03"></a>

#### F-REP-03 · 报告与流程证据仍以通用pre JSON展示，缺API工作台的阅读工具

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-rep-03)。

**目标交互**：编排和报告证据具备可读、可复制、受边界约束的阅读器。

**改动落点**：[frontend/src/flow/WorkflowRunInspector.tsx:1069-1110](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/flow/WorkflowRunInspector.tsx#L1069)；[frontend/src/features/reports/ReportExecutionWorkspace.tsx:462-533](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L462)；[frontend/src/features/api-console/ResponseCodeReader.tsx:4-69](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/ResponseCodeReader.tsx#L4)。

**实施步骤**：

1. 复用已有ResponseCodeReader/浅色代码能力，形成协议/文本/JSON阅读模式。
2. 提供换行、复制、搜索/展开和可用的体积提示；大附件继续走原授权下载。
3. 请求/响应/提取/输出使用同一冻结定位，不随当前草稿变化。
4. 390采用单列和局部滚动，长JSON不撑开页面。

**API、模型与兼容**：不扩采数据、不把大附件全部拉入内存；按现有项目ON/OFF策略展示授权证据。

**依赖**：[F-REP-01](#f-rep-01)。

**验收与新增行为测试**：

- [ ] 长JSON/纯文本/空值/缺值和附件引用可分辨。
- [ ] 切节点晚回包不覆盖当前证据。
- [ ] 复制/下载只含当次有权证据；移动端操作可达。

<a id="f-rep-04"></a>

#### F-REP-04 · 报告缺时间、流程、环境或用例等任务维度筛选

**优先级/批次/复杂度**：P2 / R1 / 大。对应 [审计证据](complete-audit.md#f-rep-04)。

**目标交互**：报告列表与趋势具有一致且可见的查询范围。

**改动落点**：[frontend/src/pages/ReportsPage.tsx:145-242](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReportsPage.tsx#L145)；[frontend/src/features/reports/report-service.ts:30-58](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/report-service.ts#L30)。

**实施步骤**：

1. 增加时间范围、流程、环境、用例/计划来源等现有可追溯维度筛选。
2. 明确列表总数、趋势窗口与通过率分母，筛选写入URL。
3. 后端列表和趋势/聚合接收相同scope，未知和空样本分别显示。
4. 按失败类型等排序若没有合同则先显示未支持，不做当前页伪筛选。

**API、模型与兼容**：需要列表/统计只读查询扩展；不重算或改写历史快照。

**验收与新增行为测试**：

- [ ] 跨页total与趋势分母一致。
- [ ] 两个环境/用例来源的执行能精确筛选。
- [ ] 时间边界、时区、空范围和失败重试后的数据不误计。

<a id="f-rep-05"></a>

#### F-REP-05 · 节点页的检查点日志没有沿节点/尝试筛选

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计证据](complete-audit.md#f-rep-05)。

**目标交互**：节点检查点/日志明确当前筛选范围。

**改动落点**：[frontend/src/features/reports/ReportExecutionWorkspace.tsx:426-434](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/reports/ReportExecutionWorkspace.tsx#L426)；[frontend/src/features/workflows/ExecutionCheckpointLog.tsx:12-35](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/workflows/ExecutionCheckpointLog.tsx#L12)。

**实施步骤**：

1. 将执行日志面板区分全运行与当前节点上下文。
2. 已有日志有node/attempt/instance字段时按冻结locator过滤并显示筛选条件。
3. 缺少实例字段的旧日志标执行级记录，不能假称节点专属。
4. 日志跳转节点时保留运行和attempt，允许返回全量。

**API、模型与兼容**：仅过滤既有授权日志；不新增日志内容或诊断采集，必要DTO字段来自已记录身份。

**依赖**：[F-REP-01](#f-rep-01)。

**验收与新增行为测试**：

- [ ] 同运行A/B节点日志可切全量和节点视图。
- [ ] 重试和嵌套实例不混合；旧记录可读。
- [ ] 无匹配显示无该节点日志，不显示另一个节点并暗示属于当前。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ReportsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReportsPage.test.tsx)
- [frontend/src/features/workflows/execution-navigation.test.ts](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/workflows/execution-navigation.test.ts)
- [backend/tests/test_reporting_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_reporting_api.py)
- [backend/tests/test_control_reports.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_control_reports.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m16"></a>

### M16 · 影响分析

**目标任务与版式**：E 差异＋D 映射/覆盖证据；变更→影响→推荐集合→覆盖缺口之间有可解释关联和资产入口，不执行仓库命令。

**入口**：`/projects/:projectId/impact`。本模块实际已有功能见 [审计章节](complete-audit.md#m16)，不得以新页面替掉其原处理链。

<a id="f-imp-01"></a>

#### F-IMP-01 · 三列影响视图是静态列表，缺变更到资产/证据的联动定位

**优先级/批次/复杂度**：P2 / R3 / 大。对应 [审计证据](complete-audit.md#f-imp-01)。

**目标交互**：影响视图能从一个变更追到原因、覆盖和真实资产。

**改动落点**：[frontend/src/pages/ImpactAnalysisPage.tsx:245-352,354-405](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ImpactAnalysisPage.tsx#L245)。

**实施步骤**：

1. 用change_keys驱动选中/过滤，变更列选择后仅高亮对应资产和推荐。
2. 区分graph中的影响关系与selection中的测试选择，不能重复列表伪装两类结果。
3. 资产/覆盖单元格可打开原因、版本及受权目标；无法映射的引用显示原文。
4. 保留分析run的冻结上下文和返回位置。

**API、模型与兼容**：复用现有changes/graph/selection/coverage；不重新执行仓库命令或自动创建测试。

**验收与新增行为测试**：

- [ ] 一变更多资产、一资产多变更和未映射缺口均正确联动。
- [ ] 打开资产定位到正确项目/固定版本或明确历史不可编辑。
- [ ] 切分析run后所有选中和来源同时切换。

<a id="f-imp-02"></a>

#### F-IMP-02 · 资产列数量使用边数，映射摘要只统计当前页且关闭态显示0

**优先级/批次/复杂度**：P2 / R3 / 小。对应 [审计证据](complete-audit.md#f-imp-02)。

**目标交互**：影响摘要的数量与渲染对象和查询范围一致。

**改动落点**：[frontend/src/pages/ImpactAnalysisPage.tsx:79-82,133,189-225,269-282](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ImpactAnalysisPage.tsx#L79)。

**实施步骤**：

1. 受影响资产显示唯一资产数，若展示边数则单独命名关联关系数。
2. 映射总数取Page.total，当前页样本数另标。
3. 未读取/关闭/失败用未提供或关闭，不置0。
4. 为所有指标定义分母、去重键和数据来源。

**API、模型与兼容**：优先纯显示修复；如需全量关联去重数则补只读聚合，不能从一页推算。

**验收与新增行为测试**：

- [ ] 同资产命中3变更时资产1、关系3不混。
- [ ] 总映射25/本页20正确显示。
- [ ] 关闭态不显示0个映射/无风险等误导结论。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ImpactAnalysisPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ImpactAnalysisPage.test.tsx)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m17"></a>

### M17 · 变更回归

**目标任务与版式**：F 回归链路＋E 人工审核；变更来源→影响→当前计划覆盖→缺失测试审核→人工批准→执行→发布门禁，端到端证据可检查。

**入口**：`/projects/:projectId/change-regression`。本模块实际已有功能见 [审计章节](complete-audit.md#m17)，不得以新页面替掉其原处理链。

<a id="f-reg-01"></a>

#### F-REG-01 · 缺失测试可以接受/拒绝，但没有展示待审核的具体提案内容

**优先级/批次/复杂度**：P1 / R0 / 大。对应 [审计证据](complete-audit.md#f-reg-01)。

**目标交互**：接受缺失测试前可以审阅将被物化的完整内容和依据。

**改动落点**：[frontend/src/pages/ChangeRegressionPage.tsx:251-310](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.tsx#L251)；[frontend/src/features/change-regression/change-regression-service.ts:38-46](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/change-regression/change-regression-service.ts#L38)。

**实施步骤**：

1. Missing Test行增加查看/审核详情，展示proposed_content的请求、断言、目标版本、变量和风险摘要。
2. 查看关联契约/Evidence与仅设计/可执行限制，复杂内容提供浅色原文。
3. 接受/拒绝在该项明确上下文中操作，提交item_id与当前run并锁定pending。
4. 审核后显示审核人/备注/时间与materialized_resource引用，保持后端批准和语义门禁。

**API、模型与兼容**：先接现有MissingTestProposal字段；不足的来源/目标快照用受权只读DTO扩展，不能把Review当Apply或跳过批准。

**验收与新增行为测试**：

- [ ] 用户可在接受前核对实际请求和Oracle，不能只凭标题盲接。
- [ ] 切run/切项期间回包不会审核另一项；重复点击受控。
- [ ] 低置信度/未审核/语义缺口仍被后端阻止批准执行。

<a id="f-reg-02"></a>

#### F-REG-02 · 新建回归强制Git Diff，不能通过已有OpenAPI/Schema版本差异发起

**优先级/批次/复杂度**：P2 / R3 / 中。对应 [审计证据](complete-audit.md#f-reg-02)。

**目标交互**：回归链路可以使用既有的契约版本差异来源。

**改动落点**：[frontend/src/pages/ChangeRegressionPage.tsx:54-67,142-144](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.tsx#L54)；[frontend/src/features/change-regression/change-regression-service.ts:15-28](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/change-regression/change-regression-service.ts#L15)。

**实施步骤**：

1. 来源编辑支持Git diff、OpenAPI对比、GraphQL/Proto版本对比及已有允许组合。
2. 复用影响分析版本选择与有效配对校验，至少一种有效来源即可。
3. 提交真实openapi_diffs/schema_diffs，不再固定空数组。
4. 明确来源指纹/版本和只读分析行为，切来源保留未提交输入。

**API、模型与兼容**：已有ChangeRegressionInput支持来源数组；需核实服务开关、项目权限与版本兼容，不放宽来源限制。

**验收与新增行为测试**：

- [ ] 无Git diff但有效OpenAPI版本对比可创建链路。
- [ ] 跨项目、不同协议、基线等于当前和无来源均正确拒绝。
- [ ] 创建后冻结来源，后续版本更新不改该链路。

<a id="f-reg-03"></a>

#### F-REG-03 · 关键链路证据ID仅文本，失败分类无法定位具体运行和证据引用

**优先级/批次/复杂度**：P2 / R3 / 中。对应 [审计证据](complete-audit.md#f-reg-03)。

**目标交互**：回归端到端证据可以逐环节打开并返回。

**改动落点**：[frontend/src/pages/ChangeRegressionPage.tsx:233-248,945-1001](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.tsx#L233)。

**实施步骤**：

1. 将Impact/TestPlanRun/ReleaseDecision ID映射到共享精确locator。
2. FailureTriage的evidence_refs提供协议/节点/attempt摘要和合法证据入口。
3. Proposal物化资源与维护证据在同一链路显示，不只展示数量。
4. 缺失或不支持定位的历史引用显示原因和可复制ID。

**API、模型与兼容**：优先复用既有运行/决策按ID读取；不重新评估或执行来填补历史字段。

**依赖**：[F-TASK-02](#f-task-02)、[F-REP-01](#f-rep-01)。

**验收与新增行为测试**：

- [ ] 从同一回归run打开影响、执行、发布判断都对应冻结来源。
- [ ] 失败分类可定位到证据或明确未提供。
- [ ] 只读查看不发Approve/Execute/Apply/Release请求。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ChangeRegressionPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ChangeRegressionPage.test.tsx)
- [frontend/src/features/change-regression/RegressionMaintenancePanel.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/change-regression/RegressionMaintenancePanel.test.tsx)
- [backend/tests/test_change_regression.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_change_regression.py)
- [backend/tests/test_s59d_change_regression.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s59d_change_regression.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m18"></a>

### M18 · 质量中心

**目标任务与版式**：A 质量洞察＋D 冻结风险；质量门禁、Flaky隔离、基线、风险/聚类、推荐测试与JUnit；统计和修复入口具备真实范围。

**入口**：`/projects/:projectId/quality`。本模块实际已有功能见 [审计章节](complete-audit.md#m18)，不得以新页面替掉其原处理链。

<a id="f-qlt-01"></a>

#### F-QLT-01 · 启用门禁统计包含停用门禁

**优先级/批次/复杂度**：P2 / R3 / 小。对应 [审计证据](complete-audit.md#f-qlt-01)。

**目标交互**：启用门禁数量按真实enabled状态统计。

**改动落点**：[frontend/src/pages/QualityCenterPage.tsx:69-75,327-345](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.tsx#L69)。

**实施步骤**：

1. 启用数filter(enabled)，总数如有需要单独命名。
2. Loading/Error时显示未提供，不在未读时显示确定的0。
3. 把统计选择器作为可测试纯逻辑，避免与表格重复口径。

**API、模型与兼容**：无需后端变更，gates现有数组足够。

**验收与新增行为测试**：

- [ ] 2启用1停用显示启用2/总数3。
- [ ] 全部停用显示启用0而非3。
- [ ] 失败/未加载时不提示没有门禁。

<a id="f-qlt-02"></a>

#### F-QLT-02 · 风险历史有翻页却无记录选择，资产和运行也缺证据入口

**优先级/批次/复杂度**：P2 / R3 / 大。对应 [审计证据](complete-audit.md#f-qlt-02)。

**目标交互**：质量问题和任意风险快照可被选择、分享并进入修复证据。

**改动落点**：[frontend/src/features/quality/use-quality-center.ts:75-104](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/quality/use-quality-center.ts#L75)；[frontend/src/pages/QualityCenterPage.tsx:76-82,120-180,202-323,527-560](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.tsx#L76)。

**实施步骤**：

1. 风险历史增加记录列表/选择器，选择后写risk URL并保留页外ID读取。
2. Flaky使用完整target/version标识和受权详情，支持record参数。
3. 最近运行提供计划运行详情/报告入口，风险推荐/聚类提供已知证据链接。
4. 目录筛选与URL恢复一致，保持隔离动作独立显式。

**API、模型与兼容**：复用getReleaseRisk/getTestPlanRun；Flaky精确读取若缺失需补受权查询。不能通过切换风险自动隔离或执行。

**验收与新增行为测试**：

- [ ] 同页第2–20条风险均能打开并刷新恢复。
- [ ] 首页Flaky问题精准落到目标版本，页外记录不误选。
- [ ] 从风险/聚类到报告仍保留运行身份，无权限正确提示。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/QualityCenterPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/QualityCenterPage.test.tsx)
- [backend/tests/test_quality_domain.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_domain.py)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m19"></a>

### M19 · 发布门禁

**目标任务与版式**：D 发布决策/证据；版本/策略→必需证据→PASS/BLOCK及逐项理由→历史指纹；缺失、过期、失败与不满足规则可区分。

**入口**：`/projects/:projectId/release`。本模块实际已有功能见 [审计章节](complete-audit.md#m19)，不得以新页面替掉其原处理链。

<a id="f-rel-01"></a>

#### F-REL-01 · 项目发布判断依赖管理员全局Runner任务目录，且只截首100条后客户端过滤

**优先级/批次/复杂度**：P1 / R0 / 大。对应 [审计证据](complete-audit.md#f-rel-01)。

**目标交互**：项目角色在其授权范围内选择Runner证据。

**改动落点**：[frontend/src/features/release-gate/use-release-gate.ts:118-122](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/release-gate/use-release-gate.ts#L118)；[frontend/src/pages/ReleaseGatePage.tsx:371-374](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.tsx#L371)；[frontend/src/features/execution-fabric/execution-fabric-service.ts:123-127](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/execution-fabric/execution-fabric-service.ts#L123)；[backend/app/services/runner_fabric.py:183-186,1157-1165](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/services/runner_fabric.py#L183)；[backend/app/services/release_gate.py:106-110](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/services/release_gate.py#L106)。

**实施步骤**：

1. 新增项目范围Runner证据列表/按ID读取，由项目服务授权read并只返回可用于该项目决策的最小摘要。
2. 发布页不再调用系统管理员全局任务API，不做全局100条后的客户端过滤。
3. 项目证据选择独立分页/搜索，展示状态/执行/时间与当前项目。
4. 读取403/500/关闭状态有明确提示；缺证据继续BLOCK，不为可用性放宽规则。

**API、模型与兼容**：这是受权读取合同扩展：保留execution-fabric系统管理权限，业务规则放服务/仓储，router仅适配。若增索引需Alembic双向迁移。

**验收与新增行为测试**：

- [ ] 非系统管理员Owner/Editor可选择本项目合法任务；Viewer仍不能创建决策。
- [ ] 第101条以后本项目任务仍可查，跨项目ID拒绝。
- [ ] 原管理员执行面权限与门禁必需/过期/终态校验全部保持。

<a id="f-rel-02"></a>

#### F-REL-02 · 生成判断没有按所选策略展示必需证据/关闭原因，性能证据仅当前20条

**优先级/批次/复杂度**：P2 / R3 / 大。对应 [审计证据](complete-audit.md#f-rel-02)。

**目标交互**：按策略引导收集真实必需证据。

**改动落点**：[frontend/src/pages/ReleaseGatePage.tsx:495-593](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.tsx#L495)；[frontend/src/features/release-gate/use-release-gate.ts:111-122](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/release-gate/use-release-gate.ts#L111)。

**实施步骤**：

1. 选择策略后立即列出必需/可选证据及当前可用性，不足项给配置/收集入口。
2. 每类选择器区分关闭、读取失败、无数据、过期/不适用，不能都叫未选择。
3. 性能与Runner也使用独立分页搜索/精确ID补取。
4. 提交前展示冻结对象摘要；缺项允许评估BLOCK时明确说明，不偷偷填默认值。

**API、模型与兼容**：不改变后端PASS/BLOCK算法；性能只读分页已有，Runner依赖项目证据读取，错误与flag状态需从hook返回。

**依赖**：[F-REL-01](#f-rel-01)。

**验收与新增行为测试**：

- [ ] 同一策略要求3类证据时界面准确列出3类。
- [ ] 开关关闭/500和真实无数据的反馈不同。
- [ ] 第21个性能run可选；无效/跨项目/过期证据仍由后端拒绝或BLOCK。

<a id="f-rel-03"></a>

#### F-REL-03 · 判断证据缺到原始对象的结构化跳转

**优先级/批次/复杂度**：P2 / R3 / 中。对应 [审计证据](complete-audit.md#f-rel-03)。

**目标交互**：每条发布阻断理由可进入对应冻结来源。

**改动落点**：[frontend/src/pages/ReleaseGatePage.tsx:163-227,597-699](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.tsx#L163)。

**实施步骤**：

1. 按evidence_type从evidence_snapshot生成严格类型的只读来源卡。
2. 展示证据ID/版本/生成时间/有效性及实际期望，再提供查看质量运行/契约/影响/风险/性能/Runner入口。
3. 无法确定来源的旧记录标无法定位并保留原值。
4. 打开来源后可返回同decision，不触发新评估。

**API、模型与兼容**：缺项目范围Runner详情依赖F-REL-01；其余使用已有读取，必要快照字段只读兼容扩展。

**依赖**：[F-REL-01](#f-rel-01)、[F-TASK-02](#f-task-02)。

**验收与新增行为测试**：

- [ ] 六类真实证据分别定位到正确对象。
- [ ] 策略更新后旧decision理由和源身份不变。
- [ ] 点击来源不触发生产部署或新的决策/执行。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ReleaseGatePage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ReleaseGatePage.test.tsx)
- [backend/tests/test_release_gate.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_release_gate.py)
- [backend/tests/test_runner_fabric.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_runner_fabric.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m20"></a>

### M20 · AI 助手

**目标任务与版式**：E AI建议审核；任务来源与建议可审阅、编辑/备注/接受/拒绝及生成草稿定位；不自动执行或扩大数据采集。

**入口**：`/projects/:projectId/ai`。本模块实际已有功能见 [审计章节](complete-audit.md#m20)，不得以新页面替掉其原处理链。

<a id="f-ai-01"></a>

#### F-AI-01 · 四种AI任务使用同一Schema/元数据JSON表单，接受也只编辑JSON

**优先级/批次/复杂度**：P2 / R4 / 大。对应 [审计证据](complete-audit.md#f-ai-01)。

**目标交互**：AI建议按实际任务选择来源并展示可理解内容。

**改动落点**：[frontend/src/pages/AIAssistantPage.tsx:284-315,374-448](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIAssistantPage.tsx#L284)。

**实施步骤**：

1. 按用例/断言/流程草稿/失败归因建立各自表单，只要求该任务合同真正需要的字段。
2. 支持从有权API/Schema/冻结执行选择公开材料，提交前展示最终发送摘要；高级JSON仍可用。
3. 审核按建议类型显示请求、规则或流程摘要与原文，备注和编辑有明确层级。
4. 将脱敏措辞与当前授权采集和ON/OFF策略对应，不默认扫描、代换、扩采或读取Secret。

**API、模型与兼容**：复用AIJobInput允许字段；新增来源读取必须有权限和大小边界，不增加模型可调用写权限。

**验收与新增行为测试**：

- [ ] 失败归因不会被无意义的必填Schema阻塞。
- [ ] 提交材料可预览且与实际payload一致，无额外采集。
- [ ] 样本关闭/开启及ON/OFF策略行为与原合同一致，接受只形成允许草稿。

<a id="f-ai-02"></a>

#### F-AI-02 · 任务失败原因和接受后资产字段未展示

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-ai-02)。

**目标交互**：AI任务失败和接受结果均可继续处理。

**改动落点**：[frontend/src/features/ai/ai-service.ts:17-47](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/ai-service.ts#L17)；[frontend/src/pages/AIAssistantPage.tsx:179-247](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIAssistantPage.tsx#L179)；[frontend/src/features/ai/use-ai-review.ts:112-119](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/use-ai-review.ts#L112)。

**实施步骤**：

1. 任务详情显示既有error_code/error_message、状态/时间和可用trace引用。
2. 建议接受后显示accepted_resource_type/id的受权链接，已审核内容可只读回看。
3. 对失败/无建议/拒绝/已接受的下一步分别说明，不伪装可执行资产。
4. job/selection进入可恢复URL，切任务保护正在编辑的审核内容。

**API、模型与兼容**：使用现有字段，不暴露模型内部链路或未经授权输入；若无Trace字段明确未提供。

**验收与新增行为测试**：

- [ ] 网关/队列失败能看对应错误而非仅failed。
- [ ] 接受后打开正确草稿，不自动发布执行。
- [ ] 刷新重开已审核建议可见备注和结果，旧响应不覆盖当前任务。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/AIAssistantPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIAssistantPage.test.tsx)
- [backend/tests/test_ai_assistant.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_ai_assistant.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m21"></a>

### M21 · 上下文检查器

**目标任务与版式**：D 只读上下文/证据；Context Revision、完整性/冲突、来源Finding、知识关系和Proposal可联动检查，保持只读。

**入口**：`/projects/:projectId/contexts`。本模块实际已有功能见 [审计章节](complete-audit.md#m21)，不得以新页面替掉其原处理链。

<a id="f-ctx-01"></a>

#### F-CTX-01 · 证据、冲突与知识关系是长列表，缺来源联动和精确引用定位

**优先级/批次/复杂度**：P2 / R4 / 大。对应 [审计证据](complete-audit.md#f-ctx-01)。

**目标交互**：只读检查器可以沿冲突、知识和来源定位证据。

**改动落点**：[frontend/src/pages/ContextInspectorPage.tsx:120-157,192-339](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContextInspectorPage.tsx#L120)。

**实施步骤**：

1. 详情拆为概要/完整性冲突/证据/知识/提案的任务页签或锚点。
2. 增加来源类型、确定性、警告和冲突相关过滤，选知识节点定位evidence_ref。
3. 来源/修订/字段路径可复制并在已有权限下定位，未知引用不猜链接。
4. focus与所选证据写URL，保持只读和过期/缺失状态。

**API、模型与兼容**：仅消费已有ContextDetail；历史revision若API不支持则作为独立只读能力评估，不直接添加编辑操作。

**验收与新增行为测试**：

- [ ] 一条冲突能找到其Provider Finding和固定修订。
- [ ] 过滤后清楚显示当前/总证据数。
- [ ] Proposal入口仍准确；无额外Review/Apply/仓库扫描请求。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ContextInspectorPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ContextInspectorPage.test.tsx)
- [frontend/src/features/context-inspector/use-context-page.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/context-inspector/use-context-page.test.tsx)
- [backend/tests/test_s49_context_contracts.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s49_context_contracts.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m22"></a>

### M22 · AI 变更集

**目标任务与版式**：E 变更列表/差异/来源；固定风险与影响证据，逐项查看目标基线和变更、审核备注/冲突，接受后进入允许的草稿。

**入口**：`/projects/:projectId/ai-changes`。本模块实际已有功能见 [审计章节](complete-audit.md#m22)，不得以新页面替掉其原处理链。

<a id="f-aic-01"></a>

#### F-AIC-01 · 修改项没有目标基线与前后差异，来源证据也没有进入审核面板

**优先级/批次/复杂度**：P2 / R4 / 大。对应 [审计证据](complete-audit.md#f-aic-01)。

**目标交互**：变更审核同时呈现固定来源、目标基线和拟修改内容。

**改动落点**：[frontend/src/pages/AIChangeSetsPage.tsx:178-200,268-333](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.tsx#L178)；[frontend/src/features/ai/ai-change-set-service.ts:3-19,42-45](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/ai-change-set-service.ts#L3)。

**实施步骤**：

1. ChangeSetDetail增加来源摘要，显示impact/risk/AI job/指纹和只读证据入口。
2. 修改项显示target id/快照哈希，读取真正固定的before内容并生成字段diff。
3. 新增项显示完整结构化预览；审核后显示人/时间/备注。
4. 基线缺失或变化时说明冲突；不能拿当前资产假装原基线。

**API、模型与兼容**：若只保存哈希而无可读取before，需要受权冻结基线快照/读取设计；可能涉及持久化扩展，必须评估Alembic迁移和历史记录降级。

**验收与新增行为测试**：

- [ ] update可核对before/after且与服务端冲突基准一致。
- [ ] source_snapshot不被当前风险重新计算替换。
- [ ] 历史无before明确缺失；查看不触发AI生成或Apply。

<a id="f-aic-02"></a>

#### F-AIC-02 · 接受后无物化资产入口，审核编辑关闭会直接丢弃

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-aic-02)。

**目标交互**：审核编辑受到保护，接受后能打开物化草稿。

**改动落点**：[frontend/src/pages/AIChangeSetsPage.tsx:299-333,374-430](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.tsx#L299)；[frontend/src/features/ai/ai-change-set-service.ts:14-19](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/ai-change-set-service.ts#L14)。

**实施步骤**：

1. 接受结果按materialized_resource_type/id显示对象入口和草稿状态。
2. 审核弹窗记录内容/备注dirty，关闭/切项时继续/放弃/取消。
3. 保存失败保持输入和具体错误；pending防止重复接受。
4. 刷新相关资产缓存但不发布/运行。

**API、模型与兼容**：无写入合同扩展；结果引用现有字段，未知类型只读显示ID。

**验收与新增行为测试**：

- [ ] 编辑JSON/备注后关闭不会静默丢失。
- [ ] 接受创建/更新工作流、用例或断言后有准确入口。
- [ ] 冲突、失败、跨项目和重复提交不会显示虚假已接受。

<a id="f-aic-03"></a>

#### F-AIC-03 · AI/质量智能开关与只读历史提示不一致，关闭态仍请求并重试503

**优先级/批次/复杂度**：P2 / R4 / 大。对应 [审计证据](complete-audit.md#f-aic-03)。

**目标交互**：关闭生成能力仍可在授权范围内读取历史，写入继续受控。

**改动落点**：[frontend/src/features/ai/use-ai-change-sets.ts:28-58,121-125](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/use-ai-change-sets.ts#L28)；[frontend/src/pages/AIChangeSetsPage.tsx:164-176](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.tsx#L164)；[backend/app/services/ai_change_sets.py:165-179,485-491](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/app/services/ai_change_sets.py#L165)。

**实施步骤**：

1. 后端将list/get的项目读取授权与生成开关分离，允许已存在历史只读访问。
2. create和review等会写草稿的操作继续要求完整AI/质量智能条件。
3. 前端canCreate消费全部前置状态，关闭时解释具体缺项，不反复重试确定的功能关闭错误。
4. 历史为空、无权限、服务故障分开，不用关闭文案掩盖500。

**API、模型与兼容**：后端服务授权调整，禁止移除项目/租户守卫；是否允许关闭态历史Review本方案明确不开放。

**验收与新增行为测试**：

- [ ] AI关闭或quality_intelligence关闭时可读本人有权历史，生成/接受按钮关闭。
- [ ] 跨项目和无权限仍403/404，不返回历史内容。
- [ ] 功能开启后新建/轮询/审核恢复；前端不再产生本轮的重复503。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/AIChangeSetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/AIChangeSetsPage.test.tsx)
- [frontend/src/features/ai/use-ai-change-sets.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/ai/use-ai-change-sets.test.tsx)
- [backend/tests/test_quality_intelligence.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_quality_intelligence.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m23"></a>

### M23 · MCP 变更集

**目标任务与版式**：E 受控多类型变更审核；精确变更集、治理摘要、批准、逐项内容/差异/结果，保留当前模型的审批和修订号限制。

**入口**：`/projects/:projectId/mcp-changes`。本模块实际已有功能见 [审计章节](complete-audit.md#m23)，不得以新页面替掉其原处理链。

<a id="f-mcp-01"></a>

#### F-MCP-01 · 返回的warnings与Trace ID、置信度/风险原因未进入审核页

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-mcp-01)。

**目标交互**：批准前能看完整治理结论和请求诊断身份。

**改动落点**：[frontend/src/features/mcp/mcp-change-set-service.ts:41-64](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/mcp/mcp-change-set-service.ts#L41)；[frontend/src/pages/MCPChangeSetsPage.tsx:91-95,154-189](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/MCPChangeSetsPage.tsx#L91)。

**实施步骤**：

1. Envelope.warnings/trace_id显示在可折叠诊断/警告区。
2. 治理摘要展示risk_level/confidence/reason_codes及批准人/时间。
3. 警告与结构化内容同屏可达，区分提示和服务端硬性阻断。
4. 批准/接受后刷新同一变更集，保留一目了然的状态迁移。

**API、模型与兼容**：仅展示现有返回字段，不新增采集；无法映射中文原因时保留原代码和解释。

**验收与新增行为测试**：

- [ ] 非空warnings不被忽略，Trace ID可复制。
- [ ] 高风险未批准仍不能物化，批准后状态来自服务端。
- [ ] 只读用户可看允许的摘要但不可批准/接受。

<a id="f-mcp-02"></a>

#### F-MCP-02 · Test Design/TestCase/TestPlan更新缺结构化预览和物化结果定位

**优先级/批次/复杂度**：P2 / R4 / 大。对应 [审计证据](complete-audit.md#f-mcp-02)。

**目标交互**：各类MCP变更都有对应的审核摘要和结果入口。

**改动落点**：[frontend/src/pages/MCPChangeSetsPage.tsx:190-247,280-373](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/MCPChangeSetsPage.tsx#L190)；[frontend/src/features/mcp/mcp-change-set-service.ts:3-17](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/mcp/mcp-change-set-service.ts#L3)。

**实施步骤**：

1. 按test_design/test_case/test_plan_update/workflow分发只读预览，复用固定版本/目标/环境/断言展示。
2. 计划更新展示现有项与拟变更项、重试和环境差异；无固定before时明确缺失。
3. 接受后各类型按materialized_resource_type/id给受权入口。
4. 保留控制工作流/控制块现有图预览和修订冲突处理。

**API、模型与兼容**：不增加MCP全局发现、自动批准或自动Apply；若需before只读快照，沿用服务端精确变更集授权。

**验收与新增行为测试**：

- [ ] 四种类型均可核对内容且与实际物化一致。
- [ ] 工作流已有图预览不退化，非工作流结果可打开。
- [ ] 冲突时整个动作按原合同拒绝，不能局部应用后宣称成功。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/MCPChangeSetsPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/MCPChangeSetsPage.test.tsx)
- [backend/tests/test_s51_mcp_flow_proposals.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s51_mcp_flow_proposals.py)
- [backend/tests/test_s62_planning_mcp.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_s62_planning_mcp.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m24"></a>

### M24 · 组织治理

**目标任务与版式**：G＋F 组织治理；组织角色、服务账号、配额/Runner、审计与密钥生命周期按角色呈现，失败不伪装健康。

**入口**：`/organization`。本模块实际已有功能见 [审计章节](complete-audit.md#m24)，不得以新页面替掉其原处理链。

<a id="f-org-01"></a>

#### F-ORG-01 · 审计/Runner/安全/支持包读取失败未显示对应错误，安全区仍固定宣称可用

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-org-01)。

**目标交互**：每个治理子域按其实际读取结果显示状态。

**改动落点**：[frontend/src/pages/OrganizationGovernancePage.tsx:304-318,450-465,1010-1054](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.tsx#L304)。

**实施步骤**：

1. runner/security/audit/supportBundle各自加载/失败/无权限/重试，避免用顶层三查询代替全部。
2. KeyRotationCard只有读取成功且能力字段成立才显示能力可用；运行健康与能力描述分开。
3. 相关操作读取不足时禁用并解释，保留原角色canRotate规则。
4. 错误使用标准message/Trace，不暴露密钥材料。

**API、模型与兼容**：优先UI修复；如某读取不应对普通角色发起，按原授权拆分enabled，不扩大权限。

**验收与新增行为测试**：

- [ ] 四个查询逐一500/403不会变成空记录或成功可用。
- [ ] 安全数据失败时不能提交默认策略或激活未知版本。
- [ ] 重试成功可恢复，服务账号一次性令牌不因重试再次显示。

<a id="f-org-02"></a>

#### F-ORG-02 · 组织审计固定首50条且缺操作者和资源定位

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-org-02)。

**目标交互**：组织审计能服务真实追踪任务。

**改动落点**：[frontend/src/features/organizations/organization-service.ts:252-259](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/organizations/organization-service.ts#L252)；[frontend/src/pages/OrganizationGovernancePage.tsx:411-417,1165-1201](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.tsx#L411)。

**实施步骤**：

1. 接服务端分页/total，增加时间、动作、身份、资源过滤。
2. 表格摘要＋只读详情展示actor/resource/Trace及允许的details。
3. 组织与项目审计共用已稳定的显示/过滤结构时再抽共享，避免过早大重构。
4. 切组织重置目录范围并校验页外定位。

**API、模型与兼容**：现有分页先接回；过滤需受权只读合同，仍遵守组织隔离和已有采集范围。

**验收与新增行为测试**：

- [ ] 第51条日志可达，total与过滤条件一致。
- [ ] 同动作不同对象/操作者可区分。
- [ ] 切组织与无权限读取不混入上一组织数据。

<a id="f-org-03"></a>

#### F-ORG-03 · 组织成员需填用户ID，提交尚未成功就清空输入

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-org-03)。

**目标交互**：身份维护可理解且提交失败保留输入。

**改动落点**：[frontend/src/pages/OrganizationGovernancePage.tsx:598-608,613-639](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.tsx#L598)。

**实施步骤**：

1. onMemberChange返回可等待结果，成功后才resetFields。
2. 失败显示标准错误并保留ID/角色，禁用重复提交。
3. 按组织可发现范围提供用户摘要/搜索，UUID仅作为高级定位。
4. 更新已有角色在确认服务器结果后更新显示。

**API、模型与兼容**：身份搜索不能复用未授权全用户目录；没有可发现合同前可先保留精确ID输入并改善标签/帮助。

**验收与新增行为测试**：

- [ ] 不存在用户/网络错误时ID和角色仍在。
- [ ] 成功才清空表单；双击不会重复更新。
- [ ] 现有用户与同名用户可区分，不泄露不可访问身份。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/OrganizationGovernancePage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/OrganizationGovernancePage.test.tsx)
- [backend/tests/test_organization_governance.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_organization_governance.py)
- [backend/tests/test_organizations_api.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_organizations_api.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m25"></a>

### M25 · 分布式执行面

**目标任务与版式**：F 分布式执行运维；管理员可检查Worker/队列/任务/Lease/Fence的当前状态与证据，计数范围/更新时间可辨。

**入口**：`/execution-fabric`。本模块实际已有功能见 [审计章节](complete-audit.md#m25)，不得以新页面替掉其原处理链。

<a id="f-fab-01"></a>

#### F-FAB-01 · 队列分组统计只取最近100个任务，Pool目录也固定首100

**优先级/批次/复杂度**：P2 / R4 / 大。对应 [审计证据](complete-audit.md#f-fab-01)。

**目标交互**：当前队列指标和库存不受最近样本窗口误导。

**改动落点**：[frontend/src/features/execution-fabric/execution-fabric-service.ts:114-144](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/execution-fabric/execution-fabric-service.ts#L114)；[frontend/src/pages/ExecutionFabricPage.tsx:142-156,288-315](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ExecutionFabricPage.tsx#L142)。

**实施步骤**：

1. 近期100任务明确叫近期任务样本；真实按类型队列计数由服务端聚合。
2. Pool目录接现有Page分页，已选Pool/Runner按ID定位。
3. 显示统计更新时间、作用组织和样本范围。
4. 任务/事件需要历史浏览时补有界分页/游标，不用limit100伪装全量。

**API、模型与兼容**：增加只读队列聚合与必要分页，管理权限仍限系统管理员；不修改Lease/Fence状态机。

**验收与新增行为测试**：

- [ ] 150个排队任务时总览与分类型数量一致或样本标识清楚。
- [ ] 第101个Pool可到达。
- [ ] 无任务/失败/未加载不混成当前队列为空。

<a id="f-fab-02"></a>

#### F-FAB-02 · 执行面不定时刷新且没有任务/Lease详情定位

**优先级/批次/复杂度**：P2 / R4 / 大。对应 [审计证据](complete-audit.md#f-fab-02)。

**目标交互**：执行面有明确刷新节奏和任务/Lease证据链。

**改动落点**：[frontend/src/pages/ExecutionFabricPage.tsx:70-87,157-166,256-284,317-342](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ExecutionFabricPage.tsx#L70)。

**实施步骤**：

1. 查询增加适度可见页轮询/最后刷新时间与手动刷新，后台页暂停不必要轮询。
2. 任务ID打开只读详情，展示执行ID/Runner/Lease/Fence/重试/错误。
3. 展示已查询的Lease及相关事件，提供到工作流执行/报告入口。
4. 读取失败保留上次数据并明确过期，刷新不触发运行或状态动作。

**API、模型与兼容**：优先消费现有字段；任务/Lease按ID详情若未公开需管理员只读合同，不能借UI修改调度一致性。

**依赖**：[F-FAB-01](#f-fab-01)。

**验收与新增行为测试**：

- [ ] 外部Runner心跳/终态变化可在有界周期观察。
- [ ] 同任务多Lease/Fence可核对，失效Lease不显示当前有效。
- [ ] 刷新、查看和切页不创建Token、不Drain或重跑任务。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/ExecutionFabricPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/ExecutionFabricPage.test.tsx)
- [backend/tests/test_runner_fabric.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_runner_fabric.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

<a id="m26"></a>

### M26 · 平台管理

**目标任务与版式**：C 库存＋G 契约检查；按能力/插件/Runner选择对象并检查版本、Schema、Digest和安全边界；未开放的安装保持不可用。

**入口**：`/platform`。本模块实际已有功能见 [审计章节](complete-audit.md#m26)，不得以新页面替掉其原处理链。

<a id="f-plat-01"></a>

#### F-PLAT-01 · 切换插件/Runner后右侧仍展示上一个能力详情

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-plat-01)。

**目标交互**：右侧详情始终属于当前库存模式和选中对象。

**改动落点**：[frontend/src/pages/PlatformCapabilitiesPage.tsx:39-67,158-166,170-247,366-406](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PlatformCapabilitiesPage.tsx#L39)。

**实施步骤**：

1. 选择状态改为有类型的capability/plugin/runnerPool对象身份。
2. 切模式展示对应详情或明确请选对象，绝不保留上一类能力详情。
3. 插件展示版本/Digest/签名身份/状态，Runner展示池/成员/边界及合法执行面入口。
4. URL和页外补取恢复具体对象，普通角色只展示允许库存。

**API、模型与兼容**：现有Plugin/RunnerPool字段足够首版；不开放插件安装或管理写能力。

**验收与新增行为测试**：

- [ ] 本轮能力→插件空态不再显示assertion.evaluate详情。
- [ ] 插件、Runner选中与刷新保持正确类型。
- [ ] 无权限模式无先前对象残影，安装按钮仍不可用。

<a id="f-plat-02"></a>

#### F-PLAT-02 · 能力检查器没有提供已返回的完整Schema和策略字段

**优先级/批次/复杂度**：P2 / R4 / 中。对应 [审计证据](complete-audit.md#f-plat-02)。

**目标交互**：能力契约可完整只读核对。

**改动落点**：[frontend/src/pages/PlatformCapabilitiesPage.tsx:366-406](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PlatformCapabilitiesPage.tsx#L366)；[frontend/src/features/capabilities/capability-service.ts:17-51](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/capabilities/capability-service.ts#L17)。

**实施步骤**：

1. 检查器提供摘要/输入Schema/输出Schema/配置Schema/策略与来源页签。
2. 展示完整可复制哈希、插件Digest及已有来源关系，长结构按需展开。
3. 默认/最大超时、网络协议/DNS、Snapshot策略分别说明，不以固定成功文案代替实际字段。
4. 库存搜索/分页逐步接回，所有字段以返回值为准。

**API、模型与兼容**：消费现有CapabilityManifest，不增加任意执行或明文凭据访问。

**依赖**：[F-PLAT-01](#f-plat-01)。

**验收与新增行为测试**：

- [ ] 能查看并复制三份Schema且内容/哈希对应当前版本。
- [ ] 缺字段、未知策略和值很长时有明确降级。
- [ ] 切能力版本不串详情，显示不改变manifest或运行配置。

**本模块回归位置（后续开发按实际改动选择；不是本轮已全部运行）**：

- [frontend/src/pages/PlatformCapabilitiesPage.test.tsx](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/pages/PlatformCapabilitiesPage.test.tsx)
- [backend/tests/test_workflow_contract.py](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/backend/tests/test_workflow_contract.py)

界面修改先在对应页面/组件测试补本项公开行为；读取/授权/持久化合同有变更时再加服务/API集成测试。只更新截图或只测私有函数不构成完成。

## 4. 全局壳详细修改项

<a id="f-ux-01"></a>

### F-UX-01 · 全局搜索请求失败被显示成没有可访问资产

**优先级/批次/复杂度**：P2 / R1 / 小。对应 [审计](complete-audit.md#f-ux-01)。

**目标**：全局搜索故障与真实无结果区分。

**落点**：[frontend/src/features/search/GlobalSearch.tsx:31-62,76-79](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/search/GlobalSearch.tsx#L31)。

1. SearchEmpty接收isError/error/refetch，显示标准错误和可复制Trace ID。
2. 保留当前关键词和可用旧结果，说明旧结果时间；提供显式重试。
3. 空查询/加载/无结果/无权限/临时失败分别显示，限制自动重试确定性错误。

**合同**：无搜索API变更，不把失败结果缓存为成功的空目录。

**验收**：

- [ ] 本轮合成503显示错误而非未找到资产。
- [ ] 重试同关键词恢复；过期A搜索不覆盖B关键词。
- [ ] 键盘选择、清空和跳转仍可用。

<a id="f-ux-02"></a>

### F-UX-02 · 接口标签读取的缓存键少了版本维度，名称不能更新

**优先级/批次/复杂度**：P2 / R1 / 小。对应 [审计](complete-audit.md#f-ux-02)。

**目标**：接口对象标签使用真实名称与正确版本缓存。

**落点**：[frontend/src/features/navigation/WorkspaceObjectTabs.tsx:254-263](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/navigation/WorkspaceObjectTabs.tsx#L254)；[frontend/src/features/api-console/use-api-console.ts:398-402](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/api-console/use-api-console.ts#L398)。

1. 统一api-detail查询键工厂，在标签读取时使用实际版本维度或稳定资产摘要。
2. 标签名称从definition获取；未加载时暂用ID但成功后更新。
3. 当前/旧版本共享稳定资产名，保留完整href与用户项目隔离。
4. 不要用宽泛查询缓存取第一个不同版本结果。

**合同**：纯查询/展示修复，不新增网络请求读取秘密。

**验收**：

- [ ] 真实页面打开接口后标签显示审计健康检查。
- [ ] 切版本/重命名/刷新后名称和深链接一致。
- [ ] 无详情或错误时安全回退ID，不能显示别的资产名。

<a id="f-ux-03"></a>

### F-UX-03 · 对象标签页自动累积模块入口，重复承担第二份模块导航

**优先级/批次/复杂度**：P2 / R1 / 中。对应 [审计](complete-audit.md#f-ux-03)。

**目标**：全局对象标签用于对象工作，不累积第二套模块导航。

**落点**：[frontend/src/features/navigation/workspace-tab-store.ts:17-44](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/navigation/workspace-tab-store.ts#L17)；[frontend/src/features/navigation/WorkspaceObjectTabs.tsx:62-78](https://github.com/a3384379/FlowTest/blob/420d2e0cd30ff3f5c0519df8fcfd26b3bc2704e4/frontend/src/features/navigation/WorkspaceObjectTabs.tsx#L62)。

1. 仅对打开的API、Workflow和Report执行对象自动登记对象tab。
2. 普通模块访问只更新当前任务导航，不创建无对象标签。
3. 兼容读取旧模块tab：逐步清理无对象记录，保留真实对象href/名称/草稿和已有关闭确认。
4. 局部节点库/集合/用例目录继续随任务切换，不叠加宽全局侧栏。

**合同**：仅UI导航偏好；存储迁移不能删除草稿/session或改执行定义。

**验收**：

- [ ] 依次访问26模块后对象tab数量不随模块数增长。
- [ ] API/流程/报告多个对象可关闭、恢复与保留草稿。
- [ ] 旧存储迁移、坏数据、存储失败及键盘焦点都可用。

全局回归重点：GlobalSearch.test.tsx、WorkspaceObjectTabs.test.tsx、workspace-tab-store.test.ts、App.test.tsx及grouped-navigation.spec.ts。先修查询键，再移除无对象模块tab；不能把用户草稿和旧标签一起清空。

## 5. API/数据扩展清单

以下是完成现有任务闭环所需的查询/适配扩展，不代表可以新增任意执行能力。最终按仓库实际已有接口复用，API名称以实现设计为准，不在本文杜撰已经存在的路由。

| 合同范围              | 对应ID                                             | 最小要求                                                            | 数据库/迁移判断                                                            |
| --------------------- | -------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 项目范围Runner证据    | F-REL-01、F-REL-02/03                              | 项目read授权、分页/按ID、最小摘要、跨项目拒绝；不复用管理员全局目录 | 通常查询扩展即可；若加索引/模型须Alembic upgrade/downgrade                 |
| 完整目录/搜索/按ID    | F-SVC-01、F-PROTO-02、F-CT-01、F-TASK-02、F-ENV-02 | Page.total、稳定排序、精确对象补取，失效/无权限有标准错误           | 先复用现有表与查询；性能所需索引单独说明                                   |
| 统计/筛选同scope      | F-DASH-01、F-CASE-04、F-REP-04、F-IMP-02、F-FAB-01 | 明确period/filter/denominator/availability，不抓全量在前端算        | 不重写历史；查询聚合先用既有事实                                           |
| 身份搜索/摘要         | F-PRJ-02、F-ORG-03                                 | 仅可发现/可授权范围；普通Owner不能读取系统全量用户                  | 不保存或展示额外个人数据；无新字段时无需迁移                               |
| 目标/Mock只读预览     | F-TGT-02、F-DATA-02                                | 复用解析/模板语义，有界不可信输入，不发外部探测，不保存             | 不落库即可优先；不引入脚本解释器                                           |
| 固定审核基线/结果引用 | F-AIC-01、F-ENG-02、F-MCP-02、F-REG-01             | 能恢复真正before和物化ID；旧记录缺失明确说明                        | 如需增加持久快照，必须设计保留、大小边界与双向迁移，不能用当前资产伪造历史 |
| AI变更关闭态读取      | F-AIC-03                                           | list/get按项目授权允许历史只读；生成/审核写入仍受开关               | 服务授权拆分通常无需新模型；仍需租户/项目/角色集成测试                     |
| 节点来源/证据摘要     | F-REP-02/05、F-PROTO-04、F-CTX-01                  | 仅公开既有冻结身份/结构字段，兼容缺字段旧对象                       | 不新增诊断采集；可选DTO演进，禁止把秘密加入边界                            |
| 范围导出              | F-API-04                                           | 明确scope/ids/format、逐对象授权、有界集合                          | 复用当前包/版本语义，不在客户端拼假全量包                                  |

所有新增对外错误遵循标准envelope并含Trace ID。SQL/Redis/目标URL/上传Schema/模板/工作流都按不可信输入继续校验。query类型、稳定DTO和类型化接口优先，避免为本方案引入万能字典合同。

## 6. 明确单列的N类能力

| 新能力                                     | 当前能做什么                                                             | 若确需新增的前置工作                                                                 |
| ------------------------------------------ | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| 节点独立完整环境                           | 一条workflow一个environment_id；节点Service/Variant可以表达不同模块/地址 | 另行设计解析优先级、凭据/变量/快照、权限、缓存、计划执行和报告来源；不能只加环境下拉 |
| 持续健康/性能稳定性判定                    | 实例生命周期与单次健康/Seed、性能冻结指标；明确未提供持续采样/稳定性     | 先定义采样来源、时窗/样本、成本、故障/权限和算法证据，UI再消费                       |
| 新HTTP方法/节点/任意分支                   | 当前前后端枚举、28类节点和线性区域约束                                   | 先扩展模型/执行与兼容测试，不通过解除前端限制假实现                                  |
| until独立间隔/耗尽策略                     | 当前ConditionLoopPolicy；间隔可由区域等待节点表达                        | 明确引擎语义、版本兼容和终态证据，不能照抄概念图字段                                 |
| 任意插件安装/脚本/Compose                  | 受控内置能力和声明式模板；安装未开放                                     | 签名、隔离、供应/运行边界是独立能力，不在本次UI修复中开放按钮                        |
| 独立用例步骤引擎/自然语言自动修复/自动部署 | 用例绑定固定发布workflow；AI/MCP提供受控草稿；Release Gate仅判断         | 独立需求与执行/审核设计；不属于本次“与原UI一致”即可自动扩展的范围                    |

这些能力不计入73项修复的完成勾选；也不能作为现有交互差距一直不修的理由。可视化已有多服务/多步骤、接回已有Headers/Metadata等属于本方案正常范围。

## 7. 验证方案

### 7.1 开发过程

1. 每个模块开始前核对AGENTS、当前工作树/HEAD、设计与相关测试，列出本次ID和实际改动路径。
2. 给本轮P1反例和结构性重构补公开行为特征测试。网络竞态用可控延迟/请求序号，不用任意sleep反复碰运气。
3. 运行命名Vitest/后端定向测试。低风险纯显示更改不为了覆盖率写镜像实现测试；优先验证用户能看到/提交的行为。
4. 读取/鉴权/快照/共享状态/数据库或引擎涉及变化时，扩展受影响集成链和部署形态，而不是用一个页面mock通过当证明。
5. 每模块修复后按报告同一反例重走，再检查相邻关闭/返回/切换/只读状态。标记剩余未实测条件，不能重复同一无变化失败充当进展。

命令模板（先确认具体文件存在；不代表本轮已执行下面所有命令）：

```sh
make test-frontend-targeted TARGETS='["src/pages/ApiConsolePage.test.tsx"]'
make test-backend-targeted TARGETS='["tests/test_release_gate.py"]'
# 后端实际变更还需相关Ruff检查；跨文件类型受影响时运行mypy app。
# 前端实际变更运行受影响format/lint/type/build；合并风险需要时再运行make check。
```

### 7.2 关键专项矩阵

| 专项        | 必须覆盖的边界                                                              | 证据                                             |
| ----------- | --------------------------------------------------------------------------- | ------------------------------------------------ |
| 断言真值    | 保存断言为空/非空/无状态码/多规则，临时字段与版本切换                       | 实际payload、HTTP状态、冻结断言与最终结论一致    |
| 编辑保护    | 主/区域/嵌套、合法/非法JSON、应用/保存、关闭/切节点/切项目/历史、旧保存回包 | 用户输入和dirty最终状态，不只检查confirm被调用   |
| 异步身份    | A慢B快、同对象多请求、切项目/协议/版本、卸载/取消                           | 正确对象和最后请求结果；旧响应被忽略             |
| 目录完整    | 21/51/101条阈值、同名层级、页外ID、失效/无权限、过滤/排序                   | total、选中、下拉和实际提交ID一致                |
| 证据定位    | 默认/显式node、attempt、iteration/branch/subflow/instance已有身份、旧快照   | 报告↔编排↔计划↔回归↔门禁是同一冻结对象           |
| 权限/关闭   | 系统管理员、组织Owner/Admin/Member、项目Owner/Editor/Viewer、不同项目       | UI解释与服务端授权一致；可选功能关闭不伪装空数据 |
| 配置维护    | 多服务依赖、多HTTP步骤、多升压阶段、现有模板/Schema限制、JSON往返           | 保存/新版本和只读预览完整、不改旧冻结对象        |
| 指标口径    | total与page不同、enabled/disabled混合、空分母、未知/失败/关闭               | 正确分母与范围、无假0/满分/通过                  |
| 副作用      | 阅读/展开/切换/预览/错误重试与真正执行动作分离                              | 只读操作无Run/Apply/Publish/通知/Provision请求   |
| 视觉/无障碍 | 1440×900、1280×800、1600扩展、390证据/审核、长文/焦点/减少动效              | 真实页面截图与键盘操作，非原型截图               |

### 7.3 现有E2E复用路径

按改动选择既有workflow-editor交互/视觉、condition-loop-state-editor、s15-test-assets、s17-data-mock、s18-contract-automation、s19-quality-scale、s21-ai-review、s23/24-protocol、s25-performance、s26-environment、s27-contract、s29-execution-fabric、s49-context及MCP相关规格。涉及frontend/e2e或playwright配置时，按仓库要求运行Compose真实浏览器验收；不能由Vitest替代。

完整80项原设计矩阵的当前状态见审计报告第5.2节。修复后必须逐条回填具体commit、命令、截图与结果；未执行的保持待验证，不能把“26模块都打开过”换算成80项通过。

## 8. 分模块交付与完成判据

每一个修改ID完成时记录：

- [ ] 对应审计反例/源码差距确实消除，有实际改动文件及明确行为。
- [ ] 必要公开行为回归通过；测试覆盖失败/返回/跨对象状态，不只对比快照。
- [ ] API/模型有变化时类型、权限、标准错误和必要迁移/兼容验证完整。
- [ ] 真实页面可复核；外部依赖/低权限/大数据未验证时如实写明。
- [ ] 业务功能、秘密边界、固定版本/冻结报告、节点执行语义和已有入口无回退。
- [ ] 若合并，最新提交Required Gate/审核问题均处理，并绑定同一head；合并后CI另查。

| 完成层级            | 能证明什么                       | 不能替代                        |
| ------------------- | -------------------------------- | ------------------------------- |
| 本地修改＋定向测试  | 本次命名路径和场景通过           | 完整CI、真实角色/服务验收       |
| make check/集成矩阵 | 本地完整检查和指定集成路径       | 最新提交远程合并门禁            |
| PR最新head门禁      | 该提交达到受信风险计划的合并要求 | 合并后main CI/部署              |
| 合并与main CI       | 已进入GitHub目标分支及相应检查   | 生产运行、设备/真实外部系统验收 |
| 真实环境验收        | 指定安装/角色/数据规模已验证     | 未覆盖的其他安装/协议/权限组合  |

## 9. 回滚与剩余风险

UI/会话/查询更改按模块可回退，但回退不得清空数据库、草稿、用户session或一次性秘密。新只读合同优先兼容旧客户端，新增字段保持旧记录可读；若引入新持久快照或索引必须有明确Alembic升级/降级策略。功能开关关闭只能隔离可选能力，不能用作隐藏未修复的核心错误。

本轮没有实施上述业务变更。第一批开发应从R0开始，保留审计中已存在的能力，逐模块修复、复核后再推进下一批。所有外部AI/Broker/Runner/KMS/压测和容量条件的真实验收都需在相应测试环境实际执行，不能由本文或97条旧测试通过推断。

## 10. 问题—实施项追踪总表

| 问题ID                    | 模块   | 优先级 | 批次 | 复杂度 | 直接依赖            |
| ------------------------- | ------ | ------ | ---- | ------ | ------------------- |
| [F-DASH-01](#f-dash-01)   | M01    | P2     | R3   | 中     | 无直接前置          |
| [F-DASH-02](#f-dash-02)   | M01    | P2     | R3   | 中     | F-QLT-02            |
| [F-API-01](#f-api-01)     | M02    | P1     | R0   | 中     | 无直接前置          |
| [F-API-02](#f-api-02)     | M02    | P2     | R1   | 小     | 无直接前置          |
| [F-API-03](#f-api-03)     | M02    | P2     | R1   | 大     | 无直接前置          |
| [F-API-04](#f-api-04)     | M02    | P2     | R1   | 中     | 无直接前置          |
| [F-API-05](#f-api-05)     | M02    | P2     | R1   | 中     | 无直接前置          |
| [F-SVC-01](#f-svc-01)     | M03    | P2     | R2   | 中     | 无直接前置          |
| [F-SVC-02](#f-svc-02)     | M03    | P2     | R2   | 中     | 无直接前置          |
| [F-SVC-03](#f-svc-03)     | M03    | P2     | R2   | 中     | F-SVC-01、F-SVC-02  |
| [F-TGT-01](#f-tgt-01)     | M04    | P2     | R2   | 大     | 无直接前置          |
| [F-TGT-02](#f-tgt-02)     | M04    | P2     | R2   | 大     | 无直接前置          |
| [F-TGT-03](#f-tgt-03)     | M04    | P2     | R2   | 中     | F-TGT-02            |
| [F-PROTO-01](#f-proto-01) | M05    | P1     | R0   | 大     | 无直接前置          |
| [F-PROTO-02](#f-proto-02) | M05    | P2     | R2   | 中     | F-PROTO-01          |
| [F-PROTO-03](#f-proto-03) | M05    | P2     | R2   | 中     | F-PROTO-01          |
| [F-PROTO-04](#f-proto-04) | M05    | P2     | R2   | 大     | 无直接前置          |
| [F-PRJ-01](#f-prj-01)     | M06    | P2     | R2   | 中     | 无直接前置          |
| [F-PRJ-02](#f-prj-02)     | M06    | P2     | R2   | 大     | 无直接前置          |
| [F-WF-01](#f-wf-01)       | M07    | P2     | R1   | 中     | 无直接前置          |
| [F-WF-02](#f-wf-02)       | M07    | P2     | R1   | 大     | F-WF-04             |
| [F-WF-03](#f-wf-03)       | M07    | P2     | R1   | 中     | F-WF-04             |
| [F-WF-04](#f-wf-04)       | M07    | P1     | R0   | 大     | 无直接前置          |
| [F-CASE-01](#f-case-01)   | M08    | P2     | R1   | 小     | 无直接前置          |
| [F-CASE-02](#f-case-02)   | M08    | P2     | R1   | 中     | 无直接前置          |
| [F-CASE-03](#f-case-03)   | M08    | P2     | R1   | 小     | 无直接前置          |
| [F-CASE-04](#f-case-04)   | M08    | P2     | R1   | 大     | 无直接前置          |
| [F-DATA-01](#f-data-01)   | M09    | P2     | R2   | 中     | 无直接前置          |
| [F-DATA-02](#f-data-02)   | M09    | P2     | R2   | 大     | F-DATA-01           |
| [F-CT-01](#f-ct-01)       | M10    | P2     | R2   | 大     | 无直接前置          |
| [F-CT-02](#f-ct-02)       | M10    | P2     | R2   | 中     | 无直接前置          |
| [F-ENG-01](#f-eng-01)     | M11    | P2     | R2   | 小     | 无直接前置          |
| [F-ENG-02](#f-eng-02)     | M11    | P2     | R2   | 中     | 无直接前置          |
| [F-ENG-03](#f-eng-03)     | M11    | P2     | R2   | 大     | 无直接前置          |
| [F-TASK-01](#f-task-01)   | M12    | P2     | R2   | 大     | 无直接前置          |
| [F-TASK-02](#f-task-02)   | M12    | P2     | R2   | 中     | 无直接前置          |
| [F-ENV-01](#f-env-01)     | M13    | P2     | R2   | 大     | 无直接前置          |
| [F-ENV-02](#f-env-02)     | M13    | P2     | R2   | 中     | 无直接前置          |
| [F-PERF-01](#f-perf-01)   | M14    | P2     | R2   | 大     | 无直接前置          |
| [F-PERF-02](#f-perf-02)   | M14    | P2     | R2   | 中     | 无直接前置          |
| [F-REP-01](#f-rep-01)     | M15    | P2     | R1   | 中     | 无直接前置          |
| [F-REP-02](#f-rep-02)     | M15    | P2     | R1   | 大     | F-REP-01            |
| [F-REP-03](#f-rep-03)     | M15    | P2     | R1   | 中     | F-REP-01            |
| [F-REP-04](#f-rep-04)     | M15    | P2     | R1   | 大     | 无直接前置          |
| [F-REP-05](#f-rep-05)     | M15    | P2     | R1   | 中     | F-REP-01            |
| [F-IMP-01](#f-imp-01)     | M16    | P2     | R3   | 大     | 无直接前置          |
| [F-IMP-02](#f-imp-02)     | M16    | P2     | R3   | 小     | 无直接前置          |
| [F-REG-01](#f-reg-01)     | M17    | P1     | R0   | 大     | 无直接前置          |
| [F-REG-02](#f-reg-02)     | M17    | P2     | R3   | 中     | 无直接前置          |
| [F-REG-03](#f-reg-03)     | M17    | P2     | R3   | 中     | F-TASK-02、F-REP-01 |
| [F-QLT-01](#f-qlt-01)     | M18    | P2     | R3   | 小     | 无直接前置          |
| [F-QLT-02](#f-qlt-02)     | M18    | P2     | R3   | 大     | 无直接前置          |
| [F-REL-01](#f-rel-01)     | M19    | P1     | R0   | 大     | 无直接前置          |
| [F-REL-02](#f-rel-02)     | M19    | P2     | R3   | 大     | F-REL-01            |
| [F-REL-03](#f-rel-03)     | M19    | P2     | R3   | 中     | F-REL-01、F-TASK-02 |
| [F-AI-01](#f-ai-01)       | M20    | P2     | R4   | 大     | 无直接前置          |
| [F-AI-02](#f-ai-02)       | M20    | P2     | R4   | 中     | 无直接前置          |
| [F-CTX-01](#f-ctx-01)     | M21    | P2     | R4   | 大     | 无直接前置          |
| [F-AIC-01](#f-aic-01)     | M22    | P2     | R4   | 大     | 无直接前置          |
| [F-AIC-02](#f-aic-02)     | M22    | P2     | R4   | 中     | 无直接前置          |
| [F-AIC-03](#f-aic-03)     | M22    | P2     | R4   | 大     | 无直接前置          |
| [F-MCP-01](#f-mcp-01)     | M23    | P2     | R4   | 中     | 无直接前置          |
| [F-MCP-02](#f-mcp-02)     | M23    | P2     | R4   | 大     | 无直接前置          |
| [F-ORG-01](#f-org-01)     | M24    | P2     | R4   | 中     | 无直接前置          |
| [F-ORG-02](#f-org-02)     | M24    | P2     | R4   | 中     | 无直接前置          |
| [F-ORG-03](#f-org-03)     | M24    | P2     | R4   | 中     | 无直接前置          |
| [F-FAB-01](#f-fab-01)     | M25    | P2     | R4   | 大     | 无直接前置          |
| [F-FAB-02](#f-fab-02)     | M25    | P2     | R4   | 大     | F-FAB-01            |
| [F-PLAT-01](#f-plat-01)   | M26    | P2     | R4   | 中     | 无直接前置          |
| [F-PLAT-02](#f-plat-02)   | M26    | P2     | R4   | 中     | F-PLAT-01           |
| [F-UX-01](#f-ux-01)       | GLOBAL | P2     | R1   | 小     | 无直接前置          |
| [F-UX-02](#f-ux-02)       | GLOBAL | P2     | R1   | 小     | 无直接前置          |
| [F-UX-03](#f-ux-03)       | GLOBAL | P2     | R1   | 中     | F-UX-02             |
