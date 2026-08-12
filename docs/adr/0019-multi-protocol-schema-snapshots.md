# ADR 0019：多协议 Schema、执行边界与 Snapshot

## 状态

已接受（S23）

## 背景

S23 在既有 REST Workflow 上增加 GraphQL Query/Mutation 与 gRPC Unary/Server Streaming。协议
Schema 会持续演进，而历史 Workflow 必须继续使用发布时的结构；调试目标和 Reflection 地址又属于
不可信网络输入。若执行时重新拉取 Schema/Descriptor，历史结果会漂移，也会把 DNS 重绑定、超限流
和 Credential 泄漏风险带入 Worker。

## 决策

1. `SchemaArtifact` 是项目内不可变版本，保存协议、来源格式、规范化内容、原始来源、结构摘要和
   SHA-256。相同项目/协议/内容按哈希拒绝重复导入；名称可产生递增版本。
2. GraphQL 接受 SDL 与 Introspection JSON；发布和执行前均使用固定 Schema 校验 Operation，拒绝
   Subscription、递归 Fragment、超过 20 层或 1000 字段的 Operation，Schema/响应上限为 2 MB。
3. gRPC 接受受限 Proto、Protoset 与 Server Reflection。Proto 只从导入包和平台内置 well-known
   types 解析，拒绝绝对路径、目录穿越、缺失导入和超过 50 个文件。Reflection 先经过项目域名、DNS
   与私网 CIDR 策略，返回内容再执行同一 Descriptor 上限校验。
4. V3 仅支持 Unary 与 Server Streaming；拒绝 Client/Bidi Streaming。单消息上限 4 MB，单流上限
   1000 条、50 MB 和 300 秒。Metadata 禁止二进制键及换行注入。
5. TLS 默认使用系统信任根；mTLS 材料以 `grpc_mtls` Credential 保存，API 只返回元数据。Credential
   固定 Host/Port，执行时目标不匹配即拒绝；私钥和证书只存在于加密执行计划，不进入公开 Snapshot。
6. `graphql.request@3.0.0` 与 `grpc.call@3.0.0` 使用 Capability 配置和受限 `bindings`。GraphQL 只允许
   写入 `variables.*`，gRPC 只允许写入 `request.*`；表达式由既有安全 JMESPath 引擎解析，不能修改
   Endpoint、TLS、Credential 或方法。
7. Workflow 发布固定 Schema ID、版本与哈希；执行计划额外保存规范化 Schema/Descriptor 字节和所需
   加密 Credential。Worker 不回读最新资产，历史 Execution 因而不受后续导入影响。
8. `MULTI_PROTOCOL` Feature Flag 默认关闭；关闭时资产仍可导入和审阅，但调试、发布和执行协议节点
   均被拒绝。V2 节点和 `/api/v1` 现有资源保持兼容。

## 结果

- REST、GraphQL 和 gRPC 节点可以在同一 DAG 中并行运行并进行可解释的结构化数据绑定。
- 协议结构、Credential 与目标网络分别经过版本、加密和 SSRF 边界控制。
- Reflection、调试与 Workflow 共用同一验证模型，避免工作台成功而 Worker 行为不同。
- GraphQL Subscription 和 gRPC Client/Bidi Streaming 保持为明确的后续范围，不以半实现方式开放。
