# FlowTest 流程编排：Codex 分阶段代码实施任务书

> 规格版本 1.0，源码校准日期 2026-09-13。基线 `b445786a0441d3b87b77cc95ce250ad99d9b36a7`。  
> 本文件是未来开发指令与阶段门槛，不是执行日志。所有测试编号的初始状态均为“未执行”。  
> 最高优先级依据为《FlowTest_流程编排_代码级实施方案.md》。本文不得据 UI 图扩展后端协议。

## 1. 执行方式：固定上下文、小任务交付、逐阶段复审

把整个交付目录置于仓库文档目录，例如 `docs/workflow-editor-codeplan/`。路径可不同，但文档和 assets/fixtures 的相对关系不变。Codex 启动时定位真实路径，不凭印象重新生成一份需求。

每次只授权一个任务或一段已明确的连续任务。推荐首轮仅执行 T00–T01，之后按 T02 → T03 → T04 → T05 → T06 → T07 → T08 → T09 → T10 → T11 推进。不要把“分任务”理解成每项独立重造状态层，所有阶段必须共用上一阶段的实现。

当前 HEAD 比基线新，不等于不能开发。先比较与本功能相关的变化；已修复内容直接复用，发生冲突的规格先登记。禁止为了匹配文档 checkout 旧提交覆盖用户修改。

### 1.1 一次性总控提示词

```text
你正在修改 a3384379/FlowTest 的流程编排模块。

先阅读：
1. 仓库 AGENTS.md、编码与贡献说明、当前工作区状态。
2. docs 中本交付包的 FlowTest_流程编排_代码级实施方案.md。
3. 源码校准与偏差修正清单.md、source-baseline.json。
4. 本次任务段以及回归验收矩阵中对应编号。

目标是修复真实页面的可编辑性和可用性，不是另做一个演示页面。
用户目标：画布/配置可调大小与最大化、简化节点入口、连线可删除、
焦点内快捷键、清晰布局，并保持已有草稿/版本/MCP/执行语义。

计划基线 b445786a0441d3b87b77cc95ce250ad99d9b36a7。
不要假定当前 HEAD 仍相同。先检查真实源码及 lockfile，列出相关差异。
先读后改，不扫描数据库、不访问真实收费/开票接口，不部署生产。

固定约束：
- 保留 React + Ant Design + @xyflow/react，使用现有锁定依赖，不升级。
- WorkflowDefinition 是持久化定义，现有 useWorkflows 是草稿权威。
- 所有图修改走统一 command/history/onChange，UI selection/viewport 不落业务图。
- 边只用 null/true/false，比较规则在 Condition 节点；映射仍在 edge.mappings。
- 不新增后端边 CRUD、任意边表达式、实时单步调试或通知节点。
- 不削弱后端 DAG 校验、expected_revision、权限、预算或阶段隔离。
- 完整保留 auth_mode/suppressed_*/replace_headers/polling/runtime_inputs/
  run_policy/cleanup/configuration/bindings/json_parse 等已有字段。
- 自动脱敏默认 OFF，遵守当前项目策略，不新增扫描、屏蔽或日志收集。
- Delete 受焦点、输入法、输入框、弹层、只读守卫约束；Tab 保留原生导航。
- 运行/历史/提案复用同一图组件但只读；不让新布局破坏嵌入式调用。
- 不创建空测试、全 mock 演示或无真实请求链的伪按钮来宣称完成。

每个任务必须：
A. 输出“需求 -> 现有源码 -> 拟改文件 -> 测试编号”的简表。
B. 先补能暴露目标问题的测试，再做最小实现。
C. 核对字段/副作用/模式边界；运行本任务可执行的检查。
D. 输出实际修改、计划符号与真实符号映射、测试证据和未执行项。
E. 门槛未通过，不擅自跳入下一任务；不删除失败测试掩盖问题。

仅执行本次明确指定的任务。涉及提交、创建分支、安装依赖、启动 Compose、
访问外部服务时遵守本次授权和仓库规则；没有授权不自动执行。
不得 reset --hard、批量转码、覆盖用户未提交修改或强制推送。
```

### 1.2 单任务启动模板

