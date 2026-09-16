# FlowTest main@8c69ccb 审计整改与验收记录

日期：2026-09-16。工作分支：`codex/workflow-audit-lifecycle-fixes`。基线：`8c69ccb0b0cde8397f826b5c2ffbd741ead1257a`。

本轮针对《FlowTest_main_8c69ccb_只读审计报告_20260913.md》整改，保留已有工作台架构。F01–F04 已完成代码修复与专项验证；V01 已补充本地几何、DOM 基线和证据留存实现。GitHub 执行及成功 artifacts 下载尚未验证，因此不声明 V2 全部验收通过。

开发前完整读取新审计报告、根 AGENTS.md、V2 UI / FUNCTION_ACCEPTANCE_CONTRACT.md 与 CURRENT_AUDIT_RESOLUTION.md，并核对当前 workflow 源码及差异。报告与设计资料提供实施要求，未将其中的示例命令或历史执行记录当成用户的额外操作授权。

## 整改对应关系

| ID | 原问题 | 实现与结果 | 验证 |
|---|---|---|---|
| F01 / P1 | 请求表单卸载后，外层应用可能把 HTTP Capability 写入非法 config | fallback 先转换为编辑节点，patch owned fields，再恢复原持久化结构；与挂载路径同样保留 configuration、bindings、metadata、auth suppression 等字段 | API / Capability × 挂载 / 卸载，组件及真实服务端 PATCH 后读取验证 |
| F02 / P1 | A 的未应用请求与版本串入 B | 草稿绑定 project、node、API ID、API version；异步载入与应用检查身份；有请求输入时切换需取消或明确丢弃；确认后重建新目标会话 | A v12 → B v2 取消、恢复原 JSON/Tab、确认与服务端保存；同 API 版本升级；旧异步响应迟到 |
| F03 / P2 | 每次文本输入提交一次整图历史 | 映射文本只保存在当前输入会话，blur / Enter 提交一次；Escape 取消，IME Enter 不接管；第二行和结构操作独立历史 | 80 字符一次撤销 / 重做；另一行编辑、删除、撤销；transform 与端点保留 |
| F04 / P2 | definition / selection 变化重建 ResizeObserver 并重新取景 | Observer 只绑定真实画布及 workflow scope，读取最新图与选中状态；普通编辑不取景；真实 resize 保持 zoom，仅在选中节点或快捷操作栏离开可见区域时平移 | 50% / 150% 缩放加平移，改名、映射、清空选中保持 viewport；Inspector resize 保持 zoom；显式 Fit 仍有效；三档选中节点与操作栏完整可见 |
| V01 / 验证缺口 | 截图只有采集，成功 CI 没有可下载证据 | 27 张真实 DOM 基线 + 独立几何断言；原始 PNG / geometry JSON 绑定 SHA、源码摘要、viewport、scenario；Compose workflow 成功/失败均上传证据 | 本地基线生成与逐张审阅；随后不更新基线复跑；远程留存验证 NOT RUN |

实际截图额外发现 1280 / 1440 Header 标题、模式切换和操作区重叠。改为按模式和操作的实际宽度分列，标题允许收缩，窄屏保留有 aria-label 的历史 / 更多图标入口；新增 Header 三组区域和列表切换按钮的防重叠几何断言。

最后逐张复核发现 1440 选中节点的中心虽可见，节点及操作栏右侧仍会被 Inspector 裁切。先增加几何断言，在旧实现上实际复现失败，再将真实 resize 的可见范围扩展至节点和实测操作栏尺寸。只允许平移，保持 zoom；普通编辑仍完全保留 viewport。后续重新构建生产 frontend 镜像、重新审阅受影响截图并复跑门禁。

## 已执行检查

