# S59B Affected Flow

## 基线与交付

从 S59A PR #83 合并后全绿 main 开始，分支 `codex/v6-s59b-affected-flow`。

- 版本化只读响应 `flowtest-affected-flows-v1`，显式比较 Context 历史版本并查询当前项目流程草稿。
- 复用 S45 Operation Identity 与 Impact Workflow Selection，区分实例、Portable、路由候选和显式资产证据。
- 知识关系按版本独立遍历，保留删除事实；启发式、多值冲突、缺失版本与分页不完整均 Fail Closed。
- 提供 Golden、领域/API 定向回归；不创建/接受/应用 Proposal，不改变 Context 或 Workflow Revision。

设计及未覆盖范围见 [ADR 0050](../adr/0050-affected-flow-selection.md)。本阶段只交付后端查询能力，
不是 S59 全阶段完成。后续 S59C Maintenance Proposal → S59D 既有 Change Regression 集成。

## 验收

本地集中验收已完成：

- Backend：Ruff Format / Ruff Check / Mypy 全部通过；1071 passed / 4 skipped，覆盖率 91.01%。
- 新增领域与 API 回归连同 Context Inspector / Change Regression 定向回归：49 项全部通过。
- Frontend：Format / Lint / Build 全部通过；230 项测试通过，分支覆盖率 80.01%。
- PR #84 已普通 Squash 合并；最终 PR Head 的 Backend、Standalone Windows、Upgrade、Security、
  Compose 与 Required Gate 均成功。合并后 main 同六项工作流全部成功，Controller 为 `33960652153`。
- 最终复审 P0=0、P1=0，接受 2 项 P2：明确 Kafka `consumes` 关系缺失、请求级总分析预算缺失。
  接受和关闭线程不代表修复；两项在 S59C 分支收口并增加回归。
- PR 最终 Head：`bd986ba9e3a9ac92b76e733099f328364613ce5d`；Merge / S59C 基线：
  `6264bb83fe6701fdc4599192215280d2ed1a50b0`。合并后证据见 PR #84 评论 `5551278331`。

实机测试（含公司 Windows）按用户要求不再要求；Windows 自动化 Bundle、CI 和 Compose 保留。
