# FlowTest V6.0 S55 Sandbox Preview Beta

## 1. 阶段状态

H1 真实 Key Rotation 已由 PR #63 普通 Squash Merge且主线七项门禁成功。S55 从最新 Main 创建独立分支
`codex/v6-s55-sandbox-preview`。实现 PR #64 已完成 GitHub Codex 复审、最终一次完整门禁、
普通 Squash Merge 及 Merge 后 Main 七项验证，S55 Beta Exit 已闭环。

## 2. 执行与安全边界

- Preview 是现有 `WorkflowExecution` 的 `run_purpose=preview`，复用 Snapshot、Scheduler、Worker、Runner、
  Event、Checkpoint 和 Report，不存在第二套 Preview Engine。
- 只允许明确分类为 Test/Sandbox 的 Environment。Production 使用 `PRODUCTION_PREVIEW_FORBIDDEN` 硬拒绝；
  Staging 与 Unclassified 也不允许进入 Preview。
- Proposal 必须已人工接受、尚未应用且没有 Blocker；Context Revision 必须当前且未过期，目标 Workflow
  Draft Revision 不得 Stale。
- 一次性 Approval 绑定 Organization、Project、Change Set、Environment、执行 Actor、Proposal/Context
  Fingerprint、Budget 和过期时间。消费时使用数据库行锁；消费后任何新命令都返回 Replay 拒绝，同一
  Idempotency Key 只返回原执行。
- MCP 执行要求 `mcp:preview:execute`；服务账号必须有效、未撤销、属于相同 Organization，并由 Owner
  明确指定为 Approval Executor。
- Secret 只接受现有 Secret Reference 并在 Snapshot 阶段解析；外部目标继续通过项目 Outbound Policy，
  Evidence、Checkpoint、错误与审计沿用统一脱敏规则。
- Missing Cleanup、可跳过 Cleanup 的强制取消策略、Unsupported Node、Arbitrary Script、Write SQL、
  Cross-Tenant 和超预算均 Fail Closed。

## 3. 固定预算与 Evidence

默认且不可扩大的上限：

| 维度            | 上限 |
| --------------- | ---: |
| Nodes           |  100 |
| Requests        |   50 |
| Dataset Rows    |   20 |
| Parallelism     |    5 |
| Runtime Seconds |  600 |

主阶段和 Cleanup 共享实际 Request Budget；恢复执行从已持久化 Checkpoint 扣除既有请求尝试。Preview
Evidence 包含 Proposal/Context Fingerprint、Execution Snapshot、Binding Trace、Assert Result、Cleanup
Result、Budget Usage、Redactions、Trace ID 和 Approval ID。

## 4. 用户与 MCP 流程

Proposal Mode 仅显示 Test/Sandbox Environment。人工接受 Proposal 后，用户点击“一次性批准并运行
Sandbox Preview”，前端创建 Approval、提交幂等执行命令并轮询 Execution/Checkpoint；流程图展示 Live
Node Status，证据面板展示 Binding、Assert、Cleanup 和 Budget。应用/发布仍是独立人工动作，Preview
不会自动 Apply 或 Publish。

MCP 工具 `flowtest.preview_flow_proposal` 只能消费已为当前服务账号签发的一次性 Approval；它不能创建
Approval，也不能访问 Production。

## 5. 定向验证

- S55/S51 后端：`4 passed`。
- Proposal Mode 前端：`7 passed`；TypeScript、ESLint、Prettier 通过。
- MCP SDK 注册、GA Red Team 与 golden contract：`3 passed`。
- 受影响后端 20 个模块 mypy 通过。
- 隔离 PostgreSQL：`0049→0050→0049→0050`，表、列创建与删除均已核对，临时库已删除。

真实执行断言覆盖：Production 硬拒绝；Sandbox Approval 一次消费；同一 Idempotency Key 返回同一执行；
不同命令 Replay 被拒绝；Main 与 Cleanup 请求均成功；10 次请求预算记录 `used=2`、`remaining=8`；
Cleanup Report 与 Execution Snapshot 进入 Preview Evidence。

## 6. Beta Exit

| 条件                   | 当前状态     | 证据                                   |
| ---------------------- | ------------ | -------------------------------------- |
| Visual Review          | Pass（本地） | Proposal Mode 7 项定向测试             |
| Sandbox Preview        | Pass（本地） | S55 真实执行链路                       |
| Cleanup                | Pass（本地） | Required Cleanup 执行与 Evidence       |
| Production MCP Preview | 0（本地）    | 独立 403 硬拒绝                        |
| Approval Replay        | 0（本地）    | 一次消费与幂等回放测试                 |
| PR Review P0/P1        | Pass         | PR #64 最终复审无阻塞项                |
| 最终完整门禁           | Pass         | PR 精确 Head 与 Merge 后 Main 七项全绿 |

Beta Exit 已成立。H2 外部运行、长时 RC 与人工安全签署仍属于 GA 门槛，不由 S55 代替。

## 7. Remote Evidence

### PR #64 精确 Head

| Workflow                  |        Run ID | Conclusion |
| ------------------------- | ------------: | ---------- |
| Backend CI                | `33306781329` | success    |
| Frontend CI               | `33306781355` | success    |
| Security CI               | `33306781336` | success    |
| Compose Smoke Test        | `33306781338` | success    |
| Standalone Windows Bundle | `33306781348` | success    |
| V2 to V3 Upgrade CI       | `33306781349` | success    |
| Required Gate Controller  | `33306779840` | success    |

### Merge 后 Main Push

| Workflow                  |        Run ID | Conclusion |
| ------------------------- | ------------: | ---------- |
| Backend CI                | `33308150863` | success    |
| Frontend CI               | `33308150850` | success    |
| Security CI               | `33308150847` | success    |
| Compose Smoke Test        | `33308150834` | success    |
| Standalone Windows Bundle | `33308150815` | success    |
| V2 to V3 Upgrade CI       | `33308150821` | success    |
| Required Gate Controller  | `33308150818` | success    |

PR #64 使用普通 Squash Merge，未使用 Admin Merge、Ruleset Bypass、Force Push 或直接推送
Main。