```text
本次执行：T__。
已完成前置任务：____（附上一阶段证据路径/提交）。
请读取本任务段及其矩阵编号，只实施本段职责。
先校准当前代码；已有正确实现不要重做；新增变化必须测试。
输出开工简表，再实施，再交付检查结果。
若发现计划与源码矛盾：记录事实与两种影响，提出最小修正规格，
不能以“模型认为更合理”为理由擅自改数据格式或删除既有能力。
```

## 2. 每轮自校准标准

| 检查点 | 必须回答的问题 | 失败时处理 |
|---|---|---|
| 开工前 | 实际文件/函数是否存在？基线差异是什么？ | 修正路径和事实，不虚构 API |
| 建模后 | 哪些是持久化字段、哪些仅 UI？是否完整保留已有数据？ | 先修类型/合成算法 |
| 接事件后 | 鼠标、按钮、键盘是不是同一路径？事件触发几次提交？ | 补事务计数测试 |
| 配置后 | 输入/取消/最大化/离页是否丢原始值？ | 补会话和冲突保护 |
| 联调后 | 保存的是本地还是服务端？运行的是哪一版本？ | 改文案与请求链，不能伪报 |
| 收尾前 | 截图、测试与代码是否对应同一版本？ | 重新采集，不引用旧证据 |

每项结论必须指向源码符号、测试名称或实际截图；“已检查”“理论可行”不能替代结果。

---

## T00：固定源码和调用链基线

**前置：** 文档目录可读，当前仓库身份明确。

**必须读取：** source-baseline.json 中 S01–S20 对应文件；实际 `pnpm-lock.yaml`、前端 tsconfig/eslint 配置；搜索全部 WorkflowDesigner 调用方。后端仅核对 graph/config/preview 契约，不改引擎。

可用的只读定位命令（在真实仓库使用；本文未执行）：

```bash
git status --short
git rev-parse HEAD
git log -5 --oneline
rg -n "WorkflowDesigner|useWorkflows|useWorkflowTabs" frontend/src
rg -n "deleteKeyCode|onNodesChange|onEdgesChange|onReconnect" frontend/src
rg -n "runtime_inputs|suppressed_headers|json_parse|validate_graph" backend/app
rg -n "@xyflow/react|antd|packageManager" frontend/package.json frontend/pnpm-lock.yaml pnpm-lock.yaml
```

最后一行只对仓库实际存在的锁文件运行；找不到先列文件，不把报错当作仓库坏了。Git 仅适用于本 FlowTest 仓库，不能把其他 Java/SVN 项目习惯套进来。

**交付：**

1. 记录当前 commit、是否有用户未提交修改、与计划基线的相关差异。
2. 核对实际安装/锁定 React Flow、Drawer、Splitter 属性；不能以线上最新文档替代当前类型。
3. 绘出文本调用链：页面 -> useWorkflows -> Designer -> Inspector -> onChange -> 草稿存储 -> PATCH。
4. 搜索并列出提案/历史调用方、API 请求编辑器复用点、现有 E2E 文件。
5. 确认 `DraftSessionProvider` 是否置于 Data Router 中，旧导航保护和新会话保护的衔接位置。
6. 将锁文件解析、未读取后端测试路径等补进开工记录，区分“事实”“拟议”。

**范围：** 不写生产代码；只新增开工/校准记录。

**验收编号：** BASE01。未经当前源码核对不得进入大规模改造。

---

## T01：刻画现状与建立回归样例

**前置：** T00 完成。

**读取：** 原 WorkflowDesigner/NodeInspector/ApiRequestEditor/use-workflows/use-workflow-tabs 的测试，以及 Playwright auth/setup/fixtures 的实际实现。

**步骤：**

1. 先运行已授权的原有定向测试，记录既有失败；不要先改预期让测试变绿。
2. 将交付包 8 个 JSON 作为合成输入引入测试。使用仓库真实后端模型验证结构和节点配置；资产 ID 由测试 seed 替换，不接真实业务。
3. 对选择节点不应改变 JSON、只读模式、旧单节点复制、已固定 API 版本等记录基线。
4. 新缺陷测试先证明失败原因：选中线无完整删除链、拖动产生多次写入、请求扩展策略被重建丢失等。
5. 不要把“来源节点默认 End”继续当正确产品目标；保留现状说明，然后新测试明确选中 API 优先。
6. 07-disconnected 样例必须为负例，验证本地可表示但服务端模型拒绝。其他样例仅结构合法不代表存在运行资产。

