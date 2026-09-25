# 新建原生控制流工作流提案

仅在用户明确要求新建带内联控制块的工作流时使用。先通过 `flowtest.list_projects`、`flowtest.inspect_project` 确定授权项目，再用 `flowtest.discover_control_capabilities` 核对控制能力、配置 schema、内联支持和边界。业务步骤只引用现有接口 ID 与固定版本；不要复制接口资产或自行推断业务字段。

调用 `flowtest.propose_control_workflow`，传入 `request` 和本提案唯一的 `idempotency_key`。`request` 包含 `project_id`、`name`、`description`、完整 `definition`。定义必须是 schema `4.0`，主流程至少有一个 `flow.control.*` 节点，包含其拥有的内联区域，并在 `run_policy.request_budget` 中给出主请求上限。Try/Finally 还需独立的 `cleanup_request_budget`。控制体默认串行，仅按用户实际需求增加并发、重试或异常分支。

服务端使用工作流发布时的权威校验检查整个定义。工具只创建待审核 ChangeSet；人工接受后才创建未发布的工作流草稿，仍不会运行。记录并报告 `proposal_id`、`item_id`、`proposed_fingerprint` 和 `review_url`，在审核页停止。不要调用人工接受、发布或执行入口，也不要把该提案送入 FlowSpec 的预览入口。
