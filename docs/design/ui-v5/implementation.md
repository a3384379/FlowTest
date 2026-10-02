# v5 冰蓝白实施记录

已在真实前端落实冰蓝白主题及核心工作区布局：接口管理采用“目录—请求—响应”，流程编排采用节点库、画布、检查器和运行证据，用例管理采用目录、完整分页资产列表与详情抽屉，报告和发布门禁优先显示失败证据。后续补齐了报告与编排的双向定位、运行轨迹、来源定位、检查器分区、节点切换确认与流程级配置，并补齐用例/套件的固定版本、计划、执行与报告关联。26 个原有模块继续通过常用任务栏或全部模块目录访问。其余页面共享新的主题与应用壳，业务操作、权限与能力开关沿用原实现。

## 基线与工作树

- 实施日期：2026-10-02。首轮开始约 12:45，功能联动续作约 15:53，用例功能续作自 18:13（Asia/Shanghai）；以日志时间为各次验证时间。
- 需求来源：[用户指定的共享对话](https://chatgpt.com/share/6abef2e2-07b8-83ea-bfde-691d3d72d13b)，使用其最新 v5 冰蓝白完整实施交接包，而非较早的 v3/v4 方向。完整方案、状态契约、全模块/节点矩阵、视觉规范、实施提示与验收材料在编辑前已读取。
- 原工作区：`/Volumes/雷电/project/FlowTest`，`codex/control-flow-validation`。开始时工作区干净。
- 实施工作树：`/Users/sqz/Documents/Codex/2026-10-02/task/FlowTest`，`codex/ui-v5-ice-light`。
- 首轮代码基线：`cfe3594d055e1feb988df18041ed9dbedda8bc6b`。提交准备阶段已同步 `main@f7c3459`，保留其认证会话修复、用例直接运行和依赖更新。本功能改动集中于前端、浏览器验收和设计记录，没有新增后端业务、数据库、执行引擎或 CI 治理改动。提交合并时另修复安全门禁发现的 urllib3、Axios 依赖漏洞及 Debian 运行层漏洞，见下方独立记录。GitHub 合并结果以 PR 和最新提交的 Required Gate 为准。
- 本地 Node 22.22.0。主干同步后在实施工作树独立执行冻结锁文件安装，保留仓库的 pnpm 11.16 声明。Linux 浏览器验证使用 Playwright 1.62.1；构建与远程门禁按仓库声明执行。

## 实际改动

完整文件清单见 [changed-files.txt](changed-files.txt)。PR 相对最新主干的 diff 可用于审阅全部源码改动。日志和隔离浏览器截图保存在本地忽略目录，不提供无法在 GitHub 打开的链接。

| 工作区             | 主要源码                                                                                                                                  | 行为与目的                                                                                                                             |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 主题与应用壳       | `frontend/src/theme/`、`main.tsx`、`App.tsx`、`features/navigation/`、`styles.css`                                                        | 单一颜色入口；浅色画布、代码、弹层、图表；68px 常用导航与可搜索模块目录；用户外观偏好独立存储；减少透明与系统减少动效                  |
| 流程布局           | `flow/WorkflowDesigner.tsx`、`WorkflowWorkspaceShell.tsx`、`WorkflowInspectorShell.tsx`、`WorkflowNodeLibrary.tsx`、`workflow-editor.css` | 列表抽屉；宽屏节点库，1280 抽屉；检查器默认 320px；节点显示类型、真实配置来源、所属区域与运行状态；内联区域同步浅色样式                |
| 流程关系与生命周期 | `flow/editor/node-presentation.ts`、`WorkflowNodeRelations.tsx`、`WorkflowSettingsEditor.tsx`、`pages/WorkflowsPage.tsx`                  | 数据引用为只读展示边；来源/下游可定位；显著呈现保存/发布/执行；历史采用冻结快照；流程级变量与执行设置接入图草稿、撤销与重做            |
| 接口管理           | `pages/ApiConsolePage.tsx`、`features/api-console/APIWorkbench.tsx`、`ExecutionResultPanel.tsx`、`use-api-console.ts`                     | 左目录与环境卡片；方法/路径行中的发送操作；请求与响应分区和内部滚动；响应、实际请求、断言与历史 tabs；HTTP200 的断言失败仍显示失败提示 |
| 失败证据           | `features/evidence/`、`flow/WorkflowRunInspector.tsx`、`pages/ReportsPage.tsx`                                                            | 失败优先排序；期望/实际并排；`undefined` 为“未提供”，保留真实 `null`/`false`/`0`；不存在的尝试次数或耗时不冒充 0                       |
| 用例管理           | `pages/TestAssetsPage.tsx`、`features/test-assets/`、`features/task-plans/task-plan-service.ts`                                           | 完整分页目录、当前页选择、详情与发布版本、流程绑定、固定成员版本、创建计划与显式执行、近期结果/报告/冻结编排、项目能力守卫             |
| 总览与报告         | `pages/DashboardPage.tsx`、`pages/ReportsPage.tsx`、`ReportExecutionWorkspace.tsx`、两处趋势图                                            | 本页统计与后端 total 分开；报告服务端分页；执行轨迹与证据工作区；双向定位冻结画布并保留请求尝试；局部加载错误与重试；390px 证据单列    |
| 发布门禁           | `pages/ReleaseGatePage.tsx`                                                                                                               | 显示策略、历史和最新结果；最新冻结判断展示逐项证据与决策上下文，阻断优先；保留策略表、历史表和人工生成判断操作                         |

保存仍由 `useWorkflows.saveDraft`/`saveWorkflowDraftFor` 完成，发布和执行使用原处理器。`WorkflowDefinition` 仍是持久化图的权威；节点编辑先应用再进入图，保存时的并发编辑与版本冲突保护保持。主题切换不清空旧导航、workspace tabs、节点草稿或工作流存储。

数据引用展示仅使用已有显式节点引用、类型化 `node_output` 来源和字段映射。无法解析的绑定显示未解析，不猜测上游。展示边不能被选中、重连或写入 `WorkflowDefinition.edges`。浏览器夹具中开启数据引用后，展示边从 0 变为 2，执行边保持 5 条。

关联对象通过现有项目路由和查询参数导航，包含执行、节点与请求尝试次数；没有新增持久化对象 tab 模型。未新增接口、执行能力、端口、策略版本或报告检查点。SQL/Redis 只读约束、受控环境模板/实例/TTL、性能默认不自动负载、AI/MCP 人工审批与逐项审核、秘密边界和项目请求级策略均保持。

## 功能联动补齐

根据用户关于“报告和编排没有关联、编排缺功能”的反馈，本次继续实现以下可操作行为，而非仅调整样式：

- 报告详情替换为完整页面工作区：左侧逐节点执行轨迹，右侧当次证据；默认选中失败节点，可切换响应、请求、提取、断言和变量映射。报告列表接入已有服务端分页。
- “定位画布”和“查看完整报告”双向传递项目、执行、节点与请求尝试次数。可刷新直接链接；重复选择同一节点不会清掉已选尝试。原流程被删除时仍可读取执行快照，不回退到其他流程草稿。
- 运行/历史模式在宽屏以执行轨迹替换节点库，1280px 提供轨迹抽屉。选择轨迹或数据来源可定位画布；来源显示基于真实图引用，不增加执行边。
- 节点检查器划分配置、输入/输出和校验。API 字段映射只有一个主要编辑入口；节点切换提供应用后继续、丢弃此节点修改和取消，输入校验失败时保留当前表单。
- 流程设置支持已有初始变量，以及失败即停止、并发上限 1–100、默认超时 1–300 秒。变更进入现有图草稿和撤销/重做链；保留所有其他定义字段及 run_policy。添加变量校验名称格式、长度和重复项，删除可撤销。历史设置只读。

对应源码为 `features/reports/ReportExecutionWorkspace.tsx`、`features/workflows/execution-navigation.ts`、`flow/WorkflowRunTrajectory.tsx`、`WorkflowNodeRelations.tsx`、`WorkflowSettingsEditor.tsx`、`editor/use-node-selection-guard.tsx` 及页面/查询层挂接。没有自动保存、发布、执行或重发历史请求。

## 阶段与验证范围

“已验证”在本记录中指列明的本地前端范围，不能当作完整发布验收通过。

| 阶段                | 状态     | 交付与已执行验证                                                                                                                     | 剩余验收/回滚范围                                                                                                                         |
| ------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| P0 源码盘点         | 已验证   | 基线/status、依赖、12 项职责、26 模块、28 注册项与额外 start 映射；已有行为测试先于修改执行                                          | [源码盘点](source-inventory.csv)、[模块映射](modules.csv)、[节点映射](nodes.csv)；无业务回滚                                              |
| P1 主题与应用壳     | 已验证   | 主题与导航、特殊认证状态、用户外观隔离、弹层焦点与深色系统浅色呈现；前端单元与浏览器检查                                             | 逐页所有弹层/屏幕阅读器审计未完成；回滚 theme/main/App/navigation/CSS 挂接                                                                |
| P2 流程核心         | 已验证   | 既有图编辑/控制字段/草稿竞态/热键回归；桌面三个视口、真实内联区域、未应用提示、冻结历史、数据边不污染执行边                          | 28 类节点的真实引擎执行与大图性能未重跑；回滚流程呈现文件，不清草稿/session                                                               |
| P3 接口、用例与报告 | 已验证   | 接口发送与断言失败提示、既有请求/版本/文件回归；完整分页目录/清选择、资产版本/计划/执行/报告关联；统计分母/本页筛选；桌面与390px证据 | 真实目标请求、服务器冲突/导出与通知实投未执行；资产导入导出/全历史统计仍需后端能力；回滚对应前端呈现文件                                  |
| P4 其他页面族       | 已映射   | 26 模块共享主题、入口与原权限差异；门禁证据分区已实现并测；既有环境/性能/AI/MCP/治理前端回归执行                                     | 其余模块逐页真实浏览器、多角色、能力开关与安全边界验收未逐项执行；不以共用主题冒充完整逐页重设计验收                                      |
| P5 最终验收         | 已改未测 | 最终格式/Lint/类型/构建、前端回归和所列浏览器截图；80 项矩阵记录各自范围；修复减少动效下的定位测量                                   | 完整 `make check`、Compose Playwright、后端、Windows、真实各角色与发布验收以最新提交门禁和验收记录为准；本地前端覆盖率已通过，不能推断 GA |

## 用例与套件功能补齐

首轮只完成了目录与列表布局，未达到方案的“目录—列表—详情、绑定版本—计划—执行—报告”操作链。本轮接入已有 API，没有新增后端契约或自动创建真实资产。

- 目录与套件/流程选项逐页读取完整记录，超过 100 条不截断；每页显示 20 条。目录计数包括筛选结果中的用例与套件。切目录、页码、类型和筛选时清除批量选择，操作对象仅限当前页。分页读取发生重复/数量变化时提示重载，不把部分数据标为完整。
- 名称打开详情，可通过 `type/focus/version` 深链接查看资产。草稿、发布版本和执行结果独立。发布版本展示冻结流程/环境/覆盖项；指定版本缺失时保留错误并禁用计划/执行，不回退到其他版本。
- 用例可明确选择流程版本，套件可选择成员版本。仅改套件说明时保留原成员版本，避免静默绑定最新版本。保存失败保留表单并显示标准错误。
- 用例“执行”接入主干直接运行接口，详情选择的旧发布版本会作为固定版本提交，不创建隐式计划；草稿运行仍需明确确认发布。用例“加入计划”可以追加到已有计划，并保留所选发布版本，也可以明确新建计划。套件和批量操作先创建可审阅的手动计划，再由用户显式执行。发布不会自动执行；新计划入队失败重试复用已创建计划与同一 Idempotency-Key。
- 用例最近结果接入主干按资产查询接口，包含直接执行与计划执行；每次只查询当前页的最多 20 个用例，满足接口 100 ID 上限。套件记录仍从计划项及 `source_suite` 冻结来源关联，覆盖最近 20 次项目计划运行，显示查询数量与后端 total。无记录只说明这个范围没有记录。混合计划的其他资产不会影响本用例/套件结果；失败、排队、运行、取消和隔离分开。
- 结果链接进入具体执行报告，详情提供报告与冻结编排回看、固定成员版本和直接引用该资产的计划。项目权限沿用既有 capabilities；无编辑/执行能力时禁用相关操作。只读回看没有写请求。
- 1440px 列表/详情与 390px 套件详情完成浏览器验证；手机页面/抽屉宽度均为 390px。所有操作使用隔离契约夹具，实际后端写入为零。模拟失败入队后重试：1 次创建计划、2 次入队、同一幂等键。

对应源码为 `AssetDetailDrawer.tsx`、`AssetPlanDialog.tsx`、`AssetRunEvidence.tsx`、`asset-workspace-service.ts`、`asset-run-view-model.ts`、`use-asset-history.ts` 及现有页面/服务挂接。主干新增的用例直接执行、最近结果与追加已有计划能力已保留并接入新版工作区。导入导出、按资产全历史检索/聚合仍列为独立后端待办。

## 主干同步后的提交前验证

主干同步保留认证 epoch 变化时清理查询缓存、草稿运行确认、运行变量/headers 和套件成员固定版本。用例工作区新增回归验证：跨 100 条记录的旧版用例直接运行、将指定旧版加入已有计划，两项均校验精确 API 请求且不触发隐式计划或执行。最终前端覆盖率复核为 111 文件、651 测试通过：语句 84.88%、分支 80.41%、函数 84.41%、行 87.19%（`github-viewport-coverage.log`），四项均通过 80% 阈值。格式、Lint/类型与构建均通过；最大化表单宽度和空分支条件问题已修复，新增四项无条件/显式分支回归。运行视图的自动居中和安全范围采用实测节点尺寸，避免初始高度与运行状态高度不同导致取景位移；补齐七项视口回归，修改前四项表征通过，修改后相关三文件/33项通过（`github-viewport-characterization.log`、`github-viewport-targeted.log`）。Linux 27 张视觉基线已复核；不更新基线的普通模式复跑共 9 项全部通过（`github-buildkit-browser-canonical-verified.log`）：包含登录、三视口几何、三视口共 27 个像素检查点、S15 用例/套件及 V1 治理/报告主路径。像素阈值仍为 0.003。S11 业务、重试、超时、取消、并行、权限及报告冒烟另行通过（`github-buildkit-s11-seed.log`）。默认、专注、运行和历史视图通过真实“适应画布”取景，先等待字体、节点和视口稳定；用例选项在弹窗及下拉动画完成后用普通点击选择。远程合并门禁单独确认。

### 合并门禁发现的依赖阻断

[PR #125](https://github.com/a3384379/FlowTest/pull/125) 首轮完整自动检查在 Python 依赖审计发现 urllib3 2.7.0 的三个已知漏洞。本地前端审计也发现 Axios 1.19.0 的七项高危问题。因此独立修复 `backend/uv.lock` 中的 urllib3 至 2.8.0，以及前端 Axios 最低版本/锁定版本至 1.20.0（包含其 follow-redirects 传递依赖 1.16.1）。未改动扫描规则或风险门槛，也没有升级测试框架和其他工具链。[urllib3 官方说明](https://urllib3.readthedocs.io/en/stable/changelog.html)与 [Axios 官方发布说明](https://github.com/axios/axios/releases/tag/v1.20.0)列明修复及兼容注意事项；定制 HTTPS 代理应核对 urllib3 的代理 TLS 配置变更。

依赖修复后，在本工作树独立环境使用冻结安装和仓库声明的 pnpm 11.16.0 验证：Python 160 包审计无已知漏洞，源码安全 Ruff 通过，存储/转移/运行输出/文件授权四文件 15 项定向回归通过（`github-urllib3-audit.json`、`github-security-fixed-ruff.log`、`github-urllib3-targeted.log`）。前端格式、Lint/类型、构建及 111 文件/651 项全量覆盖率均通过，四项覆盖率与上述数值一致（`github-security-fixed-coverage.log`、`github-security-fixed-lint.log`、`github-security-fixed-build.log`）。前端审计高危/严重项为 0，保留两项 Vitest / @vitest/mocker 中危开发依赖条目作单独跟踪（同一 [GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9)，`github-node-audit-final.json`）；既有 `--audit-level high` 门禁保持。

源码依赖修复后的镜像扫描进一步发现缓存 Python 基础层中的 OpenSSL 与 PCRE2 高危条目。`backend/Dockerfile` 的共享 Python 运行层、`mock-target/Dockerfile` 的 Python 构建后运行层定向更新 `libssl3t64`、`openssl-provider-legacy`、`libpcre2-8-0`，校验最低 Debian 修复版本分别为 `3.5.7-1~deb13u3`、`3.5.7-1~deb13u3`、`10.46-1~deb13u3`，使缓存或复用基础镜像仍取得修复库。使用原 Debian 签名源，不改 Python/Go 版本、基础镜像默认值、扫描忽略规则或门槛。修复依据为 [Debian OpenSSL 安全公告](https://security-tracker.debian.org/tracker/DSA-6531-1)及 [PCRE2 包状态](https://security-tracker.debian.org/tracker/source-package/pcre2)。

运行层修复在本地 Linux arm64 完成：应用运行镜像使用已有阶段二 Python 基础镜像构建通过，mock 镜像使用其正常源码构建通过；两份 Dockerfile 的 `docker build --check` 无警告。实际应用镜像导入 `app.main` 并以独立本地 CA 验证 HTTPS 成功响应、错误主机名拒绝、不可信 CA 拒绝，保持严格证书校验；三个库实际版本均达到上述下限（`github-debian-runtime-build.log`、`github-debian-mock-build.log`、`github-debian-runtime-probe-local-tls-fixed.log`）。CI 路由 91 项定向回归通过（`github-runtime-routing-targeted.log`）。这些构建验证没有替代最新提交的 Linux amd64 全镜像扫描或 Compose 检查。

上述本地 Linux 浏览器检查在依赖修复前完成；修复后的完整浏览器与部署检查以最新 PR 提交的远程自动验证为准，不沿用旧提交的绿灯。`1259622` 的完整 CI 后端、Windows 和升级回滚检查通过；前端两项测试超时，浏览器矩阵暴露旧导航/布局定位与 1280px 运行截图问题，尚待修复并重新验证。隔离验证栈和临时进程已清理，原工作区仍干净，已有运行实例健康。

### 完整 CI 中的浏览器与测试修复

`1259622` 的前端全量测试有 649 项通过，两项复合/目录交互测试超过 60 秒。将 GraphQL 配置/绑定与 gRPC mTLS 分成独立场景，并使用一次真实粘贴输入验证完整字段；目录选择测试将查询限定到标签、当前行与工具栏，保留跨 100 条读取、禁止意外写入和切目录清选择的断言。没有提高超时、关闭测试或降低覆盖率。单工作线程下两文件 34 项定向检查通过（`github-ci-timeout-fixed-targeted.log`）；随后全量覆盖率 111 文件 / 652 项通过（`github-ci-followup-full-coverage.log`，482.09s），四项覆盖率保持 84.88% / 80.41% / 84.41% / 87.19%。

旧侧栏验收已迁移到 68px 常用任务栏及全部模块抽屉，保留三档视口中的未应用草稿/URL/tab、键盘进入/退出、焦点恢复、浏览器历史和逐帧尺寸稳定检查。S16 用抽屉自身关闭按钮退出列表，直接从新版顶栏选择环境，版本 Diff / 调试使用命名的更多按钮；S21 等待实际弹窗/下拉动画完成再选择；发布门禁和 API 候选选项定位限定到对应行/下拉；新增节点使用宽屏停靠库拖入可命中的画布。小屏顶部改为两行，保留项目、全局搜索、外观及退出入口。截图前增加整图中心与画布中心的几何断言；测量尚未反映新布局时，继续通过真实适应画布操作取景，截图阈值和节点/状态内容比较保持。相关浏览器脚本在本任务独立的 BuildKit PostgreSQL、Redis、MinIO、mock、API/Worker 进程与专用端口上复核，默认 Compose 的 mock 地址保持；本地可通过 `FLOWTEST_E2E_MOCK_TARGET_URL` 选择隔离目标。临时进程不连接原实例数据库。最终本地普通模式已通过导航、发布门禁、编排审计/交互及三视口 27 张截图（32 项，`github-buildkit-browser-ci-followup-final.log`）；S16 / S21 的脚本修复继续定向复核，不能将整次运行写为全通过。原有基线没有再次更新，0.003 像素门槛保持。

以下为此前各轮验证记录，不能替代主干同步后的最终门禁。

## 检查记录

工作目录均为上述实施工作树。开发期间的失败及修复日志保留在 `output/playwright/ui-v5/logs/`，最终结论以下表和实际日志为准。

| 检查                  | 命令与范围                                                                                                                                                                                                      | 结果/日志                                                                                                                                                                                 |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 修改前表征基线        | `make test-frontend-targeted TARGETS='[...]'`，5 个相关文件                                                                                                                                                     | 65 项通过；`baseline-tests-reuse.log`                                                                                                                                                     |
| 全部前端单元/组件测试 | `cd frontend`；`pnpm_config_verify_deps_before_run=warn pnpm test`                                                                                                                                              | 用例补齐后 107 文件、586 项通过（83.76s）；`assets-frontend-all.log`。之前 568 项日志保留作历史记录，当前结论以本轮日志为准                                                               |
| 用例与门禁针对性回归  | `make test-frontend-targeted TARGETS='["src/pages/TestAssetsWorkspace.test.tsx","src/pages/TestAssetsPage.test.tsx","src/pages/ReleaseGatePage.test.tsx","src/features/test-assets/use-test-assets.test.tsx"]'` | 4 文件、18 项通过；`assets-gate-final.log`                                                                                                                                                |
| 最终动效/弹层影响范围 | `make test-frontend-targeted`，外观、App、接口、报告、用例目录、门禁6文件                                                                                                                                       | 6文件、29项通过；`reduced-motion-popup-delivery.log`；浏览器同时检查减少动效下的弹层几何与开关操作                                                                                        |
| 格式                  | `cd frontend`；`pnpm_config_verify_deps_before_run=warn pnpm format:check`                                                                                                                                      | 通过；`association-format-final-complete.log`                                                                                                                                             |
| Lint 与类型           | `cd frontend`；`pnpm_config_verify_deps_before_run=warn pnpm lint`                                                                                                                                              | ESLint（复杂度≤10）及 `tsc -b` 通过；`association-lint-final-complete.log`                                                                                                                |
| 生产构建              | `cd frontend`；`pnpm_config_verify_deps_before_run=warn pnpm build`                                                                                                                                             | 通过；`association-build-final-complete.log`                                                                                                                                              |
| 功能联动针对性检查    | `make test-frontend-targeted`，报告/编排页面、检查器、导航及设置                                                                                                                                                | 6文件45项、设置2项、定位影响范围2文件35项通过；`association-tests-expanded.log`、`settings-variables-final.log`、`association-location-tests.log`。新增缺失入口测试在实现前失败，之后通过 |
| 修改与文档            | `git diff --check`；CSV行数、源码路径与文档链接核对                                                                                                                                                             | 通过记录见 `association-docs-check.log`、`association-git-status-final.log`、`git-diff-delivery.patch`                                                                                    |
| 集中颜色对            | 按相对亮度核算正文/说明/主色/控件边界等10组token色对                                                                                                                                                            | 正文14.08、说明6.13、次级文字5.21、主色/浅蓝背景4.54、控件边界/白底3.15；`contrast-token-check.log`；不是整站WCAG审计                                                                     |
| 浏览器                | Playwright CLI；1440×900、1280×800、1600×1000、390×844；系统深色/减少动效                                                                                                                                       | 真实前端配隔离契约夹具；相关截图与 `qa-*-result.log`；不操作真实后端资产/目标                                                                                                             |

本次不收集覆盖率，不降低仓库阈值。未运行的后端、全覆盖率、Compose E2E、部署形态与远程门禁属于独立的后续发布验证；没有根据前端本地通过推断其结果。

## 本轮功能联动与截图

本轮浏览器仍运行真实前端和隔离契约夹具。设置添加/撤销/重做、历史返回恢复草稿和证据导航都检查了网络写入，未发出后端资产变更或真实目标请求。完整脚本和诊断过程留在 `output/playwright/ui-v5/`。

| 场景             | 实现截图/证据                                                                                                                                                                                                                                            | 已观察结果                                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| 节点未应用时切换 | 三种选择（`output/playwright/ui-v5/22-node-switch-confirmation.png`，本地留存）；`qa-association-settings-result.log`                                                                                                                                    | 取消保留输入，应用后继续进入目标节点；丢弃有组件回归                                                        |
| 流程设置         | 变量与执行设置（`output/playwright/ui-v5/23-workflow-settings-1440.png`，本地留存）；`qa-association-settings-result.log`                                                                                                                                | 添加变量可撤销/重做；图定义其他字段和运行策略有回归保护；零后端写入                                         |
| 历史/草稿隔离    | 历史执行轨迹（`output/playwright/ui-v5/24-workflow-history-trajectory-1440.png`，本地留存）；`qa-association-frozen-complete-result.log`                                                                                                                 | 冻结并发20不混入草稿7和新增变量；返回后节点名称/变量/设置恢复；零后端写入                                   |
| 报告工作区       | 桌面完整报告（`output/playwright/ui-v5/25-report-workspace-1440.png`，本地留存）                                                                                                                                                                         | 轨迹选择、失败金额对照、冻结环境、定位画布和导出入口                                                        |
| 精确请求证据联动 | `qa-association-attempt-result.log`                                                                                                                                                                                                                      | 来源定位后选择第1次请求，报告→画布→报告及刷新均保留该次503响应；同节点再选不重置尝试；零后端写入            |
| 响应式联动       | 390px完整报告（`output/playwright/ui-v5/26-report-workspace-390.png`，本地留存）、1280px历史画布（`output/playwright/ui-v5/27-history-trajectory-1280.png`，本地留存）；`qa-association-responsive-result.log`、`qa-association-mobile-final-result.log` | 手机页面宽390、无整体横向溢出，轨迹自动显示选中节点，冻结上下文单列；1280px轨迹抽屉选择后关闭并定位正确节点 |

## 首轮主题与布局截图

| 场景          | 实现截图                                                                                                                                                                                                                            | 观察                                                                          |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 流程/1440     | 流程编辑器（`output/playwright/ui-v5/03-workflow-1440.png`，本地留存）                                                                                                                                                              | 白色节点、蓝色执行关系、节点库/检查器/运行面板                                |
| 流程/1280     | 1280工作区（`output/playwright/ui-v5/04-workflow-1280.png`，本地留存）                                                                                                                                                              | 节点库抽屉，保留可读检查器                                                    |
| 系统深色/1600 | 浅色工作区（`output/playwright/ui-v5/05-workflow-dark-os-1600.png`，本地留存）                                                                                                                                                      | 主题仍为 ice-light，无深色主画布                                              |
| 历史证据      | 冻结快照（`output/playwright/ui-v5/07-workflow-history-evidence-1440.png`，本地留存）                                                                                                                                               | v1/冻结环境；保存与发布按钮不存在；期望29900与实际29901                       |
| 内联控制结构  | 控制块（`output/playwright/ui-v5/08-workflow-control-1440.png`，本地留存）、内部区域（`output/playwright/ui-v5/09-workflow-control-region.png`，本地留存）                                                                          | 真实 foreach 区域与其两个步骤，无装饰端口                                     |
| 接口          | 1440工作台（`output/playwright/ui-v5/06-api-workbench-1440.png`，本地留存）、1280（`output/playwright/ui-v5/13-api-workbench-1280.png`，本地留存）                                                                                  | 请求/响应分区；HTTP200与失败断言同时显示                                      |
| 用例          | 目录与列表（`output/playwright/ui-v5/17-assets-1440.png`，本地留存）                                                                                                                                                                | 首轮布局记录；当前版本以本轮 28–34 截图为准                                   |
| 报告          | 桌面失败证据（`output/playwright/ui-v5/10-report-evidence-1440.png`，本地留存）、手机证据（`output/playwright/ui-v5/11-report-evidence-390.png`，本地留存）、手机列表（`output/playwright/ui-v5/12-report-list-390.png`，本地留存） | 后端total120、本页1条；手机页面宽度390，无页面横向溢出                        |
| 门禁          | 逐项证据与决策上下文（`output/playwright/ui-v5/18-release-gate-1440.png`，本地留存）                                                                                                                                                | BLOCK及2项真实夹具阻断原因；无部署操作                                        |
| 应用壳与外观  | 总览（`output/playwright/ui-v5/14-quality-overview-1440.png`，本地留存）、模块目录（`output/playwright/ui-v5/20-module-directory.png`，本地留存）、外观（`output/playwright/ui-v5/21-appearance-settings.png`，本地留存）           | 搜索模块/关闭焦点恢复；减少透明可操作；系统深色和减少动效时弹层白色且在视口内 |

原型与真实模型不一致处见 [必要视觉差异](visual-deviations.md)。全部80项见 [验收矩阵](acceptance.csv)，其中源码映射和部分前端回归不能代替其完整真实环境条件。

## 用例续作验证与截图

定向回归 `make test-frontend-targeted` 涉及用例页面/工作区、useTestAssets、资产服务/目录/运行模型、计划确认和 TestPlansPage 共 8 文件，33 项通过（`assets-targeted-final.log`）。修改前基线为 4 文件/14 项（`assets-baseline.log`）。

本轮最终 `pnpm format:check`、`pnpm lint`（包含 `tsc -b`）和 `pnpm build` 均通过，分别见 `assets-format-check-final.log`、`assets-lint-complete.log`、`assets-build-final.log`。浏览器操作记录在 `assets-browser-retry-stats.log`、`assets-mobile-measurements.log`。

| 场景                 | 证据                                                                                      |
| -------------------- | ----------------------------------------------------------------------------------------- |
| 完整目录与绑定/结果  | 1440px 列表（`output/playwright/ui-v5/28-assets-list-1440.png`，本地留存）                |
| 资产详情与冻结定义   | 1440px 详情（`output/playwright/ui-v5/29-asset-detail-1440.png`，本地留存）               |
| 用例执行与报告       | 执行证据（`output/playwright/ui-v5/30-asset-execution-evidence-1440.png`，本地留存）      |
| 执行前确认版本与计划 | 可审阅的操作（`output/playwright/ui-v5/31-asset-plan-review-1440.png`，本地留存）         |
| 套件成员固定版本     | 1440px 套件（`output/playwright/ui-v5/32-suite-fixed-versions-1440.png`，本地留存）       |
| 套件关联计划         | 390px 关联计划（`output/playwright/ui-v5/33-suite-related-plans-390.png`，本地留存）      |
| 套件报告/编排回看    | 390px 执行证据（`output/playwright/ui-v5/34-suite-execution-evidence-390.png`，本地留存） |

## 剩余风险与回滚

当前核心工作区可供代码与视觉审阅。用例目录已通过现有分页读取完整记录；大项目的目录首载请求量仍随资产数量增长，服务端目录筛选/聚合属于后续优化。用例最近结果包含直接与计划执行，套件的计划记录只覆盖最近 20 次项目运行，不能替代按资产全历史检索。用例已支持追加已有计划；用例原生导入导出仍需后端能力。报告失败过滤仍是本页过滤，服务端失败分页未实现。未提供的维护状态等字段不会填假数据。

减少动效规则使用 `transition-duration: 0s`，避免给所有定位属性引入非零过渡、干扰弹层/画布几何测量。Ant Design 仍使用其正常的系统动效开关；图表和画布也响应系统偏好。深色系统且减少动效时，外观弹层实测位于1440px视口内、背景白色、开关可点击。

全站共用主题会影响既有弹层、表单和图表，故正式合并前仍需完整前端覆盖率与风险对应的 PR Required Gate，以及真实权限/后端/Compose验收。现有 Ant Design `maskClosable` 弃用提示未作无关重构；不宣称大图性能提升或完整可访问性合规。

回滚只回退本工作树列出的前端主题、工作区与导航改动。不要清数据库、缓存、旧导航、workspace tabs、节点表单或工作流 session。旧偏好存储未删除，外观偏好独立使用 `flowtest:appearance:v5:<user>`；按 PR 的明确文件范围或提交回退，不使用全局 reset/clean。
