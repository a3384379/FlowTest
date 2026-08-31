# ADR 0048：失败诊断与受限 Repair Proposal

## 状态

已接受，V6.1 S58 起执行。

## 背景

失败执行已经保存不可变 Workflow Snapshot、节点状态和脱敏 `NodeResult`，但用户仍需人工判断失败属于产品、
测试定义、数据、契约还是运行环境。S58 需要把结构化诊断连接到安全的测试侧修复闭环，同时避免把产品缺陷
错误地“修复”为更弱的测试，也不能为 Repair 建立第二套 Proposal、审批或 Preview 生命周期。

执行证据、错误消息、目标 URL、响应和用户填写的修复理由均视为不可信输入。修复必须继续遵守项目授权、
Context Revision、FlowSpec 验证、人工审核、一次性 Sandbox Preview Approval 和审计边界。

## 决策

- 只对终态失败执行生成 `flowtest-failure-diagnosis-v1`。诊断复用确定性的 Failure Triage 规则，只读取已持久化、
  脱敏的执行与节点证据；API 不返回原始 Secret、Cookie、Authorization Header 或未净化 Body。
- `PRODUCT_DEFECT` 必须 Fail Closed：只返回诊断和建议，不返回可用 Patch 类型，也不能创建测试修复 Proposal。
  环境、网络、认证、超时、上游服务、取消和未知失败同样不允许借 Cleanup 失败扩大为测试修改。
- Repair 采用显式类型和字段白名单：Binding 只改 Edge/Binding，Data 只改 Variable/Parameter，Cleanup 只接受
  FlowSpec v2 Cleanup/Run Policy，Contract Drift 只保留 Operation Identity 并更新版本、契约指纹和必要 Oracle，
  Oracle 只改 Assertion。跨类型变更、Schema 切换和空 Patch 一律拒绝。
- Oracle 或 Contract Drift 中的断言变化必须显式确认可能弱化 Oracle；确认只记录风险，不代替人工审核。
- 创建前按 `Project Edit → Failed Execution → Target Workflow/Revision → Context Revision → Sensitive Input →
  FlowSpec Validation → Patch Scope` 完成只读预检，之后才进入 Idempotency Claim 和持久化动作。无权限、过期
  Context、陈旧草稿、敏感理由或越界 Patch 不得先写入幂等记录或 Proposal。
- Repair Proposal 复用现有 FlowSpec `AIChangeSet`、Review、Accept、Preview Approval 和 Sandbox Preview。
  `source_ref` 使用 `repair://workflow-executions/{execution_id}`，Source Snapshot 记录诊断、Context 指纹、Patch
  类型、理由和 Oracle 风险，不复制原始运行证据。
- Web 从失败执行历史打开诊断；用户只能选择诊断允许的 Patch 类型和 Ready Context Revision。创建后进入现有
  Proposal Review；只有 Accepted、尚未 Apply 的 Proposal 才能申请新的、一次性 Sandbox Re-preview Approval。

## 结果

安全闭环固定为：

```text
Failed Execution
  → Redacted Diagnosis
  → Product Defect Guard / Typed Patch Boundary
  → Existing AIChangeSet Review
  → Fresh One-time Sandbox Approval
  → Re-preview
```

诊断不会自动改测试，Repair 不会自动 Accept、Apply、Publish 或在生产环境执行。历史执行和目标草稿发生变化时，
用户必须重新导出当前 FlowSpec、重新生成 Proposal 并重新审核。

## 否决方案

- 让 LLM 或规则直接修改工作流草稿、Oracle 或测试数据。
- 为 Repair 新建独立 Proposal 表、审批状态机或 Preview 通道。
- 将 Product Defect 自动归因为 Bad Test，或自动放宽断言以获得绿色结果。
- 接受任意 JSON Patch，再依靠人工审核发现越界字段。
- 复用已消费的 Preview Approval，或允许生产环境 Re-preview。