**交付：** 现状测试清单、原失败日志、fixture 使用说明、每个待修缺陷对应红色测试或明确未执行原因。

**范围：** 测试与测试数据为主，尚不重写页面。测试失败可以是预期复现，但必须标明红测，不得标为阶段实现完成。

**验收编号：** BASE02–BASE03。

---

## T02：类型补齐、字段保留与图分析纯函数

**前置：** 已有问题复现测试。

**生产文件：** `lib/api.ts`、新增 `editor/editor-types.ts`、`editor/request-overrides.ts`、`editor/graph-analysis.ts`；只有需要接入时最小修改已有 helper。不要引入新持久化图格式。

**实现细则：**

1. 前端类型补入 optional runtime_inputs，mapping transform 补 json_parse；不为每条旧 JSON 注入默认字段。
2. 声明显式 EditorSelection、GraphEditResult、位置更新和诊断类型；不把 UI Node 当领域 Node。
3. 实现 effective node kind：只在匹配 capability ID + 固定版本时映射 legacy 类型；未知能力不猜测。
4. 图分析建立 nodeById/incoming/outgoing 索引；遍历均有 visited；缺失节点与不合法边返回诊断而非无限递归。
5. 完整诊断区分 main 连通与 cleanup 引用，检查 conditions、endpoint、acyclic、mapping endpoint、数据集数量等。
6. 请求覆盖编辑采用“clone 原对象 -> 仅替换三个管辖键”，保留 authentication suppression、replace_headers 和未来合法字段。
7. 不修改原对象，不改变节点/边数组顺序。no-op 返回 unchanged；非法有限数坐标整批 blocked。
8. 展示无法编辑的已知扩展策略摘要，不重置未知字段，不宣称所有模板继承。

**应补真实断言：**

- 对输入 deep freeze；操作不抛因原地赋值产生的异常，不污染输入。
- fixture04 仅修改 Body.filter，期望 auth_*、suppressed_*、replace_headers、polling、runtime_inputs、run_policy 深度相等。
- fixture06 改节点名称，json_parse 与 transform.template 保留。
- fixture05 不能被“所有节点必须从主 Start 可达”误报；cleanup_for 的非法引用应被发现。
- 同一 effective start 的不同表示获得相同删除保护结果。

**验收编号：** DATA01–DATA07。与实际后端校验矛盾时先修诊断器，不修改后端 validator。

---

## T03：受控选择、统一控制器与历史基础

**生产文件：** `WorkflowDesigner.tsx`、新 `WorkflowCanvas.tsx`、`editor/canvas-adapter.ts`、`editor/editor-history.ts`、`editor/use-workflow-editor.ts`。

**实现细则：**

1. 把领域 definition -> CanvasNode/CanvasEdge 提取为单向 adapter；继续展示原 runtime/proposal 状态。
2. selection 使用 nodeIds/edgeIds/primary；adapter 的 selected 与业务选择保持一致。
3. onNodesChange/onEdgesChange 的 select 分批更新 UI；click 只确定 primary，不能清空本次框选；PaneClick 统一取消。
4. `deleteKeyCode={null}`；此阶段尚未接删除功能时不允许隐式删除。
5. 所有领域命令进入单一 dispatcher；只读入口统一守卫，不依赖 disabled 按钮。
6. 历史保存完整 definition 的 before/after 与选择快照，上限50；no-op/选择/缩放不进入历史。
7. 控制器事件层完成“读最新状态 -> pure helper -> 更新 latest ref -> 更新 history -> onChange 一次”。不要在 reducer/updater/effect 重放外部副作用。
8. 父层 echo 使用 JSON 深度语义比较；连续两次命令发生于 React 批量渲染前时，第二次必须读取第一次的最新 ref，不能丢第一次修改。
9. 收到不同 identity/外部导入替换，取消过期 gesture/dialog 并清空不适用历史；只改变服务端 revision 而内容未变，不清空历史。
10. 设置可选 surface，默认embedded，页面显式workspace；保持全部既有公共 props 可用。

**验收编号：** SEL01–SEL06、HIST04–HIST10。补连续两次命令和 StrictMode 测试。通过后才能让其他入口接 dispatcher。

---

## T04：删除、连线、重连、边映射全链路

**生产文件：** `editor/graph-commands.ts`、`workflow-graph.ts`、`WorkflowCanvas.tsx`、`WorkflowEdgeInspector.tsx`；节点 Inspector 只改其映射入口，不复制新数据模型。

