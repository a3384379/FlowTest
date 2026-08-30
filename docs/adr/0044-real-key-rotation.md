# ADR 0044：组织数据密钥真实轮换

## 状态

已接受，V6 H1 起执行。

## 背景

S47 只保存 Key Version 计划元数据，Apply/Rollback 会如实拒绝。V6 的 Context、Proposal 和 Preview
会继续增加组织范围内的敏感数据，因此不能在只切换元数据的状态下启动 Sandbox Preview。

## 决策

- `FLOWTEST_DATA_ENCRYPTION_KEY` 保留为默认版本，`FLOWTEST_DATA_ENCRYPTION_KEYRING` 通过 Secret Manager
  或部署环境提供额外稳定密钥引用。API 只接收引用和 fingerprint，不接收密钥材料。
- 新密文使用经认证的 `FTK1` 包络保存密钥引用；引用同时加入 AES-256-GCM AAD。旧版无包络密文仍使用
  默认密钥读取，避免破坏历史数据。
- 组织活动 Key Version 决定新写入使用的密钥引用。数据加密服务在写入前获取组织治理共享锁，
  Apply/Rollback 获取独占锁，阻止活动版本切换期间产生旧密钥新写入。
- Apply 在单一数据库事务内锁定受管行，解密旧值、用目标引用重加密、立即解密并常量时间比对，
  全部成功后才激活新版本。任一密文失败时整体回滚。
- Rollback 不只切换元数据；它使用上一版仍可用的密钥对同一组数据重加密和校验，再恢复活动版本。
- 当前注册表覆盖 Secret、本地 Credential、Import Preview、Workflow Execution Plan、Test Plan Webhook
  和 Notification Webhook。Vault Credential 只保存外部引用，不在本地重加密。
- 审计只记录版本、分类 migrated/verified 计数和密文摘要，不记录明文、密钥、nonce 或完整密文。
- Full、Compact 和 Standalone 共享密文格式与生命周期语义。Backup/Restore 和 Standalone→Compact
  传输只携带密文及其引用，密钥环始终通过独立安全渠道恢复。
- S55 新增的任何 Preview 密文必须注册进同一轮换表，并复用活动组织密钥解析器。

## 结果

Key Version 从“计划元数据”升级为真实数据生命周期。线上轮换需要同时保留新旧密钥，并可能在大组织事务期间
短暂阻塞相关加密写入；这是 V6.0 Core 为获得原子性和可证明回滚接受的取舍。分批/在线无停机轮换不在 V6.0 Core 范围。
`FTK1` 包络不被 H1 之前的应用识别；因此一旦产生新密文，数据库迁移会拒绝直接降级到旧应用，
运维必须保留当前版本或恢复升级前完整恢复点。

## 否决方案

- 只切换 `active_key_version` 或只更新 fingerprint。
- 把密钥材料通过组织 API 或数据库保存。
- 先提交部分重加密，再异步修复失败行。
- 在缺失上一版密钥时允许元数据回滚。
