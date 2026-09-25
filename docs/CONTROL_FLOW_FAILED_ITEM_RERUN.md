# 失败轮次派生重跑

适用于已结束的正式工作流运行中，顶层内联 ForEach 的失败轮次。入口在流程编排的执行历史或最近运行面板：打开原运行报告，选择“派生重跑失败项”，指定失败的 `input_index`。

派生运行创建新的执行 ID，记录 `derived_from_execution_id`、`rerun_loop_node_id` 和 `rerun_input_indices`。原运行、原报告和发布版本保持不变。新运行使用原运行保存的加密计划、冻结集合和成功的上游 checkpoint，只执行选中的失败轮次；原流程的下游节点不会在派生运行中调度。请从新运行报告核对本次结果，不要把它与原运行合并为一份“已通过”报告。

如果选中轮次已成功创建或提交过资源，系统复用该步骤的输出，不默认重发写请求。创建派生运行前需确认外部资源仍有效，并填写查证依据。失败的写步骤或结果未知的写步骤默认禁止重试；只有人工查证并明确选择“查证后允许重试失败写操作”后才会重试。资源已过期时暂停重跑，先重新准备数据。

API 使用 `POST /api/v1/projects/{project_id}/workflow-executions/{execution_id}/failed-items/rerun`，建议提供 `Idempotency-Key`。请求示例：

```json
{
  "loop_node_id": "loop",
  "input_indices": [1],
  "upstream_resource_status": "confirmed_valid",
  "write_retry_strategy": "reject",
  "verification_note": "已核对本次创建的资源仍有效"
}
```

`input_indices` 只接受原报告中明确失败的原始索引。`upstream_resource_status` 可为 `unverified`、`confirmed_valid`、`expired`；存在需复用的写操作输出时必须选择 `confirmed_valid`。`write_retry_strategy` 可为 `reject` 或 `verified_safe_to_retry`。确认外部状态时必须填写至少 8 字的 `verification_note`。接口返回新执行记录；运行结果通过现有执行详情查询。

当前不支持流程级 cleanup、嵌套控制、数据集批量运行或从派生运行再次派生；服务会明确拒绝这些情况。大量轮次的服务端按需加载和完整断点调试仍在开发中。
