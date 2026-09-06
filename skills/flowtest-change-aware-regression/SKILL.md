---
name: flowtest-change-aware-regression
description: "将 FlowTest Context/Knowledge 变化和受影响流程接入既有 Change Regression，生成受控维护提案。用于变更回归与维护建议，不创建第二套生命周期或自动批量应用 Patch。"
---

# FlowTest 变更感知回归

先读 [manifest.yaml](manifest.yaml)。本 Skill 使用原 Change Regression、AIChangeSet、Review 和 Preview，
不是新维护系统。固定一个授权项目及已有 `run_id`；若尚未创建 Run 或绑定 Context，交由用户在原
Change Regression 页面完成，不伪造 Git Diff、Impact ID 或以孤立提案冒充已经关联。

1. 用 `flowtest.inspect_change_regression` 读取 Run、Impact、计划、Context 绑定和 Proposal ID；再用
   `flowtest.inspect_change_impact` 查看结构化变更和当前测试缺口。不得把 Snapshot 内的提案状态当作
   当前审核状态，最终状态必须通过 `flowtest.inspect_flow_proposal` 重读。
2. 用 `flowtest.inspect_context_diff` 比较用户指定的固定前后修订；其 `request` 包含 `project_id`、
   `context_id`、`before_revision`、`after_revision`。只使用结构化、脱敏差异，不复制源码或原始数据行。
3. 用 `flowtest.inspect_affected_flows` 获取有界结果，分页最大 50。区分精确、Portable 与启发式关系；
   保留分页、未映射和 `analysis_complete=false` 诊断，不将启发式或用户确认提升成自动 Patch 权限。
4. 对有精确影响证据的目标导出最新 FlowSpec、检查固定目标 Revision，并调用 `flowtest.validate_flowspec`。
   Patch 仅限原服务支持的 binding/data/cleanup/contract_drift/oracle 范围。不得夹带版本策略迁移或弱化
   产品缺陷；Oracle 弱化需用户明确确认，不能自动填确认字段。
5. 调用 `flowtest.propose_maintenance`，`request` 为 `project_id`、`run_id`、`workflow_id`、`maintenance`
   和默认 `dry_run=true`。`maintenance` 包含同一 Context 前后修订、Run 对应 Impact、期望草稿版本、kind、
   proposed_spec 和 rationale。验证后在用户任务范围内传 `dry_run=false` 及顶层 `idempotency_key`，由服务
   原子创建并关联待审核提案；内容不变的重试保持原键。陈旧状态需重新分析，不盲目重试旧 Patch。
6. 交付 Proposal ID、Run ID、Diff Ref 和诊断，进入原 Visual Review。不得代为 Accept、Apply 或 Publish。
   仅当用户另行要求 Sandbox Preview 时，重读当前提案并要求 accepted、`applied=false`，确认非生产
   环境且取得绑定当前执行服务账号的新一次性批准，再调用 `flowtest.preview_flow_proposal`。

成功 Preview 不计正式 TestPlan 执行或 Release 放行；失败清理必须报告失败。后续固定版本发布、计划更新、
审核和正式执行由既有人工流程完成。需核对质量声明时读取 [references/evaluation.md](references/evaluation.md)。
