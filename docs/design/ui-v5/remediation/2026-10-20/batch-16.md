# M14 性能实验室整改记录

依据：[F-PERF-01/02 实施方案](../../audits/2026-10-19/remediation-plan.md#m14)与[冻结审计](../../audits/2026-10-19/complete-audit.md#m14)。本轮保持声明式编译白名单、既有权限、网络策略和执行后端，不接受用户脚本。

**两项完成本地整改与验证，累计48/73项本地完成、25项待完成；已合并仍为39项。** R2全部完成本地验证，后续R3十项、R4十五项继续实施；最新GitHub交付另行确认。

## 复杂场景与版本维护

- 新建和新版本共用完整可视化编辑器：最多20个HTTP步骤、请求头、JSON请求体、预期状态码与小数暂停；固定VU和最多20个阶梯阶段；最多30项阈值、单位、提前中止、延迟及优雅停止。
- 切换负载模型保留两边的未保存输入，仅提交当前模型允许的字段。所有预算与声明式合同校验保持一致，超限、未知字段和非法JSON明确提示。
- 原版本保留，修改保存为独立草稿；发布后才允许派生新版本。原配置摘要、字段差异及JSON预览分开呈现，高级JSON只有显式应用才进入表单。关闭、路由跳转和刷新均保护未保存输入。
- 手机标题、操作、阈值和阶梯表单可换行；长标题弹窗使用有界容器，正文独立滚动，底部按钮保持可达。同类环境模板弹窗同步这一布局边界。

## 新运行与证据身份

- 运行成功使用202返回的真实ID写入URL及详情缓存，清除场景选中；显示版本、排队/开始/完成时间、冻结摘要、阈值及原始指标。
- 从旧运行上下文启动后直接进入新运行，旧链接可返回和刷新；终态前沿用有界轮询。失败保留原场景，带trace错误，仅显式重试才再次发起命令。
- 项目/对象切换、卸载后忽略旧成功与失败。额外复审在真实浏览器发现：路由已切换但React尚未提交时，旧上下文引用仍有效。新增两项原生路由测试先复现失败，再以路由器当前location key与发起时location核对，阻止旧回包导航、缓存选中和提示。
- 同一时序补查M12和M13，先分别复现旧任务选入运行与旧环境清理提示（2失败/7通过），再补上路由当前身份核对。11个受影响文件64项通过；日志`remediation-r2-sibling-race-before.log`和`remediation-r2-sibling-race-after.log`。没有改动后台执行或重复发起真实命令。
- P95和回归指标显示两位小数，缺失数据不添加单位；手机概览两列，桌面目录固定名称/操作，手机使用有界横向滚动。截图必须等待响应式固定列更新后截取，不能用视口调整中的瞬态布局判断最终效果。

主要实现：[页面](../../../../../frontend/src/pages/PerformanceLabPage.tsx)、[编辑器](../../../../../frontend/src/features/performance/PerformanceScenarioDialog.tsx)、[声明式字段](../../../../../frontend/src/features/performance/PerformanceDefinitionFields.tsx)、[表单合同](../../../../../frontend/src/features/performance/performance-definition.ts)、[命令与读取](../../../../../frontend/src/features/performance/use-performance-lab.ts)、[响应身份校验](../../../../../frontend/src/features/performance/performance-service.ts)。

## 隔离浏览器与真实运行

专用Compose项目`flowtest-product-completion`、端口13078，专用合成项目`2ddd1783-aef1-4b2f-bda3-12c96706fc32`。原3000项目与个人浏览器未改。独立性能worker遵守现有非特权、只读文件系统、cap_drop和网络限制，只访问内部mock-target。

1. 场景A v1 `a2460f16-e1a2-4243-bb39-1fb35127ab59`：两个HTTP步骤、两个阶梯、请求头/请求体及0.015秒暂停；模拟503后保留同一候选，仅重试一次真实201。v2 `77b50cd0-3237-45ee-a03a-fc9ea63be7cd`改请求头、正文和优雅停止，其余字段完整保留。v1先显式发布，v2保持草稿，两者均未执行；不以编辑/发布充作压测成功。
2. 安全场景B v1 `7ba1cf15-30a3-4a81-a97e-8cd83e60aab9`：两个GET /health、1VU/1秒。运行 `3b66c225-e55d-4063-babd-1752cace6f89`真实k6通过、100个请求，冻结摘要`a1568fe4788734f7acc80c66ac2401efac1d945b8263eb2b919e0204a0633f64`。
3. B v2 `3e890d6d-bc59-4588-b49e-fcfe2aba6297`仅将X-Revision改为safe-v2。从旧运行页面显式发起，返回运行 `8d6876cf-aec6-4319-aae8-eb493c68f14c`被立即选中，真实k6通过、98个请求，摘要`933f1051d3961e7959403c580b485bc3e30c3e2da525c355cb371b96f2adaafa`，原始指标产物`121c28b9-f296-4b49-aac3-7dd7024b2d72`。
4. 后退及刷新v1仍为safe-v1，前进v2仍为safe-v2，两个冻结摘要不变。真实压测只启动上述两次；后续只读复验未增加队列命令。
5. 跨项目迟到响应采用明确的合成202拦截，不进入后端队列。修复前能把页面拉回原项目；补修后切到M13项目保持原地址，合成运行读取0次，无迟到成功提示，再恢复真实v2链接。
6. 最终1440px目录/证据及390px概览/冻结请求截图均逐张目视检查；手机document宽390。长标题弹窗稳定位置x8/y24/w374/h796，内部body与scrollWidth均326，标题和底部操作可见。

证据位于忽略目录output/playwright/audit-20261019：`remediation-performance-real-run.log`、`remediation-performance-version-retry.log`、`remediation-performance-new-run-readonly.log`、`remediation-performance-editor-final-layout.log`、`remediation-performance-desktop-stable.log`、`remediation-performance-late-project-response-after.log`。首次双运行脚本已完成真实写入、历史与API验证后，因调整视口尚未稳定而失败；后续从既有运行继续只读验收，没有重建样本或重复运行。自动化定位和失败日志保留，不增加超时或重试掩盖问题。

## 验证及交付边界

- 原有三项原始指标下载测试完整保留；响应身份校验新增四项。中间编辑误覆盖旧测试已纠正，不能用缺少旧测试时的全量通过作为最终验收。
- 队列失败显式重试、草稿禁止派生版本及路由提交前竞态均先复现再修复。路由竞态修复前2失败/6通过；修复后5个具名文件32项通过，格式、ESLint/TypeScript和构建通过。日志`remediation-performance-precommit-race-before.log`、`remediation-performance-precommit-race-after.log`。
- 后端未改变，树`b10fd948e99922afa1dacaf6ced5914e8fd17622`沿用M13完整1886通过、14跳过、2项既有警告、91.08%及Ruff/mypy442通过；性能后端具名6项通过。
- 最终整合源码`989d4a1568a9227a1238a1822b80c22d53dcfa76`，frontend树`90ae16e9218941fb5ab24167c05b72c8c8df79f8`：格式、ESLint/TypeScript、171文件1138项及生产构建全部通过，无未处理异常，覆盖率85.99/82.04/85.81/88.56%。日志`remediation-r2-ownership-final-frontend-full.log`。检查期间应用和测试源码冻结；此前f395ccf的1134项与11c8087的1136项完整通过分别绑定旧树，没有冒充最终整合验证。
- S25更新真实界面标签和返回ID断言，格式、类型、lint及用例发现通过；本地未运行完整Playwright S25/S26框架流程，实际CLI双运行与远端Compose门禁分开记账。未执行环境容器Provision，不声称正式部署、实体Windows或全站设计签收。

M11认证覆盖来源修复`552b81a`、M12和M13已整合在本分支。准备通过既有PR #144交付四个模块，须核对推送后最新HEAD的正式Required Gate、完整审查分页、匹配SHA合并及合并后回归。旧d9bed230门禁通过不能替代该新源码的门禁。

## PR144 首轮整合门禁补修

`821d55377e1198383f3b9eda743980e999238b40`已更新至PR144，原auth覆盖审查线程已在修复交付后解决。正式运行39564951442的Compose作业失败：64通过、S26一项失败、S18及1440px几何两项重试通过。S26模糊标签同时匹配“模板版本ID”输入与“模板版本”下拉；补修改用准确combobox角色/名称、当前展开选项，并等待前两个写入弹窗关闭。S18在首页初始重定向尚未结束时打开导航，补充等待最终dashboard与标题再操作；几何测量279.99999618530273按百分之一CSS像素精度比较，280/400宽度预算不变。

没有提高超时、重试、跳过或移除业务断言。3个验收文件格式、ESLint/TypeScript、生产构建及8项用例发现检查通过，实际完整框架运行须由新HEAD的Compose门禁确认。本地没有执行环境容器Provision。应用与Vitest测试所在`frontend/src`树仍为`fd875d7bd6b25d541f6051f2f7de93b5594ed4f5`，既有1138项完整结果绑定这一未改变的输入；本补修改变的是E2E源码，不能用Vitest结果替代浏览器验收。失败完整日志`remediation-pr144-r2-compose-failed.log`及静态检查日志单独保留；当前仍39项已合并。

## Viewer 验收作用域与最终复验

旧运行39564951442因后续提交取消；其已结束的Compose失败仍按上述结果保留。补查已取消的前端作业日志时，发现任务执行Viewer测试曾以62.283秒超时失败。`2e4dfb696a9234377097dc6ac6db63c9e8504c8c`将四个按钮查询限制到当前render的标题、计划行和运行队列，减少全页可访问性计算；原四个禁用断言、实际点击及禁止请求计数0全部保留，没有提高60秒超时。初次精确文字定位遗漏图标的可访问名称，已恢复原匹配文字并保留局部范围。

该文件8项专项及ESLint/TypeScript通过；最终frontend树`26273ccbcd3be8f81f30e21ce442a5a0a9fa308c`、src树`80210dd552257f54024cd0fc38cf3988f2636a4f`重新完成格式、171文件1138项、覆盖率85.99/82.04/85.81/88.56%和生产构建，无未处理异常。完整日志`remediation-r2-viewer-final-frontend-full.log`，旧取消作业日志`remediation-pr144-r2-frontend-cancelled.log`及专项日志独立保留。后端树b10fd948e99922afa1dacaf6ced5914e8fd17622未变，1886项完整验证继续适用。新HEAD正式门禁、完整审查分页、保护合并及合并后回归仍分开确认。