### T04-A 删除

1. 实现 planDeletion：保护 effective Start 和唯一 main End；计算所有 incident edges。
2. 对仍保留节点的 source_node_id、expected_source_node_id、cleanup_for 与可识别 capability 引用做检查。
3. 硬引用存在就 blocked；普通单线无映射直接删除+undo；映射/条件/多选按主规格确认。
4. 一个确认动作只提交一次；重复键、异步弹框期间点击其他删除不重复创建事务。
5. Modal 确认回来重新读取当前scope/definition并重算；变化则取消或重确认，不能回写捕获的旧图。
6. Delete、右键、浮动条、Inspector 底部按钮共用 requestDelete，不分别过滤数组。
7. undo 恢复原ID、condition、映射行和节点配置；不自动跨过已删断言创建新边。

### T04-B 连接/重连

1. 条件输出使用 true/false UI Handle，普通输出 out；只派生到 React Flow，不持久化 sourceHandle。
2. 连线ID由事件层生成 edge-UUID，长度不超过128；测试传入固定ID。
3. invalidConnect 可用于即时反馈，最终 commit 仍需同一 helper 再验，避免只验证拖动预览。
4. 重连候选图先去掉旧边参与校验；保持边ID，不 delete+add 分两步。
5. 映射端点变化确认后同步 source/target.node_id；保留原 path/transform/key 并要求用户检查兼容性。
6. onReconnectEnd 松开在空白处不是删除指令；取消仍保留原边。
7. 普通边禁止 condition 非空；条件源两分支允许相同目标，不能因 source/target 相同误去重。
8. 两个已占用分支提供原子交换，不开放生成两个true的下拉修改。

### T04-C Inspector 映射

1. 显示真实 source/target 名称与只读 ID、条件含义、映射计数、删除入口。
2. 比较表达式仍由 Condition 节点配置；不要显示 `response.code == 0` 的任意边脚本编辑框。
3. 入站映射必须明确选入边；新边 Inspector 与原节点入站入口编辑同一 edge.mappings。
4. mapping 行保留 transform 即使本期不编辑它；目标不支持请求参数时不能假装普通 Body 映射可用。

**验收编号：** DEL01–DEL08、EDGE01–EDGE09；在真正受控 ReactFlow harness 和浏览器补至少一条选线删除用例，不只测纯数组。

---

## T05：手势事务与焦点内快捷键

**生产文件：** `use-workflow-editor.ts`、`use-canvas-hotkeys.ts`、`WorkflowCanvas.tsx`、`WorkflowShortcutHelp.tsx`。

**实现细则：**

1. dragStart 捕获选择集及初始位置；position changes 只更新 transientPositions；dragStop 用事件最终坐标提交一次。
2. 多选移动共用一个事务。取消/失焦/切换视图恢复起点；外部替换图时取消旧gesture。
3. 键盘方向移动由库触发时仍可提交，不能因为仅关注dragStop让键盘移动失效。
4. 容器tabIndex与可见focus样式；hover不抢焦点。下钻检查composedPath，Portal合成冒泡不能触发画布删除。
5. 键位按主规格：Delete/Backspace、Ctrl/Cmd C/V/Z/ShiftZ/A、WindowsCtrlY、Enter、Shift+A、Space、F、Esc、?；Tab保持原生。
6. input/textarea/select/contenteditable/combobox/textbox及IME不接管；modal/drawer/confirm打开时禁止画布修改。
7. 未找到内部clipboard、无历史或当前动作不可用时不吞浏览器原按键。
8. 单节点剪贴板只在当前资源内存；Start不可复制，重复Dataset不可粘贴，多选复制明确不可用。
9. Esc一次处理一层；可写快捷键命令与只读查看操作分离；按钮标题显示同一键位表。
10. onChange与local draft store调用计数必须匹配一整个手势，而不是pointermove数量。

**验收编号：** HIST01–HIST03、KEY01–KEY10，重跑SEL与DEL。UI“有快捷键帮助”不等于快捷键已实现。

---

## T06：响应式分栏、可调宽与专注模式

**生产文件：** `WorkflowsPage.tsx`、`WorkflowInspectorShell.tsx`、`use-workspace-layout.ts`、`workflow-editor.css`；按需最小调整 App 的 workflow route class。

