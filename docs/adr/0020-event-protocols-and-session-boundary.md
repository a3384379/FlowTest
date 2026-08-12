# ADR 0020：事件协议、消息 Schema 与会话边界

## 状态

已接受（S24）

## 背景

S24 在 Capability Runtime 中增加 Kafka Produce/Consume 与 WebSocket 会话节点。消息系统和长连接
与普通请求不同：消费可能无界、Offset 可能被意外提交、Schema Registry 会变化，WebSocket 活连接
也不能在 Worker 丢失后迁移。若这些差异被隐藏在通用字典或动态配置中，历史执行会漂移，并可能产生
消息丢失、无限等待、Secret 泄漏或恢复 Worker 写入旧会话等问题。

## 决策

1. `EventSource` 是项目级不可变版本，Kafka 固定 Bootstrap Servers 与可选 Schema Registry，
   WebSocket 固定 `ws/wss` URL；配置以 SHA-256 固定到 Workflow Snapshot。
2. Kafka 消息 Schema 复用不可变 `SchemaArtifact`，支持 Avro、JSON Schema 2020-12 与 Protobuf；
   可从兼容 Schema Registry Subject/Version 导入。Snapshot 固定 Schema ID、版本、哈希与规范内容，
   Worker 不在执行时回读 Registry。
3. Kafka 使用稳定的 `confluent-kafka` 客户端，不暴露 `AdminClient`。平台禁用 Topic 自动创建、
   自动提交和自动 Offset Store；Consume 最多 1000 条、300 秒。配置 Correlation 后命中即返回。
4. 单条消息解码前后均限制为 4 MB；Confluent Wire Format 的 Schema ID 必须与固定 Snapshot 一致。
   Header 进入结果前统一脱敏 Authorization、Cookie、Token 与 Secret 等字段。
5. WebSocket 提供 Connect、Send、Await、Close 与便捷 Exchange。Session Key 只存在于单次执行的
   `EventProtocolRunner`，所有等待都有消息数和时间上限；执行结束无条件关闭剩余会话。
6. WebSocket 会话不能迁移。连接丢失或后续节点找不到 Session 时返回 `SESSION_LOST`，使用者必须
   从 Connect 节点重试整段会话；Exchange 始终在 `finally` 中清理连接。
7. Kafka Bootstrap、Schema Registry 和 WebSocket URL 均复用项目 SSRF、DNS 与 CIDR 白名单。
   动态 Binding 只允许改变消息、Key 或 Correlation，不允许改变 Topic、Endpoint、Schema 或协议。
8. Compose 的 ARM64 验收使用固定 digest 的 Redpanda `v26.2.1`；CI 另以固定 digest 的 Apache
   Kafka `4.3.1` 验证同一客户端契约。两者都只作为测试目标，不向产品开放管理能力。
9. 回滚到 S23 会删除 S24 专属的 `EventSource` 与 Kafka `SchemaArtifact`，再恢复旧检查约束；V2/S23
   的 GraphQL、gRPC 及其他业务数据不受影响。执行 downgrade 前必须备份并进入维护窗口。

## 结果

- REST 输出可安全绑定到 Kafka 消息或 WebSocket Exchange，并和 GraphQL/gRPC 一起进入同一 DAG。
- 历史执行不受事件源、Registry 或消息 Schema 后续变化影响。
- Kafka 消费与 WebSocket Await 都有明确终止条件，Worker 结束后不遗留活连接。
- Kafka Admin、有界之外的消费、自动提交、WebSocket 会话迁移和用户脚本继续保持拒绝。
