# 第二十三批：M21 上下文检查器联动

对应冻结审计 [F-CTX-01](../../audits/2026-10-19/complete-audit.md#f-ctx-01) 与[实施方案](../../audits/2026-10-19/remediation-plan.md#f-ctx-01)。原审计、原方案保持不变。

## 实施结果

- 将详情分为概要、完整性与冲突、证据、知识关系、关联提案五个可切换区域；保留既有状态、Provider统计、完整性、知识和提案能力。
- 冲突按当前固定修订的完整证据指纹定位，显示匹配数和原始指纹；来源类型、确定性、警告及同一来源修订可以组合筛选，显示当前/总量。未知引用明确提示，不按相似内容猜测。
- 证据详情提供上下文修订、证据ID、来源ref/revision、路径、主题、置信度、指纹、警告及完整Finding原文；复制不额外读取凭据或Secret。
- 知识节点、关系两端和evidence_ref联动到唯一匹配的证据；未知或重复引用不生成外部跳转。关系显示相关数/总数。
- focus、revision、当前分区、筛选与证据/知识选择进入URL，刷新恢复；目录分页可直接定位，目录限高，证据/知识列表各自分页。
- 当前详情接口仅返回当前修订。旧revision链接会阻止将新修订冒充旧修订，明确显示两者身份，并要求主动选择“查看当前修订”；不夸大为所有历史接口均不可用。
- 过期只读、缺失引用、服务错误和目录/详情重试明确区分；响应的项目与对象身份不符时停止展示，直接Data Router切换期间的迟到结果不能覆盖新选择。
- 保留实际Flow Proposal深链；页面不增加扫描、Review、Apply、执行等写入能力。

## 代码与检查

实施提交 `986ced4b45539bc84e18f90e84e9f71dfbd194c1`；前端树 `ebc047dac9e91ee5853692e13e81d80df7ab69af`。变更位于ContextInspectorPage、context-inspector服务/Hook及新证据、知识、导航组件；同步S57既有验收步骤以切换到对应分区，保留原可见性与Proposal断言。

针对性前端5文件20项通过，覆盖共享Context分页的失败修复和回归维护消费者；后端既有S49/S57合同7项通过。全量前端177文件1259项通过，无未处理异常，覆盖率语句86.10%、分支82.40%、函数85.87%、行88.64%；格式、lint/类型、构建通过。详见[验证补充](batch-23-validation.md)。

先补反例再实现：联动/旧修订3项失败、原6项通过；增加未知/外项目/迟到响应后最终20项通过。中途JSDOM深层Card/Table样式计算导致取消的检查均保留为未完成；压平布局与改为紧凑分页列表后通过，没有放宽超时、重试、覆盖率或原可见性断言。

## 真实浏览器验证

在自有隔离Compose `flowtest-product-completion` / `127.0.0.1:13078`，使用已拥有的隔离项目 `fc3f1f13-763a-43c0-88ae-8d9f26925ca7`。原3000端口环境未改动。

通过受限临时服务账号创建2个明确标注的合成Context、3次合成证据摄入和1个未应用Flow Proposal；账号在finally中撤销。凭据只在进程内使用，不写日志或文件。合成资料不代表被测系统结果。

- 冲突Context `9212559b-09d1-466f-b099-281dfb1771bb`，旧修订 `8da25da7-691d-41d3-a0c0-b73a3a36b138`，当前 `ad9bfbb9-a34b-410b-8ec8-feea7b06cbb2`：旧修订阻止替换、主动切换当前、冲突→契约Finding、1/2计数、URL刷新恢复通过。
- 知识节点 `state.m21` → 仓库证据，筛选恢复2/2，source_ref/revision/path一致。
- 就绪Context `89968cce-4e3b-49f3-a3ab-709f5c308e0c` → 实际Proposal `d9af57c2-5a8a-4372-a893-411ef2812a15`：打开真实“Flow Proposal 可视化审核”，未审核或应用。
- 1440px与390px截图已检查；390px文档宽度390，无横向溢出。
- 资料准备8次业务HTTP写入（含账号创建/撤销）；随后实际页面联动验证业务写入0、页面异常0、发布/执行0、AI队列0。首次准备时遇到并发认证刷新409，未重复资料写入；其后资料成功一次，受限账号已撤销。

原始日志、截图在主工作树 `output/playwright/audit-20261019/remediation-context-*`。关键日志：`remediation-context-links-browser.log`、`remediation-context-final-targeted.log`、`remediation-context-backend-contracts.log`、`remediation-context-full-frontend.log`。

## 交付与剩余边界

F-CTX-01本地完成，本地61/73、待完成12。R3 PR145在精确HEAD `4599b91904c93cfaba84742d75c431d68ca23e50` Required Gate成功、两条评审均解决且完整分页无遗漏后，合并为main `cbd6410840b99f5fa7c2c55910a58456927fef23`；已合并58/73。其独立主分支Full Regression为运行39625538263，记录时仍运行，不能写成已通过。

本批与M20的远端最新HEAD门禁、完整Compose S21/S57及正式部署仍单独验收。M22及之后12项继续实施。通用AI审核入口已有服务端change_set守卫，M22反例已确认接受/拒绝均409；不把它记为已确认的绕过漏洞。