**实现细则：**

1. 先梳理真实高度链；normal模式保留应用顶栏、项目页签，工作区填满剩余可用高度。
2. 原工作流大表格缩为紧凑列表，默认220px；画布为主，不常驻额外节点库列。
3. 复用当前Antd Splitter，Panel为直接子节点；onResize只UI，onResizeEnd写布局偏好。
4. 工作区宽不足1240先折叠列表；Canvas560+Inspector320仍放不下时Inspector覆盖展示，不横向挤压。
5. 无选择默认关闭Inspector；打开、拖宽、折叠之间不改变定义/dirty/history。
6. 偏好校验finite/range，响应式临时折叠不覆盖用户偏好。坏JSON/存储满不阻断画布操作。
7. 专注模式只改变同一容器布局/样式，不重建ReactFlow；viewport/selection返回后保持。
8. 全屏配置不同于画布专注；覆盖层z-index、焦点与Esc均按实际Antd版本验证。
9. 原运行console/debug/history搬到可折叠区域仍可访问；不得为了腾空间删功能。
10. proposal/dialog继续embedded固定合理高度；不能继承全屏fixed布局或百分比零高度。

**验收编号：** LAY01–LAY08。屏幕1440×900、1920×1080、1280×800；必须测真实页面，不只截单组件。

---

## T07：事务式节点配置、请求抽屉最大化、离页恢复

**生产文件：** `WorkflowNodeInspector.tsx`、`WorkflowApiRequestEditor.tsx`、`WorkflowInspectorShell.tsx`、`editor/use-node-edit-session.ts`、`editor/editor-types.ts`；现有 `features/drafts/draft-session.ts` 增量类型化Map，Provider按需修改不改变旧草稿语义。

### T07-A 会话与输入

1. session保存baseNode/draftNode/generation/dirty/rawFields/activeTab/requestDraft，状态在现有DraftSession内存可恢复。
2. 节点输入不逐字符触发wholegraphonChange，Apply一次replace-node历史；不开放nodeID重命名。
3. 非法JSON不清空、不静默回原值；当前raw,error和模式必须保留；不能用JSON.stringify值作为不断变化key导致重挂载。
4. 选择切换先处理dirty会话；当前节点外部删除永远不能Apply复活。
5. 只有position变化时保留最新position；config等内容变化阻断旧session覆盖。
6. dirty会话与工作流storagefailure使用不同unsafe keys，不能互相解除保护。
7. Map只保存未应用配置和raw，不保存响应或诊断日志；Apply/明确discard才清除，路由unmount不清除dirty。
8. 返回资源时restore前检查baseline；注销清理对应内存，不把上个用户值带给下个用户。

### T07-B 请求编辑器

1. 复用现有BodyEditor、批量Header/Params编辑，不重写一套表单。
2. 移动Drawer尺寸/最大化时同一个FormInstance与session不重建。
3. Params/Headers/Body inherit/custom切换保留各custom草稿；Headers继承不擅自清空auth suppression。
4. 保存请求与节点基础信息合成一次node替换，保留三个管辖键之外全部config。
5. 固定版本详情失败就错误，不能静默用最新版本；升级是明确操作，不伴随一次普通名称修改。
6. 不因全屏图画了“发送请求”就新增自动执行；保持模板preview与真实运行结果区分。
7. preview把现有serviceOverride/endpointVariant传对；有不支持的策略列出限制或禁用不准确预览。
8. 布局切换和模板后台refetch都不能覆盖正在输入的原始文本。
9. 顶部保存/发布/运行遇未Apply配置先引导Apply验证或返回；验证失败无后续网络写入。

**验收编号：** FORM01–FORM12、DATA01–DATA07、LIFE11–LIFE12；路由/全局保存部分在T09补最终集成，但本阶段不得留“后续必做”而声称闭环已完成。

---

## T08：工具栏瘦身、节点库和上下文新增

**生产文件：** `WorkflowEditorToolbar.tsx`、`WorkflowNodeLibrary.tsx`、`editor/node-registry.ts`、现有 `workflow-graph.ts` / ApiPicker提取后的组件。

**实现细则：**

