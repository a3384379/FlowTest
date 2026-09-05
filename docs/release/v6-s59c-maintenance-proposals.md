# S59C Maintenance Proposal

## 范围与当前状态

- 基线：S59B PR #84 合并后全绿 main；分支 `codex/v6-s59c-maintenance-proposals`。
- 三项前置 P2 与维护提案实现共用一个阶段 PR；前置正确性修复与功能变更保留独立提交。
- 新维护 API、可信 Provenance、精确目标证据、共享 Patch 白名单、既有 Review/Preview/Apply 兼容，以及
  审核窗口来源展示已实现。详细边界见 [ADR 0051](../adr/0051-maintenance-proposals.md)。
- 不自动接受、应用或发布；启发式不授予 Patch 权限。S59D 的 Change Regression Snapshot v4/页面尚未开发。

## 验证记录

- 前置债务与相关模块定向回归：66 项通过；Maintenance/Repair/FlowSpec 相关定向回归已通过。
- 新增覆盖：重复请求只创建一个提案；项目/Context/目标隔离；敏感值和越界 Patch 在幂等 Claim 前拒绝；
  当前版本失效、失效 Context、启发式、伪造来源拒绝；统一列表及可视化元数据；人工接受前的 Apply/Preview
  阻断；接受后的 Preview 审批和 Apply；Apply 后 Preview 禁止。
- 后端集中门禁：Ruff Format / Ruff / mypy 通过，1097 passed / 4 skipped，覆盖率 91.04%。
- 前端集中门禁：Format / ESLint / TypeScript / Build 通过，232 项通过，分支覆盖率 80.17%。
- Playwright CLI 在隔离 Compose 项目 `flowtest-s59c` 验证：可信来源可见；人工接受前 Apply/Preview
  禁用；接受后单次 Preview 经真实 Worker 执行，Main 与 Cleanup 均 `passed`，审批已消费。
  初始无 Cleanup 夹具被既有安全规则正确拒绝，补齐夹具后通过，未放宽任何 Preview 门禁。
- 同一浏览器随后将提案 Apply 到草稿成功；无需原深链可通过既有列表重新发现维护提案。
- 本地浏览器证据：`output/playwright/s59c-preview-passed.png`（不纳入源码提交）。测试使用隔离 PostgreSQL
  Fixture、当前后端源码与本次前端构建，不修改既有业务数据，不运行实机或容量门禁。
- PR、独立复审、远程 Required Gate、普通合并与合并后 main 门禁尚未完成。

实机测试（含公司 Windows）不要求；自动化 Windows CI、Compose 和既有非实机验收策略保留。
