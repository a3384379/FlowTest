# ADR 0033：外部 LLM 编排边界

## 状态

已接受，S48 起生效。

## 背景

V6.0 Core 需要让外部 LLM 汇集 Code MCP、Database MCP 与 FlowTest MCP 的授权证据，生成可审核的
集成测试草稿。FlowTest 已有确定性的 FlowSpec、AIChangeSet、执行快照和权限边界；若服务端再内置
Provider SDK、Prompt 或主动连接任意 MCP，会形成第二套编排平面，并扩大凭据和提示注入风险。

## 决策

- 外部 LLM 是编排者；FlowTest Server 不主动发现或连接第三方 MCP，也不托管模型会话。
- FlowTest 只通过版本化 HTTP/MCP 应用接口接收有界 Typed Evidence、Plan 与 Proposal 命令。
- 领域转换、校验、编译、Fingerprint 和 Diff 必须确定性执行，不访问模型、网络或 Secret 明文。
- LLM 名称、Provider 名称、Prompt、展示文案和会话状态不进入 FlowSpec 语义 Fingerprint。
- 外部返回内容一律视为不可信输入；代码注释、数据库 Comment 和文档指令不获得控制语义。
- 认证、Tenant、Scope、Idempotency、Expected Revision、审核与审计继续由 FlowTest 执行。

## 结果

V6.0 不新增模型 Provider 表、Prompt 运行记录或 Server 侧 Agent Runtime。模型可替换而不改变可执行语义，
失去外部 LLM 时，已有导入、审核与执行能力仍可独立工作。

## 否决方案

- FlowTest Server 主动连接任意 MCP 或保存第三方 MCP 凭据。
- 让 LLM 直接创建、发布、生产执行或删除 Workflow。
- 将 Prompt/Provider 信息混入可执行 Fingerprint。
