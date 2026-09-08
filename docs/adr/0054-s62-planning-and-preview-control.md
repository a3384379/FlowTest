# ADR 0054：S62 分析准备、Test Plan 建议与 Preview 控制

状态：已实现，待本轮集中门禁与 PR 复审。

## 决策

S62 继续复用现有 `ChangeRegressionRun`、`ImpactRun`、`RegressionMaintenanceSnapshot`、
`AIChangeSet`、`AIChangeItem` 和 `WorkflowService`，不新增 Proposal、维护或 Preview 状态机。
新增 MCP 入口只负责准备分析、产生待审核的计划成员建议和请求 Graceful Cancel：

| MCP 工具 | Scope | 允许的副作用 | 明确禁止 |
| --- | --- | --- | --- |
| `flowtest.prepare_change_regression` | `mcp:regression:prepare` | 在固定 Context 前后版本上创建一次分析 Run 并绑定既有证据 | Accept、Execute、Release 放行、Coverage 豁免 |
| `flowtest.propose_test_plan_update` | `mcp:test-plan:propose` | 创建 `AIChangeSet` 草稿及一个 typed `test_plan_update` 项 | 直接修改已发布计划、Publish、Execute |
| `flowtest.cancel_preview` | `mcp:preview:execute` | 调用既有 `WorkflowService.request_cancel(force=false)` | 强制取消、生产取消、直接改写执行状态 |

分析入口在幂等 Claim 前完成组织/项目、变更来源、Release 引用和 Context Revision 校验；Claim 后再次
校验可变引用，并以一个事务持久化 Impact、Change Regression、Context 绑定、Stage、Audit 和完成回执。
计划建议的 Dry Run 不写入计划或 ChangeSet；正式建议仅写入 Draft，人工接受后才通过现有
`TestPlanService` 物化。建议快照中的未发布 Workflow/Case/Suite 依赖会返回明确标识，物化时固定版本
不可用则拒绝，避免将草稿依赖带入正式执行。

`AIChangeItem.item_type` 增加 `test_plan_update`，迁移 `20260908_0053` 同步 PostgreSQL 与
Standalone SQLite。Standalone 对已有 SQLite 表重建 CHECK 约束但保留所有行、索引和旧类型；迁移
降级会先删除该类型建议，再恢复旧约束。所有输出只包含结构化摘要、版本和深链，不包含凭据、原始响应、
数据库行或完整执行快照。

## 审核与执行边界

- `requires_human_review=true` 且 `automatic_publish/execute/release=false` 是固定契约。
- Test Plan 建议沿用现有 ChangeSet Review；用户接受后只更新草稿计划成员，不自动发布计划或排程。
- Preview 取消按执行 ID 和项目范围锁定，非 Preview 或跨项目执行返回不可枚举的错误；重复取消和已完成
  Preview 是幂等无操作，Cleanup 是否待完成会如实返回。
- 所有 MCP 工具仍使用服务账号 Scope 与组织边界；浏览器会话、用户 JWT、Docker/.env 凭据和内部 SQL
  不作为备用通道。

## 验证

定向测试覆盖严格 Schema、Dry Run 无副作用、Change Regression 幂等恢复、Test Plan 建议不改计划、
共享 ChangeSet 类型约束、MCP SDK 注册排序及 Standalone Transfer 基线 `20260908_0053`。真实宿主、真实
LLM、若依业务目标和人工审核不在隔离测试中伪造；最终集中 CI 由本阶段所有实现收口后统一执行。
