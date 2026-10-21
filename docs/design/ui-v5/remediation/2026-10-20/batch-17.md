# M18 质量中心整改记录

依据：[质量中心审计](../../audits/2026-10-19/complete-audit.md#m18)与[F-QLT-01/02实施方案](../../audits/2026-10-19/remediation-plan.md#m18)。本模块先于总览整改，提供其所依赖的准确Flaky记录入口。

**两项完成本地整改与验证，累计50/73项本地完成、23项待完成；已合并仍为39项。** 后端最终1888项、前端1162项完整通过。最新GitHub门禁、合并与正式环境验收另行确认。

## 逐项对应

| 问题     | 最终交互与实现                                                                                         | 验收边界                                                       |
| -------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| F-QLT-01 | 启用门禁按enabled筛选，另标总数；加载/失败不以0表示未读数据                                            | 2启用1停用显示2/3，全停用显示0/3，失败显示未提供               |
| F-QLT-02 | 风险历史可选，risk/record与四类目录页码进入URL；页外记录独立读取固定资产版本，运行/基线/样本可准确打开 | 同页非首项、页外记录、翻页、刷新、返回与跨项目拒绝均有行为验收 |

统计只改变显示口径，不改变门禁评估、Flaky算法、隔离策略、执行引擎或脱敏/采集政策。

## 风险历史与冻结证据

- 当前风险ID固定在URL，翻页只改变目录页码，不隐式选中下一页首项。首次默认选择最新记录后固定其ID，显式失效/无权限记录保持错误，不替换为另一条可见记录。
- 历史默认收起，按“切换风险快照”展开；20条目录在最高300px区域滚动，保留完整服务端分页。刷新保留风险及目录页码，历史面板重新收起，当前冻结证据仍可见。
- 风险推荐提供工作流、测试用例、OpenAPI、Pact及性能场景的已知固定证据入口。工作流/用例/套件按原版本读取配置及指纹，不借当前草稿补齐失效历史；契约复用固定证据查看器，不触发Provider验证、Broker访问或生成草稿；性能定位到不可变场景ID。
- 失败聚类样本直接携带execution ID打开报告；计划运行与基线携带run ID，已知计划同时带focus ID。JUnit下载保留原处理路径。

主要实现：[质量证据组件](../../../../../frontend/src/features/quality/QualityEvidence.tsx)、[读取与命令](../../../../../frontend/src/features/quality/use-quality-center.ts)、[导航](../../../../../frontend/src/features/quality/quality-navigation.ts)、[页面](../../../../../frontend/src/pages/QualityCenterPage.tsx)。

## Flaky准确记录与独立隔离

- 新增受权只读GET `/projects/{project_id}/flaky-tests/{record_id}`，业务授权与项目边界在QualityService，router只转换DTO，沿用既有READ权限与标准错误/trace。无模型、迁移、日志或采集变更。
- record链接独立于当前目录页，显示完整资产ID、版本、累计通过/失败、最后更新、最后一次计划运行及原始版本指纹/配置。客户端核对记录/风险响应的ID及项目，错误不冒充另一条记录。
- 页外所选记录可显式隔离/恢复，操作始终传原record ID；目录开关的可访问名称包含目标版本。读取、切换、预览不会隔离或运行；Viewer禁写，权限刷新失败不使用缓存的旧编辑许可。
- 项目、URL上下文变化及卸载后忽略旧成功/失败和下载反馈；命令参数固定发起项目。编辑弹窗随项目重置，旧回执不能关闭新项目表单。

接口与回归：[router](../../../../../backend/app/api/v1/endpoints/quality.py)、[service](../../../../../backend/app/services/quality.py)、[只读/授权及分页测试](../../../../../backend/tests/test_quality_record_reads.py)、[前端SDK](../../../../../frontend/src/features/quality/quality-service.ts)。

## 额外复审与补修

1. 原生路由测试先复现旧门禁、风险、隔离成功/失败在项目切换后仍提示或改URL，以及权限刷新失败仍可编辑。补充生命周期与路由器当前location核对，写入只在权限读取成功时允许。
2. 默认风险从页内数据写入URL时，详情组件的key一度从空值变成ID，关闭刚打开的推荐证据窗。改用已解析的activeRiskId作为身份，首次规范化URL不再重建同一详情。
3. 149条明确合成目录记录加1条真实记录的PostgreSQL验收中，原8页共150行只有139个唯一ID，出现11条重复。新同分、同更新时间46条交错插入回归先失败，再在原排序后补ID升序；同一150条数据重读为150个唯一ID、重复0。总数、评分、隔离及真实记录均不变。
4. 手机8页分页条曾撑宽到492px；质量网格改为单列、分页换行及总数独立成行，实际document宽恢复390。Flaky目录最高360px，网格不把短门禁卡拉成空白长卡；当前风险与固定记录优先，完整目录仍可滚动。
5. 单测的Modal在JSDOM保留ant-zoom-appear/opacity0，诊断记录确认并非请求未发出。测试宿主关闭动画，保留所有可见性、准确引用、trace和写入次数断言；产品动画不变。没有提高超时、重试或删除断言。
6. 对照失败状态验收发现：部分目录读取失败仍出现“暂无记录”，历史收起时隐藏读取错误，指定风险错误省略trace。新增/加强五项回归先复现5失败/18通过，再区分成功空数据与未提供、清除错误态的旧目录、在收起态显示错误并保留trace。补修后30项专项和浏览器四类503/指定风险404注入全部通过，原ID与独立固定版本读取保持，写入和队列命令均为0。

## 真实样本与浏览器回执

独立Compose `flowtest-product-completion`、13078端口、隔离Chromium。原3000项目与个人浏览器未改。专用项目 `fc3f1f13-763a-43c0-88ae-8d9f26925ca7`，名称`隔离合成审计M18-1792570400897`。

- 通过实际API创建环境、健康接口、流程v1与计划，仅显式运行一次内部GET /health。计划运行`575bcfb6-ba2a-4f9a-a85c-1b0c5aea4b9e`通过，执行`0afd8bde-8ee2-4264-8f79-1c7a354a824a`；没有额外队列命令。
- 原Flaky记录`ae4292c4-0a74-4ead-b33a-6c0c59d3234f`对应工作流`9b9e9602-474b-48fc-9679-f0029dba564f` v1，1次通过/1次总运行、得分0。随后发布v2，原v1配置/指纹不变：`67c1bda2227cc83ff696528db53c7b5e74bdeef5661722ebdb7578c6009766ea`；v2为`4bd44c028d02eae4bdca80e58498a7e8e08fd1823e0d9548ec1f39f01c8d4d33`。
- 实际创建2启用1停用门禁、显式Mapping与一条只读Git Diff影响分析，再通过原风险API生成22条冻结记录。没有执行仓库命令。风险生成在后续合成目录插入之前，冻结Flaky因子仍为当时的0，不随当前目录变化。
- 149条数据库目录记录**明确为合成分页fixture**，不充作149次真实执行；加真实记录共150条、当前149项正分、30项隔离。原真实记录在页外，首100条只有10项隔离。新增读取接口直接恢复其v1，推荐工作流证据独立打开v2。
- 历史旧记录`2b34bff6-1943-4962-89d6-f6f31e6e042e`、当前记录`6e1cfb30-eb52-4e1e-81f3-ed0e7909c8f1`位于第2页；选择、切第1页、刷新、打开计划运行及返回均保持当前风险和Flaky身份。跨项目读取实际404并带trace。
- GUI对原记录明确隔离再恢复，只有两次真实PUT；只读审计回执核对序列`[true,false]`，最终恢复未隔离、原目标v1不变。其余截图、翻页与复验写入0。
- 真实浏览器以明确的合成200拦截补验迟到隔离回执：在切到M13项目后释放，仅验证前端时序，不进入后端写入。没有旧导航/成功提示，返回后原记录仍未隔离。
- 最终1440px与390px截图逐张目视核对，手机document390、历史滚动区300px，页面异常0；风险历史、固定版本、精确运行入口及分页全部可用。

主要日志位于忽略目录output/playwright/audit-20261019：`remediation-quality-project-seed.log`、`remediation-quality-offpage-seed.log`、`remediation-quality-quarantine-readonly-receipt.log`、`remediation-quality-pagination-readonly.log`（修复前139唯一）、`remediation-quality-compact-browser.log`（修复后150唯一）、`remediation-quality-late-project-response.log`、`remediation-quality-read-errors-browser.log`（明确合成故障注入）。截图为`remediation-quality-main-desktop.png`、`remediation-quality-main-mobile.png`、`remediation-quality-fixed-record-mobile.png`及`remediation-quality-evidence-desktop.png`。

首次GUI脚本在只读阶段错误使用中文关闭按钮名，实际基础组件为Close；修正后从相同既有样本继续。第二次完成所有桌面交互和两次隔离写入后在手机宽度检查失败，后续只读恢复，没有重复种数据、运行计划或重放隔离。

## 检查与源码边界

- 两个具名前端文件最终30项通过，覆盖门禁口径/未知状态、非首项风险、刷新/返回、页外原版本、失效/跨项目、四类推荐入口、隔离准确写入、六类迟到成功/失败、权限刷新失败和各目录错误状态。原测试均保留。最终专项日志`remediation-quality-read-errors-after.log`；更早26项日志只对应补修前输入。
- 后端两个具名文件5项通过。分页新增回归修复前1失败/1通过，补修后5项专项通过，未通过重复请求掩盖排序缺陷。
- 最终backend树`f9576a75393421612feb7982ba2cc4e1196a05fc`：646文件Ruff格式/检查、mypy442文件、1888项测试通过，14项既有跳过、2项既有警告，覆盖率91.09%。日志`remediation-quality-order-final-backend-full.log`。
- 最终整合源码`81a003a8f8f2ca3a9fac3afe540116adf10b05eb`，frontend树`bc19a031672c1a86be489da12f570ab175510234`：格式、ESLint/TypeScript、172文件1162项及生产构建完整通过，无未处理异常，覆盖率86.03/82.16/85.82/88.60%。日志`remediation-quality-read-state-final-frontend-full.log`，运行期间应用/测试源码冻结。更早2fee1ae的1156项及935e02c的1158项完整通过只对应各自原树；16ea1f5检查为后续版式调整主动中断130，没有计作成功。
- 本地未运行完整Compose框架S19与实体Windows验收，亦未宣称正式部署。新分支PR、最新HEAD正式Required Gate、审查、合并及合并后回归须独立确认。