| 检查 | 结果 |
|---|---|
| Backend `ruff format --check .`、`ruff check .`、`mypy app` | PASS；557 个格式文件、391 个类型检查文件 |
| Backend `pytest` | PASS：1350 passed / 5 skipped；覆盖率 90.62% |
| Frontend `format:check`、`lint`、`build` | PASS |
| Frontend `test:coverage`（最终源码） | PASS：85 个测试文件、395 项测试；Statements 85.60%、Branches 80.52%、Functions 84.81%、Lines 87.84% |
| 新增请求身份与映射事务定向测试 | PASS：5 项；完整请求编辑器组件文件 17 项通过 |
| Linux Chromium / Compose 专项 + 布局 + 截图采集 | PASS：14 项，另有登录 setup 1 项通过 |
| 最终组合回归（不更新截图基线） | PASS：22 项 Playwright（8 专项 / 8 交互 / 3 布局 / 3 视觉矩阵），27 个像素检查点；登录 setup 另 1 项通过；耗时 1.8 分钟 |
| CI 留存实现静态验证 | PASS：YAML 解析、固定 upload action SHA、报告路径及 27 个基线文件；远程执行 NOT RUN |
| Compose `/api/v1/ready` 与真实页面运行 | PASS：database / storage / redis 就绪；浏览器创建、保存、发布合成验收流程并实际执行 mock-target 请求 |

5 项 Backend infrastructure 测试因为未设置 `FLOWTEST_RUN_INTEGRATION=1` 而跳过，标记 NOT RUN；上述 Compose 页面执行不能替代这 5 个独立测试。全仓库 FlowSpec/MCP 组件与后端测试已执行，但本轮没有单独执行 S51 MCP 可视化审核浏览器场景，标记 NOT RUN。Windows 安装包构建、公司环境部署、GitHub CI / artifacts 下载均 NOT RUN，未触发远程 CI。

本地日志位于 `output/workflow-audit-backend-pytest.log`、`output/workflow-audit-frontend-coverage-final.log`、`output/workflow-audit-linux-e2e.log`、`output/workflow-audit-linux-baseline-final.log` 及 `output/workflow-audit-linux-final.log`。先完整生成并打开审阅 27 张原始截图，再以同一生产 frontend 镜像执行最终组合回归，不更新基线。只使用合成测试项目采集 UI 证据，未扩大产品日志或数据采集。

## 视觉证据及差距表

实际打开核对的权威概念图：V2 `01-workspace.png`、`02-focus.png`、`03-palette.png`、`04-fullscreen-editor.png`、`05-edge-inspector.png`、`07-run-view.png`、`08-version-diff.png`。概念图用于信息架构与视觉层级对照，像素比较采用经过审阅的真实 DOM 基线。

| 检查点 | 1280×800 | 1440×900 | 1920×1080 | 结论 / 偏差 |
|---|---|---|---|---|
| 01 Default Edit | 已打开 | 已打开 | 已打开 | Header 不重叠；默认 Canvas 高度分别守住 460 / 600 / 720px；1440 / 1920 List 默认 240–280px |
| 02 Add Node | 已打开 | 已打开 | 已打开 | Palette 400px；搜索、类别、不可用原因明确 |
| 03 Node selected | 已打开 | 已打开 | 已打开 | 单选、浮动操作和 Quick Inspector 可见 |
| 04 Edge selected | 已打开 | 已打开 | 已打开 | 浮动映射 / 删除操作及端点信息可见 |
| 05 Inspector resized | 已打开 | 已打开 | 已打开 | 保持用户缩放；保障选中节点和浮动操作栏可见，不自动把所有节点重新取景 |
| 06 Fullscreen config | 已打开 | 已打开 | 已打开 | 保留语义分区、请求 Tab 与固定应用动作；狭屏通过内容滚动访问后续策略区 |
| 07 Focus Mode | 已打开 | 已打开 | 已打开 | 核心保存 / 运行 / 调试 / 添加 / 撤销等保留；截图通过真实 Fit 操作稳定取景 |
| 08 Run Mode | 已打开 | 已打开 | 已打开 | 真实执行成功；200–280px Runtime Dock 在工作台内 |
| 09 History Mode | 已打开 | 已打开 | 已打开 | 同一 Dock；只读快照状态可见 |

Default Edit 实测画布高度：1280×800 为 513px，1440×900 为 608px，1920×1080 为 788px；1440 / 1920 默认列表宽度均为 256px，1280 默认折叠。

