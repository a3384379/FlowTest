# ADR 0041：V6 数据分类、保留与导出

## 状态

已接受，所有 V6 数据变更适用。

## 背景

Context、Evidence、Plan、Proposal 与 Preview Evidence 会混合来源元数据、业务结构、PII、Secret 引用和审计。
若没有逐字段分类，Encryption、Rotation、Retention、Export 与 Support Bundle 容易出现不一致。

## 决策

每个新字段在 Schema/迁移评审中必须属于以下一类，并采用默认策略：

| 分类 | 静态保护 | 默认保留 | Export / Support Bundle | 展示与日志 |
| --- | --- | --- | --- | --- |
| Public Metadata | 常规存储 | 随父对象 | 允许 | 可展示 |
| Internal Metadata | 租户隔离 | 随父对象 | 授权导出；Support 最小化 | 日志仅 ID/计数 |
| Sensitive Business Metadata | 应用层加密或等效受控存储 | 最短业务期 | 显式授权且脱敏 | 默认遮蔽 |
| Secret | 仅引用；值加密且写入态 | 按 Secret 策略 | 禁止值导出 | 永不返回或记录值 |
| PII | 加密/Tokenize、租户隔离 | 明确 TTL | 授权且脱敏 | 默认遮蔽 |
| Execution Evidence | Artifact/DB 受控存储、完整性哈希 | 执行证据策略 | 授权、脱敏、带清单 | 有界摘要 |
| Audit | 防篡改、最小必要字段 | 合规策略 | 管理员受控 | 不含敏感值 |

- Evidence Envelope 和 Context Revision 必须记录 Redactions、Expiry 与 Source Revision。
- Secret Rotation 元数据与 Secret 值分离；API 边界值只写，Backup/Restore 保持密钥版本，不导出明文。
- Retention 删除派生内容时保留最小 Audit Tombstone，不保留被删敏感正文。
- Standalone→Compact Transfer 继续使用版本化 Manifest、分类、加密 Secret 和逐项完整性校验。
- Support Bundle 默认排除 Prompt、原始 Evidence 正文、Secret、PII 与请求/响应敏感体。

## 结果

所有新增 Migration/Contract/PR 必须填写分类矩阵、Retention、导出与回滚影响；缺失即不能合并。真实 Key
Rotation 仍需独立授权和证据，本文不宣称已完成轮换。

## 否决方案

- 用一个通用 JSON Blob 绕过字段分类。
- 将 Secret 值放入 Evidence、Plan、FlowSpec、日志或 Support Bundle。
- 只删主表而遗留可识别的 Artifact 或派生 Snapshot。