1. 原有多个Select+Button从主工具栏移出，统一添加节点，常用/高级/搜索有清晰用途。
2. registry有限列举当前真实支持类型及依赖；不接受任意插件自执行、不把名字当后端type。
3. HTTP、提取、断言、条件、等待优先；数据集、只读SQL/Redis、GraphQL/gRPC/Kafka/WebSocket、子流程/ForEach按类访问。
4. START自动存在，不用一个可无限点击的“新增开始节点”破坏边界约束。
5. 依赖不可用显示原因和正确配置入口；禁止生成空credentialId/虚构API资源后宣称可运行。
6. 复用API分页搜索、乱序响应防护、当前选中项按ID查询；不要一次性拉整个项目全部接口。
7. 拖拽使用screenToFlowPosition(clientX,clientY)；点击新增在可见中心；新增后选中节点但不反复fitView。
8. 断言/提取的source优先用户选中输出节点；未知来源显示待配置，不能继续默认End。
9. 为新提取变量提供不覆盖已有变量的建议名；自动布局仅位置变更。
10. “拖到线上插入”并非基础门槛，可不实现；若实现，只按主规格允许的无映射普通边原子插入。

**验收编号：** PAL01–PAL06，并回归所有既有高级节点测试。调整旧按钮测试为新路径是允许的，删除测试覆盖本身不允许。

---

## T09：草稿、发布、执行、历史与提案集成

**生产文件：** `WorkflowsPage.tsx`、`use-workflows.ts`、`workflow-service.ts`，现有tabs/draft/Proposal仅需要时最小修改。

**实现细则：**

1. 三种状态明确：表单未应用、本地流程已保存、服务端草稿已保存；运行版本另显示。
2. 不完整图可在本地编辑/恢复，但服务端保存前诊断；不弱化WorkflowDraftUpdate.definition校验。
3. `expected_revision/baseRevision/editVersion/generation/rebase`沿用现有算法，布局变化不递增业务editVersion。
4. 测试保存请求进行中继续编辑、切到其他工作流、discard后旧请求返回、409冲突、localStorage失败、多页签关闭。
5. 全部返回值错误传播保持；不把runMutation抛错吞掉后继续publish/execute。
6. 发布明确服务端草稿与本地未保存差异；不隐式保存/发布/运行串连。
7. 执行调用可扩展可选version，使用后端已有version字段；保留Idempotency-Key。没有目标环境/版本显示原因。
8. 未应用表单遇顶栏动作先完成T07约定。即使弹框用户已确认，一旦资源变化仍需取消过期动作。
9. runtime/history继续用实际snapshot，不用draft覆盖；proposal只读mode和原props继续工作。
10. 保留FlowSpec导入/MCP提案/RepairDialog/URL focus与proposal/工作区页签；不强行把审批流程改成普通草稿写入。
11. 图形Diff、单步恢复不在本期；已有版本差异和断点前运行正常展示。后端存在cancel能力与否必须依据实际路由，不给未接入按钮伪造成功结果。
12. 发布缺少expected_revision原子校验属于明确后续风险，不使用前端doublecheck宣称跨用户并发已彻底解决。

**验收编号：** LIFE01–LIFE12，FORM11–FORM12，DEL07–DEL08，所有原use-workflows/use-workflow-tabs回归。

---

## T10：真实交互、视觉与跨模式验收

**前置：** T02–T09局部测试均有结果，真实测试环境明确授权。

**拟新增E2E：** `frontend/e2e/workflow-editor-interactions.spec.ts` 与 `workflow-editor-layout.spec.ts`。复用现有认证/seed，遵守串行worker=1。

**必须覆盖的真人路径：**

1. 从页面选项目/工作流，新增API/断言，连接，配置，保存；整个过程中没有偷偷访问被测业务。
2. 真实点击SVG连线命中区域，Delete删除、Undo恢复，包括映射与branch。
3. 拖动节点，保持手势结束的坐标；连续变更只有一次草稿写入；多选可移动删除。
4. 鼠标停画布、焦点仍Header输入框，Delete只删文字；IME合成期不执行画布命令。
5. 调宽右栏、配置最大化缩小，保留非法JSON和typed字段；导航离开再返回保留会话。
6. 宽窄窗口切换保持原viewport；embedded提案无fixed污染；run/history不能改。
7. 运行隔离mock资产，记录实际版本、请求快照与输出；非HTTP断言节点不能凭空显示HTTP200。
8. 页面normal/focus/full config/edge选中/节点库/历史，在三档尺寸采集截图；确认没有遮挡关键按钮和横向滚动。

