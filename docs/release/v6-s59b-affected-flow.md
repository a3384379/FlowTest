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
- PR、远程门禁、Compose Playwright 与合并尚未完成，不提前标记成功。

实机测试（含公司 Windows）按用户要求不再要求；Windows 自动化 Bundle、CI 和 Compose 保留。
