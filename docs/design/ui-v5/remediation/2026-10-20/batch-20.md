# 第二十批：变更回归来源与冻结证据链

对应冻结审计 F-REG-02、F-REG-03；原审计和方案保持不变。M17 本地完成，累计56/73项，余17项。GitHub交付单独记录，不能把本地完成当作已合并。

## 来源编辑与校验

- 新建链路支持可选Git diff、OpenAPI、GraphQL、Proto版本对比及组合；从真实项目目录提交版本ID，至少一种有效来源即可。创建表单可收起，未提交输入保留；只读角色不能打开写入表单，能力关闭时仍可查看历史。
- 前端拒绝无来源、不完整配对、相同版本、目录外或协议错误的引用。后端新增共享输入验证，防止已有Git diff掩盖同版本OpenAPI/Schema配对；项目与协议授权保持原服务校验。没有改变执行算法、数据库或自动脱敏策略。
- 冻结来源入口按原ImpactRun读取source_summary、指纹和原版本，不改用最新目录。OpenAPI打开固定证据抽屉，GraphQL/Proto使用既有版本定位入口；Git摘要没有原diff时明确只可核对指纹。

实现：[来源表单](../../../../../frontend/src/features/change-regression/RegressionSourcesEditor.tsx)、[配对合同](../../../../../frontend/src/features/change-regression/regression-sources.ts)、[冻结版本](../../../../../frontend/src/features/change-regression/RegressionSourceSnapshot.tsx)、[后端验证](../../../../../backend/app/schemas/impact.py)。

## 逐环节证据与状态

- Impact、TestPlanRun、ReleaseDecision均使用准确ID定位；当前链路写入URL，后退和刷新保留选中。详情响应核对项目和记录身份，未知ID不回退到另一条记录。
- FailureTriage只解析受支持的内部引用，先按本链路的父计划运行核对执行或运行项归属，再提供节点或运行项链接。未提供的协议、尝试和迭代实例明确说明；不支持、越界、读取失败的引用保留原文和原因，不生成假跳转。
- 计划运行接收item定位，自动翻到对应20项分页并高亮；可返回选中项。缺项与读取失败分别提示。生成资产显示物化ID、原审核设计、固定版本及维护入口，不能从设计ID猜测不存在的资产。
- 慢命令绑定发起时项目；切换记录、项目或卸载后不导航、不弹迟到提示。历史分类字段不完整时保留原始读取器，避免页面崩溃。门禁已评估但因执行失败阻断时，显示“评估已阻断，未生成独立发布判断”。
- 手机将语义描述和豁免表单改为响应式列，宽表在自身区域滚动。实测从693px页面溢出修正到390px，未用整体隐藏溢出来遮挡控件。

实现：[页面](../../../../../frontend/src/pages/ChangeRegressionPage.tsx)、[证据链](../../../../../frontend/src/features/change-regression/RegressionEvidence.tsx)、[命令与读取](../../../../../frontend/src/features/change-regression/use-change-regression.ts)、[运行项定位](../../../../../frontend/src/features/task-plans/TestPlanRunDetails.tsx)。

## 行为验证与审计纠正

1. 新来源与证据测试先复现缺失行为；额外慢响应、URL身份与不完整历史测试为6失败/20通过，并复现历史分类join崩溃。补修后通过。
2. 后端同版本混合Git的真实缺陷为4失败/5通过；修复后4个具名文件39项通过，Ruff和mypy442源文件通过。
3. 输入冻结在20c3ffb39e4ceb0b686bb1a0f38927b8cfa4857a：backend树3d6cd0079b4d23d44da58ca0a1edfa219841696e完成1899通过、14既有跳过、2既有警告、91.10%覆盖率；frontend树8c8b7b647fb60bbc284c7b0769484456fc274394完成173文件1210项、无未处理异常、覆盖率86.12/82.32/85.96/88.69%，格式、lint/TypeScript、生产构建通过。完整日志remediation-regression-backend-full.log和remediation-regression-frontend-full.log。
4. 浏览器继续发现693px手机溢出及门禁阻断提示不准确；提示测试先1失败/28通过，再补修bdbea80。最终frontend树e5c527569881846188c71b84ca356773686a7e4e、src树32f061cf80afd59913e33ac6f3ea2b7c999e0fde完成3个具名文件47项、lint/TypeScript和构建，日志remediation-regression-final-47.log、remediation-regression-mobile-build.log。1210项全量只绑定补修前的树，没有冒称最终树的1211项全量已跑；最终整合PR仍需完整门禁。
5. 两次浏览器只读脚本分别因抽屉遮罩和中文“关闭”按钮定位失败；均已执行到来源、返回及手机检查，没有重复创建或执行。纠正自动化关闭顺序与真实按钮名称后，最终remediation-regression-linkage-final-r2.log通过，页面错误0、业务写入0、队列命令0，失败和来源页面document宽均390。

## 隔离项目真实验收

使用专用Compose flowtest-product-completion、端口13078和既有合成项目fc3f1f13-763a-43c0-88ae-8d9f26925ca7，未修改原3000项目或个人浏览器。

- OpenAPI来源链路039e6dae-e364-494b-91df-6262a29e50ae通过真实表单创建，Git为空、未生成草案、未执行。基线bb58649d-88a8-4b04-a0f9-79e2d37d0d8d、当前5ed464d0-a93c-49c7-848a-8b25f744156c；新增契约9930f1ff-7cd3-4e97-af96-5ec8c56ba3bc后，原source_summary与指纹da8cc325217647f1cbbefdfacc0f545c63cfe15597bbe792be9258f75e8461c8不变。
- 受控失败链路65c21ce9-6f7e-44db-98ba-c9a597612f31：只显式执行一次内部GET /health，断言预期201而实际200。计划运行87a1c6d1-7d31-4a8b-adf1-6facb4bbaff0失败、尝试1次；实际执行4e9105f7-ebcd-463d-a246-4306f2b4352a的m17-check节点可定位。失败分类按既有规则在显式门禁评估后生成，正确BLOCK且无独立ReleaseDecision，未把执行完成误当已产生分类。
- 受控通过链路e7a9aea7-1af0-4c7c-b9be-43340d58bfb0：只显式执行一次内部健康检查，固定流程v2。计划运行19e96197-b845-4be4-b864-0aa79d622e8b、影响3e22dcf4-c1ee-47b1-83da-838683a47e3e、独立发布判断ac31fcbd-e215-4c80-a3e2-4609d97f7181均逐个打开并返回原链路。
- 本批共19个显式业务写入请求，其中2个入队命令；随后只读复验新增写入0。未重跑M18/M16的历史种子，未自动发布或部署。两次真实执行会自然增加本项目质量记录，后续不能继续使用M18早先150条样本的计数作为当前值。
- 1440/390px桌面、来源和失败页面截图保留在忽略目录output/playwright/audit-20261019。来源抽屉与同链路返回通过；不以合成单元fixture冒充真实执行。

本批未执行正式部署、实体Windows或全站设计签收；这些与本地、当前HEAD门禁及合并后回归分别验收。