本轮审计的 P1：F01 / F02 / Header 重叠均已修复，剩余 0；F03 / F04 的 P2 已修复。V01 本地证据已补齐，远端可下载产物仍未验证。剩余非阻断差异：Linux 字体回退与 macOS / Windows 不同；Inspector 改宽后，非选中节点可能部分移出画布，这符合保留 viewport 的策略。未对完整 V2 的所有扩展功能和设计细节重新逐项签署验收，不能把这些计数理解为完整 V2 P0/P1 清零。

原始截图及对应 JSON：`output/playwright/workflow-final-matrix/linux/{1280x800,1440x900,1920x1080}/`。基线：`frontend/e2e/workflow-editor-visual.spec.ts-snapshots/`。原始截图不遮罩；像素回归只遮罩合成项目时间戳、执行 ID / 时间、节点响应耗时，保留节点名称、执行状态、按钮和布局。差异比例上限 0.003，并有独立几何断言。

## Functional Gate 声明

以下结果限定本轮改动及已执行回归，不代表整个 V2 全量功能重新验收。

```text
Selection Gate: PASS（真实 node/edge 互斥、单选移动及组件回归）
Edge Editing Gate: PASS（真实连线命中、创建/重连取消、真假分支交换、删除/撤销、映射及组件回归）
Keyboard Gate: PASS（输入 Enter/Escape/IME、输入焦点保护、画布删除/撤销及组件回归）
Undo/Redo Gate: PASS（80 字符、独立行、删除及 viewport 专项）
Draft Lifecycle Gate: PASS（挂载/卸载、切换取消/确认、恢复、迟到响应）
Request Override Preservation Gate: PASS（含服务端持久化验证）
Read-only Gate: PASS（真实 History 热键不修改图及组件回归）
FlowSpec/MCP Regression Gate: NOT RUN（专项浏览器场景；组件与后端回归 PASS）
Run/History Gate: PASS（真实运行与历史快照）
Remaining functional blockers: F01–F04 无剩余；完整 V2 全量验收未重新执行
Tests actually executed: 见上表及最终组合回归日志
Tests not executed and reason: 5 个 opt-in infrastructure 测试、S51 专项浏览器、Windows/公司部署与远程 CI 未执行
```

## UI Gate 声明

```text
UI Geometry Gate: PASS
Information Architecture Gate: PASS（本轮 9 状态及已核对语义区域）
Interaction Visibility Gate: PASS（节点/连线浮动操作、Palette、Focus 核心操作）
1280 Visual Gate: PASS（9 张 DOM 基线回归与人工审阅）
1440 Visual Gate: PASS（9 张 DOM 基线回归与人工审阅）
1920 Visual Gate: PASS（9 张 DOM 基线回归与人工审阅）
Remaining P0: 0（本轮检查范围）
Remaining P1: 0（本轮检查范围；不替代完整 V2 统计）
Remaining P2: 跨平台字体差异与 viewport 保持后的非选中节点裁切
Reference images actually inspected: 上述 7 张 V2 图
Final screenshots actually inspected: 三档尺寸 × 九状态，共 27 张原始截图
Intentional deviations: 真实 DOM 基线不机械比对概念图；Linux 基线；合成动态字段仅在像素比较中遮罩；远程 artifacts NOT RUN
```

## CI 与交付边界

保持现有 `ci:milestone` 机制，只在大阶段完成后触发远程重任务。本轮本地验证完成后，应用户明确要求提交并合并到 GitHub；业务代码、专项测试及 27 张 DOM 基线通过普通 PR 发布，候选稳定后添加一次 `ci:milestone`。远程门禁与合并结果以对应 PR 的实时记录为准。

新增成功 / 失败证据上传属于 CI 治理文件变更。`scripts/required_gate.py` 的 `enforce_trusted_governance` 明确拒绝普通 `pull_request_target` 中修改这些文件，要求“CI 治理文件只能通过受控 Bootstrap 流程更新”。因此 `.github/workflows/compose-ci.yml` 的留存补丁需要通过既有受控 Bootstrap 路径发布，不能由普通业务 PR 绕过门禁；该补丁保留在本地，不纳入本次普通业务 PR；远端生效与下载验证保持 NOT RUN。未修改分支保护规则，也未使用 bypass。

工作区原有 `deploy/ruoyi/compose.yaml` 修改保持原样，不属于本轮整改。