**证据：** 测试文件和test title、命令退出状态、HTML report/trace/screenshot路径。只在真实存在时给出路径；不能伪造Actions链接或写“全绿”。

**验收编号：** ACC01–ACC03，外加全部标记浏览器层的编号。不要把不同版本截图混成一套验收证据。

---

## T11：范围复审、文档同步与交付判定

**步骤：**

1. 对照R01–R07逐项填写实际实现文件/符号/测试，任何空白都不能整体标为完成。
2. 搜索高风险反模式：`deleteKeyCode`重复监听、UI字段进定义、`request_overrides:{}`无意清空、node ID改写、`as any`、空测试、mockReactFlow覆盖全部测试、fakeStep/fakeRun按钮。
3. 检查新增文件确实接入真实路由，不是放在unused/demo目录。
4. diff范围核查：没有无关后端引擎/数据迁移/依赖升级/全站样式重置；没有改变默认脱敏策略。
5. 重跑授权的format/lint/test:coverage/build；服务端结构契约与真实E2E记录不能省略为“理论已覆盖”。
6. 已知平台/并发限制写入文档，禁止用UI承诺超出服务器契约的行为。
7. 记录实际符号映射、截图目录、测试状态、未通过/未执行项和回滚单元。
8. 提交或PR仅按用户授权；最终报告不用一句“全部完成”掩盖欠缺。

**验收编号：** ACC04–ACC05，以及全部必需矩阵。阶段完成 != 项目发布通过；只有必需行为和对应真实验收满足才给发布通过结论。

---

## 3. 阶段报告与可恢复执行上下文

每个任务在仓库实际docs路径保存一份进度记录。下列字段是执行时填写，不要预填PASS。

```text
任务编号/起始HEAD/结束HEAD：
本任务对应需求：
真实阅读文件与重要差异：
计划符号 -> 实现符号 -> 文件：
本次修改文件及必要性：
领域字段新增/删除：应为无新增协议（前端补已有类型除外）
输入 -> 操作 -> 领域变化 -> history条数 -> 草稿写入次数：
只读/焦点/跨资源保护：
矩阵编号 -> 实际测试文件/test title：
已执行命令 -> 退出码 -> 证据：
未执行项 -> 原因 -> 阻断范围：
与计划偏差 -> 是否已调整规格：
下一任务前置是否满足：
```

模型上下文不足时只保留：基线+当前HEAD、本任务ID、真实修改文件、必须保持的领域契约、失败测试与下一步。不要仅留“UI优化进行中”。新会话继续前重新读上一任务报告与当前diff，避免第二个模型把已完成部分覆盖。

## 4. 失败处理的固定规则

| 情况 | 允许 | 不允许 |
|---|---|---|
| 找不到计划文件 | 搜索真实符号，登记等价路径 | 造一个同名空文件伪装存在 |
| 库属性类型不匹配 | 读锁定版本类型，采用等价受支持接口 | 升级大版本或as any压过去 |
| 旧测试表达坏体验 | 保留原因说明，新增正确目标用例后改预期 | 批量删除相关测试 |
| 只读被键盘绕过 | 修统一守卫并补跨入口测试 | 只隐藏Delete按钮 |
| 不完整图不能服务端存 | 清楚标本地草稿+问题列表 | 移除后端DAG校验 |
| 请求字段越改越少 | owned-key patch+roundtrip测试 | 按表单当前可见字段重建全部config |
| UI未达图效果 | 调整布局、参考几何要求 | 抄图中的错误协议/状态 |
| E2E环境不可用 | 标未执行及具体阻断，交付可运行测试 | 把mock结果当真实浏览器PASS |
| 当前HEAD已有新修复 | 按源事实复用，修正计划映射 | 为匹配旧计划重写回旧代码 |

## 5. 开发过程中不该改变的产品决策

常用节点优先，不要求普通用户理解全部能力；高级能力能找得到且有原因提示。普通任务不要先全量分析代码/数据库再允许用户添加节点。删除可恢复、字段来源可见、执行版本可解释，比增加一整排功能按钮更重要。

这份任务书是约束和校准工具，不是模型输出质量的保证。实际交付仍必须靠源码差异、可运行测试和用户路径验收，而不是仅靠一段很长的提示词。
