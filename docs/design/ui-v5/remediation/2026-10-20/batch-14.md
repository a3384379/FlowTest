# M12 任务执行整改记录

依据：[完整审计 M12](../../audits/2026-10-19/complete-audit.md#m12)、[详细方案 M12](../../audits/2026-10-19/remediation-plan.md#m12)。对应 `F-TASK-01/02`。

**两项已实现，具名专项、完整本地检查与真实浏览器/Worker验收通过，计入44项本地完成。** 当前44/73项本地完成、29项待完成、37项已合并。本地检查、最新提交GitHub门禁与正式发布分开记录。

## 多执行项编组

- 新建计划从单目标改为1至100个执行项；每项选择工作流、测试用例或套件，并在选择时固定其当前已发布版本。未发布/其他项目对象不进入可选项。
- 每项显示执行顺序、固定版本和失败重试0至3次；可上移、下移和删除，至少保留一项。工作流逐项选择环境；用例/套件明确继承其固定发布配置，未伪造后端不支持的环境覆盖。
- SDK按原接口items数组发送实际顺序、版本及重试，不重建历史计划。第101项和非法版本在提交前拒绝，服务端原有上限/版本/归属校验保持。编辑旧计划只改既有调度和启停字段。
- 创建使用Form原生校验和显式中文按钮；请求失败保留全部执行项、排序、名称及trace，可重试相同负载。提交中禁止改动/关闭，成功后一次性Webhook秘密按原规则展示；截图和验收日志不包含该秘密。
- 首先将原创建弹窗独立提取，保持原行为的2文件5项回归通过，重构84a35b8和功能a300bf1分别提交。

## 计划和运行的准确定位

- 计划名称写入focus URL；使用已有受权GET按ID读取，显示独立所选计划详情。目标在第21条、搜索页外或当前列表之外时仍能读取，无需切到目录页，也不会用首项替代。
- 所选详情显示保存的执行顺序/类型/ID/固定版本/环境及重试。跨项目、缺失和读取失败保留指定ID及trace，可重试同一ID；失败对象不显示编辑或运行操作。
- 运行详情进入run URL，关闭只清run，保留focus；刷新和浏览器返回均恢复相同运行。入队使用返回的真实run.id打开对应详情，固定目标和报告仍来自原执行快照。
- 写入需要权限读取成功。Viewer能读计划和运行，不能执行、编辑、取消、签发或读取Owner凭据。缓存和查询按项目、计划、运行划分，响应校验项目与对象ID。
- 异步操作以项目、所选计划、所选运行及工作区生命周期校验归属。切项目、切运行或离开页面后的迟到成功/失败不会修改当前选中对象或显示过期提示；服务端已入队记录仍保留在其原项目历史。

## 额外审计与手机可用性

并发复审发现，最初上下文只有项目/计划，尚未包含运行：等待入队期间切到另一条已存在运行，旧响应会覆盖新选择。新增公开Hook回归，修复前1失败/3通过；68c088a将selectedRunId纳入上下文和变更键，修复后4项通过。真实浏览器拦截并延迟一个明确标记的合成202响应，再打开已有运行，释放后仍停留原运行；未读取合成ID，后端入队命令0。日志 `remediation-task-selected-run-race-before.log`、`remediation-task-selected-run-race-browser.log`。真实执行验收与此合成竞态测试分开记账。

手机初验没有页面横向溢出，但两个目录仍并排压缩为窄列。60eedec改为980px以下上下排列，表格在自身范围滚动，表头不逐字挤压；主区保持清楚的纵向间距。390px补验确认上下排列、document390px；运行弹窗x8/宽374/高625，新建弹窗x8/宽374/高744，3行表单局部滚动且操作区可见。最初加载骨架及入场半透明截图未当成验收证据，已等数据与动画稳定后补截并目视复查。

## 检查与精确源码

- 修改前前端2文件5项、后端test_tasking_api.py的27项通过；原重试、固定版本展开、CI、签名Webhook和取消路径保留。后端应用及数据库模型未改，没有迁移。
- 最终4个前端具名文件16项通过：TestPlansPage、TestPlanTargetSelect、task-plan-service、use-test-plans。覆盖三类型排序/逐项配置、503保留和相同负载重试、第21计划/取消运行URL及历史、404/503保留ID精确重试、100项有序发送/101项禁止、未发布版本禁止、跨项目响应拒绝、迟到成功/失败及卸载/改选运行。
- 源码 `68c088ae6217ec79af34e769e987b58c8eb9a74d` 的frontend树 `2e540bd619585c531edb26cbcfd8f0c8e55abc5a` 完整检查通过：166文件1103项、无未处理异常，覆盖率85.88/81.88/85.59/88.42%，格式、ESLint/TypeScript和构建通过。日志 `remediation-task-final-frontend-full.log`。检查期间应用/测试源码冻结，后续仅文档收尾。
- backend树 `24f0584db804775d4b88af8853cbab0af63dff46` 与测试工程最终1882项/14跳过/2项既有警告/91.07%的完整检查相同，Ruff/mypy442文件通过；未重复运行不变后端，不把27项专项冒充完整检查。
- 更早a0b2树完整166文件1102项通过，发生在最后竞态补修前，仅作为历史记录。新树已独立完整复验，没有套用旧结果。
- S15计划创建按钮改为“创建计划”，保留原创建/排队/完成断言，新增实际返回run.id、详情及URL检查后再关闭；S19保留原Cron、优先级及可视操作区断言并更新同一按钮名称。两文件格式/ESLint和用例发现检查通过，未扩大超时/重试或跳过场景；完整Compose浏览器门禁另行确认。

开发中保留了自有测试/工具错误：最初基线误列尚不存在的Hook测试，改为实际2文件；新工作区安装需要--extra dev，修正缺pytest-cov的配置；测试等待权限可用、按可见弹窗范围查询，处理Antd测试固定ID及保留的隐藏下拉菜单。没有提高超时、跳过或削弱核心断言。

## 真实 PostgreSQL、浏览器与 Worker

隔离Compose `flowtest-product-completion`、端口13078及隔离Chromium，项目 `98ed1f70-df68-4c4c-9ccd-5edc17f23434`，唯一标记 `隔离合成审计M12-1792558136065`。未修改用户3000端口或其他项目；现有PostgreSQL0064保持，不重复回滚测试工程新增引用。

1. 在专用项目创建并显式发布v1合成工作流、独立用例和套件成员，目标仅为受控mock-target健康接口。准备A/B/C三个独立环境；用例固定B，套件成员固定C。它们是验收fixture，没有修改真实用户资产。
2. GUI组织工作流、用例、套件，再将套件上移，实际保存顺序workflow/suite/case、版本1/1/1、重试1/0/0。拦截首次创建为503，保留三项及名称/trace，恢复后仅一次真实201，原失败未产生记录。
3. 真实计划 `8b0b7409-1001-42eb-9917-72940abdf662`，显式运行 `bef27fcc-620b-46d7-91a6-160140e2ba21` 返回202；刷新及返回打开同一运行。Worker终态为passed，三项位置0/1/2分别保留A/C/B环境和v1，三次实际执行均passed。
4. 对应执行ID为42646443-d536-499a-bb7c-008c5eb3c282、f0af3188-8439-43a2-a310-b6be36dcea15、cafd497f-5bcf-4c28-b3f0-05a1b1cf4940。报告/编排入口继续使用每项真实执行ID，未将排队当完成。
5. 再通过真实API创建20个明确命名的停用计划作为分页样本，不运行它们；原计划变为第21条，目录总数21。第1页不含原计划时从focus直接打开，刷新仍相同；另一个受权项目使用原ID收到404/trace、无操作入口、不替换对象。检查阶段命令0、页面异常0。
6. 真实API验证101项422、未发布用例404、跨项目工作流404，均有trace，前后计划总数仍21。额外未发布用例仅作拒绝样本，没有发布/执行；真实选择器不显示该目标。
7. 桌面1440/document1440，手机390/document390，修复后计划与队列上下排列，详情及创建弹窗稳定进入视口。只读截图与竞态补验不会创建新运行。

主要日志：`remediation-task-positive-browser.log`、`remediation-task-run-actual-status.log`、`remediation-task-offpage-seed.log`、`remediation-task-offpage-browser.log`、`remediation-task-mobile-layout-responsive.log`、`remediation-task-rejected-targets-browser.log`、`remediation-task-selected-run-race-browser.log`。位于忽略的output/playwright/audit-20261019目录。最终截图包括remediation-task-plan21-mobile.png、remediation-task-run-mobile.png及稳定后的桌面详情；已逐张目视核对。

## 改动与待确认

- 前端：[创建与逐项编组](../../../../../frontend/src/features/task-plans/CreatePlanDialog.tsx)、[准确计划详情](../../../../../frontend/src/features/task-plans/FocusedTestPlan.tsx)、[状态/URL与迟到响应](../../../../../frontend/src/features/task-plans/use-test-plans.ts)、[原SDK合同](../../../../../frontend/src/features/task-plans/task-plan-service.ts)、[运行详情](../../../../../frontend/src/features/task-plans/TestPlanRunDetails.tsx)、[页面](../../../../../frontend/src/pages/TestPlansPage.tsx)、[手机样式](../../../../../frontend/src/features/task-plans/task-plans.css)。
- 后端路由、服务、执行引擎、模型、签名秘密及调度策略保持；只对接已有功能。
- 本批最新HEAD正式Required Gate、审查、GitHub合并和合并后回归尚需确认；未做正式部署或真实Windows实体终端验收。全站73项仍未全部完成，M13环境实验室继续整改。
