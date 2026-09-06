# V6.2 收尾：可靠性、效果验收与易用性

状态：可靠性/分页本地实现与集中验收完成，待 PR 复审及 CI；真实模型验收待接入确认，不标记 GA。
基线：S60 PR #88 合并提交 `6440e305cd2987ccec2f635b0e3ca0ca28933dc4`。
分支：`codex/v6-2-consolidation`。无数据库结构变化，Migration/Standalone 基线保持 `20260831_0051`。

## 本批交付

- Repair 与 Maintenance 的已完成操作回执可恢复；身份、Scope、项目编辑授权仍先执行。
  无既有回执才执行当前状态预检和 Claim，事务提交前仍重验。不同账号、项目、操作、请求不能共享回执。
  回执仅代表历史操作成功，不证明 Proposal 现在仍可审核、Preview 或 Apply；后续操作继续读取当前状态。
- Context Inspector、失败修复和变更维护三个入口均按需分页，每页 20 条，可访问第 101 条以后的记录。
  切页保留当前修复表单；切换项目不复用旧项目列表。没有全量拉取或扩大后端权限。
- S60 文档补入最终合并与主线六项 CI，保留本地首轮超时事实，不把 skipped 写成 PASS。
- 历史 P2 台账按原审查链接去重，区分已修复、部分缓解、延期；不因线程 resolved 宣称清零。

## 阶段完成矩阵

| 阶段 | 交付状态 | 验收边界 |
| --- | --- | --- |
| S48～S56 / H1 | 已合并 | V6 Core RC 自动化基线；保留已登记限制 |
| S57.0 / S57 | 已合并 | 基础正确性、Java Provider、State Knowledge、Context Inspector |
| S58 | 已合并 | 失败诊断、受限修复、人工审核及 Re-preview |
| S59.0 / S59A～D | 已合并 | 统一提案、Diff、Affected Flow、维护与原 Change Regression 接入 |
| S60A / S60 | 已合并且主线 CI 完成 | 五个 Skill 包、MCP 入口、独立评测；不是 LLM 效果证明 |
| 本轮 V6.2 收尾 | 本地验收完成 | 不预填 PR 或主线通过；模型效果仍待验收 |

## 历史债务核对

范围为原 12 项及 S57.0～S60 已登记后续债务，不是对全仓所有代码重新进行穷尽审计。
本轮不再次公开展开未修复问题细节，具体上下文保留在原复审。

| 项目 / 原始记录 | 当前状态与依据 |
| --- | --- |
| 原 12 项中的其他 11 项 | 已交付：PR #71～73、S57 Context Inspector、S60 自包含评测 |
| [PR #74 静态请求值](https://github.com/a3384379/FlowTest/pull/74#discussion_r3893225118) | 部分缓解，完整功能仍延期；现有 test_selected_scenario_path_and_cookie_inputs_fail_closed_without_disappearing 明确编译不支持 |
| [PR #72 Java 记录一](https://github.com/a3384379/FlowTest/pull/72#discussion_r3892760259) | 延期；未发现专门修复，不按历史线程状态清零 |
| [PR #72 Java 记录二](https://github.com/a3384379/FlowTest/pull/72#discussion_r3892760266) | 延期；DTO 解包不等于普通 Controller 的 Body 判定已修复 |
| [PR #75 MCP 参数记录](https://github.com/a3384379/FlowTest/pull/75#discussion_r3893634955) | 延期；SDK 调用前校验仍在业务错误包装之外 |
| PR #71 两项、PR #76 全限定引用 | 已在 S59.0 收口，见该阶段测试与验收 |
| PR #78 三项 | 已在 S59.0 收口，见 Patch Correctness 与 Unified Proposal Discovery |
| PR #82 来源、PR #84 两项、PR #85 范围授权 | 已在 S59C 收口，见其验收 |
| S59D 审核事务与 PR #87 旧评测副本 | 已在 S60 收口，见 test_s60_foundation.py |
| [PR #77 Context 分页](https://github.com/a3384379/FlowTest/pull/77#discussion_r3894507495) | 本轮已实现并有定向回归，待最终合并 |
| [PR #88 操作回执](https://github.com/a3384379/FlowTest/pull/88#discussion_r3942516451) | 本轮已实现并有定向回归，待最终合并 |

本范围本轮提交前为 6 项未完整关闭，其中 2 项在本轮修复、4 项继续延期；原 12 项的静态请求值
包含在这 4 项内，不重复相加。该数不冒充全仓历史缺陷总数，也不将“代码未发现修复”写成新漏洞发现。

## 真实 LLM 效果验收

方案见 [隔离业务验收协议](v6-2-business-acceptance.md)。本轮尚无真实模型运行结果，模型接入待确认。
既有 Golden 聚合、手写请求、契约测试、页面测试都不替代这项证据，也不填写无样本支持的成功率。
结构化修复编辑器、受控创建 Regression Run、CI 接入模板留待试用反馈排序，不在收尾中另建生命周期。

## 集中检查与发布边界

- Backend：Ruff Format/Check、mypy app 通过；完整 Pytest 1210 passed / 4 skipped，Coverage 91.13%。
- Frontend：Format/Lint/TypeScript/Build 通过；240 tests passed，Branch Coverage 80.34%。
  静态检查发现的组件复杂度超标已通过拆出分页展示修正，未绕过复杂度规则。
- 隔离 Compose：登录初始化、S57 Context Inspector、S58 Repair/Re-preview，共 3 passed。
- 操作回执定向回归先复现旧实现 stale 拒绝，再验证新实现返回原回执；另覆盖权限撤销、账号隔离、
  同键不同请求、新键仍执行当前校验以及无额外 Proposal/Claim。
- 前端回归验证直接取第 6 页、每页 20 条、不全量加载、项目切换归位，以及切页保留修复 JSON 编辑。
- 额外真实浏览器验收：隔离项目 `e1100e80-5b3f-4a84-ab5e-9b8c194a0017` 创建 101 条测试 Context，
  Inspector 点击第 6 页后显示最早的“V6.2 分页上下文 1”，列表总数为 101；未修改生产资产。
- 历史 Java 两项以纯内存样本复核：路由均可见，但所需 DTO 字段未产生；不据通用解包函数宣称已修复。

开发中仅定向回归，完成后执行一次集中后端/前端检查及隔离 Compose Playwright。
PR 复审仅以 P0/P1 阻塞；最终候选 Required Gate 成功后普通合并，不绕过保护规则。
当前及后续均不要求实机测试（包括公司 Windows），此状态不是“实机通过”。
Windows 自动 CI 保留。连续 RC、外部备份恢复、升级/回滚与迁移签署、独立安全审批、生产授权和人工签署
未因此豁免，`GA_READY=NO`。S56 RC 记录不自动代替 S60 或本轮冻结候选的版本级运行验收。
回滚使用普通 revert，无迁移或数据删除；隔离 Compose 停止时保留数据卷。
