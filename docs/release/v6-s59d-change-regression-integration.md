# S59D：接入既有 Change Regression

状态：实现与定向验证中，尚未完成阶段验收或合并。

## 范围与兼容

在 S45 的 ChangeRegressionRun.selection_summary 内增加 `context_maintenance`，其类型为
`s47.4-change-regression-v4`。包含固定 Context/Knowledge Diff 引用、修订 ID 与真实指纹、受影响流程、
分析范围/诊断、Maintenance Proposal ID、人工审核、正式回归要求。已有 Missing Test AIChangeSet 同步 v4
扩展；没有 AIChangeSet 的 Run 也可接入。不重写历史记录，不创建空 AIChangeSet，不扩建表或状态机。

Context-only 创建不在本阶段：仍需真实 Git / Schema 来源，不伪造 Git Diff。绑定操作仅限 review_required，
且后版本必须是当前 Ready Context。已有提案绑定后不允许更换来源，应为新变更创建新的回归链路。

## 受控操作

- `PUT .../change-regressions/{run_id}/context-maintenance`：固定前后版本；分析一次最多扫描 100 个流程，
  沿用 S59B 节点/身份/比较预算。未覆盖项与截断保留，不能宣称分析完整。
- `POST .../context-maintenance/workflows/{workflow_id}/proposals`：复用 S59C prepare/persist 和 Patch 白名单。
  项目授权和来源校验在幂等 Claim 前；Claim 后重新加锁校验；AIChangeSet、关联快照、Stage、Audit 和完成
  Claim 一次提交。失败全部回滚，不留下孤立提案。
- `POST .../context-maintenance/proposals`：显式关联已存在提案，独立用户动作。校验服务端来源标识、项目、
  Impact、Context 前后 ID/指纹与受影响 Workflow；不通过 URI 猜测身份。重复关联不新增 Stage。
- `POST .../context-maintenance/review`：人工说明和未覆盖项显式确认；不自动 Accept / Apply / Publish。
- `POST .../context-maintenance/plan-workflows`：显式加入/更新已发布的受影响 Workflow 固定版本；
  校验目标属于本次影响证据且版本匹配当前草稿，复用 TestPlan Service，保留已有运行参数与重试配置。
  计划更新、维护审核失效、Stage 与 Audit 一次提交，失败全部回滚。不发布或执行任何流程。

前端扩展原 Change Regression 页面。精确非启发式证据可进入人工 Patch 表单，后端仍执行完整复核。
审核链接打开原 Flow Proposal 窗口，不复制 Review/Preview/Apply 生命周期。前端不提交任何 CI 成功标志。

## 审核与覆盖规则

关联提案 pending 或 accepted-but-unapplied 会阻止维护证据审核；rejected 或 accepted-and-applied 可继续。
拒绝提案不是豁免测试要求，所有已知受影响流程仍需回归。未绑定维护证据的历史链路维持原有规则。

维护审核要求受影响流程当前草稿已发布，并由 TestPlan 直接或经 Case/Suite 引用匹配的固定 WorkflowVersion。
审核冻结版本 ID、版本号、指纹、草稿 revision；批准时检查 Context 仍有效、提案状态未变、固定版本未失配。
批准后禁止维护扩展修改。执行前检查计划仍包含这些版本，Release 必须有这些版本的真实 standard 成功执行；
Preview、仅 Apply 草稿、仅声称计划 passed 均不算覆盖。

原 Current TestPlan Gap、Missing Test Review、正式执行失败与 Release Policy 门禁全部保留。
不完整分析的人工确认只表示补充检查责任已被明确接受，不改变 analysis_complete，也不豁免已知流程或语义缺口。
成功 Release Evidence 保存固定 v4 快照与可信 TestPlanRun/ReleaseDecision 引用；已有 ReleaseDecision 重读
不重新获取最新 Context、不重解释历史证据。

## 验证计划

- v3 / 无 Missing Test、选择操作保持 v4、锁后刷新 ORM 缓存。
- 无权用户、跨项目、来源伪造、Impact/Context/版本/Workflow 错配、过期与未发布草稿。
- 原子失败注入和同键重试、重复关联、pending 阻断、诊断显式确认。
- 固定版本计划覆盖、正式执行证据、Release 幂等、Preview 不计覆盖、终态不可修改。
- 前端空态/诊断/固定证据/审核深链/人工 Patch 与现有 S45 页面回归。
- 稳定后一次集中 Backend / Frontend 门禁、隔离 Compose Playwright，再 PR 复审与远程 Required Gate。

不执行实机或公司 Windows 验收，保留自动 Windows CI；不重复容量门禁，不改变 GA 的其他授权要求。

## 当前候选验证

- 后端集中门禁：Format / Ruff / mypy 通过，1128 passed / 4 skipped，覆盖率 91.06%。
- 前端集中门禁：Format / ESLint / TypeScript / Build 通过，237 项通过，分支覆盖率 80.28%。
- 随后仅新增 Viewer 授权和 v3/v4 操作选择契约断言；15 项 S59D 定向回归通过，生产代码未变化。
- Compose 真实浏览器验收进行中；PR 复审与远程 Required Gate 尚未完成。

## Compose 发现的用户路径修复

- 真实浏览器确认：仅 Apply 草稿会被审核门禁正确阻断。但旧系统没有通用的计划版本更新入口，
  因此补充上述显式 plan-workflows 操作，复用已有 TestPlan 校验和持久化逻辑，不放宽门禁。
- 新增失败回归覆盖入口缺失、更新与证据提交原子性、参数保留，以及前端独立表单字段 ID。
- 修复后后端集中门禁全绿：1132 passed / 4 skipped，覆盖率 91.06%；前端 238 项通过，
  分支覆盖率 80.30%，格式、Lint、类型和 Build 全绿。S59D 定向 16 项及相关旧链路/Tasking API 验证通过。

## 最终验收闭环（随 S60A 回填）

- PR #86 最终候选 `bd9f7cd696d1be9f28fb753d10e5755e718ff52a` 正常 squash 合并；
  main 为 `ac96f139ea2d1b75c202e2cab112fc4e94ec8eac`。
- 最终 PR 候选及 main 的 Backend、Frontend、Security、Compose、Standalone Windows、Upgrade 和
  Required Gate Controller 七项工作流均 Success，提交上的受信 Required Gate 为 success。
- Main Controller：[33973942413](https://github.com/a3384379/FlowTest/actions/runs/33973942413)。
- 真实 Compose 正向 Release 通过，原未映射 Git 负向 Release 保持阻断；专用测试栈已停止。
- 复审 P0=0、P1=0；保留 1 项已接受、未修复的审核记录事务顺序 P2，以 PR 原复审为准。
  不把线程结束视为代码修复。S59D 已完成开发及验收，可以从全绿 main 启动 S60。
