# 第十八批整改：总览全量统计与精确质量证据

对应冻结审计 [M01](../../audits/2026-10-19/complete-audit.md#m01) 与 [详细方案](../../audits/2026-10-19/remediation-plan.md#m01)。完成 F-DASH-01、F-DASH-02；不修改原73项审计基线。

## 实际问题与修复

1. 原总览使用首100条Flaky记录的长度和隔离数量作为资产总数。新增受项目读取权限保护的只读 `GET /projects/{project_id}/flaky-tests/summary`，单次SQL聚合整个项目，不拉取全部记录。按 `(target_type,target_id)` 去重统计资产，另提供版本记录总数、正分版本数与隔离版本数，隔离资产无需是假定的正分资产子集。保留原Flaky算法、执行与隔离行为。
2. 响应明确 `project_cumulative` 范围、聚合时刻及记录更新时间范围。总览标明累计资产/版本分母，与风险卡片的冻结窗口分开解释。读取失败时为未提供并保留trace；不回退到已加载样本或零。当前权限允许读取核心Flaky记录时，其统计独立于可选质量智能风险开关。
3. 问题队列保留首100条及已载入/目录总量说明。每个入口携带 `record,target_type,target,version`，质量中心按ID补取页外记录，核对原目标和版本后读取固定证据，保留浏览器返回、刷新及返回项目总览入口。旧的仅record链接继续兼容。部分元数据、非法正整数版本、跨项目/记录或目标版本不符均明确失败，不替换成首项或最新版本。
4. 质量中心查询键包含完整定位参数，切换目录记录时清理旧目标元数据，隔离回执仍按记录查询前缀失效。固定版本证据与原运行关联沿用第十七批实现。
5. 真机尺寸浏览器发现390px页面宽470px，进一步定位为最近运行表格的最小宽度。补充卡片min-width约束、手机网格和表格横向滚动后，document宽390px。分页不丢失，桌面布局继续保留。

## 回归与反例

- 后端新聚合回归先复现2项422失败（summary被动态记录UUID路由误识别），新增静态路由与服务聚合后，具名3文件7项通过。覆盖150记录、首100仅10隔离而全量30隔离；同资产多版本去重、相同UUID不同目标类型、零分隔离、空项目、Viewer读取、跨项目404/trace、未登录401及无审计写入。
- 前端新增公开行为回归先复现7失败/30通过；补修后4个具名文件65项通过。覆盖全量与样本分离、聚合503时样本仍可读但总量未知、相同资产不同版本的精确链接、元数据不匹配/不完整、旧项目迟到响应、错误项目/范围响应、页外原版本、准确运行链接及原权限边界。
- 所有已有测试保留；新增长请求测试通过真实切换项目后释放旧响应验证查询隔离，没有重试请求掩盖覆盖问题。

## 隔离浏览器回执

使用Playwright技能的隔离Chromium和独立Compose `flowtest-product-completion`（13078）。原3000项目及个人浏览器未改。复用第十七批明确标注的专用合成目录项目 `fc3f1f13-763a-43c0-88ae-8d9f26925ca7`，没有重复种数据、运行计划、执行隔离或其他业务写入。

- 实际PostgreSQL聚合150项资产/150条版本记录，149项正分资产、30项隔离；首100条仅10项隔离。首页149/30，队列明确100/150。
- 点击队列真实链接，定位记录 `01227eba-3f5f-4bac-a5cd-aeb1542dab7b`、workflow目标 `7421ffe1-4717-4990-82a0-8bc60cba6166` v1；返回首页、浏览器后退和刷新保持同一原始定位。此目标为合成目录引用，不冒充真实执行资产。
- 原真实记录 `ae4292c4-0a74-4ead-b33a-6c0c59d3234f` 继续打开流程v1，指纹 `67c1bda2227cc83ff696528db53c7b5e74bdeef5661722ebdb7578c6009766ea`；将链接改成v2明确拒绝且没有隔离控件。
- 明确合成503拦截：全量未知、trace可见、样本入口仍存在，队列标不完整。明确合成迟到200拦截：切到M13项目后释放旧项目999999计数，当前项目未受污染。拦截仅验证前端时序，没有后端写入。
- 最终1440px与390px截图逐张目视核对，手机document390；业务写入0、页面异常0。首轮脚本在刷新后使用全页文字定位碰到目录同名，修正为证据卡作用域；第二轮真实尺寸检查发现宽度问题后修复，没有提高超时。

日志位于忽略目录 `output/playwright/audit-20261019`：`remediation-dashboard-summary-before.log`、`remediation-dashboard-summary-after.log`、`remediation-dashboard-frontend-before.log`、`remediation-dashboard-frontend-final.log`、`remediation-dashboard-browser-final.log`。截图为 `remediation-dashboard-main-desktop.png`、`remediation-dashboard-main-mobile.png`、`remediation-dashboard-summary-error-desktop.png`；宽度反例与诊断另存。

## 完整检查与交付边界

应用/测试源码提交 `0eab68dc99f29be459ad934f86115f10e4a6b199`，backend树 `340518ebd2e9cdc0d621af4f1e29745e7d966495`，frontend树 `05cf78b7fb17edc2df53eae31ca85764ae602a65`，src树 `39a47dea24acdc15756a85002638b9d6ce526c44`。

- 最终 `make check` 完整通过：647文件Ruff格式、Ruff检查、mypy442文件，1890项后端测试通过/14项既有跳过/2项既有警告，覆盖率91.09%；前端格式、ESLint/TypeScript、172文件1172项、生产构建通过，无未处理异常，覆盖率86.03/82.19/85.82/88.60%。完整日志 `remediation-dashboard-mobile-final-check.log`。运行期间此工作树应用和测试源码冻结。
- 手机补修前的一轮make check主动中断，退出130，未计作通过；旧日志 `remediation-dashboard-final-check.log` 保留。
- 本地专项浏览器不等于完整Compose框架验收；未运行实体Windows、外部Provider/Broker或正式环境部署。本批尚未获得独立最新HEAD远程门禁及合并确认，不能据此宣称已全部交付。

累计52/73项完成本地实现和验证，剩余21项；R3余M16/M17/M19共6项，R4十五项。GitHub已合并项仍按独立回执计算。
