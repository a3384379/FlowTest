# ADR 0035：External Evidence Envelope

## 状态

已接受，S49 实现。

## 背景

外部 LLM 和第三方 MCP 可接触源码与数据库元数据，但 FlowTest 不应接收无界原始仓库、数据库行或可执行
内容。证据还必须有可验证 Revision、明确语义角色和安全降级路径。

## 决策

- 接收契约版本为 `flowtest-external-evidence-v1`，内容由 Provider Identity、Source Revision、Subject、
  Typed Findings、Redactions 和 Warnings 组成，所有稳定对象 `extra=forbid`。
- 每个 Finding 必须声明语义角色、确定性、置信度、来源引用和语义 Fingerprint；无 Revision 来源拒绝。
- 设置条目数、字符串、嵌套深度和总字节预算；原始代码、数据库行和二进制仅允许受控摘要或引用。
- Bearer、Cookie、Password、API Key、Connection String、PEM、Secret 明文和未脱敏 PII 拒绝入库。
- Prompt Instruction 字段没有契约位置；代码注释、接口说明和数据库 Comment 只作为不可信文本证据。
- Tenant/Project/Subject 引用必须在授权边界内；未知 Provider 不获得额外信任。
- Normalize、Redact、Validate 后才计算 Fingerprint；失败使用标准错误信封和 Trace ID，日志只记录路径与原因。

## 结果

FlowTest 能接收不同语言和数据库工具产生的可移植事实，同时不执行被分析代码，也不把外部文本提升为
控制指令。V6.1 的内置 Provider 必须输出同一 Envelope。

## 否决方案

- 上传完整仓库或数据库导出作为 Evidence Item。
- 保存无法定位到 Source Revision 的“当前事实”。
- 为每个 Provider 定义互不兼容的持久化结构。
